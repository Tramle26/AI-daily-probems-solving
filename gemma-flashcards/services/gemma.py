# services/gemma.py
import json
import os

from google import genai
from google.genai import types
from ollama import Client as OllamaClient
from pydantic import BaseModel, Field

GOOGLE_MODEL = "gemma-4-26b-a4b-it"
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "gemma3:4b")


# --- Pydantic schemas (API response shape from Gemma) ---

class FlashcardSchema(BaseModel):
    front: str = Field(description="A short word or phrase in the target language.")
    back: str = Field(description="The meaning plus a tiny learning note.")
    example: str = Field(description="A short example sentence.")
    topic: str = Field(default="", description="Topic tag, e.g. sports, food.")
    difficulty: str = Field(default="beginner", description="beginner, intermediate, advanced.")
    memory_tip: str = Field(default="", description="Short mnemonic or learning tip.")


class DeckSchema(BaseModel):
    cards: list[FlashcardSchema] = Field(description="The full set of flashcards.")


# --- SSE helpers ---

def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def clean_count(value):
    try:
        return min(max(int(value), 1), 20)
    except (TypeError, ValueError):
        return 6


# --- Prompts ---

def build_topic_prompt(language, theme, count, exclude_words=None, native_language="English"):
    exclude = ""
    if exclude_words:
        exclude = f"\nDo NOT include these already-known words: {', '.join(exclude_words)}"
    return f"""
Create a deck of exactly {count} flashcards for a beginner learning {language}.
Explain meanings in {native_language}.

Theme: {theme}
{exclude}

Each flashcard has:
- front: a short word or phrase in {language}
- back: the meaning plus a tiny, friendly learning note
- example: a short example sentence that fits the theme
- topic: a topic tag
- difficulty: beginner, intermediate, or advanced
- memory_tip: a short mnemonic (optional)

Rules:
- Do not repeat cards.
- Order the deck from easier to harder.
"""


# --- Streaming JSON parser (unchanged from original app.py) ---

def stream_cards(text_pieces):
    """Yield each flashcard the moment it is complete in the JSON stream."""
    buffer = ""
    scanned = 0
    depth = 0
    in_string = False
    escaped = False
    start = None

    for piece in text_pieces:
        buffer += piece
        while scanned < len(buffer):
            char = buffer[scanned]

            if in_string:
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
                if depth == 2:
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


# --- Provider calls ---

def google_cards(client, prompt):
    stream = client.models.generate_content_stream(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            response_mime_type="application/json",
            response_schema=DeckSchema,
        ),
    )
    return (chunk.text for chunk in stream if chunk.text)


def local_cards(client, prompt):
    stream = client.chat(
        model=LOCAL_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You create short, friendly language-learning flashcards.",
            },
            {"role": "user", "content": prompt},
        ],
        format=DeckSchema.model_json_schema(),
        options={"temperature": 0.7},
        stream=True,
    )
    return (chunk.message.content for chunk in stream if chunk.message.content)


def card_stream(language, theme, count, provider="google", exclude_words=None, native_language="English"):
    """Return an iterator of raw card dicts from the chosen provider."""
    prompt = build_topic_prompt(language, theme, count, exclude_words, native_language)

    if provider == "local":
        client = OllamaClient()
        pieces = local_cards(client, prompt)
    else:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY in your .env file.")
        client = genai.Client(api_key=api_key)
        pieces = google_cards(client, prompt)

    yield from stream_cards(pieces)