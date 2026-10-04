"""Facility endpoints: CRUD, activate/suspend, dormancy scan,
video-availability and regulatory-summary computed reads."""

from datetime import timedelta

from flask import Blueprint, request

from calc import cap_for_facility, regulatory_summary
from core import (ALL_ROLES, CLOCK, DB, auth, body, err, list_response,
                  new_entity, ok_obj, opt_int, parse_date, parse_dt, pub,
                  req_int, req_str, touch)

bp = Blueprint("facilities", __name__)


def facility_or_404(facility_id):
    facility = DB.facilities.get(facility_id)
    if facility is None:
        err("ERR_FACILITY_NOT_FOUND", 404,
            "Facility %s does not exist" % facility_id)
    return facility


@bp.post("/comm-services/facilities")
def create_facility():
    auth(["PlatformAdmin"])
    data = body()
    entity = new_entity()
    entity.update({
        "name": req_str(data, "name"),
        "state_code": req_str(data, "state_code"),
        "video_booth_count": req_int(data, "video_booth_count"),
        "video_turnover_minutes": opt_int(data, "video_turnover_minutes", 10),
        "max_session_minutes": req_int(data, "max_session_minutes"),
        "visiting_open_minutes": req_int(data, "visiting_open_minutes"),
        "visiting_close_minutes": req_int(data, "visiting_close_minutes"),
        "daily_session_limit_per_inmate": opt_int(
            data, "daily_session_limit_per_inmate", 2),
        "status": "ONBOARDING",
    })
    DB.facilities[entity["id"]] = entity
    return ok_obj(pub(entity), 201)


@bp.get("/comm-services/facilities/<facility_id>")
def get_facility(facility_id):
    auth(ALL_ROLES)
    return ok_obj(pub(facility_or_404(facility_id)))


@bp.get("/comm-services/facilities")
def list_facilities():
    auth(ALL_ROLES)
    items = list(DB.facilities.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        items = [f for f in items if f["state_code"] == state_code]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return list_response(items, pub)


@bp.post("/comm-services/facilities/<facility_id>/activate")
def activate_facility(facility_id):
    auth(["PlatformAdmin"])
    facility = facility_or_404(facility_id)
    if facility["status"] not in ("ONBOARDING", "SUSPENDED"):
        err("ERR_INVALID_STATE", 409,
            "Only an ONBOARDING or SUSPENDED facility can be activated")
    has_active_contract = any(
        c["facility_id"] == facility["id"] and c["status"] == "ACTIVE"
        for c in DB.contracts.values())
    if not has_active_contract:
        err("ERR_NO_ACTIVE_CONTRACT", 409,
            "Facility activation requires at least one ACTIVE contract")
    facility["status"] = "ACTIVE"
    touch(facility)
    return ok_obj(pub(facility))


@bp.post("/comm-services/facilities/<facility_id>/suspend")
def suspend_facility(facility_id):
    auth(["PlatformAdmin"])
    facility = facility_or_404(facility_id)
    if facility["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", 409, "Only an ACTIVE facility can be suspended")
    facility["status"] = "SUSPENDED"
    touch(facility)
    return ok_obj(pub(facility))


@bp.post("/comm-services/facilities/<facility_id>/run-dormancy-scan")
def run_dormancy_scan(facility_id):
    auth(["PlatformAdmin"])
    facility = facility_or_404(facility_id)
    cap = cap_for_facility(facility)
    now = CLOCK.now()
    flagged = 0
    if cap is not None:
        threshold = timedelta(days=cap["dormancy_days"])
        for account in DB.accounts.values():
            if (account["facility_id"] == facility["id"]
                    and account["status"] == "CLOSED"
                    and account["unclaimed_balance_cents"] > 0
                    and account["escheat_status"] == "NONE"
                    and account["unclaimed_since"] is not None
                    and now >= account["unclaimed_since"] + threshold):
                # Boundary: an age exactly equal to dormancy_days qualifies.
                account["escheat_status"] = "DORMANT"
                touch(account)
                flagged += 1
    return ok_obj({"accounts_flagged": flagged})


@bp.get("/comm-services/facilities/<facility_id>/video-availability")
def video_availability(facility_id):
    auth(ALL_ROLES)
    facility = facility_or_404(facility_id)
    raw = request.args.get("date")
    if raw is None:
        err("ERR_INVALID_REQUEST", 400, "Query parameter date is required")
    day = parse_date(raw)
    booked = sum(
        s["duration_minutes"] for s in DB.sessions.values()
        if s["facility_id"] == facility["id"] and s["status"] == "CONFIRMED"
        and s["scheduled_start"].date() == day)
    bookable = (facility["video_booth_count"]
                * (facility["visiting_close_minutes"]
                   - facility["visiting_open_minutes"]) - booked)
    return ok_obj({
        "date": day.isoformat(),
        "booth_count": facility["video_booth_count"],
        "booked_minutes": booked,
        "bookable_minutes": bookable,
    })


@bp.get("/comm-services/facilities/<facility_id>/regulatory-summary")
def get_regulatory_summary(facility_id):
    auth(["PlatformAdmin", "StateRegulator", "ComplianceOfficer"])
    facility = facility_or_404(facility_id)
    raw_start = request.args.get("period_start")
    raw_end = request.args.get("period_end")
    if raw_start is None or raw_end is None:
        err("ERR_INVALID_REQUEST", 400,
            "period_start and period_end query parameters are required")
    period_start = parse_dt(raw_start, "period_start")
    period_end = parse_dt(raw_end, "period_end")
    return ok_obj(regulatory_summary(facility, period_start, period_end))
