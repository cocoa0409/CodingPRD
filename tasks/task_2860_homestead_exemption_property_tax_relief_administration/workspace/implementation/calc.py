"""The named calculations of PRD §2.7 and §3.

Every figure is an integer number of whole cents and every rate is integer
basis points.  Exact rational arithmetic (fractions.Fraction) is used
throughout so that the single pinned round-half-up happens exactly where the
specification puts it and nowhere else.
"""

from fractions import Fraction

import db
from db import COUNTY_MILL_RATE_BPS, REFUND_INTEREST_BPS_PER_YEAR

BPS = 10000


def round_half_up(value):
    """Round an exact rational to a whole cent, half away from zero."""
    frac = Fraction(value)
    num, den = frac.numerator, frac.denominator
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


# --------------------------------------------------------------------------
# parcel_value_decomposition (PRD §2.7)
# --------------------------------------------------------------------------
def _program_of(grant):
    return db.get("relief_programs", grant["program_id"])


def _waterfall_key(grant):
    program = _program_of(grant)
    rank = program["priority_rank"] if program else 0
    return (rank, grant.get("created_at") or "", grant.get("_seq") or 0)


def grants_on_parcel(parcel_id):
    return [g for g in db.rows("exemption_grants") if g["parcel_id"] == parcel_id]


def capped_value(parcel):
    years_since_base = max(0, parcel["tax_year"] - parcel["base_year"])
    factor = Fraction(BPS + parcel["assessment_cap_pct_bps"] * years_since_base, BPS)
    return round_half_up(Fraction(parcel["base_year_value_cents"]) * factor)


def assessed_basis(parcel, active_grants):
    """Steps one and two: cap first, then the controlling valuation freeze."""
    capped = capped_value(parcel)
    assessed = min(parcel["market_value_cents"], capped)
    freeze_grants = [g for g in active_grants if g.get("frozen_value_cents") is not None]
    if freeze_grants:
        controlling = sorted(freeze_grants, key=_waterfall_key)[0]
        assessed = min(assessed, controlling["frozen_value_cents"])
    return capped, assessed


def decompose(parcel, bump_version=True):
    """Run the four-step decomposition for a parcel and record the mutation."""
    all_grants = grants_on_parcel(parcel["id"])
    active = [g for g in all_grants if g["benefit_status"] == "ACTIVE"]

    capped, assessed = assessed_basis(parcel, active)
    parcel["capped_value_cents"] = capped
    parcel["assessed_value_cents"] = assessed

    for grant in all_grants:
        if grant["benefit_status"] != "ACTIVE":
            grant["applied_exempt_value_cents"] = 0

    remaining = assessed
    total = 0
    for grant in sorted(active, key=_waterfall_key):
        applied = min(grant["benefit_amount_cents"], remaining)
        grant["applied_exempt_value_cents"] = applied
        total += applied
        remaining -= applied

    parcel["exempt_value_cents"] = total
    parcel["taxable_value_cents"] = assessed - total

    if total == 0:
        parcel["exemption_status"] = "UNEXEMPTED"
    elif total == assessed:
        parcel["exemption_status"] = "FULLY_EXEMPT"
    else:
        parcel["exemption_status"] = "PARTIALLY_EXEMPT"

    if bump_version:
        db.touch(parcel)
    return parcel


def pre_event_assessed(parcel):
    """The assessed basis as it stands before a new grant is inserted."""
    active = [g for g in grants_on_parcel(parcel["id"]) if g["benefit_status"] == "ACTIVE"]
    return assessed_basis(parcel, active)[1]


# --------------------------------------------------------------------------
# income_relief_tier (PRD §3.4)
# --------------------------------------------------------------------------
def income_relief_tier(income_cents, income_limit_cents):
    """Exact integer cross-multiplication; returns (tier, multiplier_bps) or None."""
    if income_cents * 2 <= income_limit_cents:
        return "TIER_FULL", 10000
    if income_cents * 4 <= income_limit_cents * 3:
        return "TIER_HIGH", 7500
    if income_cents <= income_limit_cents:
        return "TIER_PARTIAL", 5000
    return None


# --------------------------------------------------------------------------
# exemption_benefit_amount (PRD §3.4)
# --------------------------------------------------------------------------
def benefit_amount(assessed_value_cents, program, relief_multiplier_bps,
                   disability_rating_pct_bps, ownership_pct_bps):
    raw = Fraction(assessed_value_cents * program["relief_pct_bps"], BPS)
    tiered = raw * Fraction(relief_multiplier_bps, BPS)
    if program["program_code"] == "VETERAN_DISABILITY":
        dis_mult = disability_rating_pct_bps
    else:
        dis_mult = BPS
    adjusted = tiered * Fraction(dis_mult, BPS)
    capped = min(Fraction(program["max_exempt_value_cents"]), adjusted)
    prorated = capped * Fraction(ownership_pct_bps, BPS)
    return round_half_up(prorated)


# --------------------------------------------------------------------------
# retroactive_refund_amount (PRD §3.7)
# --------------------------------------------------------------------------
def claim_window(claim, program, grant):
    last_eligible = claim["filing_tax_year"] - 1
    first_eligible = max(
        claim["filing_tax_year"] - program["statutory_lookback_years"],
        grant["first_eligible_tax_year"],
        claim["requested_start_tax_year"],
    )
    return first_eligible, last_eligible


def per_year_saving(benefit_amount_cents):
    return round_half_up(Fraction(benefit_amount_cents * COUNTY_MILL_RATE_BPS, BPS))


def gross_refund(years, benefit_amount_cents):
    saving = per_year_saving(benefit_amount_cents)
    return sum(saving for _ in years)


def net_final_refund(years, benefit_amount_cents, outstanding_cents, filing_tax_year):
    """Steps 1..6 of the NET_FINAL variant, in the pinned order."""
    saving = {y: per_year_saving(benefit_amount_cents) for y in years}
    gross = sum(saving[y] for y in years)

    offset_remaining = min(gross, outstanding_cents)
    absorbed = {}
    refundable = {}
    for y in years:
        absorbed[y] = min(offset_remaining, saving[y])
        refundable[y] = saving[y] - absorbed[y]
        offset_remaining -= absorbed[y]
    offset_applied = sum(absorbed[y] for y in years)

    interest = {}
    for y in years:
        interest[y] = round_half_up(
            Fraction(refundable[y] * REFUND_INTEREST_BPS_PER_YEAR * (filing_tax_year - y), BPS)
        )

    net_refund = sum(refundable[y] for y in years)
    refund_interest = sum(interest[y] for y in years)
    return {
        "gross_refund_cents": gross,
        "offset_applied_cents": offset_applied,
        "net_refund_cents": net_refund,
        "refund_interest_cents": refund_interest,
        "total_payable_cents": net_refund + refund_interest,
    }


# --------------------------------------------------------------------------
# recovery_assessment_total (PRD §3.8)
# --------------------------------------------------------------------------
def recovery_assessment(case, grant, program):
    years = range(case["improper_start_tax_year"], case["improper_end_tax_year"] + 1)
    back_tax_total = 0
    penalty_total = 0
    interest_total = 0
    for y in years:
        back_tax = round_half_up(
            Fraction(grant["benefit_amount_cents"] * COUNTY_MILL_RATE_BPS, BPS)
        )
        penalty = round_half_up(Fraction(back_tax * program["penalty_pct_bps"], BPS))
        interest = round_half_up(
            Fraction(
                back_tax * program["interest_pct_bps_per_year"] * (case["assessment_tax_year"] - y),
                BPS,
            )
        )
        back_tax_total += back_tax
        penalty_total += penalty
        interest_total += interest
    return {
        "back_tax_cents": back_tax_total,
        "penalty_cents": penalty_total,
        "interest_cents": interest_total,
        "total_assessed_cents": back_tax_total + penalty_total + interest_total,
    }


# --------------------------------------------------------------------------
# fraud_risk_score (PRD §3.8)
# --------------------------------------------------------------------------
def _taxpayer_checks(taxpayer_id):
    app_ids = {
        a["id"] for a in db.rows("exemption_applications") if a["taxpayer_id"] == taxpayer_id
    }
    return [c for c in db.rows("verification_checks") if c["application_id"] in app_ids]


def _check_recency_key(check):
    return (check.get("checked_at") or "", check.get("created_at") or "", check.get("_seq") or 0)


def fraud_risk_score(taxpayer_id, variant):
    checks = _taxpayer_checks(taxpayer_id)

    def any_mismatch(sources):
        if variant == "SCREENING_SNAPSHOT":
            for source in sources:
                per_source = [c for c in checks if c["source"] == source]
                if not per_source:
                    continue
                newest = sorted(per_source, key=_check_recency_key)[-1]
                if newest["result"] == "MISMATCH":
                    return True
            return False
        for check in sorted(checks, key=_check_recency_key):
            if check["source"] in sources and check["result"] == "MISMATCH":
                return True
        return False

    f1 = 100 if any_mismatch({"VOTER_REGISTRY", "DMV"}) else 0
    homestead_parcels = {
        g["parcel_id"]
        for g in db.rows("exemption_grants")
        if g["taxpayer_id"] == taxpayer_id
        and g["exemption_type"] == "HOMESTEAD_BASIC"
        and g["benefit_status"] in ("ACTIVE", "SUSPENDED")
    }
    f2 = 100 if len(homestead_parcels) >= 2 else 0
    f3 = 100 if any_mismatch({"USPS_NCOA"}) else 0
    f4 = 100 if any_mismatch({"INCOME_DOR"}) else 0

    weighted = f1 * 3500 + f2 * 3000 + f3 * 1500 + f4 * 2000
    return round_half_up(Fraction(weighted, BPS))


# --------------------------------------------------------------------------
# portable_freeze_allocation (PRD §3.6)
# --------------------------------------------------------------------------
def portable_allocation(transfer_value_cents, portable_balance_cents, destination_assessed_cents):
    balance = portable_balance_cents if portable_balance_cents is not None else 0
    return min(transfer_value_cents, balance, destination_assessed_cents)
