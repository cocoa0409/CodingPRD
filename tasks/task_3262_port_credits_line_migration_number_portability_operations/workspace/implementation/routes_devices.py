"""Routes: device installment plans and trade-in assessments."""

from flask import Blueprint, request

import calculations
import clock
import errors
import lookups
import middleware
import models
import response
import services
import storage

bp = Blueprint("devices", __name__, url_prefix="/portability")

PLAN_READERS = ("PlatformAdmin", "CustomerService", "TradeInInspector", "Customer")
WRITERS = ("CustomerService", "PlatformAdmin")


# ---------------------------------------------------------------------------
def _plan_exists_active(line_id):
    """Only one installment plan exists per subscriber line at a time (PRD 3.5).

    A plan that is UPGRADE_ELIGIBLE was financed and is still in force, so it
    blocks a fresh activation exactly as an ACTIVE one does.
    """
    for plan in storage.db.all("device_installment_plans"):
        if plan["subscriber_line_id"] != line_id:
            continue
        if plan["plan_state"] in ("ACTIVE", "UPGRADE_ELIGIBLE"):
            return True
    return False


@bp.post("/device-installment-plans")
@middleware.require_roles(*WRITERS)
def create_plan(caller):
    data = middleware.body()
    line_id = middleware.required_str(data, "subscriber_line_id")
    line = lookups.line(line_id)
    middleware.require_expected_line_version(data, line)

    device_price = middleware.required_int(data, "device_price_cents")
    down_payment = middleware.optional_int(data, "down_payment_cents", 0)
    installment_months = middleware.required_int(data, "installment_months")
    if installment_months <= 0:
        errors.fail("ERR_INVALID_REQUEST", "installment_months must be at least 1.")

    activation_at = middleware.optional_instant(data, "activation_at")

    # Checked last of the semantically meaningful gates (validations priority 27).
    if activation_at is not None and _plan_exists_active(line_id):
        errors.fail("ERR_DEVICE_PLAN_STATE",
                    "The line already carries an ACTIVE installment plan.")

    financed = calculations.financed_balance_cents(device_price, down_payment)
    monthly, _first = calculations.level_installment_cents(financed, installment_months)

    plan = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "subscriber_line_id": line_id,
        "device_model": middleware.required_str(data, "device_model"),
        "device_price_cents": device_price,
        "down_payment_cents": down_payment,
        "installment_months": installment_months,
        "monthly_installment_cents": monthly,
        "remaining_balance_cents": financed,
        "plan_state": "QUOTED",
        "financed_at": None,
        "upgrade_eligible_at": None,
        "trade_in_credit_cents": 0,
    }
    storage.db.add("device_installment_plans", plan)

    if activation_at is not None:
        plan["financed_at"] = clock.fmt(activation_at)
        eligible = calculations.upgrade_eligible_at(activation_at, installment_months)
        plan["upgrade_eligible_at"] = clock.fmt(eligible)
        plan["plan_state"] = (
            "UPGRADE_ELIGIBLE" if clock.now() >= eligible else "ACTIVE"
        )

    models.touch(line)
    return response.ok(models.plan_out(plan), 201)


@bp.get("/device-installment-plans/<plan_id>")
@middleware.require_roles(*PLAN_READERS)
def get_plan(caller, plan_id):
    plan = lookups.plan(plan_id)
    line = lookups.line(plan["subscriber_line_id"])
    middleware.enforce_ownership(caller, line["account_id"])
    return response.ok(models.plan_out(plan))


@bp.get("/subscriber-lines/<line_id>/device-installment-plans")
@middleware.require_roles(*PLAN_READERS)
def list_line_plans(caller, line_id):
    line = lookups.line(line_id)
    middleware.enforce_ownership(caller, line["account_id"])
    rows = [
        p for p in storage.db.all("device_installment_plans")
        if p["subscriber_line_id"] == line_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = response.paginate(rows, request.args)
    return response.ok_list([models.plan_out(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
@bp.post("/trade-in-assessments")
@middleware.require_roles(*WRITERS)
def create_assessment(caller):
    data = middleware.body()
    plan_id = middleware.required_str(data, "installment_plan_id")
    lookups.plan(plan_id)

    declared = middleware.required_str(data, "declared_condition")
    if declared not in calculations.GRADE_VALUE_CENTS:
        errors.fail("ERR_INVALID_REQUEST", "declared_condition is not a recognized value.")

    record = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "installment_plan_id": plan_id,
        "parent_plan_id": plan_id,
        "device_model": middleware.required_str(data, "device_model"),
        "declared_condition": declared,
        "graded_condition": None,
        "assessment_state": "SUBMITTED",
        "estimated_credit_cents": calculations.trade_in_estimated(declared),
        "final_credit_cents": 0,
        "grade_delta_cents": 0,
        "submitted_at": clock.fmt_now(),
        "graded_at": None,
    }
    storage.db.add("trade_in_assessments", record)
    return response.ok(models.assessment_out(record), 201)


@bp.get("/trade-in-assessments")
@middleware.require_roles("Customer")
def list_assessments(caller):
    rows = storage.db.all("trade_in_assessments")
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = response.paginate(rows, request.args)
    return response.ok_list([models.assessment_out(r) for r in page], limit, offset, total)


@bp.get("/device-installment-plans/<plan_id>/trade-in-assessments")
@middleware.require_roles("PlatformAdmin", "CustomerService", "TradeInInspector", "CreditAnalyst")
def list_plan_assessments(caller, plan_id):
    lookups.plan(plan_id)
    rows = [
        t for t in storage.db.all("trade_in_assessments")
        if t["installment_plan_id"] == plan_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = response.paginate(rows, request.args)
    return response.ok_list([models.assessment_out(r) for r in page], limit, offset, total)


@bp.post("/trade-in-assessments/<assessment_id>/grade")
@middleware.require_roles("TradeInInspector")
def grade_assessment(caller, assessment_id):
    data = middleware.body()
    record = lookups.assessment(assessment_id)

    if record["assessment_state"] != "SUBMITTED":
        errors.fail("ERR_INVALID_STATE", "Only a SUBMITTED assessment can be graded.")

    plan = lookups.plan(record["installment_plan_id"])
    if plan["plan_state"] != "ACTIVE":
        errors.fail("ERR_PLAN_NOT_ACTIVE",
                    "A trade-in credit may only be settled against an ACTIVE plan.")

    graded = data.get("graded_condition")
    if not isinstance(graded, str) or graded not in calculations.GRADE_VALUE_CENTS:
        errors.fail("ERR_INVALID_REQUEST", "graded_condition is not a recognized value.")

    record["graded_condition"] = graded
    record["graded_at"] = clock.fmt_now()
    record["final_credit_cents"] = calculations.trade_in_final(graded)
    record["estimated_credit_cents"] = calculations.trade_in_estimated(
        record["declared_condition"])
    record["grade_delta_cents"] = calculations.trade_in_grade_delta(
        record["estimated_credit_cents"], record["final_credit_cents"])
    record["assessment_state"] = "GRADED"
    models.touch(record)

    plan["trade_in_credit_cents"] = record["final_credit_cents"]
    financed = calculations.financed_balance_cents(
        plan["device_price_cents"], plan["down_payment_cents"])
    plan["remaining_balance_cents"] = calculations.remaining_balance_cents(
        financed, plan["trade_in_credit_cents"])
    services.recompute_plan(plan)

    return response.ok(models.assessment_out(record))