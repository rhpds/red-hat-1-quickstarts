# Module 2: AI Quickstart RAG — Running the Demo

### Brief Overview

This is part 1 of 2 on the flagship AI Quickstart RAG, the lab's anchor demo. Participants open an already-deployed RAG chatbot through the **RAG UI** tab and run the core "grounded answers from company knowledge" demo: the FantaCo enterprise story, the pre-loaded knowledge bases, and direct chat that returns answers with source citations. The emphasis is on *showing the sales value* — accurate, grounded, citable answers over a customer's own documents — not on deployment or infrastructure. Adapted from the upstream `showroom-ai-quickstart-rag` lab, tightened and re-slanted toward selling.

### Audience and Time

- **Target personas:** Red Hat Solution Architects, Red Hat One attendees
- **Prerequisites for this module:** Module 1 (what a QuickStart is); access to the pre-deployed AI Quickstart RAG instance via the RAG UI tab
- **Estimated duration:** 20 minutes

### Learning Objectives

- Open and orient to the pre-deployed AI Quickstart RAG via the RAG UI tab
- Frame the FantaCo enterprise use case as a customer-relevant sales story
- Run the direct-chat RAG demo and show grounded answers with source citations
- Articulate the core value proposition: accurate, citable answers over a customer's own knowledge, with reduced hallucinations

### Lab Structure

| Section | Title | Duration |
|---------|-------|----------|
| 1 | The customer story: why FantaCo built a RAG chatbot | 4 min |
| 2 | Open the RAG UI and get oriented | 4 min |
| 3 | The knowledge bases behind the demo | 4 min |
| 4 | Run it: grounded answers with citations | 8 min |

### Detailed Steps

1. Set the sales scene with the FantaCo story — a large enterprise connecting employees to HR, Legal, Procurement, Sales, and TechSupport docs through one chat interface — and the business problem RAG solves (fast, accurate, grounded answers; fewer hallucinations).
2. Open the **RAG UI** tab in the right pane (no login, no route copying — it is pre-deployed per tenant). Tour the chat box and the left sidebar (processing mode, document collections, sampling controls).
3. Show the pre-loaded FantaCo knowledge bases (e.g., `hr-vector-db-v1-0`) and, optionally, demonstrate uploading a customer's own document to create a custom knowledge base — the "bring your own data" selling beat.
4. Run the direct-chat demo: first ask a question with no knowledge base (general answer, no citations), then select a knowledge base and ask the same class of question (e.g., "What is the vacation policy for full-time employees?") to show a grounded answer with a *Searched vector stores* / *File Search Results* trace.
5. Land the value: this is what a customer gets over *their* documents — answers they can trust and trace, not a generic model guess.

### Key Takeaways

- RAG turns a generic LLM into a trustworthy assistant over the customer's own knowledge
- Source citations are the credibility moment in the demo — grounded, traceable answers
- The pre-deployed, pre-loaded environment lets an SA get to the "wow" in seconds, with no setup

### Infrastructure Notes

Requires the AI Quickstart RAG pre-deployed per tenant namespace (`user-{guid}-rag`) via GitOps ahead of the session, reachable through the AgnosticV-defined **RAG UI** Showroom tab. Participants perform no deployment, login, or route lookup. Pre-loaded knowledge bases: `hr-vector-db-v1-0`, `legal-vector-db-v1-0`, `procurement-vector-db-v1-0`, `sales-vector-db-v1-0`, `techsupport-vector-db-v1-0`.
