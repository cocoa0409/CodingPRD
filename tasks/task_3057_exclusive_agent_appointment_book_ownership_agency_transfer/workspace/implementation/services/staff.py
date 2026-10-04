"""Team staffing under a sponsoring agreement (PRD §3.5)."""

import clock
import db
import middleware
from errors import (
    ApiError, ERR_AGENCY_STAFFING_CAP, ERR_AGREEMENT_NOT_FOUND, ERR_INTERVAL_OVERLAP,
    ERR_INVALID_STATE, ERR_LICENSED_REQUIRED, ERR_SPONSOR_AGREEMENT_NOT_ACTIVE,
)
from services import calculations as calc
from services import factories, recompute

LIVE_AGENT_STATES = ("ACTIVE", "TRANSITIONING")
MIN_UNITS = 1
MAX_UNITS = 20


def list_staff(request, role=None, user_id=None):
    rows = list(db.staff_rows().values())
    if role == "AgencyPrincipal":
        rows = [r for r in rows if r["agency_id"] == user_id]
    elif role == "StaffMember":
        rows = [r for r in rows if r["id"] == user_id]
    rows = middleware.filter_by(rows, {
        "agency_id": request.args.get("agency_id"),
        "agent_id": request.args.get("agent_id"),
        "sponsoring_agreement_id": request.args.get("sponsoring_agreement_id"),
        "status": request.args.get("status"),
    })
    if request.args.get("agent_id") is not None:
        wanted = request.args.get("agent_id")
        rows = [r for r in rows if r["allocated_agent_id"] == wanted]
    rows.sort(key=lambda s: s["created_at"])
    return rows


def nominate(payload):
    agreement_id = payload.get("sponsoring_agreement_id")
    agreement = db.agreement_rows().get(agreement_id)
    if agreement is None:
        raise ApiError(ERR_AGREEMENT_NOT_FOUND)

    units = payload.get("allocation_units")
    if units is None or int(units) < MIN_UNITS or int(units) > MAX_UNITS:
        raise ApiError("ERR_INVALID_ALLOCATION_UNITS",
                       "allocation_units must be between 1 and 20 inclusive.", 400)

    agent = db.agent_rows().get(agreement["agent_id"])
    _require_live_sponsor(agent)

    _check_overlap(agreement["agent_id"], payload.get("assignment_start_date"),
                   payload.get("assignment_end_date"), exclude_id=None)

    member = factories.create_staff({
        "full_name": payload.get("full_name"),
        "role_title": payload.get("role_title"),
        "allocation_units": units,
        "agency_id": agreement["agency_id"],
        "sponsoring_agreement_id": agreement["id"],
        "allocated_agent_id": agreement["agent_id"],
        "assignment_start_date": payload.get("assignment_start_date"),
        "assignment_end_date": payload.get("assignment_end_date"),
    })
    return member


def appoint(member):
    agreement = db.agreement_rows().get(member["sponsoring_agreement_id"])
    if agreement is None:
        raise ApiError(ERR_AGREEMENT_NOT_FOUND)
    agent = db.agent_rows().get(agreement["agent_id"])

    # The target member's own state is checked before any precondition on the
    # sponsor: a transition out of a terminal member is ERR_ALREADY_TERMINAL
    # (PRD §2.12: state checks precede the business-safety gates).
    if member["status"] != "PENDING":
        if member["status"] == "TERMINATED":
            raise ApiError("ERR_ALREADY_TERMINAL")
        raise ApiError(ERR_INVALID_STATE)

    # Sponsor liveness precedes the licensing requirement (priority 5).
    _require_live_sponsor(agent)

    if agreement["status"] != "ACTIVE":
        raise ApiError(ERR_SPONSOR_AGREEMENT_NOT_ACTIVE)
    if agent is None or agent["status"] != "ACTIVE":
        raise ApiError(ERR_SPONSOR_AGREEMENT_NOT_ACTIVE)

    allocated = db.agent_rows().get(member.get("allocated_agent_id"))
    if allocated is None:
        raise ApiError(ERR_LICENSED_REQUIRED)
    recompute.refresh_license_status(allocated["id"])
    if allocated["license_status"] != "LICENSED":
        raise ApiError(ERR_LICENSED_REQUIRED)

    agency = db.agency_rows().get(member["agency_id"])
    if agency is None:
        raise ApiError("ERR_AGENCY_NOT_FOUND")
    if calc.agency_level_units(agency["id"]) >= calc.AGENCY_UNIT_CAP:
        raise ApiError(ERR_AGENCY_STAFFING_CAP)

    _check_overlap(member.get("allocated_agent_id"), member.get("assignment_start_date"),
                   member.get("assignment_end_date"), exclude_id=member["id"])

    member["status"] = "ACTIVE"
    member["allocated_agent_id"] = allocated["id"]
    recompute.touch(member)

    for agreement_row in recompute.agreements_for(agency["id"]):
        agreement_row["staffing_reimbursement_cents"] = \
            calc.staffing_reimbursement_cents(agency["id"])
        recompute.touch(agreement_row)
    agency["staffing_reimbursement_cents"] = \
        calc.staffing_reimbursement_cents(agency["id"])
    recompute.touch(agency)
    return member


def _require_live_sponsor(agent):
    if agent is None or agent["status"] not in LIVE_AGENT_STATES:
        raise ApiError(ERR_SPONSOR_AGREEMENT_NOT_ACTIVE)


def _check_overlap(owner_key, start, end, exclude_id):
    if start is None or end is None or owner_key is None:
        return
    lo = clock.parse_iso(start)
    hi = clock.parse_iso(end)
    for other in db.staff_rows().values():
        if other["id"] == exclude_id:
            continue
        if other.get("allocated_agent_id") != owner_key:
            continue
        if other["status"] == "TERMINATED":
            continue
        other_start = other.get("assignment_start_date")
        other_end = other.get("assignment_end_date")
        if other_start is None or other_end is None:
            continue
        olo = clock.parse_iso(other_start)
        ohi = clock.parse_iso(other_end)
        # A team member's booked window is a closed interval, so a window that
        # merely touches a sibling's endpoint still collides (PRD §2.10).
        if lo <= ohi and olo <= hi:
            raise ApiError(ERR_INTERVAL_OVERLAP)