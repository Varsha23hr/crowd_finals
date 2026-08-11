from functools import wraps
from flask import session, redirect, url_for, request
from models import User


def verify_credentials(username, password):
    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
        return user

    return None


def current_user():
    return session.get("user")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            if request.path.startswith("/api/"):
                return {"error": "Unauthorized"}, 401
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped