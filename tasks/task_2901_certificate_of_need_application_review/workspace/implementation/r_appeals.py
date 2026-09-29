"""Appeals, litigation holds and the disposition cascades (PRD §3.9)."""

from flask import Blueprint

import auth
import cascades
import clock
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("appeals", __name__)

READ_ROLES = auth.STAFF_AND_PARTIES
APPEAL_STATUSES = ("FILED", "BRIEFING", "HEARD", "STAYED", "AFFIRMED", "REVERSED", "REMANDED")
ADVANCE_STEPS = {"FILED": "BRIEFING", "BRIEFING": "HEARD"}
HOLD_ACTIONS = ("APPLY", "LIFT")
DISPOSITIONS = ("AFFIRMED", "REVERSED", "REMANDED")
HOLD_SOURCES = ("BRIEFING", "HEARD")


@bp.post("/appeals")
def file_appeal():
    user_id, _role = auth.identity(["Applicant"])
    body = shape.body()
    application_id = shape.string_field(body, "application_id")
    appellant_id = shape.string_field(body, "appellant_applicant_id")
    grounds = shape.string_field(body, "grounds")

    app = services.application(application_id)
    appellant = services.applicant(appellant_id)

    services.require_owner(user_id, appellant_id)
    services.require_not_barred(appellant)

    standing = appellant_id == app["applicant_id"]
    if not standing:
        for row in store.rows("interventions"):
            if (row["application_id"] == app["id"] and row["status"] == "GRANTED"
                    and row["affected_party_applicant_id"] == appellant_id):
                standing = True
                break
    if not standing:
        raise ApiError("ERR_NOT_AFFECTED_PARTY",
                       "The appellant has no standing to appeal this application.")

    closes = app.get("appeal_window_closes_at")
    if closes is None or clock.now() > clock.parse_instant(closes):
        raise ApiError("ERR_APPEAL_WINDOW_EXPIRED", "The appeal window has expired.")

    if services.pending_appeal_exists(app["id"]):
        raise ApiError("ERR_APPEAL_PENDING",
                       "Another appeal on this application is still pending.")

    record = store.create("appeals", {
        "application_id": app["id"],
        "appellant_applicant_id": appellant_id,
        "grounds": grounds,
        "filed_at": clock.now_str(),
        "status": "FILED",
        "status_before_hold": None,
        "litigation_hold_active": False,
        "disposition": None,
        "decided_by_user_id": None,
    })
    return envelope.ok(record, 201)


@bp.get("/appeals/<record_id>")
def read_appeal(record_id):
    auth.identity(READ_ROLES)
    return envelope.ok(services.appeal(record_id))


@bp.get("/appeals")
def list_appeals():
    auth.identity(READ_ROLES)
    limit, offset = shape.pagination()
    picked = shape.filters("application_id", "appellant_applicant_id", "status")
    rows = shape.apply_filters(store.sort_created(store.rows("appeals")), picked)
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.post("/appeals/<record_id>/advance")
def advance_appeal(record_id):
    auth.identity(["AppealBoardMember"])
    body = shape.body()
    to_status = shape.enum_field(body, "to_status", APPEAL_STATUSES)
    record = services.appeal(record_id)
    if ADVANCE_STEPS.get(record["status"]) != to_status:
        raise ApiError("ERR_APPEAL_NOT_IN_REQUIRED_STATUS",
                       "The appeal is not in the status this advance requires.")
    record["status"] = to_status
    store.touch(record)
    return envelope.ok(record)


@bp.post("/appeals/<record_id>/litigation-hold")
def litigation_hold(record_id):
    auth.identity(["AppealBoardMember"])
    body = shape.body()
    action = shape.enum_field(body, "action", HOLD_ACTIONS)
    record = services.appeal(record_id)

    if action == "APPLY":
        if record["status"] not in HOLD_SOURCES:
            raise ApiError("ERR_APPEAL_NOT_IN_REQUIRED_STATUS",
                           "A hold may only be applied from BRIEFING or HEARD.")
        record["status_before_hold"] = record["status"]
        record["status"] = "STAYED"
        record["litigation_hold_active"] = True
    else:
        if record["status"] != "STAYED":
            raise ApiError("ERR_APPEAL_NOT_IN_REQUIRED_STATUS",
                           "A hold may only be lifted from STAYED.")
        record["status"] = record["status_before_hold"] or "BRIEFING"
        record["status_before_hold"] = None
        record["litigation_hold_active"] = False
    store.touch(record)
    return envelope.ok(record)


@bp.post("/appeals/<record_id>/decide")
def decide_appeal(record_id):
    user_id, _role = auth.identity(["AppealBoardMember"])
    body = shape.body()
    disposition = shape.enum_field(body, "disposition", DISPOSITIONS)
    shape.string_field(body, "rationale", required=False, default=None)
    record = services.appeal(record_id)

    if record["status"] != "HEARD":
        raise ApiError("ERR_APPEAL_NOT_IN_REQUIRED_STATUS",
                       "A disposition may only be entered from HEARD.")

    record["disposition"] = disposition
    record["decided_by_user_id"] = user_id
    record["litigation_hold_active"] = False
    record["status"] = disposition
    store.touch(record)

    if disposition in ("REVERSED", "REMANDED"):
        touch = cascades.Touch()
        if disposition == "REVERSED":
            cascades.reversal_cascade(record, touch)
        else:
            cascades.remand_cascade(record, touch)
        touch.flush()
    return envelope.ok(record)
