"""Scholarship sliding-scale awards: preview vs final variants and the tier formula."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    BRANCH_DIRECTOR_HEADERS,
    assert_branch_pool_invariants,
    assert_cents,
    assert_fraction,
    assert_ratio,
    make_member_headers,
)
from test_helpers import fixtures


def test_preview_and_final_award_diverge_after_income_correction(api):
    """The provisional tier at submission and the final tier at approval are two
    separate computations: the preview reads the declared income, the approval
    recomputes from the corrected verified income supplied through resubmission.

    PRD §3.4: "The provisional tier is written to `preview_award_pct`: a ratio
    strictly below 0.30 previews 0.75; a ratio of exactly 0.30 or above but
    strictly below 0.50 previews 0.50; a ratio of exactly 0.50 or above but
    strictly below 0.80 previews 0.25; and a ratio of exactly 0.80 or above is
    ineligible."
    PRD §3.4: "Resubmission recomputes `income_ratio` and `preview_award_pct`
    from the updated inputs."
    PRD §3.4: "A successful approval writes `award_pct`, computes
    `award_obligation_cents` as that annualized amount, sets `award_start_on` to
    the current date and `award_end_on` to `award_start_on` plus 365 days (the
    annual renewal boundary), and cascades: the membership's `assistance_pct`
    becomes the awarded fraction and the membership's `version` increments by
    one; the branch's `scholarship_pool_obligated_cents` increases by
    `award_obligation_cents`, which lowers `scholarship_pool_available_cents` by
    the same amount; and every `PENDING` draft of the membership has its
    `amount_cents` recomputed under the new assistance fraction."
    PRD §3.4: "Because verified income may differ from the declared figures, the
    final `award_pct` can legitimately differ from `preview_award_pct`."

    Design: Difficulty/dual_variant_calc/scholarship_preview_vs_final_award_diverge_after_income_correction
    """
    world = fixtures.setup_funded_pool(api, amount_cents=200_000)

    # Declared income 2,000,000 on a one-person household: ratio 0.4000 -> preview 0.50.
    application = fixtures.submit_application(api, world, household_size=1, annual_income_cents=2_000_000)
    assert_ratio(application["income_ratio"], 0.4000, "application.income_ratio")
    assert_fraction(application["preview_award_pct"], 0.50, "application.preview_award_pct")

    get_success_data(api.review_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    get_success_data(api.request_info_application(application["id"], BRANCH_DIRECTOR_HEADERS))

    # Verified income 1,300,000: ratio 0.2600 -> final award 0.75.
    resubmitted = get_success_data(
        api.submit_info_application(
            application["id"],
            {"documentation": ["TAX_RETURN"], "annual_income_cents": 1_300_000},
            make_member_headers(world["member"]["id"]),
        )
    )
    assert_ratio(resubmitted["income_ratio"], 0.2600, "resubmitted.income_ratio")

    approved = get_success_data(
        api.approve_application(
            application["id"],
            {"expected_membership_version": world["membership"]["version"]},
            BRANCH_DIRECTOR_HEADERS,
        )
    )
    assert_fraction(approved["preview_award_pct"], 0.75, "approved.preview_award_pct")
    assert_fraction(approved["award_pct"], 0.75, "approved.award_pct")
    assert application["preview_award_pct"] != approved["award_pct"], (
        "the provisional tier from the declared income must diverge from the "
        "final award computed from the corrected verified income"
    )
    assert_cents(approved["award_obligation_cents"], 72_000, "application.award_obligation_cents")

    membership = get_success_data(api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_fraction(membership["assistance_pct"], 0.75, "membership.assistance_pct")

    branch = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(branch["scholarship_pool_available_cents"], 128_000, "branch.pool_available")
    assert_branch_pool_invariants(branch)


def test_final_award_recomputed_from_verified_inputs_not_declared_preview(api):
    """The approve transition recomputes the ratio from the verified inputs; the
    declared-income preview tier never obligates the pool.

    PRD §3.4: "The preview is informational only — it obligates nothing from the
    pool and never touches the membership's `assistance_pct`."
    PRD §3.4: "the final `income_ratio` is recomputed from the verified inputs
    and must yield an `award_pct` among 0.25, 0.50, or 0.75"
    PRD §3.4: "Resubmission recomputes `income_ratio` and `preview_award_pct`
    from the updated inputs."

    Design: Difficulty/dual_variant_calc/scholarship_preview_vs_final_award_diverge_after_income_correction
    """
    world = fixtures.setup_funded_pool(api, amount_cents=200_000)

    # Declared income 1,000,000 -> ratio 0.2000 -> preview 0.75.
    application = fixtures.submit_application(api, world, household_size=1, annual_income_cents=1_000_000)
    assert_fraction(application["preview_award_pct"], 0.75, "application.preview_award_pct")

    # Before any adjudication the pool carries no obligation and the membership
    # carries no assistance: the preview is informational only.
    branch = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(branch["scholarship_pool_obligated_cents"], 0, "branch.pool_obligated")
    membership = get_success_data(api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_fraction(membership["assistance_pct"], 0, "membership.assistance_pct")

    get_success_data(api.review_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    get_success_data(api.request_info_application(application["id"], BRANCH_DIRECTOR_HEADERS))

    # Verified income 2,500,000 -> ratio 0.5000 -> final award 0.25, not the previewed 0.75.
    get_success_data(
        api.submit_info_application(
            application["id"],
            {"documentation": ["TAX_RETURN"], "annual_income_cents": 2_500_000},
            make_member_headers(world["member"]["id"]),
        )
    )
    approved = get_success_data(
        api.approve_application(
            application["id"],
            {"expected_membership_version": world["membership"]["version"]},
            BRANCH_DIRECTOR_HEADERS,
        )
    )
    assert_fraction(approved["award_pct"], 0.25, "approved.award_pct")
    assert_cents(approved["award_obligation_cents"], 24_000, "application.award_obligation_cents")

    branch = get_success_data(api.get_branch(world["branch"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_cents(branch["scholarship_pool_obligated_cents"], 24_000, "branch.pool_obligated")
    assert_branch_pool_invariants(branch)


def test_sliding_scale_multi_input_boundary_ratio_exactly_point_three(api):
    """Household size feeds a nested min(n, 12) multiplier, the ratio rounds to
    four decimals before comparison, and a ratio of exactly 0.3000 is NOT below
    0.30, so it falls to the 0.50 tier.

    PRD §3.4: "The household multiplier is 0.80 plus 0.20 times the household
    size capped at 12 — so a household of one yields 1.00, two yields 1.20, four
    yields 1.60, and twelve yields 3.20 — expressed with two decimal places
    rounded half-up."
    PRD §3.4: "The `income_ratio` is then the `annual_income_cents` divided by
    the product of the association's `ami_base_cents` and that household
    multiplier, rounded to four decimal places half-up before any tier
    comparison is made."
    PRD §3.4: "a ratio of exactly 0.30 or above but strictly below 0.50 previews
    0.50"

    Design: Difficulty/combinatorial_formula/sliding_scale_multi_input_tiered_with_nested_min_and_rounding
    """
    world = fixtures.setup_funded_pool(
        api, amount_cents=300_000, household_type="FAMILY", max_adults=2, max_dependents=6
    )

    # Household of four -> multiplier 1.60; income 2,400,000 / (5,000,000 * 1.60) = 0.3000 exactly.
    application = fixtures.submit_application(api, world, household_size=4, annual_income_cents=2_400_000)
    assert_ratio(application["income_ratio"], 0.3000, "application.income_ratio")
    assert_fraction(application["preview_award_pct"], 0.50, "application.preview_award_pct")

    get_success_data(api.review_application(application["id"], BRANCH_DIRECTOR_HEADERS))
    approved = get_success_data(
        api.approve_application(
            application["id"],
            {"expected_membership_version": world["membership"]["version"]},
            BRANCH_DIRECTOR_HEADERS,
        )
    )
    assert_ratio(approved["income_ratio"], 0.3000, "approved.income_ratio")
    assert_fraction(approved["award_pct"], 0.50, "approved.award_pct")
    assert_cents(approved["award_obligation_cents"], 48_000, "application.award_obligation_cents")

    membership = get_success_data(api.get_membership(world["membership"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert_fraction(membership["assistance_pct"], 0.50, "membership.assistance_pct")


def test_sliding_scale_household_size_alone_flips_the_tier(api):
    """With income and AMI fixed, moving only household_size from 1 to 4 moves
    the ratio from 0.6000 to 0.3750 and the award from the 0.25 tier to the
    0.50 tier.

    PRD §3.4: "The household multiplier is 0.80 plus 0.20 times the household
    size capped at 12 — so a household of one yields 1.00, two yields 1.20, four
    yields 1.60, and twelve yields 3.20 — expressed with two decimal places
    rounded half-up."
    PRD §3.4: "a ratio strictly below 0.30 previews 0.75; a ratio of exactly
    0.30 or above but strictly below 0.50 previews 0.50; a ratio of exactly 0.50
    or above but strictly below 0.80 previews 0.25"

    Design: Difficulty/combinatorial_formula/sliding_scale_multi_input_tiered_with_nested_min_and_rounding
    """
    world = fixtures.setup_funded_pool(
        api, amount_cents=300_000, household_type="FAMILY", max_adults=2, max_dependents=6
    )

    # Income 3,000,000, household 1 -> ratio 0.6000 -> 0.25 tier.
    solo = fixtures.submit_application(api, world, household_size=1, annual_income_cents=3_000_000)
    assert_ratio(solo["income_ratio"], 0.6000, "solo.income_ratio")
    assert_fraction(solo["preview_award_pct"], 0.25, "solo.preview_award_pct")

    # Same income, household 4 -> ratio 0.3750 -> 0.50 tier: size alone flipped the tier.
    family = fixtures.submit_application(api, world, household_size=4, annual_income_cents=3_000_000)
    assert_ratio(family["income_ratio"], 0.3750, "family.income_ratio")
    assert_fraction(family["preview_award_pct"], 0.50, "family.preview_award_pct")
