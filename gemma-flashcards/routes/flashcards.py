# routes/flashcards.py
import threading

from flask import Blueprint, Response, current_app, render_template, request, stream_with_context
from flask_login import login_required
from ollama import ResponseError
from pydantic import ValidationError

from extensions import db
from models import VocabularyItem
from services.embeddings import is_model_loaded
from services.gemma import FlashcardSchema, card_stream, clean_count, sse
from services.profile import get_profile
from services.vocabulary import (
    build_continuity_context,
    build_embedding_continuity_context,
    embed_vocabulary_item,
    get_words_by_status,
    is_valid_vocab_word,
    upsert_vocabulary,
)

bp = Blueprint("flashcards", __name__)


def _embed_vocab_ids(app, vocab_ids):
    with app.app_context():
        for vocab_id in vocab_ids:
            vocab = db.session.get(VocabularyItem, vocab_id)
            if not vocab:
                continue
            try:
                embed_vocabulary_item(vocab)
                db.session.commit()
            except Exception:
                db.session.rollback()


@bp.get("/flashcards")
@login_required
def index():
    topic = (
        request.args.get("topic", "").strip()
        or request.args.get("theme", "").strip()
    )
    return render_template("flashcards.html", topic=topic)


@bp.get("/stream")
@login_required
def stream():
    language = request.args.get("language", "French").strip() or "French"
    topic = (
        request.args.get("topic", "").strip()
        or request.args.get("theme", "").strip()
        or "World Cup soccer"
    )
    provider = request.args.get("provider", "google")
    count = clean_count(request.args.get("count", "6"))

    @stream_with_context
    def events():
        pending_embed_ids = []
        try:
            profile = get_profile()
            exclude = get_words_by_status(language, "mastered")
            # Never cold-load embeddings before streaming — that alone can take 10–30s.
            continuity = ""
            if is_model_loaded():
                continuity = build_embedding_continuity_context(topic, language)
            if not continuity:
                continuity = build_continuity_context(topic, language)

            emitted = 0
            # Ask for a few extras so filtered junk doesn't shrink the deck.
            request_count = min(count + 4, 20)
            for card_data in card_stream(
                language,
                topic,
                request_count,
                provider,
                exclude_words=exclude,
                native_language=profile.native_language,
                continuity_context=continuity,
            ):
                try:
                    card = FlashcardSchema.model_validate(card_data)
                except ValidationError:
                    continue
                if not is_valid_vocab_word(card.front, language):
                    continue

                vocab = upsert_vocabulary(
                    word=card.front,
                    language=language,
                    meaning=card.back,
                    example=card.example or "",
                    topic=card.topic or topic,
                    source_type="topic",
                )
                db.session.commit()

                emitted += 1
                card_payload = card.model_dump()
                card_payload["vocab_id"] = vocab.id
                # Emit first so the UI isn't blocked on embedding / model load.
                yield sse(
                    "card",
                    {"index": emitted, "total": count, "card": card_payload},
                )
                yield sse("progress", {"current": emitted, "total": count})
                pending_embed_ids.append(vocab.id)

                if emitted >= count:
                    break

            if emitted == 0:
                yield sse("error", {"message": "The model didn't return any valid cards. Try again."})
                return

        except ResponseError as exc:
            yield sse("error", {"message": f"Ollama error: {exc.error}"})
            return
        except RuntimeError as exc:
            yield sse("error", {"message": str(exc)})
            return
        except Exception as exc:
            yield sse("error", {"message": f"Something went wrong: {exc}"})
            return

        if pending_embed_ids:
            app = current_app._get_current_object()
            threading.Thread(
                target=_embed_vocab_ids,
                args=(app, list(pending_embed_ids)),
                daemon=True,
            ).start()

        yield sse("done", {"message": "Deck ready"})

    return Response(
        events(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
