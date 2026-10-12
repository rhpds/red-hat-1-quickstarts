# Glossary

Shared vocabulary for the "Selling with Red Hat QuickStarts" lab. Definitions only —
no implementation detail.

### QuickStart (Red Hat QuickStart)

A packaged, demo-ready proof-of-concept accelerator that an SA can stand up quickly to
show a customer a credible, hands-on scenario instead of a slide deck. Used here as a
*selling* mechanism to shorten the sales cycle.

### AI Quickstart

A QuickStart in the Red Hat **AI Quickstarts** catalog (`docs.redhat.com/en/learn/ai-quickstarts`) —
community/example AI use cases authored by Red Hat experts that deploy on the Red Hat AI
platform. The three featured in this lab are **RAG**, **IT Self Service**, and **PPE
Compliance Monitor**. Note the casing: Red Hat writes the catalog family as "AI Quickstart"
(lowercase s), distinct from the general "QuickStart" term.

### RAG (Retrieval-Augmented Generation)

Enhancing an LLM's answers by retrieving relevant documents from a knowledge base and
giving them to the model as context, so answers are grounded in the customer's own data
and carry source citations. The flagship QuickStart of this lab.

### FantaCo

The fictional enterprise used as the customer story in the RAG demo. Its employees query
internal HR, Legal, Procurement, Sales, and TechSupport documentation through one chat
interface. The demo environment comes pre-loaded with FantaCo's documents.

### Knowledge base

A named collection of embedded documents (a vector store) the RAG app can retrieve from.
The demo ships with pre-loaded FantaCo collections; a custom one can be created by
uploading documents in the UI.

### Direct mode

The RAG app's simple, single-turn processing mode: retrieve matching chunks from a
selected knowledge base and pass them straight to the LLM for a grounded, citable answer.

### Agent-based mode

The RAG app's multi-step processing mode: the model plans, reasons, and calls tools
(knowledge-base retrieval, web search) across several turns before answering. Produces the
demo's "wow" moment when the **web-search tool** answers a question beyond the model's
training cutoff.

### RAG UI tab

The Showroom right-pane tab (defined in AgnosticV, not in this repo's `ui-config.yml`)
that opens the pre-deployed RAG chatbot directly, so learners never copy a route URL or
log in to reach the app.

### AI Quickstart IT Self Service

Module 4's (deferred) featured QuickStart — **term identity unresolved.** The name maps to
two upstream repos: `it-self-service-agent` (Slack/email/ServiceNow "laptop refresh") and
`speeding-up-ticket-resolution` (Zammad ticket portal). Reviewer feedback named the latter;
pending author clarification. Do not treat as settled.
