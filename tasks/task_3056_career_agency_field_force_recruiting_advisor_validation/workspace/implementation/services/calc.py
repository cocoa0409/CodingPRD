"""Calculation rules (§1.3) and the money primitives of §2.7.

Every rounding order below is pinned by the PRD prose of §3; the docstrings name
the sentence that pins it.
"""

from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Constants (§1.3 `constants` blocks)
# ---------------------------------------------------------------------------
COMPONENT_WEIGHT = Decimal("0.70")
RAW_COMPONENT_WEIGHT = Decimal("0.305")
PASS_CUT = Decimal("8.00")
CONDITIONAL_CUT = Decimal("5.50")

WEIGHTS = {
    "V1": {
        "MARKET_KNOWLEDGE": Decimal("0.175"),
        "RELATIONSHIP": Decimal("0.275"),
        "RESILIENCE": Decimal("0.25"),
        "ETHICS": Decimal("0.30"),
    },
    "V2": {
        "MARKET_KNOWLEDGE": Decimal("0.30"),
        "RELATIONSHIP": Decimal("0.15"),
        "RESILIENCE": Decimal("0.20"),
        "ETHICS": Decimal("0.35"),
    },
}
COMPETENCY_KEYS = ["MARKET_KNOWLEDGE", "RELATIONSHIP", "RESILIENCE", "ETHICS"]

PRODUCT_REQUIREMENT_PCT = Decimal("0.35")
PRODUCTION_DRAW_PCT = Decimal("0.25")
FLAT_MONTHLY_AMOUNT = 200000
RECRUITER_OVERRIDE_PCT = Decimal("0.05")

MAX_EXTENSIONS = 2

DISTRICT_OVERRIDE_RATE = Decimal("0.03")
MANAGING_DIRECTOR_OVERRIDE_RATE = Decimal("0.02")
DEFAULT_OVERRIDE_CAP_CENTS = 300000

FIRST_YEAR_COMMISSION_RATE = Decimal("0.40")

EARLY_LAPSE_MONTHS = 11
UNEARNED_DENOMINATOR = Decimal("24")
LATE_LAPSE_RESIDUAL_PCT = Decimal("0.50")
REINSTATEMENT_WINDOW_DAYS = 90
CHARGEBACK_BLOCK_CENTS = 500000

TIER_1_MIN = Decimal("95.00")
TIER_2_MIN = Decimal("90.00")
TIER_3_MIN = Decimal("85.00")
TIER_1_RATE = Decimal("0.050")
TIER_2_RATE = Decimal("0.035")
TIER_3_RATE = Decimal("0.020")

JOINT_VOID_WINDOW_DAYS = 30


def d(value):
    """Coerce a JSON number to Decimal via its string form (never via float)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    return Decimal(str(value))


def round_2(value):
    """Round half up to two decimal places (§2.7 first convention)."""
    return d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round half up to the nearest whole cent (§2.7 second convention)."""
    return int(d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def f2(value):
    """Serialise a round_2 quantity as a JSON number with two decimals."""
    return float(round_2(value))


# ---------------------------------------------------------------------------
# §1.3 selection_assessment_weighted_score
# ---------------------------------------------------------------------------
def weighted_score(version, competency_scores):
    table = WEIGHTS[version]
    avg = sum(d(competency_scores[k]) * table[k] for k in COMPETENCY_KEYS)
    # PINNED EVALUATION ORDER — round-then-sum. Each term is rounded to 2 dp
    # BEFORE the addition (PRD §3.2: "the two intermediate products are rounded
    # before they are added").
    weighted_component = round_2(avg * COMPONENT_WEIGHT)
    raw_component = round_2(d(competency_scores["ETHICS"]) * RAW_COMPONENT_WEIGHT)
    score = round_2(weighted_component + raw_component)
    if score >= PASS_CUT:
        outcome = "PASS"
    elif score >= CONDITIONAL_CUT:
        outcome = "CONDITIONAL"
    else:
        outcome = "FAIL"
    return score, outcome


# ---------------------------------------------------------------------------
# §1.3 commission_credit_allocation
# ---------------------------------------------------------------------------
def case_gross_commission_cents(policy):
    return round_cents(d(policy["annual_premium_cents"]) * FIRST_YEAR_COMMISSION_RATE)


def split_shares(case_gross, split_pct_lead):
    """PINNED ROUNDING ORDER — round-the-lead-then-subtract. The support share is
    the remainder, never independently rounded (PRD §3.6)."""
    lead_raw = d(case_gross) * d(split_pct_lead)
    lead = round_cents(lead_raw)
    support = int(case_gross) - lead
    return lead, support


# ---------------------------------------------------------------------------
# §1.3 chargeback_assessment
# ---------------------------------------------------------------------------
def completed_months(issue_date, lapse_date):
    """PRD §2.8: year difference times twelve plus month difference, minus one
    when the lapse day-of-month falls earlier than the issue day-of-month."""
    months = (lapse_date.year - issue_date.year) * 12 + (lapse_date.month - issue_date.month)
    if lapse_date.day < issue_date.day:
        months -= 1
    if months < 0:
        months = 0
    return months


def assessed_amount(gross, months, is_advanced, surrender=False):
    if surrender:
        assessed = int(gross)
    elif months <= EARLY_LAPSE_MONTHS:
        factor = Decimal(1) - d(months) / UNEARNED_DENOMINATOR
        assessed = round_cents(d(gross) * factor)
    elif months == 12:
        assessed = round_cents(d(gross) * LATE_LAPSE_RESIDUAL_PCT)
    else:  # months >= 13
        assessed = round_cents(d(gross) * LATE_LAPSE_RESIDUAL_PCT) if is_advanced else 0
    if assessed > int(gross):
        assessed = int(gross)
    if assessed < 0:
        assessed = 0
    return assessed


# ---------------------------------------------------------------------------
# §1.3 training_allowance_draw
# ---------------------------------------------------------------------------
def product_requirement_cents(contract):
    return round_cents(d(contract["validation_requirement_cents"]) * PRODUCT_REQUIREMENT_PCT)


def draw_per_window(contract, requirement_met):
    """PINNED ORDER: TERMINATED test, then the product requirement, then mode."""
    if contract["contract_status"] == "TERMINATED":
        return 0
    if requirement_met:
        return 0
    if contract["training_allowance_mode"] == "FLAT_MONTHLY":
        return FLAT_MONTHLY_AMOUNT
    return round_cents(d(contract["validation_requirement_cents"]) * PRODUCTION_DRAW_PCT)


def recruiter_override_cents(contract):
    return round_cents(d(contract["validation_requirement_cents"]) * RECRUITER_OVERRIDE_PCT)


# ---------------------------------------------------------------------------
# §1.3 persistency_rate_and_renewal
# ---------------------------------------------------------------------------
def persistency_pct(policies_issued, policies_persisted):
    if policies_issued == 0:
        return Decimal("0.00")
    return round_2(Decimal(100) * d(policies_persisted) / d(policies_issued))


def persistency_tier(pct):
    if pct >= TIER_1_MIN:
        return "TIER_1", TIER_1_RATE
    if pct >= TIER_2_MIN:
        return "TIER_2", TIER_2_RATE
    if pct >= TIER_3_MIN:
        return "TIER_3", TIER_3_RATE
    return "INELIGIBLE", Decimal("0.000")


def renewal_commission(base_cents, rate):
    return round_cents(d(base_cents) * d(rate))


# ---------------------------------------------------------------------------
# §1.3 override_allocation
# ---------------------------------------------------------------------------
def rank_rate(rank):
    if rank == "DISTRICT_DIRECTOR":
        return DISTRICT_OVERRIDE_RATE
    if rank == "MANAGING_DIRECTOR":
        return MANAGING_DIRECTOR_OVERRIDE_RATE
    return Decimal("0")


def override_income(ancestor, accruing_descendant_credits, cap_cents):
    """(1) own posture gate, (2) descendant eligibility filter, (3) per-credit
    rank accrual with round-then-sum, (4) single sum-then-cap LAST (§3.6)."""
    if ancestor["contract_status"] == "TERMINATED":
        return 0
    if ancestor["validation_posture"] in ("AT_RISK", "FAILED_POSTURE"):
        return 0
    rate = rank_rate(ancestor["rank"])
    if rate == 0:
        return 0
    total = 0
    for gross in accruing_descendant_credits:
        total += round_cents(d(gross) * rate)
    return min(total, int(cap_cents))