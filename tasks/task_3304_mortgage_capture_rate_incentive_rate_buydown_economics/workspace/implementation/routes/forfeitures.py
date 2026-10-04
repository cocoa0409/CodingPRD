"""DepositForfeiture endpoints: proposal and finalisation."""

from flask import Blueprint

from db import db, parse_iso
from errors import fail
from response import ok
from checks import (
    authenticate, body, require_fields, enum_field, get_contract, get_forfeiture,
    check_contract_version, require_state,
)
from services import common, calc, cascades

bp = Blueprint("forfeitures", __name__)

DETAIL_ROLES = ["PlatformAdmin", "ClosingOfficer", "ComplianceOfficer"]
STATUTE_CLASSES = ["FULL_FORFEITURE", "PARTIAL_FORFEITURE", "RESTITUTION_REQUIRED"]


@bp.post("/housing/contracts/<contract_id>/deposit-forfeitures")
def create_forfeiture(contract_id):
    authenticate(["ClosingOfficer"])
    contract = get_contract(contract_id)
    payload = body()
    require_fields(payload, ["statute_class", "expected_contract_version"])
    statute_class = enum_field(payload, "statute_class", STATUTE_CLASSES)

    # Priority 4: a settlement may only attach to a cancelled contract.
    if contract.get("contract_status") != "CANCELLED":
        fail("ERR_INVALID_STATE", "the contract is not CANCELLED")

    check_contract_version(payload, contract)

    forfeited, refunded, retained = calc.deposit_forfeiture_split(contract, statute_class)
    row = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "statute_class": statute_class,
        "forfeited_cents": forfeited,
        "refunded_cents": refunded,
        "retained_incentive_cents": retained,
        "forfeiture_status": "PROPOSED",
    }
    common.stamp_new(row)
    db.deposit_forfeitures[row["id"]] = row
    common.touch(contract)
    return ok(common.dump(row), 201)


@bp.get("/housing/deposit-forfeitures/<forfeiture_id>")
def get_forfeiture_detail(forfeiture_id):
    authenticate(DETAIL_ROLES)
    row = get_forfeiture(forfeiture_id)
    return ok(common.dump(row), 200)


@bp.post("/housing/deposit-forfeitures/<forfeiture_id>/finalize")
def finalize_forfeiture(forfeiture_id):
    authenticate(["ClosingOfficer"])
    row = get_forfeiture(forfeiture_id)
    if row.get("forfeiture_status") != "PROPOSED":
        fail("ERR_FORFEITURE_NOT_PROPOSED", "the settlement is not PROPOSED")
    contract = db.contracts.get(row.get("contract_id"))
    if contract is None or contract.get("contract_status") != "CANCELLED":
        fail("ERR_FORFEITURE_NOT_PROPOSED", "the owning contract is not CANCELLED")

    # Priority 21: the settlement must conserve the deposit.
    if int(row.get("forfeited_cents") or 0) + int(row.get("refunded_cents") or 0) != int(
        contract.get("earnest_money_cents") or 0
    ):
        fail("ERR_DEPOSIT_SUM_MISMATCH", "the settlement does not conserve the deposit")

    # A blocking open cure window on a rate-buydown obligation must have elapsed.
    if not _cure_window_open(contract):
        pass
    else:
        fail(
            "ERR_FORFEITURE_NOT_PROPOSED",
            "a blocking rate-buydown cure window is still unexpired",
        )

    row["forfeiture_status"] = "FINALIZED"
    common.touch(row)
    contract["deposit_held_cents"] = int(row.get("forfeited_cents") or 0)
    common.touch(contract)

    buyer = cascades.buyer_of_contract(contract)
    if buyer is not None:
        buyer["buyer_status"] = "WITHDRAWN"
        cascades.refresh_buyer(buyer)
    return ok(common.dump(row), 200)


def _cure_window_open(contract):
    """True while any unacknowledged disclosure on the contract is still inside its window."""
    for disc in common.disclosures_of_contract(contract["id"]):
        if disc.get("disclosure_status") not in ("ISSUED", "CURING"):
            continue
        deadline = disc.get("cure_deadline_iso")
        if deadline is not None and parse_iso(db.clock) <= parse_iso(deadline):
            return True
    return False