from extensions import db
from models import Flashcard, FlashcardDeck, VocabularyItem
from services.embeddings import cosine_similarity, embed_text


def get_words_by_status(language, status):
    return [
        v.word
        for v in VocabularyItem.query.filter_by(language=language, mastery_status=status).all()
    ]


def upsert_vocabulary(word, language, meaning, example, topic, source_type, source_id=None, document_id=None):
    item = VocabularyItem.query.filter_by(word=word, language=language).first()
    if item:
        item.meaning = meaning or item.meaning
        item.example = example or item.example
        item.topic = topic or item.topic
        return item
    item = VocabularyItem(
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
    keyword = theme.split()[0].lower()  # e.g. "soccer" or "World"
    return (
        VocabularyItem.query.filter_by(language=language)
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

    items = VocabularyItem.query.filter_by(language=language).filter(
        VocabularyItem.embedding_blob.isnot(None)
    ).all()

    scored = []
    for item in items:
        if exclude_word and item.word.lower() == exclude_word.lower():
            continue
        score = cosine_similarity(query_vec, item.embedding_blob)
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def build_embedding_continuity_context(theme, language, top_k=10):
    neighbors = find_similar_vocab(theme, language, top_k=top_k, exclude_word=theme)
    if not neighbors:
        return ""
    words = ", ".join(v.word for v in neighbors)
    return f"\nRelated vocabulary the learner already knows: {words}. Connect new words to these."