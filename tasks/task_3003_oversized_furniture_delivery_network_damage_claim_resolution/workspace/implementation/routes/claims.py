"""Damage claims and chargebacks: inspection, triage, liability, settlement,
dispute/reversal."""
from flask import Blueprint, request

from db import db, new_id
from errors import (
    err_chargeback_open,
    err_claim_requires_inspectable_shipment,
    err_forbidden,
    err_invalid_request,
    err_invalid_state,
)
from middleware import require_roles
from response import success
from services import calculations as calc
from services import supplier_metrics
from services.common import get_or_404, list_response, stamp_new, touch
from validation import get_body, req_bool, req_enum, req_int, req_string

bp = Blueprint("claims", __name__)


def _claim_for_chargeback(chargeback):
    for c in db.damage_claims.values():
        if c["id"] == chargeback["damage_claim_id"]:
            return c
    return None


def _chargeback_for_claim(claim_id):
    for cb in db.chargebacks.values():
        if cb["damage_claim_id"] == claim_id:
            return cb
    return None


# --- Damage claims ------------------------------------------------------------

@bp.post("/damage-claims")
@require_roles("Customer", "HubOperator")
def create_damage_claim():
    body = get_body(request)
    raw_shipment_id = body.get("shipment_id")
    shipment = get_or_404(db.shipments, raw_shipment_id if isinstance(raw_shipment_id, str) else None)
    claimant_role = req_enum(body, "claimant_role", {"CUSTOMER", "HUB_INSPECTOR"})
    concealment = req_enum(body, "concealment", {"CONCEALED", "VISIBLE_AT_DELIVERY"})
    item = db.items.get(shipment["item_id"])
    replacement_snapshot = item["declared_value_cents"] if item is not None else 0
    claim = stamp_new(
        {
            "id": new_id(),
            "shipment_id": shipment["id"],
            "claimant_role": claimant_role,
            "concealment": concealment,
            "damage_pct": None,
            "is_structural": None,
            "repair_cost_cents": None,
            "replacement_cost_cents": replacement_snapshot,
            "resolution_type": None,
            "liability_party": None,
            "chargeback_amount_cents": 0,
            "status": "OPEN",
        }
    )
    db.damage_claims[claim["id"]] = claim
    return success(claim, status=201)


_CLAIM_STATES = {"OPEN", "INSPECTION", "DETERMINATION", "SETTLED", "WITHDRAWN"}


@bp.get("/damage-claims")
@require_roles("NetworkAdmin", "ClaimsAdjuster", "HubOperator", "Customer")
def list_damage_claims():
    return list_response(
        db.damage_claims,
        [
            ("shipment_id", "shipment_id", None),
            ("status", "status", _CLAIM_STATES),
        ],
    )


@bp.get("/damage-claims/<claimId>")
@require_roles("NetworkAdmin", "ClaimsAdjuster", "HubOperator", "Customer")
def get_damage_claim(claimId):
    return success(get_or_404(db.damage_claims, claimId))


@bp.post("/damage-claims/<claimId>/inspect")
@require_roles("HubOperator")
def inspect_claim(claimId):
    claim = get_or_404(db.damage_claims, claimId)
    body = get_body(request)
    damage_pct = req_int(body, "damage_pct")
    is_structural = req_bool(body, "is_structural")
    repair_cost = req_int(body, "repair_cost_cents")
    if damage_pct < 0 or damage_pct > 100:
        raise err_invalid_request("damage_pct must be between 0 and 100")
    if repair_cost < 0:
        raise err_invalid_request("repair_cost_cents must be >= 0")
    if claim["status"] != "OPEN":
        raise err_invalid_state("Claim must be OPEN to inspect")
    shipment = db.shipments.get(claim["shipment_id"])
    if shipment is None or shipment["current_state"] not in ("AT_HUB", "DELIVERED"):
        raise err_claim_requires_inspectable_shipment()
    claim["damage_pct"] = damage_pct
    claim["is_structural"] = is_structural
    claim["repair_cost_cents"] = repair_cost
    claim["resolution_type"] = calc.damage_triage(
        is_structural, damage_pct, repair_cost, claim["replacement_cost_cents"]
    )
    claim["status"] = "INSPECTION"
    touch(claim)
    return success(claim)


@bp.post("/damage-claims/<claimId>/determine")
@require_roles("ClaimsAdjuster")
def determine_claim(claimId):
    claim = get_or_404(db.damage_claims, claimId)
    if claim["status"] != "INSPECTION":
        raise err_invalid_state("Claim must be INSPECTION to determine")
    liability_party, amount = calc.chargeback_allocation(
        claim["concealment"], claim["repair_cost_cents"], claim["replacement_cost_cents"]
    )
    claim["liability_party"] = liability_party
    claim["chargeback_amount_cents"] = amount
    claim["status"] = "DETERMINATION"
    touch(claim)
    if liability_party == "SUPPLIER":
        shipment = db.shipments.get(claim["shipment_id"])
        chargeback = stamp_new(
            {
                "id": new_id(),
                "damage_claim_id": claim["id"],
                "supplier_id": shipment["supplier_id"] if shipment is not None else None,
                "shipment_id": claim["shipment_id"],
                "amount_cents": amount,
                "reason_code": calc.chargeback_reason_code(claim["resolution_type"]),
                "status": "PENDING",
            }
        )
        db.chargebacks[chargeback["id"]] = chargeback
    return success(claim)


@bp.post("/damage-claims/<claimId>/settle")
@require_roles("ClaimsAdjuster")
def settle_claim(claimId):
    claim = get_or_404(db.damage_claims, claimId)
    if claim["status"] != "DETERMINATION":
        raise err_invalid_state("Claim must be DETERMINATION to settle")
    chargeback = _chargeback_for_claim(claim["id"])
    if chargeback is not None and chargeback["status"] in ("PENDING", "DISPUTED"):
        raise err_chargeback_open()
    claim["status"] = "SETTLED"
    touch(claim)
    shipment = db.shipments.get(claim["shipment_id"])
    if shipment is not None:
        supplier_metrics.recompute_supplier(shipment["supplier_id"])
    return success(claim)


@bp.post("/damage-claims/<claimId>/withdraw")
@require_roles("Customer", "ClaimsAdjuster")
def withdraw_claim(claimId):
    claim = get_or_404(db.damage_claims, claimId)
    if claim["status"] != "OPEN":
        raise err_invalid_state("Claim must be OPEN to withdraw")
    claim["status"] = "WITHDRAWN"
    touch(claim)
    return success(claim)


# --- Chargebacks ---------------------------------------------------------------

_CHARGEBACK_STATES = {"PENDING", "SETTLED", "DISPUTED", "REVERSED"}


@bp.get("/chargebacks")
@require_roles("NetworkAdmin", "ClaimsAdjuster", "SupplierRep")
def list_chargebacks():
    return list_response(
        db.chargebacks,
        [
            ("supplier_id", "supplier_id", None),
            ("damage_claim_id", "damage_claim_id", None),
            ("shipment_id", "shipment_id", None),
            ("status", "status", _CHARGEBACK_STATES),
        ],
    )


@bp.get("/chargebacks/<chargebackId>")
@require_roles("NetworkAdmin", "ClaimsAdjuster", "SupplierRep")
def get_chargeback(chargebackId):
    return success(get_or_404(db.chargebacks, chargebackId))


@bp.post("/chargebacks/<chargebackId>/settle")
@require_roles("NetworkAdmin")
def settle_chargeback(chargebackId):
    chargeback = get_or_404(db.chargebacks, chargebackId)
    if chargeback["status"] not in ("PENDING", "DISPUTED"):
        raise err_invalid_state("Chargeback must be PENDING or DISPUTED to settle")
    chargeback["status"] = "SETTLED"
    touch(chargeback)
    supplier_metrics.recompute_supplier(chargeback["supplier_id"])
    return success(chargeback)


@bp.post("/chargebacks/<chargebackId>/dispute")
@require_roles("SupplierRep")
def dispute_chargeback(chargebackId):
    chargeback = get_or_404(db.chargebacks, chargebackId)
    if request.user_id != chargeback["supplier_id"]:
        raise err_forbidden("A supplier may only dispute its own chargebacks")
    if chargeback["status"] != "PENDING":
        raise err_invalid_state("Chargeback must be PENDING to dispute")
    chargeback["status"] = "DISPUTED"
    touch(chargeback)
    return success(chargeback)


@bp.post("/chargebacks/<chargebackId>/reverse")
@require_roles("NetworkAdmin")
def reverse_chargeback(chargebackId):
    chargeback = get_or_404(db.chargebacks, chargebackId)
    if chargeback["status"] != "DISPUTED":
        raise err_invalid_state("Chargeback must be DISPUTED to reverse")
    chargeback["status"] = "REVERSED"
    touch(chargeback)
    supplier_metrics.recompute_supplier(chargeback["supplier_id"])
    return success(chargeback)
