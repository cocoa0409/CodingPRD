"""Calculation rules (scaffold 1.3 / PRD section 3). All integer math; the
only rounding anywhere is round-half-up per SME score component."""
from decimal import Decimal, ROUND_HALF_UP

# position_grade_determination constants
WEIGHT_KNOWLEDGE = 300
WEIGHT_SUPERVISION = 200
WEIGHT_COMPLEXITY = 250
WEIGHT_IMPACT = 250

GRADE_BANDS = [
    (1000, 1599, 5),
    (1600, 2199, 7),
    (2200, 2799, 9),
    (2800, 3399, 11),
    (3400, 3899, 12),
    (3900, 4299, 13),
    (4300, 4699, 14),
    (4700, 5000, 15),
]

LEVEL_GRADE_CAP = {1: 5, 2: 7, 3: 9, 4: 11, 5: 13}

# sme_technical_score constants
SME_WEIGHT_KNOWLEDGE = Decimal("0.30")
SME_WEIGHT_SKILL = Decimal("0.20")
SME_WEIGHT_ABILITY = Decimal("0.50")
SME_SCALE = 6
SME_BASE = 70

# category_assignment defaults
DEFAULT_BQ_CUT = 95
DEFAULT_WQ_CUT = 85

# certificate_roster_selection
RULE_OF_MANY_MIN = 3
CATEGORY_RANK = {"BEST_QUALIFIED": 3, "WELL_QUALIFIED": 2, "QUALIFIED": 1}

# certificate_expiry
MAX_EXTENSIONS = 2
EXTENSION_MAX_DAYS = 30

# appeal_window / offer_response_window
APPEAL_WINDOW_DAYS = 14
OFFER_RESPONSE_DAYS = 5


def total_points(k, s, c, i):
    return WEIGHT_KNOWLEDGE * k + WEIGHT_SUPERVISION * s + WEIGHT_COMPLEXITY * c + WEIGHT_IMPACT * i


def provisional_grade(k, s, c, i):
    """Narrative-method preview: min over factors of LEVEL_GRADE_CAP."""
    return min(LEVEL_GRADE_CAP[k], LEVEL_GRADE_CAP[s], LEVEL_GRADE_CAP[c], LEVEL_GRADE_CAP[i])


def official_grade(points):
    """Point-factor band lookup; bands are inclusive at both ends."""
    for lo, hi, grade in GRADE_BANDS:
        if lo <= points <= hi:
            return grade
    return None


def _round_half_up_int(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def sme_technical_score(r_k, r_s, r_a):
    """Pinned order: round each weighted component half-up to an integer
    FIRST, then sum, then add the base of 70."""
    comp_k = _round_half_up_int(SME_WEIGHT_KNOWLEDGE * r_k * SME_SCALE)
    comp_s = _round_half_up_int(SME_WEIGHT_SKILL * r_s * SME_SCALE)
    comp_a = _round_half_up_int(SME_WEIGHT_ABILITY * r_a * SME_SCALE)
    return SME_BASE + comp_k + comp_s + comp_a


def category_for_score(score, bq_cut, wq_cut):
    """Boundaries are >= inclusive at both cut points; raw score only,
    preference points never affect category."""
    if score >= bq_cut:
        return "BEST_QUALIFIED"
    if score >= wq_cut:
        return "WELL_QUALIFIED"
    return "QUALIFIED"


def qualification_determination(app_row, position, series):
    """Returns (required, creditable, qualified). Pinned order: official_grade
    first, then required, then education credit, then creditable, then the
    two conjuncts. Equality qualifies (creditable >= required)."""
    grade = position["official_grade"]
    required = series["quals_base_months"] + (grade - series["min_grade"]) * series["quals_months_per_grade_step"]
    if series["allows_education_substitution"]:
        education_credit = min(app_row["claimed_education_months"], series["education_substitution_cap_months"])
    else:
        education_credit = 0
    creditable = app_row["claimed_experience_months"] + education_credit
    qualified = creditable >= required and (
        not series["positive_education_required"] or app_row["claimed_education_months"] > 0
    )
    return required, creditable, qualified


def preference_state(applicant, verified_doc_types):
    """preference_verified / preference_points from the claim and the set of
    verified document types on file (PRD 3.3)."""
    claim = applicant["veteran_preference_claim"]
    if claim == "NONE":
        return True, 0
    if claim == "FIVE_POINT":
        verified = "DD214" in verified_doc_types
        return verified, (5 if verified else 0)
    # TEN_POINT_CP and TEN_POINT_CPS both need DD214 + VA_LETTER verified
    verified = "DD214" in verified_doc_types and "VA_LETTER" in verified_doc_types
    return verified, (10 if verified else 0)


def select_roster(announcement, apps):
    """certificate_roster_selection. Returns the roster list or None when the
    rule-of-many minimum is not met."""
    if announcement["assessment_method"] == "UNRANKED":
        roster = [a for a in apps if a["status"] == "QUALIFIED"]
        return roster if roster else None
    candidates = [a for a in apps if a["status"] == "RATED"]
    if not candidates:
        return None
    present = sorted({CATEGORY_RANK[a["quality_category"]] for a in candidates}, reverse=True)
    roster = []
    for rank in present:
        if len(roster) >= RULE_OF_MANY_MIN:
            break
        roster.extend(a for a in candidates if CATEGORY_RANK[a["quality_category"]] == rank)
    if len(roster) < RULE_OF_MANY_MIN:
        return None
    return roster


def rank_entries(entry_infos, unranked):
    """certificate_ranking. entry_infos: list of dicts with keys
    quality_category, cps_float, preference_eligible, augmented_score,
    submitted_at, seq. Returns entries in rank order (rank_position is
    1-based position)."""
    if unranked:
        return sorted(entry_infos, key=lambda e: (e["submitted_at"], e["seq"]))

    def key(e):
        return (
            -CATEGORY_RANK[e["quality_category"]],
            0 if e["cps_float"] else 1,
            0 if e["preference_eligible"] else 1,
            -e["augmented_score"],
            e["submitted_at"],
            e["seq"],
        )

    return sorted(entry_infos, key=key)
