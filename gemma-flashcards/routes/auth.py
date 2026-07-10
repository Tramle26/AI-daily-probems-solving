from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from models import User, UserProfile

bp = Blueprint("auth", __name__)


def is_safe_url(target: str) -> bool:
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


def _valid_email(email: str) -> bool:
    return bool(email) and "@" in email and "." in email.split("@")[-1]


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        display_name = request.form.get("display_name", "").strip()

        if not _valid_email(email):
            flash("Enter a valid email address.", "error")
            return render_template("signup.html")
        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template("signup.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("signup.html")
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
            return render_template("signup.html")

        user = User(email=email, display_name=display_name or email.split("@")[0])
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        db.session.add(UserProfile(user_id=user.id))
        db.session.commit()

        login_user(user)
        return redirect(url_for("main.onboarding"))

    return render_template("signup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user is None or not user.check_password(password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")
        if not user.is_active:
            flash("This account has been deactivated.", "error")
            return render_template("login.html")

        login_user(user, remember=bool(request.form.get("remember")))
        next_url = request.args.get("next")
        if next_url and is_safe_url(next_url):
            return redirect(next_url)
        return redirect(url_for("main.dashboard"))

    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
