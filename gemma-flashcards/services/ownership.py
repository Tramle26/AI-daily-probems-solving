from flask_login import current_user


def current_user_id():
    if not current_user.is_authenticated:
        raise RuntimeError("Authentication required")
    return current_user.id


def owned_query(model):
    """Query rows owned by the logged-in user."""
    return model.query.filter_by(user_id=current_user_id())


def get_owned_or_404(model, object_id):
    return owned_query(model).filter_by(id=object_id).first_or_404()
