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
    if request.endpoint and request.endpoint.startswith("static"):
        return
    if request.endpoint in ("main.onboarding", "flashcards.stream"):
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


# --- Stub pages: real logic added in later Phase 1 steps ---

@bp.get("/dashboard")
def dashboard():
    return render_template("stub.html", page_title="Dashboard", phase="Phase 1 (Step 1.8)")


@bp.get("/upload")
def upload():
    return render_template("stub.html", page_title="Upload", phase="Phase 1 (Step 1.4)")


@bp.get("/quiz")
def quiz():
    return render_template("stub.html", page_title="Quiz", phase="Phase 1 (Step 1.7)")


@bp.get("/dictionary")
def dictionary():
    return render_template("stub.html", page_title="Dictionary", phase="Phase 1 (Step 1.6)")


@bp.get("/history")
def history():
    return render_template("stub.html", page_title="History", phase="Phase 1 (Step 1.5)")