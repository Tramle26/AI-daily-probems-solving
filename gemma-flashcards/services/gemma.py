# services/gemma.py
import json
import os
import re

from google import genai
from google.genai import types
from ollama import Client as OllamaClient
from pydantic import BaseModel, Field

from models import DocumentChunk
from services.documents import keyword_search_chunks
from services.retrieval import search_chunks_text

GOOGLE_MODEL = "gemma-4-26b-a4b-it"
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "gemma3:4b")


# Pydantic schemas (API response shape from Gemma)

class FlashcardSchema(BaseModel):
    front: str = Field(description="A short word or phrase in the target language.")
    back: str = Field(description="The meaning plus a tiny learning note.")
    example: str = Field(description="A short example sentence.")
    topic: str = Field(default="", description="Topic tag, e.g. sports, food.")
    difficulty: str = Field(default="beginner", description="beginner, intermediate, advanced.")
    memory_tip: str = Field(default="", description="Short mnemonic or learning tip.")


class DeckSchema(BaseModel):
    cards: list[FlashcardSchema] = Field(description="The full set of flashcards.")


# SSE helpers

def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def clean_count(value):
    try:
        return min(max(int(value), 1), 20)
    except (TypeError, ValueError):
        return 6


def parse_model_json(text, model_class):
    """Parse structured model output, tolerating markdown code fences."""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        cleaned = re.sub(r"```(?:json)?\s*$", "", cleaned).strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned).strip()

    try:
        return model_class.model_validate_json(cleaned)
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            return model_class.model_validate_json(cleaned[start : end + 1])
        raise


# Prompts

def build_topic_prompt(
    language,
    theme,
    count,
    exclude_words=None,
    native_language="English",
    continuity_context="",
):
    exclude = ""
    if exclude_words:
        exclude = f"\nDo NOT include these already-known words: {', '.join(exclude_words)}"
    return f"""
Create a deck of exactly {count} flashcards for a beginner learning {language}.
Explain meanings in {native_language}.

Theme: {theme}
{exclude}
{continuity_context}

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


# Streaming JSON parser (unchanged from original app.py)

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


# Provider calls

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


def card_stream(
    language,
    theme,
    count,
    provider="google",
    exclude_words=None,
    native_language="English",
    continuity_context="",
):
    """Return an iterator of raw card dicts from the chosen provider."""
    prompt = build_topic_prompt(
        language,
        theme,
        count,
        exclude_words,
        native_language,
        continuity_context,
    )

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

class VocabularyEntry(BaseModel):
    word: str
    meaning: str
    example: str
    topic: str = ""
    difficulty: str = "beginner"


class VocabularyList(BaseModel):
    items: list[VocabularyEntry]


class DictionaryResult(BaseModel):
    word: str
    meaning: str
    simple_explanation: str
    example: str
    translation: str
    topic: str = ""
    difficulty: str = "beginner"
    similar_words: list[str] = []
    common_mistakes: list[str] = []


def build_dictionary_prompt(
    word, lookup_language, target_language, native_language, related_words=None
):
    related = ""
    if related_words:
        related = f"\nThe learner has previously studied: {', '.join(related_words)}"

    if lookup_language == native_language:
        return f"""
The learner typed a word in {native_language} and wants to learn the {target_language} equivalent.
Word entered: "{word}"
Explain everything in {native_language}.{related}

Return JSON with:
- word: the {target_language} equivalent (what they need to learn)
- meaning: meaning in {native_language}
- simple_explanation: beginner-friendly explanation in {native_language}
- example: example sentence in {target_language}
- translation: translation of the example in {native_language}
- topic, difficulty, similar_words (other {target_language} words), common_mistakes
"""
    return f"""
Explain the {target_language} word "{word}" for a language learner.
Explain in {native_language}.{related}

Return: word, meaning, simple_explanation, example, translation, topic, difficulty, similar_words, common_mistakes.
"""


def dictionary_lookup(
    client, word, lookup_language, target_language, native_language, related_words=None
):
    prompt = build_dictionary_prompt(
        word, lookup_language, target_language, native_language, related_words
    )
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            response_mime_type="application/json",
            response_schema=DictionaryResult,
        ),
    )
    return parse_model_json(response.text, DictionaryResult)

def build_document_prompt(text, language, max_words, native_language="English"):
    excerpt = text[:8000]
    return f"""
    Extract the {max_words} most useful {language} vocabulary items from this passage.
Explain meanings in {native_language}.

Passage:
{excerpt}

Return JSON with items: word, meaning, example, topic, difficulty.
Focus on words a learner needs to understand this text.
"""

def extract_document_vocabulary(client, text, language, max_words, native_language="English"):
    prompt = build_document_prompt(text, language, max_words, native_language)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.5,
            response_mime_type="application/json",
            response_schema=VocabularyList,
        ),
    )
    return parse_model_json(response.text, VocabularyList)

class ExcelFillResult(BaseModel):
    meaning: str
    example: str
    topic: str = ""


def build_excel_fill_prompt(word, language, native_language):
    return f"""
The learner uploaded a vocabulary list. For the {language} word "{word}", provide:
meaning (in {native_language}), example sentence, and topic tag.
"""


def fill_missing_card_fields(client, word, language, native_language):
    prompt = build_excel_fill_prompt(word, language, native_language)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            response_mime_type="application/json",
            response_schema=ExcelFillResult,
        ),
    )
    return parse_model_json(response.text, ExcelFillResult)

def build_ask_prompt(document_text, question, native_language):
    return f"""
Answer this question using ONLY the document below.
Explain in {native_language} when helpful.
If the answer is not in the document, say so clearly.

Document:
{document_text[:8000]}

Question: {question}
"""


def ask_document(client, document_text, question, native_language):
    prompt = build_ask_prompt(document_text, question, native_language)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3),
    )
    return response.text


def ask_document_smart(client, doc, question, native_language):
    """RAG over indexed chunks when available; fall back to keyword/truncation otherwise."""
    chunk_count = DocumentChunk.query.filter_by(document_id=doc.id).count()

    if chunk_count > 0:
        chunks = search_chunks_text(doc.id, question, top_k=5)
        prompt = build_rag_prompt(question, chunks, native_language)
        sources = chunks
    else:
        snippets = keyword_search_chunks(doc.raw_text, question)
        context = "\n\n".join(snippets) if snippets else doc.raw_text[:8000]
        prompt = build_ask_prompt(context, question, native_language)
        sources = []

    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.3),
    )
    return response.text, sources

class AskVocabSuggestion(BaseModel):
    words: list[VocabularyEntry]


def extract_vocab_from_answer(client, answer, language, native_language):
    prompt = f"""
From this study answer, list key {language} vocabulary items with meanings in {native_language}.

Answer:
{answer}
"""
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AskVocabSuggestion,
        ),
    )
    return parse_model_json(response.text, AskVocabSuggestion)


def build_rag_prompt(question, chunk_texts, native_language):
    context = "\n\n---\n\n".join(chunk_texts)
    return f"""
Answer this question using ONLY the excerpts below from the user's document.
Explain in {native_language} when helpful.
If the answer is not supported by the excerpts, say so.

Excerpts:
{context}

Question: {question}
"""


def build_semantic_vocab_prompt(question, chunk_texts, language, native_language, max_words=15):
    context = "\n\n---\n\n".join(chunk_texts)
    return f"""
The user asked: {question}

Based ONLY on these excerpts from their {language} study material:
{context}

List the {max_words} most important {language} vocabulary items for this question.
Explain meanings in {native_language}.
Return JSON with items: word, meaning, example, topic, difficulty.
"""