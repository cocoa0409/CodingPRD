"""Banking facilities, collection accounts, the waterfall, receipts and clock."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint

import calc
from envelope import created, ok, ok_list
from errors import ApiError
from serializers import account_out, facility_out, milestone_out, run_out, tier_out
from store import (
    accounts_of_film,
    base_row,
    db,
    facilities_of_film,
    get_account,
    get_contract,
    get_facility,
    get_film,
    get_milestone,
    now,
    runs_of_account,
    tiers_of_account,
    touch,
)
from util import ZERO2, q2
from validation import actor, body, page, require_roles

bp = Blueprint("finance", __name__)

FACILITY_STATUSES = (
    "PROPOSED",
    "APPROVED",
    "DRAWN",
    "MARGIN_CALL",
    "REPAID",
    "DEFAULTED",
)
ACCOUNT_STATUSES = ("OPEN", "LOCKED", "CLOSED")
TIER_TYPES = (
    "COLLECTION_FEE",
    "SALES_COMMISSION",
    "SALES_EXPENSES",
    "BANK_DEBT",
    "EQUITY_RECOUPMENT",
    "DEFERMENT",
    "PARTICIPATION",
)

FINANCE_READ_ROLES = ("HeadOfSales", "CollectionAgent", "Lender", "PlatformAdmin")


def open_account_of_film(film_id):
    for account in accounts_of_film(film_id):
        if account["status"] == "OPEN":
            return account
    return None


def resync_bank_debt_tier(film_id, amount):
    for tier in calc.tiers_of_film(film_id, "BANK_DEBT"):
        if tier["cap_usd"] is None or q2(tier["cap_usd"]) != q2(amount):
            tier["cap_usd"] = q2(amount)
            touch(tier)


# ------------------------------------------------------------------ facilities


@bp.post("/films/<film_id>/banking-facilities")
@require_roles("Lender")
def create_facility(film_id):
    film = get_film(film_id)
    payload = body()
    row = base_row()
    row.update(
        {
            "film_id": film["id"],
            "lender_name": payload.req_string("lender_name"),
            "discount_rate_pct": payload.req_number(
                "discount_rate_pct",
                minimum=Decimal("0"),
                maximum=Decimal("0.30"),
                exclusive_min=True,
            ),
            "advance_rate_pct": payload.req_number(
                "advance_rate_pct",
                minimum=Decimal("0"),
                maximum=Decimal("1"),
                exclusive_min=True,
            ),
            "facility_cap_usd": q2(payload.req_number("facility_cap_usd")),
            "completion_bond_required": payload.opt_bool(
                "completion_bond_required", True
            ),
            "completion_bond_posted": False,
            "bond_provider": None,
            "bond_amount_usd": None,
            "eligible_collateral_usd": ZERO2,
            "advance_amount_usd": ZERO2,
            "drawn_amount_usd": ZERO2,
            "outstanding_debt_usd": ZERO2,
            "status": "PROPOSED",
            "approved_by_user_id": None,
        }
    )
    db.facilities[row["id"]] = row
    calc.write_facility_figures(row)
    return created(facility_out(row))


@bp.get("/films/<film_id>/banking-facilities")
@require_roles(*FINANCE_READ_ROLES)
def list_facilities(film_id):
    film = get_film(film_id)
    items, meta = page(facilities_of_film(film["id"]), facility_out)
    return ok_list(items, meta)


@bp.post("/banking-facilities/<facility_id>/state")
@require_roles("Lender")
def facility_state(facility_id):
    facility = get_facility(facility_id)
    payload = body()
    to_status = payload.req_enum("to_status", FACILITY_STATUSES)
    current = facility["status"]
    if to_status == current:
        raise ApiError("ERR_INVALID_STATE")

    if to_status == "APPROVED":
        if current != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE")
        calc.write_facility_figures(facility)
        if not calc.has_investment_grade_executed_contract(facility["film_id"]):
            raise ApiError("ERR_NO_ELIGIBLE_COLLATERAL")
        if facility["eligible_collateral_usd"] <= 0:
            raise ApiError("ERR_NO_ELIGIBLE_COLLATERAL")
        facility["status"] = "APPROVED"
        facility["approved_by_user_id"] = actor()
        touch(facility)
    elif to_status == "DRAWN":
        if current != "APPROVED":
            raise ApiError("ERR_INVALID_STATE")
        if actor() == facility["approved_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if facility["completion_bond_required"] and not facility[
            "completion_bond_posted"
        ]:
            raise ApiError("ERR_COMPLETION_BOND_REQUIRED")
        calc.write_facility_figures(facility)
        if facility["advance_amount_usd"] <= 0:
            raise ApiError("ERR_NO_ELIGIBLE_COLLATERAL")
        facility["status"] = "DRAWN"
        facility["drawn_amount_usd"] = facility["advance_amount_usd"]
        facility["outstanding_debt_usd"] = facility["advance_amount_usd"]
        touch(facility)
        resync_bank_debt_tier(facility["film_id"], facility["drawn_amount_usd"])
    elif to_status == "DEFAULTED":
        if current != "MARGIN_CALL":
            raise ApiError("ERR_INVALID_STATE")
        facility["status"] = "DEFAULTED"
        touch(facility)
    else:
        # PROPOSED, MARGIN_CALL and REPAID are only ever reached by cascade.
        raise ApiError("ERR_INVALID_STATE")
    return ok(facility_out(facility))


@bp.post("/banking-facilities/<facility_id>/completion-bond")
@require_roles("Lender")
def post_completion_bond(facility_id):
    facility = get_facility(facility_id)
    payload = body()
    bond_provider = payload.req_string("bond_provider")
    bond_amount = q2(payload.req_number("bond_amount_usd"))
    if facility["status"] in ("REPAID", "DEFAULTED"):
        raise ApiError("ERR_INVALID_STATE")

    facility["completion_bond_posted"] = True
    facility["bond_provider"] = bond_provider
    facility["bond_amount_usd"] = bond_amount
    calc.write_facility_figures(facility)
    if (
        facility["status"] == "MARGIN_CALL"
        and facility["advance_amount_usd"] >= facility["drawn_amount_usd"]
    ):
        facility["status"] = "DRAWN"
    touch(facility)
    return ok(facility_out(facility))


# ----------------------------------------------------------- collection accounts


@bp.post("/films/<film_id>/collection-accounts")
@require_roles("CollectionAgent")
def create_account(film_id):
    film = get_film(film_id)
    payload = body()
    row = base_row()
    row.update(
        {
            "film_id": film["id"],
            "bank_name": payload.req_string("bank_name"),
            "account_reference": payload.req_string("account_reference"),
            "total_receipts_usd": ZERO2,
            "total_distributed_usd": ZERO2,
            "run_count": 0,
            "status": "OPEN",
        }
    )
    db.accounts[row["id"]] = row
    return created(account_out(row))


@bp.get("/films/<film_id>/collection-accounts")
@require_roles(*FINANCE_READ_ROLES)
def list_accounts(film_id):
    film = get_film(film_id)
    items, meta = page(accounts_of_film(film["id"]), account_out)
    return ok_list(items, meta)


@bp.get("/collection-accounts/<account_id>")
@require_roles(*FINANCE_READ_ROLES)
def read_account(account_id):
    return ok(account_out(get_account(account_id)))


@bp.post("/collection-accounts/<account_id>/state")
@require_roles("CollectionAgent")
def account_state(account_id):
    account = get_account(account_id)
    payload = body()
    to_status = payload.req_enum("to_status", ACCOUNT_STATUSES)
    current = account["status"]
    if to_status == current:
        raise ApiError("ERR_INVALID_STATE")
    if to_status == "LOCKED":
        if current != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        account["status"] = "LOCKED"
        touch(account)
    elif to_status == "OPEN":
        if current != "LOCKED":
            raise ApiError("ERR_INVALID_STATE")
        account["status"] = "OPEN"
        touch(account)
    else:
        # CLOSED is only ever reached through the film WRAPPED cascade.
        raise ApiError("ERR_INVALID_STATE")
    return ok(account_out(account))


# ------------------------------------------------------------- waterfall tiers


@bp.post("/collection-accounts/<account_id>/waterfall-tiers")
@require_roles("CollectionAgent")
def create_tier(account_id):
    account = get_account(account_id)
    payload = body()
    tier_order = payload.req_int("tier_order", minimum=1)
    tier_type = payload.req_enum("tier_type", TIER_TYPES)
    recipient_name = payload.req_string("recipient_name")
    pct_of_available = payload.req_number(
        "pct_of_available",
        minimum=Decimal("0"),
        maximum=Decimal("1"),
        exclusive_min=True,
    )
    cap_usd = payload.nullable_number("cap_usd")

    for existing in tiers_of_account(account["id"]):
        if existing["tier_order"] == tier_order:
            raise ApiError("ERR_TIER_ORDER_TAKEN")
        if cap_usd is None and existing["cap_usd"] is None:
            raise ApiError("ERR_TIER_ORDER_TAKEN")

    row = base_row()
    row.update(
        {
            "account_id": account["id"],
            "tier_order": tier_order,
            "tier_type": tier_type,
            "recipient_name": recipient_name,
            "pct_of_available": pct_of_available,
            "cap_usd": None if cap_usd is None else q2(cap_usd),
            "recouped_usd": ZERO2,
        }
    )
    db.tiers[row["id"]] = row
    return created(tier_out(row))


@bp.get("/collection-accounts/<account_id>/waterfall-tiers")
@require_roles(*FINANCE_READ_ROLES)
def list_tiers(account_id):
    account = get_account(account_id)
    items, meta = page(calc.ordered_tiers(account["id"]), tier_out)
    return ok_list(items, meta)


# --------------------------------------------------------------- distribution


@bp.post("/collection-accounts/<account_id>/distribute")
@require_roles("CollectionAgent")
def distribute(account_id):
    account = get_account(account_id)
    payload = body()
    amount_in = q2(payload.req_number("amount_in_usd"))
    if account["status"] != "OPEN":
        raise ApiError("ERR_COLLECTION_ACCOUNT_NOT_OPEN")
    if amount_in > calc.account_balance(account):
        raise ApiError("ERR_INSUFFICIENT_ACCOUNT_BALANCE")

    entries = calc.run_waterfall(account, amount_in)
    allocations = []
    allocated = Decimal("0")
    for entry in entries:
        tier = entry["tier"]
        allocations.append(
            {
                "tier_id": tier["id"],
                "tier_type": tier["tier_type"],
                "recipient_name": tier["recipient_name"],
                "amount_usd": q2(entry["amount"]),
            }
        )
        allocated += entry["amount"]
    allocated = q2(allocated)

    row = base_row(versioned=False)
    row.update(
        {
            "account_id": account["id"],
            "run_index": account["run_count"] + 1,
            "amount_in_usd": amount_in,
            "amount_allocated_usd": allocated,
            "residual_usd": q2(amount_in - allocated),
            "allocations": allocations,
            "run_by_user_id": actor(),
        }
    )
    db.runs[row["id"]] = row
    account["total_distributed_usd"] = q2(
        account["total_distributed_usd"] + allocated
    )
    account["run_count"] = account["run_count"] + 1
    touch(account)
    calc.apply_run_cross_effects(account, entries)
    return created(run_out(row))


@bp.get("/collection-accounts/<account_id>/distribution-runs")
@require_roles(*FINANCE_READ_ROLES)
def list_runs(account_id):
    account = get_account(account_id)
    rows = sorted(
        runs_of_account(account["id"]),
        key=lambda row: (row["run_index"], row["created_at"], row["_seq"]),
    )
    items, meta = page(rows, run_out)
    return ok_list(items, meta)


# ------------------------------------------------------------------- receipts


@bp.post("/payment-milestones/<milestone_id>/receipt")
@require_roles("CollectionAgent")
def post_receipt(milestone_id):
    milestone = get_milestone(milestone_id)
    payload = body()
    amount = q2(payload.req_number("amount_usd"))
    received_at = payload.req_instant("received_at")
    contract = get_contract(milestone["contract_id"])
    if milestone["status"] not in ("SCHEDULED", "INVOICED"):
        raise ApiError("ERR_INVALID_STATE")
    if contract["negotiation_status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_STATE")
    account = open_account_of_film(contract["film_id"])
    if account is None:
        raise ApiError("ERR_COLLECTION_ACCOUNT_NOT_OPEN")
    if amount != q2(milestone["amount_usd"]):
        raise ApiError("ERR_RECEIPT_AMOUNT_MISMATCH")

    milestone["status"] = "RECEIVED"
    milestone["received_amount_usd"] = amount
    milestone["received_at"] = received_at
    milestone["received_by_user_id"] = actor()

    agreement = calc.agreement_for_film(contract["film_id"])
    accrued = ZERO2
    if agreement is not None:
        prior = q2(agreement["gross_collected_usd"])
        rate = calc.commission_rate(agreement["commission_pct"], prior)
        accrued = q2(amount * rate)
        agreement["gross_collected_usd"] = q2(prior + amount)
        agreement["commission_earned_usd"] = q2(
            agreement["commission_earned_usd"] + accrued
        )
        touch(agreement)
    milestone["accrued_commission_usd"] = accrued
    touch(milestone)

    account["total_receipts_usd"] = q2(account["total_receipts_usd"] + amount)
    touch(account)

    calc.resync_commission_tier(contract["film_id"], agreement)
    calc.resync_expense_tier(contract["film_id"], agreement)

    calc.resync_collection_status(contract)
    touch(contract)
    return ok(milestone_out(milestone))


@bp.post("/payment-milestones/<milestone_id>/reverse-receipt")
@require_roles("CollectionAgent")
def reverse_receipt(milestone_id):
    milestone = get_milestone(milestone_id)
    payload = body()
    payload.req_string("reason")
    contract = get_contract(milestone["contract_id"])
    if milestone["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE")
    account = open_account_of_film(contract["film_id"])
    if account is None:
        raise ApiError("ERR_COLLECTION_ACCOUNT_NOT_OPEN")
    amount = q2(milestone["received_amount_usd"])
    if calc.account_balance(account) < amount:
        raise ApiError("ERR_RECEIPT_ALREADY_DISTRIBUTED")

    accrued = q2(milestone["accrued_commission_usd"])
    milestone["status"] = "INVOICED"
    milestone["received_amount_usd"] = ZERO2
    milestone["received_at"] = None
    milestone["received_by_user_id"] = None
    milestone["accrued_commission_usd"] = ZERO2
    touch(milestone)

    account["total_receipts_usd"] = q2(account["total_receipts_usd"] - amount)
    touch(account)

    agreement = calc.agreement_for_film(contract["film_id"])
    if agreement is not None:
        agreement["gross_collected_usd"] = q2(
            agreement["gross_collected_usd"] - amount
        )
        agreement["commission_earned_usd"] = q2(
            agreement["commission_earned_usd"] - accrued
        )
        touch(agreement)
    calc.resync_commission_tier(contract["film_id"], agreement)

    calc.resync_collection_status(contract)
    touch(contract)
    return ok(milestone_out(milestone))


# ------------------------------------------------------------- logical clock


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    payload = body()
    instant = payload.req_instant("to_iso8601")
    db.current_utc = instant
    return ok()
