import json
import os
from dotenv import load_dotenv
from flask import Flask, Response, render_template, request, stream_with_context
from google import genai
from google.genai import types
from ollama import Client as OllamaClient
from ollama import ResponseError
from pydantic import BaseModel , Field, ValidationError

from extensions import db

load_dotenv()

GOOGLE_MODEL = "gemma-4-26b-a4b-it"

class Flashcard(BaseModel):
    front: str = Field(description="A short word or phrase in the target language.")
    back: str = Field(description="The English meaning and a tiny learning note.")
    example: str = Field(description="A short example sentence using the theme.")

class Deck(BaseModel):
    cards: list[Flashcard] = Field(description="The full set of flashcards.")

def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

def clean_count(value):
    try:
        return min(max(int(value), 1), 20)
    except ValueError:
        return 6


def build_prompt(language, theme, count):
    return f"""
Create a deck of exactly {count} flashcards for a beginner learning {language}.

Theme: {theme}

Each flashcard has:
- front: a short word or phrase in {language}
- back: the English meaning plus a tiny, friendly learning note
- example: a short example sentence that fits the theme

Rules:
- Do not repeat cards.
- Order the deck from easier to harder.
"""

def stream_cards(text_pieces):
    """Yield each flashcard the moment it is complete in the JSON stream.

    The model streams one big object like {"cards": [ {...}, {...} ]} a few
    characters at a time. We walk the growing text and, each time a card's
    closing "}" arrives, we hand that finished card back so the browser can
    show it immediately instead of waiting for the whole deck.
    """
    buffer = ""
    scanned = 0  # how far into buffer we have already looked
    depth = 0  # current { } nesting depth
    in_string = False  # are we inside a "quoted string"?
    escaped = False  # was the previous character a backslash?
    start = None  # index in buffer where the current card object began

    for piece in text_pieces:
        buffer += piece
        while scanned < len(buffer):
            char = buffer[scanned]

            if in_string:
                # Inside a string, ignore braces; just watch for the closing quote.
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "{":
                depth += 1
                if depth == 2:  # depth 1 is the outer wrapper; depth 2 is a card
                    start = scanned
            elif char == "}":
                if depth == 2 and start is not None:
                    try:
                        yield json.loads(buffer[start : scanned + 1])
                    except json.JSONDecodeError:
                        pass
                    start = None
                depth -= 1

            scanned += 1


def google_cards(client, language, theme, count):
    # generate_content_stream returns the deck as a stream of text chunks.
    stream = client.models.generate_content_stream(
        model=GOOGLE_MODEL,
        contents=build_prompt(language, theme, count),
        config=types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json",
            response_schema=Deck,
        ),
    )
    return (chunk.text for chunk in stream if chunk.text)


def local_cards(client, language, theme, count):
    # Ollama streams the same JSON; format=<schema> keeps the output structured.
    stream = client.chat(
        model=LOCAL_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You create short, friendly language-learning flashcards.",
            },
            {
                "role": "user",
                "content": build_prompt(language, theme, count),
            },
        ],
        format=Deck.model_json_schema(),
        options={"temperature": 0.7},
        stream=True,
    )
    return (chunk.message.content for chunk in stream if chunk.message.content)


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///learning.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)

    with app.app_context():
        import models  # noqa: F401 — register all models with SQLAlchemy
        db.create_all()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/stream")
    def stream():
        # The browser's EventSource can only make GET requests, so the deck settings
        # arrive in the query string.
        language = request.args.get("language", "French").strip() or "French"
        theme = request.args.get("theme", "World Cup soccer").strip() or "World Cup soccer"
        provider = request.args.get("provider", "google")
        count = clean_count(request.args.get("count", "6"))

        @stream_with_context
        def events():
            try:
                # Pick a provider and get back a stream of raw JSON text pieces.
                if provider == "local":
                    client = OllamaClient()
                    pieces = local_cards(client, language, theme, count)
                else:
                    api_key = os.environ.get("GEMINI_API_KEY")
                    if not api_key:
                        yield sse("error", {"message": "Missing GEMINI_API_KEY in your .env file."})
                        return

                    client = genai.Client(api_key=api_key)
                    pieces = google_cards(client, language, theme, count)

                # Turn the stream into finished cards and push each one to the browser.
                emitted = 0
                for card_data in stream_cards(pieces):
                    try:
                        card = Flashcard.model_validate(card_data)
                    except ValidationError:
                        continue  # skip anything that is not a well-formed card

                    emitted += 1
                    yield sse(
                        "card",
                        {"index": emitted, "total": count, "card": card.model_dump()},
                    )
                    yield sse("progress", {"current": emitted, "total": count})

                    if emitted >= count:  # stop if the model is feeling generous
                        break

                if emitted == 0:
                    yield sse("error", {"message": "The model didn't return any cards. Try again."})
                    return

            except ResponseError as exc:
                yield sse(
                    "error",
                    {
                        "message": (
                            f"Ollama error: {exc.error}. "
                            f"Try running: ollama pull {LOCAL_MODEL}"
                        )
                    },
                )
                return
            except Exception as exc:
                yield sse("error", {"message": f"Something went wrong: {exc}"})
                return

            yield sse("done", {"message": "Deck ready"})

        # text/event-stream keeps the HTTP connection open so we can push cards over time.
        return Response(
            events(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)