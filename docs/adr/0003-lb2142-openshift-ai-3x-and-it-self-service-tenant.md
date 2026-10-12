# 3. LB2142 tenant: add IT Self Service, and move OpenShift AI to 3.5

Date: 2026-10-12

## Status

Accepted

## Context

ADR 0002 decided the LB2142 "Selling with AI Quickstarts" tenant would host multiple
pre-deployed QuickStarts side by side. RAG (GitOps) was already in the tenant; this change
adds **IT Self Service** (MakeOps, `quickstart_deploy_via_make`, `INSTALL_MODE=demo`)
alongside it, lifting the workloads from the standalone `ai-qs-it-self-service-tenant`.

Two things surfaced during integration that were not obvious from the handoff:

- **There is no "extra model."** The handoff said to add `llama-scout-17b` as a second model
  "alongside RAG's." But RAG's existing model already *is* `llama-scout-17b`. Both QuickStarts
  want the same model, so a single LiteLLM virtual key serves both.
- **The two base clusters disagreed on OpenShift AI (RHOAI).** RAG's cluster pinned
  `stable-2.25` with ModelMesh Managed / KServe Removed; the IT Self Service cluster pinned
  `stable-3.3` with KServe + ModelRegistry + ModelMesh Managed. The ask was to "update to the
  latest versions and make a superset."

The superset ask collides with reality on RHOAI 3.x. Investigation of the live operator
schema (`opendatahub-operator` DSC v2 types) and the `ocp4_workload_openshift_ai` role found:

- **ModelMesh Serving no longer exists** as a DataScienceCluster component in 3.x. Setting
  `modelmeshserving: Managed` on a 3.x channel is silently pruned by the API server — it never
  runs. So a *literal* superset (KServe + ModelMesh + ModelRegistry all Managed) is impossible
  on 3.x; it is only possible by staying on 2.x.
- **KServe runs in RawDeployment mode on 3.x** — the embedded Serverless/Service Mesh
  dependency is gone; no extra deployment-mode vars are needed.
- **The dashboard moves to the Kubernetes Gateway API.** Its host becomes
  `data-science-gateway.<ingress>`; the old `rhods-dashboard-redhat-ods-applications.<ingress>`
  route is gone, so any hardcoded dashboard URL breaks.

Neither RAG nor IT Self Service serves a model in-cluster — both use the remote MaaS/LiteLLM
endpoint — so KServe/ModelRegistry are not strictly required by either app. The latest
released RHOAI minor as of this date is 3.5, but **RAG is already proven on `stable-3.4`** in
the standalone `ai-qs-rag-cluster` config — a tested target rather than an assumption.

The author chose to modernize off 2.25 onto the RHOAI 3.x line, pinned to the proven `stable-3.4`.

## Decision

- **Add IT Self Service to the LB2142 tenant** via `quickstart_deploy_via_make`
  (`it-self-service-agent` pinned `v0.0.13`, `INSTALL_MODE=demo`), in its own namespace
  `user-{{ guid }}-it-selfsvc`, reached via a new **Webmail** Showroom tab. RAG keeps its
  GitOps delivery and `user-{{ guid }}-rag` namespace.
- **One shared model and virtual key** (`llama-scout-17b`) serves both apps — not a second
  model. The handoff's "extra model" was a misread.
- **The shared tenant quota is the sum** of both apps (52 CPU / 80Gi memory / 112Gi storage),
  because the tenant uses one shared ClusterResourceQuota across all its namespaces (per-suffix
  quota overrides are ignored in CRQ mode). LimitRange is set per-suffix.
- **OpenShift AI moves to `stable-3.4`** on the shared cluster (the channel proven with RAG),
  with **KServe: Managed** and
  **ModelRegistry: Managed** and **ModelMesh: Removed** (forced — gone in 3.x). This is the
  "superset spirit" adapted to what 3.x actually supports, and it matches the known-good IT
  Self Service 3.x cluster config.
- **The Showroom "OpenShift AI" tab is re-pointed** to
  `https://data-science-gateway.{{ openshift_cluster_ingress_domain }}` for the Gateway API.
- **Showroom collection is bumped to `v1.8.0`** (latest) on both the tenant and the cluster.

## Consequences

- **RAG is already proven on `stable-3.4`** (standalone `ai-qs-rag-cluster`), which retires the
  main risk of the 2.x → 3.x jump. The residual risk is the *combined* tenant: KServe +
  ModelRegistry are turned on (off in the proven RAG config) and the dashboard tab is re-pointed
  — these still need an end-to-end check in CI. If the combination misbehaves, the fallback is
  to pin the shared cluster back to `stable-2.25` and restore the literal superset (which forgoes
  3.x).
- The `it-self-service-agent` pin stays at `v0.0.13`. `v0.0.15` exists (swaps observability
  Langfuse → MLflow, which may change demo-mode deploy dependencies); bumping is deferred until
  a demo deploy is re-verified.
- Showroom `v1.8.0` crosses the `v1.7.0` Traefik v3 / routing change, so both lab guides need a
  rendering re-test.
- KServe + ModelRegistry are Managed despite neither app needing in-cluster serving — a small
  amount of dead weight accepted for compatibility with the standalone IT config.
- Work lands on branch `ci/rh1-2027-lb2142-test-yamls` in `rhpds/agnosticv`; CI (`test.yaml`)
  validates the combined tenant. The `.adoc` content for Module 4 is written in this repo only
  after IT Self Service is reachable in the tenant.
