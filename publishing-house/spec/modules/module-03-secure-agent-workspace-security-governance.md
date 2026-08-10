# Module 3: Secure Agent Workspace — Security & Governance Deep Dive

### Brief Overview

Building on the Secure Agent Workspace deployment from Module 2, this module goes deeper into the security and governance controls the QuickStart configures — specifically RBAC and network policy — so participants can speak to and demonstrate these controls credibly in a customer conversation.

### Audience and Time

- **Target personas:** Red Hat Solution Architects, Red Hat One attendees
- **Prerequisites for this module:** Completion of Module 2 (Secure Agent Workspace deployed and explored)
- **Estimated duration:** 20 minutes

### Learning Objectives

- Configure the security and governance controls (RBAC, network policy) built into the Secure Agent Workspace QuickStart
- Explain how these controls address customer concerns about running AI agents securely on shared infrastructure

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Review the governance model: RBAC and network policy | 6 min |
| 2 | Inspect and configure RBAC controls | 7 min |
| 3 | Inspect and configure network policy controls | 7 min |

### Detailed Steps

1. Review the security and governance model that Secure Agent Workspace applies to the environment deployed in Module 2 — what it constrains and why that matters to a customer evaluating AI agent workloads.
2. Inspect the RBAC roles and bindings the QuickStart provisions, using the Red Hat OpenShift console or CLI, and identify which personas/service accounts each role is scoped to.
3. Adjust or exercise an RBAC control per the QuickStart's documented configuration options, and observe the resulting change in access.
4. Inspect the network policies the QuickStart provisions, and identify which traffic paths are permitted versus restricted.
5. Adjust or exercise a network policy control per the QuickStart's documented configuration options, and observe the resulting change in connectivity.
6. Summarize how these controls together support a "governed, secure environment" narrative for a customer audience.

### Key Takeaways

- Secure Agent Workspace's value proposition rests on concrete, inspectable RBAC and network policy controls, not just marketing claims
- Being able to show — not just describe — these controls strengthens a customer demo
- These controls map to common customer objections about securely running AI agents on shared OpenShift infrastructure

### Infrastructure Notes

Uses the Secure Agent Workspace environment deployed in Module 2; no additional deployment required. Relies on the RBAC and network policy configuration options documented in the upstream repository (validatedpatterns-sandbox/secure-agent-workspace).
