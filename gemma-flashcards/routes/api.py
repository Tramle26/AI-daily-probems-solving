import os

from flask import Blueprint, Response, jsonify, request, session, stream_with_context
from google import genai

from extensions import db
from models import (
    AskHistory,
    ConversationSession,
    DictionarySearch,
    QuizSession,
    UploadedDocument,
    VocabularyItem,
)
from services.gemma import (
    ask_document_smart,
    build_conversation_system_prompt,
    conversation_reply,
    conversation_reply_stream,
    dictionary_lookup,
    extract_document_vocabulary,
    extract_vocab_from_answer,
    sse,
    summarize_conversation,
)
from services.profile import get_profile
from services.progress import generate_weekly_report, get_progress_charts, upsert_daily_snapshot
from services.quiz import (
    build_fill_blank,
    build_multiple_choice,
    get_quiz_pool,
    grade_and_update_mastery,
)
from services.retrieval import index_document
from services.review import mark_review_feedback
from services.roadmap import check_level_completion
from services.vocabulary import (
    find_similar_vocab,
    is_valid_vocab_word,
    related_words_for_conversation,
    save_deck,
    upsert_vocabulary,
)

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.get("/progress/charts")
def progress_charts():
    range_key = request.args.get("range", "week")
    return jsonify(get_progress_charts(range_key))


@bp.get("/progress/weekly-report")
def weekly_report():
    force = request.args.get("refresh") == "1"
    cached = session.get("weekly_report")
    if cached and not force:
        payload = dict(cached)
        payload["cached"] = True
        return jsonify({"report": payload})

    try:
        report = generate_weekly_report()
    except Exception as exc:
        return jsonify({"error": f"Report failed: {exc}"}), 500

    session["weekly_report"] = report
    return jsonify({"report": report})


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
    upsert_daily_snapshot()
    check_level_completion()
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

    embedding_neighbors = find_similar_vocab(word, target_language, top_k=5)
    if embedding_neighbors:
        related = [v.word for v in embedding_neighbors]
    else:
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

    emb_words = [v.word for v in embedding_neighbors]
    combined = list(dict.fromkeys(emb_words + result.similar_words))
    result.similar_words = combined[:8]

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
    upsert_daily_snapshot()
    check_level_completion()
    return jsonify({"score": score, "total": total, "accuracy": accuracy})


@bp.post("/review/feedback")
def review_feedback():
    data = request.get_json()
    item = mark_review_feedback(data["vocab_id"], data["got_it"])
    check_level_completion()
    payload = {"ok": True}
    if item and item.next_review_at:
        payload["next_review_at"] = item.next_review_at.isoformat()
        payload["interval_days"] = item.interval_days
    return jsonify(payload)


@bp.post("/review/mini-quiz")
def review_mini_quiz():
    data = request.get_json()
    session = QuizSession(source_type="review", quiz_type="multiple_choice")
    db.session.add(session)
    db.session.flush()
    score, total = grade_and_update_mastery(session, data["answers"])
    upsert_daily_snapshot()
    check_level_completion()
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
    answer, sources = ask_document_smart(client, doc, data["question"], profile.native_language)

    entry = AskHistory(document_id=doc.id, question=data["question"], answer=answer)
    db.session.add(entry)
    db.session.commit()

    return jsonify({"answer": answer, "ask_id": entry.id, "sources": sources})


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


@bp.post("/documents/<int:doc_id>/index")
def document_index(doc_id):
    doc = UploadedDocument.query.get_or_404(doc_id)
    reindex = request.json.get("reindex", False) if request.is_json else False
    count = index_document(doc.id, doc.raw_text, reindex=reindex)
    return jsonify({"chunks_indexed": count})


@bp.post("/semantic-search")
def semantic_search():
    # RAG answer or vocabulary extraction mode — see original step 2b.6
    ...


@bp.get("/vocabulary/<int:vocab_id>/similar")
def vocabulary_similar(vocab_id):
    item = VocabularyItem.query.get_or_404(vocab_id)
    similar = find_similar_vocab(item.word, item.language, top_k=8, exclude_word=item.word)
    return jsonify({
        "word": item.word,
        "similar": [{"word": v.word, "meaning": v.meaning, "topic": v.topic} for v in similar],
    })

@bp.post("/conversation/start")
def conversation_start():
    data = request.get_json() or {}
    profile = get_profile()
    topic = (data.get("topic") or "daily life").strip()
    difficulty = data.get("difficulty") or profile.level or "beginner"
    target_words = [w.strip() for w in (data.get("target_words") or []) if w and str(w).strip()]
    target_words = target_words[:8]

    # Avoid cold-loading the embedding model here — that can take 10–30s.
    related_words = related_words_for_conversation(
        topic, profile.target_language, target_words, limit=8
    )

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    system_prompt = build_conversation_system_prompt(
        profile.target_language,
        topic,
        difficulty,
        target_words,
        related_words,
        profile.native_language,
    )

    conv = ConversationSession(
        topic=topic,
        difficulty=difficulty,
        target_words=target_words,
        messages=[],
    )
    db.session.add(conv)
    db.session.commit()

    meta = {
        "session_id": conv.id,
        "topic": topic,
        "difficulty": difficulty,
        "target_words": target_words,
        "related_words": related_words,
    }

    want_stream = (
        request.args.get("stream") == "1"
        or "text/event-stream" in (request.headers.get("Accept") or "")
    )

    try:
        client = genai.Client(api_key=api_key)
        if want_stream:

            @stream_with_context
            def generate():
                yield sse("meta", meta)
                parts = []
                try:
                    for chunk in conversation_reply_stream(client, system_prompt, []):
                        parts.append(chunk)
                        yield sse("token", {"text": chunk})
                    opening = "".join(parts).strip()
                    if not opening:
                        yield sse("error", {"error": "Empty opening from model"})
                        return
                    messages = [{"role": "assistant", "content": opening}]
                    conv.messages = messages
                    from sqlalchemy.orm.attributes import flag_modified

                    flag_modified(conv, "messages")
                    db.session.commit()
                    yield sse("done", {**meta, "messages": messages, "reply": opening})
                except Exception as exc:
                    db.session.rollback()
                    yield sse("error", {"error": f"Conversation start failed: {exc}"})

            return Response(
                generate(),
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        opening = conversation_reply(client, system_prompt, [])
    except Exception as exc:
        return jsonify({"error": f"Conversation start failed: {exc}"}), 500

    messages = [{"role": "assistant", "content": opening}]
    conv.messages = messages
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(conv, "messages")
    db.session.commit()

    return jsonify({**meta, "messages": messages})


@bp.post("/conversation/<int:session_id>/message")
def conversation_message(session_id):
    data = request.get_json() or {}
    user_text = (data.get("message") or "").strip()
    if not user_text:
        return jsonify({"error": "Message required"}), 400

    conv = ConversationSession.query.get_or_404(session_id)
    if conv.finished_at:
        return jsonify({"error": "Conversation already finished"}), 400

    profile = get_profile()
    messages = list(conv.messages or [])
    messages.append({"role": "user", "content": user_text})

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    system_prompt = build_conversation_system_prompt(
        profile.target_language,
        conv.topic or "daily life",
        conv.difficulty or profile.level or "beginner",
        conv.target_words or [],
        [],
        profile.native_language,
    )

    want_stream = (
        request.args.get("stream") == "1"
        or "text/event-stream" in (request.headers.get("Accept") or "")
    )

    try:
        client = genai.Client(api_key=api_key)
        if want_stream:

            @stream_with_context
            def generate():
                parts = []
                try:
                    for chunk in conversation_reply_stream(client, system_prompt, messages):
                        parts.append(chunk)
                        yield sse("token", {"text": chunk})
                    reply = "".join(parts).strip()
                    if not reply:
                        yield sse("error", {"error": "Empty reply from model"})
                        return
                    full_messages = messages + [{"role": "assistant", "content": reply}]
                    conv.messages = full_messages
                    from sqlalchemy.orm.attributes import flag_modified

                    flag_modified(conv, "messages")
                    db.session.commit()
                    yield sse("done", {"reply": reply, "messages": full_messages})
                except Exception as exc:
                    db.session.rollback()
                    yield sse("error", {"error": f"Reply failed: {exc}"})

            return Response(
                generate(),
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        reply = conversation_reply(client, system_prompt, messages)
    except Exception as exc:
        return jsonify({"error": f"Reply failed: {exc}"}), 500

    messages.append({"role": "assistant", "content": reply})
    conv.messages = messages
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(conv, "messages")
    db.session.commit()

    return jsonify({"reply": reply, "messages": messages})


@bp.post("/conversation/<int:session_id>/finish")
def conversation_finish(session_id):
    from datetime import datetime

    conv = ConversationSession.query.get_or_404(session_id)
    if conv.finished_at:
        return jsonify(
            {
                "summary": conv.summary,
                "words_used_correctly": conv.words_used_correctly or [],
                "words_missed": conv.words_missed or [],
                "corrections": conv.corrections or [],
            }
        )

    profile = get_profile()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    try:
        client = genai.Client(api_key=api_key)
        result = summarize_conversation(
            client,
            conv.messages or [],
            conv.target_words or [],
            profile.native_language,
        )
    except Exception as exc:
        return jsonify({"error": f"Summary failed: {exc}"}), 500

    conv.words_used_correctly = result.words_used_correctly
    conv.words_missed = result.words_missed
    conv.corrections = result.corrections
    conv.summary = result.summary
    conv.finished_at = datetime.utcnow()
    db.session.commit()

    return jsonify(
        {
            "summary": conv.summary,
            "words_used_correctly": conv.words_used_correctly or [],
            "words_missed": conv.words_missed or [],
            "corrections": conv.corrections or [],
        }
    )


@bp.post("/embeddings/warmup")
def embeddings_warmup():
    """Kick off embedding-model load without blocking the request."""
    import threading

    from services.embeddings import is_model_loaded, warmup_model

    if is_model_loaded():
        return jsonify({"ready": True, "warmed": False})

    threading.Thread(target=warmup_model, daemon=True).start()
    return jsonify({"ready": False, "warmed": True})
