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
        import models  # noqa: F401 — register all models with SQLAlchemy
        db.create_all()

    from routes import flashcards, main,api

    app.register_blueprint(main.bp)
    app.register_blueprint(flashcards.bp)
    app.register_blueprint(api.bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)