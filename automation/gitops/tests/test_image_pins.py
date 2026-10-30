import importlib.util
import json
import re
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('image_pins', ROOT / 'image_pins.py')
image_pins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image_pins)
LOCAL_STREAMS = {
    'image-registry.openshift-image-registry.svc:5000/openshift/tools:latest',
    'image-registry.openshift-image-registry.svc:5000/redhat-ods-applications/s2i-generic-data-science-notebook:2024.2',
}


def images(value):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'image' and isinstance(item, str):
                found.append(item)
            if value.get('name') in ('INGESTION_PIPELINE_IMAGE', 'JUPYTER_IMAGE', 'SERVING_RUNTIME_IMAGE') and key == 'value' and isinstance(item, str):
                found.append(item)
            found.extend(images(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(images(item))
    return found


class ImagePinTests(unittest.TestCase):
    def test_deployment_profiles_render_reviewed_digests(self):
        profiles = (
            ('rag', ROOT / 'tenant/rag', ['--set', 'llm-service.enabled=false'], LOCAL_STREAMS),
            ('self-service-agent', ROOT / 'tenant/it-selfsvc/chart', ['-f', str(ROOT / 'tenant/it-selfsvc/chart/values-test.yaml'), '-f', str(ROOT / 'tenant/it-selfsvc/chart/values-demo.yaml')], set()),
            ('ppe', ROOT / 'tenant/multimodal/chart', ['--set', 's3Credentials.accessKeyId=access', '--set', 's3Credentials.secretAccessKey=secret', '--set', 's3Credentials.uiUsername=user', '--set', 's3Credentials.uiPassword=password', '--set', 'modelServing.runtimeType=openvino'], set()),
            ('ppe-gpu', ROOT / 'tenant/multimodal/chart', ['--set', 's3Credentials.accessKeyId=access', '--set', 's3Credentials.secretAccessKey=secret', '--set', 's3Credentials.uiUsername=user', '--set', 's3Credentials.uiPassword=password', '--set', 'modelServing.runtimeType=kserve'], set()),
            ('it-zammad', ROOT / 'tenant/it-selfsvc/chart', ['--set', 'ticketingZammad.enabled=true'], set()),
            ('it-observability', ROOT / 'tenant/it-selfsvc/chart', ['--set', 'langfuse.enabled=true', '--set-string', 'langfuse.minio.image=registry.invalid/minio@sha256:' + 'a' * 64, '--set-string', 'langfuse.minio.clientImage=registry.invalid/mc@sha256:' + 'b' * 64], set()),
            ('rag-gpu', ROOT / 'tenant/rag', ['--set', 'global.models.demo.enabled=true', '--set', 'global.models.demo.id=example', '--set', 'global.models.demo.device=gpu'], LOCAL_STREAMS),
            ('nemo', ROOT / 'tenant/it-selfsvc/chart/nemo-guardrails', ['--set', 'jailbreakDetect.enabled=true'], set()),
        )
        for name, chart, args, exceptions in profiles:
            with self.subTest(profile=name):
                output = subprocess.check_output(['helm', 'template', name, str(chart), *args], text=True)
                all_images = images(list(yaml.safe_load_all(output)))
                self.assertTrue(all_images)
                missing = {image for image in all_images if not re.search(r'@sha256:[a-f0-9]{64}$', image)}
                self.assertEqual(missing, exceptions)

    def test_unreviewed_image_fails_render(self):
        p = subprocess.run(['helm', 'template', 'rag', str(ROOT / 'tenant/rag'), '--set', 'image.tag=unreviewed'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('has no reviewed digest', p.stderr)

    def test_unavailable_optional_minio_images_fail_closed(self):
        p = subprocess.run(['helm', 'template', 'it', str(ROOT / 'tenant/it-selfsvc/chart'), '--set', 'langfuse.enabled=true'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('quay.io/minio/', p.stderr)
        self.assertIn('has no reviewed digest', p.stderr)

    def test_helpers_match_lock_and_apply_is_repeatable(self):
        for name in ('rag', 'it-selfsvc/chart', 'multimodal/chart'):
            helper = ROOT / 'tenant' / name / 'templates/_rh1-image-pins.tpl'
            self.assertEqual(helper.read_text(), image_pins.helper())
        lock = json.loads(image_pins.LOCK.read_text())
        self.assertTrue(lock)
        self.assertTrue(all(re.fullmatch(r'sha256:[a-f0-9]{64}', digest) for digest in lock.values()))
        raw = b'containers:\n  - image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"\n'
        patched = image_pins.patch_template(raw)
        self.assertEqual(image_pins.patch_template(patched), patched)


if __name__ == '__main__':
    unittest.main()
