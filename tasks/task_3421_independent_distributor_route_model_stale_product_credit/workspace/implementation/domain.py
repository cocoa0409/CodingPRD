"""Domain queries and lifecycle side effects shared by route modules."""
from datetime import timedelta

import calc
import clock
import store
from constants import (
    STRIKE_WINDOW_DAYS, STRIKE_SUSPEND_THRESHOLD, CLAIM_AUTO_EXPIRE_DAYS,
    AGREEMENT_LIVE_STATUSES, PROBATION_NUM, PROBATION_DEN,
)

# --- Entity lookup helpers ------------------------------------------------------


def agreements_of(distributor_id):
    return [a for a in store.all_of("agreements") if a["distributor_id"] == distributor_id]


def resolve_agreement(distributor_id, for_date=None, active_only=False):
    """The distributor's operative agreement.

    Prefers ACTIVE agreements (optionally the one whose half-open interval
    contains for_date), then falls back to the latest-created agreement.
    Returns None when the distributor has no agreements at all.
    """
    agreements = agreements_of(distributor_id)
    if not agreements:
        return None
    actives = [a for a in agreements if a["status"] == "ACTIVE"]
    if for_date is not None:
        covering = [a for a in actives if a["_start"] <= for_date < a["_end"]]
        if covering:
            return covering[0]
    if actives:
        return actives[0]
    if active_only:
        return None
    return agreements[-1]


def catalog_of(agreement):
    if agreement is None:
        return {}
    bakery = store.get("bakeries", agreement["bakery_id"])
    if bakery is None:
        return {}
    return {entry["sku"]: entry for entry in bakery["product_catalog"]}


def find_production_day(bakery_id, date_str):
    for day in store.all_of("production_days"):
        if day["bakery_id"] == bakery_id and day["date"] == date_str:
            return day
    return None


def plans_of_agreement(agreement_id):
    return [p for p in store.all_of("financing_plans") if p["agreement_id"] == agreement_id]


def live_plan_of(agreement_id):
    """Plan in ACTIVE or DELINQUENT for the agreement, if any."""
    for plan in plans_of_agreement(agreement_id):
        if plan["status"] in ("ACTIVE", "DELINQUENT"):
            return plan
    return None


# --- Order / claim quantity queries ----------------------------------------------


def orders_of(distributor_id):
    return [o for o in store.all_of("orders") if o["distributor_id"] == distributor_id]


def claims_of(distributor_id):
    return [c for c in store.all_of("stale_claims") if c["distributor_id"] == distributor_id]


def delivered_qty_for(distributor_id, sku, delivery_date):
    """Delivered units summed over DELIVERED/RECONCILED orders on that date."""
    total = 0
    for order in orders_of(distributor_id):
        if order["status"] not in ("DELIVERED", "RECONCILED"):
            continue
        if order["delivery_date"] != delivery_date:
            continue
        for line in order.get("delivered_lines") or []:
            if line["sku"] == sku:
                total += line["qty"]
    return total


def delivered_qty_any_date(distributor_id, sku):
    total = 0
    for order in orders_of(distributor_id):
        if order["status"] not in ("DELIVERED", "RECONCILED"):
            continue
        for line in order.get("delivered_lines") or []:
            if line["sku"] == sku:
                total += line["qty"]
    return total


def credited_qty_for(distributor_id, sku, delivery_date):
    """pulled_qty summed over APPROVED / CREDIT_ISSUED claims for (sku, date)."""
    total = 0
    for claim in claims_of(distributor_id):
        if claim["status"] not in ("APPROVED", "CREDIT_ISSUED"):
            continue
        for item in claim["items"]:
            if item["sku"] == sku and item["delivery_date"] == delivery_date:
                total += item["pulled_qty"]
    return total


# --- ISO week helpers --------------------------------------------------------------


def week_tuple_of(d):
    iso = d.isocalendar()
    return (iso[0], iso[1])


def week_str(wt):
    return f"{wt[0]}-W{wt[1]:02d}"


def parse_week(value):
    """Parse 'YYYY-Www' -> (year, week) or None."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split("-W")
    if len(parts) != 2:
        return None
    try:
        year, week = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if len(parts[0]) != 4 or len(parts[1]) != 2 or week < 1 or week > 53:
        return None
    return (year, week)


def date_in_week(d, wt):
    return week_tuple_of(d) == wt


# --- Stale credit ------------------------------------------------------------------


def claim_base_credit(items, agreement):
    """Uncapped stale credit over the given items (provisional == base)."""
    catalog = catalog_of(agreement)
    distributor_id = agreement["distributor_id"]
    total = 0
    for item in items:
        unit_charge = calc.unit_charge_cents(
            catalog[item["sku"]]["list_price_cents"], agreement["discount_pct"])
        eligible = min(
            item["pulled_qty"],
            delivered_qty_for(distributor_id, item["sku"], item["delivery_date"])
            - credited_qty_for(distributor_id, item["sku"], item["delivery_date"]),
        )
        eligible = max(eligible, 0)
        total += calc.stale_item_base_cents(eligible, unit_charge)
    return total


def weekly_stale_cap(distributor_id, week_t):
    """Returns (cap_cents, used_cents) for the distributor's ISO week."""
    gross = 0
    for order in orders_of(distributor_id):
        if order["status"] in ("DELIVERED", "RECONCILED") and order.get("_delivered_date"):
            if date_in_week(order["_delivered_date"], week_t):
                gross += order["total_charge_cents"] or 0
    used = 0
    for claim in claims_of(distributor_id):
        if claim["status"] == "CREDIT_ISSUED" and claim.get("_submitted_date"):
            if date_in_week(claim["_submitted_date"], week_t):
                used += claim["issued_credit_cents"] or 0
    return calc.stale_cap_cents(gross), used


# --- Account standing (PRD 2.9) -----------------------------------------------------


def compute_standing(distributor):
    balance = distributor["trade_balance_cents"]
    if balance * PROBATION_DEN > PROBATION_NUM * distributor["credit_limit_cents"]:
        return "PROBATION"
    for agreement in agreements_of(distributor["id"]):
        for plan in plans_of_agreement(agreement["id"]):
            if plan["status"] == "DELINQUENT":
                return "WATCH"
    return "GOOD"


def recompute_standing(distributor, always_bump=False):
    """Refresh account_standing; bump version always or only on change."""
    new_standing = compute_standing(distributor)
    if new_standing != distributor["account_standing"]:
        distributor["account_standing"] = new_standing
        store.touch(distributor)
    elif always_bump:
        store.touch(distributor)


# --- Audits and strikes --------------------------------------------------------------


def in_trailing_window(entry_date, anchor_date):
    """Trailing 90 calendar days ending on (and including) anchor_date."""
    delta = (anchor_date - entry_date).days
    return 0 <= delta <= STRIKE_WINDOW_DAYS - 1


def recompute_strikes(agreement, new_audit_date):
    count = 0
    for account in store.all_of("retail_accounts"):
        if account["distributor_id"] != agreement["distributor_id"]:
            continue
        for entry in account["audit_log"]:
            if entry["is_violation"] and in_trailing_window(entry["_audit_date"], new_audit_date):
                count += 1
    if agreement["strike_count"] != count:
        agreement["strike_count"] = count
        store.touch(agreement)
    return count


# --- Order / production-day capacity ---------------------------------------------------


def forecast_units(day):
    total = 0
    for order in store.all_of("orders"):
        if order["status"] not in ("DRAFT", "SUBMITTED", "CONFIRMED"):
            continue
        if order["delivery_date"] != day["date"]:
            continue
        agreement = store.get("agreements", order.get("_agreement_id") or "")
        if agreement is None or agreement["bakery_id"] != day["bakery_id"]:
            continue
        total += order["units_total"]
    return total


def release_reservation(order):
    agreement = store.get("agreements", order.get("_agreement_id") or "")
    if agreement is None:
        return
    day = find_production_day(agreement["bakery_id"], order["delivery_date"])
    if day is not None:
        day["allocated_units"] -= order["units_total"]
        store.touch(day)


def cancel_future_orders(agreement):
    """Suspension cascade: cancel SUBMITTED/CONFIRMED orders dated on/after today."""
    today = clock.today()
    for order in store.all_of("orders"):
        if order.get("_agreement_id") != agreement["id"]:
            continue
        if order["status"] not in ("SUBMITTED", "CONFIRMED"):
            continue
        if order["_delivery_date"] < today:
            continue
        was_confirmed = order["status"] == "CONFIRMED"
        order["status"] = "CANCELLED"
        order["cancelled_reason"] = "AGREEMENT_SUSPENDED"
        store.touch(order)
        if was_confirmed:
            release_reservation(order)


def suspend_agreement(agreement, reason):
    agreement["status"] = ("SUSPENDED_SERVICE" if reason == "SERVICE_DEFAULT"
                           else "SUSPENDED_CLASSIFICATION")
    agreement["suspension_reason"] = reason
    store.touch(agreement)
    if reason == "CLASSIFICATION_DISPUTE":
        distributor = store.get("distributors", agreement["distributor_id"])
        distributor["classification_status"] = "DISPUTED"
        store.touch(distributor)
    cancel_future_orders(agreement)


# --- Production-day close side effects -------------------------------------------------


def delinquency_evaluation(close_date):
    for plan in store.all_of("financing_plans"):
        if plan["status"] not in ("ACTIVE", "DELINQUENT"):
            continue
        weeks_elapsed = (close_date - plan["_disburse_date"]).days // 7
        scheduled_due = min(weeks_elapsed, plan["term_weeks"]) * plan["weekly_payment_cents"]
        delinquent = plan["total_paid_cents"] < scheduled_due - plan["weekly_payment_cents"]
        if delinquent and plan["status"] == "ACTIVE":
            plan["status"] = "DELINQUENT"
            store.touch(plan)
        elif not delinquent and plan["status"] == "DELINQUENT":
            plan["status"] = "ACTIVE"
            store.touch(plan)
        agreement = store.get("agreements", plan["agreement_id"])
        distributor = store.get("distributors", agreement["distributor_id"])
        recompute_standing(distributor, always_bump=True)


def auto_expire_claims(close_date):
    for claim in store.all_of("stale_claims"):
        if claim["status"] not in ("SUBMITTED", "NEEDS_INFO"):
            continue
        if (close_date - claim["_created_date"]).days > CLAIM_AUTO_EXPIRE_DAYS:
            claim["status"] = "DENIED"
            claim["denial_reason"] = "AUTO_EXPIRED"
            store.touch(claim)


# --- Exit and settlement ---------------------------------------------------------------


def create_transfer(agreement, mode, exit_date):
    """TerritoryTransfer with gross valuation per the mode-keyed variant."""
    activated_date = agreement["_activated_date"]
    full_years = max(0, (exit_date - activated_date).days) // 365
    depreciation = calc.depreciation_cents(agreement["purchase_price_cents"], full_years)
    compliant = 0
    for account in store.all_of("retail_accounts"):
        if account["distributor_id"] != agreement["distributor_id"]:
            continue
        has_violation = any(
            e["is_violation"] and in_trailing_window(e["_audit_date"], exit_date)
            for e in account["audit_log"]
        )
        if not has_violation:
            compliant += 1
    if mode == "VOLUNTARY":
        goodwill = calc.goodwill_cents(compliant)
        penalty = 0
    else:
        goodwill = 0
        penalty = calc.for_cause_penalty_cents(agreement["purchase_price_cents"])
    gross = agreement["purchase_price_cents"] - depreciation + goodwill - penalty
    return store.insert("transfers", {
        "agreement_id": agreement["id"],
        "mode": mode,
        "gross_valuation_cents": gross,
        "valuation_detail": {
            "depreciation_cents": depreciation,
            "goodwill_cents": goodwill,
            "penalty_cents": penalty,
        },
        "financing_payoff_cents": None,
        "distributor_payout_cents": None,
        "status": "PENDING",
        "settled_on": None,
    })


def begin_exit(agreement, mode):
    """Agreement -> EXITING with a PENDING transfer and territory -> EXITING."""
    agreement["status"] = "EXITING"
    agreement["exited_on"] = clock.iso()
    agreement["_exit_date"] = clock.today()
    store.touch(agreement)
    create_transfer(agreement, mode, clock.today())
    territory = store.get("territories", agreement["territory_id"])
    territory["status"] = "EXITING"
    store.touch(territory)


def settle_transfer(transfer):
    agreement = store.get("agreements", transfer["agreement_id"])
    settle_date = clock.today()
    plan = live_plan_of(agreement["id"])
    payoff = 0
    if plan is not None:
        last_accrual = plan["_last_payment_date"] or plan["_disburse_date"]
        days = (settle_date - last_accrual).days
        accrued = calc.accrued_interest_cents(
            plan["outstanding_principal_cents"], plan["annual_interest_rate"], days)
        payoff = plan["outstanding_principal_cents"] + accrued
        plan["status"] = "SETTLED_ON_EXIT"
        plan["outstanding_principal_cents"] = 0
        store.touch(plan)
    transfer["financing_payoff_cents"] = payoff
    transfer["distributor_payout_cents"] = transfer["gross_valuation_cents"] - payoff
    transfer["status"] = "SETTLED"
    transfer["settled_on"] = clock.iso()
    store.touch(transfer)
    agreement["status"] = "EXITED"
    store.touch(agreement)
    territory = store.get("territories", agreement["territory_id"])
    territory["status"] = "AVAILABLE"
    store.touch(territory)
    distributor = store.get("distributors", agreement["distributor_id"])
    remaining = [a for a in agreements_of(distributor["id"])
                 if a["status"] in AGREEMENT_LIVE_STATUSES]
    if not remaining:
        distributor["status"] = "EXITED"
        store.touch(distributor)
