import os
from datetime import datetime

from google import genai

from extensions import db
from models import Roadmap, RoadmapLevel, VocabularyItem
from services.ownership import current_user_id, owned_query

DEFAULT_ROADMAP_LEVELS = [
    {
        "index": 1,
        "title": "Foundation",
        "description": "Core vocabulary and phrases",
        "target_word_count": 50,
    },
    {
        "index": 2,
        "title": "Everyday life",
        "description": "Daily conversation topics",
        "target_word_count": 50,
    },
    {
        "index": 3,
        "title": "Intermediate",
        "description": "Broader grammar and reading",
        "target_word_count": 50,
    },
    {
        "index": 4,
        "title": "Advanced",
        "description": "Fluency and nuance",
        "target_word_count": 50,
    },
]


def _load_saved_roadmap():
    return owned_query(Roadmap).order_by(Roadmap.created_at.desc()).first()


def _mastered_count_for_topics(topics):
    base = owned_query(VocabularyItem).filter_by(mastery_status="mastered")
    if not topics:
        return base.count()
    return base.filter(VocabularyItem.topic.in_(topics)).count()


def _progress_from_roadmap(roadmap):
    levels = (
        RoadmapLevel.query.filter_by(roadmap_id=roadmap.id)
        .order_by(RoadmapLevel.level_index)
        .all()
    )
    current = next(
        (level for level in levels if level.status == "active"),
        levels[-1] if levels else None,
    )
    serialized = []

    for level in levels:
        topics = level.topics or []
        words_mastered = _mastered_count_for_topics(topics)
        target = level.target_word_count or 50
        serialized.append(
            {
                "index": level.level_index,
                "title": level.title,
                "description": level.description or "",
                "topics": topics,
                "target_word_count": target,
                "status": level.status,
                "words_mastered": min(words_mastered, target),
                "progress_pct": min(100, round(words_mastered / target * 100)) if target else 0,
            }
        )

    return {
        "has_roadmap": True,
        "title": roadmap.title,
        "current_level_index": current.level_index if current else 1,
        "current_level_title": current.title if current else "",
        "levels": serialized,
        "message": None,
    }


def _estimated_progress(profile):
    mastered = owned_query(VocabularyItem).filter_by(mastery_status="mastered").count()
    levels = []
    cumulative = 0
    current_index = 1
    active_found = False

    for template in DEFAULT_ROADMAP_LEVELS:
        target = template["target_word_count"]
        level_start = cumulative
        cumulative += target

        if mastered >= cumulative:
            status = "completed"
            words_done = target
        elif not active_found:
            status = "active"
            current_index = template["index"]
            active_found = True
            words_done = max(0, mastered - level_start)
        else:
            status = "locked"
            words_done = 0

        levels.append(
            {
                **template,
                "topics": [],
                "status": status,
                "words_mastered": words_done,
                "progress_pct": min(100, round(words_done / target * 100)) if target else 0,
            }
        )

    if not active_found:
        current_index = len(DEFAULT_ROADMAP_LEVELS)

    active = next((level for level in levels if level["status"] == "active"), levels[-1])

    return {
        "has_roadmap": False,
        "title": f"{profile.target_language} learning path",
        "current_level_index": current_index,
        "current_level_title": active["title"],
        "levels": levels,
        "message": "Personalized roadmap coming soon. Progress is estimated from words you've mastered.",
    }


def get_roadmap_progress(profile):
    roadmap = _load_saved_roadmap()
    if roadmap:
        return _progress_from_roadmap(roadmap)
    return _estimated_progress(profile)


def _fallback_plan(profile):
    language = profile.target_language or "your language"
    return {
        "title": f"{language} learning path",
        "levels": [
            {
                "level_index": template["index"],
                "title": template["title"],
                "description": template["description"],
                "topics": [],
                "target_word_count": template["target_word_count"],
            }
            for template in DEFAULT_ROADMAP_LEVELS
        ],
    }


def _plan_from_gemma(profile, placement_result=None):
    from services.gemma import generate_roadmap_plan

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return _fallback_plan(profile)

    client = genai.Client(api_key=api_key)
    plan = generate_roadmap_plan(client, profile, placement_result)
    by_index = {level.level_index: level for level in plan.levels}

    serialized = []
    for i, template in enumerate(DEFAULT_ROADMAP_LEVELS, start=1):
        level = by_index.get(i)
        if level is None and plan.levels:
            level = plan.levels[i - 1] if i <= len(plan.levels) else None
        if level is None:
            serialized.append(
                {
                    "level_index": i,
                    "title": template["title"],
                    "description": template["description"],
                    "topics": [],
                    "target_word_count": template["target_word_count"],
                }
            )
            continue
        serialized.append(
            {
                "level_index": i,
                "title": level.title,
                "description": level.description,
                "topics": list(level.topics or [])[:5],
                "target_word_count": level.target_word_count or 50,
            }
        )
    return {
        "title": plan.title or f"{profile.target_language} learning path",
        "levels": serialized,
    }


def generate_roadmap_for_profile(profile, placement_result=None):
    """Ask Gemma for a 4-level plan and persist Roadmap + RoadmapLevel rows."""
    try:
        plan = _plan_from_gemma(profile, placement_result)
    except Exception:
        plan = _fallback_plan(profile)

    for old in owned_query(Roadmap).all():
        db.session.delete(old)
    db.session.flush()

    roadmap = Roadmap(user_id=current_user_id(), title=plan["title"])
    db.session.add(roadmap)
    db.session.flush()

    for i, level_data in enumerate(plan["levels"][:4], start=1):
        db.session.add(
            RoadmapLevel(
                roadmap_id=roadmap.id,
                level_index=level_data.get("level_index", i),
                title=level_data["title"],
                description=level_data.get("description", ""),
                topics=level_data.get("topics") or [],
                target_word_count=level_data.get("target_word_count") or 50,
                status="active" if i == 1 else "locked",
            )
        )

    db.session.commit()
    return roadmap


def check_level_completion():
    """Mark active levels complete when topic mastery hits the target; unlock the next."""
    roadmap = _load_saved_roadmap()
    if not roadmap:
        return None

    levels = (
        RoadmapLevel.query.filter_by(roadmap_id=roadmap.id)
        .order_by(RoadmapLevel.level_index)
        .all()
    )
    changed = False

    for i, level in enumerate(levels):
        if level.status != "active":
            continue

        target = level.target_word_count or 50
        mastered = _mastered_count_for_topics(level.topics or [])
        if mastered < target:
            continue

        level.status = "completed"
        level.completed_at = datetime.utcnow()
        changed = True

        if i + 1 < len(levels) and levels[i + 1].status == "locked":
            levels[i + 1].status = "active"

    if changed:
        db.session.commit()

    return roadmap
