# Implementation Guides

Step-by-step instructions for building the Gemma language learning memory system from [userflow.md](../../userflow.md).

| Phase | Guide | Focus | PyTorch? |
|-------|-------|-------|----------|
| 0 | [phase-0-foundation.md](phase-0-foundation.md) | DB, nav, Gemma refactor, schema hooks | No |
| 1 | [phase-1-mvp.md](phase-1-mvp.md) | Onboarding, save deck, upload, dictionary, quiz, dashboard | No |
| 2a | [phase-2a-personalization.md](phase-2a-personalization.md) | Review, Excel, Ask Gemma, topic tags, library | No — **done** |
| 2b | [phase-2b-embeddings.md](phase-2b-embeddings.md) | Semantic search RAG, similar words, embedding continuity | **Yes** — next |
| 3 | [phase-3-advanced.md](phase-3-advanced.md) | Placement, full roadmap, conversation, weekly report, SM-2 | Optional |
| 4 | [phase-4-auth.md](phase-4-auth.md) | Sign up / log in, per-user data isolation | No — **done** |

**Prerequisites for all phases:** Phase 0 complete and verified.

**Competition demo target:** Phases 0–4 are implemented. Sign up, then use placement, conversation, and SM-2 review with private per-user data.
