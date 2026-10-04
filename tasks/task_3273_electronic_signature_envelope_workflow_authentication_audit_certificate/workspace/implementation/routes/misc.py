"""Field, session, audit-event and logical-clock routes."""

from flask import Blueprint, request

from db import db, now_clock
from errors import (
    ApiError,
    ERR_ENVELOPE_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from middleware import (
    authenticate,
    ROLE_ACCOUNT,
    ROLE_PLATFORM_ADMIN,
    ROLE_RECIPIENT,
)
from response import ok, ok_array, paginate, read_pagination
from services.common import append_event, serialize, serialize_list, touch
from timeutil import fmt, parse_iso

bp = Blueprint("misc", __name__)


@bp.route("/esign/fields", methods=["GET"])
def list_fields():
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    limit, offset = read_pagination(request.args)
    envelope_id = request.args.get("envelope_id")
    document_id = request.args.get("envelope_document_id")
    recipient_id = request.args.get("recipient_id")
    fields = list(db.fields.values())
    if envelope_id:
        fields = [f for f in fields if f["envelope_id"] == envelope_id]
    if document_id:
        fields = [
            f for f in fields if f["envelope_document_id"] == document_id
        ]
    if recipient_id:
        fields = [f for f in fields if f["recipient_id"] == recipient_id]
    fields.sort(key=lambda f: f.get("_ord", 0))
    window, limit, offset, total = paginate(fields, limit, offset)
    return ok_array(serialize_list(window), limit, offset, total, 200)


@bp.route("/esign/fields/<field_id>", methods=["GET"])
def get_field(field_id):
    actor = authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN, ROLE_RECIPIENT])
    field = db.field(field_id)
    if field is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "no field placement matches id %s" % field_id,
            ERR_INVALID_REQUEST[1],
        )
    if actor.is_recipient and actor.user_id != field["recipient_id"]:
        raise ApiError(
            "ERR_FORBIDDEN",
            "recipient %s may not read field %s" % (actor.user_id, field_id),
            403,
        )
    return ok(serialize(field), 200)


@bp.route("/esign/fields/<field_id>", methods=["PATCH"])
def patch_field(field_id):
    """Supply or update a field's value; append FIELD_COMPLETED on the null ->
    non-null transition (scaffold §1.5, PRD §3.5)."""
    actor = authenticate([ROLE_RECIPIENT, ROLE_ACCOUNT])
    field = db.field(field_id)
    if field is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "no field placement matches id %s" % field_id,
            ERR_INVALID_REQUEST[1],
        )
    if actor.is_recipient and actor.user_id != field["recipient_id"]:
        raise ApiError(
            "ERR_FORBIDDEN",
            "recipient %s may not update field %s" % (actor.user_id, field_id),
            403,
        )

    envelope = db.envelope(field["envelope_id"])
    if envelope is None:
        raise ApiError(
            ERR_ENVELOPE_NOT_FOUND[0],
            "the owning envelope no longer exists",
            ERR_ENVELOPE_NOT_FOUND[1],
        )
    if actor.is_account:
        from middleware import owned_by_account

        owned_by_account(actor, envelope["sender_account_id"])

    body = request.get_json(silent=True) or {}
    if "value" not in body:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'value' is missing",
            ERR_INVALID_REQUEST[1],
        )
    was_null = field.get("value") is None
    new_value = body["value"]
    if actor.is_recipient:
        # The acting recipient may only fill its own placements.
        if field["recipient_id"] != actor.user_id:
            raise ApiError(
                "ERR_FORBIDDEN",
                "recipient %s may not update field %s"
                % (actor.user_id, field_id),
                403,
            )
    field["value"] = new_value
    touch(field)
    if was_null and new_value is not None:
        append_event(
            envelope["id"], "FIELD_COMPLETED", recipient_id=field["recipient_id"],
            detail="field %s completed" % field["id"],
        )
    return ok(serialize(field), 200)


@bp.route("/esign/sessions", methods=["GET"])
def list_sessions():
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    limit, offset = read_pagination(request.args)
    recipient_id = request.args.get("recipient_id")
    envelope_id = request.args.get("envelope_id")
    status = request.args.get("status")
    sessions = list(db.sessions.values())
    if recipient_id:
        sessions = [s for s in sessions if s["recipient_id"] == recipient_id]
    if envelope_id:
        sessions = [s for s in sessions if s["envelope_id"] == envelope_id]
    if status:
        sessions = [s for s in sessions if s["status"] == status]
    sessions.sort(key=lambda s: s.get("_ord", 0))
    window, limit, offset, total = paginate(sessions, limit, offset)
    return ok_array(serialize_list(window), limit, offset, total, 200)


@bp.route("/esign/sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    actor = authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN, ROLE_RECIPIENT])
    session = db.session(session_id)
    if session is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "no signing session matches id %s" % session_id,
            ERR_INVALID_REQUEST[1],
        )
    if actor.is_recipient and actor.user_id != session["recipient_id"]:
        raise ApiError(
            "ERR_FORBIDDEN",
            "recipient %s may not read session %s" % (actor.user_id, session_id),
            403,
        )
    return ok(serialize(session), 200)


@bp.route("/esign/audit-events", methods=["GET"])
def list_audit_events():
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    limit, offset = read_pagination(request.args)
    envelope_id = request.args.get("envelope_id")
    recipient_id = request.args.get("recipient_id")
    event_type = request.args.get("event_type")
    events = list(db.audit_events.values())
    if envelope_id:
        events = [e for e in events if e["envelope_id"] == envelope_id]
    if recipient_id:
        events = [e for e in events if e["recipient_id"] == recipient_id]
    if event_type:
        events = [e for e in events if e["event_type"] == event_type]
    events.sort(key=lambda e: e.get("_ord", 0))
    window, limit, offset, total = paginate(events, limit, offset)
    return ok_array(serialize_list(window), limit, offset, total, 200)


@bp.route("/esign/audit-events/<event_id>", methods=["GET"])
def get_audit_event(event_id):
    authenticate([ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN])
    event = db.event(event_id)
    if event is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "no audit event matches id %s" % event_id,
            ERR_INVALID_REQUEST[1],
        )
    return ok(serialize(event), 200)


@bp.route("/esign/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate([ROLE_PLATFORM_ADMIN])
    body = request.get_json(silent=True) or {}
    to_iso8601 = body.get("to_iso8601")
    if to_iso8601 is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0], "required field 'to_iso8601' is missing",
            ERR_INVALID_REQUEST[1],
        )
    instant = parse_iso(to_iso8601)
    if instant is None:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            "to_iso8601 must be a valid ISO 8601 instant",
            ERR_INVALID_REQUEST[1],
        )
    db.clock = instant
    return ok({"current_utc": fmt(instant)}, 200)