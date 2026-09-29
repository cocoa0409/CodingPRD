"""Prize money: the waterfall, its sign-off and its undoing (PRD section 3.8)."""

from flask import Blueprint

import calc
import db
import response
import serializers as ser
import validation as v
from auth import endpoint, caller, require_org_owner
from db import store
from errors import fail

bp = Blueprint("prizes", __name__)

DISTRIBUTION_STATES = ("DRAFT", "CALCULATED", "APPROVED", "VOIDED")
ALLOCATION_STATES = ("CALCULATED", "APPROVED", "VOIDED")


@bp.post("/prize-distributions")
@endpoint(["FinanceOfficer"])
def create_distribution():
    payload = v.body()
    organization_id = v.req_str(payload, "organization_id")
    league_id = v.req_str(payload, "league_id")
    tournament_name = v.req_str(payload, "tournament_name", 1, 120)
    placement = v.req_int(payload, "placement", 1)
    gross_prize_cents = v.req_int(payload, "gross_prize_cents", 0)
    tournament_end_at = v.req_instant(payload, "tournament_end_at")

    # Band 6 resolves league_id before organization_id, per the §2.6 listing.
    v.find_league(league_id)
    organization = v.find_organization(organization_id)

    record = {
        "organization_id": organization["id"],
        "league_id": league_id,
        "tournament_name": tournament_name,
        "placement": placement,
        "gross_prize_cents": gross_prize_cents,
        "tournament_end_at": tournament_end_at,
        "distribution_status": "DRAFT",
        "association_levy_cents": 0,
        "org_share_cents": 0,
        "allocated_cents": 0,
        "unallocated_cents": gross_prize_cents,
        "withholding_total_cents": 0,
        "escrow_total_cents": 0,
        "calculated_by_user_id": None,
        "approved_by_user_id": None,
        "void_reason": None,
    }
    db.insert(store.distributions, record)
    return response.object_response(ser.distribution(record), 201)


@bp.get("/prize-distributions/<distribution_id>")
@endpoint(["LeagueAdmin", "GeneralManager", "FinanceOfficer"])
def read_distribution(distribution_id):
    record = v.find_distribution(distribution_id)
    require_org_owner(record["organization_id"])
    return response.object_response(ser.distribution(record))


@bp.get("/prize-distributions")
@endpoint(["LeagueAdmin", "GeneralManager", "FinanceOfficer"])
def list_distributions():
    limit, offset = response.pagination()
    organization_id = v.str_filter("organization_id")
    league_id = v.str_filter("league_id")
    status = v.enum_filter("distribution_status", DISTRIBUTION_STATES)
    records = list(store.distributions.values())
    if organization_id is not None:
        records = [d for d in records if d["organization_id"] == organization_id]
    if league_id is not None:
        records = [d for d in records if d["league_id"] == league_id]
    if status is not None:
        records = [d for d in records if d["distribution_status"] == status]
    return response.paginated(db.in_creation_order(records), ser.distribution, limit, offset)


@bp.post("/prize-distributions/<distribution_id>/calculate")
@endpoint(["FinanceOfficer"])
def calculate_distribution(distribution_id):
    record = v.find_distribution(distribution_id)
    if record["distribution_status"] != "DRAFT":
        fail("ERR_DISTRIBUTION_NOT_DRAFT")
    organization = store.organizations[record["organization_id"]]
    league = store.leagues[record["league_id"]]
    if not calc.eligible_prize_contracts(record):
        fail("ERR_NO_ELIGIBLE_CONTRACTS")

    totals, rows = calc.prize_waterfall(record, league, organization)
    user_id, _role = caller()
    record.update(totals)
    record["distribution_status"] = "CALCULATED"
    record["calculated_by_user_id"] = user_id
    db.touch(record)

    for row in rows:
        allocation = {
            "prize_distribution_id": record["id"],
            "contract_id": row["contract"]["id"],
            "weight_bp": row["weight_bp"],
            "gross_share_cents": row["gross_share_cents"],
            "withholding_rate_bp": row["withholding_rate_bp"],
            "withholding_cents": row["withholding_cents"],
            "escrow_holdback_cents": row["escrow_holdback_cents"],
            "net_cents": row["net_cents"],
            "allocation_status": "CALCULATED",
        }
        db.insert(store.allocations, allocation)

    # prize_payable_cents is derived from CALCULATED and APPROVED distributions, so the
    # org_share is already counted; the organization is versioned for the cascade.
    db.touch(organization)
    return response.object_response(ser.distribution(record))


@bp.post("/prize-distributions/<distribution_id>/approve")
@endpoint(["LeagueAdmin"])
def approve_distribution(distribution_id):
    record = v.find_distribution(distribution_id)
    if record["distribution_status"] != "CALCULATED":
        fail("ERR_DISTRIBUTION_NOT_CALCULATED")
    user_id, _role = caller()
    if user_id == record["calculated_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    record["distribution_status"] = "APPROVED"
    record["approved_by_user_id"] = user_id
    db.touch(record)
    for allocation in db.in_creation_order(list(store.allocations.values())):
        if allocation["prize_distribution_id"] != record["id"]:
            continue
        if allocation["allocation_status"] != "CALCULATED":
            continue
        allocation["allocation_status"] = "APPROVED"
        db.touch(allocation)
    return response.object_response(ser.distribution(record))


@bp.post("/prize-distributions/<distribution_id>/void")
@endpoint(["FinanceOfficer"])
def void_distribution(distribution_id):
    record = v.find_distribution(distribution_id)
    payload = v.body()
    void_reason = v.req_str(payload, "void_reason", 1)
    if record["distribution_status"] not in ("CALCULATED", "APPROVED"):
        fail("ERR_DISTRIBUTION_NOT_CALCULATED")

    record["void_reason"] = void_reason
    record["distribution_status"] = "VOIDED"
    # The ledger is wound back to its pre-calculation shape exactly.
    record["association_levy_cents"] = 0
    record["org_share_cents"] = 0
    record["allocated_cents"] = 0
    record["withholding_total_cents"] = 0
    record["escrow_total_cents"] = 0
    record["unallocated_cents"] = record["gross_prize_cents"]
    db.touch(record)

    for allocation in db.in_creation_order(list(store.allocations.values())):
        if allocation["prize_distribution_id"] != record["id"]:
            continue
        if allocation["allocation_status"] == "VOIDED":
            continue
        allocation["allocation_status"] = "VOIDED"
        db.touch(allocation)

    organization = store.organizations.get(record["organization_id"])
    if organization is not None:
        db.touch(organization)
    return response.object_response(ser.distribution(record))


@bp.get("/prize-distributions/<distribution_id>/allocations")
@endpoint(["LeagueAdmin", "PlayerAgent", "FinanceOfficer"])
def list_distribution_allocations(distribution_id):
    record = v.find_distribution(distribution_id)
    limit, offset = response.pagination()
    status = v.enum_filter("allocation_status", ALLOCATION_STATES)
    records = [a for a in store.allocations.values()
               if a["prize_distribution_id"] == record["id"]]
    if status is not None:
        records = [a for a in records if a["allocation_status"] == status]
    return response.paginated(db.in_creation_order(records), ser.allocation, limit, offset)
