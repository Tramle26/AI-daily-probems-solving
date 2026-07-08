# Phase 1: Minimum Strong Version (MVP)

This guide implements the competition-ready demo loop from [userflow.md](../../userflow.md) (lines 624–638). **Prerequisite:** [Phase 0 complete](phase-0-foundation.md).

## Goals


| In scope (Phase 1)                       | Out of scope (Phase 2+)     |
| ---------------------------------------- | --------------------------- |
| Onboarding (language, goal, level)       | Excel upload                |
| Save generated decks to SQLite           | Ask Gemma / semantic search |
| History-aware flashcard generation       | PyTorch embeddings          |
| PDF/text upload → Gemma vocab extraction | Weak word review flow       |
| Dictionary search + add to deck          | Placement test, roadmap     |
| Multiple choice + fill-in-the-blank quiz | Conversation practice       |
| Dashboard with stats + recommendations   | Charts, weekly AI report    |




## Exit criteria

- [ ] New user completes onboarding and lands on dashboard
- [ ] Topic flashcards exclude mastered words and can be saved
- [ ] User uploads text/PDF → generates flashcards → saves deck
- [ ] Dictionary lookup works and word can be added to history
- [ ] Quiz updates mastery status (weak / learning / mastered)
- [ ] Dashboard shows learned, mastered, weak counts and quiz accuracy
- [ ] Full demo loop runs end-to-end without errors

---



## Prerequisites

- Phase 0 complete (`learning.db`, nav, `/flashcards` SSE working)
- `GEMINI_API_KEY` in `.env`
- Run all commands from `gemma-flashcards/`

---



## Step 1.1 — Add Phase 1 dependencies

Edit `pyproject.toml`:

```toml
dependencies = [
    "flask>=3.1.3",
    "flask-sqlalchemy>=3.1.0",
    "google-genai>=2.10.0",
    "ollama>=0.6.2",
    "pydantic>=2.13.4",
    "python-dotenv>=1.2.2",
    "pypdf>=5.0.0",
]
```

```bash
uv sync
```

Register the API blueprint in `app.py`:

```python
from routes import flashcards, main, api

app.register_blueprint(main.bp)
app.register_blueprint(flashcards.bp)
app.register_blueprint(api.bp)
```

---



## Step 1.2 — Onboarding + settings



### Constants and routes (`routes/main.py`)

```python
from flask import Blueprint, render_template, request, redirect, url_for, g
from extensions import db
from services.profile import get_profile, update_streak

bp = Blueprint("main", __name__)

LANGUAGES = ["English", "Spanish", "Vietnamese", "French", "Chinese"]
GOALS = [
    ("daily_conversation", "Daily conversation"),
    ("document_vocabulary", "Study from documents"),
    ("exam_prep", "Exam preparation"),
    ("reading_comprehension", "Reading comprehension"),
    ("speaking_writing", "Speaking and writing"),
    ("review", "Review words already learned"),
]


@bp.before_app_request
def load_profile():
    g.profile = get_profile()


@bp.before_app_request
def require_onboarding():
    from flask import request
    if request.endpoint and request.endpoint.startswith("static"):
        return
    if request.endpoint in ("main.onboarding", "flashcards.stream"):
        return
    profile = get_profile()
    if profile.goal is None and request.endpoint != "main.onboarding":
        return redirect(url_for("main.onboarding"))


@bp.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    profile = get_profile()
    if request.method == "POST":
        profile.target_language = request.form["target_language"]
        profile.native_language = request.form["native_language"]
        profile.level = request.form.get("level") or None
        profile.goal = request.form.get("goal") or None
        db.session.commit()
        return redirect(url_for("main.dashboard"))
    return render_template(
        "onboarding.html",
        languages=LANGUAGES,
        goals=GOALS,
        profile=profile,
    )


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    profile = get_profile()
    if request.method == "POST":
        profile.target_language = request.form["target_language"]
        profile.native_language = request.form["native_language"]
        profile.level = request.form.get("level") or None
        profile.goal = request.form.get("goal") or None
        db.session.commit()
        return redirect(url_for("main.settings"))
    return render_template("settings.html", languages=LANGUAGES, goals=GOALS, profile=profile)
```



### Template `templates/onboarding.html`

```html
{% extends "base.html" %}
{% block title %}Welcome — Gemma Learning{% endblock %}
{% block content %}
<section class="panel">
  <h1>Set up your learning profile</h1>
  <p class="muted">Choose your target language and goals. You can change these later in Settings.</p>
  <form method="post" class="form-grid">
    <label>Target language
      <select name="target_language" required>
        {% for lang in languages %}
        <option value="{{ lang }}" {% if profile.target_language == lang %}selected{% endif %}>{{ lang }}</option>
        {% endfor %}
      </select>
    </label>
    <label>Native / explanation language
      <select name="native_language" required>
        {% for lang in languages %}
        <option value="{{ lang }}" {% if profile.native_language == lang %}selected{% endif %}>{{ lang }}</option>
        {% endfor %}
      </select>
    </label>
    <label>Level (optional)
      <select name="level">
        <option value="">Not sure yet</option>
        {% for lvl in ["A1","A2","B1","B2","C1"] %}
        <option value="{{ lvl }}" {% if profile.level == lvl %}selected{% endif %}>{{ lvl }}</option>
        {% endfor %}
      </select>
    </label>
    <label>Learning goal
      <select name="goal">
        <option value="">Choose one</option>
        {% for value, label in goals %}
        <option value="{{ value }}" {% if profile.goal == value %}selected{% endif %}>{{ label }}</option>
        {% endfor %}
      </select>
    </label>
    <button type="submit" class="primary">Start learning</button>
  </form>
</section>
{% endblock %}
```

Copy `onboarding.html` → `settings.html`, change title and button text to "Save settings".

Update `routes/main.py` home redirect:

```python
@bp.get("/")
def home():
    return redirect(url_for("main.dashboard"))
```

---



## Step 1.3 — Vocabulary service + save deck

Create `services/vocabulary.py`:

```python
from extensions import db
from models import Flashcard, FlashcardDeck, VocabularyItem


def get_words_by_status(language, status):
    return [
        v.word
        for v in VocabularyItem.query.filter_by(language=language, mastery_status=status).all()
    ]


def upsert_vocabulary(word, language, meaning, example, topic, source_type, source_id=None, document_id=None):
    item = VocabularyItem.query.filter_by(word=word, language=language).first()
    if item:
        item.meaning = meaning or item.meaning
        item.example = example or item.example
        item.topic = topic or item.topic
        return item
    item = VocabularyItem(
        word=word,
        language=language,
        meaning=meaning,
        example=example,
        topic=topic,
        source_type=source_type,
        source_id=source_id,
        document_id=document_id,
        mastery_status="new",
    )
    db.session.add(item)
    return item


def save_deck(title, language, source_type, cards, source_id=None, document_id=None):
    deck = FlashcardDeck(
        title=title,
        language=language,
        source_type=source_type,
        source_id=source_id,
    )
    db.session.add(deck)
    db.session.flush()

    for card in cards:
        vocab = upsert_vocabulary(
            word=card["front"],
            language=language,
            meaning=card["back"],
            example=card.get("example", ""),
            topic=card.get("topic", ""),
            source_type=source_type,
            source_id=deck.id,
            document_id=document_id,
        )
        db.session.add(
            Flashcard(
                deck_id=deck.id,
                vocabulary_item_id=vocab.id,
                front=card["front"],
                back=card["back"],
                example=card.get("example"),
                topic=card.get("topic"),
                difficulty=card.get("difficulty"),
                memory_tip=card.get("memory_tip"),
            )
        )

    db.session.commit()
    return deck
```

Create `routes/api.py`:

```python
from flask import Blueprint, jsonify, request

from services.vocabulary import save_deck

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.post("/decks")
def create_deck():
    data = request.get_json()
    if not data or not data.get("cards"):
        return jsonify({"error": "No cards provided"}), 400

    deck = save_deck(
        title=data.get("title", "My Deck"),
        language=data["language"],
        source_type=data.get("source_type", "topic"),
        cards=data["cards"],
        source_id=data.get("source_id"),
        document_id=data.get("document_id"),
    )
    return jsonify({"id": deck.id, "title": deck.title}), 201
```



### History-aware `/stream`

Update `routes/flashcards.py`:

```python
from services.profile import get_profile
from services.vocabulary import get_words_by_status

# inside stream(), before card_stream:
profile = get_profile()
exclude = get_words_by_status(language, "mastered")

# pass to card_stream / build_topic_prompt:
# exclude_words=exclude, native_language=profile.native_language
```



### Save Deck UI (`templates/flashcards.html`)

Add after generate button:

```html
<button type="button" id="saveDeck" class="secondary" hidden>Save Deck</button>
```

Add to JavaScript:

```javascript
let generatedCards = []

source.addEventListener("card", (event) => {
  const data = JSON.parse(event.data)
  generatedCards.push(data.card)
  addCard(data.card)
  setProgress(data.index, data.total)
})

source.addEventListener("done", () => {
  showMessage("Deck ready. Tap a card to practice.")
  generateButton.disabled = false
  document.querySelector("#saveDeck").hidden = false
  source.close()
})

document.querySelector("#saveDeck").addEventListener("click", async () => {
  const title = document.querySelector("#theme").value || "My Deck"
  const language = document.querySelector("#language").value
  const res = await fetch("/api/decks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, language, source_type: "topic", cards: generatedCards }),
  })
  showMessage(res.ok ? "Deck saved to history!" : "Failed to save deck.")
})
```

Reset `generatedCards = []` at the start of each new generation.

---



## Step 1.4 — Document upload + vocab extraction

Create `services/documents.py`:

```python
from pypdf import PdfReader

from extensions import db
from models import UploadedDocument


def extract_text_from_file(file_storage):
    filename = file_storage.filename or "paste.txt"
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(file_storage)
        pages = [page.extract_text() or "" for page in reader.pages]
        return filename, "\n".join(pages).strip()
    raw = file_storage.read()
    return filename, raw.decode("utf-8", errors="replace").strip()


def save_document(filename, text, language):
    doc = UploadedDocument(
        filename=filename,
        raw_text=text,
        language=language,
        word_count=len(text.split()),
    )
    db.session.add(doc)
    db.session.commit()
    return doc
```

Add to `services/gemma.py`:

```python
class VocabularyEntry(BaseModel):
    word: str
    meaning: str
    example: str
    topic: str = ""
    difficulty: str = "beginner"


class VocabularyList(BaseModel):
    items: list[VocabularyEntry]


def build_document_prompt(text, language, max_words, native_language="English"):
    excerpt = text[:8000]
    return f"""
Extract the {max_words} most useful {language} vocabulary items from this passage.
Explain meanings in {native_language}.

Passage:
{excerpt}

Return JSON with items: word, meaning, example, topic, difficulty.
Focus on words a learner needs to understand this text.
"""


def extract_document_vocabulary(client, text, language, max_words, native_language="English"):
    prompt = build_document_prompt(text, language, max_words, native_language)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.5,
            response_mime_type="application/json",
            response_schema=VocabularyList,
        ),
    )
    return VocabularyList.model_validate_json(response.text)
```



### Upload routes

```python
# routes/main.py
from services.documents import extract_text_from_file, save_document

@bp.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        language = request.form.get("language") or g.profile.target_language
        if "file" in request.files and request.files["file"].filename:
            filename, text = extract_text_from_file(request.files["file"])
        else:
            filename, text = "paste.txt", request.form.get("text", "").strip()
        if not text:
            return render_template("upload.html", languages=LANGUAGES, error="No text found.")
        doc = save_document(filename, text, language)
        return redirect(url_for("main.upload_preview", doc_id=doc.id))
    return render_template("upload.html", languages=LANGUAGES)


@bp.route("/upload/<int:doc_id>")
def upload_preview(doc_id):
    doc = UploadedDocument.query.get_or_404(doc_id)
    return render_template("upload_preview.html", doc=doc)
```

```python
# routes/api.py
import os
from google import genai
from models import UploadedDocument
from services.gemma import extract_document_vocabulary
from services.vocabulary import save_deck

@bp.post("/documents/<int:doc_id>/generate")
def generate_from_document(doc_id):
    data = request.get_json()
    doc = UploadedDocument.query.get_or_404(doc_id)
    max_words = min(int(data.get("max_words", 10)), 20)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    client = genai.Client(api_key=api_key)
    result = extract_document_vocabulary(
        client, doc.raw_text, doc.language or data["language"],
        max_words, data.get("native_language", "English"),
    )

    cards = [
        {
            "front": item.word,
            "back": item.meaning,
            "example": item.example,
            "topic": item.topic,
            "difficulty": item.difficulty,
        }
        for item in result.items
    ]

    if data.get("save", False):
        deck = save_deck(
            title=doc.filename or "Document deck",
            language=doc.language,
            source_type="document",
            cards=cards,
            source_id=doc.id,
            document_id=doc.id,
        )
        return jsonify({"cards": cards, "deck_id": deck.id})

    return jsonify({"cards": cards})
```



### Template `templates/upload.html`

Form with: language select, file input, textarea for paste, submit button.

### Template `templates/upload_preview.html`

Show first 500 chars of extracted text, max words input, "Generate flashcards" button calling `/api/documents/<id>/generate`, card preview, "Save deck" checkbox.

---



## Step 1.5 — History page

```python
@bp.route("/history")
def history():
    from models import VocabularyItem
    status = request.args.get("status")
    query = VocabularyItem.query.order_by(VocabularyItem.first_seen_at.desc())
    if status:
        query = query.filter_by(mastery_status=status)
    items = query.limit(200).all()
    return render_template("history.html", items=items, status=status)
```



### Template `templates/history.html`

Filter links: All | new | learning | weak | mastered

Table columns: Word, Meaning, Topic, Status, Source, Last reviewed

---



## Step 1.6 — Dictionary search

Add to `services/gemma.py`:

```python
class DictionaryResult(BaseModel):
    word: str
    meaning: str
    simple_explanation: str
    example: str
    translation: str
    topic: str = ""
    difficulty: str = "beginner"
    similar_words: list[str] = []
    common_mistakes: list[str] = []


def build_dictionary_prompt(word, language, native_language, related_words=None):
    related = ""
    if related_words:
        related = f"\nThe learner has previously studied: {', '.join(related_words)}"
    return f"""
Explain the {language} word "{word}" for a language learner.
Explain in {native_language}.{related}

Return: word, meaning, simple_explanation, example, translation, topic, difficulty, similar_words, common_mistakes.
"""


def dictionary_lookup(client, word, language, native_language, related_words=None):
    prompt = build_dictionary_prompt(word, language, native_language, related_words)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            response_mime_type="application/json",
            response_schema=DictionaryResult,
        ),
    )
    return DictionaryResult.model_validate_json(response.text)
```

```python
# routes/main.py
@bp.route("/dictionary")
def dictionary():
    return render_template("dictionary.html", profile=g.profile)

# routes/api.py
from extensions import db
from models import DictionarySearch, VocabularyItem
from services.gemma import dictionary_lookup
from services.profile import get_profile
from services.vocabulary import upsert_vocabulary

@bp.post("/dictionary/search")
def dictionary_search():
    data = request.get_json()
    word = data["word"].strip()
    language = data.get("language") or get_profile().target_language
    profile = get_profile()

    related = [v.word for v in VocabularyItem.query.filter_by(language=language).limit(10).all()]

    api_key = os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    result = dictionary_lookup(client, word, language, profile.native_language, related)

    search = DictionarySearch(word=word, language=language, result_json=result.model_dump())
    db.session.add(search)
    db.session.commit()

    payload = result.model_dump()
    payload["search_id"] = search.id
    return jsonify(payload)


@bp.post("/dictionary/add")
def dictionary_add():
    data = request.get_json()
    upsert_vocabulary(
        word=data["word"],
        language=data["language"],
        meaning=data["meaning"],
        example=data.get("example", ""),
        topic=data.get("topic", ""),
        source_type="dictionary",
    )
    if data.get("search_id"):
        search = DictionarySearch.query.get(data["search_id"])
        if search:
            search.added_to_deck = True
    db.session.commit()
    return jsonify({"ok": True})
```



### Template `templates/dictionary.html`

Search input, results panel (meaning, example, similar words), "Add to vocabulary" button.

---



## Step 1.7 — Quiz

Create `services/quiz.py`:

```python
import random
from datetime import datetime

from extensions import db
from models import Flashcard, QuizAnswer, QuizSession, VocabularyItem


def get_quiz_pool(source_type, source_id=None, limit=10):
    if source_type == "weak":
        items = VocabularyItem.query.filter_by(mastery_status="weak").all()
    elif source_type == "deck" and source_id:
        items = (
            VocabularyItem.query.join(Flashcard)
            .filter(Flashcard.deck_id == source_id)
            .all()
        )
    elif source_type == "today":
        today = datetime.utcnow().date()
        items = VocabularyItem.query.filter(
            db.func.date(VocabularyItem.first_seen_at) == today
        ).all()
    else:
        items = VocabularyItem.query.filter(
            VocabularyItem.mastery_status != "mastered"
        ).limit(limit).all()
    return items[:limit]


def build_multiple_choice(items):
    if len(items) < 2:
        return []
    questions = []
    all_meanings = [v.meaning for v in items if v.meaning]
    for item in items:
        if not item.meaning:
            continue
        wrong_pool = [m for m in all_meanings if m != item.meaning]
        wrong = random.sample(wrong_pool, min(3, len(wrong_pool)))
        options = wrong + [item.meaning]
        random.shuffle(options)
        questions.append({
            "vocab_id": item.id,
            "question": f'What does "{item.word}" mean?',
            "options": options,
            "correct": item.meaning,
            "quiz_type": "multiple_choice",
        })
    return questions


def build_fill_blank(items):
    questions = []
    for item in items:
        if not item.example or item.word not in item.example:
            continue
        questions.append({
            "vocab_id": item.id,
            "question": item.example.replace(item.word, "_____", 1),
            "correct": item.word.strip(),
            "quiz_type": "fill_blank",
        })
    return questions


def grade_and_update_mastery(session, answers):
    score = 0
    for answer in answers:
        item = VocabularyItem.query.get(answer["vocab_id"])
        if not item:
            continue
        user = answer.get("user_answer", "").strip().lower()
        correct = answer.get("correct", "").strip().lower()
        is_correct = user == correct

        if is_correct:
            score += 1
            item.review_count = (item.review_count or 0) + 1
            item.mastery_status = "mastered" if item.review_count >= 2 else "learning"
        else:
            item.mastery_status = "weak"

        item.last_reviewed_at = datetime.utcnow()
        db.session.add(QuizAnswer(
            session_id=session.id,
            vocabulary_item_id=item.id,
            question=answer.get("question"),
            user_answer=answer.get("user_answer"),
            correct_answer=answer.get("correct"),
            is_correct=is_correct,
        ))

    session.score = score
    session.total = len(answers)
    session.finished_at = datetime.utcnow()
    db.session.commit()
    return score, len(answers)
```

```python
# routes/main.py
@bp.route("/quiz")
def quiz():
    from models import FlashcardDeck
    decks = FlashcardDeck.query.order_by(FlashcardDeck.created_at.desc()).limit(20).all()
    return render_template("quiz.html", decks=decks)

# routes/api.py
from services.quiz import build_fill_blank, build_multiple_choice, get_quiz_pool, grade_and_update_mastery

@bp.post("/quiz/start")
def quiz_start():
    data = request.get_json()
    items = get_quiz_pool(data["source_type"], data.get("source_id"), data.get("limit", 10))
    if not items:
        return jsonify({"error": "No vocabulary available for this quiz source."}), 400

    builder = build_fill_blank if data["quiz_type"] == "fill_blank" else build_multiple_choice
    questions = builder(items)
    if not questions:
        return jsonify({"error": "Could not build questions from vocabulary."}), 400

    session = QuizSession(
        source_type=data["source_type"],
        source_id=data.get("source_id"),
        quiz_type=data["quiz_type"],
        total=len(questions),
    )
    db.session.add(session)
    db.session.commit()
    return jsonify({"session_id": session.id, "questions": questions})


@bp.post("/quiz/submit")
def quiz_submit():
    data = request.get_json()
    session = QuizSession.query.get_or_404(data["session_id"])
    score, total = grade_and_update_mastery(session, data["answers"])
    accuracy = round(score / total * 100) if total else 0
    return jsonify({"score": score, "total": total, "accuracy": accuracy})
```



### Template `templates/quiz.html`

Wizard: pick source (weak / deck / all) → pick type (MC / fill-blank) → questions → results with score.

---



## Step 1.8 — Dashboard

Create `services/progress.py`:

```python
from datetime import datetime, timedelta

from models import FlashcardDeck, QuizSession, UploadedDocument, VocabularyItem


def get_dashboard_summary():
    total = VocabularyItem.query.count()
    mastered = VocabularyItem.query.filter_by(mastery_status="mastered").count()
    weak = VocabularyItem.query.filter_by(mastery_status="weak").count()
    weak_items = VocabularyItem.query.filter_by(mastery_status="weak").limit(5).all()

    week_ago = datetime.utcnow() - timedelta(days=7)
    sessions = QuizSession.query.filter(QuizSession.finished_at >= week_ago).all()
    if sessions and sum(s.total for s in sessions):
        accuracy = sum(s.score for s in sessions) / sum(s.total for s in sessions) * 100
    else:
        accuracy = 0.0

    recent_decks = FlashcardDeck.query.order_by(FlashcardDeck.created_at.desc()).limit(5).all()
    recent_uploads = UploadedDocument.query.order_by(UploadedDocument.uploaded_at.desc()).limit(5).all()

    if weak:
        recommendation = {"label": "Review weak words", "url": "main.quiz", "hint": f"{weak} words need practice"}
    else:
        recommendation = {"label": "Generate a new deck", "url": "flashcards.index", "hint": "Pick a topic to study"}

    return {
        "total": total,
        "mastered": mastered,
        "weak": weak,
        "accuracy": round(accuracy, 1),
        "weak_items": weak_items,
        "recent_decks": recent_decks,
        "recent_uploads": recent_uploads,
        "recommendation": recommendation,
    }
```

```python
@bp.route("/dashboard")
def dashboard():
    from services.progress import get_dashboard_summary
    update_streak(g.profile)
    summary = get_dashboard_summary()
    return render_template("dashboard.html", profile=g.profile, summary=summary)
```



### Template `templates/dashboard.html`

Stat cards: Words learned, Mastered, Weak, Quiz accuracy (7d), Streak

Sections: Recent decks, Recent uploads, Weak words list, Recommended next activity (CTA link)

---



## Step 1.9 — Update profile streak helper

Ensure `services/profile.py` has:

```python
from datetime import date, timedelta

def update_streak(profile):
    today = date.today()
    if profile.last_active_date == today:
        return
    if profile.last_active_date == today - timedelta(days=1):
        profile.streak_days = (profile.streak_days or 0) + 1
    else:
        profile.streak_days = 1
    profile.last_active_date = today
    db.session.commit()
```

---



## MVP demo script (judges)

1. Open app → onboarding (French, English, document vocabulary goal)
2. **Upload** → paste French paragraph → generate 8 words → save deck
3. **Flashcards** → generate topic deck "café" → save
4. **Dictionary** → search a word → add to vocabulary
5. **Quiz** → weak words → 5 multiple choice → submit
6. **Dashboard** → verify counts, weak list, recommendation
7. **History** → filter by weak / mastered

---



## Verification checklist


| Test                         | Expected                                                 |
| ---------------------------- | -------------------------------------------------------- |
| First visit without goal     | Redirect to `/onboarding`                                |
| Save deck after generate     | Rows in `flashcard_deck`, `flashcard`, `vocabulary_item` |
| Generate with mastered words | Those words excluded from new deck                       |
| PDF upload                   | Text extracted, preview shown                            |
| Document generate            | JSON cards returned, optional save                       |
| Dictionary search            | `dictionary_search` row created                          |
| Quiz wrong answer            | Word status → `weak`                                     |
| Quiz correct twice           | Word status → `mastered`                                 |
| Dashboard                    | Stats match database counts                              |


---



## Troubleshooting

**Quiz has no questions:** Need at least 2 vocabulary items with meanings for MC; fill-blank needs example sentences containing the word.

**Document generate fails on long PDF:** Phase 1 truncates to 8000 chars. Phase 2b adds RAG for full documents.

**Onboarding redirect loop:** Ensure `flashcards.stream` is exempt in `require_onboarding`.

**Mastered words not excluded:** Check `get_words_by_status` uses same language string as form input.

---



## What comes next

→ [Phase 2a: Personalization](phase-2a-personalization.md) — review flow, Excel, Ask Gemma, topic continuity

---



## File checklist

- [ ] `services/vocabulary.py`
- [ ] `services/documents.py`
- [ ] `services/quiz.py`
- [ ] `services/progress.py`
- [ ] `routes/api.py`
- [ ] Updated `routes/main.py`, `routes/flashcards.py`, `services/gemma.py`
- [ ] Templates: onboarding, settings, dashboard, upload, upload_preview, history, dictionary, quiz
- [ ] Flashcards save button + JS
- [ ] `pypdf` in pyproject.toml