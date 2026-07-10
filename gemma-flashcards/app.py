# app.py
import os

from dotenv import load_dotenv
from flask import Flask

from extensions import db, login_manager

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///learning.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.path.join(app.root_path, "uploads")

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from models import User

        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import jsonify, redirect, request, url_for

        if request.path.startswith("/api/") or request.path == "/stream":
            return jsonify({"error": "Authentication required"}), 401
        return redirect(url_for("auth.login", next=request.path))

    with app.app_context():
        import models  # noqa: F401
        from models import VocabularyItem
        from sqlalchemy import inspect, text

        # Phase 4: recreate DB if the multi-user schema is missing.
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        needs_reset = False
        if "user" not in tables:
            needs_reset = bool(tables)
        elif "vocabulary_item" in tables:
            cols = {col["name"] for col in inspector.get_columns("vocabulary_item")}
            if "user_id" not in cols:
                needs_reset = True

        if needs_reset:
            db.drop_all()

        db.create_all()

        inspector = inspect(db.engine)
        if "vocabulary_item" in inspector.get_table_names():
            existing = {col["name"] for col in inspector.get_columns("vocabulary_item")}
            alters = []
            if "next_review_at" not in existing:
                alters.append("ALTER TABLE vocabulary_item ADD COLUMN next_review_at DATETIME")
            if "ease_factor" not in existing:
                alters.append("ALTER TABLE vocabulary_item ADD COLUMN ease_factor FLOAT DEFAULT 2.5")
            if "interval_days" not in existing:
                alters.append("ALTER TABLE vocabulary_item ADD COLUMN interval_days INTEGER DEFAULT 1")
            for stmt in alters:
                db.session.execute(text(stmt))
            if alters:
                db.session.commit()

        VocabularyItem.query.filter_by(mastery_status="weak").update(
            {"mastery_status": "practice"}
        )
        db.session.commit()

    from routes import api, auth, flashcards, main
    from models import MASTERY_STATUS_LABELS

    @app.context_processor
    def inject_globals():
        from flask_login import current_user

        from services.background import get_background_config
        from services.profile import get_profile

        profile = get_profile() if current_user.is_authenticated else None
        return {
            "mastery_labels": MASTERY_STATUS_LABELS,
            "background_config": get_background_config(profile),
        }

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(flashcards.bp)
    app.register_blueprint(api.bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
