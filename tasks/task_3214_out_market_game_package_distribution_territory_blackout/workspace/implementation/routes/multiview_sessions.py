"""Multiview sessions: start, end."""
from flask import Blueprint

from db import db
from errors import (
    err_not_owner, err_multiview_cap, err_not_found, err_already_terminal,
)
from middleware import require_roles
from response import success
from services import (
    new_resource, touch, get_or_404, multiview_check_eligibility,
    active_multiview_sessions, MAX_MULTIVIEW_SESSIONS,
)
from validate import body_json, req_string

bp = Blueprint("multiview_sessions", __name__)


def _check_owner(auth, account_id):
    user_id, role = auth
    if role in ("Subscriber", "VenueManager") and user_id != account_id:
        raise err_not_owner()


@bp.post("/multiview-sessions")
@require_roles("Subscriber", "VenueManager")
def start_multiview_session(auth):
    body = body_json()
    subscription_id = req_string(body, "subscription_id")
    sub = get_or_404(db.subscriptions, subscription_id)
    _check_owner(auth, sub["account_id"])

    # Eligibility (priority 20): feature entitlement
    multiview_check_eligibility(sub)
    # Cap (priority 19): at most MAX_MULTIVIEW_SESSIONS active per account
    active = active_multiview_sessions(sub["account_id"])
    if len(active) >= MAX_MULTIVIEW_SESSIONS:
        raise err_multiview_cap()

    session = new_resource()
    session.update({
        "subscription_id": sub["id"],
        "account_id": sub["account_id"],
        "status": "ACTIVE",
    })
    db.multiview_sessions[session["id"]] = session
    active_count = len(active_multiview_sessions(sub["account_id"]))
    return success({
        "multiview_session_id": session["id"],
        "active_count": active_count,
    }, status=201)


@bp.post("/multiview-sessions/<sid>/end")
@require_roles("Subscriber", "VenueManager")
def end_multiview_session(sid, auth):
    session = db.multiview_sessions.get(sid)
    if session is None:
        raise err_not_found()
    if session["status"] != "ACTIVE":
        raise err_already_terminal()
    _check_owner(auth, session["account_id"])
    session["status"] = "ENDED"
    touch(session)
    active_count = len(active_multiview_sessions(session["account_id"]))
    return success({
        "multiview_session_id": session["id"],
        "active_count": active_count,
    })
