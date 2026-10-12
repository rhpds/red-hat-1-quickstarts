# Module 3: AI Quickstart RAG — Selling the Agentic Story

### Brief Overview

Part 2 of 2 on the flagship AI Quickstart RAG. Having shown grounded answers in Module 2, participants now run the *agentic* RAG demo — the model that plans, reasons, and calls tools — and the live web-search "wow" moment that proves the system can answer beyond its training cutoff. The module closes on the part that matters most to an SA: the customer sales narrative. How to frame the demo, what to highlight, which questions customers ask, and how to tie it all back to Red Hat OpenShift AI. This is a selling module first and a technical module second.

### Audience and Time

- **Target personas:** Red Hat Solution Architects, Red Hat One attendees
- **Prerequisites for this module:** Module 2 (RAG UI orientation, direct-chat demo, FantaCo framing)
- **Estimated duration:** 20 minutes

### Learning Objectives

- Run the agentic RAG demo and show the agent calling tools across multiple steps
- Demonstrate the live web-search tool answering a question beyond the model's training cutoff
- Analyze when to position direct RAG vs agentic RAG in a customer conversation
- Deliver a concise customer sales narrative that ties the RAG QuickStart back to Red Hat OpenShift AI

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | Switch to Agent mode: the model that uses tools | 4 min |
| 2 | The "wow": live web search beyond the training cutoff | 7 min |
| 3 | Direct vs agentic — positioning it for the customer | 4 min |
| 4 | The sales narrative: talking points and tie-back | 5 min |

### Detailed Steps

1. Switch *Processing mode* to *Agent-based* and show how the agent plans, retrieves, and surfaces its reasoning trace (tool calls and results as collapsible steps) — the "it's doing real work" moment.
2. Run the web-search scenario: ask "Who won the Super Bowl in 2025?" with web search off (stale/declined answer), then on (live `web_search` tool call → correct, grounded answer). This is the headline demo beat — live data the base model never saw.
3. Contrast direct vs agentic for a customer: direct = fast, single-turn, citable policy lookups; agentic = multi-step synthesis and live external data. Frame each against a customer use case.
4. Deliver the sales narrative: the business problem (trustworthy answers over proprietary + live knowledge), what to show first, the common customer questions, and the tie-back to Red Hat OpenShift AI and MaaS as the platform that makes it real and supportable.
5. Give participants a one-paragraph "how I'd pitch this" recap they can reuse in front of a customer.

### Key Takeaways

- Agentic RAG + web search is the demo's "wow" — live, grounded answers beyond the model's training data
- The SA's job is narration and framing, not clicking through features — the sales story is the deliverable
- The close is always the tie-back: this runs on Red Hat OpenShift AI, which is what the customer is actually buying

### Infrastructure Notes

Same pre-deployed AI Quickstart RAG instance as Module 2, reached via the **RAG UI** tab. The web-search tool requires the agent's Tavily search integration to be configured in the environment (set via AgnosticV `ai_quickstart_tavily_search_key`). No deployment steps performed by participants. **Verify against the live environment:** confirm the web-search tool is enabled and the Super Bowl scenario behaves as written before the event.
