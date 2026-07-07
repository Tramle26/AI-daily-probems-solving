# routes/flashcards.py
import os

from flask import Blueprint, Response, render_template, request, stream_with_context
from google import genai
from ollama import Client as OllamaClient
from ollama import ResponseError
from pydantic import ValidationError

from services.gemma import (
    FlashcardSchema,
    card_stream,
    clean_count,
    sse,
)
from services.profile import get_profile
from services.vocabulary import get_words_by_status

bp = Blueprint("flashcards", __name__)


@bp.get("/flashcards")
def index():
    return render_template("flashcards.html")


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

            emitted = 0
            for card_data in card_stream(
                language,
                theme,
                count,
                provider,
                exclude_words=exclude,
                native_language=profile.native_language,
            ):
                try:
                    card = FlashcardSchema.model_validate(card_data)
                except ValidationError:
                    continue

                emitted += 1
                yield sse(
                    "card",
                    {"index": emitted, "total": count, "card": card.model_dump()},
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