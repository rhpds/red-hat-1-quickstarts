# Selling with Red Hat QuickStarts: A Hands-On Tour for Solution Architects

<!-- This file is the design document for your lab or demo. -->
<!-- Fill in each section below, or run /rhdp-publishing-house to have the intake skill help. -->
<!-- Sections marked with [brackets] are placeholders — replace with real content. -->
<!-- The validation gate checks for all required sections before submission. -->

## Overview

Red Hat One Solution Architects need a fast, credible way to demo Red Hat QuickStarts to customers and use them to sell OpenShift AI and related products, shortening the sales cycle. This lab walks SAs through what a QuickStart is and how it works, then puts them hands-on with two new QuickStarts — Secure Agent Workspace and Private AI Coding Assistant — before wrapping up with a tour of the rest of the QuickStart family and concrete next steps for using QuickStarts in customer conversations. Participants will deploy and exercise both QuickStarts on OpenShift, and leave able to position and demo the full QuickStart catalog to a customer.

## Target Audience

- **Role:** Red Hat Solution Architects (SAs), Red Hat One attendees
- **Experience level:** Intermediate
- **What they already know:** Core Red Hat OpenShift and OpenShift AI concepts; comfortable navigating the OpenShift console; general customer-facing solution architecture experience
- **What they don't know:** How Red Hat QuickStarts work mechanically as a selling/demo mechanism; the specifics of the Secure Agent Workspace and Private AI Coding Assistant QuickStarts; how to position the broader QuickStart family in a sales conversation

## Prerequisites

- Working familiarity with Red Hat OpenShift and Red Hat OpenShift AI fundamentals (console navigation, basic project/pod concepts)
- Access to the pre-provisioned lab OpenShift environment (provisioned automatically for the lab)

<!-- Can the lab validate these automatically? No — trust-based; assumed from the SA role and Red Hat One attendance. -->

## Learning Objectives

1. Explore the Red Hat QuickStarts catalog and identify how QuickStarts accelerate customer proofs-of-concept
2. Deploy the Secure Agent Workspace QuickStart to provision a governed, secure environment for AI agents on OpenShift
3. Configure the security and governance controls (RBAC, network policy) built into the Secure Agent Workspace QuickStart
4. Deploy the Private AI Coding Assistant QuickStart in an air-gapped OpenShift environment
5. Demonstrate the Private AI Coding Assistant's air-gapped, in-cluster AI-assisted development workflow to a customer audience
6. Analyze the broader QuickStart family to match customer use cases to the right QuickStart in a sales conversation

<!-- Scale to duration: up to 3 objectives per 45 min of content. Start with action verbs: Configure, Deploy, Create, Implement, Troubleshoot, Monitor, Scale. Each should be testable. NOT: Understand, Learn, Know. -->

## Content Type

Lab (hands-on)

## Products & Technologies

- Red Hat OpenShift Container Platform
- Red Hat OpenShift AI
- Red Hat QuickStarts — Secure Agent Workspace (https://github.com/validatedpatterns-sandbox/secure-agent-workspace)
- Red Hat QuickStarts — Private AI Coding Assistant (https://github.com/rh-ai-quickstart/private-coding-assistant)

<!-- Use official names: "Red Hat OpenShift", not "OpenShift". List upstream projects separately. -->

## Module Map

| Module | Title | Duration |
|--------|-------|----------|
| 1 | Selling with Red Hat QuickStarts: What Is a QuickStart? | 10 min |
| 2 | Secure Agent Workspace — Deploy & Explore | 20 min |
| 3 | Secure Agent Workspace — Security & Governance Deep Dive | 20 min |
| 4 | Private AI Coding Assistant — Deploy | 15 min |
| 5 | Private AI Coding Assistant — Air-Gapped Dev Workflow | 15 min |
| 6 | QuickStart Family Recap & Next Steps | 10 min |
| — | **Total hands-on** | **1.5 hours** |
| — | Intro / presentation | Included in Module 1 |
| — | **Total lab** | **~1.5 hours** |

<!-- Each module 10-30 min. Total: lab 1-4 hours, demo 15-45 min. Modules should build on each other. -->

## Difficulty Level

Intermediate

## Environment

**Learner view:** Participants start with a pre-provisioned Red Hat OpenShift cluster with Red Hat OpenShift AI installed. Module 1 introduces the QuickStarts catalog and lab structure. In Modules 2–3, participants deploy and explore the Secure Agent Workspace QuickStart from its upstream repository. In Modules 4–5, participants deploy the Private AI Coding Assistant QuickStart in an air-gapped configuration and use it to complete an AI-assisted coding task. Module 6 recaps the full QuickStart family with name, description, use case, value prop, and links for each, plus a call to action / next steps for using QuickStarts with customers.

**Automation needed:** Yes

- Provision Red Hat OpenShift AI operator and base namespaces/projects ahead of the session
- Pre-stage or grant registry/network access needed to deploy the Secure Agent Workspace QuickStart (validatedpatterns-sandbox/secure-agent-workspace)
- Pre-stage the Private AI Coding Assistant QuickStart (rh-ai-quickstart/private-coding-assistant), including any models/images required to run it air-gapped
- Confirm each QuickStart's own deploy automation (Helm/GitOps per its upstream repo) works unattended in the lab environment

## Infrastructure Requirements

- **Cloud provider:** TBD — confirmed in infrastructure phase
- **Cluster type:** TBD — confirmed in infrastructure phase
- **OCP version:** TBD — confirmed in infrastructure phase
- **Topology:** TBD — confirmed in infrastructure phase
- **Sizing:** TBD — confirmed in infrastructure phase
- **Automation approach:** TBD — confirmed in infrastructure phase
- **AI/MaaS:** TBD — confirmed in infrastructure phase
- **External services:** TBD — confirmed in infrastructure phase
- **AAP version:** TBD — confirmed in infrastructure phase
- **Non-GA products:** TBD — confirmed in infrastructure phase

<!-- Not all fields must be known at intake. "TBD, estimating ~X" is fine. -->

## Assessment Strategy (Optional)

Skipped — classic Showroom lab without solve/validate automation. Success is trust-based: participants complete each module's steps and can demo the resulting QuickStart deployments.
