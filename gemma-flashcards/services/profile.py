# services/profile.py
from datetime import date, timedelta

from flask_login import current_user

from extensions import db
from models import UserProfile


def get_profile():
    """Return the current user's profile, creating one if needed."""
    if not current_user.is_authenticated:
        return None

    profile = current_user.profile
    if profile is None:
        profile = UserProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()
    return profile


def update_streak(profile):
    if not profile:
        return
    today = date.today()
    if profile.last_active_date == today:
        return
    if profile.last_active_date == today - timedelta(days=1):
        profile.streak_days = (profile.streak_days or 0) + 1
    else:
        profile.streak_days = 1
    profile.last_active_date = today
    db.session.commit()
