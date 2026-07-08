# app.py
import os

from dotenv import load_dotenv
from flask import Flask

from extensions import db

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///learning.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)

    with app.app_context():
        import models  # noqa: F401, register all models with SQLAlchemy
        from models import VocabularyItem

        db.create_all()
        VocabularyItem.query.filter_by(mastery_status="weak").update(
            {"mastery_status": "practice"}
        )
        db.session.commit()

    from routes import flashcards, main,api
    from models import MASTERY_STATUS_LABELS

    @app.context_processor
    def inject_mastery_labels():
        from services.background import get_background_config
        from services.profile import get_profile

        profile = get_profile()
        return {
            "mastery_labels": MASTERY_STATUS_LABELS,
            "background_config": get_background_config(profile),
        }

    app.register_blueprint(main.bp)
    app.register_blueprint(flashcards.bp)
    app.register_blueprint(api.bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)