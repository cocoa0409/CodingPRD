"""Warranty adjudication and the reserve ledger (PRD 3.8)."""

from flask import Blueprint

import db
import response
import serializers
import validation
from db import make_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from services import calc
from services.core import resolve, rows

bp = Blueprint("warranty", __name__)

FAILURE_MODES = (
    "TANK_LEAK",
    "ANODE_DEPLETION",
    "THERMOSTAT",
    "GAS_VALVE",
    "COMPRESSOR",
    "OTHER",
)
CLAIM_STATUSES = ("OPEN", "VALIDATED", "DENIED", "PAID")

READ_ROLES = ["WarrantyAnalyst", "PlantAdmin", "ComplianceEngineer"]


def _model_of(claim):
    unit = db.db.units[claim["heater_unit_id"]]
    return db.db.models[unit["product_model_id"]]


@bp.post("/warranty-claims")
@endpoint(["WarrantyAnalyst"])
def create_claim():
    body = validation.json_body()
    heater_unit_id = validation.string(body, "heater_unit_id")
    failure_mode = validation.enum(body, "failure_mode", FAILURE_MODES)
    hardness = validation.number(
        body, "reported_water_hardness_gpg", minimum=0.0, maximum=60.0
    )

    unit = resolve("unit", heater_unit_id)
    # Position 34: only a unit in the field can carry a field claim.
    if unit["build_status"] != "SHIPPED" or unit.get("shipped_at") is None:
        raise ApiError("ERR_UNIT_NOT_IN_SERVICE")

    # Coverage is decided on the frozen figure, never on a later recomputation.
    frozen_months = calc.months_in_service(unit["shipped_at"], db.db.now())
    row = make_row(
        {
            "heater_unit_id": unit["id"],
            "failure_mode": failure_mode,
            "reported_water_hardness_gpg": hardness,
            "months_in_service_at_report": frozen_months,
            "coverage_pct": None,
            "approved_payout_cents": None,
            "status": "OPEN",
            "paid_at": None,
            "reason_code": None,
        }
    )
    db.db.claims[row["id"]] = row
    return response.created(serializers.warranty_claim(row))


@bp.get("/warranty-claims/<cid>")
@endpoint(READ_ROLES)
def read_claim(cid):
    return response.ok(serializers.warranty_claim(resolve("claim", cid)))


@bp.get("/warranty-claims")
@endpoint(READ_ROLES)
def list_claims():
    heater_unit_id = validation.query_string("heater_unit_id")
    failure_mode = validation.query_enum("failure_mode", FAILURE_MODES)
    status = validation.query_enum("status", CLAIM_STATUSES)
    result = rows("claim")
    if heater_unit_id is not None:
        result = [r for r in result if r["heater_unit_id"] == heater_unit_id]
    if failure_mode is not None:
        result = [r for r in result if r["failure_mode"] == failure_mode]
    if status is not None:
        result = [r for r in result if r["status"] == status]
    return response.paginate(ordered(result), serializers.warranty_claim)


@bp.post("/warranty-claims/<cid>/validate")
@endpoint(["WarrantyAnalyst"])
def validate_claim(cid):
    claim = resolve("claim", cid)
    if claim["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    coverage_pct, part_cents = calc.warranty_coverage(
        claim["failure_mode"], claim["months_in_service_at_report"]
    )
    # Position 29: a claim can be denied out of warranty but never validated at zero.
    if coverage_pct == 0:
        raise ApiError("ERR_WARRANTY_COVERAGE_EXPIRED")

    claim["coverage_pct"] = coverage_pct
    claim["approved_payout_cents"] = calc.warranty_payout(part_cents, coverage_pct)
    claim["status"] = "VALIDATED"
    touch(claim)
    return response.ok(serializers.warranty_claim(claim))


@bp.post("/warranty-claims/<cid>/deny")
@endpoint(["WarrantyAnalyst"])
def deny_claim(cid):
    claim = resolve("claim", cid)
    body = validation.json_body()
    reason_code = validation.string(body, "reason_code")
    if claim["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    claim["status"] = "DENIED"
    claim["reason_code"] = reason_code
    # A denied claim carries no residual monetary intent.
    claim["coverage_pct"] = calc.D("0.00")
    claim["approved_payout_cents"] = 0
    touch(claim)
    return response.ok(serializers.warranty_claim(claim))


@bp.post("/warranty-claims/<cid>/pay")
@endpoint(["WarrantyAnalyst"])
def pay_claim(cid):
    claim = resolve("claim", cid)
    if claim["status"] != "VALIDATED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    model = _model_of(claim)
    balance = model["warranty_reserve_accrued_cents"] - model["warranty_paid_cents"]
    payout = claim["approved_payout_cents"] or 0
    # Position 30: a payout exactly equal to the balance drains it and is allowed.
    if payout > balance:
        raise ApiError("ERR_WARRANTY_RESERVE_INSUFFICIENT")

    claim["status"] = "PAID"
    claim["paid_at"] = db.db.now()
    touch(claim)
    # The lifetime accrual figure is never touched by a payment.
    model["warranty_paid_cents"] += payout
    touch(model)
    return response.ok(serializers.warranty_claim(claim))


@bp.post("/warranty-claims/<cid>/reverse-payment")
@endpoint(["WarrantyAnalyst"])
def reverse_payment(cid):
    claim = resolve("claim", cid)
    body = validation.json_body()
    reason_code = validation.string(body, "reason_code")
    if claim["status"] != "PAID":
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    model = _model_of(claim)
    payout = claim["approved_payout_cents"] or 0
    claim["status"] = "VALIDATED"
    claim["paid_at"] = None
    claim["reason_code"] = reason_code
    touch(claim)
    model["warranty_paid_cents"] -= payout
    touch(model)
    return response.ok(serializers.warranty_claim(claim))
