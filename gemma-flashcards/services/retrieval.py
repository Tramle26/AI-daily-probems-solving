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