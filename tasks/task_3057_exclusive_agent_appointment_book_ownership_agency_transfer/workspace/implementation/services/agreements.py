"""Agreement drafting and transcription, including the commission lines."""

import clock
import db
import middleware
import occ
from errors import (
    ApiError, ERR_AGENT_NOT_FOUND, ERR_INVALID_STATE, ERR_LICENSED_REQUIRED,
    ERR_SCHEDULE_MISSING,
)
from services import calculations as calc
from services import factories, recompute

TERMINAL = ("TERMINATED",)


def draft(payload):
    agent_id = payload.get("agent_id")
    agency_id = payload.get("agency_id")
    if agent_id is not None and agent_id not in db.agent_rows():
        raise ApiError(ERR_AGENT_NOT_FOUND)

    schedule = payload.get("commission_schedule")
    if not calc.schedule_complete(schedule):
        raise ApiError(ERR_SCHEDULE_MISSING)

    agreement = factories.create_agreement({
        "agent_id": agent_id,
        "agency_id": agency_id,
        "agreement_type": payload.get("agreement_type"),
        "commission_schedule": schedule,
    })
    return agreement


def list_agreements(request, role=None, user_id=None):
    rows = list(db.agreement_rows().values())
    if role == "AgencyPrincipal":
        rows = [a for a in rows if a.get("agency_id") == user_id]
    rows = middleware.filter_by(rows, {
        "agent_id": request.args.get("agent_id"),
        "agency_id": request.args.get("agency_id"),
        "status": request.args.get("status"),
    })
    rows.sort(key=lambda a: a["created_at"])
    return rows


def transcribe(agreement, expected_agent_version):
    agent = db.agent_rows().get(agreement["agent_id"])
    if agent is None:
        raise ApiError(ERR_AGENT_NOT_FOUND)

    # OCC first: a stale expected_agent_version refuses before anything else.
    occ.check(agent, expected_agent_version, "expected_agent_version")

    if agreement["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agreement["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE)

    if agent["status"] != "TRANSITIONING":
        raise ApiError(ERR_INVALID_STATE)

    recompute.refresh_license_status(agent["id"])
    if agent["license_status"] != "LICENSED":
        raise ApiError(ERR_LICENSED_REQUIRED)

    if agreement.get("agreement_type") != "EXCLUSIVE_AGENT":
        raise ApiError(ERR_INVALID_STATE)

    if not calc.schedule_complete(agreement.get("commission_schedule")):
        raise ApiError(ERR_SCHEDULE_MISSING)

    agent["appointment_date"] = clock.iso()
    agent["status"] = "ACTIVE"
    recompute.refresh_agent_is_new(agent["id"])
    recompute.touch(agent)

    agreement["status"] = "ACTIVE"
    agreement["license_verified_at"] = clock.iso()
    recompute.touch(agreement)

    agency_id = agreement["agency_id"] or agent.get("agency_id")
    if agency_id:
        agency = db.agency_rows().get(agency_id)
        if agency is not None:
            _rebuild_agency_roll(agency)
    return agreement


def _rebuild_agency_roll(agency):
    """Recompute the agency roll (book counts, exposure, commission) and the
    three commission lines the transcription pins (PRD §3.3)."""
    recompute.recompute_agency(agency["id"])
    agreements = recompute.agreements_for(agency["id"])
    if not agreements:
        return
    agreement = agreements[0]
    schedule = agreement.get("commission_schedule")
    agreement["direct_additions_commission_cents"] = \
        calc.direct_additions_commission_cents(agency["id"], schedule)
    agreement["renewal_commission_cents"] = \
        calc.renewal_commission_cents(agency["id"], schedule)
    agreement["direct_additions_revenue_cents"] = \
        calc.direct_additions_revenue_cents(agency["id"], schedule)
    # The trailing term commission carries the established book for the term.
    agency["annualized_commission_cents"] = (
        agreement["direct_additions_commission_cents"]
        + agreement["renewal_commission_cents"])
    agency["rolling_base_cents"] = agency.get("rolling_base_cents") or 0
    recompute.recompute_agency(agency["id"])