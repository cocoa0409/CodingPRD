"""Agency lifecycle: creation, activation, termination and the ops sweep."""

import clock
import db
import middleware
import money
import occ
from errors import (
    ApiError, ERR_DUPLICATE_POLICY, ERR_INVALID_STATE,
)
from services import calculations as calc
from services import factories, ops, recompute

TERMINAL = ("TERMINATED",)


def create(payload):
    code = payload.get("agency_code")
    if code is not None:
        for existing in db.agency_rows().values():
            if existing["agency_code"] == code:
                raise ApiError(ERR_DUPLICATE_POLICY)
    # An agency is created with a unique agency_code, a display name, the
    # region_code that drives successor ranking, and a market_need_score
    # (PRD §3.9); each of those is a required part of the create input.
    for field_name in ("agency_code", "name", "region_code", "market_need_score"):
        value = payload.get(field_name)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            raise ApiError("ERR_INVALID_REQUEST",
                           f"{field_name} is required to create an agency.", 400)
    agency = factories.create_agency(payload)
    # The create endpoint runs recompute_agency; a freshly created record keeps
    # the version it was born with (PRD §2.4: version starts at 1).
    recompute.recompute_agency_soft(agency["id"])
    return agency


def list_agencies(request):
    rows = list(db.agency_rows().values())
    rows = middleware.filter_by(rows, {
        "status": request.args.get("status"),
        "region_code": request.args.get("region_code"),
    })
    rows.sort(key=lambda a: a["created_at"])
    return rows


def activate(agency, expected_version):
    if agency["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    occ.check(agency, expected_version, "expected_agency_version")
    if agency["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE)
    agency["status"] = "ACTIVE"
    agency["term_start_date"] = clock.iso()
    agency["ops_run_index"] = 0
    agency["rolling_base_cents"] = agency.get("rolling_base_cents") or 0
    recompute.touch(agency)
    return agency


def terminate(agency):
    if agency["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agency["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE)

    live = [a for a in db.agent_rows().values()
            if a.get("agency_id") == agency["id"]
            and a["status"] not in ("PENDING_TERMINATION", "TERMINATED")]
    if live:
        raise ApiError(ERR_INVALID_STATE)

    # Cascade: every StaffMember under the agency becomes TERMINATED, which
    # rebuilds agency_level_units and then staffing_reimbursement_cents
    # (PRD §3.9, §3.5).
    recompute.terminate_staff_under_agency(agency["id"])
    agency["status"] = "TERMINATED"
    # Every campaign under the agency is cancelled, and its posture is derived
    # from the agency's now-terminal status.
    for campaign in db.campaign_rows().values():
        if campaign["agency_id"] != agency["id"]:
            continue
        if campaign["status"] != "CANCELLED":
            campaign["status"] = "CANCELLED"
        campaign["participation_posture"] = factories.participation_posture(agency)
        recompute.touch(campaign)

    recompute.recompute_agency_soft(agency["id"])
    recompute.touch(agency)
    return agency


def run_ops(agency):
    if agency["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if agency["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE)
    ops.maybe_promote_ceasing_agents()
    return ops.run_ops(agency["id"])


def performance(agency):
    """A computed read: the snapshot is derived without mutating the record."""
    snap = recompute.snapshot_agency(agency["id"])
    return {
        "book_open_count": snap["book_open_count"],
        "exposure_inforce_cents": money.as_number(snap["exposure_inforce_cents"]),
        "agency_paid_claims_cents": money.as_number(snap["agency_paid_claims_cents"]),
        "loss_ratio": snap["loss_ratio"],
        "growth_new_pct": snap["growth_new_pct"],
        "performance_status": snap["performance_status"],
        "agency_valuation_cents": money.as_number(snap["agency_valuation_cents"]),
    }


def agencies_for_agent(agent):
    return db.agency_rows().get(agent.get("agency_id"))


def unit_cap_reached(agency):
    return calc.agency_level_units(agency["id"]) >= calc.AGENCY_UNIT_CAP