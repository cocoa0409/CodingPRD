"""BuydownCostRecord endpoints: recognition, recapture and the cure deadline."""

from flask import Blueprint

from db import db
from errors import fail
from response import ok
from checks import (
    authenticate, body, require_fields, int_field, get_contract, get_buydown,
    get_allocation, check_contract_version, require_state,
)
from services import common, calc

bp = Blueprint("buydowns", __name__)

DETAIL_ROLES = ["PlatformAdmin", "ClosingOfficer", "ComplianceOfficer"]
CREATE_ROLES = ["ClosingOfficer", "SalesCounselor"]


@bp.post("/housing/contracts/<contract_id>/buydown-records")
def create_buydown_record(contract_id):
    authenticate(CREATE_ROLES)
    contract = get_contract(contract_id)
    payload = body()
    require_fields(payload, ["allocation_id", "gross_buydown_cents", "expected_contract_version"])

    # Priority 3: path, then body foreign keys left to right.
    if contract.get("contract_status") not in ("PENDING", "LOCKED"):
        fail("ERR_INVALID_STATE", "the contract is not PENDING or LOCKED")
    allocation = get_allocation(payload["allocation_id"])
    if allocation.get("contract_id") != contract_id:
        fail("ERR_RESOURCE_NOT_FOUND", "the allocation belongs to another contract")
    if allocation.get("bucket") != "RATE_BUYDOWN":
        fail("ERR_INVALID_ENUM_VALUE", "the allocation is not a RATE_BUYDOWN bucket")
    require_state(allocation, "allocation_status", {"RESERVED", "APPLIED"})

    community = common.community_of(contract)
    if community is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the contract has no community")
    if community.get("program_status") == "SUSPENDED":
        fail("ERR_COMMUNITY_SUSPENDED", "the community is suspended")

    # Priority 20: gross buydown must fit the linked allocation.
    gross = int_field(payload, "gross_buydown_cents", minimum=1)
    if gross > int(allocation.get("allocation_total_cents") or 0):
        fail(
            "ERR_BUYDOWN_EXCEEDS_ALLOCATION",
            "gross_buydown_cents exceeds the linked allocation total",
        )

    # Priority 23: optimistic concurrency on the contract.
    check_contract_version(payload, contract)

    row = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "allocation_id": allocation["id"],
        "gross_buydown_cents": gross,
        "recapture_credit_cents": 0,
        "allowed_buydown_cost_cents": 0,
        "aba_cure_deadline_iso": calc.aba_disclosure_cure_deadline_offset(contract_id),
        "record_status": "DRAFT",
    }
    common.stamp_new(row)
    db.buydown_records[row["id"]] = row
    calc.buydown_cost_recognition(row, contract)
    common.touch(contract)
    return ok(common.dump(row), 201)


@bp.get("/housing/buydown-records/<buydown_id>")
def get_buydown_detail(buydown_id):
    authenticate(DETAIL_ROLES)
    record = get_buydown(buydown_id)
    contract = db.contracts.get(record.get("contract_id"))
    # buydown_cost_recognition re-runs on every read.
    calc.buydown_cost_recognition(record, contract)
    return ok(common.dump(record), 200)