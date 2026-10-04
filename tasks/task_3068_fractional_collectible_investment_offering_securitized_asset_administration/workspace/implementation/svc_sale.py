"""Holding decisions, sale execution, accruals, distributions, reconciliation."""
from envelope import ApiError, invalid_request, invalid_state, not_found, forbidden, stale
from catalog import HOLD_LAPSE_DAYS, CADENCE_DUE_DAYS, CADENCE_REQUIRED_DAYS
from store import DB, parse_dt, to_ms, add_days
from models import (make_holding_decision, make_accrual, make_distribution,
                    refresh_overview, insert_index, sort_by_creation)
from svc_common import (body, require, as_int, enum_value,
                        recompute_offering_shares, recompute_offering_cash)
from calc import (waterfall, bps_floor, day_gap, cadence_flag, management_fee,
                  presentation_amount)
import views


def _offering(offering_id):
    row = DB.offerings.get(offering_id)
    if row is None:
        raise not_found("Offering %s does not exist." % offering_id)
    return row


def _artwork(offering):
    return DB.artworks.get(offering["artwork_id"])


def _occ(data, offering):
    expected = as_int(data, "expected_offering_version")
    if expected is not None and int(expected) != int(offering["version"]):
        raise stale("expected_offering_version does not match the offering's version.")


def _actor():
    from flask import g
    return getattr(g, "user_id", None)


def _artwork_by_id(artwork_id):
    return DB.artworks.get(artwork_id)


# ---------------------------------------------------------------------------
# HoldingDecision
# ---------------------------------------------------------------------------

def raise_decision(offering_id):
    offering = _offering(offering_id)
    data = body()
    require(data, ["decision_type"])
    dtype = enum_value(data, "decision_type", "decision_type")
    if dtype == "SELL":
        proposed = as_int(data, "proposed_gross_cents", minimum=0)
        if proposed is None:
            raise invalid_request("proposed_gross_cents is required for a SELL decision.")
    else:
        proposed = None
        if data.get("proposed_gross_cents") is not None:
            raise invalid_request("proposed_gross_cents must be null for a HOLD decision.")
    if offering["status"] not in ("ALLOCATED", "HELD"):
        raise invalid_state("A holding decision requires an ALLOCATED or HELD offering.")
    artwork = _artwork(offering)
    row = make_holding_decision(offering, {**data, "proposed_gross_cents": proposed},
                                _actor())
    now = to_ms(DB.now())
    if dtype == "HOLD":
        row["status"] = "APPROVED"
        row["approved_by_user_id"] = _actor()
        offering["status"] = "ALLOCATED"
        offering["updated_at"] = now
        offering["version"] = int(offering["version"]) + 1
    return views.holding_decision(row), 201


def get_decision(decision_id):
    row = DB.holding_decisions.get(decision_id)
    if row is None:
        raise not_found("HoldingDecision %s does not exist." % decision_id)
    return views.holding_decision(row)


def list_decisions(offering_id, query):
    _offering(offering_id)
    rows = [r for r in DB.ordered("holding_decisions") if r["offering_id"] == offering_id]
    status = query.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def approve_decision(decision_id):
    row = DB.holding_decisions.get(decision_id)
    if row is None:
        raise not_found("HoldingDecision %s does not exist." % decision_id)
    offering = _offering(row["offering_id"])
    data = body()
    if row["decision_type"] == "SELL":
        if row["status"] != "PENDING":
            raise invalid_state("Only a PENDING SELL decision can be approved.")
        end = parse_dt(offering.get("holding_period_end_at"))
        if end is None or parse_dt(DB.now()) < end:
            raise ApiError("ERR_HOLD_PERIOD_ACTIVE",
                           "The holding period has not run; the sale cannot be approved.")
        if _actor() == row.get("created_by_user_id"):
            raise forbidden("The officer who raised the decision may not approve it.")
        _occ(data, offering)
        now = to_ms(DB.now())
        row["status"] = "APPROVED"
        row["approved_by_user_id"] = _actor()
        row["updated_at"] = now
        row["version"] = int(row.get("version") or 1) + 1
        offering["status"] = "SALE_PENDING"
        offering["updated_at"] = now
        offering["version"] = int(offering["version"]) + 1
        artwork = _artwork(offering)
        artwork["status"] = "SALE_PENDING"
        refresh_overview(artwork, bump=True)
        return views.holding_decision(row)

    if offering["status"] not in ("ALLOCATED", "HELD"):
        raise invalid_state("A HOLD approval requires an ALLOCATED or HELD offering.")
    if row["status"] != "PENDING":
        raise invalid_state("Only a PENDING HOLD decision can be approved.")
    now = to_ms(DB.now())
    row["status"] = "APPROVED"
    row["approved_by_user_id"] = _actor()
    row["updated_at"] = now
    row["version"] = int(row.get("version") or 1) + 1
    offering["status"] = "ALLOCATED"
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    return views.holding_decision(row)


def reject_decision(decision_id):
    row = DB.holding_decisions.get(decision_id)
    if row is None:
        raise not_found("HoldingDecision %s does not exist." % decision_id)
    offering = _offering(row["offering_id"])
    data = body()
    _occ(data, offering)
    if row["status"] == "APPROVED":
        if _actor() == row.get("approved_by_user_id"):
            raise forbidden("The officer who approved the decision may not overturn it.")
        row["status"] = "REJECTED"
        if offering["status"] == "SALE_PENDING":
            offering["status"] = "ALLOCATED"
            artwork = _artwork(offering)
            artwork["status"] = "HELD"
            refresh_overview(artwork, bump=True)
    elif row["status"] == "PENDING":
        row["status"] = "REJECTED"
    else:
        raise invalid_state("Only an APPROVED or PENDING decision can be rejected.")
    now = to_ms(DB.now())
    row["updated_at"] = now
    row["version"] = int(row.get("version") or 1) + 1
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    return views.holding_decision(row)


def revise_decision(decision_id):
    row = DB.holding_decisions.get(decision_id)
    if row is None:
        raise not_found("HoldingDecision %s does not exist." % decision_id)
    data = body()
    require(data, ["proposed_gross_cents"])
    proposed = as_int(data, "proposed_gross_cents", minimum=0)
    if row["status"] != "REJECTED":
        raise invalid_state("Only a REJECTED decision can be revised.")
    offering = _offering(row["offering_id"])
    now = to_ms(DB.now())
    row["status"] = "PENDING"
    row["proposed_gross_cents"] = proposed
    row["updated_at"] = now
    row["version"] = int(row.get("version") or 1) + 1
    offering["status"] = "ALLOCATED"
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    return views.holding_decision(row)

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def execute_sale(decision_id):
    row = DB.holding_decisions.get(decision_id)
    if row is None:
        raise not_found("HoldingDecision %s does not exist." % decision_id)
    data = body()
    require(data, ["executed_gross_cents"])
    gross = as_int(data, "executed_gross_cents", minimum=0)
    offering = _offering(row["offering_id"])
    artwork = _artwork(offering)
    if row["status"] != "APPROVED":
        raise invalid_state("Only an APPROVED decision can be executed.")
    if offering["status"] != "SALE_PENDING":
        raise invalid_state("Execution requires the offering to be SALE_PENDING.")
    _occ(data, offering)
    now = to_ms(DB.now())

    if int(gross) < int(artwork["reserve_price_cents"]):
        row["status"] = "FAILED"
        row["executed_gross_cents"] = int(gross)
        row["updated_at"] = now
        row["version"] = int(row.get("version") or 1) + 1
        offering["status"] = "ALLOCATED"
        offering["updated_at"] = now
        offering["version"] = int(offering["version"]) + 1
        artwork["status"] = "HELD"
        refresh_overview(artwork, bump=True)
        return views.holding_decision(row)

    # the management fee is accrued again at the moment of execution
    _current_management(offering, artwork)

    start = parse_dt(offering.get("holding_clock_started_at"))
    held_for_days = (parse_dt(now) - start).days if start is not None else 0
    wf = waterfall(offering, artwork, int(gross), held_for_days)
    distribution = make_distribution(offering, wf)

    row["status"] = "EXECUTED"
    row["executed_gross_cents"] = int(gross)
    row["updated_at"] = now
    row["version"] = int(row.get("version") or 1) + 1
    offering["status"] = "CLOSED"
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    artwork["status"] = "SOLD"
    refresh_overview(artwork, bump=True)
    return views.holding_decision(row)


# ---------------------------------------------------------------------------
# FeeAccrual
# ---------------------------------------------------------------------------

def _holding_days_pair(offering):
    start = parse_dt(offering.get("holding_clock_started_at"))
    end = parse_dt(offering.get("holding_period_end_at"))
    if start is None or end is None:
        return None, None, None
    plain = (end - start).days
    return plain, plain + 1, start


def _accrue_management(offering, artwork):
    presentation_days, settle_days, start = _holding_days_pair(offering)
    if presentation_days is None:
        start = parse_dt(offering.get("holding_clock_started_at"))
        presentation_days, settle_days = 0, 0
    value = int(artwork.get("last_appraised_value_cents") or 0)
    presentation = presentation_amount(value, offering["management_fee_bps"],
                                       presentation_days)
    settle = management_fee(value, offering["management_fee_bps"], settle_days)
    return make_accrual(offering, "MANAGEMENT", value, presentation, settle)


def _current_management(offering, artwork):
    """The management fee accrued a second time at the moment of execution:
    the same reading, but taken over the days elapsed so far."""
    start = parse_dt(offering.get("holding_clock_started_at"))
    days = (parse_dt(DB.now()) - start).days if start is not None else 0
    value = int(artwork.get("last_appraised_value_cents") or 0)
    presentation = presentation_amount(value, offering["management_fee_bps"], days)
    settle = management_fee(value, offering["management_fee_bps"], days)
    return make_accrual(offering, "MANAGEMENT", value, presentation, settle)


def accrue_fees(offering_id):
    offering = _offering(offering_id)
    data = body()
    require(data, ["accrual_type"])
    kind = enum_value(data, "accrual_type", "accrual_type")
    artwork = _artwork(offering)
    if kind == "MANAGEMENT":
        row = _accrue_management(offering, artwork)
    else:
        if offering["status"] != "CLOSED":
            raise ApiError("ERR_ACCRUAL_TYPE_UNSUPPORTED",
                           "Profit participation requires a closed sale cycle.")
        dist = None
        for d in DB.distributions.values():
            if d["offering_id"] == offering_id:
                dist = d
        basis = int(dist["distributable_cents"]) if dist else 0
        participation = bps_floor(basis, offering["profit_participation_bps"])
        row = make_accrual(offering, "PROFIT_PARTICIPATION", basis,
                           participation, participation)
    offering["updated_at"] = to_ms(DB.now())
    offering["version"] = int(offering["version"]) + 1
    return {
        "accrual_id": row["id"],
        "accrual_type": row["accrual_type"],
        "basis_value_cents": row["basis_value_cents"],
        "presentation_amount_cents": row["presentation_amount_cents"],
        "settle_amount_cents": row["settle_amount_cents"],
        "amount_cents": row["amount_cents"],
        "accrued_at": row["accrued_at"],
    }, 201


def list_accruals(offering_id, query):
    _offering(offering_id)
    rows = [r for r in DB.ordered("fee_accruals") if r["offering_id"] == offering_id]
    kind = query.get("accrual_type")
    if kind:
        rows = [r for r in rows if r["accrual_type"] == kind]
    return rows


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

def list_distributions(offering_id, query):
    _offering(offering_id)
    rows = [r for r in DB.ordered("distributions") if r["offering_id"] == offering_id]
    status = query.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def pay_distribution(offering_id, distribution_id):
    offering = _offering(offering_id)
    dist = DB.distributions.get(distribution_id)
    if dist is None or dist["offering_id"] != offering_id:
        raise not_found("Distribution %s does not exist under this offering."
                        % distribution_id)
    data = body()
    _occ(data, offering)
    if dist["status"] != "CALCULATED":
        raise invalid_state("Only a CALCULATED distribution can be paid.")
    amount = int(dist["investor_residual_cents"])
    account = next(iter(DB.platform_accounts.values()), None)
    if account is not None:
        if int(account["balance_cents"]) - amount < 0:
            raise ApiError("ERR_ACCOUNT_UNDERFUNDED",
                           "The payment would take the account below zero.")
        account["balance_cents"] = int(account["balance_cents"]) - amount
        account["total_paid_out_cents"] = int(account["total_paid_out_cents"]) + amount
        account["updated_at"] = to_ms(DB.now())
        account["version"] = int(account.get("version") or 1) + 1
    now = to_ms(DB.now())
    dist["status"] = "PAID"
    dist["updated_at"] = now
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    return views.distribution(dist)


# ---------------------------------------------------------------------------
# reconciliation
# ---------------------------------------------------------------------------

def reconcile_cadence(offering_id):
    offering = _offering(offering_id)
    artwork = _artwork(offering)
    now = to_ms(DB.now())
    gap = day_gap(now, artwork.get("last_appraisal_at"))
    flag = cadence_flag(gap)
    lapsed = 0
    for order in DB.transfer_orders.values():
        if order["offering_id"] != offering_id or order["status"] != "OPEN":
            continue
        age = day_gap(now, order.get("created_at"))
        if age is not None and age >= HOLD_LAPSE_DAYS:
            order["status"] = "LAPSED"
            order["updated_at"] = now
            order["version"] = int(order.get("version") or 1) + 1
            lapsed += 1
    if lapsed:
        offer = DB.offerings.get(offering_id)
        offer["updated_at"] = now
        offer["version"] = int(offer["version"]) + 1
        from svc_common import recompute_lots
        recompute_lots(offer)
    return {
        "appraisal_flag": flag,
        "gap_days": gap,
        "lapsed_transfer_orders": lapsed,
        "next_appraisal_due_at": artwork.get("next_appraisal_due_at"),
    }


# ---------------------------------------------------------------------------
# PlatformAccount / clock
# ---------------------------------------------------------------------------

def open_platform_account():
    from models import make_platform_account
    data = body()
    require(data, ["account_name"])
    row = make_platform_account(data)
    return views.platform_account(row), 201


def credit_platform_account(amount_cents):
    """Credit the segregated account (matching side of a collected debit)."""
    account = next(iter(DB.platform_accounts.values()), None)
    if account is None:
        return None
    account["balance_cents"] = int(account["balance_cents"]) + int(amount_cents)
    account["investor_funds_held_cents"] = (
        int(account["investor_funds_held_cents"]) + int(amount_cents))
    account["updated_at"] = to_ms(DB.now())
    account["version"] = int(account.get("version") or 1) + 1
    return account


def release_investor_funds(amount_cents):
    """A refund draws the refunded money back out of both the balance and the
    segregated subset, so the balance never exceeds the sum of its parts."""
    account = next(iter(DB.platform_accounts.values()), None)
    if account is None:
        return None
    amount = int(amount_cents)
    held = int(account["investor_funds_held_cents"])
    account["investor_funds_held_cents"] = max(0, held - amount)
    account["balance_cents"] = max(0, int(account["balance_cents"]) - amount)
    account["updated_at"] = to_ms(DB.now())
    account["version"] = int(account.get("version") or 1) + 1
    return account


def get_platform_account(account_id):
    row = DB.platform_accounts.get(account_id)
    if row is None:
        raise not_found("PlatformAccount %s does not exist." % account_id)
    return views.platform_account(row)


def set_clock():
    data = body()
    require(data, ["current_utc"])
    from svc_common import body_datetime
    when = body_datetime(data, "current_utc")
    DB.advance(when)
    from store import fmt_dt
    return {"current_utc": fmt_dt(DB.now())}
