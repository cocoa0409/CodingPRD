"""HraAccount endpoints: funding, carryover and the year-end close (PRD 3.7)."""

from flask import Blueprint, request

import calc
import errors
from auth import ALL_ROLES, ROLE_HRA_ADMINISTRATOR, require_caller
from domain import (body_reference, deny_held_claims, get_hra_account,
                   get_plan_year, get_retiree, require_certified_eligible)
from envelope import object_response, paginate
from errors import fail
from store import base_record, db, now, order_asc, touch
from validate import read_body

bp = Blueprint("hra_accounts", __name__)

ACCOUNT_STATUSES = ("OPEN", "FROZEN", "CLOSED")


@bp.post("/retiree-benefits/hra-accounts")
def create_hra_account():
    require_caller((ROLE_HRA_ADMINISTRATOR,))
    body = read_body()
    plan_year = body_reference(body, "plan_year_id", get_plan_year)
    retiree = body_reference(body, "retiree_id", get_retiree)
    prior = body_reference(body, "prior_year_account_id", get_hra_account)

    retiree_id = body.string("retiree_id")
    plan_year_id = body.string("plan_year_id")
    covered_months = body.integer("covered_months", minimum=0, maximum=12)
    prior_id = body.string("prior_year_account_id", required=False,
                           nullable=True, default=None)

    if plan_year["status"] != "OPEN":
        fail(errors.ERR_PLAN_YEAR_NOT_OPEN)

    require_certified_eligible(retiree_id, plan_year_id)

    for existing in db.hra_accounts.values():
        if existing["retiree_id"] == retiree_id \
                and existing["plan_year_id"] == plan_year_id:
            fail(errors.ERR_DUPLICATE_HRA_ACCOUNT,
                 "A reimbursement account already exists for this retiree and "
                 "plan year.")

    if prior is not None:
        if prior["retiree_id"] != retiree_id:
            fail(errors.ERR_DUPLICATE_HRA_ACCOUNT,
                 "prior_year_account_id belongs to another retiree.")
        prior_plan_year = db.plan_years.get(prior["plan_year_id"])
        if prior_plan_year is None or prior_plan_year["year"] >= plan_year["year"]:
            fail(errors.ERR_DUPLICATE_HRA_ACCOUNT,
                 "prior_year_account_id must reference an earlier plan year.")
        if prior["status"] != "CLOSED":
            fail(errors.ERR_PRIOR_HRA_ACCOUNT_NOT_CLOSED)

    annual_credit = calc.hra_annual_credit_cents(plan_year, retiree,
                                                 covered_months)
    carryover_in = prior["available_balance_cents"] if prior is not None else 0
    funded = annual_credit + carryover_in

    record = base_record()
    record.update({
        "retiree_id": retiree_id,
        "plan_year_id": plan_year_id,
        "prior_year_account_id": prior_id,
        "covered_months": covered_months,
        "annual_credit_cents": annual_credit,
        "carryover_in_cents": carryover_in,
        "funded_cents": funded,
        "available_balance_cents": funded,
        "pending_hold_cents": 0,
        "substantiated_paid_cents": 0,
        "premium_offset_cents": 0,
        "forfeited_cents": 0,
        "status": "OPEN",
        "closed_at": None,
    })
    db.hra_accounts[record["id"]] = record
    return object_response(record, 201)


@bp.get("/retiree-benefits/hra-accounts/<hra_account_id>")
def read_hra_account(hra_account_id):
    require_caller(ALL_ROLES)
    return object_response(get_hra_account(hra_account_id))


@bp.get("/retiree-benefits/hra-accounts")
def list_hra_accounts():
    require_caller(ALL_ROLES)
    rows = list(db.hra_accounts.values())
    for field in ("retiree_id", "plan_year_id", "prior_year_account_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    return paginate(order_asc(rows))


@bp.post("/retiree-benefits/hra-accounts/<hra_account_id>/close-year")
def close_hra_account(hra_account_id):
    require_caller((ROLE_HRA_ADMINISTRATOR,))
    account = get_hra_account(hra_account_id)

    if account["status"] != "OPEN":
        fail(errors.ERR_HRA_ACCOUNT_NOT_OPEN)

    plan_year = db.plan_years.get(account["plan_year_id"])
    if plan_year is None or plan_year["status"] not in ("OPEN", "CLOSED"):
        fail(errors.ERR_PLAN_YEAR_NOT_OPEN,
             "Year-end close requires the plan year to be OPEN or CLOSED.")

    # The claim cascade runs first, so pending_hold_cents is 0 by the time
    # forfeiture is computed.
    deny_held_claims(account)

    cap = calc.carryover_cap_cents(account["annual_credit_cents"],
                                   plan_year["carryover_cap_pct"])
    forfeited = calc.year_end_forfeiture_cents(
        account["available_balance_cents"], cap)
    account["forfeited_cents"] += forfeited
    account["available_balance_cents"] -= forfeited

    account["status"] = "CLOSED"
    account["closed_at"] = now()
    touch(account)
    return object_response(account)
