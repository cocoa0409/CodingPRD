"""Scoring a category gap and approving the tier it will sell at."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_status,
    assert_two_decimal_value,
    assert_version_is,
)
from test_helpers.constants import (
    GAP_ANALYZED,
    GAP_DRAFT,
    GAP_TIER_APPROVED,
    TIER_NBE,
    TIER_PREMIUM,
)
from test_helpers.test_users import DIRECTOR_HEADERS, SOURCING_HEADERS


def test_high_turnover_gap_saturates_its_velocity_cap_and_recommends_premium(
    api, program
):
    """Sales 32.00, share 22.50, velocity capped at 15.00 and price 10.00 give 79.50.

    PRD 3.1: "The velocity component is the weekly unit velocity divided by 40,
    rounded half up to two decimals, then capped at 15.00."

    PRD 3.1: "The recommendation is `PREMIUM` when the gap score is at least
    70.00 **and** the national brand's shelf price is at least 500 cents;
    otherwise it is `NBE` when the gap score is at least 45.00; otherwise it is
    `OPENING_PRICE`."

    Design: Difficulty/combinatorial_formula/category_gap_score_nonlinear_clamps
    """
    gap = validate_success(
        api.create_gap(
            f.premium_gap_payload(program["program_id"]), SOURCING_HEADERS
        ),
        expected_status=201,
    )

    scored = validate_success(api.analyze_gap(gap["id"], {}, SOURCING_HEADERS))

    assert_two_decimal_value(scored["gap_score"], 79.50, "gap_score")
    assert scored["recommended_tier"] == TIER_PREMIUM
    assert_status(scored, GAP_ANALYZED, "gap")
    assert scored["approved_tier"] is None


def test_mid_market_gap_scores_every_component_under_its_cap_and_recommends_nbe(
    api, program
):
    """Sales 10.00, share 15.00, velocity 13.00 and a sub-400 price 9.00 give 47.00.

    PRD 3.1: "The price component is a flat 10.00 whenever the national brand's
    shelf price is at least 400 cents, and otherwise the shelf price in cents
    divided by 40, rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/category_gap_score_nonlinear_clamps
    """
    gap = validate_success(
        api.create_gap(f.gap_payload(program["program_id"]), SOURCING_HEADERS),
        expected_status=201,
    )

    scored = validate_success(api.analyze_gap(gap["id"], {}, SOURCING_HEADERS))

    assert_two_decimal_value(scored["gap_score"], 47.00, "gap_score")
    assert scored["recommended_tier"] == TIER_NBE
    assert_status(scored, GAP_ANALYZED, "gap")


def test_reanalysis_restating_one_input_merges_it_with_the_stored_measurements(
    api, analyzed_gap
):
    """Restating only the benchmark price rescores 47.00 to 48.00 from stored values.

    PRD 3.1: "Restated values are written to the gap **first**, and the score is
    then computed from the stored values, so a re-analysis that supplies a
    corrected velocity scores against the corrected velocity."

    Design: Corner/endpoints/gap_analyze_self_loop_rescores_from_partial_input_restatement
    """
    gap_id = analyzed_gap["gap_id"]
    before = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_two_decimal_value(before["gap_score"], 47.00, "gap_score before")

    rescored = validate_success(
        api.analyze_gap(gap_id, {"nb_retail_price_cents": 649}, SOURCING_HEADERS)
    )

    assert rescored["nb_retail_price_cents"] == 649
    assert rescored["category_annual_sales_cents"] == 250000000
    assert_two_decimal_value(rescored["pl_share_pct"], 20.0, "pl_share_pct")
    assert rescored["unit_velocity_per_week"] == 520
    assert_two_decimal_value(rescored["gap_score"], 48.00, "gap_score after")
    assert rescored["recommended_tier"] == TIER_NBE
    assert_status(rescored, GAP_ANALYZED, "gap")
    assert_version_is(rescored, before["version"] + 1, "gap")
    assert rescored["approved_tier"] is None


def test_tier_decision_on_a_gap_that_was_never_analyzed_is_rejected(api, draft_gap):
    """A DRAFT gap has no score to judge, so the decision is refused outright.

    PRD 3.1: "The tier decision belongs to a `ProgramDirector` alone and requires
    the gap to be `ANALYZED`; from any other status it is refused with
    `ERR_GAP_NOT_ANALYZED` (HTTP 409)."

    Design: Corner/validations/tier_decision_on_unanalyzed_gap_rejected
    """
    gap_id = draft_gap["gap_id"]

    response = api.decide_gap_tier(
        gap_id, f.tier_decision_payload(approved_tier=TIER_NBE), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_GAP_NOT_ANALYZED.value, 409)

    gap = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_status(gap, GAP_DRAFT, "gap")
    assert gap["gap_score"] is None
    assert gap["recommended_tier"] is None
    assert gap["approved_tier"] is None


def test_overriding_the_recommended_tier_without_a_justification_is_rejected(
    api, analyzed_gap
):
    """Approving PREMIUM over a recommended NBE demands a written justification.

    PRD 3.1: "A director is free to overrule the recommendation, but when
    `approved_tier` differs from `recommended_tier` a non-empty
    `override_justification` must accompany the decision; omitting it, or
    supplying it empty, is refused with `ERR_OVERRIDE_JUSTIFICATION_REQUIRED`
    (HTTP 422)."

    Design: Corner/validations/tier_override_without_justification_rejected
    """
    gap_id = analyzed_gap["gap_id"]

    response = api.decide_gap_tier(
        gap_id, f.tier_decision_payload(approved_tier=TIER_PREMIUM), DIRECTOR_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_OVERRIDE_JUSTIFICATION_REQUIRED.value, 422)

    gap = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_status(gap, GAP_ANALYZED, "gap")
    assert_two_decimal_value(gap["gap_score"], 47.00, "gap_score")
    assert gap["recommended_tier"] == TIER_NBE
    assert gap["approved_tier"] is None


def test_reanalysis_of_a_tier_approved_gap_is_rejected_and_rescores_nothing(
    api, tier_approved_gap
):
    """TIER_APPROVED is terminal for analysis, so a restated velocity is discarded.

    PRD 3.1: "A gap that has already reached `TIER_APPROVED` or `REJECTED` can no
    longer be analysed, and the attempt is refused with `ERR_GAP_STATE_INVALID`
    (HTTP 409)."

    Design: Corner/state_machines/gap_analyze_after_tier_approved_rejected
    """
    gap_id = tier_approved_gap["gap_id"]

    response = api.analyze_gap(
        gap_id, {"unit_velocity_per_week": 900}, SOURCING_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_GAP_STATE_INVALID.value, 409)

    gap = validate_success(api.get_gap(gap_id, SOURCING_HEADERS))
    assert_status(gap, GAP_TIER_APPROVED, "gap")
    assert_two_decimal_value(gap["gap_score"], 47.00, "gap_score")
    assert gap["unit_velocity_per_week"] == 520, "the restated input must be discarded"
