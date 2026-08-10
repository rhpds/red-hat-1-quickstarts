# Module 2: Secure Agent Workspace — Deploy & Explore

### Brief Overview

This module puts participants hands-on with the first of the lab's two featured QuickStarts, Secure Agent Workspace (https://github.com/validatedpatterns-sandbox/secure-agent-workspace). Participants deploy the QuickStart onto their pre-provisioned Red Hat OpenShift cluster and explore the resulting environment, building the foundation for the security and governance deep dive in Module 3.

### Audience and Time

- **Target personas:** Red Hat Solution Architects, Red Hat One attendees
- **Prerequisites for this module:** Completion of Module 1; pre-provisioned Red Hat OpenShift cluster with Red Hat OpenShift AI installed; registry/network access pre-staged for the Secure Agent Workspace QuickStart
- **Estimated duration:** 20 minutes

### Learning Objectives

- Deploy the Secure Agent Workspace QuickStart to provision a governed, secure environment for AI agents on OpenShift
- Identify the components the QuickStart provisions and how they fit together in the deployed environment

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Introduce Secure Agent Workspace: purpose and architecture | 5 min |
| 2 | Deploy the QuickStart | 10 min |
| 3 | Explore the deployed environment | 5 min |

### Detailed Steps

1. Introduce the Secure Agent Workspace QuickStart: what customer problem it solves (a governed, secure workspace for AI agents on OpenShift) and where it fits in a sales conversation.
2. Review the QuickStart's deploy process as documented in its upstream repository, and confirm the lab environment has the prerequisites pre-staged (registry/network access, base namespaces).
3. Run the QuickStart's deploy process against the pre-provisioned cluster, following the upstream repo's documented deployment method.
4. Observe the deployment complete and verify the expected resources (namespaces, workloads) are present in the Red Hat OpenShift console.
5. Explore the deployed Secure Agent Workspace environment at a high level — its layout and the components visible from the console — to prepare for the governance deep dive in Module 3.

### Key Takeaways

- Secure Agent Workspace packages a governed, secure environment for running AI agents on OpenShift as a repeatable, demo-ready deployment
- The QuickStart's deploy process mirrors what a customer would run themselves, making it a credible artifact for a live demo
- Understanding the deployed environment's layout is a prerequisite for explaining its security and governance controls in the next module

### Infrastructure Notes

Requires registry/network access pre-staged for validatedpatterns-sandbox/secure-agent-workspace, and confirmation that the QuickStart's own deploy automation (Helm/GitOps per its upstream repo) runs unattended in the lab environment, per the design spec's automation requirements.
