from flask import Blueprint, render_template, request, redirect, url_for, g

from extensions import db
from models import FlashcardDeck, UploadedDocument, VocabularyItem
from services.documents import extract_text_from_file, save_document
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
    if request.endpoint and request.endpoint.startswith("static"):
        return
    if request.endpoint in ("main.onboarding", "flashcards.stream"):
        return
    if request.endpoint and request.endpoint.startswith("api."):
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


@bp.route("/dashboard")
def dashboard():
    from services.progress import get_dashboard_summary

    update_streak(g.profile)
    summary = get_dashboard_summary()
    return render_template("dashboard.html", profile=g.profile, summary=summary)


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


@bp.route("/quiz")
def quiz():
    decks = FlashcardDeck.query.order_by(FlashcardDeck.created_at.desc()).limit(20).all()
    return render_template("quiz.html", decks=decks)


@bp.route("/dictionary")
def dictionary():
    return render_template("dictionary.html", profile=g.profile)


@bp.route("/history")
def history():
    status = request.args.get("status")
    query = VocabularyItem.query.order_by(VocabularyItem.first_seen_at.desc())
    if status:
        query = query.filter_by(mastery_status=status)
    items = query.limit(200).all()
    return render_template("history.html", items=items, status=status)
