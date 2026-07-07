from extensions import db
from models import UserProfile

def get_profile():
    """Return the single local user profile, creating one if needed"""
    profile = UserProfile.query.first()
    if not profile:
        profile = UserProfile(target_language="French", native_language="English")
        db.session.add(profile)
        db.session.commit()
    return profile
    