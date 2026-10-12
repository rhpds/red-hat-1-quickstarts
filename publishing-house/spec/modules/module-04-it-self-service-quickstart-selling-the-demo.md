# Module 4: AI Quickstart IT Self Service — Selling the Demo

> **Status: planned, not yet written.** Grounded on `rh-ai-quickstart/it-self-service-agent`
> (laptop-refresh self-service agent). Content will be adapted from the existing
> `rhpds/showroom-ai-quickstart-it-self-service-agent` lab once the app is pre-deployed
> in the combined LB2142 tenant. See `docs/adr/0002-modules-4-5-grounding.md`.

### Brief Overview

Participants demo an already-deployed IT Self Service agent that resolves an employee's
laptop-refresh request end to end. The agent "meets employees where they are" — here, over
email — so the demo runs through a test inbox: an employee emails a request, the routing
agent replies, offers region-specific laptop options, and files the (mocked) ServiceNow
ticket. This is a *selling* module: the value is the automated, policy-aware resolution
story, not the plumbing.

**Demo-surface caveat (drives the whole module design):** the only app surface is a
Greenmail *test-email* web UI (a user dropdown + compose box), and LLM replies take
10–30 seconds. The module must be a tightly scripted, pre-warmed demo — not a free-roam
exploration. Mitigations below are mandatory, not optional.

### Audience and Time

- **Target personas:** Red Hat Solution Architects, Red Hat One attendees
- **Prerequisites for this module:** Module 1 (what a QuickStart is); access to the pre-deployed IT Self Service agent via the Webmail tab
- **Estimated duration:** 20 minutes

### Learning Objectives

- Run the pre-deployed IT Self Service agent as a customer demo via the Webmail tab
- Narrate the laptop-refresh workflow: request → options → approval → ticket created
- Show how the agent applies policy (eligibility) and regional catalogs per persona
- Position the value — faster resolution, higher compliance, fewer rejected requests — and tie it back to Red Hat OpenShift AI

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | The customer story: self-service that meets employees in their inbox | 4 min |
| 2 | Run the laptop-refresh demo (pre-warmed, scripted) | 9 min |
| 3 | Switch personas to show policy + regional catalogs | 3 min |
| 4 | The sales narrative and OpenShift AI tie-back | 4 min |

### Detailed Steps

1. Frame the business problem: IT service desks are slow and inconsistent; this agent automates routine requests end to end, applying policy automatically. (Adapt value props from the upstream `index`/`01-overview` pages.)
2. **Pre-warm:** before narrating, send the first email so the model is loaded and the first visible reply is fast. Open the **Webmail** tab.
3. Run the laptop-refresh flow as `alice.johnson@company.com` (eligible): "I'd like to see available laptop options" → agent lists options with specs/pricing → select an option → approve → agent creates the ticket and returns a ticket number.
4. Switch personas to show the agent's intelligence: a region difference (EMEA vs LATAM catalog) and/or an ineligible user — proving policy awareness, not a canned script.
5. Deliver the sales narrative: faster closure, higher compliance, fewer rejected requests; "meets users where they are" (email today, Slack/ServiceNow/web the same pattern); close on Red Hat OpenShift AI + MaaS as the platform.

**Cut from the upstream lab:** the `03-explore-deployment` page entirely (`oc login`, `oc get pods` — pure plumbing). Trim `04-going-further` to the extensibility/multi-channel talking points; drop eval/tracing/CLI depth.

### Key Takeaways

- The agent resolves a real request end to end, applying policy automatically — that's the sell
- "Meet employees where they are": email here, but the same agent pattern extends to Slack, ServiceNow, and web
- A pre-warmed, scripted demo hides the latency; narration and framing are the deliverable

### Infrastructure Notes

Pre-deployed per tenant via **MakeOps** (`quickstart_deploy_via_make`, repo `rh-ai-quickstart/it-self-service-agent`, `INSTALL_MODE: demo`) into its **own namespace** `user-{guid}-it-selfsvc` — separate from RAG's `user-{guid}-rag` so they don't collide. Deployed in demo/mock mode (mock-eventing, mock-ServiceNow, Greenmail); no Knative/Kafka. LLM via MaaS/LiteLLM (`llama-scout-17b`) — this is the "extra model" to add alongside RAG's. Reached via a **Webmail** Showroom tab (`test-email-server-ui-user-{guid}-it-selfsvc.{openshift_cluster_ingress_domain}`). No deployment or `oc` steps performed by participants.
