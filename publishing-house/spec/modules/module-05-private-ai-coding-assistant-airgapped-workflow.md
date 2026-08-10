# Module 5: Private AI Coding Assistant — Air-Gapped Dev Workflow

### Brief Overview

Building on the deployment from Module 4, this module has participants use the Private AI Coding Assistant to complete an AI-assisted coding task entirely within the air-gapped OpenShift environment, preparing them to demonstrate the workflow live to a customer audience.

### Audience and Time

- **Target personas:** Red Hat Solution Architects, Red Hat One attendees
- **Prerequisites for this module:** Completion of Module 4 (Private AI Coding Assistant deployed in air-gapped mode)
- **Estimated duration:** 15 minutes

### Learning Objectives

- Demonstrate the Private AI Coding Assistant's air-gapped, in-cluster AI-assisted development workflow to a customer audience

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Access the in-cluster coding assistant workflow | 4 min |
| 2 | Complete an AI-assisted coding task | 8 min |
| 3 | Frame the workflow for a customer demo | 3 min |

### Detailed Steps

1. Access the Private AI Coding Assistant's in-cluster development interface, as provided by the QuickStart deployed in Module 4.
2. Confirm the workflow operates entirely within the cluster, with no external network dependency, and note this as a key point for a customer demo.
3. Use the coding assistant to complete a representative AI-assisted development task per the QuickStart's documented usage pattern.
4. Observe the assistant's response and the resulting code change, confirming the workflow behaves as expected in the air-gapped environment.
5. Frame the workflow as a customer demo: identify the talking points that connect the observed behavior back to the customer's need for private, in-cluster AI-assisted development.

### Key Takeaways

- The Private AI Coding Assistant delivers an AI-assisted development experience without requiring external network access, addressing customer data-residency and isolation concerns
- Completing a real coding task in the environment gives SAs a concrete, repeatable demo moment rather than an abstract description
- This workflow, combined with the Module 4 deployment, forms a complete "deploy and demo" narrative for the QuickStart

### Infrastructure Notes

Uses the Private AI Coding Assistant environment deployed in Module 4; no additional deployment required. Relies on the in-cluster coding workflow and models/images pre-staged per the upstream repository (rh-ai-quickstart/private-coding-assistant).
