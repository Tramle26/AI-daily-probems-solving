# Phase 2b: PyTorch Embeddings (Semantic Search + Related Words)

Upgrades [Phase 2a](phase-2a-personalization.md) with **sentence-transformers** (PyTorch) for true semantic document search and vocabulary similarity. **Prerequisite:** Phase 0 schema (`DocumentChunk`, `embedding_blob` columns) and Phase 1 upload flow.

## Goals

| In scope (Phase 2b) | Out of scope |
|---------------------|--------------|
| Chunk + embed uploaded documents | Custom PyTorch model training |
| Semantic study search (RAG) | Placement test |
| Ask Gemma using retrieved chunks (not truncation) | Conversation (Phase 3) |
| Embed vocabulary on save | Forget-predictor ML |
| Similar words from user's history | |
| Embedding-based topic continuity | |

## Why PyTorch here

| Feature | Without PyTorch (Phase 2a) | With PyTorch (Phase 2b) |
|---------|---------------------------|-------------------------|
| "Important words in chapter 2?" | First 8000 chars only | Finds semantically similar chunks anywhere in doc |
| Similar words | Gemma guess or topic tags | Cosine neighbors from saved vocab vectors |
| sports → soccer continuity | `topic ILIKE '%sport%'` | Embedding neighbors across related topics |

## Exit criteria

- [ ] Upload document → chunks indexed with embeddings
- [ ] Semantic search returns answer grounded in relevant passages
- [ ] Dictionary shows similar words from user's saved vocabulary
- [ ] New flashcard generation uses embedding neighbors for continuity
- [ ] First model load documented; indexing shows progress in UI

---

## Prerequisites

- Phase 1 + 2a complete
- `DocumentChunk` table exists (Phase 0)
- `VocabularyItem.embedding_blob` column exists (nullable OK)
- ~500MB disk for `sentence-transformers` + model weights
- CPU sufficient (`all-MiniLM-L6-v2`); GPU optional

---

## Step 2b.1 — Add dependencies

```toml
"sentence-transformers>=3.0.0",
"numpy>=2.0.0",
```

```bash
uv sync
```

First run downloads `all-MiniLM-L6-v2` (~90MB model + PyTorch deps).

---

## Step 2b.2 — Embedding service

Create `services/embeddings.py`:

```python
import numpy as np
from sentence_transformers import SentenceTransformer

_model = None
MODEL_NAME = "all-MiniLM-L6-v2"


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_text(text: str) -> list[float]:
    if not text or not text.strip():
        return []
    vector = get_model().encode(text, normalize_embeddings=True)
    return vector.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    clean = [t for t in texts if t and t.strip()]
    if not clean:
        return []
    vectors = get_model().encode(clean, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    va, vb = np.array(a), np.array(b)
    return float(np.dot(va, vb))
```

Lazy-load pattern: model loads on first embed call, not at app startup (keeps Flask fast).

---

## Step 2b.3 — Retrieval service

Create `services/retrieval.py`:

```python
from extensions import db
from models import DocumentChunk
from services.embeddings import cosine_similarity, embed_text, embed_texts


def chunk_document(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end - overlap
    return chunks


def index_document(document_id: int, text: str, reindex: bool = False):
    """Chunk, embed, and persist DocumentChunk rows."""
    if reindex:
        DocumentChunk.query.filter_by(document_id=document_id).delete()
        db.session.commit()

    existing = DocumentChunk.query.filter_by(document_id=document_id).count()
    if existing and not reindex:
        return existing

    chunks = chunk_document(text)
    vectors = embed_texts(chunks)

    for i, (chunk_text, vector) in enumerate(zip(chunks, vectors)):
        db.session.add(DocumentChunk(
            document_id=document_id,
            chunk_index=i,
            text=chunk_text,
            embedding_blob=vector,
        ))
    db.session.commit()
    return len(chunks)


def search_chunks(document_id: int, question: str, top_k: int = 5) -> list[dict]:
    query_vec = embed_text(question)
    if not query_vec:
        return []

    chunks = DocumentChunk.query.filter_by(document_id=document_id).all()
    scored = []
    for chunk in chunks:
        if chunk.embedding_blob:
            score = cosine_similarity(query_vec, chunk.embedding_blob)
            scored.append({"score": score, "text": chunk.text, "chunk_index": chunk.chunk_index})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def search_chunks_text(document_id: int, question: str, top_k: int = 5) -> list[str]:
    return [hit["text"] for hit in search_chunks(document_id, question, top_k)]
```

---

## Step 2b.4 — Vocabulary embedding helpers

Add to `services/vocabulary.py`:

```python
from services.embeddings import cosine_similarity, embed_text


def embed_vocabulary_item(item):
    text = f"{item.word}: {item.meaning or ''}. {item.example or ''}"
    item.embedding_blob = embed_text(text)


def embed_vocabulary_item_if_missing(item):
    if not item.embedding_blob:
        embed_vocabulary_item(item)


def find_similar_vocab(word, language, top_k=5, exclude_word=None):
    query_vec = embed_text(word)
    if not query_vec:
        return []

    items = VocabularyItem.query.filter_by(language=language).filter(
        VocabularyItem.embedding_blob.isnot(None)
    ).all()

    scored = []
    for item in items:
        if exclude_word and item.word.lower() == exclude_word.lower():
            continue
        score = cosine_similarity(query_vec, item.embedding_blob)
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def build_embedding_continuity_context(theme, language, top_k=10):
    """Find prior vocab semantically related to the new theme."""
    neighbors = find_similar_vocab(theme, language, top_k=top_k, exclude_word=theme)
    if not neighbors:
        return ""
    words = ", ".join(v.word for v in neighbors)
    return f"\nRelated vocabulary the learner already knows: {words}. Connect new words to these."
```

Update `upsert_vocabulary` / `save_deck` to call `embed_vocabulary_item(vocab)` after save (wrap in try/except — don't fail deck save if embed slow).

Batch backfill script for existing vocab:

```python
# One-time in flask shell
from models import VocabularyItem
from services.vocabulary import embed_vocabulary_item_if_missing
for item in VocabularyItem.query.all():
    embed_vocabulary_item_if_missing(item)
db.session.commit()
```

---

## Step 2b.5 — RAG prompts in Gemma service

Add to `services/gemma.py`:

```python
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
```

---

## Step 2b.6 — API routes

```python
# routes/api.py
from services.retrieval import index_document, search_chunks, search_chunks_text
from services.gemma import build_rag_prompt, build_semantic_vocab_prompt

@bp.post("/documents/<int:doc_id>/index")
def document_index(doc_id):
    from models import UploadedDocument
    doc = UploadedDocument.query.get_or_404(doc_id)
    reindex = request.json.get("reindex", False) if request.is_json else False
    count = index_document(doc.id, doc.raw_text, reindex=reindex)
    return jsonify({"chunks_indexed": count})


@bp.post("/semantic-search")
def semantic_search():
    data = request.get_json()
    doc_id = data["document_id"]
    question = data["question"].strip()
    profile = get_profile()

    hits = search_chunks(doc_id, question, top_k=5)
    if not hits:
        return jsonify({"error": "Document not indexed. Call /api/documents/<id>/index first."}), 400

    chunk_texts = [h["text"] for h in hits]
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    if data.get("mode") == "vocabulary":
        prompt = build_semantic_vocab_prompt(
            question, chunk_texts, data.get("language", profile.target_language),
            profile.native_language, data.get("max_words", 15),
        )
        response = client.models.generate_content(
            model=GOOGLE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VocabularyList,
            ),
        )
        result = VocabularyList.model_validate_json(response.text)
        return jsonify({
            "items": [i.model_dump() for i in result.items],
            "chunks_used": hits,
        })

    prompt = build_rag_prompt(question, chunk_texts, profile.native_language)
    response = client.models.generate_content(model=GOOGLE_MODEL, contents=prompt)
    return jsonify({"answer": response.text, "chunks_used": hits})


@bp.get("/vocabulary/<int:vocab_id>/similar")
def vocabulary_similar(vocab_id):
    from models import VocabularyItem
    item = VocabularyItem.query.get_or_404(vocab_id)
    similar = find_similar_vocab(item.word, item.language, top_k=8, exclude_word=item.word)
    return jsonify({
        "word": item.word,
        "similar": [{"word": v.word, "meaning": v.meaning, "topic": v.topic} for v in similar],
    })
```

---

## Step 2b.7 — Wire indexing on upload

Update document save flow (Phase 1 upload):

```python
# After save_document() in upload POST handler:
from services.retrieval import index_document

doc = save_document(filename, text, language)
try:
    index_document(doc.id, doc.raw_text)
except Exception as exc:
    # Log but don't fail upload — user can re-index manually
    app.logger.warning("Embedding index failed: %s", exc)
```

Show indexing status on upload preview: "Indexed N chunks" or "Index pending".

---

## Step 2b.8 — Upgrade Ask Gemma to RAG

Replace Phase 2a truncated ask with RAG when chunks exist:

```python
def ask_document_smart(client, doc, question, native_language):
    from models import DocumentChunk
    chunk_count = DocumentChunk.query.filter_by(document_id=doc.id).count()

    if chunk_count > 0:
        from services.retrieval import search_chunks_text
        from services.gemma import build_rag_prompt
        chunks = search_chunks_text(doc.id, question, top_k=5)
        prompt = build_rag_prompt(question, chunks, native_language)
    else:
        prompt = build_ask_prompt(doc.raw_text, question, native_language)

    response = client.models.generate_content(model=GOOGLE_MODEL, contents=prompt)
    return response.text
```

---

## Step 2b.9 — Upgrade dictionary similar words

In `/api/dictionary/search`, merge embedding neighbors with Gemma results:

```python
embedding_neighbors = find_similar_vocab(word, language, top_k=5)
gemma_result = dictionary_lookup(client, word, language, profile.native_language, related_words)

# Merge similar_words: embedding first, then Gemma, dedupe
emb_words = [v.word for v in embedding_neighbors]
combined = list(dict.fromkeys(emb_words + gemma_result.similar_words))
gemma_result.similar_words = combined[:8]
```

---

## Step 2b.10 — Upgrade flashcard continuity

In `/stream`, prefer embedding continuity over tag-only:

```python
from services.vocabulary import build_embedding_continuity_context, build_continuity_context

continuity = build_embedding_continuity_context(theme, language)
if not continuity:
    continuity = build_continuity_context(theme, language)  # Phase 2a fallback
```

---

## Step 2b.11 — UI: Semantic search page

Add `templates/semantic_search.html` or section on Ask page:

- Document dropdown
- Question input: "What are the important words in chapter 2?"
- Mode toggle: **Answer** | **Extract vocabulary**
- Results: answer text + expandable "Sources used" (chunk snippets with scores)
- Button: "Save as flashcard deck"

Example fetch:

```javascript
const res = await fetch("/api/semantic-search", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    document_id: docId,
    question: question,
    mode: "vocabulary",
    max_words: 12,
  }),
})
```

---

## Performance notes

| Issue | Mitigation |
|-------|------------|
| First embed slow (~5–15s) | Show "Loading language model…" once; lazy `get_model()` |
| Large PDF many chunks | Batch `embed_texts(chunks)` not one-by-one |
| Re-upload same doc | `reindex=True` deletes old chunks first |
| Memory | MiniLM is small; avoid loading multiple models |

---

## Verification checklist

| Test | Expected |
|------|----------|
| Upload 20-page PDF | `document_chunk` rows with non-null `embedding_blob` |
| Ask about content on page 15 | RAG retrieves relevant chunk (not truncated away) |
| Semantic vocab mode | Returns word list from relevant sections |
| `/api/vocabulary/<id>/similar` | Returns semantically related saved words |
| Dictionary search | `similar_words` includes embedding neighbors |
| Soccer deck after sports vocab | Prompt includes embedding-related old words |

---

## Troubleshooting

**"Document not indexed":** Call `POST /api/documents/<id>/index` or re-upload.

**Empty search results:** Chunks may lack embeddings — check `embedding_blob IS NOT NULL`.

**Import error for sentence_transformers:** Run `uv sync`; ensure Python 3.10+ compatible wheels.

**Slow on every request:** Ensure `get_model()` uses global singleton, not reinstantiating.

---

## What comes next

→ [Phase 3: Advanced](phase-3-advanced.md) — placement test, roadmap, conversation, charts, SM-2 review

---

## File checklist

- [ ] `sentence-transformers`, `numpy` in pyproject.toml
- [ ] `services/embeddings.py`
- [ ] `services/retrieval.py`
- [ ] Vocabulary embed helpers + save_deck hook
- [ ] RAG prompts in `services/gemma.py`
- [ ] API: `/api/documents/<id>/index`, `/api/semantic-search`, `/api/vocabulary/<id>/similar`
- [ ] Upload auto-index + Ask Gemma RAG upgrade
- [ ] Dictionary + flashcard continuity upgrades
- [ ] Semantic search UI
