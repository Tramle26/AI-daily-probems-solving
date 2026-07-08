from datetime import datetime, timedelta

from extensions import db
from models import VocabularyItem


def get_review_queue(limit=15):
    cutoff = datetime.utcnow() - timedelta(days=3)
    return (
        VocabularyItem.query.filter(
            VocabularyItem.mastery_status.in_(["practice", "learning"]),
            db.or_(
                VocabularyItem.last_reviewed_at.is_(None),
                VocabularyItem.last_reviewed_at < cutoff,
            ),
        )
        .order_by(VocabularyItem.last_reviewed_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )


def mark_review_feedback(vocab_id, got_it: bool):
    item = VocabularyItem.query.get(vocab_id)
    if not item:
        return
    if got_it:
        item.review_count = (item.review_count or 0) + 1
        item.mastery_status = "mastered" if item.review_count >= 2 else "learning"
    else:
        item.mastery_status = "practice"
    item.last_reviewed_at = datetime.utcnow()
    db.session.commit()
