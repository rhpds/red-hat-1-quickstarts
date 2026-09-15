# Selling with Red Hat QuickStarts: A Hands-On Tour for Solution Architects

<!-- This file is the design document for your lab or demo. -->
<!-- Fill in each section below, or run /rhdp-publishing-house to have the intake skill help. -->
<!-- Sections marked with [brackets] are placeholders — replace with real content. -->
<!-- The validation gate checks for all required sections before submission. -->

## Overview

Red Hat One Solution Architects need a fast, credible way to demo Red Hat QuickStarts to customers and use them to sell OpenShift AI and related products, shortening the sales cycle. This is a sales-enablement lab, not a deployment lab: SAs learn what a QuickStart is and how to navigate the catalog to match a QuickStart to a customer use case, then practice running and narrating three pre-deployed AI Quickstarts — RAG, IT Self Service, and PPE Compliance Monitor — as customer-facing demos. An optional stretch module lets SAs with time remaining deploy a QuickStart end-to-end. Participants leave able to position and demo the QuickStart family to a customer.

## Target Audience

- **Role:** Red Hat Solution Architects (SAs), Red Hat One attendees
- **Experience level:** Intermediate
- **What they already know:** Core Red Hat OpenShift and OpenShift AI concepts; comfortable navigating the OpenShift console; general customer-facing solution architecture experience
- **What they don't know:** How Red Hat QuickStarts work mechanically as a selling/demo mechanism; the specifics of the AI Quickstart RAG, IT Self Service, and PPE Compliance Monitor QuickStarts; how to position the broader QuickStart family in a sales conversation

## Prerequisites

- Working familiarity with Red Hat OpenShift and Red Hat OpenShift AI fundamentals (console navigation, basic project/pod concepts)
- Access to the pre-provisioned lab OpenShift environment (provisioned automatically for the lab)

<!-- Can the lab validate these automatically? No — trust-based; assumed from the SA role and Red Hat One attendance. -->

## Learning Objectives

1. Explore the Red Hat QuickStarts catalog and identify how QuickStarts accelerate customer proofs-of-concept
2. Demonstrate the AI Quickstart RAG to a customer audience using a pre-deployed instance
3. Demonstrate the AI Quickstart IT Self Service to a customer audience using a pre-deployed instance
4. Demonstrate the AI Quickstart PPE Compliance Monitor to a customer audience using a pre-deployed instance
5. Analyze the broader QuickStart family to match customer use cases to the right QuickStart in a sales conversation

<!-- Scale to duration: up to 3 objectives per 45 min of content. Start with action verbs: Configure, Deploy, Create, Implement, Troubleshoot, Monitor, Scale. Each should be testable. NOT: Understand, Learn, Know. -->

## Content Type

Lab (hands-on)

## Products & Technologies

- Red Hat OpenShift Container Platform 4.21
- Red Hat OpenShift AI 3.5
- AI Quickstart RAG
- AI Quickstart IT Self Service
- AI Quickstart PPE Compliance Monitor

<!-- Use official names: "Red Hat OpenShift", not "OpenShift". List upstream projects separately. -->

## Module Map

| Module | Title | Duration |
|--------|-------|----------|
| 1 | Selling with Red Hat QuickStarts: What Is a QuickStart? | 15 min |
| 2 | AI Quickstart RAG — Selling the Demo | 20 min |
| 3 | AI Quickstart IT Self Service — Selling the Demo | 20 min |
| 4 | AI Quickstart PPE Compliance Monitor — Selling the Demo | 20 min |
| — | **Total core** | **1.25 hours** |
| 5 | Deploy a QuickStart (Optional/Stretch) | 20 min, if time allows |

<!-- Each module 10-30 min. Total: lab 1-4 hours, demo 15-45 min. Modules should build on each other. -->

## Difficulty Level

Intermediate

## Environment

**Learner view:** Participants start with a pre-provisioned Red Hat OpenShift cluster with Red Hat OpenShift AI installed, with the AI Quickstart RAG, AI Quickstart IT Self Service, and AI Quickstart PPE Compliance Monitor already deployed. Module 1 introduces the QuickStarts catalog and lab structure, with an optional walkthrough of demoing one of the featured QuickStarts to a customer. Modules 2–4 walk participants through using each pre-deployed QuickStart and narrating it as a customer demo — no deployment steps for participants. Module 5 is an optional stretch module where participants deploy a QuickStart (TBD) end-to-end, for SAs with time remaining.

**Automation needed:** Yes

- GitOps-based pre-deployment of AI Quickstart RAG, AI Quickstart IT Self Service, and AI Quickstart PPE Compliance Monitor into each tenant namespace ahead of the session (author is automating this via GitOps)
- Provision Red Hat OpenShift AI operator and base namespaces/projects ahead of the session

## Infrastructure Requirements

- **Cloud provider:** CNV
- **Cluster type:** Multinode (Sandbox API, Cluster/Tenant model — one shared cluster per event instance, each SA gets an isolated tenant namespace)
- **OCP version:** 4.21
- **Topology:** Shared-cluster — 12 concurrent tenants per cluster, 6–8 clusters planned for the RH1 event
- **Sizing:** 3 control plane (16 vCPU, 64GB RAM each); 6 workers (16 vCPU, 64GB RAM, 200GB disk each) — estimate, to be validated by infra review
- **Automation approach:** GitOps, pre-deploying all three QuickStarts per tenant namespace ahead of the session (author-owned automation, in progress)
- **AI/MaaS:** MaaS, open-source model tier (via Red Hat Developer Playground MaaS)
- **External services:** github.com, quay.io, Red Hat Developer Playground MaaS (model access, API key, subscription)
- **AAP version:** N/A — AAP not in products
- **Non-GA products:** None flagged yet — the three featured QuickStarts are moving to production as of this revision; will revisit closer to the event

<!-- Not all fields must be known at intake. "TBD, estimating ~X" is fine. -->

## Assessment Strategy (Optional)

Skipped — classic Showroom lab without solve/validate automation. Success is trust-based: participants complete each module's steps and can demo the resulting QuickStart deployments.
