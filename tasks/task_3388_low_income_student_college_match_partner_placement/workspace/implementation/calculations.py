"""Calculation rules (SCAFFOLD section 1.3 / PRD section 3).

All monetary values are integer cents. Rounding is round-half-up to whole
cents at the pinned rounding points; the grant component is the deliberate
unrounded remainder. Floats are never used for money.
"""
from decimal import Decimal, ROUND_HALF_UP

import store

# household_income_cap
BASE_CAP_CENTS = 6500000
REF_HOUSEHOLD_SIZE = 4
PER_MEMBER_ADJUST_CENTS = 400000

# academic_index / academic_eligibility
AI_CAP = 2000
AI_GPA_WEIGHT = 2
AI_TEST_DIVISOR = 4
MIN_GPA_SCALED = 350
MIN_TEST_SCORE = 1200
PREP_WAIVER_MIN_GPA = 330

# need_tier
NEED_HIGH_FRACTION = Decimal("0.5")

# expected_family_contribution
P_ALLOW_BASE_CENTS = 2400000
P_ALLOW_PER_MEMBER_CENTS = 600000
P_RATE = Decimal("0.20")
V_ASSET_RATE = Decimal("0.12")
V_ALLOW_BASE_CENTS = 2000000
V_ALLOW_PER_MEMBER_CENTS = 550000
V_RATE = Decimal("0.22")

# aid_package_composition
WORK_STUDY_CAP_CENTS = 300000
WORK_STUDY_RATE = Decimal("0.10")
LOAN_CAP_CENTS = 150000
LOAN_RATE = Decimal("0.20")

# match_priority_score
PREP_ALUM_BONUS = 40
REFERRAL_BONUS = 25
NEED_AWARE_BONUS = 15

# ranking_list_shape
MAX_RANKS = 12

# discrepancy_assessment
DISCREPANCY_MAX_PCT = 10

# persistence_rates
RATE_SCALE_BP = 10000


def _rhu(value):
    """Round a Decimal half-up to a whole cent."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def income_cap_cents(household_size):
    return BASE_CAP_CENTS + (household_size - REF_HOUSEHOLD_SIZE) * PER_MEMBER_ADJUST_CENTS


def income_eligible(household_income_cents, household_size):
    # Boundary: income exactly equal to the cap IS eligible (<=).
    return household_income_cents <= income_cap_cents(household_size)


def compute_prep_alum(student_id):
    """True iff the student has at least one COMPLETED PrepProgram right now."""
    return any(
        p["student_id"] == student_id and p["status"] == "COMPLETED"
        for p in store.prep_programs.values()
    )


def academic_index(gpa_scaled, test_score):
    test_component = 0 if test_score is None else test_score // AI_TEST_DIVISOR
    return min(AI_CAP, gpa_scaled * AI_GPA_WEIGHT + test_component)


def academic_eligible(prep_alum, gpa_scaled, test_score):
    # Every comparison is inclusive of its boundary.
    if prep_alum:
        return gpa_scaled >= PREP_WAIVER_MIN_GPA
    return (
        gpa_scaled >= MIN_GPA_SCALED
        and test_score is not None
        and test_score >= MIN_TEST_SCORE
    )


def need_tier(household_income_cents, household_size):
    half_cap = _rhu(Decimal(income_cap_cents(household_size)) * NEED_HIGH_FRACTION)
    return "HIGH" if household_income_cents <= half_cap else "STANDARD"


def efc_provisional(household_income_cents, household_size):
    allowance = P_ALLOW_BASE_CENTS + household_size * P_ALLOW_PER_MEMBER_CENTS
    return max(0, _rhu(Decimal(household_income_cents - allowance) * P_RATE))


def efc_verified(verified_income_cents, verified_assets_cents, verified_household_size):
    # The asset add-back is rounded BEFORE the rate multiplication (pinned
    # rounding order).
    asset_addback = _rhu(Decimal(verified_assets_cents) * V_ASSET_RATE)
    allowance = V_ALLOW_BASE_CENTS + verified_household_size * V_ALLOW_PER_MEMBER_CENTS
    return max(0, _rhu(Decimal(verified_income_cents + asset_addback - allowance) * V_RATE))


def compose_package(coa_cents, efc_cents, aid_policy):
    """Waterfall allocation in the pinned evaluation order; each component is
    rounded half-up BEFORE its cap; grant is the unrounded remainder."""
    need_cents = max(0, coa_cents - efc_cents)
    work_study_cents = min(WORK_STUDY_CAP_CENTS, _rhu(Decimal(need_cents) * WORK_STUDY_RATE))
    if aid_policy == "NO_LOAN":
        loan_cents = 0
    else:  # MINIMAL_LOAN
        loan_cents = min(LOAN_CAP_CENTS, _rhu(Decimal(need_cents - work_study_cents) * LOAN_RATE))
    grant_cents = need_cents - work_study_cents - loan_cents
    return need_cents, work_study_cents, loan_cents, grant_cents


def priority_score(application, college, referral_converted):
    score = application["academic_index"] or 0
    if application["prep_alum"]:
        score += PREP_ALUM_BONUS
    if referral_converted:
        score += REFERRAL_BONUS
    if college["aid_policy"] == "NO_LOAN" and application["need_tier"] == "HIGH":
        score += NEED_AWARE_BONUS
    return score


def discrepancy_outcome(reported_income_cents, verified_income_cents):
    """Exact integer cross-multiplication; a difference of exactly ten percent
    of the reported figure is VERIFIED (strictly greater breaches)."""
    if reported_income_cents == 0:
        return "VERIFIED" if verified_income_cents == 0 else "DISCREPANCY"
    diff = abs(verified_income_cents - reported_income_cents)
    if diff * 100 > reported_income_cents * DISCREPANCY_MAX_PCT:
        return "DISCREPANCY"
    return "VERIFIED"


def rate_bp(numerator, denominator):
    """Basis points, round-half-up; an empty denominator reports 0."""
    if denominator == 0:
        return 0
    # floor((num*10000)/den + 1/2) with exact integer arithmetic
    return (numerator * RATE_SCALE_BP * 2 + denominator) // (2 * denominator)


def latest_list_seq(application_id):
    """Greatest RankingEntry list_seq for the application; 0 if none yet."""
    seqs = [e["list_seq"] for e in store.ranking_entries.values()
            if e["application_id"] == application_id]
    return max(seqs) if seqs else 0


def latest_decided_verification(application_id):
    """The latest IncomeVerification of the application in a decided state
    (VERIFIED, DISCREPANCY, or WAIVED); None if none is decided."""
    records = [
        v for v in store.verifications.values()
        if v["application_id"] == application_id
        and v["outcome"] in ("VERIFIED", "DISCREPANCY", "WAIVED")
    ]
    if not records:
        return None
    records.sort(key=lambda v: v["created_at"])  # stable: insertion order breaks ties
    return records[-1]


def latest_verified_verification(application_id):
    records = [
        v for v in store.verifications.values()
        if v["application_id"] == application_id and v["outcome"] == "VERIFIED"
    ]
    if not records:
        return None
    records.sort(key=lambda v: v["created_at"])
    return records[-1]


def create_package(match_id, application, college, guaranteed_full_need):
    """Create a PROVISIONAL AidPackage under the PROVISIONAL EFC variant."""
    efc = efc_provisional(application["household_income_cents"], application["household_size"])
    need, work_study, loan, grant = compose_package(
        college["coa_cents"], efc, college["aid_policy"])
    return store.create(store.aid_packages, {
        "match_id": match_id,
        "application_id": application["id"],
        "college_id": college["id"],
        "coa_cents": college["coa_cents"],
        "efc_cents": efc,
        "need_cents": need,
        "work_study_cents": work_study,
        "loan_cents": loan,
        "grant_cents": grant,
        "aid_variant": "PROVISIONAL",
        "guaranteed_full_need": guaranteed_full_need,
        "status": "PROVISIONAL",
    })


def recompute_package(package):
    """Recompute all amounts under the package's current aid_variant."""
    application = store.applications.get(package["application_id"])
    college = store.colleges.get(package["college_id"])
    if package["aid_variant"] == "VERIFIED":
        verification = latest_verified_verification(package["application_id"])
        efc = efc_verified(
            verification["verified_income_cents"],
            verification["verified_assets_cents"],
            verification["verified_household_size"],
        )
    else:
        efc = efc_provisional(
            application["household_income_cents"], application["household_size"])
    need, work_study, loan, grant = compose_package(
        package["coa_cents"], efc, college["aid_policy"])
    package["efc_cents"] = efc
    package["need_cents"] = need
    package["work_study_cents"] = work_study
    package["loan_cents"] = loan
    package["grant_cents"] = grant
