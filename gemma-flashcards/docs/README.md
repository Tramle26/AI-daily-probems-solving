# Implementation Guides

Step-by-step instructions for building the Gemma language learning memory system from [userflow.md](../../userflow.md).

| Phase | Guide | Focus | PyTorch? |
|-------|-------|-------|----------|
| 0 | [phase-0-foundation.md](phase-0-foundation.md) | DB, nav, Gemma refactor, schema hooks | No |
| 1 | [phase-1-mvp.md](phase-1-mvp.md) | Onboarding, save deck, upload, dictionary, quiz, dashboard | No |
| 2a | [phase-2a-personalization.md](phase-2a-personalization.md) | Review, Excel, Ask Gemma, topic tags | No |
| 2b | [phase-2b-embeddings.md](phase-2b-embeddings.md) | Semantic search RAG, similar words, embedding continuity | **Yes** |
| 3 | [phase-3-advanced.md](phase-3-advanced.md) | Placement, roadmap, conversation, charts, SM-2 review | Optional |

**Prerequisites for all phases:** Phase 0 complete and verified.

**Competition demo target:** Finish Phase 1, then add Phase 2b if long-document semantic search is a differentiator.
