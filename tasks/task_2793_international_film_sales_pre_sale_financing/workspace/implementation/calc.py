"""Derived figures and the pinned calculations of PRD section 3."""
from __future__ import annotations

from decimal import Decimal

from store import (
    accounts_of_film,
    comparables_of_territory,
    contracts_of_buyer,
    contracts_of_film,
    db,
    facilities_of_film,
    milestones_of_contract,
    now,
    open_accounts_of_film,
    tiers_of_account,
    touch,
    valuations_of_film,
)
from util import ZERO2, q2, q4, q6, whole_days_between

# ------------------------------------------------------------------ constants
COMP_LOOKBACK_YEARS = 7
MIN_COMP_SAMPLE = 3
ASK_PREMIUM = Decimal("1.25")
FLOOR_DISCOUNT = Decimal("0.70")

NET_EXECUTION_HEADROOM = Decimal("1.50")

TIER1_BREAK = Decimal("1000000.00")
TIER2_BREAK = Decimal("3000000.00")
TIER2_FACTOR = Decimal("0.75")
TIER3_FACTOR = Decimal("0.50")
EXPENSE_LOG_TOLERANCE = Decimal("2.00")

DAYS_PER_YEAR = Decimal("365")
UNBONDED_HAIRCUT = Decimal("0.50")

TURNAROUND_MINUTES = 30
MEETING_MINUTES_CAP = 240

CURE_WINDOW_DAYS = 30
MAX_NEGOTIATION_ROUNDS = 4

REQUIRED_TECHNICAL_ITEMS = 14
REQUIRED_LEGAL_ITEMS = 6
MAX_REVISION_ROUNDS = 2

LIVE_NEGOTIATION = ("OFFERED", "COUNTERED", "ACCEPTED")
PIPELINE_NEGOTIATION = ("OFFERED", "COUNTERED", "ACCEPTED", "EXECUTED")
UNPAID_MILESTONES = ("SCHEDULED", "INVOICED")
INVESTMENT_GRADE = ("AAA", "AA", "A")
LIVE_FACILITIES = ("PROPOSED", "APPROVED", "DRAWN", "MARGIN_CALL")


# ------------------------------------------------------------- film counters


def film_counters(film):
    film_id = film["id"]
    contracts = contracts_of_film(film_id)
    committed = Decimal("0")
    collected = Decimal("0")
    for contract in contracts:
        if contract["negotiation_status"] in ("ACCEPTED", "EXECUTED"):
            committed += contract["minimum_guarantee_usd"]
        for milestone in milestones_of_contract(contract["id"]):
            if milestone["status"] == "RECEIVED":
                collected += milestone["received_amount_usd"]
    committed = q2(committed)
    gap = q2(film["production_budget_usd"] - committed)
    if gap < 0:
        gap = ZERO2
    published = 0
    licensed = 0
    for valuation in valuations_of_film(film_id):
        if valuation["status"] in ("PUBLISHED", "LICENSED"):
            published += 1
        if valuation["status"] == "LICENSED":
            licensed += 1
    return {
        "total_mg_committed_usd": committed,
        "total_mg_collected_usd": q2(collected),
        "financing_gap_usd": gap,
        "published_territory_count": published,
        "licensed_territory_count": licensed,
    }


def published_count(film):
    return film_counters(film)["published_territory_count"]


def licensed_count(film):
    return film_counters(film)["licensed_territory_count"]


def evaluate_sold_out(film):
    """IN_MARKET -> SOLD_OUT, system evaluated after a successful execution."""
    counters = film_counters(film)
    published = counters["published_territory_count"]
    licensed = counters["licensed_territory_count"]
    if film["sales_status"] == "IN_MARKET" and published >= 1 and licensed == published:
        film["sales_status"] = "SOLD_OUT"
        touch(film)
        return True
    return False


def evaluate_back_in_market(film):
    """SOLD_OUT -> IN_MARKET whenever the licensed count falls below published."""
    counters = film_counters(film)
    if (
        film["sales_status"] == "SOLD_OUT"
        and counters["licensed_territory_count"] < counters["published_territory_count"]
    ):
        film["sales_status"] = "IN_MARKET"
        touch(film)
        return True
    return False


# ---------------------------------------------------------- buyer exposures


def buyer_gross_exposure(buyer_id):
    total = Decimal("0")
    for contract in contracts_of_buyer(buyer_id):
        if contract["negotiation_status"] in PIPELINE_NEGOTIATION:
            total += contract["minimum_guarantee_usd"]
    return q2(total)


def buyer_net_unpaid_exposure(buyer_id):
    total = Decimal("0")
    for contract in contracts_of_buyer(buyer_id):
        if contract["negotiation_status"] != "EXECUTED":
            continue
        for milestone in milestones_of_contract(contract["id"]):
            if milestone["status"] in UNPAID_MILESTONES:
                total += milestone["amount_usd"]
    return q2(total)


# -------------------------------------------------------- contract counters


def contract_pct_total(contract_id):
    total = Decimal("0")
    for milestone in milestones_of_contract(contract_id):
        total += milestone["pct_of_mg"]
    return q4(total)


def contract_unpaid(contract_id):
    total = Decimal("0")
    for milestone in milestones_of_contract(contract_id):
        if milestone["status"] in UNPAID_MILESTONES:
            total += milestone["amount_usd"]
    return q2(total)


def contract_received(contract_id):
    total = Decimal("0")
    for milestone in milestones_of_contract(contract_id):
        if milestone["status"] == "RECEIVED":
            total += milestone["received_amount_usd"]
    return q2(total)


def derive_collection_status(contract):
    """Collection axis (PRD 3.7). WRITTEN_OFF is terminal."""
    if contract["collection_status"] == "WRITTEN_OFF":
        return contract["collection_status"]
    received = contract_received(contract["id"])
    unpaid = contract_unpaid(contract["id"])
    if received <= 0:
        return "UNPAID"
    if unpaid <= 0:
        return "PAID"
    return "PARTIALLY_PAID"


def resync_collection_status(contract):
    status = derive_collection_status(contract)
    if status != contract["collection_status"]:
        contract["collection_status"] = status
        return True
    return False


def milestone_by_label(contract_id, label):
    for milestone in milestones_of_contract(contract_id):
        if milestone["label"] == label:
            return milestone
    return None


# ---------------------------------------------------------------- agreements


def executed_agreement(film_id):
    from store import agreements_of_film

    for agreement in agreements_of_film(film_id):
        if agreement["status"] == "EXECUTED":
            return agreement
    return None


def agreement_in_force(film_id):
    """status EXECUTED and term_start <= current_utc < term_end (PRD 3.1)."""
    from store import agreements_of_film

    instant = now()
    for agreement in agreements_of_film(film_id):
        if agreement["status"] != "EXECUTED":
            continue
        start = agreement["term_start_date"]
        end = agreement["term_end_date"]
        if start <= instant and (end is None or instant < end):
            return agreement
    return None


# ------------------------------------------------------------ waterfall tiers


def tier_status(tier):
    """Derived in the order given by PRD 3.9."""
    cap = tier["cap_usd"]
    if cap is not None and tier["recouped_usd"] >= cap:
        return "SATISFIED"
    if tier["tier_type"] == "BANK_DEBT":
        account = db.accounts.get(tier["account_id"])
        if account is not None:
            live = [
                facility
                for facility in facilities_of_film(account["film_id"])
                if facility["status"] in ("APPROVED", "DRAWN", "MARGIN_CALL")
            ]
            if not live:
                return "SUSPENDED"
    return "ACTIVE"


def tiers_of_film(film_id, tier_type, open_only=True):
    found = []
    accounts = open_accounts_of_film(film_id) if open_only else accounts_of_film(film_id)
    for account in accounts:
        for tier in tiers_of_account(account["id"]):
            if tier["tier_type"] == tier_type:
                found.append(tier)
    return found


def resync_commission_tier(film_id, agreement):
    """Every receipt / reversal resyncs the SALES_COMMISSION ceiling."""
    if agreement is None:
        return
    target = q2(agreement["commission_earned_usd"])
    for tier in tiers_of_film(film_id, "SALES_COMMISSION"):
        if tier["cap_usd"] is None or q2(tier["cap_usd"]) != target:
            tier["cap_usd"] = target
            touch(tier)


def resync_expense_tier(film_id, agreement):
    """SALES_EXPENSES ceiling = round(min(incurred, cap), 2)."""
    if agreement is None:
        return
    incurred = agreement["expenses_incurred_usd"]
    cap = agreement["expense_cap_usd"]
    target = q2(incurred if incurred < cap else cap)
    for tier in tiers_of_film(film_id, "SALES_EXPENSES"):
        if tier["cap_usd"] is None or q2(tier["cap_usd"]) != target:
            tier["cap_usd"] = target
            touch(tier)


# ------------------------------------------------------------------ banking


def eligible_contracts_for_facility(film_id):
    """PRD 3.8 eligibility filter, in created_at ASC order."""
    eligible = []
    for contract in contracts_of_film(film_id):
        if contract["negotiation_status"] != "EXECUTED":
            continue
        if contract["delivery_status"] == "REJECTED":
            continue
        buyer = db.buyers.get(contract["buyer_id"])
        if buyer is None:
            continue
        if buyer["credit_rating"] not in INVESTMENT_GRADE:
            continue
        if buyer["status"] != "ACTIVE":
            continue
        eligible.append(contract)
    return eligible


def has_investment_grade_executed_contract(film_id):
    for contract in contracts_of_film(film_id):
        if contract["negotiation_status"] != "EXECUTED":
            continue
        buyer = db.buyers.get(contract["buyer_id"])
        if buyer is None:
            continue
        if buyer["credit_rating"] in INVESTMENT_GRADE and buyer["status"] == "ACTIVE":
            return True
    return False


def facility_figures(facility):
    """(eligible_collateral_usd, advance_amount_usd) — rounding order is pinned."""
    instant = now()
    total = Decimal("0")
    for contract in eligible_contracts_for_facility(facility["film_id"]):
        unpaid_milestones = [
            milestone
            for milestone in milestones_of_contract(contract["id"])
            if milestone["status"] in UNPAID_MILESTONES
        ]
        if not unpaid_milestones:
            continue
        unpaid = Decimal("0")
        tenor = None
        for milestone in unpaid_milestones:
            unpaid += milestone["amount_usd"]
            due = milestone["due_date"]
            if tenor is None or due > tenor:
                tenor = due
        unpaid = q2(unpaid)
        days = whole_days_between(instant, tenor)
        discount_factor = q6(
            Decimal("1") - facility["discount_rate_pct"] * (Decimal(days) / DAYS_PER_YEAR)
        )
        contract_value = q2(unpaid * facility["advance_rate_pct"] * discount_factor)
        total += contract_value
    eligible = q2(total)
    cap = facility["facility_cap_usd"]
    advance = cap if cap < eligible else eligible
    if facility["completion_bond_required"] and not facility["completion_bond_posted"]:
        advance = q2(advance * UNBONDED_HAIRCUT)
    else:
        advance = q2(advance)
    return eligible, advance


def write_facility_figures(facility):
    eligible, advance = facility_figures(facility)
    changed = (
        facility["eligible_collateral_usd"] != eligible
        or facility["advance_amount_usd"] != advance
    )
    facility["eligible_collateral_usd"] = eligible
    facility["advance_amount_usd"] = advance
    return changed


def refresh_facilities(film_id, allow_margin_call=False, allow_cure=False):
    """Recompute the live facilities of a film after a collateral changing event."""
    for facility in facilities_of_film(film_id):
        if facility["status"] not in LIVE_FACILITIES:
            continue
        changed = write_facility_figures(facility)
        if (
            allow_margin_call
            and facility["status"] == "DRAWN"
            and facility["advance_amount_usd"] < facility["drawn_amount_usd"]
        ):
            facility["status"] = "MARGIN_CALL"
            changed = True
        elif (
            allow_cure
            and facility["status"] == "MARGIN_CALL"
            and facility["advance_amount_usd"] >= facility["drawn_amount_usd"]
        ):
            facility["status"] = "DRAWN"
            changed = True
        if changed:
            touch(facility)


def refresh_facilities_for_buyer(buyer_id):
    """PRD 3.4 — APPROVED or DRAWN facilities of films this buyer has executed on."""
    film_ids = []
    for contract in contracts_of_buyer(buyer_id):
        if contract["negotiation_status"] == "EXECUTED":
            if contract["film_id"] not in film_ids:
                film_ids.append(contract["film_id"])
    for film_id in film_ids:
        for facility in facilities_of_film(film_id):
            if facility["status"] not in ("APPROVED", "DRAWN"):
                continue
            if write_facility_figures(facility):
                touch(facility)


# --------------------------------------------------------------- valuations


def comparable_sample(film, territory_id):
    """Eligible comparables, sorted by fee ASC then created_at ASC."""
    cutoff = now().year - COMP_LOOKBACK_YEARS
    sample = [
        comparable
        for comparable in comparables_of_territory(territory_id)
        if comparable["genre"] == film["genre"]
        and comparable["verified"] is True
        and comparable["release_year"] >= cutoff
    ]
    sample.sort(
        key=lambda row: (row["gross_license_fee_usd"], row["created_at"], row["_seq"])
    )
    return sample


def median_fee(sample):
    size = len(sample)
    if size == 0:
        return None
    if size % 2 == 1:
        return q2(sample[size // 2]["gross_license_fee_usd"])
    lower = sample[size // 2 - 1]["gross_license_fee_usd"]
    upper = sample[size // 2]["gross_license_fee_usd"]
    return q2((lower + upper) / Decimal("2"))


def cast_multiplier_for(score):
    if score >= 85:
        return Decimal("1.40")
    if score >= 70:
        return Decimal("1.20")
    if score >= 50:
        return Decimal("1.00")
    return Decimal("0.80")


def valuation_figures(film, territory, method, sample):
    median = median_fee(sample)
    if method == "COMPARABLE_WEIGHTED":
        multiplier = Decimal("1.00")
        estimate = q2(median * territory["base_value_index"])
    else:
        multiplier = cast_multiplier_for(film["principal_cast_score"])
        estimate = q2(median * territory["base_value_index"] * multiplier)
    return {
        "comp_sample_size": len(sample),
        "comp_median_usd": median,
        "cast_multiplier": multiplier,
        "estimate_usd": estimate,
        "ask_price_usd": q2(estimate * ASK_PREMIUM),
        "floor_price_usd": q2(estimate * FLOOR_DISCOUNT),
    }


def published_valuation(film_id, territory_id):
    for valuation in valuations_of_film(film_id):
        if valuation["territory_id"] == territory_id and valuation["status"] == "PUBLISHED":
            return valuation
    return None


def licensed_valuation(film_id, territory_id):
    for valuation in valuations_of_film(film_id):
        if valuation["territory_id"] == territory_id and valuation["status"] == "LICENSED":
            return valuation
    return None


# --------------------------------------------------------------- commission


def commission_rate(commission_pct, gross_before):
    """One rate, chosen from the pre-receipt gross total (PRD 3.7 step two)."""
    if gross_before < TIER1_BREAK:
        return commission_pct
    if gross_before < TIER2_BREAK:
        return q6(commission_pct * TIER2_FACTOR)
    return q6(commission_pct * TIER3_FACTOR)


def agreement_for_film(film_id):
    """The agreement that carries the film's commission and expense figures."""
    from store import agreements_of_film

    executed = executed_agreement(film_id)
    if executed is not None:
        return executed
    agreements = agreements_of_film(film_id)
    return agreements[0] if agreements else None


# ------------------------------------------------------------ waterfall run


def ordered_tiers(account_id):
    return sorted(
        tiers_of_account(account_id),
        key=lambda row: (row["tier_order"], row["created_at"], row["_seq"]),
    )


def run_waterfall(account, amount_in):
    """Single pass in tier_order ASC, then one residual sweep (PRD 3.9)."""
    tiers = ordered_tiers(account["id"])
    remaining = q2(amount_in)
    entries = []
    changed = []
    for tier in tiers:
        allocated = ZERO2
        if tier_status(tier) == "ACTIVE":
            target = q2(remaining * tier["pct_of_available"])
            if tier["cap_usd"] is not None:
                room = q2(tier["cap_usd"] - tier["recouped_usd"])
                if room < target:
                    target = room
            if remaining < target:
                target = remaining
            if target < 0:
                target = ZERO2
            if target > 0:
                tier["recouped_usd"] = q2(tier["recouped_usd"] + target)
                remaining = q2(remaining - target)
                if tier not in changed:
                    changed.append(tier)
            allocated = target
        entries.append({"tier": tier, "amount": allocated})
    if remaining > 0:
        candidates = [
            entry
            for entry in entries
            if entry["tier"]["cap_usd"] is None and tier_status(entry["tier"]) == "ACTIVE"
        ]
        if candidates:
            candidates.sort(
                key=lambda entry: (
                    -entry["tier"]["tier_order"],
                    entry["tier"]["created_at"],
                    entry["tier"]["_seq"],
                )
            )
            sweep = candidates[0]
            sweep["tier"]["recouped_usd"] = q2(sweep["tier"]["recouped_usd"] + remaining)
            sweep["amount"] = q2(sweep["amount"] + remaining)
            if sweep["tier"] not in changed:
                changed.append(sweep["tier"])
            remaining = ZERO2
    for tier in changed:
        touch(tier)
    return entries


def apply_run_cross_effects(account, entries):
    """SALES_EXPENSES feeds the agreement; BANK_DEBT retires facility debt."""
    film_id = account["film_id"]
    expense_total = Decimal("0")
    debt_total = Decimal("0")
    for entry in entries:
        if entry["amount"] <= 0:
            continue
        if entry["tier"]["tier_type"] == "SALES_EXPENSES":
            expense_total += entry["amount"]
        elif entry["tier"]["tier_type"] == "BANK_DEBT":
            debt_total += entry["amount"]
    if expense_total > 0:
        agreement = agreement_for_film(film_id)
        if agreement is not None:
            agreement["expenses_recouped_usd"] = q2(
                agreement["expenses_recouped_usd"] + expense_total
            )
            touch(agreement)
    if debt_total > 0:
        for facility in facilities_of_film(film_id):
            if facility["status"] not in ("DRAWN", "MARGIN_CALL", "DEFAULTED"):
                continue
            outstanding = q2(facility["outstanding_debt_usd"] - debt_total)
            if outstanding < 0:
                outstanding = ZERO2
            facility["outstanding_debt_usd"] = outstanding
            if facility["status"] == "DRAWN" and outstanding <= 0:
                facility["status"] = "REPAID"
                facility["outstanding_debt_usd"] = ZERO2
            touch(facility)


def account_balance(account):
    return q2(account["total_receipts_usd"] - account["total_distributed_usd"])
