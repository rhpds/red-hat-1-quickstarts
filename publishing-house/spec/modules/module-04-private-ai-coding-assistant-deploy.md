# Module 4: Private AI Coding Assistant — Deploy

### Brief Overview

This module transitions participants to the lab's second featured QuickStart, Private AI Coding Assistant (https://github.com/rh-ai-quickstart/private-coding-assistant). Participants deploy the QuickStart in an air-gapped OpenShift configuration, setting up for the hands-on air-gapped development workflow demo in Module 5.

### Audience and Time

- **Target personas:** Red Hat Solution Architects, Red Hat One attendees
- **Prerequisites for this module:** Completion of Modules 1–3; pre-provisioned Red Hat OpenShift cluster with Red Hat OpenShift AI installed; Private AI Coding Assistant QuickStart and its required models/images pre-staged for air-gapped operation
- **Estimated duration:** 15 minutes

### Learning Objectives

- Deploy the Private AI Coding Assistant QuickStart in an air-gapped OpenShift environment
- Identify the components the QuickStart provisions and how air-gapped operation changes the deployment compared to a connected deployment

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Introduce Private AI Coding Assistant: purpose and air-gapped architecture | 4 min |
| 2 | Deploy the QuickStart in air-gapped mode | 8 min |
| 3 | Verify the deployment | 3 min |

### Detailed Steps

1. Introduce the Private AI Coding Assistant QuickStart: what customer problem it solves (in-cluster, private AI-assisted development without external network dependency) and where it fits in a sales conversation.
2. Review the QuickStart's deploy process as documented in its upstream repository, noting what differs for air-gapped operation (e.g., pre-staged models/images rather than pulling from external sources).
3. Confirm the lab environment has the air-gapped prerequisites pre-staged, per the automation requirements defined for this lab.
4. Run the QuickStart's deploy process against the pre-provisioned cluster in its air-gapped configuration, following the upstream repo's documented deployment method.
5. Observe the deployment complete and verify the expected resources (namespaces, workloads, model artifacts) are present in the Red Hat OpenShift console, confirming no external network calls were required.

### Key Takeaways

- Private AI Coding Assistant packages an in-cluster, air-gapped AI-assisted development environment as a repeatable, demo-ready deployment
- Air-gapped deployment requires pre-staging models and images that a connected deployment would otherwise pull on demand
- A successful air-gapped deployment is itself a talking point for customers with strict network isolation requirements

### Infrastructure Notes

Requires the Private AI Coding Assistant QuickStart (rh-ai-quickstart/private-coding-assistant) and any models/images it needs pre-staged ahead of the session to run air-gapped, and confirmation that the QuickStart's own deploy automation runs unattended in the lab environment, per the design spec's automation requirements.
