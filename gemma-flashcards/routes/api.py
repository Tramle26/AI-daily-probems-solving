from flask import Blueprint, jsonify, request

from services.vocabulary import save_deck

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.post("/decks")
def create_deck():
    data = request.get_json()
    if not data or not data.get("cards"):
        return jsonify({"error": "No cards provided"}), 400

    deck = save_deck(
        title=data.get("title", "My Deck"),
        language=data["language"],
        source_type=data.get("source_type", "topic"),
        cards=data["cards"],
        source_id=data.get("source_id"),
        document_id=data.get("document_id"),
    )
    return jsonify({"id": deck.id, "title": deck.title}), 201