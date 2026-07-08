import os

from flask import Blueprint, jsonify, request
from google import genai

from extensions import db
from models import DictionarySearch, QuizSession, UploadedDocument, VocabularyItem
from services.gemma import dictionary_lookup, extract_document_vocabulary
from services.profile import get_profile
from services.quiz import (
    build_fill_blank,
    build_multiple_choice,
    get_quiz_pool,
    grade_and_update_mastery,
)
from services.vocabulary import save_deck, upsert_vocabulary

bp = Blueprint("api", __name__, url_prefix="/api")


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

    client = genai.Client(api_key=api_key)
    result = extract_document_vocabulary(
        client,
        doc.raw_text,
        doc.language or data["language"],
        max_words,
        data.get("native_language", "English"),
    )

    cards = [
        {
            "front": item.word,
            "back": item.meaning,
            "example": item.example,
            "topic": item.topic,
            "difficulty": item.difficulty,
        }
        for item in result.items
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
    language = data.get("language") or get_profile().target_language
    profile = get_profile()

    related = [v.word for v in VocabularyItem.query.filter_by(language=language).limit(10).all()]

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    client = genai.Client(api_key=api_key)
    result = dictionary_lookup(client, word, language, profile.native_language, related)

    search = DictionarySearch(word=word, language=language, result_json=result.model_dump())
    db.session.add(search)
    db.session.commit()

    payload = result.model_dump()
    payload["search_id"] = search.id
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
