# routes/flashcards.py
import os

from flask import Blueprint, Response, render_template, request, stream_with_context
from ollama import ResponseError
from pydantic import ValidationError

from extensions import db
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


@bp.get("/flashcards")
def index():
    theme = request.args.get("theme", "").strip()
    return render_template("flashcards.html", theme=theme)


@bp.get("/stream")
def stream():
    language = request.args.get("language", "French").strip() or "French"
    theme = request.args.get("theme", "World Cup soccer").strip() or "World Cup soccer"
    provider = request.args.get("provider", "google")
    count = clean_count(request.args.get("count", "6"))

    @stream_with_context
    def events():
        try:
            profile = get_profile()
            exclude = get_words_by_status(language, "mastered")
            continuity = build_embedding_continuity_context(theme, language)
            if not continuity:
                continuity = build_continuity_context(theme, language)

            emitted = 0
            for card_data in card_stream(
                language,
                theme,
                count,
                provider,
                exclude_words=exclude,
                native_language=profile.native_language,
                continuity_context=continuity,
            ):
                try:
                    card = FlashcardSchema.model_validate(card_data)
                except ValidationError:
                    continue
                if not is_valid_vocab_word(card.front):
                    continue

                vocab = upsert_vocabulary(
                    word=card.front,
                    language=language,
                    meaning=card.back,
                    example=card.example or "",
                    topic=card.topic or theme,
                    source_type="topic",
                )
                try:
                    embed_vocabulary_item(vocab)
                except Exception:
                    pass  # never block flashcard streaming on a slow/broken embedding model
                db.session.commit()

                emitted += 1
                card_payload = card.model_dump()
                card_payload["vocab_id"] = vocab.id
                yield sse(
                    "card",
                    {"index": emitted, "total": count, "card": card_payload},
                )
                yield sse("progress", {"current": emitted, "total": count})

                if emitted >= count:
                    break

            if emitted == 0:
                yield sse("error", {"message": "The model didn't return any cards. Try again."})
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

        yield sse("done", {"message": "Deck ready"})

    return Response(
        events(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )