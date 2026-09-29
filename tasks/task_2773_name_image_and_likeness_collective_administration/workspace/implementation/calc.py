"""Integer-cents arithmetic (PRD 2.6) and the ten declared calculations."""

# --- rounding discipline ----------------------------------------------------

def round_half_up(n, d):
    """Exact rational n/d rounded to the nearest integer, exact half away from zero."""
    if d < 0:
        n, d = -n, -d
    if n >= 0:
        return (2 * n + d) // (2 * d)
    return -((-2 * n + d) // (2 * d))


def floor_div(n, d):
    """Exact rational n/d truncated toward negative infinity."""
    if d < 0:
        n, d = -n, -d
    return n // d


# --- calc_contribution_processing_fee ---------------------------------------

FEE_BAND_1_MAX_CENTS = 99999
FEE_BAND_1_BPS = 290
FEE_BAND_1_FIXED_CENTS = 30
FEE_BAND_2_MAX_CENTS = 999999
FEE_BAND_2_BPS = 250
FEE_BAND_2_FIXED_CENTS = 30
FEE_BAND_3_BPS = 210
FEE_BAND_3_FIXED_CENTS = 0


def processing_fee(gross_amount_cents):
    """Average-rate band selection; both band boundaries are inclusive."""
    if gross_amount_cents <= FEE_BAND_1_MAX_CENTS:
        bps, fixed = FEE_BAND_1_BPS, FEE_BAND_1_FIXED_CENTS
    elif gross_amount_cents <= FEE_BAND_2_MAX_CENTS:
        bps, fixed = FEE_BAND_2_BPS, FEE_BAND_2_FIXED_CENTS
    else:
        bps, fixed = FEE_BAND_3_BPS, FEE_BAND_3_FIXED_CENTS
    return round_half_up(gross_amount_cents * bps, 10000) + fixed


# --- calc_contribution_deductible_amount ------------------------------------

DEDUCTIBLE_AGI_PCT_INDIVIDUAL = 60
DEDUCTIBLE_AGI_PCT_ENTITY = 100


def deductible_ceiling(annual_agi_cents, donor_kind):
    pct = (DEDUCTIBLE_AGI_PCT_INDIVIDUAL if donor_kind == "INDIVIDUAL"
           else DEDUCTIBLE_AGI_PCT_ENTITY)
    return floor_div(annual_agi_cents * pct, 100)


# --- calc_release_withholding -----------------------------------------------

NRA_STATUTORY_PCT = 30
BACKUP_WITHHOLDING_PCT = 24
TREATY_EXEMPT_CEILING_CENTS = 300000


def withholding(requested_amount_cents, tax_person_kind, taxpayer_doc_on_file,
                treaty_exempt_claimed):
    r = requested_amount_cents
    if tax_person_kind == "NONRESIDENT_ALIEN":
        if treaty_exempt_claimed and r <= TREATY_EXEMPT_CEILING_CENTS:
            return "NONE", 0
        return "NRA_STATUTORY", round_half_up(r * NRA_STATUTORY_PCT, 100)
    if taxpayer_doc_on_file != "W9":
        return "BACKUP", round_half_up(r * BACKUP_WITHHOLDING_PCT, 100)
    return "NONE", 0


# --- calc_deliverable_payout_eligible ---------------------------------------

LATE_PENALTY_PCT = 15


def payout_eligible(base, late_flag):
    if late_flag:
        return base - round_half_up(base * LATE_PENALTY_PCT, 100)
    return base


# --- calc_collective_funding_posture ----------------------------------------

RESTRICTED_COVERAGE_PCT = 75


def funding_posture(settled_net_funds_cents, released_total_cents,
                    committed_unreleased_cents):
    available = settled_net_funds_cents - released_total_cents
    committed = committed_unreleased_cents
    if committed == 0:
        return "OPEN"
    if available >= committed:
        return "OPEN"
    if available * 100 >= committed * RESTRICTED_COVERAGE_PCT:
        return "RESTRICTED"
    return "FROZEN"


# --- calc_clawback_amount ---------------------------------------------------

CLAWBACK_CAP_PCT = {
    "NCAA_2024": 100,
    "NCAA_2026": 50,
    "NAIA": 75,
}


def clawback_amount(released_total_cents, earned_cents, termination_reason,
                    association_ruleset):
    if termination_reason == "MUTUAL_RELEASE":
        return 0
    unearned = released_total_cents - earned_cents
    cap_pct = CLAWBACK_CAP_PCT.get(association_ruleset, 100)
    cap = floor_div(released_total_cents * cap_pct, 100)
    return max(0, min(unearned, cap))


# --- calc_athlete_tax_reporting ---------------------------------------------

FORM_1099_THRESHOLD_CENTS = 60000


def tax_form_required(gross, tax_person_kind):
    if gross == 0:
        return "NONE"
    if tax_person_kind == "NONRESIDENT_ALIEN":
        return "FORM_1042_S"
    if gross >= FORM_1099_THRESHOLD_CENTS:
        return "FORM_1099_NEC"
    return "NONE"


# --- global constants -------------------------------------------------------

ATHLETE_ANNUAL_CAP_CENTS = 5000000
MIN_ROSTER_SHARE_CENTS = 1
DISCLOSURE_THRESHOLD_CENTS = 60000
DISCLOSURE_WINDOW_HOURS = 168
MAX_STRUCTURE_CHANGES = 2
MAX_SUBMISSIONS = 3
MAX_DISCLOSURE_RETURNS = 2
MAX_OVERLAPPING_BATCHES = 2
