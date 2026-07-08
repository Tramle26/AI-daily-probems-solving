from models import VocabularyItem

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
    try:
        from models import Roadmap
    except ImportError:
        return None

    return Roadmap.query.order_by(Roadmap.created_at.desc()).first()


def _progress_from_roadmap(roadmap):
    from models import RoadmapLevel

    levels = (
        RoadmapLevel.query.filter_by(roadmap_id=roadmap.id)
        .order_by(RoadmapLevel.level_index)
        .all()
    )
    current = next((level for level in levels if level.status == "active"), levels[-1] if levels else None)
    serialized = []

    for level in levels:
        topics = level.topics or []
        words_mastered = (
            VocabularyItem.query.filter(
                VocabularyItem.mastery_status == "mastered",
                VocabularyItem.topic.in_(topics),
            ).count()
            if topics
            else VocabularyItem.query.filter_by(mastery_status="mastered").count()
        )
        target = level.target_word_count or 50
        serialized.append(
            {
                "index": level.level_index,
                "title": level.title,
                "description": level.description or "",
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
    mastered = VocabularyItem.query.filter_by(mastery_status="mastered").count()
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
