"""Priority scoring, income eligibility, and verification gates (PRD §3.2/§3.3)."""

from test_helpers import (
    ApiErrorId,
    api_client,
    complete_assessment,
    create_application,
    create_assessment,
    create_cycle,
    create_verified_application,
    get_application,
    patch_application_status,
    reset_clock,
    scope_assessment,
    scope_item_payload,
    validate_error,
    STAFF,
)


def test_priority_score_standard_mode_ignores_hazard_severity():
    """PRD §3.3: "Under a cycle whose `priority_mode` is `HAZARD_PRIORITY`, the
    score's hazard bonus is ten points per severity level of the
    `safety_hazard_max_severity` recorded on the latest `SCOPED` assessment,
    while under `STANDARD` the bonus is zero and severity never enters the
    score at all."
    PRD §3.2: "The score starts from a base of 40 points when `is_older_adult`
    is true, plus 25 points when `is_veteran` is true, plus 30 points when
    `has_disability` is true."

    Older-adult veteran (base 65), household_size 2, income 3000000 -> low tier
    (3000000*100 <= 50*6170000), multiplier 1.25: round_half_up(81.25) = 81 both
    before and after a severity-4 assessment is scoped under STANDARD.

    Design: Difficulty/dual_variant_calc/priority_score_standard_vs_hazard_mode_diverge
    """
    reset_clock()
    cycle = create_cycle(total_budget_cents=2_000_000, priority_mode="STANDARD")
    app = create_verified_application(
        cycle["id"],
        homeowner_name="Olga Older",
        date_of_birth="1960-05-05",
        household_size=2,
        household_income_cents=3_000_000,
        is_veteran=True,
    )
    assert app["priority_score"] == 81, (
        f"pre-scope STANDARD score must be round_half_up(65 * 1.25) = 81, "
        f"got {app['priority_score']}"
    )
    asm = create_assessment(app["id"], scheduled_on="2026-09-02")
    complete_assessment(
        asm["id"],
        scope_items=[
            scope_item_payload(
                category="SAFETY",
                est_low_cents=100_000,
                est_high_cents=200_000,
                description="grab bars",
            )
        ],
        safety_hazard_max_severity=4,
        accessibility_needs_count=1,
    )
    scope_assessment(asm["id"])
    app_after = get_application(app["id"])
    assert app_after["priority_score"] == 81, (
        "STANDARD mode must ignore safety_hazard_max_severity 4 after scoping"
    )


def test_priority_score_hazard_mode_adds_severity_bonus_and_clamps():
    """PRD §3.3: "Under a cycle whose `priority_mode` is `HAZARD_PRIORITY`, the
    score's hazard bonus is ten points per severity level of the
    `safety_hazard_max_severity` recorded on the latest `SCOPED` assessment,
    while under `STANDARD` the bonus is zero and severity never enters the
    score at all."
    PRD §3.3: "While no assessment has been scoped, the hazard term is zero
    regardless of mode."
    PRD §3.2: "The base is then multiplied by the tier factor — one and a half
    for the deep-need tier, one and a quarter for the low tier, exactly one for
    the standard tier — then a hazard bonus is added, then the result is rounded
    half up to an integer, and finally the score is clamped into the inclusive
    range 0 to 100."

    Identical household under HAZARD_PRIORITY: 81 pre-scope (hazard term 0),
    then round_half_up(81.25 + 10 * 4) = 121 clamped to 100 after scoping.

    Design: Difficulty/dual_variant_calc/priority_score_standard_vs_hazard_mode_diverge
    """
    reset_clock()
    cycle = create_cycle(
        total_budget_cents=2_000_000, priority_mode="HAZARD_PRIORITY"
    )
    app = create_verified_application(
        cycle["id"],
        homeowner_name="Olga Older",
        date_of_birth="1960-05-05",
        household_size=2,
        household_income_cents=3_000_000,
        is_veteran=True,
    )
    assert app["priority_score"] == 81, (
        "hazard term must be 0 while no assessment is scoped, even under "
        f"HAZARD_PRIORITY; got {app['priority_score']}"
    )
    asm = create_assessment(app["id"], scheduled_on="2026-09-02")
    complete_assessment(
        asm["id"],
        scope_items=[
            scope_item_payload(
                category="SAFETY",
                est_low_cents=100_000,
                est_high_cents=200_000,
                description="grab bars",
            )
        ],
        safety_hazard_max_severity=4,
        accessibility_needs_count=1,
    )
    scope_assessment(asm["id"])
    app_after = get_application(app["id"])
    assert app_after["priority_score"] == 100, (
        f"expected round_half_up(65 * 1.25 + 10 * 4) = 121 clamped to 100, "
        f"got {app_after['priority_score']}"
    )


def test_priority_score_deep_tier_boundary_clamps_at_ceiling():
    """PRD §3.2: "Income at or below 30% of AMI is the deep-need tier; income
    above 30% but at or below 50% of AMI is the low tier; anything higher that
    still passed the 80% eligibility ceiling is the standard tier."
    PRD §3.2: "The AMI table, in integer cents, is: one occupant 5,400,000
    (that is, $54,000); two occupants 6,170,000; three 6,940,000; four
    7,710,000; five 8,330,000; six 8,950,000; seven 9,560,000; eight
    10,180,000."

    Older-adult disabled applicant (base 70), household_size 1, income exactly
    30% of AMI (1620000 * 100 <= 30 * 5400000 with equality): 70 * 1.5 = 105,
    clamped to the 100 ceiling.

    Design: Difficulty/combinatorial_formula/priority_score_tier_boundary_and_ceiling_clamp
    """
    reset_clock()
    cycle = create_cycle(total_budget_cents=5_000_000)
    app_x = create_verified_application(
        cycle["id"],
        homeowner_name="X Deep",
        date_of_birth="1960-05-05",
        household_size=1,
        household_income_cents=1_620_000,
        has_disability=True,
    )
    assert app_x["priority_score"] == 100, (
        f"base 70 * 1.5 = 105 must clamp to the 100 ceiling; got "
        f"{app_x['priority_score']}"
    )


def test_priority_score_one_cent_over_deep_tier_drops_multiplier():
    """PRD §3.2: "Income at or below 30% of AMI is the deep-need tier; income
    above 30% but at or below 50% of AMI is the low tier; anything higher that
    still passed the 80% eligibility ceiling is the standard tier."

    The same household one cent above the deep-tier boundary (1620001 * 100 >
    30 * 5400000) falls to the low tier: round_half_up(70 * 1.25) =
    round_half_up(87.5) = 88 — one cent of income moves the score by 12.

    Design: Difficulty/combinatorial_formula/priority_score_tier_boundary_and_ceiling_clamp
    """
    reset_clock()
    cycle = create_cycle(total_budget_cents=5_000_000)
    app_y = create_verified_application(
        cycle["id"],
        homeowner_name="Y Low",
        date_of_birth="1960-05-05",
        household_size=1,
        household_income_cents=1_620_001,
        has_disability=True,
    )
    assert app_y["priority_score"] == 88, (
        f"one cent over the 30% boundary must drop to the 1.25 multiplier: "
        f"round_half_up(70 * 1.25) = 88; got {app_y['priority_score']}"
    )


def test_income_exactly_at_80pct_ami_verifies():
    """PRD §3.2: "First, income eligibility: the household qualifies when
    `household_income_cents` scaled by one hundred is at most eighty times the
    area median income for its household size — equivalently, annual income at
    or below 80% of AMI, inclusive, so an income of exactly 80% of AMI passes
    and one cent above fails with `ERR_INCOME_LIMIT_EXCEEDED`."

    household_size 1 at income 4320000 (4320000 * 100 == 80 * 5400000) verifies;
    a flagless applicant scores 0.

    Design: Difficulty/boundary_precision_check/income_exactly_at_80pct_ami_passes_one_cent_over_fails
    """
    reset_clock()
    cycle = create_cycle()
    app = create_verified_application(
        cycle["id"],
        homeowner_name="At Limit",
        date_of_birth="1990-01-01",
        household_size=1,
        household_income_cents=4_320_000,
    )
    assert app["status"] == "VERIFIED"
    assert app["priority_score"] == 0, (
        f"no vulnerability flags means base 0 at any tier; got "
        f"{app['priority_score']}"
    )


def test_income_one_cent_over_80pct_ami_rejected():
    """PRD §3.2: "First, income eligibility: the household qualifies when
    `household_income_cents` scaled by one hundred is at most eighty times the
    area median income for its household size — equivalently, annual income at
    or below 80% of AMI, inclusive, so an income of exactly 80% of AMI passes
    and one cent above fails with `ERR_INCOME_LIMIT_EXCEEDED`."

    Income 4320001 for household_size 1: 4320001 * 100 = 432000100 >
    432000000, so verification is rejected and the application stays
    UNDER_VERIFICATION.

    Design: Difficulty/boundary_precision_check/income_exactly_at_80pct_ami_passes_one_cent_over_fails
    """
    reset_clock()
    cycle = create_cycle()
    app = create_application(
        cycle["id"],
        homeowner_name="Over Limit",
        date_of_birth="1990-01-01",
        household_size=1,
        household_income_cents=4_320_001,
    )
    patch_application_status(app["id"], "UNDER_VERIFICATION")
    resp = api_client.patch_application(app["id"], {"status": "VERIFIED"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INCOME_LIMIT_EXCEEDED)
    app_after = get_application(app["id"])
    assert app_after["status"] == "UNDER_VERIFICATION", (
        "a failed transition must leave the state untouched"
    )


def test_income_tier_at_50pct_boundary_selects_low_over_standard():
    """PRD §3.2: "Income at or below 30% of AMI is the deep-need tier; income
    above 30% but at or below 50% of AMI is the low tier; anything higher that
    still passed the 80% eligibility ceiling is the standard tier."

    Older-adult applicants (base 40), household_size 1: income 2700000 equals
    50% of AMI (2700000 * 100 <= 50 * 5400000 with equality) and keeps the 1.25
    multiplier (score 50); 2700001 drops to the standard tier (score 40).

    Design: Corner/calculations/income_tier_at_50pct_boundary_selects_low_over_standard
    """
    reset_clock()
    cycle = create_cycle()
    app_a = create_verified_application(
        cycle["id"],
        homeowner_name="Tier At",
        date_of_birth="1960-05-05",
        household_size=1,
        household_income_cents=2_700_000,
    )
    assert app_a["priority_score"] == 50, (
        f"exactly 50% of AMI keeps the low tier: 40 * 1.25 = 50; got "
        f"{app_a['priority_score']}"
    )
    app_b = create_verified_application(
        cycle["id"],
        homeowner_name="Tier Over",
        date_of_birth="1960-05-05",
        household_size=1,
        household_income_cents=2_700_001,
    )
    assert app_b["priority_score"] == 40, (
        f"one cent over 50% of AMI drops to the standard tier: 40 * 1.0 = 40; "
        f"got {app_b['priority_score']}"
    )


def test_application_is_older_adult_birthday_boundary():
    """PRD §3.2: "The application is born `SUBMITTED`, and at creation the
    server computes `is_older_adult` from `date_of_birth` against the logical
    clock using calendar birthday math: an applicant aged at least 62 — exactly
    62 counts — is an older adult."

    With the logical clock pinned at 2026-09-01, an applicant born 1964-09-01
    turns exactly 62 (is_older_adult true); born 1964-09-02 does not (false).

    Design: Corner/entities/application_is_older_adult_birthday_boundary
    """
    reset_clock()
    cycle = create_cycle()
    born_on = create_application(
        cycle["id"], homeowner_name="Born On", date_of_birth="1964-09-01"
    )
    born_after = create_application(
        cycle["id"], homeowner_name="Born After", date_of_birth="1964-09-02"
    )
    assert born_on["is_older_adult"] is True, (
        "the 62nd birthday exactly is inclusive"
    )
    assert born_after["is_older_adult"] is False


def test_verify_without_ownership_doc_returns_verification_incomplete():
    """PRD §3.2: "Second, documentation: both `ownership_doc_provided` and
    `occupancy_doc_provided` must be true, otherwise
    `ERR_VERIFICATION_INCOMPLETE`."

    An applicant well under the income cap but missing the ownership document
    is blocked from VERIFIED, proving the documentation gate is independent of
    the income gate.

    Design: Corner/validations/verify_without_ownership_doc_returns_verification_incomplete
    """
    reset_clock()
    cycle = create_cycle()
    app = create_application(
        cycle["id"],
        homeowner_name="No Deed",
        household_income_cents=1_000_000,
        ownership_doc_provided=False,
        occupancy_doc_provided=True,
    )
    patch_application_status(app["id"], "UNDER_VERIFICATION")
    resp = api_client.patch_application(app["id"], {"status": "VERIFIED"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_INCOMPLETE)
    app_after = get_application(app["id"])
    assert app_after["status"] == "UNDER_VERIFICATION"
