# Phase 2b: PyTorch Embeddings (Semantic Search + Related Words)

Upgrades the **completed Phase 2a** baseline with **sentence-transformers** (PyTorch) for true semantic document search and vocabulary similarity.

## Current baseline (already shipped)

Phase 2a is done. Do **not** re-implement these — build on them:

| Feature | Current implementation | Phase 2b upgrade |
|---------|------------------------|------------------|
| Ask Gemma | `POST /api/ask` — keyword snippets via `keyword_search_chunks`, else first 8000 chars | RAG over embedded `DocumentChunk` rows |
| Topic continuity | `build_continuity_context()` — `topic ILIKE` in `services/vocabulary.py` | `build_embedding_continuity_context()` with fallback |
| Dictionary similar words | Gemma guess + 10 recent saved words | Merge embedding neighbors from user's history |
| Document vocab extract | `extract_document_vocabulary()` — first 8000 chars | Optional: semantic chunk selection first |
| Mastery statuses | `new`, `learning`, `practice`, `mastered` (`weak` migrated → `practice`) | No change |
| Vocabulary browser | `/library` with search by word/topic + status filters | Similar-words panel per item |
| UI theming | `services/background.py` — topic categories + live canvas | Optional: richer topic labels from embeddings |
| Schema hooks | `DocumentChunk.embedding_blob`, `VocabularyItem.embedding_blob` (nullable) | Populate on upload / save |

**Not started:** `sentence-transformers`, `services/embeddings.py`, `services/retrieval.py`, chunk indexing on upload.

## Goals

| In scope (Phase 2b) | Out of scope (Phase 3) |
|---------------------|------------------------|
| Chunk + embed uploaded documents | Placement test |
| Semantic study search (RAG) | Conversation practice |
| Upgrade Ask Gemma to retrieved chunks | Gemma-generated roadmap |
| Embed vocabulary on save | SM-2 review |
| Similar words from user's history | Weekly AI report |
| Embedding-based flashcard continuity | |
| Index status on upload preview | |

## Why PyTorch here

| Feature | Today (Phase 2a) | After Phase 2b |
|---------|------------------|----------------|
| "Important words in chapter 2?" | Keyword hit or first 8000 chars | Finds semantically similar chunks anywhere in doc |
| Similar words | Gemma guess or topic tags | Cosine neighbors from saved vocab vectors |
| sports → soccer continuity | `topic ILIKE '%sport%'` | Embedding neighbors across related topics |
| Long PDF page 15 content | Often missed | Retrieved by semantic similarity |

## Exit criteria

- [ ] Upload document → `document_chunk` rows with non-null `embedding_blob`
- [ ] Ask Gemma answers from retrieved chunks when indexed (fallback to current keyword/truncation path when not)
- [ ] `/api/semantic-search` returns grounded answers + source snippets
- [ ] Dictionary shows similar words from user's saved vocabulary (embedding neighbors)
- [ ] Flashcard `/stream` prefers embedding continuity, falls back to tag continuity
- [ ] Upload preview shows "Indexed N chunks" or re-index button
- [ ] First model load documented; slow path shows user feedback

---

## Prerequisites

- Phase 1 + 2a verified (review, Excel, Ask, library, dashboard charts)
- `DocumentChunk` and `VocabularyItem.embedding_blob` exist (Phase 0)
- `GEMINI_API_KEY` set for RAG answer synthesis
- ~500MB disk for `sentence-transformers` + `all-MiniLM-L6-v2` weights
- CPU sufficient; GPU optional

---

## Step 2b.1 — Add dependencies

Add to `pyproject.toml`:

```toml
"sentence-transformers>=3.0.0",
"numpy>=2.0.0",
```

```bash
uv sync
```

First embed call downloads `all-MiniLM-L6-v2` (~90MB). Keep lazy loading — do **not** load at Flask startup.

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


def index_document(document_id: int, text: str, reindex: bool = False) -> int:
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
    neighbors = find_similar_vocab(theme, language, top_k=top_k, exclude_word=theme)
    if not neighbors:
        return ""
    words = ", ".join(v.word for v in neighbors)
    return f"\nRelated vocabulary the learner already knows: {words}. Connect new words to these."
```

Hook into `save_deck()` / `upsert_vocabulary()` — call `embed_vocabulary_item(vocab)` after save inside try/except so a slow embed never blocks deck save.

**Backfill existing vocab** (one-time Flask shell):

```python
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

Add to `routes/api.py`:

```python
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
```

---

## Step 2b.7 — Wire indexing on upload

Update `save_document()` flow in `routes/main.py` upload POST:

```python
doc = save_document(filename, text, language)
try:
    from services.retrieval import index_document
    index_document(doc.id, doc.raw_text)
except Exception as exc:
    current_app.logger.warning("Embedding index failed: %s", exc)
```

Update `templates/upload_preview.html`:
- Show chunk count from `DocumentChunk.query.filter_by(document_id=doc.id).count()`
- Button: "Re-index document" → `POST /api/documents/<id>/index`

Also delete chunks when document is removed — extend `delete_document()` in `services/documents.py`.

---

## Step 2b.8 — Upgrade Ask Gemma (replace current hybrid)

**Current code** (`routes/api.py` → `api_ask`):

```python
snippets = keyword_search_chunks(doc.raw_text, data["question"])
context = "\n\n".join(snippets) if snippets else doc.raw_text[:8000]
answer = ask_document(client, context, data["question"], profile.native_language)
```

**Replace with** `ask_document_smart()`:

```python
def ask_document_smart(client, doc, question, native_language):
    chunk_count = DocumentChunk.query.filter_by(document_id=doc.id).count()

    if chunk_count > 0:
        chunks = search_chunks_text(doc.id, question, top_k=5)
        prompt = build_rag_prompt(question, chunks, native_language)
    else:
        snippets = keyword_search_chunks(doc.raw_text, question)
        context = "\n\n".join(snippets) if snippets else doc.raw_text[:8000]
        prompt = build_ask_prompt(context, question, native_language)

    response = client.models.generate_content(model=GOOGLE_MODEL, contents=prompt, ...)
    return response.text
```

Keep keyword fallback when document is not indexed — do not break existing Ask flow.

Optional Ask UI upgrade (`templates/ask.html`): expandable "Sources used" section when RAG chunks are returned.

---

## Step 2b.9 — Upgrade dictionary similar words

In `POST /api/dictionary/search`, replace the current "10 most recent words" related list:

```python
# Today:
related = [v.word for v in VocabularyItem.query.filter_by(language=target_language).limit(10).all()]

# Phase 2b:
embedding_neighbors = find_similar_vocab(word, target_language, top_k=5)
related = [v.word for v in embedding_neighbors]
# Fall back to recent words if no embeddings yet
```

After Gemma lookup, merge `similar_words`:

```python
emb_words = [v.word for v in embedding_neighbors]
combined = list(dict.fromkeys(emb_words + result.similar_words))
result.similar_words = combined[:8]
```

---

## Step 2b.10 — Upgrade flashcard continuity

In `routes/flashcards.py` → `stream()`:

```python
from services.vocabulary import build_embedding_continuity_context, build_continuity_context

continuity = build_embedding_continuity_context(theme, language)
if not continuity:
    continuity = build_continuity_context(theme, language)
```

Also embed each vocab item after stream save (same try/except pattern as `save_deck`).

---

## Step 2b.11 — UI: Semantic search on Ask page

Extend `templates/ask.html` rather than a separate page (keeps nav simple):

- Mode toggle: **Ask** | **Extract vocabulary**
- "Extract vocabulary" calls `POST /api/semantic-search` with `mode: "vocabulary"`
- Show answer + expandable source chunks with similarity scores
- Button: "Save as flashcard deck" (reuse existing `POST /api/decks`)

**Library enhancement (optional):** On `/library`, add "Similar words" fetch per row via `/api/vocabulary/<id>/similar`.

---

## Performance notes

| Issue | Mitigation |
|-------|------------|
| First embed slow (~5–15s) | Show "Loading language model…" once; lazy `get_model()` |
| Large PDF many chunks | Batch `embed_texts(chunks)` not one-by-one |
| Re-upload same doc | `reindex=True` deletes old chunks first |
| Memory | MiniLM only; single global singleton |
| Deck save blocked | Never fail save on embed error — log and backfill later |

---

## Verification checklist

| Test | Expected |
|------|----------|
| Upload 20-page PDF | `document_chunk` rows with non-null `embedding_blob` |
| Ask about content deep in doc | RAG retrieves relevant chunk (not truncated away) |
| Ask on unindexed doc | Falls back to keyword / 8000-char path (no error) |
| Semantic vocab mode | Word list from relevant sections |
| `/api/vocabulary/<id>/similar` | Semantically related saved words |
| Dictionary search | `similar_words` includes embedding neighbors |
| Soccer deck after sports vocab | Prompt includes embedding-related old words |
| Upload preview | Shows chunk count |

---

## Troubleshooting

**"Document not indexed":** Call `POST /api/documents/<id>/index` or re-upload.

**Empty search results:** Check `embedding_blob IS NOT NULL` on chunks.

**Import error for sentence_transformers:** Run `uv sync`; Python 3.14 wheels may lag — pin to 3.12/3.13 if needed.

**Slow on every request:** Ensure `get_model()` uses global singleton.

---

## What comes next

→ [Phase 3: Advanced](phase-3-advanced.md) — placement, full roadmap, conversation, weekly report, SM-2

---

## File checklist

- [ ] `sentence-transformers`, `numpy` in `pyproject.toml`
- [ ] `services/embeddings.py`
- [ ] `services/retrieval.py`
- [ ] Vocabulary embed helpers + `save_deck` / stream hooks
- [ ] RAG prompts in `services/gemma.py`
- [ ] API: `/api/documents/<id>/index`, `/api/semantic-search`, `/api/vocabulary/<id>/similar`
- [ ] Upload auto-index + chunk cleanup on delete
- [ ] Ask Gemma RAG upgrade (keep keyword fallback)
- [ ] Dictionary + flashcard continuity upgrades
- [ ] Ask page semantic search UI + upload preview index status
