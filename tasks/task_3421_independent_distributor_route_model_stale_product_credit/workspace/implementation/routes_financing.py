"""Financing plan routes: create/list under an agreement, disburse, payments."""
from flask import Blueprint, request

import auth
import calc
import clock
import domain
import store
import validators as V
from constants import (
    ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR,
    FINANCIER_TYPES,
)
from errors import (
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_FINANCING_PLAN_EXISTS, ERR_STALE_VERSION, ERR_PAYMENT_BELOW_INTEREST,
    raise_err,
)
from response import ok_object, ok_list, pagination_params, body

bp = Blueprint("financing", __name__)

ALL = (ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR)
CREDIT = (ROLE_CREDIT_ANALYST,)
PAYERS = (ROLE_DISTRIBUTOR, ROLE_CREDIT_ANALYST)


@bp.route("/agreements/<rid>/financing-plans", methods=["POST"])
def create_plan(rid):
    user_id, role = auth.caller()
    auth.require_role(role, CREDIT)
    agreement = store.get("agreements", rid)
    if agreement is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    data = body()
    # Stage 6: shape.
    financier_type = V.get_enum(data, "financier_type", FINANCIER_TYPES)
    lender_name = data.get("lender_name")
    if financier_type == "EXTERNAL_LENDER":
        if not isinstance(lender_name, str) or not lender_name.strip():
            raise_err(ERR_INVALID_REQUEST,
                      "lender_name is required for EXTERNAL_LENDER financing")
    elif lender_name is not None:
        raise_err(ERR_INVALID_REQUEST,
                  "lender_name is forbidden for COMPANY financing")
    principal = V.get_int(data, "principal_cents", minimum=1)
    if principal != agreement["financed_amount_cents"]:
        raise_err(ERR_INVALID_REQUEST,
                  "principal_cents must equal the agreement's financed_amount_cents")
    rate = V.get_number(data, "annual_interest_rate")
    if not (0 < rate < 1):
        raise_err(ERR_INVALID_REQUEST,
                  "annual_interest_rate must be strictly between 0 and 1")
    term_weeks = V.get_int(data, "term_weeks", minimum=1)
    expected_version = V.get_int(data, "expected_agreement_version")
    # Stage 7: state preconditions.
    if agreement["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE,
                  "Financing plans can be created only for a DRAFT agreement")
    for plan in domain.plans_of_agreement(rid):
        if plan["status"] not in ("DRAFT", "SUPERSEDED"):
            raise_err(ERR_FINANCING_PLAN_EXISTS,
                      "A live financing plan already exists for this agreement")
    # Stage 8: OCC on the parent agreement version.
    if expected_version != agreement["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_agreement_version does not match the agreement version")
    plan = store.insert("financing_plans", {
        "agreement_id": rid,
        "financier_type": financier_type,
        "lender_name": lender_name if financier_type == "EXTERNAL_LENDER" else None,
        "principal_cents": principal,
        "annual_interest_rate": rate,
        "term_weeks": term_weeks,
        "weekly_payment_cents": None,
        "disburse_date": None,
        "outstanding_principal_cents": None,
        "total_paid_cents": 0,
        "status": "DRAFT",
        "_disburse_date": None,
        "_last_payment_date": None,
    })
    # A successful creation supersedes any prior DRAFT plan.
    for prior in domain.plans_of_agreement(rid):
        if prior["id"] != plan["id"] and prior["status"] == "DRAFT":
            prior["status"] = "SUPERSEDED"
            store.touch(prior)
    store.touch(agreement)
    return ok_object(plan, 201)


@bp.route("/agreements/<rid>/financing-plans", methods=["GET"])
def list_plans(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ALL)
    agreement = store.get("agreements", rid)
    if agreement is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    auth.check_resource_owner(user_id, role, agreement["distributor_id"])
    plans = domain.plans_of_agreement(rid)
    status = request.args.get("status")
    if status is not None:
        plans = [p for p in plans if p["status"] == status]
    page = pagination_params()
    total = len(plans)
    window = plans[page["offset"]:page["offset"] + page["limit"]]
    return ok_list(window, total, page)


@bp.route("/financing-plans/<rid>/disburse", methods=["POST"])
def disburse(rid):
    user_id, role = auth.caller()
    auth.require_role(role, CREDIT)
    plan = store.get("financing_plans", rid)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "Financing plan not found")
    if plan["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT plan can be disbursed")
    agreement = store.get("agreements", plan["agreement_id"])
    if agreement["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE,
                  "The parent agreement must still be DRAFT at disbursement")
    plan["disburse_date"] = clock.today().isoformat()
    plan["_disburse_date"] = clock.today()
    plan["outstanding_principal_cents"] = plan["principal_cents"]
    plan["weekly_payment_cents"] = calc.weekly_payment_cents(
        plan["principal_cents"], plan["annual_interest_rate"], plan["term_weeks"])
    plan["status"] = "ACTIVE"
    store.touch(plan)
    return ok_object(plan)


@bp.route("/financing-plans/<rid>/payments", methods=["POST"])
def record_payment(rid):
    user_id, role = auth.caller()
    auth.require_role(role, PAYERS)
    plan = store.get("financing_plans", rid)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "Financing plan not found")
    agreement = store.get("agreements", plan["agreement_id"])
    auth.check_resource_owner(user_id, role, agreement["distributor_id"])
    data = body()
    amount = V.get_int(data, "amount_cents", minimum=1)
    if plan["status"] not in ("ACTIVE", "DELINQUENT"):
        raise_err(ERR_INVALID_STATE,
                  "Payments are accepted only on ACTIVE or DELINQUENT plans")
    interest = calc.interest_portion_cents(plan["outstanding_principal_cents"],
                                           plan["annual_interest_rate"])
    if amount < interest:
        raise_err(ERR_PAYMENT_BELOW_INTEREST,
                  "Payment is smaller than the accrued interest portion")
    principal_portion = min(amount - interest, plan["outstanding_principal_cents"])
    plan["outstanding_principal_cents"] -= principal_portion
    plan["total_paid_cents"] += amount
    plan["_last_payment_date"] = clock.today()
    store.touch(plan)
    if plan["outstanding_principal_cents"] == 0:
        plan["status"] = "PAID_OFF"
        store.touch(plan)
        distributor = store.get("distributors", agreement["distributor_id"])
        domain.recompute_standing(distributor)
    return ok_object(plan)
