import os

from flask import Blueprint, jsonify, request
from google import genai

from extensions import db
from models import AskHistory, DictionarySearch, QuizSession, UploadedDocument, VocabularyItem
from services.documents import keyword_search_chunks
from services.gemma import (
    ask_document,
    dictionary_lookup,
    extract_document_vocabulary,
    extract_vocab_from_answer,
)
from services.profile import get_profile
from services.progress import get_progress_charts
from services.quiz import (
    build_fill_blank,
    build_multiple_choice,
    get_quiz_pool,
    grade_and_update_mastery,
)
from services.review import mark_review_feedback
from services.vocabulary import is_valid_vocab_word, save_deck, upsert_vocabulary

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.get("/progress/charts")
def progress_charts():
    range_key = request.args.get("range", "week")
    return jsonify(get_progress_charts(range_key))


@bp.post("/decks")
def create_deck():
    data = request.get_json()
    if not data or not data.get("cards"):
        return jsonify({"error": "No cards provided"}), 400

    deck = save_deck(
        title=data.get("title", "My Deck"),
        language=data["language"],
        source_type=data.get("source_type", "topic"),
        cards=data["cards"],
        source_id=data.get("source_id"),
        document_id=data.get("document_id"),
    )
    return jsonify({"id": deck.id, "title": deck.title}), 201


@bp.post("/documents/<int:doc_id>/generate")
def generate_from_document(doc_id):
    data = request.get_json()
    doc = UploadedDocument.query.get_or_404(doc_id)
    max_words = min(int(data.get("max_words", 10)), 20)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    try:
        client = genai.Client(api_key=api_key)
        result = extract_document_vocabulary(
            client,
            doc.raw_text,
            doc.language or data["language"],
            max_words,
            data.get("native_language", "English"),
        )
    except Exception as exc:
        return jsonify({"error": f"Generation failed: {exc}"}), 500

    cards = [
        {
            "front": item.word,
            "back": item.meaning,
            "example": item.example,
            "topic": item.topic,
            "difficulty": item.difficulty,
        }
        for item in result.items
        if is_valid_vocab_word(item.word)
    ]

    if data.get("save", False):
        deck = save_deck(
            title=doc.filename or "Document deck",
            language=doc.language,
            source_type="document",
            cards=cards,
            source_id=doc.id,
            document_id=doc.id,
        )
        return jsonify({"cards": cards, "deck_id": deck.id})

    return jsonify({"cards": cards})


@bp.post("/dictionary/search")
def dictionary_search():
    data = request.get_json()
    word = data["word"].strip()
    profile = get_profile()
    lookup_language = data.get("language") or profile.target_language
    target_language = profile.target_language
    native_language = profile.native_language

    related = [
        v.word
        for v in VocabularyItem.query.filter_by(language=target_language).limit(10).all()
    ]

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    client = genai.Client(api_key=api_key)
    result = dictionary_lookup(
        client, word, lookup_language, target_language, native_language, related
    )

    search = DictionarySearch(
        word=word, language=lookup_language, result_json=result.model_dump()
    )
    db.session.add(search)
    db.session.commit()

    payload = result.model_dump()
    payload["search_id"] = search.id
    payload["vocab_language"] = target_language
    return jsonify(payload)


@bp.post("/dictionary/add")
def dictionary_add():
    data = request.get_json()
    upsert_vocabulary(
        word=data["word"],
        language=data["language"],
        meaning=data["meaning"],
        example=data.get("example", ""),
        topic=data.get("topic", ""),
        source_type="dictionary",
    )
    if data.get("search_id"):
        search = DictionarySearch.query.get(data["search_id"])
        if search:
            search.added_to_deck = True
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/quiz/start")
def quiz_start():
    data = request.get_json()
    items = get_quiz_pool(data["source_type"], data.get("source_id"), data.get("limit", 10))
    if not items:
        return jsonify({"error": "No vocabulary available for this quiz source."}), 400

    builder = build_fill_blank if data["quiz_type"] == "fill_blank" else build_multiple_choice
    questions = builder(items)
    if not questions:
        return jsonify({"error": "Could not build questions from vocabulary."}), 400

    session = QuizSession(
        source_type=data["source_type"],
        source_id=data.get("source_id"),
        quiz_type=data["quiz_type"],
        total=len(questions),
    )
    db.session.add(session)
    db.session.commit()
    return jsonify({"session_id": session.id, "questions": questions})


@bp.post("/quiz/submit")
def quiz_submit():
    data = request.get_json()
    session = QuizSession.query.get_or_404(data["session_id"])
    score, total = grade_and_update_mastery(session, data["answers"])
    accuracy = round(score / total * 100) if total else 0
    return jsonify({"score": score, "total": total, "accuracy": accuracy})


@bp.post("/review/feedback")
def review_feedback():
    data = request.get_json()
    mark_review_feedback(data["vocab_id"], data["got_it"])
    return jsonify({"ok": True})


@bp.post("/review/mini-quiz")
def review_mini_quiz():
    data = request.get_json()
    session = QuizSession(source_type="review", quiz_type="multiple_choice")
    db.session.add(session)
    db.session.flush()
    score, total = grade_and_update_mastery(session, data["answers"])
    return jsonify({"score": score, "total": total})


@bp.post("/ask")
def api_ask():
    data = request.get_json()
    doc = UploadedDocument.query.get_or_404(data["document_id"])
    profile = get_profile()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    client = genai.Client(api_key=api_key)
    snippets = keyword_search_chunks(doc.raw_text, data["question"])
    context = "\n\n".join(snippets) if snippets else doc.raw_text[:8000]
    answer = ask_document(client, context, data["question"], profile.native_language)

    entry = AskHistory(document_id=doc.id, question=data["question"], answer=answer)
    db.session.add(entry)
    db.session.commit()

    return jsonify({"answer": answer, "ask_id": entry.id})


@bp.post("/ask/<int:ask_id>/make-cards")
def ask_make_cards(ask_id):
    entry = AskHistory.query.get_or_404(ask_id)
    doc = entry.document
    profile = get_profile()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    client = genai.Client(api_key=api_key)
    suggestions = extract_vocab_from_answer(
        client, entry.answer, doc.language, profile.native_language
    )
    cards = [
        {"front": w.word, "back": w.meaning, "example": w.example, "topic": w.topic}
        for w in suggestions.words
    ]
    deck = save_deck(
        f"From: {entry.question[:40]}",
        doc.language,
        "ask",
        cards,
        document_id=doc.id,
    )
    return jsonify({"deck_id": deck.id, "cards": cards})
