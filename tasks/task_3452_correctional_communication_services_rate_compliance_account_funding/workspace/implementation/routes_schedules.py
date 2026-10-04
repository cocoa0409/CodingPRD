"""RateSchedule endpoints: get/list and OCC-guarded activation."""

from flask import Blueprint

from calc import cap_for_facility
from core import (ALL_ROLES, CLOCK, DB, auth, body, err, list_response,
                  ok_obj, pub, req_int, touch, apply_filters)

bp = Blueprint("schedules", __name__)

_PER_MINUTE_FIELDS = (
    "local_per_minute_cents",
    "intrastate_per_minute_cents",
    "interstate_per_minute_cents",
    "international_per_minute_cents",
)


def schedule_or_404(schedule_id):
    schedule = DB.schedules.get(schedule_id)
    if schedule is None:
        err("ERR_RATE_SCHEDULE_NOT_FOUND", 404,
            "RateSchedule %s does not exist" % schedule_id)
    return schedule


@bp.get("/comm-services/rate-schedules/<schedule_id>")
def get_schedule(schedule_id):
    auth(ALL_ROLES)
    return ok_obj(pub(schedule_or_404(schedule_id)))


@bp.get("/comm-services/rate-schedules")
def list_schedules():
    auth(ALL_ROLES)
    items = apply_filters(DB.schedules.values(), ["contract_id", "status"])
    return list_response(items, pub)


@bp.post("/comm-services/rate-schedules/<schedule_id>/activate")
def activate_schedule(schedule_id):
    auth(["PlatformAdmin"])
    data = body()
    expected = req_int(data, "expected_contract_version")
    schedule = schedule_or_404(schedule_id)
    if schedule["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409,
            "Only a DRAFT rate schedule can be activated")
    contract = DB.contracts.get(schedule["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        err("ERR_CONTRACT_NOT_ACTIVE", 409,
            "Schedule activation requires an ACTIVE contract")
    # OCC on the parent contract's version (PRD section 2.7).
    if expected != contract["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_contract_version %s does not match current contract "
            "version %s" % (expected, contract["version"]))
    facility = DB.facilities.get(contract["facility_id"])
    cap = cap_for_facility(facility) if facility is not None else None
    if cap is not None:
        # A price exactly equal to its cap is allowed.
        for name in _PER_MINUTE_FIELDS:
            if schedule[name] > cap["max_per_minute_cents"]:
                err("ERR_RATE_EXCEEDS_CAP", 409,
                    "%s exceeds max_per_minute_cents" % name)
        if schedule["connection_fee_cents"] > cap["max_connection_fee_cents"]:
            err("ERR_RATE_EXCEEDS_CAP", 409,
                "connection_fee_cents exceeds max_connection_fee_cents")
        if schedule["message_price_cents"] > cap["max_ancillary_fee_cents"]:
            err("ERR_RATE_EXCEEDS_CAP", 409,
                "message_price_cents exceeds max_ancillary_fee_cents")
        if schedule["video_session_fee_cents"] > cap["max_ancillary_fee_cents"]:
            err("ERR_RATE_EXCEEDS_CAP", 409,
                "video_session_fee_cents exceeds max_ancillary_fee_cents")
    # Supersede the contract's previously ACTIVE schedule, if any.
    for other in DB.schedules.values():
        if (other["contract_id"] == contract["id"]
                and other["status"] == "ACTIVE"
                and other["id"] != schedule["id"]):
            other["status"] = "SUPERSEDED"
            touch(other)
    schedule["status"] = "ACTIVE"
    schedule["activated_at"] = CLOCK.now()
    touch(schedule)
    touch(contract)  # activation advances FacilityContract.version by one
    return ok_obj(pub(schedule))
