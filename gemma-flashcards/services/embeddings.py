import numpy as np
from sentence_transformers import SentenceTransformer

_model = None
MODEL_NAME = "all-MiniLM-L6-v2"


def is_model_loaded() -> bool:
    return _model is not None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def warmup_model() -> bool:
    """Load the embedding model if needed. Safe to call from a background thread."""
    try:
        get_model()
        return True
    except Exception:
        return False


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
