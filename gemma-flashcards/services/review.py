from datetime import datetime, timedelta

from extensions import db
from models import VocabularyItem
from services.ownership import get_owned_or_404, owned_query


def sm2_update(item, quality: int):
    """quality: 0–5 (0=complete blackout, 5=perfect)"""
    if quality >= 3:
        if (item.review_count or 0) == 0:
            item.interval_days = 1
        elif item.review_count == 1:
            item.interval_days = 3
        else:
            item.interval_days = round((item.interval_days or 1) * (item.ease_factor or 2.5))
        item.review_count = (item.review_count or 0) + 1
        item.mastery_status = (
            "mastered" if item.review_count >= 4 and quality >= 4 else "learning"
        )
        item.ease_factor = (item.ease_factor or 2.5) + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        item.ease_factor = max(1.3, item.ease_factor)
    else:
        item.review_count = 0
        item.interval_days = 1
        item.mastery_status = "practice"
        item.ease_factor = max(1.3, (item.ease_factor or 2.5) - 0.2)

    item.next_review_at = datetime.utcnow() + timedelta(days=item.interval_days or 1)
    item.last_reviewed_at = datetime.utcnow()


def get_review_queue(limit=20):
    now = datetime.utcnow()
    return (
        owned_query(VocabularyItem)
        .filter(
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


def mark_review_feedback(vocab_id, got_it: bool):
    item = get_owned_or_404(VocabularyItem, vocab_id)
    sm2_update(item, 4 if got_it else 1)
    db.session.commit()
    return item
