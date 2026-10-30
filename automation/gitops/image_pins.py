"""Apply the reviewed image digest lock to vendored Helm templates."""
import argparse
import gzip
import io
import json
import re
import tarfile
from pathlib import Path

LOCK = Path(__file__).with_name("image-lock.json")
MARKER = 'include "rh1.pinnedImage"'
IMAGE_LINE = re.compile(r'^([ \t]*(?:-[ \t]+)?image[ \t]*:[ \t]*)(.*?)([ \t]*)$', re.MULTILINE)
EXPRESSION = re.compile(r'{{-?\s*(.*?)\s*-?}}')
IMAGE_ENV = re.compile(r'^([ \t]*-[ \t]+name:[ \t]+(?:INGESTION_PIPELINE_IMAGE|JUPYTER_IMAGE|SERVING_RUNTIME_IMAGE)[ \t]*\n)([ \t]*value[ \t]*:[ \t]*)(.*?)([ \t]*)$', re.MULTILINE)


def image_expression(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    parts, expressions, offset = [], [], 0
    for match in EXPRESSION.finditer(value):
        parts.append(value[offset:match.start()].replace('%', '%%'))
        expression = re.sub(r'\s*\|\s*quote\s*$', '', match.group(1).strip())
        if expression.startswith('template '):
            expression = 'include ' + expression[len('template '):]
        parts.append('%v')
        expressions.append('(' + expression + ')')
        offset = match.end()
    parts.append(value[offset:].replace('%', '%%'))
    if '{{' in ''.join(parts) or '}}' in ''.join(parts):
        raise ValueError('Unsupported multiline Helm image expression')
    fmt = json.dumps(''.join(parts))
    return '(printf ' + fmt + (' ' + ' '.join(expressions) if expressions else '') + ')'


def patch_template(data):
    text = data.decode('utf-8')
    def replace(match):
        prefix, value, trailing = match.groups()
        if MARKER in value or not value.strip() or value.lstrip().startswith('#'):
            return match.group(0)
        return prefix + '{{ include "rh1.pinnedImage" ' + image_expression(value) + ' | quote }}' + trailing
    text = IMAGE_LINE.sub(replace, text)
    def replace_env(match):
        header, prefix, value, trailing = match.groups()
        if MARKER in value or not value.strip():
            return match.group(0)
        return header + prefix + '{{ include "rh1.pinnedImage" ' + image_expression(value) + ' | quote }}' + trailing
    return IMAGE_ENV.sub(replace_env, text).encode('utf-8')


def patch_archive(data, depth=0):
    if depth > 5:
        raise ValueError('Helm dependency nesting is too deep')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as source:
        entries = [(item, source.extractfile(item).read() if item.isfile() else None) for item in source.getmembers()]
    changed = False
    for i, (item, content) in enumerate(entries):
        if content is None:
            continue
        updated = content
        if item.name.endswith(('.tgz', '.tar.gz')):
            updated = patch_archive(content, depth + 1)
        elif '/templates/' in item.name and item.name.endswith(('.yaml', '.yml', '.tpl')):
            updated = patch_template(content)
        if updated != content:
            item.size = len(updated)
            entries[i] = (item, updated)
            changed = True
    if not changed:
        return data
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w') as archive:
            for item, content in entries:
                item.mtime = 0
                item.pax_headers.pop('mtime', None)
                archive.addfile(item, io.BytesIO(content) if content is not None else None)
    return output.getvalue()


def helper():
    lock = json.loads(LOCK.read_text())
    for name, digest in lock.items():
        if not isinstance(name, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError('Invalid image lock entry')
    entries = ' '.join(json.dumps(k) + ' ' + json.dumps(v) for k, v in sorted(lock.items()))
    return ('{{- define "rh1.pinnedImage" -}}\n'
            '{{- $image := . -}}\n'
            '{{- $pins := dict ' + entries + ' -}}\n'
            '{{- $digest := get $pins $image -}}\n'
            '{{- if regexMatch "@sha256:[a-f0-9]{64}$" $image -}}{{- $image -}}\n'
            '{{- else if $digest -}}\n'
            '{{- printf "%s@%s" $image $digest -}}\n'
            '{{- else if or (eq $image "image-registry.openshift-image-registry.svc:5000/openshift/tools:latest") (eq $image "image-registry.openshift-image-registry.svc:5000/redhat-ods-applications/s2i-generic-data-science-notebook:2024.2") -}}{{- $image -}}\n'
            '{{- else -}}{{- fail (printf "Image %s has no reviewed digest; set an image with @sha256 or update image-lock.json" $image) -}}{{- end -}}\n'
            '{{- end -}}\n')


def apply(chart):
    chart = Path(chart)
    if not chart.is_dir():
        raise ValueError(f'Chart directory not found: {chart}')
    for path in chart.rglob('*'):
        if not path.is_file():
            continue
        if path.suffix == '.tgz':
            original = path.read_bytes()
            patched = patch_archive(original)
        elif 'templates' in path.parts and path.suffix in ('.yaml', '.yml', '.tpl') and path.name != '_rh1-image-pins.tpl':
            original = path.read_bytes()
            patched = patch_template(original)
        else:
            continue
        if original != patched:
            path.write_bytes(patched)
    roots = {chart}
    roots.update(p.parent for p in chart.rglob('Chart.yaml'))
    for root in roots:
        templates = root / 'templates'
        if templates.is_dir():
            (templates / '_rh1-image-pins.tpl').write_text(helper())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chart', action='append', type=Path, help='chart to patch; defaults to all three tenant charts')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / 'tenant'
    for chart in args.chart or [root / 'rag', root / 'it-selfsvc/chart', root / 'multimodal/chart']:
        apply(chart)
        print('Applied image lock:', chart)


if __name__ == '__main__':
    main()
