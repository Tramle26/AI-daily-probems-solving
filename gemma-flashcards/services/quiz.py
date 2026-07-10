import random
from datetime import datetime

from extensions import db
from models import Flashcard, FlashcardDeck, QuizAnswer, QuizSession, VocabularyItem
from services.ownership import current_user_id, get_owned_or_404, owned_query


def get_quiz_pool(source_type, source_id=None, limit=10):
    base = owned_query(VocabularyItem)
    if source_type in ("practice", "weak"):
        items = base.filter_by(mastery_status="practice").all()
    elif source_type == "deck" and source_id:
        deck = get_owned_or_404(FlashcardDeck, source_id)
        items = (
            owned_query(VocabularyItem)
            .join(Flashcard)
            .filter(Flashcard.deck_id == deck.id)
            .all()
        )
    elif source_type == "today":
        today = datetime.utcnow().date()
        items = base.filter(db.func.date(VocabularyItem.first_seen_at) == today).all()
    else:
        items = base.filter(VocabularyItem.mastery_status != "mastered").limit(limit).all()
    return items[:limit]


def build_multiple_choice(items):
    if len(items) < 2:
        return []
    questions = []
    all_meanings = [v.meaning for v in items if v.meaning]
    for item in items:
        if not item.meaning:
            continue
        wrong_pool = [m for m in all_meanings if m != item.meaning]
        wrong = random.sample(wrong_pool, min(3, len(wrong_pool)))
        options = wrong + [item.meaning]
        random.shuffle(options)
        questions.append({
            "vocab_id": item.id,
            "question": f'What does "{item.word}" mean?',
            "options": options,
            "correct": item.meaning,
            "quiz_type": "multiple_choice",
        })
    return questions


def build_fill_blank(items):
    questions = []
    for item in items:
        if not item.example or item.word not in item.example:
            continue
        questions.append({
            "vocab_id": item.id,
            "question": item.example.replace(item.word, "_____", 1),
            "correct": item.word.strip(),
            "quiz_type": "fill_blank",
        })
    return questions


def grade_and_update_mastery(session, answers):
    score = 0
    for answer in answers:
        item = owned_query(VocabularyItem).filter_by(id=answer["vocab_id"]).first()
        if not item:
            continue
        user = answer.get("user_answer", "").strip().lower()
        correct = answer.get("correct", "").strip().lower()
        is_correct = user == correct

        if is_correct:
            score += 1
            item.review_count = (item.review_count or 0) + 1
            item.mastery_status = "mastered" if item.review_count >= 2 else "learning"
        else:
            item.mastery_status = "practice"

        item.last_reviewed_at = datetime.utcnow()
        db.session.add(QuizAnswer(
            session_id=session.id,
            vocabulary_item_id=item.id,
            question=answer.get("question"),
            user_answer=answer.get("user_answer"),
            correct_answer=answer.get("correct"),
            is_correct=is_correct,
        ))

    session.score = score
    session.total = len(answers)
    session.finished_at = datetime.utcnow()
    db.session.commit()
    return score, len(answers)


def create_quiz_session(source_type, quiz_type, source_id=None, total=0):
    session = QuizSession(
        user_id=current_user_id(),
        source_type=source_type,
        source_id=source_id,
        quiz_type=quiz_type,
        total=total,
    )
    db.session.add(session)
    return session
