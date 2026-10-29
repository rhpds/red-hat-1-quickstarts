# RAG GitOps deployment

The cluster agnosticv workload bootstraps `infra/bootstrap`. The tenant
workload bootstraps `tenant/bootstrap`, which creates an Argo CD Application
for `tenant/deploy/helm/rag` in this repository and, when `it-selfsvc` is
configured, a second Application for `it-selfsvc/chart`. The Applications
deploy into separate tenant namespaces. Cluster operators are managed by
agnosticv; the infra chart is a marker for the integration point.

## IT Self Service

The copied chart defaults to upstream release `v0.0.13`, matching the existing
make-based catalog item. It uses the upstream test and demo values, and includes
the GreenMail manifest, mock ServiceNow credentials, and Argo CD hooks for the
database migration and initialization jobs. The copied Llama Stack dependency
is patched to support an environment reference for the inference token.
GreenMail's upstream webmail backend still pulls a `latest` image and installs
its pinned Python packages at startup, so it needs registry and package access.

The conversion covers the catalog item's `make install INSTALL_MODE=demo` path:

| Make step | GitOps equivalent |
| --- | --- |
| Create namespace | AgnosticV tenant namespace workload and Argo CD `CreateNamespace` |
| Build Helm dependencies | Refresh command vendors the locked packages |
| Apply GreenMail manifest | Copied manifest in the vendored chart's templates |
| Create mock ServiceNow credentials | Added mock Secret template |
| Install Helm chart with demo values and model arguments | Tenant bootstrap creates an Application with the test and demo values and translated Helm values |
| Delete old initialization jobs and wait for workloads | Argo CD sync hooks recreate the two jobs; Application health reports workload readiness |
| Print the webmail URL | The agnosticv Showroom configuration supplies the URL |

Other Make targets and optional modes are not converted. In particular, the
Make target's manual namespace context switch and broad job deletion are not
performed by Argo CD.

To refresh the copy, install Git, Helm, Python 3 and PyYAML, then run:

```sh
python3 automation/gitops/update-it-selfsvc.py --ref v0.0.13
git diff -- automation/gitops/it-selfsvc
git status --short automation/gitops/it-selfsvc
```

The command clones the upstream repository and downloads the locked chart
dependencies, including the nested Zammad dependency. It records the source
commit in `it-selfsvc/source.json`. For an offline refresh use
`--source /path/to/it-self-service-agent --dependency-dir /path/to/helm/charts`.
Review changes to the upstream demo chart and jobs before deploying a new version.

The tenant bootstrap accepts `it-selfsvc.namespace`, `it-selfsvc.git.revision`,
and `it-selfsvc.model` fields `id`, `url`, and `apiToken`, plus optional native
Helm overrides in `it-selfsvc.values`. Set `it-selfsvc.model.name` to a simple
provider name when the model ID contains slashes; it defaults to the model ID.
The agnosticv tenant configuration provides these values and provisions `user-<guid>-it-selfsvc` alongside
`user-<guid>-rag`. The model token is rendered into a Kubernetes Secret rather
than the Llama Stack ConfigMap, but is still present in the Argo CD Application
values; restrict access to those Applications.

Agnosticv supplies `litellm_virtual_key` to both quickstarts along with the
model and inference URL. The RAG chart currently renders that token directly
into its Llama Stack ConfigMap as well as the Argo CD Application values.

## RAG

To refresh the vendored files, install Git, Helm, Python 3 and PyYAML, then run:

```sh
python3 automation/gitops/update-rag.py --ref main
git diff -- automation/gitops
git status --short automation/gitops
```

`--ref` accepts a branch, tag, or commit. The command clones upstream RAG,
records the resolved commit in `rag-source.json`, copies `infra/`, `tenant/`,
and `deploy/helm/rag/`, and builds the Helm dependencies from `Chart.lock`.
It also copies upstream's Llama Stack and Playwright tests into
`upstream-rag-tests/` at the same commit. It resets the copied tenant chart's Git URL and path to this repository. The
local infra bootstrap is preserved. The copied tenant and infra files are
replaced on refresh, so review and commit local changes before running it.
The locally maintained IT Self Service Application template, the RAG
`tenant-` Application-name prefix, and Argo CD comparisons for the generated
Route hostname and OpenShift AI Notebook additions are preserved during a RAG
refresh.
Commit the six packages in the RAG chart's `charts/` directory along with the
other changes so Argo CD can render without fetching them at deployment time.
The refresh also patches the Llama Stack dependency's model readiness script to
quote Secret-backed environment references; it fails if the upstream template
changes and the patch needs review.

For an offline refresh, use `--source /path/to/RAG --ref <commit>` and
`--dependency-dir /path/to/locked/packages`. The source must be a Git checkout;
uncommitted changes there are not copied. Run the tests with:

```sh
python3 -m unittest discover -s automation/gitops/tests
```

To verify the actual agnosticv tenant values with placeholder credentials,
install Ansible and point the optional contract test at that checkout:

```sh
AGNOSTICV_TENANT_CONFIG=/path/to/agnosticv/rh1-2027/lb2142-ai-quickstarts-tenant/common.yaml \
  python3 -m unittest discover -s automation/gitops/tests -p test_agnosticv_integration.py -v
```

This renders the agnosticv values using Ansible and checks both bootstrap
Applications and the resulting RAG and IT Self Service Helm resources. It does not
contact a cluster or use real credentials.

For a live end-to-end test, install the browser dependency and Chromium:

```sh
python3 -m pip install -r automation/gitops/e2e/requirements.txt
python3 -m playwright install chromium
python3 automation/gitops/e2e/live-test.py --namespace <namespace> \
  --route <rag-route-name> --tenant-app <bootstrap-application> \
  --rag-app <rag-application> --expected-revision <full-commit-sha> \
  --model <llama-stack-model-id> --inference-url <api-url>
```

The runner prints the current cluster and asks for approval. It checks that the
infra, tenant, and RAG Applications point to the expected paths and commit and
are Healthy and Synced, checks the latest ingestion runs and collection file
statuses, then tests document retrieval, model inference, and browser chat. By
default it requires successful HR, legal, sales, procurement, and tech-support
runs and populated collections without failed, cancelled, or in-progress files.
Supply `--pipeline-name` one or more times to select the expected runs for a
customized deployment; in that case only the selected `--collection` is checked.
For a pre-approved noninteractive run, pass the exact API URL as
`--confirm-cluster`; a mismatch fails. For a locally installed Helm release,
use `--helm-deployment`: this skips GitOps validation and labels the result
accordingly. Use `--browser-channel chrome` for installed Chrome and
`--insecure-ui` only when the UI certificate is not trusted. The default test
uses the populated `hr-vector-db-v1-0` collection and its sample handbook;
`--collection` and `--question` select a different document and question.
Use `--argocd-namespace` or `--expected-repo-url` only when testing a different
Argo CD instance or an explicitly selected staging repository.

Normal deployments receive the inference URL, model ID and API key from
agnosticv. The runner asks for any missing model URL, model ID, and API key and
tests the supplied OpenAI-compatible endpoint. Alternatively pass
`--inference-secret NAME:KEY` to read the API key from a Secret in the test
namespace. It does not print or persist the key. Use `--inference-model` if the
provider model ID differs from the Llama Stack model ID without its provider
prefix. Provision the model settings before running the test.

The original upstream suites are kept in `upstream-rag-tests/`. To run them,
install `e2e_ui/requirements.txt` and `integration/llamastack/requirements.txt`
from that directory in a separate virtual environment. Port-forward the UI and
Llama Stack services in separate terminals (replace the namespace and UI service
name as needed), then run the tests in a third terminal:

```sh
oc -n <namespace> port-forward svc/<rag-ui-service> 8501:8501
oc -n <namespace> port-forward svc/llamastack 8321:8321
```

```sh
export RAG_UI_ENDPOINT=http://localhost:8501
export LLAMA_STACK_ENDPOINT=http://localhost:8321
export INFERENCE_MODEL='<registered-model-id>'
export SKIP_MODEL_TESTS=false
python -m pytest automation/gitops/upstream-rag-tests/e2e_ui \
  automation/gitops/upstream-rag-tests/integration/llamastack -v
```

Some upstream tests skip inference, use old APIs, or reuse a fixed test database;
run them only against a suitable test instance. A successful upstream run alone
does not prove this deployment's GitOps and RAG flow. The strict runner above
fails when its required model, collection, retrieval, UI, or GitOps checks fail.
