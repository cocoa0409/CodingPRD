"""Recipient routes: authentication, sessions, signing and declining."""

from flask import Blueprint, request

from db import db, new_id, now_clock
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import (
    authenticate,
    ROLE_ACCOUNT,
    ROLE_PLATFORM_ADMIN,
    ROLE_RECIPIENT,
)
from response import ok, ok_array, paginate, read_pagination
from services.common import append_event, serialize, serialize_list, stamp_new, touch
from services.envelope import load_envelope, load_recipient
from services.lifecycle import guard_envelope_from_set, guard_envelope_terminal
from services.recipient import (
    VALID_AUTH_METHODS,
    authenticate_recipient,
    guard_envelope_not_expired,
    guard_routing_released,
    open_session,
)
from services.signing import decline_recipient, sign_recipient
from timeutil import fmt

bp = Blueprint("recipients", __name__)


def _assert_acting_recipient(actor, recipient):
    """A Recipient-role caller may act only on the recipient row it names."""
    from errors import ERR_FORBIDDEN

    if actor.is_recipient and actor.user_id != recipient["id"]:
        raise ApiError(
            ERR_FORBIDDEN[0],
            "recipient %s may not act on recipient %s"
            % (actor.user_id, recipient["id"]),
            ERR_FORBIDDEN[1],
        )


@bp.route("/esign/recipients", methods=["GET"])
def list_recipients():
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    limit, offset = read_pagination(request.args)
    envelope_id = request.args.get("envelope_id")
    status = request.args.get("status")
    recipients = list(db.recipients.values())
    if envelope_id:
        recipients = [r for r in recipients if r["envelope_id"] == envelope_id]
    if status:
        recipients = [r for r in recipients if r["status"] == status]
    recipients.sort(key=lambda r: r.get("_ord", 0))
    window, limit, offset, total = paginate(recipients, limit, offset)
    return ok_array(serialize_list(window), limit, offset, total, 200)


@bp.route("/esign/recipients/<recipient_id>", methods=["GET"])
def get_recipient(recipient_id):
    actor = authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN, ROLE_RECIPIENT])
    recipient = load_recipient(recipient_id)
    _assert_acting_recipient(actor, recipient)
    return ok(serialize(recipient), 200)


@bp.route("/esign/recipients/<recipient_id>/authenticate", methods=["POST"])
def post_authenticate(recipient_id):
    actor = authenticate([ROLE_RECIPIENT])
    recipient = load_recipient(recipient_id)
    _assert_acting_recipient(actor, recipient)
    envelope = load_envelope(recipient["envelope_id"])
    guard_envelope_from_set(envelope, ("SENT", "DELIVERED"))

    body = request.get_json(silent=True) or {}
    method = body.get("method")
    if method not in VALID_AUTH_METHODS:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "method must be one of %s" % "|".join(VALID_AUTH_METHODS),
            ERR_INVALID_REQUEST[1],
        )
    recipient = authenticate_recipient(envelope, recipient, method, body)
    return ok(serialize(recipient), 200)


@bp.route("/esign/recipients/<recipient_id>/sessions", methods=["POST"])
def post_session(recipient_id):
    actor = authenticate([ROLE_RECIPIENT])
    recipient = load_recipient(recipient_id)
    _assert_acting_recipient(actor, recipient)
    envelope = load_envelope(recipient["envelope_id"])
    guard_envelope_from_set(envelope, ("SENT", "DELIVERED"))

    body = request.get_json(silent=True) or {}
    consent = bool(body.get("consent_to_electronic_records", False))
    open_session(envelope, recipient, consent)

    session = {
        "id": new_id(),
        "recipient_id": recipient["id"],
        "envelope_id": envelope["id"],
        "status": "OPEN",
        "consent_to_electronic_records": consent,
        "consent_captured_at": fmt(now_clock()) if consent else None,
        "opened_at": fmt(now_clock()),
    }
    stamp_new(session)
    db.insert(db.sessions, session)

    if recipient["status"] in ("WAITING", "SENT", "DELIVERED"):
        recipient["status"] = "SIGNING"
        touch(recipient)
    if consent:
        recipient["consent_accepted"] = True
        recipient["consent_accepted_at"] = fmt(now_clock())
        touch(recipient)

    append_event(
        envelope["id"], "SESSION_OPENED", recipient_id=recipient["id"],
        detail="signing session opened",
    )
    if consent:
        append_event(
            envelope["id"], "CONSENT_ACCEPTED", recipient_id=recipient["id"],
            detail="consent to electronic records accepted",
        )
    return ok(serialize(session), 201)


@bp.route("/esign/recipients/<recipient_id>/sign", methods=["POST"])
def post_sign(recipient_id):
    actor = authenticate([ROLE_RECIPIENT])
    recipient = load_recipient(recipient_id)
    _assert_acting_recipient(actor, recipient)
    envelope = load_envelope(recipient["envelope_id"])
    guard_envelope_from_set(envelope, ("SENT", "DELIVERED"))
    recipient = sign_recipient(envelope, recipient)
    return ok(serialize(recipient), 200)


@bp.route("/esign/recipients/<recipient_id>/decline", methods=["POST"])
def post_decline(recipient_id):
    actor = authenticate([ROLE_RECIPIENT])
    recipient = load_recipient(recipient_id)
    _assert_acting_recipient(actor, recipient)
    envelope = load_envelope(recipient["envelope_id"])
    body = request.get_json(silent=True) or {}
    decline_reason = body.get("decline_reason")
    if decline_reason is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'decline_reason' is missing",
            ERR_INVALID_REQUEST[1],
        )
    decline_recipient(envelope, recipient, decline_reason)
    return ok(serialize(recipient), 200)