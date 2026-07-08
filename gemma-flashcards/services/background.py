import re
from collections import Counter

from sqlalchemy import func

from extensions import db
from models import UploadedDocument, VocabularyItem

TOPIC_PATTERNS = [
    (r"food|eat|restaurant|cook|kitchen|meal|drink|coffee|tea|fruit|bakery", "food", ["🍎", "🍞", "☕", "🥐"]),
    (r"sport|soccer|football|basketball|tennis|gym|fitness|game|cup|match", "sports", ["⚽", "🏆", "🎾"]),
    (r"travel|trip|city|airport|hotel|map|country|vacation|tour", "travel", ["✈", "🗺", "🧳", "🏙"]),
    (r"nature|garden|forest|animal|plant|flower|weather|sea|beach|mountain", "nature", ["🌿", "🌸", "🦋", "☁"]),
    (r"music|song|dance|concert|instrument|piano|guitar", "music", ["🎵", "🎸", "🎹"]),
    (r"school|study|exam|class|lesson|learn|book|read|library|grammar", "study", ["📚", "✏", "📝", "★"]),
    (r"work|office|business|job|meeting|career|company", "work", ["💼", "📊", "💻"]),
    (r"family|home|house|friend|people|daily|conversation|life", "daily", ["🏠", "💬", "☀", "★"]),
    (r"health|doctor|medicine|body|hospital|wellness", "health", ["💊", "🩺", "❤"]),
    (r"tech|computer|code|software|digital|internet|phone", "tech", ["💻", "📱", "⚡"]),
]

TOPIC_PALETTES = {
    "food": {"blob1": "#ffd9b8", "blob2": "#ffb8b8", "glyph": "#d66b6b"},
    "sports": {"blob1": "#ffe8a8", "blob2": "#ffc8a8", "glyph": "#c97a4a"},
    "travel": {"blob1": "#ffe082", "blob2": "#f5bcbc", "glyph": "#b86b6b"},
    "nature": {"blob1": "#ffe8c8", "blob2": "#f5d0a8", "glyph": "#8a9a6b"},
    "music": {"blob1": "#fff0b8", "blob2": "#f5bcbc", "glyph": "#c97a7a"},
    "study": {"blob1": "#fff59d", "blob2": "#fce8e8", "glyph": "#d66b6b"},
    "work": {"blob1": "#ffe8e8", "blob2": "#ffd9a8", "glyph": "#9a7070"},
    "daily": {"blob1": "#fff5f5", "blob2": "#fff59d", "glyph": "#e89191"},
    "health": {"blob1": "#ffd9d9", "blob2": "#ffe8e8", "glyph": "#d66b6b"},
    "tech": {"blob1": "#fff0c8", "blob2": "#fce8e8", "glyph": "#b87a7a"},
    "default": {"blob1": "#fff59d", "blob2": "#fce8e8", "glyph": "#ffd54f"},
}


def _normalize_topic(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def classify_topic(topic: str) -> str:
    text = _normalize_topic(topic)
    if not text:
        return "default"
    for pattern, category, _ in TOPIC_PATTERNS:
        if re.search(pattern, text):
            return category
    return "default"


def get_topic_glyphs(category: str) -> list[str]:
    for _, cat, glyphs in TOPIC_PATTERNS:
        if cat == category:
            return glyphs
    return ["★", "✦", "☆"]


def get_active_topics(limit: int = 5) -> list[dict]:
    rows = (
        db.session.query(VocabularyItem.topic, func.count(VocabularyItem.id).label("count"))
        .filter(VocabularyItem.topic.isnot(None), VocabularyItem.topic != "")
        .group_by(VocabularyItem.topic)
        .order_by(func.count(VocabularyItem.id).desc())
        .limit(limit * 2)
        .all()
    )

    topics = []
    seen = set()
    for topic, count in rows:
        label = (topic or "").strip()
        key = _normalize_topic(label)
        if not key or key in seen:
            continue
        seen.add(key)
        category = classify_topic(label)
        topics.append(
            {
                "label": label,
                "count": count,
                "category": category,
                "glyphs": get_topic_glyphs(category),
            }
        )
        if len(topics) >= limit:
            break

    if not topics:
        doc_topics = []
        for doc in UploadedDocument.query.order_by(UploadedDocument.uploaded_at.desc()).limit(5):
            for raw in doc.detected_topics or []:
                label = str(raw).strip()
                if label:
                    doc_topics.append(label)
        for label in doc_topics[:limit]:
            category = classify_topic(label)
            topics.append(
                {
                    "label": label,
                    "count": 1,
                    "category": category,
                    "glyphs": get_topic_glyphs(category),
                }
            )

    return topics


def get_background_config(profile=None) -> dict:
    topics = get_active_topics()
    categories = Counter(t["category"] for t in topics if t["category"] != "default")
    dominant = categories.most_common(1)[0][0] if categories else "default"
    palette = TOPIC_PALETTES.get(dominant, TOPIC_PALETTES["default"])

    glyphs = []
    labels = []
    for topic in topics:
        labels.append(topic["label"])
        glyphs.extend(topic["glyphs"])
    if not glyphs:
        glyphs = ["★", "✦", "☆", "♥"]

    unique_glyphs = []
    seen_glyphs = set()
    for glyph in glyphs:
        if glyph not in seen_glyphs:
            seen_glyphs.add(glyph)
            unique_glyphs.append(glyph)

    return {
        "topics": labels,
        "dominant_category": dominant,
        "glyphs": unique_glyphs[:8],
        "palette": palette,
        "language": getattr(profile, "target_language", None) or "French",
    }
