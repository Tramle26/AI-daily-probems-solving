import os
from datetime import date, datetime, timedelta

from google import genai
from sqlalchemy import func

from extensions import db
from models import ProgressSnapshot, QuizSession, VocabularyItem
from services.roadmap import get_roadmap_progress

RANGE_DAYS = {"week": 7, "month": 30, "year": 365}


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _normalize_day(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _words_by_day(start_dt: datetime, end_dt: datetime):
    rows = (
        db.session.query(
            func.date(VocabularyItem.first_seen_at).label("day"),
            func.count(VocabularyItem.id).label("count"),
        )
        .filter(
            VocabularyItem.first_seen_at >= start_dt,
            VocabularyItem.first_seen_at < end_dt + timedelta(days=1),
        )
        .group_by("day")
        .all()
    )
    return {_normalize_day(row.day): row.count for row in rows}


def _activity_by_day(start_dt: datetime, end_dt: datetime):
    active = set()

    for row in (
        db.session.query(func.date(VocabularyItem.first_seen_at))
        .filter(
            VocabularyItem.first_seen_at >= start_dt,
            VocabularyItem.first_seen_at < end_dt + timedelta(days=1),
        )
        .distinct()
        .all()
    ):
        day = _normalize_day(row[0])
        if day:
            active.add(day)

    for row in (
        db.session.query(func.date(VocabularyItem.last_reviewed_at))
        .filter(
            VocabularyItem.last_reviewed_at.isnot(None),
            VocabularyItem.last_reviewed_at >= start_dt,
            VocabularyItem.last_reviewed_at < end_dt + timedelta(days=1),
        )
        .distinct()
        .all()
    ):
        day = _normalize_day(row[0])
        if day:
            active.add(day)

    for row in (
        db.session.query(func.date(QuizSession.finished_at))
        .filter(
            QuizSession.finished_at.isnot(None),
            QuizSession.finished_at >= start_dt,
            QuizSession.finished_at < end_dt + timedelta(days=1),
        )
        .distinct()
        .all()
    ):
        day = _normalize_day(row[0])
        if day:
            active.add(day)

    return active


def get_words_learned_series(range_key: str = "week"):
    range_key = range_key if range_key in RANGE_DAYS else "week"
    today = date.today()
    days = RANGE_DAYS[range_key]
    start = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(today, datetime.max.time())
    counts = _words_by_day(start_dt, end_dt)

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
    today = date.today()
    days = RANGE_DAYS[range_key]
    start = today - timedelta(days=days - 1)
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(today, datetime.max.time())
    active_days = _activity_by_day(start_dt, end_dt)
    word_counts = _words_by_day(start_dt, end_dt)

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
    return {
        "new": VocabularyItem.query.filter_by(mastery_status="new").count(),
        "learning": VocabularyItem.query.filter_by(mastery_status="learning").count(),
        "practice": VocabularyItem.query.filter_by(mastery_status="practice").count(),
        "mastered": VocabularyItem.query.filter_by(mastery_status="mastered").count(),
    }


def get_progress_charts(range_key: str = "week"):
    return {
        "range": range_key if range_key in RANGE_DAYS else "week",
        "words_series": get_words_learned_series(range_key),
        "streak_roadmap": get_streak_roadmap(range_key),
        "mastery_breakdown": get_mastery_breakdown(),
    }


def upsert_daily_snapshot():
    today = date.today()
    snap = ProgressSnapshot.query.filter_by(date=today).first()
    if not snap:
        snap = ProgressSnapshot(date=today)
        db.session.add(snap)

    snap.words_learned = VocabularyItem.query.count()
    snap.words_mastered = VocabularyItem.query.filter_by(mastery_status="mastered").count()

    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time())
    sessions = QuizSession.query.filter(
        QuizSession.finished_at.isnot(None),
        QuizSession.finished_at >= start,
        QuizSession.finished_at <= end,
    ).all()
    if sessions and sum(s.total for s in sessions):
        snap.quiz_accuracy = sum(s.score for s in sessions) / sum(s.total for s in sessions) * 100
    else:
        snap.quiz_accuracy = snap.quiz_accuracy or 0.0

    db.session.commit()
    return snap


def get_dashboard_summary(profile):
    total = VocabularyItem.query.count()
    mastered = VocabularyItem.query.filter_by(mastery_status="mastered").count()
    practice = VocabularyItem.query.filter_by(mastery_status="practice").count()

    week_ago = datetime.utcnow() - timedelta(days=7)
    sessions = QuizSession.query.filter(QuizSession.finished_at >= week_ago).all()
    if sessions and sum(s.total for s in sessions):
        accuracy = sum(s.score for s in sessions) / sum(s.total for s in sessions) * 100
    else:
        accuracy = 0.0

    study_words = (
        VocabularyItem.query.filter(
            VocabularyItem.mastery_status.in_(["new", "learning"])
        )
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
