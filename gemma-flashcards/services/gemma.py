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
from services.retrieval import retrieve_for_followup, sample_document_chunks, search_chunks_text

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

Keep every field SHORT so the deck streams quickly:
- front: 1–3 words in {language}
- back: meaning in {native_language} (max ~12 words)
- example: one short sentence (max ~10 words)
- topic: one word
- difficulty: beginner, intermediate, or advanced
- memory_tip: leave empty or one short phrase

Rules:
- front must be a real word or short phrase in {language}, never punctuation or symbols alone.
- Do not repeat cards.
- Prefer common, useful words. Do not pad with long explanations.
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
Each word must be a real vocabulary item, not punctuation, URLs, or garbled symbols.
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


class DocumentFollowUps(BaseModel):
    opening: str = Field(description="Short friendly greeting that references the document.")
    questions: list[str] = Field(description="3–5 follow-up study questions about the document.")


class DocumentAssistantTurn(BaseModel):
    reply: str = Field(description="Answer grounded in the document excerpts.")
    follow_up: str = Field(description="One short follow-up question to keep studying.")


def generate_document_followups(client, chunk_texts, language, native_language, filename=""):
    """Use sampled document chunks to propose follow-up study questions."""
    context = "\n\n---\n\n".join(chunk_texts) if chunk_texts else "(no indexed excerpts)"
    prompt = f"""
You are a language-learning study coach for a document titled "{filename or 'uploaded file'}".
The learner is studying {language}. Write the opening and questions in {native_language}.

Using ONLY the excerpts below, greet the learner briefly and propose 3–5 follow-up questions
that help them understand vocabulary, key ideas, and useful phrases from this document.
Questions should be concrete and answerable from the excerpts.

Excerpts:
{context}
"""
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.5,
            response_mime_type="application/json",
            response_schema=DocumentFollowUps,
        ),
    )
    return parse_model_json(response.text, DocumentFollowUps)


def document_assistant_reply(
    client,
    doc,
    user_message,
    messages,
    language,
    native_language,
):
    """Answer with PyTorch RAG context, then ask one follow-up question."""
    chunks = retrieve_for_followup(doc.id, user_message, top_k=5)
    if not chunks:
        snippets = keyword_search_chunks(doc.raw_text, user_message)
        chunks = snippets or [doc.raw_text[:4000]]

    context = "\n\n---\n\n".join(chunks)
    history = "\n".join(
        f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
        for m in (messages or [])[-6:]
    )
    prompt = f"""
You are a study assistant for an uploaded {language} learning document.
Answer in {native_language} when explaining; keep short target-language quotes when useful.

Use ONLY the excerpts below. If the answer is not supported, say so.
After answering, ask exactly one short follow-up question that digs deeper into the document.

Recent chat:
{history or "(none)"}

Excerpts:
{context}

Learner message: {user_message}
"""
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.4,
            response_mime_type="application/json",
            response_schema=DocumentAssistantTurn,
        ),
    )
    turn = parse_model_json(response.text, DocumentAssistantTurn)
    return turn, chunks


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

class PlacementQuestion(BaseModel):
    question: str
    question_type: str  # vocab_mc, fill_blank, reading
    options: list[str] = []
    correct: str
    skill: str


class PlacementQuestionSet(BaseModel):
    questions: list[PlacementQuestion]


class PlacementEvaluation(BaseModel):
    estimated_level: str
    weak_areas: list[str]
    strengths: list[str]
    summary: str


def build_placement_questions_prompt(profile, count=10):
    language = profile.target_language or "French"
    native = profile.native_language or "English"
    return f"""
Create a placement test of exactly {count} mixed questions for a learner of {language}.
Write question text in {native}. Target-language content (words, blanks, passages) stays in {language}.

Mix question_type across: vocab_mc, fill_blank, reading.
Each question needs:
- question: the prompt text
- question_type: one of vocab_mc, fill_blank, reading
- options: 4 choices for vocab_mc / reading; empty list for fill_blank
- correct: the exact correct answer string (must match one option for MC)
- skill: short skill tag like vocabulary, grammar, reading, listening_proxy

Cover a range from beginner to advanced so we can estimate level.
Return JSON with questions array only.
"""


def generate_placement_questions(client, profile, count=10):
    prompt = build_placement_questions_prompt(profile, count)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.5,
            response_mime_type="application/json",
            response_schema=PlacementQuestionSet,
        ),
    )
    return parse_model_json(response.text, PlacementQuestionSet)


def build_placement_evaluation_prompt(profile, questions_with_answers):
    language = profile.target_language or "French"
    native = profile.native_language or "English"
    lines = []
    for i, item in enumerate(questions_with_answers, start=1):
        lines.append(
            f"{i}. skill={item.get('skill', '')} type={item.get('question_type', '')}\n"
            f"   Q: {item.get('question', '')}\n"
            f"   Correct: {item.get('correct', '')}\n"
            f"   User: {item.get('user_answer', '')}\n"
            f"   Match: {item.get('is_correct', False)}"
        )
    transcript = "\n".join(lines)
    return f"""
Evaluate this {language} placement test. Write summary and area labels in {native}.

Results:
{transcript}

Return JSON with:
- estimated_level: one of beginner, elementary, intermediate, advanced, expert
  (or CEFR A1–C1 mapped to those words)
- weak_areas: 2–5 short topic/skill labels
- strengths: 2–5 short topic/skill labels
- summary: 2–4 sentences for the learner
"""


def evaluate_placement(client, profile, questions_with_answers):
    prompt = build_placement_evaluation_prompt(profile, questions_with_answers)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=PlacementEvaluation,
        ),
    )
    return parse_model_json(response.text, PlacementEvaluation)


class WeeklyReport(BaseModel):
    strong_areas: list[str] = []
    weak_areas: list[str] = []
    suggested_topics: list[str] = []
    review_focus: list[str] = []
    narrative: str = ""


def build_weekly_report_prompt(profile, stats):
    native = profile.native_language or "English"
    language = profile.target_language or "French"
    return f"""
Write a weekly progress report for a {language} learner. Respond in {native}.

Stats:
- Words learned (total): {stats.get('total_words', 0)}
- Mastered: {stats.get('mastered', 0)}
- Practice / weak: {stats.get('practice', 0)}
- Quiz accuracy (7d): {stats.get('accuracy', 0)}%
- New words this week: {stats.get('words_this_week', 0)}
- Active study days this week: {stats.get('active_days', 0)}
- Current roadmap level: {stats.get('roadmap_level', 'n/a')}
- Words to study: {', '.join(stats.get('study_words', []) or []) or 'none'}
- Top topics: {', '.join(stats.get('topics', []) or []) or 'none'}

Return JSON with:
- strong_areas: short labels
- weak_areas: short labels
- suggested_topics: 3–5 topics to study next
- review_focus: words or skills to review
- narrative: 3–5 encouraging sentences summarizing the week
"""


def generate_weekly_report_text(client, profile, stats):
    prompt = build_weekly_report_prompt(profile, stats)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.5,
            response_mime_type="application/json",
            response_schema=WeeklyReport,
        ),
    )
    return parse_model_json(response.text, WeeklyReport)


class RoadmapLevelPlan(BaseModel):
    level_index: int
    title: str
    description: str
    topics: list[str]
    target_word_count: int = 50


class RoadmapPlan(BaseModel):
    title: str
    levels: list[RoadmapLevelPlan]


def build_roadmap_prompt(profile, placement_result=None):
    weak = ""
    if placement_result is not None:
        areas = getattr(placement_result, "weak_areas", None) or []
        if areas:
            weak = f"\nFocus extra practice on these weak areas: {', '.join(areas)}."

    level = profile.level or "beginner"
    goal = profile.goal or "general language learning"
    return f"""
Create a personalized 4-level learning roadmap for a student studying {profile.target_language}.
Explain titles and descriptions in {profile.native_language}.

Learner level: {level}
Learning goal: {goal}
{weak}

Return JSON with:
- title: short roadmap title
- levels: exactly 4 levels, each with:
  - level_index: 1 through 4
  - title: short level name
  - description: one sentence about what they will learn
  - topics: 3–5 topic tags (lowercase English keywords like food, travel, work)
  - target_word_count: integer around 40–60

Rules:
- Level 1 is foundational; level 4 is the most advanced for this learner.
- Topics must be concrete vocabulary themes the app can match later.
- Align the path with the learner's goal and current level.
"""


def generate_roadmap_plan(client, profile, placement_result=None):
    prompt = build_roadmap_prompt(profile, placement_result)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.5,
            response_mime_type="application/json",
            response_schema=RoadmapPlan,
        ),
    )
    return parse_model_json(response.text, RoadmapPlan)


class ConversationSummary(BaseModel):
    words_used_correctly: list[str] = []
    words_missed: list[str] = []
    corrections: list[str] = []
    summary: str = ""


def build_conversation_system_prompt(
    language, topic, difficulty, target_words, related_words, native_language
):
    targets = ", ".join(target_words) if target_words else "(none — free practice)"
    related = ""
    if related_words:
        related = f"\nRelated words the learner has studied: {', '.join(related_words)}."

    return f"""
You are a friendly {language} conversation partner helping a language learner practice.
Speak mostly in {language}. Keep replies short (1–3 sentences).
Explain corrections briefly in {native_language} when needed.

Topic: {topic}
Difficulty: {difficulty}
Target vocabulary the learner should try to use: {targets}
{related}

Rules:
- Stay on the topic. Ask follow-up questions so the learner keeps talking.
- If they misuse a target word, correct gently, then continue the conversation.
- Do not dump long grammar lectures. Prefer natural dialogue.
- Start with one short opening line that invites them into the topic
  and naturally suggests using one of the target words.
"""


def build_conversation_summary_prompt(messages, target_words, native_language):
    transcript = "\n".join(
        f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
        for m in (messages or [])
    )
    targets = ", ".join(target_words) if target_words else "(none)"

    return f"""
You are evaluating a language-practice conversation.
Write the summary and notes in {native_language}.

Target vocabulary: {targets}

Transcript:
{transcript}

Return JSON with:
- words_used_correctly: target words the learner used correctly
- words_missed: target words they never used or used wrongly
- corrections: short list of important mistakes and the better form
- summary: 2–4 sentences on how the practice went and what to review next
"""


def _conversation_contents(messages):
    """Map stored chat turns to GenAI Content objects."""
    contents = []
    for message in messages or []:
        role = message.get("role", "user")
        text = message.get("content", "")
        if not text:
            continue
        # GenAI uses "model" for assistant turns.
        api_role = "model" if role == "assistant" else "user"
        contents.append(
            types.Content(role=api_role, parts=[types.Part.from_text(text=text)])
        )
    return contents


def _conversation_generate_config(system_prompt):
    return types.GenerateContentConfig(
        temperature=0.7,
        max_output_tokens=180,
        system_instruction=system_prompt,
    )


def _conversation_request_contents(messages):
    contents = _conversation_contents(messages)
    if contents:
        return contents
    return [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text="Start the conversation.")],
        )
    ]


def conversation_reply(client, system_prompt, messages):
    """Generate the next assistant turn for an ongoing conversation."""
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=_conversation_request_contents(messages),
        config=_conversation_generate_config(system_prompt),
    )
    return (response.text or "").strip()


def conversation_reply_stream(client, system_prompt, messages):
    """Yield text chunks as Gemma generates the next turn."""
    stream = client.models.generate_content_stream(
        model=GOOGLE_MODEL,
        contents=_conversation_request_contents(messages),
        config=_conversation_generate_config(system_prompt),
    )
    for chunk in stream:
        text = getattr(chunk, "text", None)
        if text:
            yield text


def summarize_conversation(client, messages, target_words, native_language):
    prompt = build_conversation_summary_prompt(messages, target_words, native_language)
    response = client.models.generate_content(
        model=GOOGLE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            response_mime_type="application/json",
            response_schema=ConversationSummary,
        ),
    )
    return parse_model_json(response.text, ConversationSummary)
