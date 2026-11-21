# LB2142 RAG ingestion — handover

**To:** Saurabh (owner of `rh-ai-quickstart/ai-architecture-charts` and the
`ingestion-pipeline` image)
**From:** Tony / agent, 2026-11-20
**Subject:** RAG knowledge-base ingestion fails on most seats; needs retry and
idempotent store creation upstream

## TL;DR

On 6 of 7 seats across two clusters, the Showroom starts and the tenant reports
`started`, but the RAG knowledge bases are empty or incomplete, so the module 2
grounded-answer demo cannot work. Two defects in the ingestion executor:

1. **No retry.** A failed `POST /v1/vector_stores/…/files` is terminal for that
   pipeline. When llama-stack restarts mid-ingest, the document set is lost.
2. **Store creation is not idempotent.** Re-running a pipeline creates a second
   vector store with the same name instead of reusing the first, leaving
   duplicates that hold different subsets of the documents.

Both are in `quay.io/rh-ai-quickstart/ingestion-pipeline:0.7.5`. Neither is
fixable from the chart values, so this is yours.

## Symptom

Ingestion component pods end in `Error`:

```
fetch-and-store-pipeline-<id>-system-container-impl-<n>   0/2   Error
```

Executor log:

```
llama_stack_client.APITimeoutError: Request timed out.
...
Exception: Failed to insert documents into vector store: Request timed out.
E1120 launcher_v2.go:417] Component failed to execute successfully: exit status 1
```

There is no retry; the pipeline run fails and nothing re-drives it.

## What triggers it

Concurrent seat provisioning. Each seat has its own llama-stack, but every
seat's five pipelines start within seconds of each other, and llama-stack
blocks on the embedding calls while inserting. While blocked it stops answering
`/v1/health`, and Kubernetes kills it:

```
Kubelet  Container llama-stack failed liveness probe, will be restarted
pod/llamastack-…  terminated exitCode=137  reason=Error
```

Every in-flight insert then fails with the timeout above.

Restarts are not the only trigger: the 2026-11-21 run at the bottom of this
document had zero restarts and still failed, with llama-stack returning a 500
mid-insert. Treat the restart as one way to provoke a transient insert failure,
not the root cause.

### Evidence (two clusters, same behaviour)

4.20 cluster (`cluster-69fb6`), workshop `dev-cp4lx`:

| seat | stores | documents per store | llama-stack restarts |
| --- | --- | --- | --- |
| `7pbkb` | **7** (`hr` and `procurement` duplicated) | 0, 0, 2, 3, 0, 1, 3 | **2** |
| `jd6wn` | 4 (`hr` missing entirely) | 2, 2, 2, 2 | 0 |
| `jxqzx` | 5 | 0, 0, 2, 1, 0 | **1** |

4.22 cluster (`cluster-79cxg`), workshop `dev-s8l2w`:

| seat | stores | documents per store | llama-stack restarts |
| --- | --- | --- | --- |
| `rtl2n` | 5 | 2, 2, 2, 1, 10 | 0 — provisioned **after** the restart, clean |
| `9vsc8` | 5 | **0, 0, 0, 0, 0** | 1 — all inserts timed out |
| `j5vf7` | 5 | **0, 0, 0, 0, 0** | 1 |
| `44pwm` | 4 | 0, 0, 2, 2 | 0 — `techsupport` store never created |

The contrast between `rtl2n` (clean, single late seat) and the seats provisioned
together is the strongest signal: it is a concurrency/latency problem, not bad
data.

### Latest reproduction (2026-11-21, container-mode cluster `8wm7t`)

Same content, current charts, 3 seats ordered together. **No llama-stack
restarts at all** this time — but ingestion still fails on 2 of 3 seats:

| seat | stores | documents per store | llama-stack restarts |
| --- | --- | --- | --- |
| `xbqkr` | 5 | 1, 1, 1, 1, 9 | 0 — clean |
| `5cnkd` | 5 | 1, 1, 1, **0** (`techsupport`) | 0 — insert failed |
| `sq48x` | 4 (`legal` never created) | 1, 1, 1, 9 | 0 |

The failure has moved from a client timeout to a server error, and it no longer
depends on the liveness probe:

```
raise Exception(f"Failed to insert documents into vector store: {e}")
Exception: Failed to insert documents into vector store:
  Error code: 500 - {'error': {'message': 'Internal server error: An unexpected error occurred.'}}
E1121 launcher_v2.go:417] Component failed to execute successfully: exit status 1
```

Two things this shows:

1. **The 500 makes the no-retry problem worse, not better.** llama-stack is
   answering but returning a transient 500 mid-batch; the executor treats it as
   terminal. A bounded retry would still fix this without any probe change.
2. **Store creation is still not get-or-create.** On `sq48x`, `legal` is absent
   while the other four completed — the same non-idempotent/partial-creation
   behaviour, just without a restart to blame.

For reference, the expected document counts on `main` are one file each for
`hr`, `legal`, `sales`, `procurement` and nine for `techsupport`; a clean seat
shows exactly `1, 1, 1, 1, 9`.

## What is needed

### 1. Retry the insert (required)

On `APITimeoutError` / connection failure against llama-stack, retry with
backoff before failing the component. A llama-stack restart takes ~60–90s to
recover, so the backoff must outlast that. A bounded retry (e.g. 5 attempts
over 5 minutes) would cover every case observed here.

### 2. Make store creation idempotent (required)

`vector_store_name` is a stable identifier the chart already provides
(`hr-vector-db-v1-0`, etc.). Creating it must be get-or-create by name, and a
re-run against an existing store must add documents to it rather than mint a
new store. Today `7pbkb` has two `hr-vector-db-v1-0` stores, one empty.

Consider also making the insert itself idempotent per file (skip files already
present) so a retry does not duplicate chunks.

### 3. Optional: bound concurrency

If the executor can serialise inserts per store — or limit how many pipelines a
seat runs at once — that would reduce the pressure on llama-stack regardless of
probe settings. Your call; 1 and 2 are the ones that actually fix it.

## Acceptance criteria

- A seat's five stores each end with their expected documents, on 3 concurrent
  seats provisioned together.
- Killing llama-stack mid-ingest does not lose documents: the pipeline retries
  and completes.
- Re-running a pipeline never produces a second store with the same name.
- `curl /v1/vector_stores` shows exactly five stores, one per knowledge base.

## How to reproduce

Cheapest reliable reproduction is 3+ seats in one workshop, ordered together
(they provision within seconds of each other). A single seat ordered on its own
usually succeeds and will not show the bug.

To see the failure directly, watch a seat while it ingests:

```bash
# per seat
oc exec -n <user>-rag <llamastack-pod> -- python3 -c "
import json,urllib.request
base='http://localhost:8321/v1'
for v in json.load(urllib.request.urlopen(base+'/vector_stores',timeout=20))['data']:
    f=json.load(urllib.request.urlopen(base+'/vector_stores/%s/files'%v['id'],timeout=20))
    print(v['name'], len(f.get('data',[])))
"
```

and check restarts with:

```bash
oc get pod <llamastack-pod> -n <user>-rag \
  -o jsonpath='{.status.containerStatuses[0].restartCount}{"\n"}'
```

Affected seats are still running:

- 4.20: `cluster-69fb6`, namespaces `user-7pbkb-rag`, `user-jd6wn-rag`,
  `user-jxqzx-rag`
- 4.22: `cluster-79cxg`, namespaces `user-9vsc8-rag`, `user-44pwm-rag`,
  `user-j5vf7-rag` (clean reference: `user-rtl2n-rag`)

## Versions

- `rag` chart 0.2.47, vendored at `red-hat-1-quickstarts/automation/gitops/tenant/rag`
- `ingestion-pipeline` 0.7.5 / image `quay.io/rh-ai-quickstart/ingestion-pipeline:0.7.5`
- `llama-stack` 0.8.7
- Observed on OCP 4.20.46 and 4.22.22

## What we are doing on our side

Deliberately **not** touching llama-stack's liveness probe: shortening the
symptom is your call to make once retry exists. We are:

- asserting per-store document counts (and duplicate names) in the LB2142
  readiness check, so a seat like `9vsc8` fails the gate instead of reporting
  green;
- setting explicit resources on llama-stack — the deployment currently gets the
  namespace LimitRange default of a **256 Mi request** against a 2 CPU / 4 GiB
  limit, which may contribute to the blocking.

We will not build a re-trigger/verification Job. That was the fallback if the
executor could not change; with your fix it would just duplicate your work.

## What we would find most useful back

A new `ingestion-pipeline` tag once retry and idempotent creation land, so we
can bump the vendored chart and re-run the same seat matrix. If you want the
exact failing pod specs and full executor logs, they are still on the two
clusters above.
