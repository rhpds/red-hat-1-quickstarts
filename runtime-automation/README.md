# runtime-automation

Solve/validate automation served by the Showroom runner (`zt-runner`) container.

The runner is a sidecar in the Showroom pod. It scans this directory, exposes
each module over SSE, and injects cluster credentials, so a lab can drive and
check itself from the browser without the learner running anything.

## How the runner uses this directory

Verified against `quay.io/rhpds/zt-runner:v2.5.0` (`/app/stream_api.py`):

| Fact | Consequence |
| --- | --- |
| `RUNTIME_DIR` = `/app/runtime-automation` if it exists, else `/showroom/repo/runtime-automation` | This directory must exist in the content repo, at the repo root. A checkout without it makes `/health` answer 503. |
| `/health` is 503 unless `RUNTIME_DIR` exists | The chart probes `/health` for **liveness**, so a missing directory kills the runner on a loop and the Showroom pod never becomes Ready. |
| `/config` lists `module-*/` and the `*.yml` files inside each | Only directories named `module-*` are exposed. Stage names are the filenames without extension. |
| `/stream/setup/<module>`, `/stream/solve/<module>`, `/stream/validate/<module>` | Stage files are `setup.yml`, `solve.yml`, `validate.yml` (or `validation.yml`). A stage with no file simply has no endpoint. |

There is no `main.yml` wrapper in this mode: each file is a standalone
playbook that manages its own inventory (`hosts: localhost`, `connection: local`).

## Runtime contract

Extravars injected by the runner:

- `k8s_kubeconfig` — rendered kubeconfig for the runtime automation identity.
  Requires showroom collection >= v1.7.2 (the identity is created by the role)
  and `ocp4_workload_showroom_runtime_automation_enable: true`.
- `guid`, `student_user`, `student_ns`, `student_ns2`
- bastion connection details for host-based labs

`/user_data/user_data.yml` is mounted in the pod. These playbooks read it for
`openshift_cluster_ingress_domain` and `user`, falling back to `DOMAIN` /
`GUID` environment variables, so the same file works in the runner and when a
human runs it by hand.

The `validation_check` action plugin is available at
`/usr/share/ansible/plugins/action/`. It takes `check`, `pass_msg` and
`error_msg`, and is what the Showroom renders as the pass/fail result.

## Module map

Directory names must match the lab's module numbers, because the Showroom
content calls `/stream/validate/module-02` and so on.

| Directory | Lab module | Gate |
| --- | --- | --- |
| `module-02` | AI Quickstart RAG — Running the Demo | RAG UI answers; five knowledge bases loaded |
| `module-03` | AI Quickstart RAG — Selling the Agentic Story | RAG stack healthy (same infrastructure as module 2) |
| `module-04` | AI Quickstart IT Self Service — Selling the Demo | ITSS app healthy; Webmail serving; demo inbox readable |
| `module-07` | Secure Agent Workspace — A Governed Personal Assistant | SAW app healthy; workspace VM running |

`solve.yml` is omitted where there is nothing to apply. The Showroom only
shows a Solve button when the stage exists, so an absent file is a deliberate
statement, not an oversight.

## Conventions

- **Validate is read-only.** It runs on demand and may run repeatedly; it must
  never change the environment it is checking.
- **Setup is idempotent.** It runs on every page load.
- **Bounded retries.** Every wait has a finite retry budget and fails with a
  message naming the component, the observed state, and the likely cause.
- **Assert the learner-visible outcome**, not internal plumbing, wherever the
  two differ.
- **No transient conditions.** Do not fail on a condition that clears itself
  (Argo CD `InvalidSpecError` during bootstrap is the standing example); wait
  for the terminal signal instead.

## Adding a module

1. Create `module-NN/` with `setup.yml` and/or `validate.yml`.
2. Build the inventory in a first play targeting `localhost`, then operate with
   `kubernetes.core.k8s_info` (defaults set `kubeconfig: {{ k8s_kubeconfig }}`).
3. Finish with `validation_check` and a checklist-style `error_msg`.
4. Tag a new content ref and point the catalog item at it — see
   `docs/e2e/runtime-automation.md`.
