"""Professional-development events and the continuing-education ledger
(PRD 3.5): PDEvent creation, attendance postings, CE entry reads and voids."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from envelope import ok, pagination_params, list_response
from errors import (
    ApiError,
    ERR_VALIDATION,
    ERR_EVENT_NOT_FOUND,
    ERR_CREDENTIAL_NOT_FOUND,
    ERR_CE_ENTRY_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_ATTENDANCE,
)
from serializers import serialize_pd_event, serialize_ce_entry
from store import db, new_id, stamp_new, stamp_new_lean, touch, parse_datetime
from validation import (
    authenticate,
    require_role,
    payload,
    req_str,
    req_number,
    opt_number,
)

bp = Blueprint("events", __name__)

EVENT_READ_ROLES = {
    "SocietyAdmin",
    "AccreditationReviewer",
    "Registrar",
    "ProgramDirector",
    "AdultLearner",
    "SchoolAdmin",
    "Consultant",
}
CE_READ_ROLES = {"SocietyAdmin", "Registrar", "AccreditationReviewer", "AdultLearner"}


def _hours_decimal(v):
    """CE hours are kept at 1 decimal place (PRD 2.9)."""
    return Decimal(str(v)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def get_event_or_404(event_id):
    e = db.pd_events.get(event_id)
    if e is None:
        raise ApiError(ERR_EVENT_NOT_FOUND[0], ERR_EVENT_NOT_FOUND[1],
                       "No PD event with id %r." % event_id)
    return e


@bp.route("/pd-events", methods=["POST"])
def create_event():
    _, role = authenticate()
    require_role(role, {"SocietyAdmin"})
    body = payload()
    title = req_str(body, "title")
    provider_name = req_str(body, "provider_name")
    start_s = body.get("start_at")
    end_s = body.get("end_at")
    start = parse_datetime(start_s)
    end = parse_datetime(end_s)
    if start is None or end is None:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "start_at and end_at are required ISO 8601 datetimes.")
    ce_hours = req_number(body, "ce_hours", gt=0)
    if not end > start:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "end_at must be strictly after start_at.")
    event = {
        "id": new_id(),
        "title": title,
        "provider_name": provider_name,
        "start_at": start_s,
        "end_at": end_s,
        "ce_hours": float(_hours_decimal(ce_hours)),
        "status": "SCHEDULED",
    }
    stamp_new(event)
    db.pd_events[event["id"]] = event
    return ok(serialize_pd_event(event), 201)


@bp.route("/pd-events/<event_id>", methods=["GET"])
def get_event(event_id):
    _, role = authenticate()
    require_role(role, EVENT_READ_ROLES)
    return ok(serialize_pd_event(get_event_or_404(event_id)), 200)


@bp.route("/pd-events/<event_id>/attendance", methods=["POST"])
def record_attendance(event_id):
    _, role = authenticate()
    require_role(role, {"SocietyAdmin"})
    event = get_event_or_404(event_id)
    body = payload()
    # Tier 3: credential_id body FK.
    cred_raw = body.get("credential_id")
    cred = None
    if isinstance(cred_raw, str):
        cred = db.credentials.get(cred_raw)
        if cred is None:
            raise ApiError(ERR_CREDENTIAL_NOT_FOUND[0], ERR_CREDENTIAL_NOT_FOUND[1],
                           "No credential with id %r." % cred_raw)
    # Tier 4: credential_id required; hours_earned > 0 and <= event.ce_hours.
    if not isinstance(cred_raw, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'credential_id' is required and must be a string.")
    hours_earned = opt_number(body, "hours_earned")
    if hours_earned is not None:
        he = Decimal(str(hours_earned))
        if he <= 0:
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "hours_earned must exceed zero.")
        if he > Decimal(str(event["ce_hours"])):
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "hours_earned may not exceed the event's ce_hours.")
    # Tier 6: attendance is recorded only on a COMPLETED event.
    if event["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Attendance requires a COMPLETED event.")
    # Tier 9: at most one non-VOID entry per credential and event.
    for e in db.ce_entries.values():
        if (e["credential_id"] == cred["id"] and e["pd_event_id"] == event["id"]
                and e["status"] != "VOID"):
            raise ApiError(ERR_DUPLICATE_ATTENDANCE[0], ERR_DUPLICATE_ATTENDANCE[1],
                           "This credential already has an entry for the event.")
    entry = {
        "id": new_id(),
        "credential_id": cred["id"],
        "pd_event_id": event["id"],
        "hours": _hours_decimal(hours_earned) if hours_earned is not None
                 else _hours_decimal(event["ce_hours"]),
        # Credit is earned when the event completes, not when the posting lands.
        "earned_at": event["end_at"],
        "status": "ACTIVE",
    }
    stamp_new_lean(entry)
    db.ce_entries[entry["id"]] = entry
    return ok(_serialize_entry(entry), 201)


def _serialize_entry(entry):
    out = serialize_ce_entry(entry)
    out["hours"] = float(entry["hours"])
    return out


@bp.route("/ce-entries/<entry_id>", methods=["GET"])
def get_ce_entry(entry_id):
    _, role = authenticate()
    require_role(role, CE_READ_ROLES)
    e = db.ce_entries.get(entry_id)
    if e is None:
        raise ApiError(ERR_CE_ENTRY_NOT_FOUND[0], ERR_CE_ENTRY_NOT_FOUND[1],
                       "No CE credit entry with id %r." % entry_id)
    return ok(_serialize_entry(e), 200)


@bp.route("/ce-entries", methods=["GET"])
def list_ce_entries():
    _, role = authenticate()
    require_role(role, CE_READ_ROLES)
    args = request.args
    items = list(db.ce_entries.values())
    for f in ("credential_id", "pd_event_id", "status"):
        v = args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, _serialize_entry)


@bp.route("/ce-entries/<entry_id>/void", methods=["POST"])
def void_ce_entry(entry_id):
    _, role = authenticate()
    require_role(role, {"SocietyAdmin"})
    e = db.ce_entries.get(entry_id)
    if e is None:
        raise ApiError(ERR_CE_ENTRY_NOT_FOUND[0], ERR_CE_ENTRY_NOT_FOUND[1],
                       "No CE credit entry with id %r." % entry_id)
    if e["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an ACTIVE CE entry can be voided.")
    e["status"] = "VOID"
    # CECreditEntry carries no version/updated_at (PRD 2.4); the credential's
    # CE totals are derived on read, so voiding needs no further writes.
    return ok(_serialize_entry(e), 200)
