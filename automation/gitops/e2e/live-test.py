#!/usr/bin/env python3
"""Validate a deployed RAG instance, including retrieval and browser chat."""
import argparse
import base64
import getpass
import json
import subprocess
import sys
import urllib.request

REPO = "https://github.com/rhpds/red-hat-1-quickstarts"
QUESTION = "What does the employee handbook say about vacation time?"

BACKEND_TEST = r'''
import json, sys, urllib.request
model, collection, question = sys.argv[1:]
base = "http://localhost:8321/v1"
def get(path):
    return json.load(urllib.request.urlopen(base + path, timeout=20))
def post(path, data):
    req = urllib.request.Request(base + path, data=json.dumps(data).encode(), headers={"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(req, timeout=120))
models = get("/models")["data"]
if model not in [m["id"] for m in models]:
    raise RuntimeError("The requested inference model is not registered")
stores = [s for s in get("/vector_stores")["data"] if s["name"] == collection]
if len(stores) != 1 or stores[0]["file_counts"]["completed"] < 1:
    raise RuntimeError("The requested document collection is missing or empty")
results = post("/vector_stores/" + stores[0]["id"] + "/search", {"query": question, "max_num_results": 3})["data"]
context = "\n".join(c.get("text", "") for result in results for c in result.get("content", []) if isinstance(c, dict))
if not context:
    raise RuntimeError("Retrieval returned no document text")
answer = post("/chat/completions", {"model": model, "messages": [
    {"role": "system", "content": "Answer only from the supplied context."},
    {"role": "user", "content": "Context:\n" + context + "\nQuestion: " + question}], "max_tokens": 2048})
content = answer["choices"][0]["message"].get("content")
if not content or not content.strip():
    raise RuntimeError("Model returned an empty answer")
print(json.dumps({"chunks": len(results), "answer": content}))
'''


def command(args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def validate_gitops_app(app, name, path, namespace=None, expected_revision=None):
    source = app["spec"]["source"]
    if source["repoURL"].rstrip("/").removesuffix(".git") != REPO or source["path"].rstrip("/") != path:
        raise ValueError(f"{name} does not point to the expected repository and path")
    if app.get("status", {}).get("sync", {}).get("status") != "Synced" or app.get("status", {}).get("health", {}).get("status") != "Healthy":
        raise ValueError(f"{name} is not Healthy and Synced")
    if expected_revision and app["status"]["sync"].get("revision") != expected_revision:
        raise ValueError(f"{name} is not synced to the expected commit")
    if namespace and app["spec"]["destination"]["namespace"] != namespace:
        raise ValueError("RAG Application destination does not match the test namespace")
    return source


def validate_ingestion(workflows, names):
    for name in names:
        matches = [w for w in workflows if w.get("metadata", {}).get("annotations", {}).get("pipelines.kubeflow.org/run_name") == name + "-run"]
        if not matches:
            raise ValueError(f"No ingestion run found for {name}")
        latest = max(matches, key=lambda w: w["metadata"]["creationTimestamp"])
        if latest.get("status", {}).get("phase") != "Succeeded":
            raise ValueError(f"Latest ingestion run for {name} is {latest.get('status', {}).get('phase', 'unknown')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--context", help="oc context; defaults to current context")
    parser.add_argument("--confirm-cluster", help="exact API URL approved for this test (for noninteractive runs)")
    parser.add_argument("--model", help="registered Llama Stack model ID; prompted if omitted")
    parser.add_argument("--inference-url", help="OpenAI-compatible model API URL; prompted if omitted")
    parser.add_argument("--inference-model", help="upstream provider model ID; defaults to model ID without provider prefix")
    parser.add_argument("--inference-secret", help="namespace Secret and key as NAME:KEY; otherwise prompt for API key")
    parser.add_argument("--collection", default="hr-vector-db-v1-0")
    parser.add_argument("--pipeline-name", action="append", help="expected ingestion run name without -run; repeat for multiple pipelines")
    parser.add_argument("--question", default=QUESTION)
    parser.add_argument("--route", default="rag-test")
    parser.add_argument("--llamastack-deployment", default="llamastack")
    parser.add_argument("--browser-channel", help="Playwright browser channel, for example chrome")
    parser.add_argument("--insecure-ui", action="store_true", help="allow an untrusted UI certificate")
    parser.add_argument("--show-answer", action="store_true", help="print the browser's answer")
    parser.add_argument("--helm-deployment", action="store_true", help="test an existing Helm deployment without claiming GitOps validation")
    parser.add_argument("--infra-app", default="lb2142-ai-quickstarts")
    parser.add_argument("--tenant-app", help="tenant bootstrap Argo CD Application name")
    parser.add_argument("--rag-app", help="child RAG Argo CD Application name")
    parser.add_argument("--expected-revision", help="full Git commit SHA to verify in each GitOps Application")
    args = parser.parse_args()
    context = args.context or command(["oc", "config", "current-context"])
    oc = ["oc", "--context", context, "--request-timeout=20s"]
    server = command(oc + ["whoami", "--show-server"])
    user = command(oc + ["whoami"])
    version = command(oc + ["get", "clusterversion", "version", "-o", "jsonpath={.status.desired.version}"])
    print(f"Cluster: {server}\nContext: {context}\nUser: {user}\nOpenShift: {version}\nNamespace: {args.namespace}", flush=True)
    if args.confirm_cluster:
        if args.confirm_cluster.rstrip("/") != server.rstrip("/"):
            raise ValueError("Approved cluster URL does not match the active context")
    elif input("Run the live test against this cluster? [y/N] ").strip().lower() not in ("y", "yes"):
        raise ValueError("Live test not approved")
    model = args.model or input("Registered Llama Stack inference model ID: ").strip()
    if not model:
        raise ValueError("A model ID is required")
    inference_url = args.inference_url or input("OpenAI-compatible inference API URL: ").strip()
    if not inference_url.startswith("https://"):
        raise ValueError("Inference API URL must use HTTPS")
    if args.inference_secret:
        name, separator, key = args.inference_secret.partition(":")
        if not separator or not name or not key:
            raise ValueError("--inference-secret must be NAME:KEY")
        secret = json.loads(command(oc + ["get", "secret", name, "-n", args.namespace, "-o", "json"]))
        token = base64.b64decode(secret["data"][key], validate=True).decode()
    else:
        token = getpass.getpass("Inference API key (not displayed): ")
    if not token:
        raise ValueError("An inference API key is required")
    provider_model = args.inference_model or model.partition("/")[2] or model
    payload = json.dumps({"model": provider_model, "messages": [{"role": "user", "content": "Reply with OK."}], "max_tokens": 2048}).encode()
    request = urllib.request.Request(inference_url.rstrip("/") + "/chat/completions", data=payload,
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        response = json.load(urllib.request.urlopen(request, timeout=120))
    finally:
        del token
    if not response["choices"][0]["message"].get("content"):
        raise ValueError("Inference service returned an empty response")
    print(f"Inference OK: {provider_model} at {inference_url}", flush=True)
    if not args.helm_deployment:
        if not args.tenant_app or not args.rag_app or not args.expected_revision:
            raise ValueError("GitOps validation requires --tenant-app, --rag-app, and --expected-revision")
        apps = [(args.infra_app, "automation/gitops/infra/bootstrap"),
                (args.tenant_app, "automation/gitops/tenant/bootstrap"),
                (args.rag_app, "automation/gitops/tenant/deploy/helm/rag")]
        for name, path in apps:
            app = json.loads(command(oc + ["get", "application", name, "-n", "openshift-gitops", "-o", "json"]))
            source = validate_gitops_app(app, name, path, args.namespace if name == args.rag_app else None, args.expected_revision)
            print(f"GitOps OK: {name} ({source['path']}, revision {app['status']['sync'].get('revision', 'unknown')})", flush=True)
    else:
        print("Helm deployment mode: GitOps provisioning is NOT validated.", flush=True)
    names = args.pipeline_name or [name + "-vector-db-v1-0" for name in ("hr", "legal", "sales", "procurement", "techsupport")]
    workflows = json.loads(command(oc + ["get", "workflows.argoproj.io", "-n", args.namespace, "-o", "json"]))
    validate_ingestion(workflows["items"], names)
    print(f"Ingestion OK: latest runs succeeded for {len(names)} pipelines.", flush=True)
    route = json.loads(command(oc + ["get", "route", args.route, "-n", args.namespace, "-o", "json"]))
    ui = "https://" + route["spec"]["host"]
    result = command(oc + ["exec", "-i", "-n", args.namespace, "deployment/" + args.llamastack_deployment,
                           "-c", "llama-stack", "--", "python", "-", model, args.collection, args.question], BACKEND_TEST)
    backend = json.loads(result)
    print(f"Backend OK: retrieved {backend['chunks']} chunks and received a model response.", flush=True)
    from playwright.sync_api import sync_playwright, expect, TimeoutError as PlaywrightTimeoutError
    with sync_playwright() as p:
        options = {"headless": True}
        if args.browser_channel:
            options["channel"] = args.browser_channel
        browser = p.chromium.launch(**options)
        try:
            page = browser.new_page(ignore_https_errors=args.insecure_ui)
            page.goto(ui, wait_until="domcontentloaded", timeout=60000)
            model_box = page.get_by_role("combobox", name="Model")
            expect(model_box).to_be_visible(timeout=60000)
            if model_box.input_value() != model:
                model_box.click()
                model_box.fill(model)
                page.get_by_role("option", name=model, exact=True).click(timeout=30000)
            # Reasoning models can spend the default 512 tokens before answering.
            page.get_by_role("slider", name="Max Tokens").press("End")
            page.wait_for_timeout(3000)  # Allow Streamlit to rerun after the slider change.
            collections = page.get_by_role("combobox", name="Select Document Collections for RAG queries")
            option = page.get_by_role("option", name=args.collection, exact=True)
            for attempt in range(4):
                collections.click()
                collections.press("ArrowDown")
                try:
                    option.click(timeout=5000)
                    break
                except PlaywrightTimeoutError:
                    if attempt == 3:
                        raise
                    page.wait_for_timeout(2000)
            chat = page.get_by_test_id("stChatInputTextArea")
            expect(chat).to_be_visible(timeout=30000)
            chat.fill(args.question)
            chat.press("Enter")
            messages = page.get_by_test_id("stChatMessage")
            page.wait_for_function("() => document.querySelectorAll('[data-testid=stChatMessage]').length >= 3", timeout=120000)
            answer = messages.last
            expect(answer.get_by_text(f"Searched vector stores: {args.collection}", exact=False)).to_be_visible(timeout=120000)
            page.wait_for_function("""() => {
              const messages = document.querySelectorAll('[data-testid=stChatMessage]');
              const blocks = messages[messages.length - 1].querySelectorAll('[data-testid=stMarkdownContainer]');
              return Array.from(blocks).some(e => {
                const t = e.innerText.trim();
                return !e.closest('[data-testid=stExpander], details') && t.length > 15 && !/^(🛠|📄|🧠|Searching|Searched)/u.test(t);
              });
            }""", timeout=180000)
            blocks = answer.locator('[data-testid="stMarkdownContainer"]').evaluate_all("es => es.filter(e => !e.closest('[data-testid=stExpander], details')).map(e => e.innerText)")
            text = next((t.strip() for t in reversed(blocks) if len(t.strip()) > 15 and not t.strip().startswith(("🛠", "📄", "🧠", "Searching", "Searched"))), "")
            if len(text) < 16 or "error" in text.lower() or args.question in text:
                raise ValueError(f"Unexpected browser chat response: {text[:300]}")
            if args.show_answer:
                print(f"Browser response: {text[:500]}", flush=True)
            print(f"Browser OK: selected {args.collection}, submitted a question, and received a response.", flush=True)
        finally:
            browser.close()
    print(f"PASS: RAG live test ({'Helm only' if args.helm_deployment else 'GitOps + RAG'})")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, subprocess.CalledProcessError, ImportError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr, file=sys.stderr)
        sys.exit(1)
