"""IncentiveAllocation endpoints: the bucket waterfall and its OCC guard."""

from flask import Blueprint, request

from db import db, PRIORITY_ORDER
from errors import fail
from response import ok, ok_list, paginate
from checks import (
    authenticate, body, require_fields, int_field, enum_field, get_contract,
    get_allocation, check_contract_version, require_state,
)
from services import common, calc, selectors
from services import contract_flows

bp = Blueprint("allocations", __name__)

READ_ROLES = [
    "PlatformAdmin",
    "SalesCounselor",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
]


@bp.post("/housing/contracts/<contract_id>/incentive-allocations")
def create_allocation(contract_id):
    authenticate(["SalesCounselor"])
    contract = get_contract(contract_id)
    payload = body()
    require_fields(payload, ["bucket", "requested_cents", "expected_contract_version"])
    bucket = enum_field(payload, "bucket", PRIORITY_ORDER)
    requested_cents = int_field(payload, "requested_cents", minimum=1)

    # Priority 4: the contract must be in a state that permits the transition.
    if contract.get("contract_status") not in ("PENDING", "LOCKED"):
        fail("ERR_INVALID_STATE", "the contract is not PENDING or LOCKED")

    community = common.community_of(contract)
    if community is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the contract has no community")
    # Priority 10: the community must not be suspended.
    if community.get("program_status") == "SUSPENDED":
        fail("ERR_COMMUNITY_SUSPENDED", "the community is suspended")

    # Priority 6: a rate-buydown obligation needs an acknowledged ABA disclosure.
    if bucket == "RATE_BUYDOWN" and not common.has_acknowledged_disclosure(
        contract_id, "AFFILIATED_BUSINESS_ARRANGEMENT"
    ):
        fail(
            "ERR_ABA_DISCLOSURE_MISSING",
            "a rate-buydown allocation requires an ACKNOWLEDGED affiliated-business disclosure",
        )

    # Priority 19: the request must fit the three remaining caps.
    remaining = calc.remaining_caps(community, contract)
    if requested_cents > calc.total_remaining_caps(remaining):
        fail(
            "ERR_INCENTIVE_BUDGET_EXHAUSTED",
            "requested_cents exceeds the sum of the remaining bucket caps",
        )

    # Priority 23: optimistic concurrency on the contract.
    check_contract_version(payload, contract)

    granted, spill_to_bucket = calc.incentive_allocation_waterfall(
        community, contract, bucket, requested_cents
    )

    row = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "bucket": bucket,
        "requested_cents": requested_cents,
        "allocation_total_cents": granted,
        "spill_to_bucket": spill_to_bucket,
        "allocation_status": "RESERVED",
    }
    common.stamp_new(row)
    db.incentive_allocations[row["id"]] = row

    common.recompute_contract_incentive_allocated(contract)
    common.touch(contract)

    if bucket == "RATE_BUYDOWN":
        for rec in contract_flows.buydowns_for_allocation(row["id"]):
            calc.buydown_cost_recognition(rec, contract)
            common.touch(rec)
    return ok(common.dump(row), 201)


@bp.get("/housing/incentive-allocations/<allocation_id>")
def get_allocation_detail(allocation_id):
    authenticate(READ_ROLES)
    allocation = get_allocation(allocation_id)
    return ok(common.dump(allocation), 200)


@bp.get("/housing/incentive-allocations/<allocation_id>/buydown-records")
def list_allocation_buydowns(allocation_id):
    authenticate(["PlatformAdmin", "SalesCounselor", "ClosingOfficer", "ComplianceOfficer"])
    get_allocation(allocation_id)
    rows = contract_flows.buydowns_for_allocation(allocation_id)
    window, pagination = paginate(
        common.sort_rows(rows), request.args.get("limit"), request.args.get("offset")
    )
    return ok_list(common.dump_all(window), 200, pagination)