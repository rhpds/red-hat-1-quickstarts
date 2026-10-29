"""Optional contract test against an agnosticv tenant configuration."""
import base64
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = os.environ.get("AGNOSTICV_TENANT_CONFIG")


@unittest.skipUnless(CONFIG, "Set AGNOSTICV_TENANT_CONFIG to an agnosticv common.yaml")
class AgnosticvIntegrationTests(unittest.TestCase):
    def test_actual_tenant_values_reach_both_charts(self):
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
                "ai_quickstart_hugging_face_token": "test-hf", "ai_quickstart_tavily_search_key": "test-tavily"}
            inputs.write_text(json.dumps(input_values))
            env = os.environ.copy()
            env.update({"ANSIBLE_LOCAL_TEMP": str(tmp / "local"), "ANSIBLE_REMOTE_TEMP": str(tmp / "remote"),
                        "ANSIBLE_NOCOLOR": "1"})
            subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", "-e", "@" + str(inputs), str(playbook)],
                           env=env, check=True, capture_output=True, text=True)
            data = yaml.safe_load(result.read_text())
            values = data["values"]
            self.assertEqual({x["suffix"] for x in data["suffixes"]}, {"rag", "it-svc"})
            self.assertIn("llama-scout-17b", data["models"])
            self.assertEqual(values["rag"]["namespace"], "user-7kzmd-rag")
            self.assertEqual(values["it-selfsvc"]["namespace"], "user-7kzmd-it-svc")
            self.assertEqual(values["it-selfsvc"]["model"], {"id": "llama-scout-17b", "url": "https://model.example.invalid/v1", "apiToken": "test-model-key"})
            self.assertEqual(values["rag"]["values"]["global"]["models"]["remotellm"]["apiToken"], "test-model-key")
            bootstrap_values = tmp / "bootstrap.yaml"
            bootstrap_values.write_text(yaml.safe_dump(values))
            bootstrap = subprocess.check_output(["helm", "template", "bootstrap", str(ROOT / "tenant/bootstrap"), "-f", str(bootstrap_values)], text=True)
            apps = {d["metadata"]["name"]: d for d in yaml.safe_load_all(bootstrap) if d and d.get("kind") == "Application"}
            rag_app = apps["tenant-7kzmd"]
            self.assertEqual(rag_app["spec"]["destination"]["namespace"], "user-7kzmd-rag")
            rag_values = tmp / "rag-values.yaml"
            rag_values.write_text(rag_app["spec"]["source"]["helm"]["values"])
            rag_output = subprocess.check_output(["helm", "template", "tenant-7kzmd", str(ROOT / "tenant/deploy/helm/rag"),
                                                  "--namespace", "user-7kzmd-rag", "-f", str(rag_values)], text=True)
            rag_resources = {(d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(rag_output)
                             if isinstance(d, dict) and "kind" in d and "metadata" in d}
            rag_config = yaml.safe_load(rag_resources[("ConfigMap", "run-config")]["data"]["config.yaml"])
            rag_model = next(p for p in rag_config["providers"]["inference"] if p["provider_id"] == "remotellm")
            self.assertEqual(rag_model["config"]["base_url"], "https://model.example.invalid")
            self.assertEqual(rag_model["config"]["api_token"], "test-model-key")
            self.assertTrue(any(m["model_id"] == "llama-scout-17b" for m in rag_config["registered_resources"]["models"]))
            app = apps["it-selfsvc-7kzmd"]
            self.assertEqual(app["spec"]["destination"]["namespace"], "user-7kzmd-it-svc")
            child_values = tmp / "it-values.yaml"
            child_values.write_text(app["spec"]["source"]["helm"]["values"])
            chart = ROOT / "it-selfsvc/chart"
            output = subprocess.check_output(["helm", "template", "self-service-agent", str(chart), "--namespace", "user-7kzmd-it-svc",
                "-f", str(chart / "values-test.yaml"), "-f", str(chart / "values-demo.yaml"), "-f", str(child_values)], text=True)
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
            self.assertEqual(base64.b64decode(email["smtp-host"]).decode(), "test-email-server-smtp.user-7kzmd-it-svc.svc.cluster.local")
            self.assertEqual(base64.b64decode(email["imap-host"]).decode(), "test-email-server-imap.user-7kzmd-it-svc.svc.cluster.local")
            for endpoint in ("https://model.example.invalid/", "https://model.example.invalid/v1", "https://model.example.invalid/v1/"):
                with self.subTest(endpoint=endpoint):
                    input_values["litellm_api_endpoint"] = endpoint
                    inputs.write_text(json.dumps(input_values))
                    subprocess.run(["ansible-playbook", "-i", "localhost,", "-c", "local", "-e", "@" + str(inputs), str(playbook)],
                                   env=env, check=True, capture_output=True, text=True)
                    self.assertEqual(yaml.safe_load(result.read_text())["values"]["it-selfsvc"]["model"]["url"], "https://model.example.invalid/v1")


if __name__ == "__main__":
    unittest.main()
