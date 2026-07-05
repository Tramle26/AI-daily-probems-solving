# LinguaCard — Gemma-Powered Language Flashcards

A local web app that turns any document or topic into a personalized vocabulary-learning loop: **generate → learn → quiz → track → reuse**. Built for the Kaggle "Build AI for Daily Life Problems" hackathon (Learning track), with Gemma as the core engine for every step.

**The one problem we solve:** language learners collect vocabulary passively (from readings, classes, feeds) but never convert it into active memory. LinguaCard closes that loop automatically.

**Languages:** English, Spanish, Vietnamese, French, Chinese.

---

## How Gemma is used (core, not bolted on)


| Step     | Gemma's job                                                                                                                                                 |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Generate | Create flashcards (word / meaning / example) from a topic or uploaded document, streamed as structured JSON                                                 |
| Answer   | Q&A over the uploaded document (semantic study search)                                                                                                      |
| Quiz     | Generate multiple-choice, fill-in-the-blank, and matching questions from the user's own learned words                                                       |
| Converse | Roleplay a short conversation that forces the user to use words they just learned                                                                           |
| Connect  | When generating a new topic (e.g. *soccer*), reuse vocabulary from related learned topics (e.g. *sports*) in definitions and examples — knowledge compounds |
| Define   | Dictionary lookup: word → meaning → example sentence                                                                                                        |


---



## Features



### MVP (must ship by July 10)

1. **Topic flashcards** — user picks language + topic + count (max 20), Gemma streams a deck. *(already working in* `gemma-flashcards/`*)*
2. **Document upload (PDF / text)** — Gemma extracts topics and generates flashcards from the file; user can look up any word in the file and add it to the deck (user sets their own max words).
3. **Ask Gemma** — questions answered from the uploaded document's content.
4. **Quizzes** — multiple choice, fill-in-the-blank, matching. Generated from the user's learned-word history so every quiz is personal.
5. **Learning history** — every word learned, searched, or uploaded is recorded (SQLite). New decks never repeat learned words; they build on them.
6. **Vocabulary chaining** — the novelty headline: new topics (e.g. *soccer*) are explained using words the user already learned (e.g. from *sports*), so knowledge compounds instead of staying in isolated decks. Cheap to build — inject learned words into the generation prompt.
7. **Progress dashboard** — streak, words learned over time, quiz accuracy / % improvement, per-topic breakdown (simple charts).



### Stretch (only if MVP is solid)

- **Conversation practice** — chat with Gemma that requires using the newest words; Gemma corrects gently. *(Best demo moment for the video if it lands.)*
- **Excel/CSV import** — create decks from a user's own word list.
- **Dictionary search** — word → meaning → usage example, in any of the 5 languages.

---



## Architecture

```
Browser (HTML/JS, SSE streaming)
   │
Flask (app.py)
   ├── Gemma (google-genai API / Ollama local fallback) — generation, Q&A, quizzes, conversation
   ├── PDF/text extraction (pypdf) → chunked context for Gemma
   └── SQLite — users' learned words, uploads, searches, quiz results, streaks
```

- **Structured output:** Pydantic schemas (`Flashcard`, `Deck`, `Quiz`) validate everything Gemma returns.
- **Streaming:** cards appear one-by-one via server-sent events (already implemented).
- **Everything is recorded:** words learned, searched, and uploaded all flow into the history table that powers the dashboard and the no-repeat / vocabulary-chaining logic.

---

## 6-day plan


| Day     | Goal                                                                  |
| ------- | --------------------------------------------------------------------- |
| Jul 4–5 | SQLite history + learned-words tracking; PDF upload → flashcards      |
| Jul 6   | Quizzes (MC, fill-blank, matching) from history; vocabulary chaining  |
| Jul 7   | Dashboard (streak, accuracy, charts); Ask-Gemma over documents        |
| Jul 8   | Stretch features (conversation practice first) if stable; polish UI   |
| Jul 9   | Writeup (≤1500 words), record video (≤3 min), publish notebook + repo |
| Jul 10  | Buffer + submit before 9 PM GMT+5                                     |


