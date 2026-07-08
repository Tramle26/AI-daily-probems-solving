# services/profile.py
from extensions import db
from models import UserProfile
from datetime import date, timedelta

def get_profile():
    """Return the single local user profile, creating one if needed."""
    profile = UserProfile.query.first()
    if not profile:
        profile = UserProfile(target_language="French", native_language="English")
        db.session.add(profile)
        db.session.commit()
    return profile

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