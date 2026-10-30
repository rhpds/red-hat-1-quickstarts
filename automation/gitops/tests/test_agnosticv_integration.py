"""Optional contract test against an agnosticv tenant configuration."""
import base64
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = os.environ.get("AGNOSTICV_TENANT_CONFIG")


@unittest.skipUnless(CONFIG, "Set AGNOSTICV_TENANT_CONFIG to an agnosticv common.yaml")
class AgnosticvIntegrationTests(unittest.TestCase):
    def assert_images_locked(self, rendered, allowed=()):
        found = []
        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(item, str) and (key == "image" or (key == "value" and value.get("name") in ("INGESTION_PIPELINE_IMAGE", "JUPYTER_IMAGE", "SERVING_RUNTIME_IMAGE"))):
                        found.append(item)
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(list(yaml.safe_load_all(rendered)))
        self.assertTrue(found)
        self.assertEqual({image for image in found if not re.search(r'@sha256:[a-f0-9]{64}$', image)}, set(allowed))

    def test_actual_tenant_values_reach_all_charts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            result = tmp / "values.yaml"
            playbook = tmp / "render.yaml"
            playbook.write_text(yaml.safe_dump([{
                "hosts": "localhost", "connection": "local", "gather_facts": False,
                "vars_files": [str(Path(CONFIG).resolve())],
                "tasks": [{"name": "Render tenant values with test inputs", "no_log": True,
                           "ansible.builtin.copy": {"dest": str(result), "content":
                               "{{ {'values': ocp4_workload_gitops_bootstrap_helm_values, "
                               "'suffixes': ocp4_workload_tenant_namespace_suffixes, "
                               "'models': ocp4_workload_litellm_virtual_keys_models} | to_nice_yaml }}"}}],
            }]))
            inputs = tmp / "inputs.json"
            input_values = {"guid": "7kzmd", "common_password": "test-password",
                "litellm_api_endpoint": "https://model.example.invalid", "litellm_virtual_key": "test-model-key",
                "openshift_cluster_ingress_domain": "apps.example.invalid",
                "ai_quickstart_hugging_face_token": "test-hf", "ai_quickstart_tavily_search_key": "test-tavily"}
            inputs.write_text(json.dumps(input_values))
            env = os.environ.copy()
            env.update({"ANSIBLE_LOCAL_TEMP": str(tmp / "local"), "ANSIBLE_REMOTE_TEMP": str(tmp / "remote"),
                        "ANSIBLE_NOCOLOR": "1"})
            subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", "-e", "@" + str(inputs), str(playbook)],
                           env=env, check=True, capture_output=True, text=True)
            data = yaml.safe_load(result.read_text())
            values = data["values"]
            self.assertEqual({x["suffix"] for x in data["suffixes"]}, {"rag", "it-selfsvc", "ppe"})
            self.assertIn("llama-scout-17b", data["models"])
            self.assertEqual(values["rag"]["namespace"], "user-7kzmd-rag")
            self.assertEqual(values["it-selfsvc"]["namespace"], "user-7kzmd-it-selfsvc")
            self.assertEqual(values["it-selfsvc"]["model"], {"id": "llama-scout-17b", "url": "https://model.example.invalid/v1", "apiToken": "test-model-key"})
            self.assertEqual(values["rag"]["values"]["global"]["models"]["remotellm"]["apiToken"], "test-model-key")
            self.assertEqual(values["ppe"]["namespace"], "user-7kzmd-ppe")
            self.assertEqual(values["ppe"]["values"]["openai"], {"apiToken": "test-model-key", "apiEndpoint": "https://model.example.invalid/v1", "model": "llama-scout-17b"})
            self.assertEqual(values["rag"]["values"]["configure-pipeline"]["minio"]["image"]["repository"], "quay.io/rh-aiservices-bu/minio")
            config_source = yaml.safe_load(Path(CONFIG).read_text())
            self.assertNotIn("agnosticd.ai_quickstarts.quickstart_deploy_via_make", config_source["workloads"])
            self.assertIn("agnosticd.core_workloads.ocp4_workload_gitops_bootstrap", config_source["workloads"])
            self.assertEqual(next(x for x in data["suffixes"] if x["suffix"] == "it-selfsvc")["limit_range"]["default"]["memory"], "1Gi")
            bootstrap_values = tmp / "bootstrap.yaml"
            bootstrap_values.write_text(yaml.safe_dump(values))
            bootstrap = subprocess.check_output(["helm", "template", "bootstrap", str(ROOT / "tenant/bootstrap"), "-f", str(bootstrap_values)], text=True)
            apps = {d["metadata"]["name"]: d for d in yaml.safe_load_all(bootstrap) if d and d.get("kind") == "Application"}
            self.assertEqual(set(apps), {"tenant-7kzmd", "it-selfsvc-7kzmd", "ppe-7kzmd"})
            ppe_app = apps["ppe-7kzmd"]
            self.assertEqual(ppe_app["spec"]["destination"]["namespace"], "user-7kzmd-ppe")
            self.assertEqual(ppe_app["spec"]["source"]["path"], "automation/gitops/tenant/multimodal/chart")
            ppe_values = tmp / "ppe-values.yaml"
            ppe_values.write_text(ppe_app["spec"]["source"]["helm"]["values"])
            ppe_output = subprocess.check_output(["helm", "template", "ppe-7kzmd", str(ROOT / "tenant/multimodal/chart"),
                                                  "--namespace", "user-7kzmd-ppe", "-f", str(ppe_values)], text=True)
            self.assert_images_locked(ppe_output)
            ppe_resources = {(d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(ppe_output)
                             if isinstance(d, dict) and "kind" in d and "metadata" in d}
            self.assertEqual(ppe_resources[("Secret", "ppe-7kzmd-ppe-compliance-monitor-openai")]["stringData"]["api-token"], "test-model-key")
            backend = ppe_resources[("Deployment", "ppe-7kzmd-ppe-compliance-monitor-backend")]
            env_vars = {e["name"]: e for e in backend["spec"]["template"]["spec"]["containers"][0]["env"]}
            self.assertEqual(env_vars["OPENAI_API_TOKEN"]["valueFrom"]["secretKeyRef"]["key"], "api-token")
            self.assertEqual(env_vars["OPENAI_API_ENDPOINT"]["value"], "https://model.example.invalid/v1")
            self.assertEqual(env_vars["OPENAI_MODEL"]["value"], "llama-scout-17b")
            self.assertEqual(env_vars["RUNTIME_TYPE"]["value"], "openvino")
            self.assertNotIn("test-model-key", yaml.safe_dump(backend))
            self.assertEqual(ppe_resources[("Route", "ppe-7kzmd-fe")]["spec"]["host"], "ppe-7kzmd-user-7kzmd-ppe.apps.example.invalid")
            label_host = "ppe-7kzmd-ls-user-7kzmd-ppe.apps.example.invalid"
            self.assertEqual(ppe_resources[("Route", "ppe-7kzmd-ls")]["spec"]["host"], label_host)
            label = ppe_resources[("Deployment", "ppe-7kzmd-ppe-compliance-monitor-labelstudio")]
            label_env = {e["name"]: e.get("value") for e in label["spec"]["template"]["spec"]["containers"][0]["env"]}
            self.assertEqual(label_env["CSRF_TRUSTED_ORIGINS"], "https://" + label_host)
            jobs = [d for (kind, _), d in ppe_resources.items() if kind == "Job" and d["metadata"].get("labels", {}).get("app.kubernetes.io/component") in ("init-data-model", "s3-buckets", "runtime-deployer")]
            self.assertEqual(len(jobs), 3)
            self.assertTrue(all(j["metadata"]["annotations"]["argocd.argoproj.io/hook"] == "Sync" for j in jobs))
            self.assertEqual(next(j for j in jobs if j["metadata"]["labels"]["app.kubernetes.io/component"] == "runtime-deployer")["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "1")
            rag_app = apps["tenant-7kzmd"]
            self.assertEqual(rag_app["spec"]["destination"]["namespace"], "user-7kzmd-rag")
            self.assertEqual(rag_app["spec"]["source"]["path"], "automation/gitops/tenant/rag")
            rag_values = tmp / "rag-values.yaml"
            rag_values.write_text(rag_app["spec"]["source"]["helm"]["values"])
            rag_output = subprocess.check_output(["helm", "template", "tenant-7kzmd", str(ROOT / "tenant/rag"),
                                                  "--namespace", "user-7kzmd-rag", "-f", str(rag_values)], text=True)
            self.assert_images_locked(rag_output, (
                "image-registry.openshift-image-registry.svc:5000/openshift/tools:latest",
                "image-registry.openshift-image-registry.svc:5000/redhat-ods-applications/s2i-generic-data-science-notebook:2024.2"))
            rag_resources = {(d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(rag_output)
                             if isinstance(d, dict) and "kind" in d and "metadata" in d}
            rag_config = yaml.safe_load(rag_resources[("ConfigMap", "run-config")]["data"]["config.yaml"])
            rag_model = next(p for p in rag_config["providers"]["inference"] if p["provider_id"] == "remotellm")
            self.assertEqual(rag_model["config"]["base_url"], "https://model.example.invalid")
            self.assertEqual(rag_model["config"]["api_token"], "test-model-key")
            self.assertTrue(any(m["model_id"] == "llama-scout-17b" for m in rag_config["registered_resources"]["models"]))
            app = apps["it-selfsvc-7kzmd"]
            self.assertEqual(app["spec"]["destination"]["namespace"], "user-7kzmd-it-selfsvc")
            self.assertEqual(app["spec"]["source"]["path"], "automation/gitops/tenant/it-selfsvc/chart")
            child_values = tmp / "it-values.yaml"
            child_values.write_text(app["spec"]["source"]["helm"]["values"])
            chart = ROOT / "tenant/it-selfsvc/chart"
            output = subprocess.check_output(["helm", "template", "self-service-agent", str(chart), "--namespace", "user-7kzmd-it-selfsvc",
                "-f", str(chart / "values-test.yaml"), "-f", str(chart / "values-demo.yaml"), "-f", str(child_values)], text=True)
            self.assert_images_locked(output)
            resources = {(d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(output)
                         if isinstance(d, dict) and "kind" in d and "metadata" in d}
            config = yaml.safe_load(resources[("ConfigMap", "run-config")]["data"]["config.yaml"])
            model = next(p for p in config["providers"]["inference"] if p["provider_id"] == "llama-scout-17b")
            self.assertEqual(model["config"]["base_url"], "https://model.example.invalid/v1")
            self.assertEqual(model["config"]["api_token"], "${env.SELFSVC_LLM_API_TOKEN}")
            secret = resources[("Secret", "llama-stack-env")]["data"]["SELFSVC_LLM_API_TOKEN"]
            self.assertEqual(base64.b64decode(secret).decode(), "test-model-key")
            for name, workers in (("agent-service", "2"), ("request-manager", "2"), ("integration-dispatcher", "1")):
                deploy = resources[("Deployment", "self-service-agent-" + name)]
                env_vars = {e["name"]: e.get("value") for e in deploy["spec"]["template"]["spec"]["containers"][0]["env"]}
                self.assertEqual(env_vars["UVICORN_WORKERS"], workers)
                if name == "agent-service":
                    self.assertEqual(env_vars["LG_PROMPT_LAPTOP_REFRESH"], "/app/agent-service/config/lg-prompts/lg-prompt-small-scout.yaml")
            email = resources[("Secret", "self-service-agent-integration-secrets")]["data"]
            self.assertEqual(base64.b64decode(email["smtp-host"]).decode(), "test-email-server-smtp.user-7kzmd-it-selfsvc.svc.cluster.local")
            self.assertEqual(base64.b64decode(email["imap-host"]).decode(), "test-email-server-imap.user-7kzmd-it-selfsvc.svc.cluster.local")
            for endpoint in ("https://model.example.invalid/", "https://model.example.invalid/v1", "https://model.example.invalid/v1/"):
                with self.subTest(endpoint=endpoint):
                    input_values["litellm_api_endpoint"] = endpoint
                    inputs.write_text(json.dumps(input_values))
                    subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", "-e", "@" + str(inputs), str(playbook)],
                                   env=env, check=True, capture_output=True, text=True)
                    resolved = yaml.safe_load(result.read_text())["values"]
                    self.assertEqual(resolved["it-selfsvc"]["model"]["url"], "https://model.example.invalid/v1")
                    self.assertEqual(resolved["ppe"]["values"]["openai"]["apiEndpoint"], "https://model.example.invalid/v1")


if __name__ == "__main__":
    unittest.main()
