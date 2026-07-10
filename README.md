# AI Daily Problems Solving — Gemma Learning

Local language-learning web app using **Gemma**, built for the Kaggle competition **Build AI for Daily Life Problems**.

**Authors:** Tram Le and Cat Linh, with support of AI

The runnable app lives in **[`gemma-flashcards/`](gemma-flashcards/)**.

## Quick start

```bash
cd gemma-flashcards
```

1. Create a `.env` with your Gemini API key:

   ```env
   GEMINI_API_KEY=your_api_key_here
   SECRET_KEY=change-me-to-a-random-string
   ```

2. Install and run:

   ```bash
   uv sync
   uv run flask --app app run --debug
   ```

3. Open http://127.0.0.1:5000 — sign up, complete onboarding, then try flashcards, upload, quiz, and review.

Full setup, optional Ollama, and troubleshooting: **[gemma-flashcards/README.md](gemma-flashcards/README.md)**.

## Repo contents

| Path | Description |
|------|-------------|
| [`gemma-flashcards/`](gemma-flashcards/) | Flask app (Gemma Learning) |
| [`userflow.md`](userflow.md) | Product / user-flow design |
| [`gemma-flashcards/docs/`](gemma-flashcards/docs/) | Phase implementation guides |
