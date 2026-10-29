# RAG GitOps deployment

The cluster agnosticv workload bootstraps `infra/bootstrap`. The tenant
workload bootstraps `tenant/bootstrap`, which creates an Argo CD Application
for `tenant/deploy/helm/rag` in this repository. Cluster operators are managed
by agnosticv; the infra chart is a marker for the integration point.

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
are Healthy and Synced, checks the latest ingestion runs, then tests document
retrieval, model inference, and browser chat. By default it requires successful
HR, legal, sales, procurement, and tech-support runs; supply `--pipeline-name`
one or more times to select the expected runs for a customized deployment.
For a pre-approved noninteractive run, pass the exact API URL as
`--confirm-cluster`; a mismatch fails. For a locally installed Helm release,
use `--helm-deployment`: this skips GitOps validation and labels the result
accordingly. Use `--browser-channel chrome` for installed Chrome and
`--insecure-ui` only when the UI certificate is not trusted. The default test
uses the populated `hr-vector-db-v1-0` collection and its sample handbook;
`--collection` and `--question` select a different document and question.

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
