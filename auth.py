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


def current_user_id():
    uid = session.get("user_id")
    if uid is not None:
        return uid
    username = session.get("user")
    if username:
        user = User.query.filter_by(username=username).first()
        if user:
            session["user_id"] = user.id
            return user.id
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            if request.path.startswith("/api/"):
                return {"error": "Unauthorized"}, 401
            return redirect(url_for("login"))

        if "user_id" not in session:
            current_user_id()

        return view(*args, **kwargs)

    return wrapped