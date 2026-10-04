"""Business logic: billing, theft pricing, SLA credits, utilization, order
totals, settlements, loaner allocation, jobsite counters, logical-clock
sweeps. All monetary math is integer cents; percentages rounded half-up."""
import calendar
import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from errors import loaner_pool_empty
from store import store

BILLABLE_STATUSES = ("REGISTERED", "DEPLOYED", "IN_TRANSIT", "IN_REPAIR")

SLA_DAYS = {"LIGHT": 3, "HEAVY": 5}
DAILY_CREDIT_CENTS = {"LIGHT": 2500, "HEAVY": 9000}
CREDIT_CAP_CENTS = 50000

DEDUCTIBLE_FLOOR_CENTS = 50000
DEDUCTIBLE_PCT = Decimal("0.10")
DEDUCTIBLE_CAP_CENTS = 250000
COVERAGE_CAP_CENTS = 1000000

BUYOUT_PCT = Decimal("0.20")
WORKDAY_MINUTES = 480


def add_months(dt, months):
    """dt + months whole months, clamping the day to the target month's end."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def billable_assets(agreement_id):
    return [a for a in store.assets.values()
            if a["agreement_id"] == agreement_id and a["status"] in BILLABLE_STATUSES]


def _select_rate_card(category, billing_dt):
    for rc in store.rate_cards.values():
        if (rc["tool_category"] == category and rc["status"] == "ACTIVE"
                and rc["effective_from"] <= billing_dt <= rc["effective_to"]):
            return rc
    return None


def compute_monthly_billing(agreement, prorate):
    """monthly_fleet_billing: tier split -> per-category min fee -> sum ->
    prorate -> single floor. Returns the billed amount in integer cents."""
    now = store.clock.now()
    counts = {}
    for a in billable_assets(agreement["id"]):
        model = store.tool_models[a["tool_model_id"]]
        counts[model["category"]] = counts.get(model["category"], 0) + 1

    subtotal = 0
    for category, n in counts.items():
        rc = _select_rate_card(category, now)
        if rc is None:
            continue
        t1 = min(n, rc["tier2_threshold"] - 1)
        t2 = (min(n - rc["tier2_threshold"] + 1,
                  rc["tier3_threshold"] - rc["tier2_threshold"])
              if n >= rc["tier2_threshold"] else 0)
        t3 = n - rc["tier3_threshold"] + 1 if n >= rc["tier3_threshold"] else 0
        charge = (t1 * rc["base_monthly_rate_cents"]
                  + t2 * rc["tier2_monthly_rate_cents"]
                  + t3 * rc["tier3_monthly_rate_cents"])
        charge = max(charge, rc["min_monthly_fee_cents"])
        subtotal += charge

    if prorate:
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        remaining = days_in_month - now.day + 1  # today through month end, inclusive
        subtotal = math.floor(subtotal * remaining / days_in_month)
    return int(subtotal)


def commit_billing(agreement, amount):
    agreement["billed_this_month_cents"] = amount
    if amount:
        acct = store.accounts[agreement["account_id"]]
        acct["outstanding_balance_cents"] = acct["outstanding_balance_cents"] + amount
        touch(acct)


def compute_sla_credit(ticket):
    """repair_turnaround_penalty: ceil breach days first, multiply, cap last."""
    model = store.tool_models[store.assets[ticket["asset_id"]]["tool_model_id"]]
    wc = model["weight_class"]
    raw_seconds = (ticket["closed_at"] - ticket["promised_return_by"]).total_seconds()
    if raw_seconds <= 0:
        return 0
    breach_days = math.ceil(raw_seconds / 86400.0)
    credit = breach_days * DAILY_CREDIT_CENTS[wc]
    return min(credit, CREDIT_CAP_CENTS)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_theft_cost(claim, asset, agreement):
    """theft_replacement_cost: age band -> depreciated value -> deductible
    (clamped) -> coverage-cap-limited approved value, floored at 0."""
    model = store.tool_models[asset["tool_model_id"]]
    days = (claim["reported_at"] - asset["commissioned_on"]).days
    age_months = days // 30
    if age_months <= 12:
        pct = Decimal("1.00")
    elif age_months <= 36:
        pct = Decimal("0.70")
    else:
        pct = Decimal("0.40")
    depreciated = round_half_up(Decimal(model["replacement_value_cents"]) * pct)
    deductible = round_half_up(DEDUCTIBLE_PCT * Decimal(depreciated))
    deductible = min(max(DEDUCTIBLE_FLOOR_CENTS, deductible), DEDUCTIBLE_CAP_CENTS)

    # running approved total over already-APPROVED claims on this agreement,
    # chronological by reported_at, ties by created_at
    prior = [c for c in store.theft_claims.values()
             if c["status"] == "APPROVED"
             and store.assets[c["asset_id"]]["agreement_id"] == agreement["id"]]
    prior.sort(key=lambda c: (c["reported_at"], c["created_at"]))
    running = sum(c["approved_replacement_value_cents"] for c in prior)

    approved = min(depreciated - deductible, COVERAGE_CAP_CENTS - running)
    approved = max(0, approved)
    return deductible, approved


def compute_utilization(agreement, mode):
    """fleet_utilization: mean over billable assets of per-asset pct, clamped
    per asset to [0,100], rounded half-up to 2 decimals."""
    now = store.clock.now()
    assets = billable_assets(agreement["id"])
    if not assets:
        return Decimal("0.00"), 0
    elapsed_days = now.day
    denom = elapsed_days * WORKDAY_MINUTES
    total = Decimal("0")
    for a in assets:
        pct = Decimal(a["utilization_minutes_current_month"]) / Decimal(denom) * 100
        if pct < 0:
            pct = Decimal("0")
        if pct > 100:
            pct = Decimal("100")
        total += pct
    mean = total / Decimal(len(assets))
    if mode == "PROJECTED":
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        mean = mean * Decimal(days_in_month) / Decimal(elapsed_days)
        if mean > 100:
            mean = Decimal("100")
        if mean < 0:
            mean = Decimal("0")
    return mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), len(assets)


def compute_order_total(order):
    """consumable_order_total: per line ceil to whole packs, then sum.
    Merging lines of one product before rounding is forbidden."""
    total = 0
    for line in order["lines"]:
        product = store.consumable_products[line["product_id"]]
        packs = (line["quantity_units"] + product["pack_size"] - 1) // product["pack_size"]
        total += packs * product["pack_size"] * product["unit_price_cents"]
    return total


def compute_settlement(agreement, option, assessed_damage_cents=None):
    """end_of_term_settlement over billable assets at computation time."""
    if option == "RENEWAL":
        return 0
    if option == "RETURN":
        return int(assessed_damage_cents or 0)
    # BUYOUT
    total = 0
    for a in billable_assets(agreement["id"]):
        model = store.tool_models[a["tool_model_id"]]
        total += round_half_up(Decimal(model["replacement_value_cents"]) * BUYOUT_PCT)
    return total


def allocate_loaner(tool_model_id):
    """loaner_allocation: AVAILABLE units of the model, oldest created_at
    first; empty pool raises ERR_LOANER_POOL_EMPTY."""
    eligible = [u for u in store.loaner_units.values()
                if u["status"] == "AVAILABLE" and u["tool_model_id"] == tool_model_id]
    if not eligible:
        raise loaner_pool_empty()
    eligible.sort(key=lambda u: u["created_at"])
    return eligible[0]


# ---- jobsite counter maintenance ----

def jobsite_inc(jobsite_id):
    js = store.jobsites.get(jobsite_id)
    if js:
        js["deployed_asset_count"] += 1
        touch(js)


def jobsite_dec(jobsite_id):
    js = store.jobsites.get(jobsite_id)
    if js:
        js["deployed_asset_count"] -= 1
        touch(js)


def touch(resource):
    resource["updated_at"] = store.clock.stamp()
    resource["version"] += 1


def add_balance(account, delta):
    account["outstanding_balance_cents"] = max(
        0, account["outstanding_balance_cents"] + delta)
    touch(account)


# ---- logical-clock sweeps ----

def advance_clock(new_dt):
    prev = store.clock.advance_to(new_dt)

    # theft-claim expiry sweep
    for claim in store.theft_claims.values():
        if claim["status"] == "REPORTED" and claim["reported_at"] + timedelta(hours=48) < new_dt:
            claim["status"] = "EXPIRED"
            touch(claim)

    # month-boundary sweep: crossing into a new calendar month
    if (prev.year, prev.month) != (new_dt.year, new_dt.month):
        for agreement in store.agreements.values():
            if agreement["status"] == "ACTIVE":
                amount = compute_monthly_billing(agreement, prorate=False)
                commit_billing(agreement, amount)
                touch(agreement)
        for asset in store.assets.values():
            if asset["utilization_minutes_current_month"]:
                asset["utilization_minutes_current_month"] = 0
                touch(asset)
    return new_dt
