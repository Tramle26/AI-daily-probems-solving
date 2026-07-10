# Gemma Learning

A local language-learning web app powered by **Gemma**. Upload documents, generate vocabulary flashcards, quiz yourself, practice conversation, and track what you’ve learned over time.

Built for the Kaggle competition **Build AI for Daily Life Problems**.

**Authors:** Tram Le and Cat Linh, with support of AI

---

## Features

- Sign up / log in with private per-user data
- Onboarding (target language, level, goal) and optional placement test
- Topic flashcards streamed from Gemma (Google API or local Ollama)
- PDF / text upload → vocabulary extraction
- Dictionary, quiz, SM-2 spaced review
- Ask Gemma (Q&A over your materials)
- Conversation practice and learning roadmap
- Semantic search / related words via local embeddings (`sentence-transformers`)

Supported focus languages: English, Spanish, Vietnamese, French, Chinese.

---

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **Python 3.14+** | See `.python-version` |
| **[uv](https://github.com/astral-sh/uv)** | Installs deps and runs the app |
| **Gemini API key** | Required for Google/Gemma cloud features — [Google AI Studio](https://aistudio.google.com/apikey) |
| **Ollama** (optional) | Only if you want the local model option on Flashcards |

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/<your-org-or-user>/AI-daily-probems-solving.git
cd AI-daily-probems-solving/gemma-flashcards
```

### 2. Create a `.env` file

In `gemma-flashcards/`, create `.env` (this file is gitignored):

```env
GEMINI_API_KEY=your_api_key_here
SECRET_KEY=change-me-to-a-random-string
```

Optional:

```env
# Local Ollama model name (default: gemma3:4b)
LOCAL_MODEL=gemma3:4b
```

### 3. Install dependencies

```bash
uv sync
```

The first run may download PyTorch / `sentence-transformers` weights used for embeddings. That can take a few minutes.

### 4. Run the app

```bash
uv run flask --app app run --debug
```

Open **http://127.0.0.1:5000** in your browser.

### 5. First visit

1. **Sign up** with an email and password  
2. Complete **onboarding** (language, level, goal)  
3. Use the dashboard, flashcards, upload, quiz, review, and other pages from the nav  

SQLite creates `instance/learning.db` automatically on first start.

---

## Optional: local Ollama

Flashcards can use **Google API** (default) or **Ollama**.

1. Install [Ollama](https://ollama.com/) and pull a model:

   ```bash
   ollama pull gemma3:4b
   ```

2. Keep Ollama running, then choose the local provider in the Flashcards UI (or set `LOCAL_MODEL` in `.env` if you use a different tag).

Most other features (quiz generation, Ask Gemma, conversation, roadmap, etc.) use the Gemini API and need `GEMINI_API_KEY`.

---

## Project layout

```
gemma-flashcards/
├── app.py              # Flask app factory
├── extensions.py       # db, login manager
├── models/             # SQLAlchemy models
├── routes/             # HTTP routes (auth, pages, API)
├── services/           # Gemma, vocab, embeddings, review, …
├── templates/          # Jinja HTML
├── static/             # CSS / JS
├── uploads/            # User uploads (gitignored)
├── instance/           # SQLite DB (gitignored)
└── docs/               # Phase implementation guides
```

Implementation notes live in [`docs/`](docs/README.md). Product flow: [`../userflow.md`](../userflow.md).

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| `Missing GEMINI_API_KEY` | Put the key in `gemma-flashcards/.env` and restart Flask |
| Auth / sessions odd after restart | Set a stable `SECRET_KEY` in `.env` |
| Slow first request | Embedding model (`all-MiniLM-L6-v2`) loads on first use |
| Ollama errors on Flashcards | Confirm `ollama serve` is running and `LOCAL_MODEL` matches a pulled model |
| Python version errors | Use Python 3.14+ (`uv` will respect `.python-version`) |

---

## License / competition note

This project was built as a learning / competition demo. Do not commit your `.env` or API keys.
