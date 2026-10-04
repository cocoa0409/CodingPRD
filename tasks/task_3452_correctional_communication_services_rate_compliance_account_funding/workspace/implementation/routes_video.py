"""VideoSession endpoints: request, confirm (charge), cancel (refund),
close-out, and listing.

Confirm re-validates everything because time has passed since creation, in
PRD section 2.8 tier order: state gates -> temporal (session-in-past, then
inmate overlap) -> capacity/daily-limit -> fiscal. ERR_INMATE_SESSION_OVERLAP
therefore outranks capacity and daily-limit failures when several apply.
"""

from datetime import timedelta

from flask import Blueprint

from calc import (active_contract, active_schedule, can_cover,
                  capacity_exceeded, cap_for_facility, daily_confirmed_count,
                  inmate_session_overlap)
from core import (ALL_ROLES, CLOCK, DB, append_ledger, auth, body, err,
                  list_response, new_entity, ok_obj, pub, req_dt, req_enum,
                  req_str, touch, apply_filters)

bp = Blueprint("video", __name__)

MIN_SESSION_MINUTES = 15


def session_or_404(session_id):
    session = DB.sessions.get(session_id)
    if session is None:
        err("ERR_VIDEO_SESSION_NOT_FOUND", 404,
            "VideoSession %s does not exist" % session_id)
    return session


def _check_window(facility, start, end):
    """Whole session must sit inside the visiting window (bounds inclusive)."""
    midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
    window_open = midnight + timedelta(minutes=facility["visiting_open_minutes"])
    window_close = midnight + timedelta(minutes=facility["visiting_close_minutes"])
    if start < window_open or end > window_close:
        err("ERR_SESSION_DURATION_INVALID", 422,
            "Session must sit inside the facility visiting window")


@bp.post("/comm-services/video-sessions")
def create_session():
    user_id, role = auth(["AccountHolder", "FacilityStaff"])
    data = body()
    # Tier 3 ownership (checkable from the body without loading entities).
    account_id = req_str(data, "account_id")
    if role == "AccountHolder" and user_id != account_id:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "AccountHolder may only request sessions on their own account")
    visitor_name = req_str(data, "visitor_name")
    start = req_dt(data, "scheduled_start")
    end = req_dt(data, "scheduled_end")
    # Tier 4 shape checks that need no entities.
    if end <= start:
        err("ERR_SESSION_DURATION_INVALID", 422,
            "Session end must be strictly after its start")
    if start.date() != end.date():
        err("ERR_SESSION_DURATION_INVALID", 422,
            "Session start and end must fall on the same UTC date")
    total_seconds = (end - start).total_seconds()
    if total_seconds < MIN_SESSION_MINUTES * 60:
        err("ERR_SESSION_DURATION_INVALID", 422,
            "Session must run at least 15 minutes")
    # Tier 5: body FKs in declared input order (facility_id, inmate_id, ...).
    facility_id = req_str(data, "facility_id")
    inmate_id = req_str(data, "inmate_id")
    facility = DB.facilities.get(facility_id)
    if facility is None:
        err("ERR_FACILITY_NOT_FOUND", 404,
            "Facility %s does not exist" % facility_id)
    inmate = DB.inmates.get(inmate_id)
    if inmate is None:
        err("ERR_INMATE_NOT_FOUND", 404,
            "Inmate %s does not exist" % inmate_id)
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_ACCOUNT_NOT_FOUND", 404,
            "Account %s does not exist" % account_id)
    # Tier 4 shape checks that need the facility.
    if total_seconds > facility["max_session_minutes"] * 60:
        err("ERR_SESSION_DURATION_INVALID", 422,
            "Session exceeds the facility max_session_minutes")
    _check_window(facility, start, end)
    if start <= CLOCK.now():
        err("ERR_SESSION_IN_PAST", 422,
            "Session start must lie strictly in the future")
    # Tier 6 state gates.
    if facility["status"] != "ACTIVE":
        err("ERR_FACILITY_NOT_ACTIVE", 409,
            "Video sessions require an ACTIVE facility")
    if account["status"] != "ACTIVE":
        err("ERR_ACCOUNT_NOT_ACTIVE", 409,
            "Video sessions require an ACTIVE account")
    if inmate["status"] != "IN_CUSTODY":
        err("ERR_INMATE_NOT_IN_CUSTODY", 409,
            "Video sessions require the inmate to be IN_CUSTODY")
    entity = new_entity()
    entity.update({
        "facility_id": facility_id,
        "inmate_id": inmate_id,
        "account_id": account_id,
        "visitor_name": visitor_name,
        "scheduled_start": start,
        "scheduled_end": end,
        "duration_minutes": int(total_seconds // 60),
        "status": "REQUESTED",
        "charge_cents": None,
        "confirmed_at": None,
        "cancelled_at": None,
        "closed_out_at": None,
    })
    DB.sessions[entity["id"]] = entity
    return ok_obj(pub(entity), 201)


@bp.get("/comm-services/video-sessions/<session_id>")
def get_session(session_id):
    auth(ALL_ROLES)
    return ok_obj(pub(session_or_404(session_id)))


@bp.get("/comm-services/video-sessions")
def list_sessions():
    auth(ALL_ROLES)
    items = apply_filters(DB.sessions.values(),
                          ["facility_id", "inmate_id", "account_id", "status"])
    return list_response(items, pub)


@bp.post("/comm-services/video-sessions/<session_id>/confirm")
def confirm_session(session_id):
    auth(["FacilityStaff"])
    session = session_or_404(session_id)
    if session["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409,
            "Only a REQUESTED session can be confirmed")
    # Tier 6 state gates, re-validated at confirm time.
    facility = DB.facilities.get(session["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        err("ERR_FACILITY_NOT_ACTIVE", 409,
            "Confirm requires an ACTIVE facility")
    account = DB.accounts.get(session["account_id"])
    if account is None or account["status"] != "ACTIVE":
        err("ERR_ACCOUNT_NOT_ACTIVE", 409, "Confirm requires an ACTIVE account")
    inmate = DB.inmates.get(session["inmate_id"])
    if inmate is None or inmate["status"] != "IN_CUSTODY":
        err("ERR_INMATE_NOT_IN_CUSTODY", 409,
            "Confirm requires the inmate to be IN_CUSTODY")
    contract = active_contract(facility["id"])
    schedule = active_schedule(contract["id"]) if contract is not None else None
    if schedule is None:
        err("ERR_NO_ACTIVE_RATE_SCHEDULE", 409,
            "Confirm requires the contract's ACTIVE rate schedule")
    # Tier 8 temporal rules.
    now = CLOCK.now()
    if session["scheduled_start"] <= now:
        err("ERR_SESSION_IN_PAST", 422,
            "Session start must still lie strictly in the future at confirm")
    if inmate_session_overlap(session["inmate_id"], session["scheduled_start"],
                              session["scheduled_end"]):
        err("ERR_INMATE_SESSION_OVERLAP", 409,
            "Inmate already holds a CONFIRMED session overlapping this one")
    # Tier 9 capacity and daily-limit rules.
    if capacity_exceeded(facility, session["scheduled_start"],
                         session["scheduled_end"]):
        err("ERR_FACILITY_CAPACITY_EXCEEDED", 409,
            "Buffered booth capacity would be exceeded")
    if (daily_confirmed_count(session["inmate_id"],
                              session["scheduled_start"].date())
            >= facility["daily_session_limit_per_inmate"]):
        err("ERR_DAILY_SESSION_LIMIT_EXCEEDED", 409,
            "Inmate is at the facility's daily CONFIRMED-session limit")
    # Tier 10: account-inmate binding, then fiscal sufficiency.
    if account["inmate_id"] != session["inmate_id"]:
        err("ERR_ACCOUNT_INMATE_MISMATCH", 409,
            "account.inmate_id does not match the session's inmate_id")
    cap = cap_for_facility(facility)
    fee = schedule["video_session_fee_cents"]
    if cap is not None:
        # Charge-time minimum at confirm time.
        fee = min(fee, cap["max_ancillary_fee_cents"])
    if not can_cover(account, fee):
        err("ERR_INSUFFICIENT_BALANCE", 402,
            "Account cannot cover the video session fee")
    session["charge_cents"] = fee
    session["confirmed_at"] = now
    session["status"] = "CONFIRMED"
    touch(session)
    append_ledger(account, "VIDEO_CHARGE", -fee, session["id"],
                  "Video session charge")
    # The charge mutates the account (balance); one version advance.
    touch(account)
    return ok_obj(pub(session))


@bp.post("/comm-services/video-sessions/<session_id>/cancel")
def cancel_session(session_id):
    user_id, role = auth(["AccountHolder", "FacilityStaff"])
    session = session_or_404(session_id)
    # Tier 3 ownership for the entity-backed role (needs the loaded session).
    if role == "AccountHolder" and session["account_id"] != user_id:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "AccountHolder may only cancel their own account's sessions")
    if session["status"] == "REQUESTED":
        # No charge was ever made; no refund is appended.
        session["status"] = "CANCELLED"
        session["cancelled_at"] = CLOCK.now()
        touch(session)
        return ok_obj(pub(session))
    if session["status"] == "CONFIRMED":
        if CLOCK.now() >= session["scheduled_start"]:
            err("ERR_SESSION_NOT_CANCELLABLE", 409,
                "A CONFIRMED session cannot be cancelled once it has started")
        session["status"] = "CANCELLED"
        session["cancelled_at"] = CLOCK.now()
        touch(session)
        account = DB.accounts.get(session["account_id"])
        if account is not None:
            # Full refund; booth-minutes budget is restored exactly.
            append_ledger(account, "VIDEO_REFUND", session["charge_cents"],
                          session["id"], "Video session cancellation refund")
            # The refund mutates the account (balance); one version advance.
            touch(account)
        return ok_obj(pub(session))
    err("ERR_INVALID_STATE", 409,
        "Only a REQUESTED or CONFIRMED session can be cancelled")


@bp.post("/comm-services/video-sessions/<session_id>/close-out")
def close_out_session(session_id):
    auth(["FacilityStaff"])
    data = body()
    outcome = req_enum(data, "outcome", ("COMPLETED", "NO_SHOW"))
    session = session_or_404(session_id)
    if session["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409,
            "Only a CONFIRMED session can be closed out")
    if CLOCK.now() < session["scheduled_end"]:
        # Boundary: a clock exactly at scheduled_end allows close-out.
        err("ERR_SESSION_NOT_ENDED", 409,
            "Session cannot be closed out before its scheduled_end")
    # Neither outcome appends a refund.
    session["status"] = outcome
    session["closed_out_at"] = CLOCK.now()
    touch(session)
    return ok_obj(pub(session))
