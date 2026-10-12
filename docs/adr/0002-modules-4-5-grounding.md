# 2. Grounding for Modules 4 (IT Self Service) and 5 (PPE), and multi-QuickStart tenant

Date: 2026-10-12

## Status

Accepted

## Context

After the flagship RAG modules (2–3), the lab adds two more "sell the pre-deployed
demo" modules: Module 4 (IT Self Service) and Module 5 (PPE Compliance Monitor). Each
needed a concrete upstream grounding, and the lab environment needed a way to host more
than one QuickStart per tenant.

**Module 4 — IT Self Service.** The name mapped to two upstream repos:
`it-self-service-agent` (a laptop-refresh self-service agent that "meets employees where
they are" — CLI/Slack/email, no browser portal) and `speeding-up-ticket-resolution` (a
Zammad persona portal that embeds `it-self-service-agent` as a git submodule). The reviewer
feedback had named ticket-resolution, and its Zammad portal is the stronger *visual* demo.
However, investigation found that `it-self-service-agent` already has **both** a Showroom
lab (`rhpds/showroom-ai-quickstart-it-self-service-agent`) **and** an AgnosticV tenant
(`ai-qs-it-self-service-tenant`, deploying in `demo` mode with a Webmail tab), whereas
ticket-resolution has neither — both would be built from scratch, plus a Zammad stack.

The `it-self-service-agent` demo surface is weak for selling: the only app UI is a Greenmail
*test-email* webmail box, LLM replies take 10–30s, and downstream systems are mocked. One
upstream page is pure `oc`/pods plumbing.

**Module 5 — PPE.** `multimodal-compliance-monitor` has a real Showroom lab
(`rh-ai-qs-showroom/showroom-ai-quickstart-multimodal-monitor`), ships its own sample video
and detection models, is visually strong (live bounding boxes), and — critically — can run
without GPU via the OpenVINO/CPU serving profile. The lab spec has `gpu_nodes: 0`.

**Tenant.** RAG deploys via GitOps; `it-self-service-agent` deploys via its upstream `make`
targets ("MakeOps", the `quickstart_deploy_via_make` AgnosticV workload). The LB2142 tenant
must host multiple QuickStarts at once.

## Decision

- **Module 4 grounds on `it-self-service-agent`**, not `speeding-up-ticket-resolution`. The
  existing Showroom lab + AgnosticV tenant outweigh the better-looking Zammad portal, given
  the from-scratch cost of the alternative. The weak demo surface is mitigated in the
  module design (mandatory, not optional): pre-warm the model and pre-send the first email,
  run a tightly scripted laptop-refresh flow, switch personas to prove policy/regional
  logic, cut the `oc`/pods page, and lean on the value narrative.
- **Module 5 grounds on `multimodal-compliance-monitor`**, adapting its existing Showroom
  lab, and is **pinned to the OpenVINO/CPU profile** (`make deploy-openvino`) because the
  tenant has no GPU nodes. It is the most visual demo in the lab.
- **Both modules keep the RAG delivery model:** app pre-deployed per tenant, reached via its
  own Showroom tab, no deploy/login/`oc` steps for participants.
- **The LB2142 tenant hosts multiple QuickStarts side by side.** GitOps (RAG) and MakeOps
  (IT Self Service) coexist. Build-phase work: add the extra model (`llama-scout-17b`
  alongside RAG's) to MaaS/LiteLLM, add the MakeOps workload to the tenant, and give each
  QuickStart its **own namespace** (`user-{guid}-rag`, `user-{guid}-it-selfsvc`, and a PPE
  namespace) so they do not collide.
- One module each (not two like RAG). `.adoc` content is deferred until each app is
  pre-deployed in the combined tenant.

## Consequences

- Module 4 carries real demo risk: latency and a bare webmail surface. It lives or dies on
  pre-warming and tight scripting; a free-roam demo will fall flat. If the surface proves
  too weak in practice, reopening the `speeding-up-ticket-resolution` option is the fallback
  (at the cost of building its showroom + Zammad tenant).
- Module 5 must not be left on the chart's default KServe/GPU profile, or it will fail to
  schedule on a `gpu_nodes: 0` cluster.
- The tenant's AgnosticV config grows to deploy three apps via two mechanisms; namespace
  isolation and model provisioning become part of the build-phase definition of done.
- The Zammad comparison that informed choosing against ticket-resolution was not verified
  against an actual lab (none exists); the decision rests on the ITSS interaction surface
  plus the existing-assets advantage.
