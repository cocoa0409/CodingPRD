"""BenefitCheck routes."""

from flask import Blueprint, request

import clock
import db
import serializers
from clock import ok
from errors import ApiError, ERR_INVALID_REQUEST
from request_context import (
    actor,
    allowed,
    body,
    created_order,
    int_value,
    need_benefit_check,
    need_prescription,
    page_args,
    paginate,
)
from services import benefit

bp = Blueprint("benefit_checks", __name__)

BENEFIT_ROLES = ["Prescriber", "Pharmacy", "NetworkOperator", "PatientService"]


@bp.post("/network/benefit-checks")
def open_benefit_check():
    role, _ = actor()
    allowed(role, ["Prescriber", "Pharmacy"])
    payload = body(required=("prescription_id", "payer_id", "benchmark_price_cents"), optional=())
    prescription = need_prescription(payload["prescription_id"])
    payer = db.get("participants", payload["payer_id"])
    if payer is None:
        raise ApiError("ERR_PARTICIPANT_NOT_FOUND")
    benchmark = int_value(payload["benchmark_price_cents"], "benchmark_price_cents", minimum=0)

    row = db.new_resource()
    row.update({
        "prescription_id": prescription["id"],
        "patient_id": prescription["patient_id"],
        "payer_id": payer["id"],
        "benchmark_price_cents": benchmark,
        "formulary_status": "UNKNOWN",
        "coverage_status": "UNKNOWN",
        "check_status": "PENDING",
        "pricing_variant": "PROVISIONAL",
        "deductible_met_snapshot_cents": payer.get("plan_deductible_met_cents", 0),
        "estimated_patient_pay_cents": 0,
        "estimated_plan_pay_cents": 0,
    })
    db.add("benefit_checks", row)
    return ok(serializers.benefit_check(row), status=201)


@bp.get("/network/benefit-checks")
def list_benefit_checks():
    role, _ = actor()
    allowed(role, BENEFIT_ROLES)
    limit, offset = page_args()
    rows = db.all_rows("benefit_checks")
    for field in ("prescription_id", "payer_id", "check_status", "pricing_variant"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    rows = created_order(rows)
    window, meta = paginate(rows, limit, offset)
    return ok([serializers.benefit_check(b) for b in window], **meta)


@bp.get("/network/benefit-checks/<bid>")
def get_benefit_check(bid):
    role, _ = actor()
    allowed(role, BENEFIT_ROLES)
    check = need_benefit_check(bid)
    return ok(serializers.benefit_check(check))


@bp.post("/network/benefit-checks/<bid>/evaluate")
def evaluate_benefit_check(bid):
    role, _ = actor()
    allowed(role, ["Pharmacy", "HubOperator"])
    body(required=(), optional=())
    check = need_benefit_check(bid)
    benefit.evaluate(check, "PROVISIONAL")
    return ok(serializers.benefit_check(check))


@bp.post("/network/benefit-checks/<bid>/complete")
def complete_benefit_check(bid):
    role, _ = actor()
    allowed(role, ["Pharmacy"])
    body(required=(), optional=())
    check = need_benefit_check(bid)
    benefit.evaluate(check, "FINAL")
    return ok(serializers.benefit_check(check))