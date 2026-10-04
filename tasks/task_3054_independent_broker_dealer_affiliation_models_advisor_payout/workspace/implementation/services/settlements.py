"""ExpensePassThrough and AdvisoryRevenueSplit (levelization) services."""

from db import (accounts, advisory_revenue_splits, expense_pass_throughs, iso_now,
                new_id, next_created_seq, parse_date, payout_periods,
                revenue_entries)
from errors import dec, fail, round_half_up
from services import advisors as advisor_service
from services import calc, common
from services import payout_periods as period_service


def serialize(row):
    return {key: value for key, value in row.items() if not key.startswith("_")}


# ---------------------------------------------------------------------------
# ExpensePassThrough (parent: Advisor)
# ---------------------------------------------------------------------------

EXPENSE_CATEGORIES = ("TECHNOLOGY", "CLEARING", "E_AND_O", "REGULATORY")
BILLING_MODELS = ("FLAT_MONTHLY", "PCT_OF_GROSS")


def find_expense_or_fail(expense_id):
    row = expense_pass_throughs.get(expense_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def create_expense(data):
    advisor_code = common.require_field(data, "advisor_code")
    period_id = common.require_field(data, "payout_period_id")
    category = common.require_field(data, "category")
    billing_model = common.require_field(data, "billing_model")
    advisor_service.get_by_code_or_fail(advisor_code)
    if period_service.payout_periods.get(period_id) is None:
        fail("ERR_NOT_FOUND")
    if category not in EXPENSE_CATEGORIES:
        fail("ERR_INVALID_REQUEST", "category is not a declared value.")
    if billing_model not in BILLING_MODELS:
        fail("ERR_INVALID_REQUEST", "billing_model is not a declared value.")
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_created_seq(),
        "advisor_code": advisor_code,
        "payout_period_id": period_id,
        "category": category,
        "billing_model": billing_model,
        "amount_cents": 0,
        "status": "PENDING",
    }
    expense_pass_throughs[row["id"]] = row
    return row


def move_expense_state(row, data):
    to_status = common.require_field(data, "to_status")
    if to_status not in ("POSTED", "WAIVED"):
        fail("ERR_INVALID_REQUEST", "to_status must be POSTED or WAIVED.")
    if row["status"] != "PENDING":
        fail("ERR_INVALID_STATE")
    row["status"] = to_status
    common.touch(row)
    if to_status == "POSTED":
        advisor = advisor_service.get_by_code_or_fail(row["advisor_code"])
        period = payout_periods.get(row["payout_period_id"])
        if period is not None:
            period_service.compute_settlement(advisor, period)
    return row


# ---------------------------------------------------------------------------
# AdvisoryRevenueSplit (parent: Account)
# ---------------------------------------------------------------------------

def find_split_or_fail(split_id):
    row = advisory_revenue_splits.get(split_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def brokerage_revenue_for(account_id, period):
    total = 0
    for entry in revenue_entries.values():
        if entry["account_id"] != account_id:
            continue
        if entry["product_type"] != "BROKERAGE_TRAIL":
            continue
        if entry["status"] not in ("RELEASED", "TRUE_UP_APPLIED"):
            continue
        when = parse_date(entry["production_date"])
        if when.year == period["year"] and when.month == period["month"]:
            total += int(entry["gross_commission_cents"])
    return total


def levelize(data):
    advisor_code = common.require_field(data, "advisor_code")
    period_id = common.require_field(data, "payout_period_id")
    advisor = advisor_service.get_by_code_or_fail(advisor_code)
    period = period_service.find_period_or_fail(period_id)

    eligible = []
    for account in accounts.values():
        if account["advisor_code"] != advisor_code:
            continue
        if account["account_type"] != "ADVISORY":
            continue
        if account["held_away"]:
            continue
        if account["fee_levelized"]:
            continue
        eligible.append(account)

    if not eligible:
        fail("ERR_YEAR_ALREADY_LEVELIZED")

    created = []
    for account in eligible:
        if account["base_annual_fee_cents"] is None:
            account["base_annual_fee_cents"] = int(account["annual_fee_cents"] or 0)
        base = int(account["base_annual_fee_cents"])
        balance = int(account["balance_cents"] or 0)
        if balance > 0:
            rafee = round_half_up(dec(base) * dec(10000) / dec(balance))
        else:
            rafee = 0
        account["rafee_effective_bps"] = rafee
        delta = round_half_up(dec(balance) * dec(calc.FEE_LEVEL_TARGET_BPS - rafee) / dec(10000))
        rebate_bps = calc.rebate_bps_for_portability(advisor["book_portability_pct"])
        # The levelization delta is computed against the account's *base* fee, so
        # an account already sitting at the 85-basis-point target yields a zero
        # delta (PRD 3.6).  The fee is rewritten only afterwards.
        advisory_revenue = round_half_up(dec(base) * dec(rebate_bps) / dec(10000)) + delta
        account["annual_fee_cents"] = base + delta
        advisory_revenue = min(advisory_revenue, calc.LEVELIZATION_FEE_CAP_CENTS)
        account["fee_levelized"] = True
        common.touch(account)

        row = {
            "id": new_id(),
            "created_at": iso_now(),
            "updated_at": iso_now(),
            "version": 1,
            "_seq": next_created_seq(),
            "account_id": account["id"],
            "payout_period_id": period_id,
            "advisory_fee_cents": account["annual_fee_cents"],
            "brokerage_revenue_cents": brokerage_revenue_for(account["id"], period),
            "advisory_revenue_cents": advisory_revenue,
            "levelization_delta_cents": delta,
            "status": "POSTED",
        }
        advisory_revenue_splits[row["id"]] = row
        created.append(row)
    advisor_service.derive(advisor)
    return created