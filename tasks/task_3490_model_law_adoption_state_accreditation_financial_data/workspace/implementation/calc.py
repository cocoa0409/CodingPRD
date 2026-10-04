"""Calculation rules (scaffold 1.3 / PRD 3). Exact formulas, pinned rounding."""

from datetime import timedelta
from decimal import Decimal, getcontext
from fractions import Fraction

from db import store, base_record
from util import rhu

getcontext().prec = 60

# ballot_adoption_rule constants
QUORUM = Fraction(3, 5)          # 0.60
SUPERMAJORITY = Fraction(2, 3)   # two-thirds

# rbc_action_level floors (inclusive lower edge of each upper band)
NONE_FLOOR = Decimal("2.0000")
COMPANY_FLOOR = Decimal("1.5000")
REGULATORY_FLOOR = Decimal("1.0000")
AUTHORIZED_FLOOR = Decimal("0.7000")

# accreditation_score
PASS_THRESHOLD = Decimal("75.0")

# exam_priority_score
COMPLAINT_WEIGHT = Decimal("0.5")
COMPLAINT_CAP = Decimal("50")
NEUTRAL_RBC_POINTS = Decimal("25")
SCORE_CAP = Decimal("100")

# cost_share_assessment
MIN_SHARE = Fraction(5, 100)     # 0.05

# core_act_coverage
MIN_COVERAGE_PCT = Decimal("50.0")

# review auto-creation
AUTO_REVIEW_PERIOD_DAYS = 180
MIN_REVIEW_GAP = timedelta(days=180)
MIN_COMMENT_WINDOW = timedelta(days=30)
MIN_CALL_COST_CENTS = 100000


def _ceil_frac(fr):
    return -(-fr.numerator // fr.denominator)


# ---------------------------------------------------------------------------
# ballot_adoption_rule
# ---------------------------------------------------------------------------

def ballot_passes(eligible_count, votes_cast, favorable):
    """Integer arithmetic with ceil at exactly the two pinned points."""
    quorum = _ceil_frac(QUORUM * eligible_count)
    required_yea = _ceil_frac(SUPERMAJORITY * votes_cast)
    return votes_cast >= quorum and favorable >= required_yea


# ---------------------------------------------------------------------------
# rbc_capital_aggregation + rbc_action_level
# ---------------------------------------------------------------------------

def action_level_for(ratio_covariance):
    if ratio_covariance >= NONE_FLOOR:
        return "NONE"
    if ratio_covariance >= COMPANY_FLOOR:
        return "COMPANY_ACTION"
    if ratio_covariance >= REGULATORY_FLOOR:
        return "REGULATORY_ACTION"
    if ratio_covariance >= AUTHORIZED_FLOOR:
        return "AUTHORIZED_CONTROL"
    return "MANDATORY_CONTROL"


def rbc_values(surplus_cents, asset_cents, uw_cents, other_cents):
    """Pinned rounding order: square+sum integer cents, sqrt, round ACL to 2
    decimals half-up, THEN divide by the ROUNDED ACL (4 decimals half-up)."""
    tac = rhu(Decimal(surplus_cents), 2)
    sumsq = asset_cents * asset_cents + uw_cents * uw_cents + other_cents * other_cents
    acl_cov = rhu(Decimal(sumsq).sqrt(), 2)
    acl_add = rhu(Decimal(asset_cents + uw_cents + other_cents), 2)
    if acl_cov == 0:
        # Unpinned edge: zero risk charges make the ratio undefined.
        # Treated as 0.0000 (=> MANDATORY_CONTROL) rather than erroring.
        ratio_cov = Decimal("0.0000")
    else:
        ratio_cov = rhu(tac / acl_cov, 4)
    if acl_add == 0:
        ratio_add = Decimal("0.0000")
    else:
        ratio_add = rhu(tac / acl_add, 4)
    return {
        "tac_cents": tac,
        "acl_covariance_cents": acl_cov,
        "acl_additive_cents": acl_add,
        "ratio_covariance": ratio_cov,
        "ratio_additive": ratio_add,
        "action_level": action_level_for(ratio_cov),
    }


# ---------------------------------------------------------------------------
# accreditation_score (desk + onsite variants)
# ---------------------------------------------------------------------------

def score_pct(compliant, total):
    return rhu(Decimal(100) * Decimal(compliant) / Decimal(total), 1)


def proposed_outcome_for(onsite_score):
    return "PASS" if onsite_score >= PASS_THRESHOLD else "FAIL"


# ---------------------------------------------------------------------------
# exam_priority_score
# ---------------------------------------------------------------------------

def exam_priority_score(premium_cents, complaint_count, insurer, total_premium_incl_self):
    complaints_per_million = (Decimal(100000000) * Decimal(complaint_count)) / Decimal(premium_cents)
    complaint_points = COMPLAINT_WEIGHT * min(COMPLAINT_CAP, complaints_per_million)

    ratio = insurer["latest_rbc_ratio"]
    if ratio is None:
        rbc_points = NEUTRAL_RBC_POINTS
    elif ratio < AUTHORIZED_FLOOR:
        rbc_points = Decimal("50")
    elif ratio < REGULATORY_FLOOR:
        rbc_points = Decimal("35")
    elif ratio < COMPANY_FLOOR:
        rbc_points = Decimal("20")
    elif ratio < NONE_FLOOR:
        rbc_points = Decimal("10")
    else:
        rbc_points = Decimal("0")

    share = Fraction(premium_cents, total_premium_incl_self)
    if share >= Fraction(25, 100):
        share_points = Decimal("20")
    elif share >= Fraction(10, 100):
        share_points = Decimal("10")
    else:
        share_points = Decimal("0")

    raw = complaint_points + rbc_points + share_points
    return rhu(min(SCORE_CAP, raw), 2)


# ---------------------------------------------------------------------------
# cost_share_assessment (pinned two-pass largest-remainder, run exactly once)
# ---------------------------------------------------------------------------

def cost_share_allocation(total_cost_cents, responses):
    """Returns {response_id: (allocated_cost_cents, cost_share_excluded)}."""
    premiums = [r["direct_premium_cents"] for r in responses]
    total_premium = sum(premiums)
    pass1 = [Fraction(p, total_premium) for p in premiums]
    survivors = [i for i, s in enumerate(pass1) if s >= MIN_SHARE]
    excluded = [i for i in range(len(responses)) if i not in survivors]
    if not survivors:
        # Pinned empty-set fallback: no exclusion applied at all.
        survivors = list(range(len(responses)))
        excluded = []

    surv_premium = sum(premiums[i] for i in survivors)
    raw = {i: Fraction(total_cost_cents * premiums[i], surv_premium) for i in survivors}
    allocated = {i: raw[i].numerator // raw[i].denominator for i in survivors}  # floor
    frac = {i: raw[i] - allocated[i] for i in survivors}
    remainder = total_cost_cents - sum(allocated.values())
    # Descending fractional part; ties broken by insurer_naic_code ascending.
    order = sorted(survivors, key=lambda i: (-frac[i], responses[i]["insurer_naic_code"]))
    for i in order[:remainder]:
        allocated[i] += 1

    result = {}
    for i in survivors:
        result[responses[i]["id"]] = (allocated[i], False)
    for i in excluded:
        result[responses[i]["id"]] = (0, True)
    return result


# ---------------------------------------------------------------------------
# core_act_coverage
# ---------------------------------------------------------------------------

def recompute_coverage(state):
    """100.0 x certified core adoptions / published core acts; 100.0 if none."""
    numerator = 0
    for ad in store.adoptions.values():
        if ad["state_code"] == state["code"] and ad["status"] in (
            "CERTIFIED_SIMILAR",
            "CERTIFIED_VARIED",
        ):
            act = store.model_acts.get(ad["model_act_id"])
            if act is not None and act["is_core"]:
                numerator += 1
    denominator = sum(
        1 for a in store.model_acts.values() if a["status"] == "PUBLISHED" and a["is_core"]
    )
    if denominator == 0:
        state["core_act_coverage_pct"] = Decimal("100.0")
    else:
        state["core_act_coverage_pct"] = rhu(
            Decimal(100) * Decimal(numerator) / Decimal(denominator), 1
        )


def auto_create_coverage_review(state):
    """Publish cascade hop 4: AUTO_COVERAGE review for the given state."""
    rec = base_record()
    rec.update({
        "state_id": state["id"],
        "period_start": store.clock,
        "period_end": store.clock + timedelta(days=AUTO_REVIEW_PERIOD_DAYS),
        "team_lead_id": None,
        "self_assessment_compliant": 0,
        "self_assessment_total": 1,
        "desk_score": score_pct(0, 1),
        "findings_compliant": None,
        "findings_total": None,
        "onsite_score": None,
        "proposed_outcome": None,
        "origin": "AUTO_COVERAGE",
        "status": "SCHEDULED",
    })
    store.reviews[rec["id"]] = rec
    return rec
