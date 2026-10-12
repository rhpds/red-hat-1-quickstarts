# Module 5: AI Quickstart PPE Compliance Monitor — Selling the Demo

> **Status: ON HOLD (TBD).** A separate QuickStart, decoupled from IT Self Service and paused
> for now. When resumed: grounded on `rh-ai-quickstart/multimodal-compliance-monitor`, adapting
> the existing `rh-ai-qs-showroom/showroom-ai-quickstart-multimodal-monitor` lab, deployed on the
> OpenVINO/CPU profile. See `docs/adr/0002-modules-4-5-grounding.md`.

### Brief Overview

Participants demo an already-deployed multimodal PPE compliance monitor: a React dashboard
streaming video with live object-detection overlays, plus a chat pane for natural-language
questions about what the camera sees. This is the most *visual* demo in the lab — bounding
boxes on a safety video land instantly with a customer. A strong adapt-from-showroom
candidate (the upstream lab already exists) and it runs **GPU-free**.

### Audience and Time

- **Target personas:** Red Hat Solution Architects, Red Hat One attendees
- **Prerequisites for this module:** Module 1 (what a QuickStart is); access to the pre-deployed PPE monitor via its Showroom tab
- **Estimated duration:** 20 minutes

### Learning Objectives

- Run the pre-deployed PPE Compliance Monitor dashboard as a customer demo
- Narrate live object detection (bounding boxes on the safety video) as the visual hook
- Use the chat pane to ask about what the camera sees (e.g. people without hard hats)
- Position the workplace-safety / operational-compliance value and tie it back to Red Hat OpenShift AI

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | The customer story: real-time, proactive safety monitoring | 4 min |
| 2 | Watch it detect: the dashboard and live bounding boxes | 8 min |
| 3 | Ask it questions: multimodal chat over the video | 4 min |
| 4 | The sales narrative and OpenShift AI tie-back | 4 min |

### Detailed Steps

1. Frame the business problem: manual safety monitoring is reactive and misses events; this QuickStart watches continuously and flags PPE/compliance issues in real time.
2. Open the dashboard tab. The seeded rooftop PPE video auto-streams with live bounding-box overlays and real-time safety summaries — no setup, no video to supply (ships with the app).
3. Narrate the detection: point out the overlays tracking people/PPE, and the running summary. This is the visual "wow."
4. Use the chat pane to ask about the scene (e.g. "how many people without hard hats?") — the multimodal + conversational insight beat; answered via the remote MaaS LLM.
5. Deliver the sales narrative: proactive vs reactive safety, manufacturing/facilities use cases; close on Red Hat OpenShift AI as the platform that runs vision + LLM together on the customer's own feeds.

**Cut from the upstream lab:** the `02-accessing-the-cluster` plumbing, the `06-train-a-yolo-model` (Label Studio / training) depth, and most of `04/05` add-source/scenario-switching — keep only what sells. Mirror how RAG cut the Kubeflow page.

### Key Takeaways

- Live bounding boxes on a safety video are the most immediate visual hook in the lab
- Multimodal + conversational: the system both *sees* and *answers questions about* what it sees
- Proactive, continuous monitoring is the value; it runs on Red Hat OpenShift AI on the customer's own feeds

### Infrastructure Notes

Pre-deployed per tenant via **GitOps/Helm on the OpenVINO (CPU) profile** (`make deploy-openvino`) — **required** because the spec has `gpu_nodes: 0`; the chart defaults to KServe/GPU and must be overridden. Ships its own sample PPE video + detection models (streamed in-cluster via MediaMTX), so no external feeds needed. Detection runs on CPU (OVMS, ~5–8 CPU / 10–16Gi); chat uses the remote MaaS LLM. Own namespace, separate from RAG and IT Self Service. Reached via a dedicated Showroom tab (dashboard Route). No deployment or `oc` steps performed by participants.
