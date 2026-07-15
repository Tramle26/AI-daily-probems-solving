import os
from datetime import date, datetime, timedelta, timezone

from google import genai
from sqlalchemy import func

from extensions import db
from models import ProgressSnapshot, QuizSession, VocabularyItem
from services.ownership import current_user_id, owned_query
from services.roadmap import get_roadmap_progress

RANGE_DAYS = {"week": 7, "month": 30, "year": 365}


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _to_local_date(dt: datetime) -> date | None:
    """Map stored UTC-naive timestamps onto the learner's local calendar day."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_local_tz()).date()


def _local_day_bounds_utc(start: date, end: date):
    """UTC-naive window covering local calendar days start..end inclusive."""
    tz = _local_tz()
    start_local = datetime.combine(start, datetime.min.time(), tzinfo=tz)
    end_local = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def _words_by_day(start: date, end: date):
    start_utc, end_utc = _local_day_bounds_utc(start, end)
    rows = (
        db.session.query(VocabularyItem.first_seen_at)
        .filter(
            VocabularyItem.user_id == current_user_id(),
            VocabularyItem.first_seen_at.isnot(None),
            VocabularyItem.first_seen_at >= start_utc,
            VocabularyItem.first_seen_at < end_utc,
        )
        .all()
    )
    counts = {}
    for (ts,) in rows:
        day = _to_local_date(ts)
        if day is None or day < start or day > end:
            continue
        key = day.isoformat()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _activity_by_day(start: date, end: date):
    active = set()
    uid = current_user_id()
    start_utc, end_utc = _local_day_bounds_utc(start, end)

    def add_local_days(query):
        for (ts,) in query:
            day = _to_local_date(ts)
            if day is not None and start <= day <= end:
                active.add(day.isoformat())

    add_local_days(
        db.session.query(VocabularyItem.first_seen_at)
        .filter(
            VocabularyItem.user_id == uid,
            VocabularyItem.first_seen_at.isnot(None),
            VocabularyItem.first_seen_at >= start_utc,
            VocabularyItem.first_seen_at < end_utc,
        )
        .all()
    )
    add_local_days(
        db.session.query(VocabularyItem.last_reviewed_at)
        .filter(
            VocabularyItem.user_id == uid,
            VocabularyItem.last_reviewed_at.isnot(None),
            VocabularyItem.last_reviewed_at >= start_utc,
            VocabularyItem.last_reviewed_at < end_utc,
        )
        .all()
    )
    add_local_days(
        db.session.query(QuizSession.finished_at)
        .filter(
            QuizSession.user_id == uid,
            QuizSession.finished_at.isnot(None),
            QuizSession.finished_at >= start_utc,
            QuizSession.finished_at < end_utc,
        )
        .all()
    )
    return active


def get_words_learned_series(range_key: str = "week"):
    range_key = range_key if range_key in RANGE_DAYS else "week"
    today = datetime.now().astimezone().date()
    days = RANGE_DAYS[range_key]
    start = today - timedelta(days=days - 1)
    counts = _words_by_day(start, today)

    if range_key == "year":
        buckets = {}
        for day in _date_range(start, today):
            month_key = day.strftime("%Y-%m")
            buckets[month_key] = buckets.get(month_key, 0) + counts.get(day.isoformat(), 0)
        labels = []
        values = []
        cursor = date(start.year, start.month, 1)
        while cursor <= today:
            key = cursor.strftime("%Y-%m")
            labels.append(cursor.strftime("%b %Y"))
            values.append(buckets.get(key, 0))
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)
        return {"labels": labels, "values": values, "total": sum(values)}

    labels = []
    values = []
    for day in _date_range(start, today):
        labels.append(day.strftime("%a %d") if range_key == "week" else day.strftime("%b %d"))
        values.append(counts.get(day.isoformat(), 0))
    return {"labels": labels, "values": values, "total": sum(values)}


def get_streak_roadmap(range_key: str = "week"):
    range_key = range_key if range_key in RANGE_DAYS else "week"
    today = datetime.now().astimezone().date()
    days = RANGE_DAYS[range_key]
    start = today - timedelta(days=days - 1)
    active_days = _activity_by_day(start, today)
    word_counts = _words_by_day(start, today)

    roadmap = []
    for day in _date_range(start, today):
        day_key = day.isoformat()
        roadmap.append(
            {
                "date": day_key,
                "label": day.strftime("%b %d"),
                "active": day_key in active_days,
                "words": word_counts.get(day_key, 0),
            }
        )

    active_count = sum(1 for item in roadmap if item["active"])
    return {
        "days": roadmap,
        "active_days": active_count,
        "total_days": len(roadmap),
        "consistency": round(active_count / len(roadmap) * 100) if roadmap else 0,
    }


def get_mastery_breakdown():
    base = owned_query(VocabularyItem)
    return {
        "new": base.filter_by(mastery_status="new").count(),
        "learning": owned_query(VocabularyItem).filter_by(mastery_status="learning").count(),
        "practice": owned_query(VocabularyItem).filter_by(mastery_status="practice").count(),
        "mastered": owned_query(VocabularyItem).filter_by(mastery_status="mastered").count(),
    }


def get_progress_charts(range_key: str = "week"):
    return {
        "range": range_key if range_key in RANGE_DAYS else "week",
        "words_series": get_words_learned_series(range_key),
        "streak_roadmap": get_streak_roadmap(range_key),
        "mastery_breakdown": get_mastery_breakdown(),
    }


def upsert_daily_snapshot():
    today = datetime.now().astimezone().date()
    uid = current_user_id()
    snap = owned_query(ProgressSnapshot).filter_by(date=today).first()
    if not snap:
        snap = ProgressSnapshot(user_id=uid, date=today)
        db.session.add(snap)

    snap.words_learned = owned_query(VocabularyItem).count()
    snap.words_mastered = owned_query(VocabularyItem).filter_by(mastery_status="mastered").count()

    start_utc, end_utc = _local_day_bounds_utc(today, today)
    sessions = owned_query(QuizSession).filter(
        QuizSession.finished_at.isnot(None),
        QuizSession.finished_at >= start_utc,
        QuizSession.finished_at < end_utc,
    ).all()
    if sessions and sum(s.total for s in sessions):
        snap.quiz_accuracy = sum(s.score for s in sessions) / sum(s.total for s in sessions) * 100
    else:
        snap.quiz_accuracy = snap.quiz_accuracy or 0.0

    db.session.commit()
    return snap


def get_dashboard_summary(profile):
    total = owned_query(VocabularyItem).count()
    mastered = owned_query(VocabularyItem).filter_by(mastery_status="mastered").count()
    practice = owned_query(VocabularyItem).filter_by(mastery_status="practice").count()

    week_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    sessions = owned_query(QuizSession).filter(QuizSession.finished_at >= week_ago).all()
    if sessions and sum(s.total for s in sessions):
        accuracy = sum(s.score for s in sessions) / sum(s.total for s in sessions) * 100
    else:
        accuracy = 0.0

    study_words = (
        owned_query(VocabularyItem)
        .filter(VocabularyItem.mastery_status.in_(["new", "learning"]))
        .order_by(func.random())
        .limit(5)
        .all()
    )
    return {
        "total": total,
        "mastered": mastered,
        "practice": practice,
        "accuracy": round(accuracy, 1),
        "study_words": study_words,
        "roadmap_progress": get_roadmap_progress(profile),
    }


def generate_weekly_report():
    from services.background import get_active_topics
    from services.gemma import generate_weekly_report_text
    from services.profile import get_profile

    profile = get_profile()
    summary = get_dashboard_summary(profile)
    charts = get_progress_charts("week")
    roadmap = summary["roadmap_progress"]

    stats = {
        "total_words": summary["total"],
        "mastered": summary["mastered"],
        "practice": summary["practice"],
        "accuracy": summary["accuracy"],
        "words_this_week": charts["words_series"]["total"],
        "active_days": charts["streak_roadmap"]["active_days"],
        "roadmap_level": roadmap.get("current_level_title") or "n/a",
        "study_words": [w.word for w in summary["study_words"]],
        "topics": [t["label"] for t in get_active_topics(limit=5)],
    }

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {
            "narrative": (
                f"You have {stats['total_words']} words saved and "
                f"{stats['mastered']} mastered. Keep reviewing practice words "
                f"and study your current level: {stats['roadmap_level']}."
            ),
            "strong_areas": [],
            "weak_areas": [],
            "suggested_topics": stats["topics"][:3],
            "review_focus": stats["study_words"][:5],
            "cached": False,
        }

    client = genai.Client(api_key=api_key)
    report = generate_weekly_report_text(client, profile, stats)
    payload = report.model_dump()
    payload["cached"] = False
    return payload
