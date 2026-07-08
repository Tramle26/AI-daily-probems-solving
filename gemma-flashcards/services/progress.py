from datetime import date, datetime, timedelta

from sqlalchemy import func

from extensions import db
from models import QuizSession, VocabularyItem
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


def get_progress_charts(range_key: str = "week"):
    return {
        "range": range_key if range_key in RANGE_DAYS else "week",
        "words_series": get_words_learned_series(range_key),
        "streak_roadmap": get_streak_roadmap(range_key),
    }


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