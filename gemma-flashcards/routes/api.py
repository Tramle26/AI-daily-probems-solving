import os

from flask import Blueprint, Response, jsonify, request, session, stream_with_context
from flask_login import login_required
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
    document_assistant_reply,
    extract_document_vocabulary,
    extract_vocab_from_answer,
    generate_document_followups,
    sse,
    summarize_conversation,
)
from services.ownership import current_user_id, get_owned_or_404, owned_query
from services.profile import get_profile
from services.progress import generate_weekly_report, get_progress_charts, upsert_daily_snapshot
from services.quiz import (
    build_fill_blank,
    build_multiple_choice,
    create_quiz_session,
    get_quiz_pool,
    grade_and_update_mastery,
)
from services.retrieval import index_document, sample_document_chunks
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
@login_required
def progress_charts():
    range_key = request.args.get("range", "week")
    return jsonify(get_progress_charts(range_key))


@bp.get("/progress/weekly-report")
@login_required
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
@login_required
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
@login_required
def generate_from_document(doc_id):
    data = request.get_json()
    doc = get_owned_or_404(UploadedDocument, doc_id)
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

    language = doc.language or data.get("language", "English")
    for card in cards:
        upsert_vocabulary(
            word=card["front"],
            language=language,
            meaning=card["back"],
            example=card.get("example", ""),
            topic=card.get("topic", ""),
            source_type="document",
            source_id=doc.id,
            document_id=doc.id,
        )
    db.session.commit()
    upsert_daily_snapshot()
    check_level_completion()

    if data.get("save", False):
        deck = save_deck(
            title=doc.filename or "Document deck",
            language=language,
            source_type="document",
            cards=cards,
            source_id=doc.id,
            document_id=doc.id,
        )
        return jsonify({"cards": cards, "deck_id": deck.id, "saved_to_library": True})

    return jsonify({"cards": cards, "saved_to_library": True})


@bp.post("/dictionary/search")
@login_required
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
            for v in owned_query(VocabularyItem).filter_by(language=target_language).limit(10).all()
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
        user_id=current_user_id(),
        word=word,
        language=lookup_language,
        result_json=result.model_dump(),
    )
    db.session.add(search)
    db.session.commit()

    payload = result.model_dump()
    payload["search_id"] = search.id
    payload["vocab_language"] = target_language
    return jsonify(payload)


@bp.post("/dictionary/add")
@login_required
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
        search = owned_query(DictionarySearch).filter_by(id=data["search_id"]).first()
        if search:
            search.added_to_deck = True
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/quiz/start")
@login_required
def quiz_start():
    data = request.get_json()
    items = get_quiz_pool(
        data["source_type"],
        data.get("source_id"),
        data.get("limit", 10),
        topic=data.get("topic"),
    )
    if not items:
        return jsonify({"error": "No vocabulary available for this quiz source."}), 400

    builder = build_fill_blank if data["quiz_type"] == "fill_blank" else build_multiple_choice
    questions = builder(items)
    if not questions:
        return jsonify({"error": "Could not build questions from vocabulary."}), 400

    quiz_session = create_quiz_session(
        source_type=data["source_type"],
        quiz_type=data["quiz_type"],
        source_id=data.get("source_id"),
        total=len(questions),
    )
    db.session.commit()
    return jsonify({"session_id": quiz_session.id, "questions": questions})


@bp.post("/quiz/submit")
@login_required
def quiz_submit():
    data = request.get_json()
    quiz_session = get_owned_or_404(QuizSession, data["session_id"])
    score, total = grade_and_update_mastery(quiz_session, data["answers"])
    accuracy = round(score / total * 100) if total else 0
    upsert_daily_snapshot()
    check_level_completion()
    return jsonify({"score": score, "total": total, "accuracy": accuracy})


@bp.post("/review/feedback")
@login_required
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
@login_required
def review_mini_quiz():
    data = request.get_json()
    quiz_session = QuizSession(
        user_id=current_user_id(),
        source_type="review",
        quiz_type="multiple_choice",
    )
    db.session.add(quiz_session)
    db.session.flush()
    score, total = grade_and_update_mastery(quiz_session, data["answers"])
    upsert_daily_snapshot()
    check_level_completion()
    return jsonify({"score": score, "total": total})


@bp.post("/ask")
@login_required
def api_ask():
    data = request.get_json()
    doc = get_owned_or_404(UploadedDocument, data["document_id"])
    profile = get_profile()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    client = genai.Client(api_key=api_key)
    answer, sources = ask_document_smart(client, doc, data["question"], profile.native_language)

    entry = AskHistory(
        user_id=current_user_id(),
        document_id=doc.id,
        question=data["question"],
        answer=answer,
    )
    db.session.add(entry)
    db.session.commit()

    return jsonify({"answer": answer, "ask_id": entry.id, "sources": sources})


@bp.post("/ask/<int:ask_id>/make-cards")
@login_required
def ask_make_cards(ask_id):
    entry = get_owned_or_404(AskHistory, ask_id)
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
@login_required
def document_index(doc_id):
    doc = get_owned_or_404(UploadedDocument, doc_id)
    reindex = request.json.get("reindex", False) if request.is_json else False
    count = index_document(doc.id, doc.raw_text, reindex=reindex)
    return jsonify({"chunks_indexed": count})


@bp.post("/documents/<int:doc_id>/assistant/start")
@login_required
def document_assistant_start(doc_id):
    """Index with PyTorch embeddings if needed, then propose follow-up questions."""
    doc = get_owned_or_404(UploadedDocument, doc_id)
    profile = get_profile()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    try:
        chunks_indexed = index_document(doc.id, doc.raw_text)
    except Exception as exc:
        return jsonify({"error": f"Could not index document with embeddings: {exc}"}), 500

    excerpts = sample_document_chunks(doc.id, top_k=6)
    if not excerpts:
        excerpts = [doc.raw_text[:4000]]

    client = genai.Client(api_key=api_key)
    try:
        followups = generate_document_followups(
            client,
            excerpts,
            language=doc.language or profile.target_language,
            native_language=profile.native_language,
            filename=doc.filename or "",
        )
    except Exception as exc:
        return jsonify({"error": f"Assistant failed: {exc}"}), 500

    return jsonify({
        "opening": followups.opening,
        "questions": followups.questions,
        "chunks_indexed": chunks_indexed,
    })


@bp.post("/documents/<int:doc_id>/assistant/chat")
@login_required
def document_assistant_chat(doc_id):
    """Answer a learner message with PyTorch RAG and ask a follow-up question."""
    doc = get_owned_or_404(UploadedDocument, doc_id)
    profile = get_profile()
    data = request.get_json() or {}
    user_message = (data.get("message") or "").strip()
    messages = data.get("messages") or []

    if not user_message:
        return jsonify({"error": "Enter a message."}), 400

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Missing GEMINI_API_KEY"}), 500

    # Ensure embeddings exist so retrieval can use PyTorch vectors.
    try:
        index_document(doc.id, doc.raw_text)
    except Exception:
        pass

    client = genai.Client(api_key=api_key)
    try:
        turn, sources = document_assistant_reply(
            client,
            doc,
            user_message=user_message,
            messages=messages,
            language=doc.language or profile.target_language,
            native_language=profile.native_language,
        )
    except Exception as exc:
        return jsonify({"error": f"Assistant failed: {exc}"}), 500

    entry = AskHistory(
        user_id=current_user_id(),
        document_id=doc.id,
        question=user_message,
        answer=f"{turn.reply}\n\nFollow-up: {turn.follow_up}",
    )
    db.session.add(entry)
    db.session.commit()

    return jsonify({
        "reply": turn.reply,
        "follow_up": turn.follow_up,
        "sources": sources,
        "ask_id": entry.id,
    })


@bp.post("/semantic-search")
@login_required
def semantic_search():
    # RAG answer or vocabulary extraction mode — see original step 2b.6
    ...

@bp.get("/vocabulary/<int:vocab_id>/similar")
@login_required
def vocabulary_similar(vocab_id):
    item = get_owned_or_404(VocabularyItem, vocab_id)
    similar = find_similar_vocab(item.word, item.language, top_k=8, exclude_word=item.word)
    return jsonify({
        "word": item.word,
        "similar": [{"word": v.word, "meaning": v.meaning, "topic": v.topic} for v in similar],
    })

@bp.post("/conversation/start")
@login_required
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
        user_id=current_user_id(),
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
@login_required
def conversation_message(session_id):
    data = request.get_json() or {}
    user_text = (data.get("message") or "").strip()
    if not user_text:
        return jsonify({"error": "Message required"}), 400

    conv = get_owned_or_404(ConversationSession, session_id)
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
@login_required
def conversation_finish(session_id):
    from datetime import datetime

    conv = get_owned_or_404(ConversationSession, session_id)
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
@login_required
def embeddings_warmup():
    """Kick off embedding-model load without blocking the request."""
    import threading

    from services.embeddings import is_model_loaded, warmup_model

    if is_model_loaded():
        return jsonify({"ready": True, "warmed": False})

    threading.Thread(target=warmup_model, daemon=True).start()
    return jsonify({"ready": False, "warmed": True})
