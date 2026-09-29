"""Household intake, follow-up contacts and the effectiveness cascade."""

from flask import Blueprint, g

import db
import domain
import response
import util
import validation
from db import store, touch
from errors import ApiError
from middleware import endpoint
from services import households as household_service
from services import zones as zone_service

bp = Blueprint("households", __name__)

READ_ROLES = ("ProgramAdmin", "RiskAnalyst", "CanvassCoordinator", "CrrTechnician")


def load_household(household_id):
    household = store.households.get(household_id)
    if household is None:
        raise ApiError("ERR_HOUSEHOLD_NOT_FOUND")
    return household


@bp.post("/crr/households")
@endpoint("CanvassCoordinator")
def create_household():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    zone_id = validation.req_str(body, "zone_id")
    address_line = validation.req_str(body, "address_line")
    occupant_count = validation.req_int(body, "occupant_count", minimum=1)
    sleeping_areas_count = validation.req_int(body, "sleeping_areas_count", minimum=1)
    storeys = validation.req_int(body, "storeys", minimum=1)
    children_under5 = validation.opt_int(body, "children_under5", default=0, minimum=0)
    adults_65plus = validation.opt_int(body, "adults_65plus", default=0, minimum=0)
    mobility_impaired_occupants = validation.opt_int(
        body, "mobility_impaired_occupants", default=0, minimum=0
    )
    hearing_impaired_occupants = validation.opt_int(
        body, "hearing_impaired_occupants", default=0, minimum=0
    )
    fuel_burning_appliance = validation.opt_bool(
        body, "fuel_burning_appliance", default=False
    )
    attached_garage = validation.opt_bool(body, "attached_garage", default=False)
    preferred_language = validation.opt_str(body, "preferred_language", default="EN")
    referral_partner_id = validation.opt_str(
        body, "referral_partner_id", non_empty=True
    )

    zone = store.zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")
    partner = None
    if referral_partner_id is not None:
        partner = store.partners.get(referral_partner_id)
        if partner is None:
            raise ApiError("ERR_PARTNER_NOT_FOUND")

    for existing in store.households.values():
        if existing["zone_id"] == zone_id and existing["address_line"] == address_line:
            raise ApiError("ERR_DUPLICATE_HOUSEHOLD_ADDRESS")

    row = db.stamp_new({})
    household = {
        "id": row["id"],
        "zone_id": zone_id,
        "address_line": address_line,
        "occupant_count": occupant_count,
        "sleeping_areas_count": sleeping_areas_count,
        "storeys": storeys,
        "children_under5": children_under5,
        "adults_65plus": adults_65plus,
        "mobility_impaired_occupants": mobility_impaired_occupants,
        "hearing_impaired_occupants": hearing_impaired_occupants,
        "fuel_burning_appliance": fuel_burning_appliance,
        "attached_garage": attached_garage,
        "preferred_language": preferred_language,
        "referral_partner_id": referral_partner_id,
        "required_smoke_devices": 0,
        "required_co_devices": 0,
        "required_strobe_devices": 0,
        "priority_band": None,
        "status": "INTAKE_QUEUED",
        "canvass_attempt_count": 0,
        "alarm_retention_flag": None,
        "last_visit_completed_at": None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    household_service.device_requirements(household)
    household["priority_band"] = zone_service.priority_band(household, zone)
    store.households[household["id"]] = household

    if partner is not None:
        # PRD 3.3: a partner referral moves the partner's counter.
        partner["referral_count"] = partner["referral_count"] + 1
        touch(partner)
    return response.ok_row(household, 201)


@bp.get("/crr/households")
@endpoint(*READ_ROLES)
def list_households():
    limit, offset = validation.pagination()
    rows = db.by_created_at(list(store.households.values()))
    for name in ("zone_id", "referral_partner_id", "status", "priority_band"):
        wanted = validation.filter_value(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/households/<household_id>")
@endpoint(*READ_ROLES)
def get_household(household_id):
    return response.ok_row(load_household(household_id))


@bp.get("/crr/households/<household_id>/follow-ups")
@endpoint("ProgramAdmin", "RiskAnalyst", "CanvassCoordinator")
def list_household_follow_ups(household_id):
    load_household(household_id)
    limit, offset = validation.pagination()
    rows = household_service.follow_ups_of(household_id)
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.post("/crr/follow-ups")
@endpoint("CanvassCoordinator")
def create_follow_up():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    household_id = validation.req_str(body, "household_id")
    contact_method = validation.req_enum(body, "contact_method", domain.CONTACT_METHODS)
    outcome = validation.req_enum(body, "outcome", domain.FOLLOWUP_OUTCOMES)
    if outcome == "REACHED_ALARM_PRESENT":
        # PRD 3.7: both optional fields become required on this outcome.
        alarms_present_count = validation.req_int(
            body, "alarms_present_count", minimum=0
        )
        plan_practiced = validation.req_bool(body, "plan_practiced")
    else:
        alarms_present_count = validation.opt_int(
            body, "alarms_present_count", minimum=0
        )
        plan_practiced = validation.opt_bool(body, "plan_practiced")

    household = store.households.get(household_id)
    if household is None:
        raise ApiError("ERR_HOUSEHOLD_NOT_FOUND")

    if household["status"] not in ("VISIT_COMPLETED", "REVISIT_REQUIRED"):
        raise ApiError("ERR_INVALID_HOUSEHOLD_STATE")

    last_completed = household["last_visit_completed_at"]
    if last_completed is None:
        days_since_visit = 0
    else:
        days_since_visit = util.whole_days_between(last_completed, util.clock.now())
    if days_since_visit < domain.FOLLOWUP_MIN_DAYS:
        raise ApiError("ERR_FOLLOWUP_TOO_EARLY")

    attempt_no = len(household_service.follow_ups_of(household_id)) + 1
    row = db.stamp_event({})
    follow_up = {
        "id": row["id"],
        "household_id": household_id,
        "attempt_no": attempt_no,
        "contact_method": contact_method,
        "outcome": outcome,
        "alarms_present_count": alarms_present_count,
        "plan_practiced": plan_practiced,
        "days_since_visit": days_since_visit,
        "contacted_by_user_id": g.user_id,
        "created_at": row["created_at"],
        "_seq": row["_seq"],
    }
    store.follow_ups[follow_up["id"]] = follow_up

    _apply_follow_up_consequences(household, outcome, plan_practiced)
    return response.ok_row(follow_up, 201)


def _lapse_plan(plan, lapse_reason):
    plan["status"] = "LAPSED"
    plan["lapse_reason"] = lapse_reason
    plan["lapsed_at"] = util.clock.now()
    touch(plan)


def _apply_follow_up_consequences(household, outcome, plan_practiced):
    """The four outcome branches of PRD 3.7."""
    if outcome in ("NO_ANSWER", "REFUSED"):
        # No state change anywhere beyond the appended row.
        return

    plan = household_service.live_plan_of(household["id"])

    if outcome == "REACHED_ALARM_MISSING":
        household["status"] = "REVISIT_REQUIRED"
        household["alarm_retention_flag"] = False
        touch(household)
        if plan is not None and plan["status"] in ("ISSUED", "VERIFIED"):
            _lapse_plan(plan, "ALARM_MISSING_AT_FOLLOW_UP")
        zone = household_service.zone_of(household)
        if zone is not None:
            zone_service.rescore_after_alarm_loss(zone)
            zone_service.reevaluate_service_state(zone)
        return

    household["alarm_retention_flag"] = True
    touch(household)
    if plan is not None and plan["status"] == "ISSUED":
        if plan_practiced:
            plan["status"] = "VERIFIED"
            plan["verified_at"] = util.clock.now()
            touch(plan)
        else:
            _lapse_plan(plan, "DRILL_NOT_PRACTICED")
