# 1. RAG flagship spans two modules, adapted from the upstream RAG Showroom

Date: 2026-10-12

## Status

Accepted

## Context

The original lab spec (`publishing-house/spec.yaml`) mapped one module per featured
QuickStart: Module 2 = RAG, Module 3 = IT Self Service, Module 4 = PPE Compliance
Monitor, Module 5 = optional Deploy. Each "Selling the Demo" module was to be authored
from the thin module outlines.

Two things changed that mapping:

1. **A mature upstream source exists.** The RAG QuickStart already has a full, working
   Showroom lab (`rh-ai-qs-showroom/showroom-ai-quickstart-rag`) — seven pages covering
   login, knowledge bases, chat mode, agent mode, querying, and the Kubeflow ingestion
   pipeline, plus 15 screenshots. It is far richer than a single "sell the demo" module
   can hold, and most of it is genuine demo/usage content worth keeping.

2. **RAG is the flagship and the immediate priority.** The author chose to focus entirely
   on RAG first, defer IT Self Service / PPE / Deploy, and reduce Module 1 to a
   placeholder. RAG was given two module slots (2 and 3) to carry the compressed upstream
   content without cramming.

The upstream lab is also technically heavy (cluster inspection, `oc get pods`, a
`curl` ingestion API with hardcoded credentials). This lab's audience is Solution
Architects learning to *sell*, not deploy — so the adaptation must cut technical depth
and amplify sales framing.

## Decision

- The RAG QuickStart occupies **two modules**: Module 2 ("Running the Demo" — FantaCo
  framing, RAG UI tab, knowledge bases, direct-chat grounded answers) and Module 3
  ("Selling the Agentic Story" — agent mode, live web-search wow, and the customer sales
  narrative).
- Content is **adapted from the upstream `showroom-ai-quickstart-rag` lab**, not written
  from scratch, and **re-slanted toward selling value over technical depth**. The
  cluster-inspection page (`02`) is reduced to a single "open the RAG UI tab" step, and
  the Kubeflow pipeline page (`07`) is dropped entirely.
- The app is **pre-deployed**; learners reach it through the AgnosticV-defined **RAG UI**
  Showroom tab — no deploy, login, or route lookup steps.
- The deferred QuickStarts renumber to Modules 4 (IT Self Service), 5 (PPE), and 6
  (Deploy, optional). Module 1 becomes a placeholder.

## Consequences

- `spec.yaml`'s module map now shows Modules 2 **and** 3 as RAG, which will surprise a
  reader who remembers the one-QuickStart-per-module design or the reviewer feedback that
  named IT Self Service for Module 3. This ADR is the explanation.
- The lab's hands-on scope temporarily narrows to RAG; IT Self Service and PPE content do
  not exist yet and their outlines are placeholders.
- The "AI Quickstart IT Self Service" term remains ambiguous (two candidate upstream
  repos) and is deliberately left unresolved pending author clarification — see
  `GLOSSARY.md`.
- Because the demo steps were adapted from upstream rather than captured from this lab's
  own environment, UI steps (especially the web-search tool) must be verified against the
  live pre-deployed environment before the event.
