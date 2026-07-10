#models/__init__.py
from datetime import datetime # import the datetime module
from extensions import db # import the db instance from extensions.py

class UserProfile(db.Model):
    __tablename__ = 'user_profile'
    id = db.Column(db.Integer, primary_key= True)
    target_language= db.Column(db.String(32), nullable = False, default = "French")
    native_language= db.Column(db.String(32), nullable = False, default = "English")
    level = db.Column(db.String(16))
    goal= db.Column(db.String(64))
    streak_days= db.Column(db.Integer, default = 0)
    last_active_date= db.Column(db.Date)
    profile_created_at= db.Column(db.DateTime, default = datetime.utcnow)

class UploadedDocument(db.Model):
    __tablename__ = 'uploaded_document'
    id= db.Column(db.Integer, primary_key = True)
    filename= db.Column(db.String(256))
    raw_text= db.Column(db.Text, nullable = False)
    language = db.Column(db.String(32))
    detected_topics = db.Column(db.JSON, default= list)
    word_count= db.Column(db.Integer, default =0)
    uploaded_at= db.Column(db.DateTime, default = datetime.utcnow)
    vocabulary_items= db.relationship("VocabularyItem", backref="document", lazy=True)
    chunks = db.relationship("DocumentChunk",backref="document", lazy= True, cascade="all,delete-orphan")

class DocumentChunk(db.Model):
    __tablename__ = "document_chunk"
    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("uploaded_document.id"), nullable=False)
    chunk_index = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    embedding_blob = db.Column(db.JSON)  # list[float]; NULL until Phase 2b indexes document
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FlashcardDeck(db.Model):
    __tablename__ = "flashcard_deck"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(256), nullable=False)
    language = db.Column(db.String(32), nullable=False)
    source_type = db.Column(db.String(32))   # topic, document, dictionary, excel
    source_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cards = db.relationship(
        "Flashcard", backref="deck", lazy=True, cascade="all, delete-orphan"
    )


class VocabularyItem(db.Model):
    __tablename__ = "vocabulary_item"

    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(128), nullable=False)
    language = db.Column(db.String(32), nullable=False)
    meaning = db.Column(db.Text)
    example = db.Column(db.Text)
    topic = db.Column(db.String(64))
    difficulty = db.Column(db.String(16))
    source_type = db.Column(db.String(32))
    source_id = db.Column(db.Integer)
    document_id = db.Column(db.Integer, db.ForeignKey("uploaded_document.id"))
    mastery_status = db.Column(db.String(16), default="new")
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_reviewed_at = db.Column(db.DateTime)
    next_review_at = db.Column(db.DateTime)
    ease_factor = db.Column(db.Float, default=2.5)
    interval_days = db.Column(db.Integer, default=1)
    review_count = db.Column(db.Integer, default=0)
    quiz_accuracy = db.Column(db.Float, default=0.0)
    user_notes = db.Column(db.Text)
    embedding_blob = db.Column(db.JSON)  # list[float]; NULL until Phase 2b embeds word+meaning

    __table_args__ = (
        db.UniqueConstraint("word", "language", name="uq_word_language"),
    )


MASTERY_STATUS_LABELS = {
    "new": "New",
    "learning": "Learning",
    "practice": "Practice",
    "mastered": "Mastered",
}


class Flashcard(db.Model):
    __tablename__ = "flashcard"

    id = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(db.Integer, db.ForeignKey("flashcard_deck.id"), nullable=False)
    vocabulary_item_id = db.Column(db.Integer, db.ForeignKey("vocabulary_item.id"))
    front = db.Column(db.String(256), nullable=False)
    back = db.Column(db.Text, nullable=False)
    example = db.Column(db.Text)
    topic = db.Column(db.String(64))
    difficulty = db.Column(db.String(16))
    memory_tip = db.Column(db.Text)


class DictionarySearch(db.Model):
    __tablename__ = "dictionary_search"

    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(128), nullable=False)
    language = db.Column(db.String(32), nullable=False)
    result_json = db.Column(db.JSON)
    document_id = db.Column(db.Integer, db.ForeignKey("uploaded_document.id"))
    added_to_deck = db.Column(db.Boolean, default=False)
    searched_at = db.Column(db.DateTime, default=datetime.utcnow)


class QuizSession(db.Model):
    __tablename__ = "quiz_session"

    id = db.Column(db.Integer, primary_key=True)
    source_type = db.Column(db.String(32))
    source_id = db.Column(db.Integer)
    quiz_type = db.Column(db.String(32))
    score = db.Column(db.Integer, default=0)
    total = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)

    answers = db.relationship(
        "QuizAnswer", backref="session", lazy=True, cascade="all, delete-orphan"
    )


class QuizAnswer(db.Model):
    __tablename__ = "quiz_answer"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("quiz_session.id"), nullable=False)
    vocabulary_item_id = db.Column(db.Integer, db.ForeignKey("vocabulary_item.id"))
    question = db.Column(db.Text)
    user_answer = db.Column(db.Text)
    correct_answer = db.Column(db.Text)
    is_correct = db.Column(db.Boolean, default=False)
    mistake_type = db.Column(db.String(32))


class ProgressSnapshot(db.Model):
    __tablename__ = "progress_snapshot"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    words_learned = db.Column(db.Integer, default=0)
    words_mastered = db.Column(db.Integer, default=0)
    quiz_accuracy = db.Column(db.Float, default=0.0)
    time_spent_minutes = db.Column(db.Integer, default=0)

class AskHistory(db.Model):
    __tablename__ = "ask_history"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("uploaded_document.id"))
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    related_words = db.Column(db.JSON, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    document = db.relationship("UploadedDocument", backref="questions")

class Roadmap(db.Model):
    __tablename__ = "roadmap"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), default="My learning path")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    levels = db.relationship(
        "RoadmapLevel", backref="roadmap", lazy=True, cascade="all, delete-orphan"
    )

class RoadmapLevel(db.Model):
    __tablename__ = "roadmap_level"

    id = db.Column(db.Integer, primary_key=True)
    roadmap_id = db.Column(db.Integer, db.ForeignKey("roadmap.id"), nullable=False)
    level_index = db.Column(db.Integer, nullable=False)
    title = db.Column(db.String(128))
    description = db.Column(db.Text)
    topics = db.Column(db.JSON, default=list)   # ["food", "travel", ...]
    target_word_count = db.Column(db.Integer, default=50)
    status = db.Column(db.String(16), default="locked")  # locked, active, completed
    completed_at = db.Column(db.DateTime)

class PlacementSession(db.Model):
    __tablename__ = "placement_session"

    id = db.Column(db.Integer, primary_key=True)
    estimated_level = db.Column(db.String(8))   # A1–C1 or beginner/advanced
    weak_areas = db.Column(db.JSON, default=list)
    strengths = db.Column(db.JSON, default=list)
    raw_evaluation = db.Column(db.JSON)
    finished_at = db.Column(db.DateTime, default=datetime.utcnow)

class ConversationSession(db.Model):
    __tablename__ = "conversation_session"

    id = db.Column(db.Integer, primary_key=True)
    topic = db.Column(db.String(128))
    difficulty = db.Column(db.String(16))
    target_words = db.Column(db.JSON, default=list)
    messages = db.Column(db.JSON, default=list)
    words_used_correctly = db.Column(db.JSON, default=list)
    words_missed = db.Column(db.JSON, default=list)
    corrections = db.Column(db.JSON, default=list)
    summary = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime)
