import os

from flask import Blueprint, render_template, request, redirect, url_for, g, session, current_app, jsonify
from google import genai

from extensions import db
from models import (
    AskHistory,
    DocumentChunk,
    FlashcardDeck,
    PlacementSession,
    UploadedDocument,
    VocabularyItem,
)
from services.documents import (
    delete_document,
    extract_text_from_file,
    guess_column_map,
    parse_excel,
    rows_to_cards,
    save_document,
)
from services.gemma import (
    evaluate_placement,
    fill_missing_card_fields,
    generate_placement_questions,
)
from services.profile import get_profile, update_streak
from services.review import get_review_queue
from services.roadmap import generate_roadmap_for_profile, get_roadmap_progress
from services.vocabulary import save_deck

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
LEVELS = [
    ("beginner", "Beginner"),
    ("elementary", "Elementary"),
    ("intermediate", "Intermediate"),
    ("advanced", "Advanced"),
    ("expert", "Expert"),
]

COLUMN_FIELDS = ["word", "meaning", "example", "topic", "difficulty", "notes"]

LEVEL_ALIASES = {
    "a1": "beginner",
    "beginner": "beginner",
    "a2": "elementary",
    "elementary": "elementary",
    "pre-intermediate": "elementary",
    "b1": "intermediate",
    "intermediate": "intermediate",
    "b2": "advanced",
    "upper-intermediate": "advanced",
    "advanced": "advanced",
    "c1": "expert",
    "c2": "expert",
    "expert": "expert",
    "proficient": "expert",
}


def map_estimated_level(raw: str) -> str:
    if not raw:
        return "beginner"
    key = raw.strip().lower().replace("_", "-")
    if key in LEVEL_ALIASES:
        return LEVEL_ALIASES[key]
    for alias, mapped in LEVEL_ALIASES.items():
        if alias in key:
            return mapped
    valid = {value for value, _ in LEVELS}
    return raw if raw in valid else "beginner"


@bp.before_app_request
def load_profile():
    g.profile = get_profile()


@bp.before_app_request
def require_onboarding():
    if request.endpoint and request.endpoint.startswith("static"):
        return
    if request.endpoint in ("main.onboarding", "flashcards.stream", "main.placement"):
        return
    if request.endpoint and (
        request.endpoint.startswith("api.")
        or request.endpoint.startswith("main.placement_")
    ):
        return
    profile = get_profile()
    if profile.goal is None and request.endpoint != "main.onboarding":
        return redirect(url_for("main.onboarding"))


@bp.get("/")
def home():
    return redirect(url_for("main.dashboard"))


@bp.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    profile = get_profile()
    if request.method == "POST":
        profile.target_language = request.form["target_language"]
        profile.native_language = request.form["native_language"]
        profile.level = request.form.get("level") or None
        profile.goal = request.form.get("goal") or None
        db.session.commit()
        try:
            generate_roadmap_for_profile(profile)
        except Exception as exc:
            current_app.logger.warning("Roadmap generation failed: %s", exc)
        if request.form.get("take_placement"):
            return redirect(url_for("main.placement"))
        return redirect(url_for("main.dashboard"))
    return render_template(
        "onboarding.html",
        languages=LANGUAGES,
        goals=GOALS,
        levels=LEVELS,
        profile=profile,
    )


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    profile = get_profile()
    if request.method == "POST":
        action = request.form.get("action") or "save"
        if action == "regenerate_roadmap":
            profile.target_language = request.form.get("target_language") or profile.target_language
            profile.native_language = request.form.get("native_language") or profile.native_language
            profile.level = request.form.get("level") or profile.level
            profile.goal = request.form.get("goal") or profile.goal
            db.session.commit()
            try:
                generate_roadmap_for_profile(profile)
            except Exception as exc:
                current_app.logger.warning("Roadmap regeneration failed: %s", exc)
            return redirect(url_for("main.roadmap_view"))

        profile.target_language = request.form["target_language"]
        profile.native_language = request.form["native_language"]
        profile.level = request.form.get("level") or None
        profile.goal = request.form.get("goal") or None
        db.session.commit()
        return redirect(url_for("main.settings"))
    return render_template(
        "settings.html",
        languages=LANGUAGES,
        goals=GOALS,
        levels=LEVELS,
        profile=profile,
    )


@bp.route("/dashboard")
def dashboard():
    from services.progress import get_dashboard_summary, get_progress_charts

    update_streak(g.profile)
    summary = get_dashboard_summary(g.profile)
    charts = get_progress_charts("week")
    return render_template(
        "dashboard.html",
        profile=g.profile,
        summary=summary,
        charts=charts,
    )


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
        try:
            from services.retrieval import index_document
            index_document(doc.id, doc.raw_text)
        except Exception as exc:
            current_app.logger.warning("Embedding index failed: %s", exc)
        return redirect(url_for("main.upload_preview", doc_id=doc.id))
    return render_template("upload.html", languages=LANGUAGES)


@bp.route("/upload/excel", methods=["GET", "POST"])
def upload_excel():
    profile = get_profile()

    if request.method == "GET":
        return render_template("upload_excel.html", languages=LANGUAGES, step="upload")

    if request.form.get("step") == "cancel":
        session.pop("excel_rows", None)
        session.pop("excel_headers", None)
        return redirect(url_for("main.upload_excel"))

    if request.form.get("step") == "confirm":
        rows = session.get("excel_rows", [])
        headers = session.get("excel_headers", [])
        column_map = {field: request.form.get(field) for field in COLUMN_FIELDS if request.form.get(field)}
        cards = rows_to_cards(rows, column_map)

        api_key = os.environ.get("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key) if api_key else None
        language = request.form.get("language") or profile.target_language
        native_language = profile.native_language

        for card in cards:
            if not card["back"] and client:
                filled = fill_missing_card_fields(client, card["front"], language, native_language)
                card["back"] = filled.meaning
                card["example"] = card["example"] or filled.example
                card["topic"] = card["topic"] or filled.topic

        save_deck(request.form.get("title", "Excel deck"), language, "excel", cards)
        session.pop("excel_rows", None)
        session.pop("excel_headers", None)
        return redirect(url_for("main.dashboard"))

    if "file" not in request.files or not request.files["file"].filename:
        return render_template("upload_excel.html", languages=LANGUAGES, step="upload", error="Choose an Excel file.")

    headers, rows = parse_excel(request.files["file"])
    session["excel_rows"] = rows
    session["excel_headers"] = headers
    guessed = guess_column_map(headers)

    return render_template(
        "upload_excel.html",
        languages=LANGUAGES,
        step="preview",
        headers=headers,
        rows=rows[:5],
        guessed=guessed,
        column_fields=COLUMN_FIELDS,
    )


@bp.route("/upload/<int:doc_id>")
def upload_preview(doc_id):
    doc = UploadedDocument.query.get_or_404(doc_id)
    chunk_count = DocumentChunk.query.filter_by(document_id=doc.id).count()
    return render_template("upload_preview.html", doc=doc, chunk_count=chunk_count)


@bp.route("/upload/<int:doc_id>/remove", methods=["POST"])
def upload_remove(doc_id):
    doc = UploadedDocument.query.get_or_404(doc_id)
    delete_document(doc)
    return redirect(url_for("main.upload"))


@bp.route("/quiz")
def quiz():
    decks = FlashcardDeck.query.order_by(FlashcardDeck.created_at.desc()).limit(20).all()
    return render_template("quiz.html", decks=decks)


@bp.route("/dictionary")
def dictionary():
    return render_template("dictionary.html", profile=g.profile)


@bp.route("/library")
def library():
    status = request.args.get("status")
    if status == "weak":
        status = "practice"
    search = request.args.get("q", "").strip()
    query = VocabularyItem.query.order_by(VocabularyItem.first_seen_at.desc())
    if status:
        query = query.filter_by(mastery_status=status)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                VocabularyItem.word.ilike(pattern),
                VocabularyItem.topic.ilike(pattern),
            )
        )
    items = query.limit(200).all()
    return render_template("library.html", items=items, status=status, search=search)


@bp.route("/history")
def history_redirect():
    return redirect(url_for("main.library", **request.args))


@bp.route("/review")
def review():
    items = get_review_queue()
    return render_template("review.html", items=items)


@bp.route("/ask", methods=["GET", "POST"])
def ask():
    docs = UploadedDocument.query.order_by(UploadedDocument.uploaded_at.desc()).all()
    history = AskHistory.query.order_by(AskHistory.created_at.desc()).limit(20).all()
    return render_template("ask.html", documents=docs, history=history)


@bp.route("/placement")
def placement():
    return render_template("placement.html", profile=g.profile)


@bp.post("/api/placement/start")
def placement_start():
    profile = get_profile()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    try:
        client = genai.Client(api_key=api_key)
        question_set = generate_placement_questions(client, profile, count=10)
    except Exception as exc:
        return jsonify({"error": f"Could not generate placement test: {exc}"}), 500

    stored = []
    public = []
    for q in question_set.questions[:10]:
        stored.append(
            {
                "question": q.question,
                "question_type": q.question_type,
                "options": q.options or [],
                "correct": q.correct,
                "skill": q.skill,
            }
        )
        public.append(
            {
                "question": q.question,
                "question_type": q.question_type,
                "options": q.options or [],
                "skill": q.skill,
            }
        )

    session["placement_questions"] = stored
    return jsonify({"questions": public})


@bp.post("/api/placement/submit")
def placement_submit():
    profile = get_profile()
    data = request.get_json() or {}
    answers = data.get("answers") or []
    stored = session.get("placement_questions") or []
    if not stored:
        return jsonify({"error": "No active placement test. Start again."}), 400

    graded = []
    for i, question in enumerate(stored):
        user_answer = ""
        if i < len(answers):
            user_answer = str(answers[i] or "").strip()
        correct = str(question.get("correct") or "").strip()
        is_correct = user_answer.lower() == correct.lower()
        graded.append(
            {
                **question,
                "user_answer": user_answer,
                "is_correct": is_correct,
            }
        )

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    try:
        client = genai.Client(api_key=api_key)
        evaluation = evaluate_placement(client, profile, graded)
    except Exception as exc:
        return jsonify({"error": f"Evaluation failed: {exc}"}), 500

    mapped_level = map_estimated_level(evaluation.estimated_level)
    profile.level = mapped_level

    placement = PlacementSession(
        estimated_level=mapped_level,
        weak_areas=evaluation.weak_areas,
        strengths=evaluation.strengths,
        raw_evaluation=evaluation.model_dump(),
    )
    db.session.add(placement)
    db.session.commit()

    try:
        generate_roadmap_for_profile(profile, placement_result=evaluation)
    except Exception as exc:
        current_app.logger.warning("Roadmap after placement failed: %s", exc)

    session.pop("placement_questions", None)

    return jsonify(
        {
            "estimated_level": mapped_level,
            "weak_areas": evaluation.weak_areas,
            "strengths": evaluation.strengths,
            "summary": evaluation.summary,
            "redirect": url_for("main.roadmap_view"),
        }
    )


@bp.route("/roadmap")
def roadmap_view():
    progress = get_roadmap_progress(g.profile)
    return render_template("roadmap.html", progress=progress, profile=g.profile)


@bp.route("/conversation")
def conversation():
    items = VocabularyItem.query.order_by(VocabularyItem.first_seen_at.desc()).limit(30).all()
    progress = get_roadmap_progress(g.profile)
    default_topic = "daily life"
    for level in progress.get("levels") or []:
        if level.get("status") == "active" and level.get("topics"):
            default_topic = level["topics"][0]
            break
    return render_template(
        "conversation.html",
        recent_words=items,
        default_topic=default_topic,
        profile=g.profile,
        difficulties=LEVELS,
    )
