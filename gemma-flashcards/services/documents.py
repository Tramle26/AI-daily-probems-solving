from pypdf import PdfReader

from extensions import db
from models import UploadedDocument


def extract_text_from_file(file_storage):
    filename = file_storage.filename or "paste.txt"
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(file_storage)
        pages = [page.extract_text() or "" for page in reader.pages]
        return filename, "\n".join(pages).strip()
    raw = file_storage.read()
    return filename, raw.decode("utf-8", errors="replace").strip()


def save_document(filename, text, language):
    doc = UploadedDocument(
        filename=filename,
        raw_text=text,
        language=language,
        word_count=len(text.split()),
    )
    db.session.add(doc)
    db.session.commit()
    return doc
