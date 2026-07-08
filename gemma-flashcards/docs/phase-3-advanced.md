# Phase 3: Advanced Features

Builds on [Phase 2b](phase-2b-embeddings.md) (recommended) or Phase 2a (if skipping PyTorch). Adds placement testing, a **full** learning roadmap, conversation practice, weekly AI reports, and SM-2 spaced review.

## Current baseline (already shipped)

Several Phase 3 items were partially built early. **Do not redo these** — extend them:

| Feature | Current implementation | Phase 3 work remaining |
|---------|------------------------|------------------------|
| Dashboard charts | Chart.js on `/dashboard` — words learned (week/month/year) + streak heatmap via `GET /api/progress/charts` | Add mastery doughnut; wire `ProgressSnapshot` |
| Roadmap (UI) | Dashboard "Learning path" section — 4 static levels, progress estimated from mastered word count | Gemma-generated roadmap, DB models, dedicated page, level unlock |
| Review | `/review` — flip cards, got it / still learning, mini quiz; queue = `practice` + `learning`, 3-day rule | SM-2 scheduling with `next_review_at` |
| Progress API | `services/progress.py` — `get_dashboard_summary`, `get_progress_charts`, streak tracking | Weekly report endpoint + snapshot upsert |
| Library | `/library` — browse/filter/search vocabulary by status and topic | Link weak words → review; conversation word picker |
| Live UI | `services/background.py` — topic-aware animated background + panel tints | Optional: conversation topic presets from active roadmap level |
| Streak | `UserProfile.streak_days` updated in dashboard | No change |
| Mastery statuses | `new`, `learning`, `practice`, `mastered` | SM-2 columns on `VocabularyItem` |

**Not started:** `PlacementSession`, `ConversationSession`, `Roadmap` / `RoadmapLevel` models, placement page, conversation chat, weekly report, SM-2 queue.

## Goals

| In scope (Phase 3) | Already done (skip) | Optional stretch |
|--------------------|---------------------|------------------|
| Placement test → estimated level | — | Forget-predictor ML |
| Full learning roadmap (Gemma-generated) | Estimated roadmap on dashboard | Multi-user auth |
| Conversation practice with Gemma | — | Public article ingestion |
| Weekly AI progress report | — | Export to Anki |
| SM-2 spaced review scheduling | Basic 3-day review queue | |
| ProgressSnapshot daily upsert | Chart data from live queries | |

## Exit criteria

- [ ] Optional placement test sets `profile.level` and records weak areas
- [ ] Gemma generates a persisted 4-level roadmap; dashboard reads from DB (not static template)
- [ ] Dedicated `/roadmap` page with "Study this level" → flashcards pre-filled with level topics
- [ ] User completes a conversation session using target vocabulary from library/recent words
- [ ] Dashboard shows weekly AI narrative report (refresh on demand)
- [ ] Review queue respects SM-2 `next_review_at` instead of fixed 3-day cutoff
- [ ] `ProgressSnapshot` updated after quiz/review/deck save

---

## Prerequisites

- Phase 1 + 2a complete (minimum)
- Phase 2b recommended for conversation word linking and semantic roadmap topic suggestions
- Some quiz history and vocabulary spread across topics for meaningful reports

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
    level_index = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(128))
    description = db.Column(db.Text)
    topics = db.Column(db.JSON, default=list)   # ["food", "travel", ...]
    target_word_count = db.Column(db.Integer, default=50)
    status = db.Column(db.String(16), default="locked")  # locked, active, completed
    completed_at = db.Column(db.DateTime)


class PlacementSession(db.Model):
    __tablename__ = "placement_session"

    id = db.Column(db.Integer, primary_key=True)
    estimated_level = db.Column(db.String(8))   # A1–C1 or beginner/advanced
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
    messages = db.Column(db.JSON, default=list)
    words_used_correctly = db.Column(db.JSON, default=list)
    words_missed = db.Column(db.JSON, default=list)
    corrections = db.Column(db.JSON, default=list)
    summary = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)
```

Extend `VocabularyItem` for SM-2:

```python
next_review_at = db.Column(db.DateTime)
ease_factor = db.Column(db.Float, default=2.5)
interval_days = db.Column(db.Integer, default=1)
```

Run app once to create tables. `services/roadmap.py` already imports `Roadmap` / `RoadmapLevel` defensively — it will start using DB rows once they exist.

---

## Step 3.2 — Placement test

### Gemma prompts (`services/gemma.py`)

```python
class PlacementQuestion(BaseModel):
    question: str
    question_type: str  # vocab_mc, fill_blank, reading
    options: list[str] = []
    correct: str
    skill: str


class PlacementQuestionSet(BaseModel):
    questions: list[PlacementQuestion]


class PlacementEvaluation(BaseModel):
    estimated_level: str
    weak_areas: list[str]
    strengths: list[str]
    summary: str
```

Generate ~10 mixed questions; store correct answers server-side (Flask session or signed token) — never send `correct` to the client.

### Routes

```python
@bp.route("/placement")
def placement():
    return render_template("placement.html")


@bp.post("/api/placement/start")
def placement_start():
    # Generate PlacementQuestionSet, return questions without answers
    ...


@bp.post("/api/placement/submit")
def placement_submit():
    # Evaluate → PlacementEvaluation
    # Update profile.level
    # Call generate_roadmap_for_profile(profile, result)
    ...
```

Link from `templates/onboarding.html` and `templates/settings.html`: "Not sure of your level? Take placement test."

Map `estimated_level` to existing `LEVELS` values in `routes/main.py` where possible.

---

## Step 3.3 — Full learning roadmap (upgrade existing stub)

**Today:** `services/roadmap.py` uses `DEFAULT_ROADMAP_LEVELS` and counts mastered words globally when no DB roadmap exists.

**Phase 3:** Generate and persist a personalized roadmap.

Extend `services/roadmap.py`:

```python
class RoadmapPlan(BaseModel):
    levels: list[dict]


def generate_roadmap_for_profile(profile, placement_result=None):
    # Gemma prompt using profile.target_language, profile.level, profile.goal,
    # placement_result.weak_areas if available
    # Create Roadmap + 4 RoadmapLevel rows; level 1 = active, rest = locked
    ...


def check_level_completion():
    # When mastered words in level.topics >= target_word_count:
    #   mark level completed, unlock next
    ...
```

Call `generate_roadmap_for_profile`:
- After placement test submit
- After onboarding if user skips placement (use self-reported level + goal)
- Manual "Regenerate roadmap" in settings (optional)

### Routes + templates

```python
@bp.route("/roadmap")
def roadmap_view():
    from services.roadmap import get_roadmap_progress
    progress = get_roadmap_progress(g.profile)
    return render_template("roadmap.html", progress=progress)
```

`templates/roadmap.html`:
- Vertical checklist of 4 levels (reuse dashboard roadmap markup)
- Active level: "Study now" → `/flashcards?theme=<first topic>`
- Show per-level topic tags and progress bar

Update dashboard learning path section to use the same `get_roadmap_progress()` data (already wired — will automatically show DB roadmap once generated).

**Topic alignment:** Roadmap level topics should feed `services/background.py` dominant category when no vocabulary topics exist yet.

---

## Step 3.4 — Conversation practice

### Gemma prompts

```python
def build_conversation_system_prompt(language, topic, difficulty, target_words, related_words, native_language):
    ...


def build_conversation_summary_prompt(messages, target_words, native_language):
    # Returns: words_used_correctly, words_missed, corrections, summary
    ...
```

### Routes

```python
@bp.route("/conversation")
def conversation():
    items = VocabularyItem.query.order_by(VocabularyItem.first_seen_at.desc()).limit(30).all()
    return render_template("conversation.html", recent_words=items)


@bp.post("/api/conversation/start")
def conversation_start():
    # Create ConversationSession
    # Phase 2b: related words via find_similar_vocab for first 3 target words
    # Gemma opening message
    ...


@bp.post("/api/conversation/<int:session_id>/message")
def conversation_message(session_id):
    ...


@bp.post("/api/conversation/<int:session_id>/finish")
def conversation_finish(session_id):
    # Gemma summary → save corrections, missed words
    ...
```

### Template `templates/conversation.html`

- Topic input (default: active roadmap level's first topic)
- Multi-select target words from `/library` recent items or dashboard "Words to study"
- Chat UI: message list + input + "End conversation"
- Summary modal: words used, corrections, suggested review

Add nav link in `templates/base.html` dropdown: Conversation.

---

## Step 3.5 — Progress charts (extend existing)

**Already done:**
- `GET /api/progress/charts?range=week|month|year`
- Chart.js line chart (words learned) + streak heatmap on dashboard

**Remaining work:**

1. **Mastery breakdown doughnut** — add to `get_progress_charts()`:

```python
"mastery_breakdown": {
    "new": VocabularyItem.query.filter_by(mastery_status="new").count(),
    "learning": VocabularyItem.query.filter_by(mastery_status="learning").count(),
    "practice": VocabularyItem.query.filter_by(mastery_status="practice").count(),
    "mastered": VocabularyItem.query.filter_by(mastery_status="mastered").count(),
},
```

2. **Daily snapshot** — add to `services/progress.py`:

```python
def upsert_daily_snapshot():
    today = date.today()
    snap = ProgressSnapshot.query.filter_by(date=today).first()
    if not snap:
        snap = ProgressSnapshot(date=today)
        db.session.add(snap)
    snap.words_learned = VocabularyItem.query.count()
    snap.words_mastered = VocabularyItem.query.filter_by(mastery_status="mastered").count()
    # quiz_accuracy from today's finished sessions
    db.session.commit()
```

Call `upsert_daily_snapshot()` after:
- `POST /api/quiz/submit`
- `POST /api/review/mini-quiz`
- `POST /api/decks`

---

## Step 3.6 — Weekly AI report

Add to `services/progress.py`:

```python
def generate_weekly_report():
    profile = get_profile()
    summary = get_dashboard_summary(profile)
    charts = get_progress_charts("week")
    # Gemma prompt: strong areas, weak areas, suggested topics, review focus
    ...
```

```python
@bp.get("/progress/weekly-report")
def weekly_report():
    return jsonify({"report": generate_weekly_report()})
```

Dashboard section below charts:
- "This week's report" card
- "Refresh report" button (cache in session or DB to avoid repeated Gemma calls)

Use `summary.study_words`, `summary.practice`, roadmap current level, and top topics from `services/background.get_active_topics()` in the prompt.

---

## Step 3.7 — SM-2 spaced review (upgrade existing queue)

**Today** (`services/review.py`):

```python
VocabularyItem.mastery_status.in_(["practice", "learning"])
VocabularyItem.last_reviewed_at < cutoff  # 3 days
```

**Upgrade:**

```python
def sm2_update(item, quality: int):
    """quality: 0–5 (0=complete blackout, 5=perfect)"""
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
        item.mastery_status = "practice"
        item.ease_factor = max(1.3, (item.ease_factor or 2.5) - 0.2)

    item.next_review_at = datetime.utcnow() + timedelta(days=item.interval_days)
    item.last_reviewed_at = datetime.utcnow()


def get_review_queue(limit=20):
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

Update `mark_review_feedback`:
- "Got it" → `sm2_update(item, 4)`
- "Still learning" → `sm2_update(item, 1)`

Update `templates/review.html` copy: mention spaced repetition; show "Next review in N days" on session complete.

**Migration:** Existing items without `next_review_at` should appear in queue (`nullsfirst`).

---

## Step 3.8 — Optional: PyTorch forget-predictor (stretch)

**Only if core Phase 3 is done and you want a research story.**

Requires 50+ quiz answers. Small `nn.Module` predicting P(forgot) within 7 days. Use score to sort review queue before SM-2 due date.

Skip for competition unless everything else is polished.

---

## Step 3.9 — Navigation updates

Add to `templates/base.html` nav dropdown:

```html
<a href="{{ url_for('main.roadmap') }}">Roadmap</a>
<a href="{{ url_for('main.conversation') }}">Conversation</a>
```

Optional placement link on onboarding/settings.

---

## Suggested build order

Given what's already built, implement in this order:

1. **SM-2 review** — immediate user value; small diff to `services/review.py`
2. **Roadmap models + Gemma generation** — replaces static dashboard estimate
3. **Placement test** — feeds roadmap personalization
4. **Weekly report** — leverages existing dashboard stats
5. **Conversation** — benefits most from Phase 2b similar-word linking
6. **ProgressSnapshot upsert + mastery doughnut** — polish

---

## Verification checklist

| Test | Expected |
|------|----------|
| Complete placement test | `profile.level` set, `placement_session` saved, roadmap generated |
| Dashboard learning path | Shows DB roadmap topics (not "coming soon" message) |
| `/roadmap` page | 4 levels, active level links to flashcards |
| Start conversation | Opening uses topic + target words |
| Send 3 messages | Corrections in replies, history saved |
| Finish conversation | Summary + missed words |
| Weekly report | Gemma narrative from stats |
| SM-2 review | Words due by `next_review_at` surface first |
| Quiz submit | `ProgressSnapshot` row for today updated |
| Mastery doughnut | Renders on dashboard |

---

## Full product demo script

1. Onboarding → optional placement test → Gemma roadmap generated
2. Upload document → semantic search (Phase 2b) → save vocab
3. Study roadmap level 1 topic → save deck (live background shifts to topic)
4. Conversation using those words → review summary
5. Quiz → dashboard charts + weekly report updated
6. SM-2 review session for due words

---

## Troubleshooting

**Placement test inconsistent levels:** Fixed question count; evaluate all answers in one Gemma call.

**Conversation drifts off topic:** Reinforce topic in system prompt on every turn.

**Charts empty:** Seed vocabulary across multiple days for demo.

**Roadmap never completes:** Lower `target_word_count` for demo; ensure topic tags on saved words match level topics.

**SM-2 queue empty after migration:** Run one-time backfill setting `next_review_at = now()` for all `practice`/`learning` items.

---

## What comes next (post-competition)

- Public article / social media source ingestion
- Export decks (CSV / Anki)
- Multi-user auth and cloud deploy
- Forget-predictor training pipeline
- Embedding-enhanced topic detection for live background

---

## File checklist

- [ ] Models: `Roadmap`, `RoadmapLevel`, `PlacementSession`, `ConversationSession`
- [ ] SM-2 columns on `VocabularyItem`
- [ ] `generate_roadmap_for_profile()` + level completion in `services/roadmap.py`
- [ ] Placement + conversation prompts in `services/gemma.py`
- [ ] Templates: `placement.html`, `roadmap.html`, `conversation.html`
- [ ] API: placement, conversation, `/api/progress/weekly-report`
- [ ] SM-2 upgrade in `services/review.py`
- [ ] `upsert_daily_snapshot()` wired after quiz/review/deck
- [ ] Mastery doughnut on dashboard
- [ ] Nav links for Roadmap and Conversation
