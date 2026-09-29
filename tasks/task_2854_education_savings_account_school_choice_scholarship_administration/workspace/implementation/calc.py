"""All seven pinned calculations (PRD 2.6, 3.2, 3.3, 3.5, 3.6, 3.8, 3.9).

Every monetary quantity is whole cents.  Percentages and rates are applied
through Decimal and reduced to whole cents with ROUND_HALF_UP immediately,
component by component, before any further arithmetic -- never summed first.
"""
from decimal import Decimal, ROUND_HALF_UP

from store import whole_months_between

# --- pinned constant tables -------------------------------------------------
INCOME_MULTIPLIER = {
    "BAND_A": Decimal("1.00"),
    "BAND_B": Decimal("0.90"),
    "BAND_C": Decimal("0.75"),
}

CATEGORY_ADDON_PCT = {
    "DISABILITY_IEP": Decimal("0.375"),
    "FOSTER": Decimal("0.225"),
    "MILITARY": Decimal("0.125"),
    "PRIOR_PUBLIC_SCHOOL": Decimal("0.0625"),
}

ADDON_AGGREGATE_CAP = Decimal("0.45")

INCOME_SCORE_WEIGHT = {
    "BAND_A": Decimal("1.0"),
    "BAND_B": Decimal("0.6"),
    "BAND_C": Decimal("0.25"),
}

CATEGORY_SCORE_POINTS = {
    "DISABILITY_IEP": 40,
    "FOSTER": 30,
    "MILITARY": 15,
    "PRIOR_PUBLIC_SCHOOL": 10,
}

SIBLING_SCORE_POINTS = 25

SCREENING_FLAG_WEIGHT = {
    "OFAC_HIT": 60,
    "PRIOR_DELISTING": 40,
    "NO_STATE_REGISTRATION": 35,
    "SHARED_BANK_ACCOUNT": 25,
    "ADDRESS_MISMATCH": 20,
    "NEW_ENTITY_UNDER_12_MONTHS": 15,
}

SCREENING_SCORE_CAP = 100
SURVEILLANCE_SCORE_CAP = 100
SUBSTANTIATED_CASE_POINTS = 25
DECAY_PER_MONTH = Decimal("0.1")
DECAY_FLOOR = Decimal("0.5")

APPEAL_ROUND_CAP = 2
QUARTERS_PER_YEAR = 4


def dec(value):
    """Decimal from an int/float/str without float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def half_up(value):
    """Round a Decimal half up (away from zero) to a whole unit."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- 1. annual_award_amount -------------------------------------------------
def annual_award_amount(base_award_cents, income_band, category_flags):
    """PRD 3.2 four-step ladder.  No proration whatsoever.

    Both the provisional (claimed) and the final (verified) variants call this;
    they differ only in which band and which flag list are handed in.
    """
    base = dec(base_award_cents)
    multiplier = INCOME_MULTIPLIER[income_band]
    total = half_up(base * multiplier)

    flags = [f for f in (category_flags or []) if f in CATEGORY_ADDON_PCT]
    # Deterministic order: add-on percentage descending, then code ascending.
    ordered = sorted(set(flags), key=lambda f: (-CATEGORY_ADDON_PCT[f], f))

    consumed = Decimal("0")
    for flag in ordered:
        own = CATEGORY_ADDON_PCT[flag]
        allowed = min(own, ADDON_AGGREGATE_CAP - consumed)
        if allowed <= 0:
            break
        total += half_up(base * allowed)
        consumed += allowed
    return total


def prorated_award_cents(annual_award_cents, quarters_remaining):
    """PRD 3.5: annual * quarters_remaining / 4, rounded half up."""
    return half_up(
        dec(annual_award_cents) * dec(quarters_remaining) / dec(QUARTERS_PER_YEAR)
    )


# --- 2. priority_score_and_rank --------------------------------------------
def priority_tier(is_renewal, has_enrolled_sibling, sibling_committed,
                  verified_prior_enrollment, verified_income_band,
                  verified_category_flags):
    """PRD 3.3 five-rung ladder, first match wins."""
    if is_renewal:
        return 1
    if has_enrolled_sibling and sibling_committed:
        return 2
    if (verified_prior_enrollment == "PUBLIC_SCHOOL_FULL_YEAR"
            and verified_income_band == "BAND_A"):
        return 3
    if verified_category_flags:
        return 4
    return 5


def priority_score(verified_income_band, verified_category_flags, tier):
    """PRD 3.3: the income term is the only rounded term and is rounded first."""
    score = half_up(dec(100) * INCOME_SCORE_WEIGHT[verified_income_band])
    for flag in (verified_category_flags or []):
        score += CATEGORY_SCORE_POINTS.get(flag, 0)
    if tier == 2:
        score += SIBLING_SCORE_POINTS
    return score


def rank_key(application):
    """PRD 3.3 ordering: tier asc, score desc, submitted_at asc, created_at asc.

    The record id is never a sort key.  submitted_at may be null on a record
    that never went through submit (a minted renewal offer), which sorts first.
    """
    return (
        application.get("priority_tier") or 0,
        -(application.get("priority_score") or 0),
        application.get("submitted_at") or "",
        application.get("created_at") or "",
    )


# --- 3. quarterly_disbursement_slice ---------------------------------------
def quarterly_disbursement_slice(final_award_cents, lifetime_disbursed_cents,
                                 quarters_remaining_at_award,
                                 disbursement_count, admin_fee_pct):
    """PRD 3.5 credit pass for one account.  Returns a dict of row figures."""
    quarters_left = int(quarters_remaining_at_award) - int(disbursement_count)
    unpaid = int(final_award_cents) - int(lifetime_disbursed_cents)
    if quarters_left <= 0:
        even_slice = 0
        remainder = 0
    else:
        # The single place the programme floors instead of rounding half up.
        even_slice = unpaid // quarters_left if unpaid >= 0 else 0
        remainder = unpaid - even_slice * quarters_left
    first = int(disbursement_count) == 0
    remainder_applied = remainder if first else 0
    gross = even_slice + remainder_applied
    fee = half_up(dec(gross) * dec(admin_fee_pct))
    return {
        "quarters_left_at_issue": quarters_left,
        "gross_amount_cents": gross,
        "remainder_applied_cents": remainder_applied,
        "admin_fee_cents": fee,
        "net_credited_cents": gross - fee,
    }


# --- 4. unused_balance_rollover -------------------------------------------
def unused_balance_rollover(balance_cents, final_award_cents, rollover_cap_pct):
    """PRD 3.9.  The comparison against the cap is strictly greater-than."""
    cap = half_up(dec(final_award_cents) * dec(rollover_cap_pct))
    balance = int(balance_cents)
    if balance > cap:
        return {"rollover_carried_cents": cap,
                "forfeited_cents": balance - cap,
                "cap_cents": cap}
    return {"rollover_carried_cents": balance,
            "forfeited_cents": 0,
            "cap_cents": cap}


# --- 5. provider_risk_score ------------------------------------------------
def screening_static_score(flags):
    """PRD 3.6: sum of the weights of the distinct flags, capped at 100."""
    total = sum(SCREENING_FLAG_WEIGHT[f] for f in set(flags or []))
    return min(total, SCREENING_SCORE_CAP)


def recommended_status(score):
    if score < 40:
        return "APPROVE"
    if score < 60:
        return "PROBATION"
    return "REJECT"


def surveillance_decayed_score(screening_score, screened_at, now_iso,
                               substantiated_case_count):
    """PRD 3.6: decayed screening term rounded BEFORE the case points are added."""
    if not screened_at:
        months = 0
    else:
        months = whole_months_between(screened_at, now_iso)
    factor = Decimal("1") - DECAY_PER_MONTH * dec(months)
    if factor < DECAY_FLOOR:
        factor = DECAY_FLOOR
    decayed = half_up(dec(screening_score) * factor)
    total = decayed + SUBSTANTIATED_CASE_POINTS * int(substantiated_case_count)
    return min(total, SURVEILLANCE_SCORE_CAP)


# --- 6. clawback_assessment ----------------------------------------------
def clawback_assessment(disallowed_principal_cents, account_balance_cents):
    """PRD 3.8.  The penalty tier is keyed on the principal alone."""
    principal = int(disallowed_principal_cents)
    if principal <= 50000:
        rate = Decimal("0.10")
    elif principal <= 250000:
        rate = Decimal("0.20")
    else:
        rate = Decimal("0.35")
    penalty = half_up(dec(principal) * rate)
    total = principal + penalty
    debit = min(int(account_balance_cents), total)
    if debit < 0:
        debit = 0
    return {
        "penalty_rate": float(rate),
        "penalty_cents": penalty,
        "clawback_total_cents": total,
        "account_debit_cents": debit,
        "receivable_cents": total - debit,
    }
