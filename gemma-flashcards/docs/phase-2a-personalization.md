# Phase 2a: Personalization (No PyTorch)

Builds on [Phase 1 MVP](phase-1-mvp.md). Adds review sessions, Excel import, Ask Gemma with truncated documents, and topic-tag-based continuity. **No PyTorch** — Phase 2b upgrades search and similar words with embeddings.

## Goals

| In scope (Phase 2a) | Out of scope (Phase 2b/3) |
|---------------------|---------------------------|
| Weak word review flow (`/review`) | Semantic search RAG |
| Excel vocabulary upload | Embedding neighbors |
| Ask Gemma Q&A (first 8000 chars of doc) | Placement test |
| Topic continuity via topic tags | Conversation practice |
| AskHistory table | Charts, weekly report |
| Mini quiz at end of review | Forget-predictor ML |

## Exit criteria

- [ ] User can complete a review session for weak/learning words
- [ ] Excel file uploads, columns mapped, deck saved
- [ ] User asks a question about an uploaded document and gets an answer
- [ ] Flashcard generation for "soccer" includes prior "sports" words from topic tags
- [ ] Ask history is saved and viewable

---

## Prerequisites

- Phase 1 complete and demo loop working
- At least a few saved vocabulary items and one uploaded document for testing

---

## Step 2a.1 — Add dependencies

```toml
"openpyxl>=3.1.0",
```

```bash
uv sync
```

---

## Step 2a.2 — AskHistory model

Add to `models/__init__.py`:

```python
class AskHistory(db.Model):
    __tablename__ = "ask_history"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("uploaded_document.id"))
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    related_words = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    document = db.relationship("UploadedDocument", backref="questions")
```

Run app once to create table, or use Flask-Migrate if configured.

Add nav link in `templates/base.html`:

```html
<a href="{{ url_for('main.ask') }}">Ask Gemma</a>
<a href="{{ url_for('main.review') }}">Review</a>
```

---

## Step 2a.3 — Weak word review flow

### Service `services/review.py`

```python
from datetime import datetime, timedelta

from models import VocabularyItem


def get_review_queue(limit=15):
    cutoff = datetime.utcnow() - timedelta(days=3)
    return (
        VocabularyItem.query.filter(
            VocabularyItem.mastery_status.in_(["weak", "learning"]),
            db.or_(
                VocabularyItem.last_reviewed_at.is_(None),
                VocabularyItem.last_reviewed_at < cutoff,
            ),
        )
        .order_by(VocabularyItem.last_reviewed_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )


def mark_review_feedback(vocab_id, got_it: bool):
    from extensions import db
    item = VocabularyItem.query.get(vocab_id)
    if not item:
        return
    if got_it:
        item.review_count = (item.review_count or 0) + 1
        item.mastery_status = "mastered" if item.review_count >= 2 else "learning"
    else:
        item.mastery_status = "weak"
    item.last_reviewed_at = datetime.utcnow()
    db.session.commit()
```

### Routes

```python
# routes/main.py
from services.review import get_review_queue

@bp.route("/review")
def review():
    items = get_review_queue()
    return render_template("review.html", items=items)


# routes/api.py
from services.review import mark_review_feedback
from services.quiz import build_multiple_choice, grade_and_update_mastery
from models import QuizSession

@bp.post("/review/feedback")
def review_feedback():
    data = request.get_json()
    mark_review_feedback(data["vocab_id"], data["got_it"])
    return jsonify({"ok": True})


@bp.post("/review/mini-quiz")
def review_mini_quiz():
    data = request.get_json()
    session = QuizSession(source_type="review", quiz_type="multiple_choice")
    db.session.add(session)
    db.session.flush()
    score, total = grade_and_update_mastery(session, data["answers"])
    return jsonify({"score": score, "total": total})
```

### Template `templates/review.html`

1. Show queue count at top
2. Flip-card UI for each word (reuse flashcard CSS)
3. Buttons: **Got it** / **Still learning** → POST `/api/review/feedback`
4. After all cards: 3-question mini quiz from same items
5. Results + link to dashboard

---

## Step 2a.4 — Excel upload

Extend `services/documents.py`:

```python
import openpyxl


def parse_excel(file_storage):
    wb = openpyxl.load_workbook(file_storage, read_only=True)
    sheet = wb.active
    rows_iter = sheet.iter_rows(values_only=True)
    headers = [str(h).strip().lower() if h else "" for h in next(rows_iter)]
    rows = []
    for row in rows_iter:
        if not any(row):
            continue
        rows.append({headers[i]: (row[i] or "") for i in range(min(len(headers), len(row)))})
    return headers, rows


COLUMN_ALIASES = {
    "word": {"word", "term", "vocabulary", "front"},
    "meaning": {"meaning", "definition", "back", "translation"},
    "example": {"example", "sentence"},
    "topic": {"topic", "theme", "category"},
    "difficulty": {"difficulty", "level"},
    "notes": {"notes", "note"},
}


def guess_column_map(headers):
    mapping = {}
    normalized = {h: h.lower().strip() for h in headers}
    for field, aliases in COLUMN_ALIASES.items():
        for header, norm in normalized.items():
            if norm in aliases:
                mapping[field] = header
                break
    return mapping


def rows_to_cards(rows, column_map):
    cards = []
    for row in rows:
        word = str(row.get(column_map.get("word", ""), "")).strip()
        if not word:
            continue
        cards.append({
            "front": word,
            "back": str(row.get(column_map.get("meaning", ""), "")).strip(),
            "example": str(row.get(column_map.get("example", ""), "")).strip(),
            "topic": str(row.get(column_map.get("topic", ""), "")).strip(),
            "difficulty": str(row.get(column_map.get("difficulty", ""), "")).strip() or "beginner",
        })
    return cards
```

Add Gemma fill for missing fields in `services/gemma.py`:

```python
class ExcelFillResult(BaseModel):
    meaning: str
    example: str
    topic: str = ""


def build_excel_fill_prompt(word, language, native_language):
    return f"""
The learner uploaded a vocabulary list. For the {language} word "{word}", provide:
meaning (in {native_language}), example sentence, and topic tag.
"""


def fill_missing_card_fields(client, word, language, native_language):
    prompt = build_excel_fill_prompt(word, language, native_language)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            response_mime_type="application/json",
            response_schema=ExcelFillResult,
        ),
    )
    return ExcelFillResult.model_validate_json(response.text)
```

### Upload route extension

```python
@bp.route("/upload/excel", methods=["GET", "POST"])
def upload_excel():
    if request.method == "POST":
        headers, rows = parse_excel(request.files["file"])
        column_map = request.form.to_dict()  # user-confirmed mapping from preview step
        cards = rows_to_cards(rows, column_map)

        # Fill missing meanings via Gemma
        for card in cards:
            if not card["back"]:
                filled = fill_missing_card_fields(client, card["front"], language, native_language)
                card["back"] = filled.meaning
                card["example"] = card["example"] or filled.example
                card["topic"] = card["topic"] or filled.topic

        deck = save_deck(request.form["title"], language, "excel", cards)
        return redirect(url_for("main.dashboard"))
    return render_template("upload_excel.html")
```

### Template flow

1. Upload Excel → show detected headers
2. User maps columns (dropdowns: Word → column A, Meaning → column B, etc.)
3. Preview first 5 rows
4. Confirm → save deck

---

## Step 2a.5 — Ask Gemma (truncated document Q&A)

Add to `services/gemma.py`:

```python
def build_ask_prompt(document_text, question, native_language):
    return f"""
Answer this question using ONLY the document below.
Explain in {native_language} when helpful.
If the answer is not in the document, say so clearly.

Document:
{document_text[:8000]}

Question: {question}
"""


def ask_document(client, document_text, question, native_language):
    prompt = build_ask_prompt(document_text, question, native_language)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3),
    )
    return response.text
```

Optional structured follow-up for vocab extraction from answer:

```python
class AskVocabSuggestion(BaseModel):
    words: list[VocabularyEntry]


def extract_vocab_from_answer(client, answer, language, native_language):
    prompt = f"""
From this study answer, list key {language} vocabulary items with meanings in {native_language}.

Answer:
{answer}
"""
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AskVocabSuggestion,
        ),
    )
    return AskVocabSuggestion.model_validate_json(response.text)
```

### Routes

```python
@bp.route("/ask", methods=["GET", "POST"])
def ask():
    docs = UploadedDocument.query.order_by(UploadedDocument.uploaded_at.desc()).all()
    history = AskHistory.query.order_by(AskHistory.created_at.desc()).limit(20).all()
    return render_template("ask.html", documents=docs, history=history)


@bp.post("/api/ask")
def api_ask():
    data = request.get_json()
    doc = UploadedDocument.query.get_or_404(data["document_id"])
    profile = get_profile()

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    answer = ask_document(client, doc.raw_text, data["question"], profile.native_language)

    entry = AskHistory(document_id=doc.id, question=data["question"], answer=answer)
    db.session.add(entry)
    db.session.commit()

    return jsonify({"answer": answer, "ask_id": entry.id})


@bp.post("/api/ask/<int:ask_id>/make-cards")
def ask_make_cards(ask_id):
    entry = AskHistory.query.get_or_404(ask_id)
    doc = entry.document
    profile = get_profile()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    suggestions = extract_vocab_from_answer(client, entry.answer, doc.language, profile.native_language)
    cards = [{"front": w.word, "back": w.meaning, "example": w.example, "topic": w.topic} for w in suggestions.words]
    deck = save_deck(f"From: {entry.question[:40]}", doc.language, "ask", cards, document_id=doc.id)
    return jsonify({"deck_id": deck.id, "cards": cards})
```

### Template `templates/ask.html`

- Document selector
- Question textarea
- Submit → show answer
- Button: "Make flashcards from this answer"
- Sidebar: recent AskHistory

> **Phase 2b upgrade:** Replace `document_text[:8000]` with RAG retrieved chunks. See [phase-2b-embeddings.md](phase-2b-embeddings.md).

---

## Step 2a.6 — Topic continuity (tag-based)

Add to `services/vocabulary.py`:

```python
def get_related_by_topic(theme, language, limit=15):
    """Find prior vocabulary whose topic overlaps the new theme (simple keyword match)."""
    keyword = theme.split()[0].lower()  # e.g. "soccer" or "World"
    return (
        VocabularyItem.query.filter_by(language=language)
        .filter(VocabularyItem.topic.ilike(f"%{keyword}%"))
        .limit(limit)
        .all()
    )


def build_continuity_context(theme, language):
    prior = get_related_by_topic(theme, language)
    if not prior:
        return ""
    words = ", ".join(v.word for v in prior)
    return f"\nThe learner previously studied related vocabulary: {words}. Use these to build examples and connections where helpful."
```

Update `build_topic_prompt` in `services/gemma.py`:

```python
def build_topic_prompt(language, theme, count, exclude_words=None, native_language="English", continuity_context=""):
    # ... existing exclude logic ...
    return f"""
Create exactly {count} flashcards for a learner studying {language}.
Explain meanings in {native_language}.

Theme: {theme}
{exclude}
{continuity_context}
...
"""
```

Wire in `routes/flashcards.py` stream route:

```python
from services.vocabulary import build_continuity_context

continuity = build_continuity_context(theme, language)
# pass continuity_context=continuity to card_stream / build_topic_prompt
```

Same context can be passed to dictionary and conversation prompts in Phase 3.

---

## Step 2a.7 — Semantic search placeholder (Phase 2a version)

Before PyTorch, offer a **keyword fallback** for "find in document":

```python
def keyword_search_chunks(text, query, context_chars=400):
    """Simple fallback until Phase 2b embeddings."""
    query_lower = query.lower()
    hits = []
    start = 0
    while True:
        idx = text.lower().find(query_lower, start)
        if idx == -1:
            break
        snippet = text[max(0, idx - context_chars): idx + context_chars]
        hits.append(snippet.strip())
        start = idx + len(query_lower)
    return hits[:5]
```

Use in Ask Gemma when user question contains a chapter reference — prepend matching snippets to prompt. Phase 2b replaces this entirely.

---

## Verification checklist

| Test | Expected |
|------|----------|
| `/review` with weak words | Queue shown, feedback updates mastery |
| Mini quiz after review | Scores saved to `quiz_session` |
| Excel upload 10 rows | Deck with 10 cards, missing meanings filled |
| Ask about uploaded doc | Answer saved in `ask_history` |
| Make cards from answer | New deck created |
| Generate "soccer" after "sports" topic | Prompt includes prior sports words |

---

## Troubleshooting

**Excel column map wrong:** Show preview step; never auto-save without user confirming mapping.

**Ask Gemma misses "chapter 2":** Truncation limit — document Phase 2b RAG as fix; keyword fallback helps partially.

**Review queue empty:** Need words with status `weak` or `learning` not reviewed in 3 days.

---

## What comes next

→ [Phase 2b: PyTorch Embeddings](phase-2b-embeddings.md) — real semantic search and embedding neighbors

---

## File checklist

- [ ] `AskHistory` model
- [ ] `services/review.py`
- [ ] Excel parsing in `services/documents.py`
- [ ] Ask prompts in `services/gemma.py`
- [ ] `templates/review.html`, `templates/ask.html`, `templates/upload_excel.html`
- [ ] API routes: `/api/review/*`, `/api/ask`, `/api/ask/<id>/make-cards`
- [ ] Topic continuity in `/stream`
- [ ] Nav links for Review and Ask Gemma
