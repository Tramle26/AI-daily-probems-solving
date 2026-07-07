# Phase 3: Advanced Features

Builds on [Phase 2b](phase-2b-embeddings.md) (or Phase 2a if skipping PyTorch). Adds placement testing, learning roadmap, conversation practice, progress charts, weekly AI reports, and improved spaced review.

## Goals

| In scope (Phase 3) | Optional stretch |
|--------------------|------------------|
| Placement test → estimated level | PyTorch forget-predictor |
| Learning roadmap (3–4 levels) | Multi-user auth |
| Conversation practice with Gemma | Public article ingestion |
| Dashboard charts (Chart.js) | Export to Anki |
| Weekly AI progress report | |
| SM-2 spaced review scheduling | |

## Exit criteria

- [ ] Optional placement test sets user level and weak areas
- [ ] Roadmap page shows progress through topic levels
- [ ] User completes a conversation session using target vocabulary
- [ ] Dashboard shows words-over-time and accuracy charts
- [ ] Weekly report generates from learning history
- [ ] Review queue respects SM-2 intervals

---

## Prerequisites

- Phase 1 MVP complete (minimum)
- Phase 2a recommended; Phase 2b recommended for conversation word linking
- Saved quiz history for charts and reports

---

## Step 3.1 — New models

Add to `models/__init__.py`:

```python
class Roadmap(db.Model):
    __tablename__ = "roadmap"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), default="My learning path")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    levels = db.relationship("RoadmapLevel", backref="roadmap", lazy=True, cascade="all, delete-orphan")


class RoadmapLevel(db.Model):
    __tablename__ = "roadmap_level"

    id = db.Column(db.Integer, primary_key=True)
    roadmap_id = db.Column(db.Integer, db.ForeignKey("roadmap.id"), nullable=False)
    level_index = db.Column(db.Integer, nullable=False)  # 1, 2, 3, 4
    title = db.Column(db.String(128))          # e.g. "Foundation vocabulary"
    description = db.Column(db.Text)
    topics = db.Column(db.JSON, default=list)   # ["food", "travel", ...]
    target_word_count = db.Column(db.Integer, default=50)
    status = db.Column(db.String(16), default="locked")  # locked, active, completed
    completed_at = db.Column(db.DateTime)


class PlacementSession(db.Model):
    __tablename__ = "placement_session"

    id = db.Column(db.Integer, primary_key=True)
    estimated_level = db.Column(db.String(8))   # A1–C1
    weak_areas = db.Column(db.JSON, default=list)
    strengths = db.Column(db.JSON, default=list)
    raw_evaluation = db.Column(db.JSON)
    finished_at = db.Column(db.DateTime, default=datetime.utcnow)


class ConversationSession(db.Model):
    __tablename__ = "conversation_session"

    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(128))
    difficulty = db.Column(db.String(16))
    target_words = db.Column(db.JSON, default=list)
    messages = db.Column(db.JSON, default=list)  # [{role, content}, ...]
    words_used_correctly = db.Column(db.JSON, default=list)
    words_missed = db.Column(db.JSON, default=list)
    corrections = db.Column(db.JSON, default=list)
    summary = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)
```

Extend `VocabularyItem` for SM-2 (optional columns):

```python
next_review_at = db.Column(db.DateTime)
ease_factor = db.Column(db.Float, default=2.5)  # SM-2 default
interval_days = db.Column(db.Integer, default=1)
```

---

## Step 3.2 — Placement test

### Generate questions via Gemma

```python
# services/gemma.py
class PlacementQuestion(BaseModel):
    question: str
    question_type: str  # vocab_mc, fill_blank, reading
    options: list[str] = []
    correct: str
    skill: str  # vocabulary, grammar, reading


class PlacementQuestionSet(BaseModel):
    questions: list[PlacementQuestion]


def build_placement_generate_prompt(language, native_language, count=10):
    return f"""
Create {count} placement test questions for a {language} learner.
Mix: vocabulary multiple choice, fill-in-the-blank, short reading comprehension.
Explain instructions in {native_language} where needed.
Return JSON with questions array: question, question_type, options (for MC), correct, skill.
Order from easier to harder.
"""


class PlacementEvaluation(BaseModel):
    estimated_level: str  # A1, A2, B1, B2, C1
    weak_areas: list[str]
    strengths: list[str]
    summary: str


def build_placement_eval_prompt(language, qa_pairs, native_language):
    return f"""
Evaluate this {language} placement test for a learner.
Explain in {native_language}.

Questions and answers:
{qa_pairs}

Return: estimated_level (A1–C1), weak_areas, strengths, summary.
"""
```

### Routes

```python
@bp.route("/placement", methods=["GET", "POST"])
def placement():
    return render_template("placement.html")


@bp.post("/api/placement/start")
def placement_start():
    profile = get_profile()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    # generate PlacementQuestionSet, return questions WITHOUT correct answers to client
    # store correct answers server-side in session or signed token
    ...


@bp.post("/api/placement/submit")
def placement_submit():
    data = request.get_json()
    profile = get_profile()
    # evaluate with Gemma → PlacementEvaluation
    session = PlacementSession(
        estimated_level=result.estimated_level,
        weak_areas=result.weak_areas,
        strengths=result.strengths,
        raw_evaluation=result.model_dump(),
    )
    profile.level = result.estimated_level
    db.session.add(session)
    db.session.commit()
    # trigger roadmap generation
    generate_roadmap_for_profile(profile, result)
    return jsonify(result.model_dump())
```

Link from onboarding: "Not sure of your level? Take placement test."

---

## Step 3.3 — Learning roadmap

```python
# services/roadmap.py
class RoadmapPlan(BaseModel):
    levels: list[dict]  # title, description, topics, target_word_count


def build_roadmap_prompt(language, level, goal, weak_areas, native_language):
    return f"""
Create a 4-level learning roadmap for a {language} learner at {level or 'unknown'} level.
Goal: {goal}. Weak areas: {', '.join(weak_areas or [])}.
Explain level descriptions in {native_language}.

Each level: title, description, topics (list), target_word_count.
Order from foundation to advanced.
"""


def generate_roadmap_for_profile(profile, placement_result=None):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = build_roadmap_prompt(
        profile.target_language, profile.level, profile.goal,
        (placement_result.weak_areas if placement_result else []),
        profile.native_language,
    )
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RoadmapPlan,
        ),
    )
    plan = RoadmapPlan.model_validate_json(response.text)

    roadmap = Roadmap(title=f"{profile.target_language} path")
    db.session.add(roadmap)
    db.session.flush()

    for i, level_data in enumerate(plan.levels, start=1):
        db.session.add(RoadmapLevel(
            roadmap_id=roadmap.id,
            level_index=i,
            title=level_data["title"],
            description=level_data.get("description", ""),
            topics=level_data.get("topics", []),
            target_word_count=level_data.get("target_word_count", 40),
            status="active" if i == 1 else "locked",
        ))
    db.session.commit()
    return roadmap
```

### Routes + template

```python
@bp.route("/roadmap")
def roadmap_view():
    roadmap = Roadmap.query.order_by(Roadmap.created_at.desc()).first()
    return render_template("roadmap.html", roadmap=roadmap)
```

UI: vertical checklist of 4 levels; "Continue" links to flashcards with pre-filled topic from active level.

Mark level completed when user reaches `target_word_count` mastered words in those topics.

---

## Step 3.4 — Conversation practice

```python
# services/gemma.py
def build_conversation_system_prompt(language, topic, difficulty, target_words, related_words, native_language):
    words = ", ".join(target_words)
    related = ", ".join(related_words) if related_words else "none"
    return f"""
You are a friendly {language} conversation partner for a language learner.

Topic: {topic}
Difficulty: {difficulty}
Target words to practice: {words}
Related vocabulary they already know: {related}

Rules:
- Stay on topic.
- Ask questions that encourage using the target words.
- Use target words naturally in your replies.
- If the learner makes mistakes, give gentle corrections in {native_language} after your reply.
- Do not immediately give full answers — offer hints first.
- Keep replies concise (2–4 sentences).
"""


def build_conversation_summary_prompt(messages, target_words, native_language):
    return f"""
Summarize this {native_language} conversation practice session.

Target words: {', '.join(target_words)}
Transcript:
{messages}

Return JSON: words_used_correctly, words_missed, corrections (list of strings), summary, suggested_review_words.
"""
```

```python
# routes/api.py
@bp.route("/conversation")
def conversation_page():
    from models import VocabularyItem
    recent = VocabularyItem.query.order_by(VocabularyItem.first_seen_at.desc()).limit(20).all()
    return render_template("conversation.html", recent_words=recent)


@bp.post("/api/conversation/start")
def conversation_start():
    data = request.get_json()
    target_words = data["target_words"]
    topic = data["topic"]

    # Phase 2b: embedding neighbors for related words
    related = []
    for w in target_words[:3]:
        related.extend([v.word for v in find_similar_vocab(w, data["language"], top_k=3)])

    session = ConversationSession(
        topic=topic,
        difficulty=data.get("difficulty", "beginner"),
        target_words=target_words,
        messages=[{"role": "system", "content": "session_started"}],
    )
    db.session.add(session)
    db.session.commit()

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    system = build_conversation_system_prompt(
        data["language"], topic, session.difficulty, target_words, related, get_profile().native_language,
    )
    opening = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=f"{system}\n\nStart the conversation with a friendly opening question about {topic}.",
    )
    session.messages = [{"role": "assistant", "content": opening.text}]
    db.session.commit()
    return jsonify({"session_id": session.id, "message": opening.text})


@bp.post("/api/conversation/<int:session_id>/message")
def conversation_message(session_id):
    data = request.get_json()
    session = ConversationSession.query.get_or_404(session_id)
    session.messages.append({"role": "user", "content": data["message"]})
    # build chat history string, call Gemma, append assistant reply
    ...
    db.session.commit()
    return jsonify({"message": assistant_text})


@bp.post("/api/conversation/<int:session_id>/finish")
def conversation_finish(session_id):
    session = ConversationSession.query.get_or_404(session_id)
    # Gemma summary → populate words_used_correctly, corrections, summary
    session.finished_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"summary": session.summary, "corrections": session.corrections})
```

### Template `templates/conversation.html`

Chat UI: topic picker, word multi-select from recent vocab, message list, input box, "End conversation" → summary modal.

---

## Step 3.5 — Progress charts

Add Chart.js via CDN in `dashboard.html`:

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

### API for chart data

```python
@bp.get("/api/progress/charts")
def progress_charts():
    from datetime import timedelta
    from models import ProgressSnapshot, VocabularyItem

    # Words learned per day (last 30 days)
    thirty_ago = datetime.utcnow() - timedelta(days=30)
    daily = (
        db.session.query(
            db.func.date(VocabularyItem.first_seen_at).label("day"),
            db.func.count(VocabularyItem.id).label("count"),
        )
        .filter(VocabularyItem.first_seen_at >= thirty_ago)
        .group_by("day")
        .all()
    )

    week_ago = datetime.utcnow() - timedelta(days=7)
    sessions = QuizSession.query.filter(QuizSession.finished_at >= week_ago).all()
    quiz_by_day = {}  # aggregate accuracy by date

    return jsonify({
        "words_per_day": [{"day": str(d.day), "count": d.count} for d in daily],
        "quiz_accuracy_by_day": quiz_by_day,
        "mastery_breakdown": {
            "new": VocabularyItem.query.filter_by(mastery_status="new").count(),
            "learning": VocabularyItem.query.filter_by(mastery_status="learning").count(),
            "weak": VocabularyItem.query.filter_by(mastery_status="weak").count(),
            "mastered": VocabularyItem.query.filter_by(mastery_status="mastered").count(),
        },
    })
```

Dashboard JS: line chart for words/day, doughnut for mastery breakdown.

### Daily snapshot job

Call after quiz/review/deck save:

```python
def upsert_daily_snapshot():
    today = date.today()
    snap = ProgressSnapshot.query.filter_by(date=today).first()
    if not snap:
        snap = ProgressSnapshot(date=today)
        db.session.add(snap)
    snap.words_learned = VocabularyItem.query.count()
    snap.words_mastered = VocabularyItem.query.filter_by(mastery_status="mastered").count()
    # quiz_accuracy from today's sessions
    db.session.commit()
```

---

## Step 3.6 — Weekly AI report

```python
# services/progress.py
def build_weekly_report_prompt(summary, profile):
    return f"""
Write a friendly weekly learning report for a {profile.target_language} learner.
Native language for explanations: {profile.native_language}.

Stats: {json.dumps(summary)}

Include: strong areas, weak areas, suggested next topics, recommended review focus.
Keep it encouraging and under 250 words.
"""


def generate_weekly_report():
    profile = get_profile()
    summary = get_dashboard_summary()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = build_weekly_report_prompt(summary, profile)
    response = client.models.generate_content(model=GOOGLE_MODEL, contents=prompt)
    return response.text
```

Dashboard section: "This week's report" + "Refresh report" button → `GET /api/progress/weekly-report`.

---

## Step 3.7 — SM-2 spaced review (no PyTorch)

```python
# services/review.py — upgrade get_review_queue

def sm2_update(item, quality: int):
    """
    quality: 0-5 (0=complete blackout, 5=perfect)
    Standard SM-2 algorithm simplified.
    """
    if quality >= 3:
        if item.review_count == 0:
            item.interval_days = 1
        elif item.review_count == 1:
            item.interval_days = 3
        else:
            item.interval_days = round(item.interval_days * (item.ease_factor or 2.5))
        item.review_count = (item.review_count or 0) + 1
        item.mastery_status = "mastered" if item.review_count >= 4 and quality >= 4 else "learning"
    else:
        item.review_count = 0
        item.interval_days = 1
        item.mastery_status = "weak"
        item.ease_factor = max(1.3, (item.ease_factor or 2.5) - 0.2)

    item.next_review_at = datetime.utcnow() + timedelta(days=item.interval_days)
    item.last_reviewed_at = datetime.utcnow()


def get_review_queue_sm2(limit=20):
    now = datetime.utcnow()
    return (
        VocabularyItem.query.filter(
            db.or_(
                VocabularyItem.next_review_at.is_(None),
                VocabularyItem.next_review_at <= now,
            ),
            VocabularyItem.mastery_status != "mastered",
        )
        .order_by(VocabularyItem.next_review_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )
```

Replace simple 3-day rule in `/review` with SM-2 queue when Phase 3 is active.

---

## Step 3.8 — Optional: PyTorch forget-predictor (stretch)

**Only if you have 50+ quiz answers per user and want a research story.**

Features per training row:
- `days_since_review`
- `review_count`
- `quiz_accuracy`
- `mistake_type` one-hot
- `word length`

Label: `1` if next quiz wrong within 7 days, else `0`.

```python
# services/forget_model.py (stretch — not required for competition)
import torch
import torch.nn as nn

class ForgetPredictor(nn.Module):
    def __init__(self, input_dim=8):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return self.net(x)
```

Use predicted P(forgot) to sort review queue before SM-2 due date. **Skip unless core Phase 3 is done.**

---

## Step 3.9 — Navigation updates

Add to `base.html`:

```html
<a href="{{ url_for('main.roadmap') }}">Roadmap</a>
<a href="{{ url_for('main.conversation') }}">Conversation</a>
```

Optional: link placement test from onboarding and settings.

---

## Verification checklist

| Test | Expected |
|------|----------|
| Complete placement test | `profile.level` set, `placement_session` saved |
| Roadmap page | 4 levels, first active |
| Start conversation | Opening message uses topic |
| Send 3 messages | Corrections appear, history saved |
| Finish conversation | Summary + missed words |
| Dashboard charts | Words/day line chart renders |
| Weekly report | Gemma narrative from stats |
| SM-2 review | Words due by `next_review_at` surface first |

---

## Troubleshooting

**Placement test gives inconsistent levels:** Use fixed question count; evaluate all answers in one Gemma call.

**Conversation drifts off topic:** Reinforce topic in every user turn system reminder.

**Charts empty:** Need vocabulary with `first_seen_at` spread across days — seed test data if demoing.

**Roadmap never completes:** Lower `target_word_count` for demo or mark complete manually via admin route.

---

## Full product demo script

1. Onboarding → optional placement test → roadmap generated
2. Upload document → semantic search (Phase 2b) → save vocab
3. Study roadmap level 1 topic → save deck
4. Conversation using those words → review summary
5. Quiz → dashboard charts updated
6. Weekly report → share strong/weak areas

---

## What comes next (post-competition)

- Public article / social media source ingestion
- Export decks (CSV / Anki)
- Multi-user auth and cloud deploy
- Forget-predictor training pipeline
- Mobile-responsive polish

---

## File checklist

- [ ] Models: Roadmap, RoadmapLevel, PlacementSession, ConversationSession
- [ ] Optional SM-2 columns on VocabularyItem
- [ ] `services/roadmap.py`
- [ ] Placement + conversation prompts in `services/gemma.py`
- [ ] Templates: placement, roadmap, conversation
- [ ] API: placement, conversation, progress charts, weekly report
- [ ] Chart.js on dashboard
- [ ] SM-2 review queue upgrade
- [ ] Nav links for Roadmap and Conversation
