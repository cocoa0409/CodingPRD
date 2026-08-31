"""Business logic: dealer roll-up, ledger, pricing engine, chargeback,
buyback snapshot, scorecard, fair lending, and the cascade helpers."""
from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from core import (
    store, clock, new_rec, bump, stamp, putdt, dtv, fail, rhu, rhu2, F,
    days_between, months_from_days,
    PROGRAM_MAX_MARKUP_BPS, PARTICIPATION_FACTOR, FLAT_FEE_BPS, INCENTIVE_BPS,
    INCENTIVE_CAP_CENTS, PROGRAM_RESERVE_CAP_CENTS, BUYBACK_ADMIN_FEE_CENTS,
    EARLY_PAYOFF_SEASONING_MONTHS, PROBATION_MIN_FUNDED_COUNT,
    PROBATION_EARLY_PAYOFF_RATE_BPS, MARKUP_BENCHMARK_BPS,
    W_DEFAULT, W_EARLY, W_DOC, W_MARKUP, MIN_REVIEW_POPULATION,
    DISPARITY_THRESHOLD_BPS, BASE_REQUIRED_DOC_TYPES,
)

OPEN_APP_STATUSES = ("SUBMITTED", "CONDITIONED", "RESUBMITTED", "APPROVED")
SCORED_FUNDING_STATUSES = ("FUNDED", "PAID_OFF", "DEFAULTED", "REPURCHASED")
OPEN_DEMAND_STATUSES = ("ISSUED", "ACKNOWLEDGED", "DISPUTED")


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def _ordered(values):
    return sorted(values, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))


def dealer_agreements(dealer_id):
    return _ordered([a for a in store.agreements.values() if a["dealer_id"] == dealer_id])


def dealer_applications(dealer_id):
    return _ordered([a for a in store.applications.values() if a["dealer_id"] == dealer_id])


def dealer_contracts(dealer_id):
    return _ordered([c for c in store.contracts.values() if c["dealer_id"] == dealer_id])


def dealer_entries(dealer_id):
    return _ordered([e for e in store.entries.values() if e["dealer_id"] == dealer_id])


def contract_entries(contract_id):
    return _ordered([e for e in store.entries.values() if e.get("contract_id") == contract_id])


def contract_documents(contract_id):
    return _ordered([d for d in store.documents.values() if d["contract_id"] == contract_id])


def dealer_reviews(dealer_id):
    return _ordered([r for r in store.reviews.values() if r["dealer_id"] == dealer_id])


def sheet_tiers(sheet_id):
    """Tier rows in demotion-walk order: min_credit_score DESC, tier_code ASC."""
    rows = [t for t in store.tiers.values() if t["rate_sheet_id"] == sheet_id]
    return sorted(rows, key=lambda t: (-t["min_credit_score"], t["tier_code"]))


# ---------------------------------------------------------------------------
# Dealer roll-up (PRD 2.8)
# ---------------------------------------------------------------------------
def recompute_reserve_balance(dealer):
    dealer["reserve_balance_cents"] = sum(
        e["amount_cents"] for e in store.entries.values() if e["dealer_id"] == dealer["id"]
    )


def recompute_exposure(dealer):
    funded = [
        c for c in store.contracts.values()
        if c["dealer_id"] == dealer["id"] and c["funding_status"] == "FUNDED"
    ]
    dealer["outstanding_principal_cents"] = sum(c["unpaid_principal_cents"] for c in funded)
    dealer["funded_contract_count"] = len(funded)


def recompute_early_payoff_rate(dealer):
    total = dealer["total_funded_ever_count"]
    if total > 0:
        dealer["early_payoff_rate_bps"] = rhu(Fraction(10000 * dealer["early_payoff_count"], total))
    else:
        dealer["early_payoff_rate_bps"] = 0


def post_entry(dealer, contract_id, entry_type, amount_cents, reason):
    entry = new_rec(versioned=False)
    entry["dealer_id"] = dealer["id"]
    entry["contract_id"] = contract_id
    entry["entry_type"] = entry_type
    entry["amount_cents"] = amount_cents
    entry["reason"] = reason
    entry["balance_after_cents"] = 0
    store.entries[entry["id"]] = entry
    recompute_reserve_balance(dealer)
    entry["balance_after_cents"] = dealer["reserve_balance_cents"]
    return entry


def hold_open_applications(dealer):
    for app in dealer_applications(dealer["id"]):
        if app["status"] in OPEN_APP_STATUSES:
            app["held_from_status"] = app["status"]
            app["status"] = "ON_HOLD"
            bump(app)


def release_held_applications(dealer):
    for app in dealer_applications(dealer["id"]):
        if app["status"] == "ON_HOLD":
            app["status"] = app.get("held_from_status") or "SUBMITTED"
            app["held_from_status"] = None
            bump(app)


def auto_suspend(dealer, reason):
    dealer["status"] = "SUSPENDED"
    dealer["suspension_reason"] = reason
    hold_open_applications(dealer)


# ---------------------------------------------------------------------------
# Amortization convention (PRD 3.5)
# ---------------------------------------------------------------------------
def straight_line_unpaid(contract, months_seasoned):
    term = contract["term_months"]
    capped = min(months_seasoned, term)
    if capped < 0:
        capped = 0
    repaid = rhu(Fraction(contract["amount_financed_cents"] * capped, term))
    return contract["amount_financed_cents"] - repaid


# ---------------------------------------------------------------------------
# Dealer participation (PRD 3.5) - dealer_reserve_amount
# ---------------------------------------------------------------------------
def eligible_markup_bps(contract, agreement):
    return min(contract["markup_bps"], agreement["max_participation_bps"], PROGRAM_MAX_MARKUP_BPS)


def participation_gross(contract, agreement, basis_months):
    eligible = eligible_markup_bps(contract, agreement)
    if agreement["participation_method"] == "RATE_PARTICIPATION":
        value = (Fraction(contract["amount_financed_cents"])
                 * Fraction(eligible, 10000)
                 * Fraction(basis_months, 12)
                 * PARTICIPATION_FACTOR)
        return rhu(value)
    flat = rhu(Fraction(contract["amount_financed_cents"] * FLAT_FEE_BPS, 10000))
    return min(agreement["flat_fee_cap_cents"], flat)


def reserve_accrued(contract, agreement, basis_months):
    return min(participation_gross(contract, agreement, basis_months), PROGRAM_RESERVE_CAP_CENTS)


def incentive_accrued(contract):
    raw = rhu(Fraction(contract["amount_financed_cents"] * INCENTIVE_BPS, 10000))
    return min(raw, INCENTIVE_CAP_CENTS)


# ---------------------------------------------------------------------------
# Reserve chargeback (PRD 3.6)
# ---------------------------------------------------------------------------
def compute_chargeback(contract, agreement, months_seasoned):
    window_months = agreement["chargeback_window_days"] // 30
    within = months_seasoned < window_months
    if not within:
        return window_months, within, 0, 0, 0
    unearned = Fraction(window_months - months_seasoned, window_months)
    participation_entry = 0
    incentive_entry = 0
    for entry in contract_entries(contract["id"]):
        if entry["entry_type"] == "PARTICIPATION_ACCRUAL":
            participation_entry += entry["amount_cents"]
        elif entry["entry_type"] == "INCENTIVE_ACCRUAL":
            incentive_entry += entry["amount_cents"]
    participation_cb = rhu(Fraction(participation_entry) * unearned)
    incentive_cb = rhu(Fraction(incentive_entry) * unearned)
    total = participation_cb + incentive_cb
    net_posted = sum(e["amount_cents"] for e in contract_entries(contract["id"]))
    if total > net_posted:
        total = net_posted
    return window_months, within, participation_cb, incentive_cb, total


# ---------------------------------------------------------------------------
# Buyback snapshot (PRD 3.7) - buyback_settlement_amount
# ---------------------------------------------------------------------------
def buyback_snapshot(contract):
    funded_at = dtv(contract, "funded_at")
    months = months_from_days(funded_at, clock.now())
    if months < 0:
        months = 0
    unpaid = straight_line_unpaid(contract, months)
    offset = sum(e["amount_cents"] for e in contract_entries(contract["id"]))
    admin_fee = BUYBACK_ADMIN_FEE_CENTS
    return unpaid, offset, admin_fee, unpaid + offset + admin_fee


def issue_demand(dealer, contract, reason):
    demand = new_rec()
    demand["contract_id"] = contract["id"]
    demand["dealer_id"] = dealer["id"]
    demand["reason"] = reason
    demand["status"] = "ISSUED"
    unpaid, offset, admin_fee, total = buyback_snapshot(contract)
    demand["unpaid_principal_cents"] = unpaid
    demand["reserve_offset_cents"] = offset
    demand["admin_fee_cents"] = admin_fee
    demand["buyback_amount_cents"] = total
    demand["dispute_reason"] = None
    stamp(demand, "settled_at", None)
    store.demands[demand["id"]] = demand
    if contract["reserve_status"] == "ACCRUED":
        contract["reserve_status"] = "HELD"
        bump(contract)
    return demand


def has_open_demand(contract_id):
    for demand in store.demands.values():
        if demand["contract_id"] == contract_id and demand["status"] in OPEN_DEMAND_STATUSES:
            return True
    return False


# ---------------------------------------------------------------------------
# Dealer termination cascade (PRD 3.9)
# ---------------------------------------------------------------------------
def terminate_dealer(dealer, reason):
    # Link one
    dealer["status"] = "TERMINATED"
    dealer["suspension_reason"] = reason if reason else "TERMINATION"

    # Link two
    terminated_agreements = []
    for agreement in dealer_agreements(dealer["id"]):
        if agreement["status"] in ("PENDING_COUNTERSIGN", "ACTIVE"):
            agreement["status"] = "TERMINATED"
            bump(agreement)
            terminated_agreements.append(agreement["id"])

    # Link three
    for app in dealer_applications(dealer["id"]):
        pinned = app.get("agreement_id")
        if pinned in terminated_agreements or pinned is None:
            if app["status"] in ("SUBMITTED", "CONDITIONED", "RESUBMITTED", "APPROVED", "ON_HOLD"):
                app["status"] = "WITHDRAWN"
                app["held_from_status"] = None
                bump(app)

    # Link four / five
    candidates = []
    for contract in dealer_contracts(dealer["id"]):
        if contract["funding_status"] != "FUNDED":
            continue
        agreement = store.agreements.get(contract["agreement_id"])
        if agreement is None:
            continue
        window_months = agreement["chargeback_window_days"] // 30
        funded_at = dtv(contract, "funded_at")
        if funded_at is None:
            continue
        seasoning = months_from_days(funded_at, clock.now())
        if seasoning < window_months and not has_open_demand(contract["id"]):
            candidates.append(contract)
    candidates.sort(key=lambda c: (c.get("funded_at") or "", c.get("created_at") or "", c.get("_seq") or 0))
    for contract in candidates:
        issue_demand(dealer, contract, "DEALER_TERMINATION")


# ---------------------------------------------------------------------------
# Tier assignment and buy rate (PRD 3.3) - tier_assignment_and_buy_rate
# ---------------------------------------------------------------------------
def select_rate_sheet(dealer):
    now = clock.now()
    candidates = []
    for sheet in store.sheets.values():
        if sheet["status"] != "PUBLISHED":
            continue
        if sheet["program_code"] != dealer["program_code"]:
            continue
        if dtv(sheet, "effective_from") <= now < dtv(sheet, "effective_to"):
            candidates.append(sheet)
    if not candidates:
        return None
    candidates.sort(key=lambda s: (dtv(s, "effective_from"), s.get("created_at") or "", s.get("_seq") or 0),
                    reverse=True)
    return candidates[0]


def select_agreement(dealer):
    now = clock.now()
    candidates = []
    for agreement in store.agreements.values():
        if agreement["dealer_id"] != dealer["id"]:
            continue
        if agreement["status"] != "ACTIVE":
            continue
        if dtv(agreement, "effective_from") <= now <= dtv(agreement, "effective_to"):
            candidates.append(agreement)
    if not candidates:
        return None
    candidates.sort(key=lambda a: (dtv(a, "effective_from"), a.get("created_at") or "", a.get("_seq") or 0),
                    reverse=True)
    return candidates[0]


def compute_ratios(app):
    ltv = rhu2(Fraction(app["amount_financed_cents"] * 100, app["collateral_value_cents"]))
    dti = rhu2(Fraction(app["monthly_debt_cents"] * 100, app["monthly_income_cents"]))
    app["_ltv_dec"] = ltv
    app["_dti_dec"] = dti
    app["ltv_pct"] = float(ltv)
    app["dti_pct"] = float(dti)


def ltv_decimal(app):
    value = app.get("_ltv_dec")
    if value is None:
        value = Decimal(str(app["ltv_pct"]))
    return value


def dti_decimal(app):
    value = app.get("_dti_dec")
    if value is None:
        value = Decimal(str(app["dti_pct"]))
    return value


# ---------------------------------------------------------------------------
# Dealer scorecard (PRD 3.8) - dealer_scorecard_composite
# ---------------------------------------------------------------------------
def scorecard_population(dealer_id, basis, period_start, period_end):
    population = []
    for contract in dealer_contracts(dealer_id):
        if contract["funding_status"] not in SCORED_FUNDING_STATUSES:
            continue
        if basis == "TRAILING_WINDOW":
            funded_at = dtv(contract, "funded_at")
            if funded_at is None:
                continue
            if not (period_start <= funded_at < period_end):
                continue
        population.append(contract)
    return population


def compute_scorecard(card, population):
    count = len(population)
    card["population_count"] = count
    if count == 0:
        card["default_rate_bps"] = 0
        card["early_payoff_rate_bps"] = 0
        card["doc_defect_rate_bps"] = 0
        card["avg_markup_bps"] = 0
        card["composite_score"] = None
        card["grade"] = "UNRATED"
        return

    defaulted = sum(1 for c in population if c["funding_status"] == "DEFAULTED")
    early = sum(1 for c in population
                if c["funding_status"] == "PAID_OFF"
                and c.get("payoff_months_seasoned") is not None
                and c["payoff_months_seasoned"] < EARLY_PAYOFF_SEASONING_MONTHS)
    defect = sum(1 for c in population if c["doc_defect_count"] > 0)

    default_rate = rhu(Fraction(10000 * defaulted, count))
    early_rate = rhu(Fraction(10000 * early, count))
    defect_rate = rhu(Fraction(10000 * defect, count))
    avg_markup = rhu(Fraction(sum(c["markup_bps"] for c in population), count))

    card["default_rate_bps"] = default_rate
    card["early_payoff_rate_bps"] = early_rate
    card["doc_defect_rate_bps"] = defect_rate
    card["avg_markup_bps"] = avg_markup

    d1 = rhu(W_DEFAULT * Fraction(default_rate, 100))
    d2 = rhu(W_EARLY * Fraction(early_rate, 100))
    d3 = rhu(W_DOC * Fraction(defect_rate, 100))
    excess = avg_markup - MARKUP_BENCHMARK_BPS
    if excess < 0:
        excess = 0
    d4 = rhu(W_MARKUP * Fraction(excess, 10))

    score = 1000 - d1 - d2 - d3 - d4
    score = max(0, min(1000, score))
    card["composite_score"] = score
    if score >= 850:
        card["grade"] = "A"
    elif score >= 700:
        card["grade"] = "B"
    elif score >= 550:
        card["grade"] = "C"
    else:
        card["grade"] = "D"


# ---------------------------------------------------------------------------
# Fair lending markup disparity (PRD 3.8) - fair_lending_markup_disparity
# ---------------------------------------------------------------------------
def review_population(dealer_id, window_start, window_end):
    population = []
    for contract in dealer_contracts(dealer_id):
        if contract["funding_status"] not in SCORED_FUNDING_STATUSES:
            continue
        funded_at = dtv(contract, "funded_at")
        if funded_at is None:
            continue
        if window_start <= funded_at < window_end:
            population.append(contract)
    return population


def compute_review(review, population):
    count = len(population)
    review["population_count"] = count

    weighted = sum(c["markup_bps"] * c["amount_financed_cents"] for c in population)
    total_amount = sum(c["amount_financed_cents"] for c in population)
    benchmark = rhu(Fraction(weighted, total_amount)) if total_amount else 0
    review["benchmark_markup_bps"] = benchmark

    control = [c for c in population if c["monitoring_cohort"] == "CONTROL"]
    monitored = [c for c in population if c["monitoring_cohort"] == "MONITORED"]
    control_avg = rhu(Fraction(sum(c["markup_bps"] for c in control), len(control))) if control else 0
    monitored_avg = rhu(Fraction(sum(c["markup_bps"] for c in monitored), len(monitored))) if monitored else 0
    review["control_avg_markup_bps"] = control_avg
    review["monitored_avg_markup_bps"] = monitored_avg

    disparity = monitored_avg - control_avg
    review["disparity_bps"] = disparity
    finding = "EXCEEDS_THRESHOLD" if disparity > DISPARITY_THRESHOLD_BPS else "WITHIN_TOLERANCE"
    review["finding"] = finding

    if finding == "WITHIN_TOLERANCE":
        review["remediation_pool_cents"] = 0
        return

    ordered = sorted(monitored, key=lambda c: (c.get("funded_at") or "",
                                               c.get("created_at") or "",
                                               c.get("_seq") or 0))
    pool = 0
    for contract in ordered:
        excess = contract["markup_bps"] - benchmark
        if excess < 0:
            excess = 0
        value = (Fraction(contract["amount_financed_cents"])
                 * Fraction(excess, 10000)
                 * Fraction(contract["term_months"], 12)
                 * PARTICIPATION_FACTOR)
        pool += rhu(value)
    review["remediation_pool_cents"] = pool
