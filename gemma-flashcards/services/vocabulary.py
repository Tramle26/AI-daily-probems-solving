import re
import unicodedata

from extensions import db
from models import Flashcard, FlashcardDeck, VocabularyItem
from services.embeddings import cosine_similarity, embed_text, is_model_loaded
from services.ownership import current_user_id, owned_query

# Script families we care about for vocab quality checks.
_LATIN_RE = re.compile(r"[A-Za-z\u00C0-\u024F\u1E00-\u1EFF]")
_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_CJK_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_HANGUL_RE = re.compile(r"[\u1100-\u11FF\u3130-\u318F\uAC00-\uD7AF]")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+$")

_LATIN_LANGUAGES = {
    "english",
    "spanish",
    "french",
    "vietnamese",
    "portuguese",
    "italian",
    "german",
}


def _script_flags(text):
    return {
        "latin": bool(_LATIN_RE.search(text)),
        "arabic": bool(_ARABIC_RE.search(text)),
        "cjk": bool(_CJK_RE.search(text)),
        "cyrillic": bool(_CYRILLIC_RE.search(text)),
        "hangul": bool(_HANGUL_RE.search(text)),
    }


def is_valid_vocab_word(word, language=None):
    """Reject punctuation junk, snake_case IDs, and mixed-script mashups."""
    text = unicodedata.normalize("NFKC", (word or "")).strip()
    if len(text) < 2 or len(text) > 80:
        return False
    if "_" in text or _IDENTIFIER_RE.match(text.replace("'", "").replace("-", "")):
        return False
    # Disallow code-like tokens and weird joins.
    if re.search(r"[<>{}[\]\\|^=+#~`$]", text):
        return False
    if text.count("/") > 1 or "//" in text:
        return False

    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < max(1, int(len(text) * 0.4)):
        return False

    flags = _script_flags(text)
    active_scripts = sum(1 for present in flags.values() if present)
    if active_scripts == 0:
        return False
    # Mixed scripts like Arabic+French "تطبيق_de_l'équipe" are never legit vocab.
    if active_scripts > 1:
        return False

    lang = (language or "").strip().lower()
    if lang in _LATIN_LANGUAGES and not flags["latin"]:
        return False
    if lang == "chinese" and not flags["cjk"]:
        return False

    return True


def get_words_by_status(language, status):
    return [
        v.word
        for v in owned_query(VocabularyItem)
        .filter_by(language=language, mastery_status=status)
        .all()
    ]


def list_library_topics():
    """Distinct non-empty topic tags from the user's vocabulary library."""
    rows = (
        owned_query(VocabularyItem)
        .with_entities(VocabularyItem.topic)
        .filter(VocabularyItem.topic.isnot(None))
        .filter(VocabularyItem.topic != "")
        .distinct()
        .order_by(VocabularyItem.topic.asc())
        .all()
    )
    return [row[0].strip() for row in rows if row[0] and row[0].strip()]


def upsert_vocabulary(word, language, meaning, example, topic, source_type, source_id=None, document_id=None):
    user_id = current_user_id()
    item = owned_query(VocabularyItem).filter_by(word=word, language=language).first()
    if item:
        item.meaning = meaning or item.meaning
        item.example = example or item.example
        item.topic = topic or item.topic
        return item
    item = VocabularyItem(
        user_id=user_id,
        word=word,
        language=language,
        meaning=meaning,
        example=example,
        topic=topic,
        source_type=source_type,
        source_id=source_id,
        document_id=document_id,
        mastery_status="new",
    )
    db.session.add(item)
    return item


def save_deck(title, language, source_type, cards, source_id=None, document_id=None):
    deck = FlashcardDeck(
        user_id=current_user_id(),
        title=title,
        language=language,
        source_type=source_type,
        source_id=source_id,
    )
    db.session.add(deck)
    db.session.flush()

    for card in cards:
        vocab = upsert_vocabulary(
            word=card["front"],
            language=language,
            meaning=card["back"],
            example=card.get("example", ""),
            topic=card.get("topic", ""),
            source_type=source_type,
            source_id=deck.id,
            document_id=document_id,
        )
        try:
            embed_vocabulary_item(vocab)
        except Exception:
            pass  # never block deck save on a slow/broken embedding model
        db.session.add(
            Flashcard(
                deck_id=deck.id,
                vocabulary_item_id=vocab.id,
                front=card["front"],
                back=card["back"],
                example=card.get("example"),
                topic=card.get("topic"),
                difficulty=card.get("difficulty"),
                memory_tip=card.get("memory_tip"),
            )
        )

    db.session.commit()
    return deck


def get_related_by_topic(theme, language, limit=15):
    """Find prior vocabulary whose topic overlaps the new theme (simple keyword match)."""
    keyword = theme.split()[0].lower()
    return (
        owned_query(VocabularyItem)
        .filter_by(language=language)
        .filter(VocabularyItem.topic.ilike(f"%{keyword}%"))
        .limit(limit)
        .all()
    )


def build_continuity_context(theme, language):
    prior = get_related_by_topic(theme, language)
    if not prior:
        return ""
    words = ", ".join(v.word for v in prior)
    return f"\nThe learner previously studied related vocabulary: {words}. Use these to build examples and connections where helpful."


def embed_vocabulary_item(item):
    text = f"{item.word}: {item.meaning or ''}. {item.example or ''}"
    item.embedding_blob = embed_text(text)


def embed_vocabulary_item_if_missing(item):
    if not item.embedding_blob:
        embed_vocabulary_item(item)


def find_similar_vocab(word, language, top_k=5, exclude_word=None):
    query_vec = embed_text(word)
    if not query_vec:
        return []

    items = (
        owned_query(VocabularyItem)
        .filter_by(language=language)
        .filter(VocabularyItem.embedding_blob.isnot(None))
        .all()
    )

    scored = []
    for item in items:
        if exclude_word and item.word.lower() == exclude_word.lower():
            continue
        score = cosine_similarity(query_vec, item.embedding_blob)
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def related_words_for_conversation(topic, language, target_words, limit=8):
    """
    Prefer embedding neighbors when the model is already warm.
    Otherwise fall back to topic tags so conversation start stays instant.
    """
    targets = {w.lower() for w in (target_words or [])}
    related = []

    if is_model_loaded():
        for word in (target_words or [])[:3]:
            try:
                neighbors = find_similar_vocab(word, language, top_k=3, exclude_word=word)
                related.extend(v.word for v in neighbors)
            except Exception:
                pass

    if len(related) < limit:
        try:
            prior = get_related_by_topic(topic or "daily", language, limit=limit + len(targets))
            related.extend(v.word for v in prior)
        except Exception:
            pass

    deduped = []
    seen = set(targets)
    for word in related:
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(word)
        if len(deduped) >= limit:
            break
    return deduped


def build_embedding_continuity_context(theme, language, top_k=10):
    # Skip when cold — loading SentenceTransformer can stall generation for 10–30s.
    if not is_model_loaded():
        return ""
    neighbors = find_similar_vocab(theme, language, top_k=top_k, exclude_word=theme)
    if not neighbors:
        return ""
    words = ", ".join(v.word for v in neighbors)
    return f"\nRelated vocabulary the learner already knows: {words}. Connect new words to these."
