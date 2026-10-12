# Handoff: AgnosticV / CI — add IT Self Service to the LB2142 tenant

**For:** a session working in the `rhpds/agnosticv` repo (worktree branch
`ci/rh1-2027-lb2142-test-yamls`).
**From:** the `red-hat-1-quickstarts` showroom-content session.
**Date:** 2026-10-12

You have none of the context from the content repo. This doc carries it. Background decisions
live in `docs/adr/0002-modules-4-5-grounding.md` and
`publishing-house/spec/automation-manifest.yaml` of the `red-hat-1-quickstarts` repo.

## Goal

The lab "Selling with Red Hat QuickStarts" (CI **LB2142**) demos **pre-deployed** AI
Quickstarts to Solution Architects — learners *use* the apps, they deploy nothing. The tenant
must pre-deploy each QuickStart in its own namespace, each reached via its own Showroom tab.

- **Today:** the tenant deploys **RAG only**.
- **This handoff:** add **IT Self Service** alongside RAG, without disturbing RAG.
- **PPE Compliance Monitor:** a *separate* QuickStart, **on hold / TBD** — not in scope here.

## Files

- **Tenant to edit:** `rh1-2027/lb2142-ai-quickstarts-tenant/common.yaml` (in `rhpds/agnosticv`).
- **Reference to copy from:** `ai-quickstarts/ai-qs-it-self-service-tenant/common.yaml` — a
  working standalone IT Self Service tenant. Lift its workloads into LB2142.
- **Showroom content repo** wired into the tenant: `rhpds/red-hat-1-quickstarts` (this repo).

## Current LB2142 state (for reference)

- RAG via GitOps, namespace `user-{{ guid }}-rag`.
- `ocp4_workload_showroom_content_ui_config` tabs: `Terminal`, `OpenShift Console`,
  `OpenShift AI`, `RAG UI` (`https://{{ guid }}-rag-user-{{ guid }}-rag.{{ openshift_cluster_ingress_domain }}`).
- RAG model via LiteLLM/MaaS (`ai_quickstart_rag_llm_model`).

## Change set — IT Self Service

Grounded on `rh-ai-quickstart/it-self-service-agent`, deployed via **MakeOps**
(`quickstart_deploy_via_make`) in **demo/mock mode**. Copy these from
`ai-qs-it-self-service-tenant/common.yaml`:

1. **Extra model** — add an `ocp4_workload_litellm_virtual_keys` entry for model
   `llama-scout-17b` (alongside RAG's existing model). This is the "extra model."
2. **Namespace** — add `ocp4_workload_tenant_namespace` for `user-{{ guid }}-it-selfsvc`
   (quota ~12 CPU / 16Gi as in the reference tenant). Keep it **separate** from
   `user-{{ guid }}-rag` so the two apps don't collide.
3. **App workload** — add `quickstart_deploy_via_make`:
   - repo `github.com/rh-ai-quickstart/it-self-service-agent` (reference tenant pins `v0.0.13`)
   - `NAMESPACE: user-{{ guid }}-it-selfsvc`
   - `INSTALL_MODE: "demo"` (mock-eventing + mock-ServiceNow + Greenmail; no Knative/Kafka)
   - LLM wired to `{{ litellm_api_endpoint }}/v1` with the `llama-scout-17b` virtual key
4. **Webmail tab** — append to the `ui-config` `tabs:` block:
   ```yaml
   - name: Webmail
     url: "https://test-email-server-ui-user-{{ guid }}-it-selfsvc.{{ openshift_cluster_ingress_domain }}"
   ```
   The module content refers to this tab by the exact name **"Webmail"** — keep the name stable.

## Guardrails / definition of done

- RAG = GitOps, IT Self Service = MakeOps — both coexist in one tenant.
- Each app in its **own namespace**: `user-{{ guid }}-rag`, `user-{{ guid }}-it-selfsvc`.
- Both models provisioned via MaaS/LiteLLM virtual keys (RAG's existing one + `llama-scout-17b`).
- Tab names in the tenant `ui-config` must match the names the Showroom modules reference
  (`RAG UI`, `Webmail`).
- Test on `ci/rh1-2027-lb2142-test-yamls`; **RAG must keep working unchanged.**

## Not in scope here

- **PPE Compliance Monitor** — separate QuickStart, on hold (TBD).
- Writing the Module 4 Showroom `.adoc` content — that happens in `red-hat-1-quickstarts`
  *after* IT Self Service is reachable in the tenant.
