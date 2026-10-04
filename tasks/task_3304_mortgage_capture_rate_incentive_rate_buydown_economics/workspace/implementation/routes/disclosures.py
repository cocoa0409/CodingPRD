"""ABADisclosure endpoints: delivery, acknowledgement and officer waiver."""

from flask import Blueprint, request

from db import db, parse_iso
from errors import fail
from response import ok
from checks import (
    authenticate, body, require_fields, enum_field, get_contract, get_disclosure,
    require_state,
)
from services import common, calc, cascades
from services import contract_flows

bp = Blueprint("disclosures", __name__)

READ_ROLES = [
    "PlatformAdmin",
    "SalesCounselor",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
    "Buyer",
]
DISCLOSURE_TYPES = [
    "AFFILIATED_BUSINESS_ARRANGEMENT",
    "STEERING_PROHIBITION",
    "RATE_BUYDOWN_TERMS",
]


@bp.post("/housing/contracts/<contract_id>/disclosures")
def create_disclosure(contract_id):
    authenticate(["ComplianceOfficer", "SalesCounselor"])
    contract = get_contract(contract_id)
    payload = body()
    require_fields(payload, ["disclosure_type"])
    disclosure_type = enum_field(payload, "disclosure_type", DISCLOSURE_TYPES)

    row = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "disclosure_type": disclosure_type,
        "delivery_iso": db.clock,
        "cure_deadline_iso": calc.disclosure_cure_deadline(db.clock),
        "disclosure_status": "ISSUED",
    }
    common.stamp_new(row)
    db.disclosures[row["id"]] = row
    buyer = cascades.buyer_of_contract(contract)
    cascades.refresh_buyer(buyer)
    return ok(common.dump(row), 201)


@bp.get("/housing/disclosures/<disclosure_id>")
def get_disclosure_detail(disclosure_id):
    authenticate(READ_ROLES)
    disclosure = get_disclosure(disclosure_id)
    contract = db.contracts.get(disclosure.get("contract_id"))
    if request.headers.get("X-User-Role") == "Buyer":
        if contract is None or contract.get("buyer_id") != request.headers.get("X-User-ID"):
            fail("ERR_FORBIDDEN", "the buyer may only read their own disclosures")
    return ok(common.dump(disclosure), 200)


@bp.post("/housing/disclosures/<disclosure_id>/acknowledge")
def acknowledge_disclosure(disclosure_id):
    authenticate(["Buyer"])
    disclosure = get_disclosure(disclosure_id)
    contract = db.contracts.get(disclosure.get("contract_id"))
    if contract is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the disclosure has no parent contract")
    if contract.get("buyer_id") != request.headers.get("X-User-ID"):
        fail("ERR_FORBIDDEN", "the buyer may only acknowledge their own disclosures")
    if disclosure.get("disclosure_status") not in ("ISSUED", "CURING"):
        fail("ERR_INVALID_STATE", "the disclosure is not in a state that may be acknowledged")
    # A lapse into CURING is not curable by the buyer.
    if parse_iso(db.clock) > parse_iso(disclosure.get("cure_deadline_iso")):
        fail("ERR_ABA_DISCLOSURE_CURE_EXPIRED", "the cure window has already closed")
    disclosure["disclosure_status"] = "ACKNOWLEDGED"
    common.touch(disclosure)
    buyer = cascades.buyer_of_contract(contract)
    cascades.refresh_buyer(buyer)
    return ok(common.dump(disclosure), 200)


@bp.post("/housing/disclosures/<disclosure_id>/waive")
def waive_disclosure(disclosure_id):
    authenticate(["ComplianceOfficer"])
    disclosure = get_disclosure(disclosure_id)
    require_state(disclosure, "disclosure_status", {"CURING"})
    contract = db.contracts.get(disclosure.get("contract_id"))
    if contract is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the disclosure has no parent contract")
    community = common.community_of(contract)
    if community is None or community.get("program_status") != "SUSPENDED":
        fail("ERR_INVALID_STATE", "the owning community is not SUSPENDED")
    disclosure["disclosure_status"] = "WAIVED"
    disclosure["officer_waived"] = True
    common.touch(disclosure)
    buyer = cascades.buyer_of_contract(contract)
    cascades.refresh_buyer(buyer)
    return ok(common.dump(disclosure), 200)