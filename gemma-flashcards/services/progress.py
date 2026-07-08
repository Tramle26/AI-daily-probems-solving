from datetime import datetime, timedelta

from models import FlashcardDeck, QuizSession, UploadedDocument, VocabularyItem


def get_dashboard_summary():
    total = VocabularyItem.query.count()
    mastered = VocabularyItem.query.filter_by(mastery_status="mastered").count()
    weak = VocabularyItem.query.filter_by(mastery_status="weak").count()
    weak_items = VocabularyItem.query.filter_by(mastery_status="weak").limit(5).all()

    week_ago = datetime.utcnow() - timedelta(days=7)
    sessions = QuizSession.query.filter(QuizSession.finished_at >= week_ago).all()
    if sessions and sum(s.total for s in sessions):
        accuracy = sum(s.score for s in sessions) / sum(s.total for s in sessions) * 100
    else:
        accuracy = 0.0

    recent_decks = FlashcardDeck.query.order_by(FlashcardDeck.created_at.desc()).limit(5).all()
    recent_uploads = UploadedDocument.query.order_by(UploadedDocument.uploaded_at.desc()).limit(5).all()

    if weak:
        recommendation = {"label": "Review weak words", "url": "main.quiz", "hint": f"{weak} words need practice"}
    else:
        recommendation = {"label": "Generate a new deck", "url": "flashcards.index", "hint": "Pick a topic to study"}

    return {
        "total": total,
        "mastered": mastered,
        "weak": weak,
        "accuracy": round(accuracy, 1),
        "weak_items": weak_items,
        "recent_decks": recent_decks,
        "recent_uploads": recent_uploads,
        "recommendation": recommendation,
    }