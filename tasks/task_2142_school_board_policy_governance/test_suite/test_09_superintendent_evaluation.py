"""The annual superintendent evaluation: rubric weights, ratings and the two composites."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_evaluation,
    api_client,
    evaluation_rating_payload,
    make_board_member_headers,
    make_board_president_headers,
    open_evaluation,
    read_board_member,
    read_evaluation,
    resign_trustee,
    seat_board,
    setup_evaluation_in_goals_set,
    submit_rating,
    superintendent_evaluation_payload,
    validate_error,
    validate_success,
)

CLERK = TEST_USERS["board_clerk_headers"]
SUPT = TEST_USERS["superintendent_headers"]

WEIGHTS = {
    "weight_instructional": 0.40,
    "weight_fiscal": 0.30,
    "weight_community": 0.20,
    "weight_governance": 0.10,
}


def test_rubric_weights_that_do_not_normalize_are_refused():
    """PRD 3.9: "Each weight is a number between 0.00 and 1.00 carried to two decimals,
    and the four must sum to exactly 1.00; a rubric that does not normalize is refused with
    `ERR_WEIGHTS_NOT_NORMALIZED`."

    Design: Corner/validations/evaluation_weights_not_summing_to_one_returns_weights_not_normalized
    """
    response = api_client.create_superintendent_evaluation(
        superintendent_evaluation_payload(
            cycle_year=2027,
            weight_instructional=0.40,
            weight_fiscal=0.30,
            weight_community=0.20,
            weight_governance=0.20,
        ),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED.value)
    assert response.status_code == 422


def test_advancing_to_midyear_with_no_ratings_is_refused():
    """PRD 3.9: "`MIDYEAR` moves `GOALS_SET → MIDYEAR_REVIEW` and requires at least one
    rating on the cycle, refusing with `ERR_NO_RATINGS_SUBMITTED` otherwise; it writes
    `midyear_formative_score`."

    Design: Corner/validations/advancing_to_midyear_with_no_ratings_returns_no_ratings_submitted
    """
    members = seat_board(1)
    evaluation = setup_evaluation_in_goals_set(members)

    response = api_client.advance_superintendent_evaluation(
        evaluation["id"], {"action": "MIDYEAR"}, make_board_president_headers(members[0]["id"])
    )
    validate_error(response, ApiErrorId.ERR_NO_RATINGS_SUBMITTED.value)
    assert response.status_code == 422

    row = read_evaluation(evaluation["id"])
    assert row["status"] == "GOALS_SET"
    assert row["midyear_formative_score"] is None
    assert row["rating_count"] == 0


def test_adopting_straight_from_planning_reports_the_stage_first():
    """PRD 3.9: "The president drives the cycle with an `action` on the ladder `SET_GOALS`,
    `MIDYEAR`, `DRAFT_SUMMATIVE`, `REOPEN` and `ADOPT`; an action that is not declared from
    the cycle's current stage is refused with `ERR_EVALUATION_STAGE_INVALID`."
    PRD 3.9: "The cycle opens in `PLANNING` with `reopen_count` 0, `rating_count` and
    `eligible_rater_count` 0, and `midyear_formative_score`, `summative_composite_score` and
    `adopted_at` all null."

    Design: Corner/validations/adopting_an_evaluation_straight_from_planning_returns_stage_invalid
    """
    members = seat_board(1)
    evaluation = open_evaluation(cycle_year=2027)

    response = api_client.advance_superintendent_evaluation(
        evaluation["id"], {"action": "ADOPT"}, make_board_president_headers(members[0]["id"])
    )
    error = validate_error(response, ApiErrorId.ERR_EVALUATION_STAGE_INVALID.value)
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_NO_RATINGS_SUBMITTED.value

    row = read_evaluation(evaluation["id"])
    assert row["status"] == "PLANNING"
    assert row["summative_composite_score"] is None


def test_a_second_score_for_the_same_domain_and_phase_is_refused():
    """PRD 3.9: "A trustee may submit only one rating per combination of cycle, `domain`
    and `phase`; a repeat is refused with `ERR_DUPLICATE_RATING`."
    PRD 3.9: "On creation `submitted_at` is stamped from the logical clock and `phase` is
    stamped from the cycle's current stage: `FORMATIVE` when the cycle is in `GOALS_SET` or
    `MIDYEAR_REVIEW`, and `SUMMATIVE` when it is in `SUMMATIVE_DRAFT`. The derived
    `counted_in_summative` flag is true exactly when the submitting trustee's `status` is
    `SEATED` and their `term_end_date` is at or after the cycle's `window_end_date`."

    Design: Corner/validations/second_rating_for_the_same_domain_and_phase_returns_duplicate_rating
    """
    members = seat_board(2)
    evaluation = setup_evaluation_in_goals_set(members)
    first = submit_rating(
        evaluation["id"],
        members[1]["id"],
        "FISCAL_STEWARDSHIP",
        4,
        comments="Steady budget management.",
    )
    assert first["phase"] == "FORMATIVE"
    assert first["score"] == 4
    assert first["counted_in_summative"] is True

    response = api_client.create_evaluation_rating(
        evaluation_rating_payload(
            evaluation["id"], members[1]["id"], domain="FISCAL_STEWARDSHIP", score=2
        ),
        make_board_member_headers(members[1]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_RATING.value)
    assert response.status_code == 409
    assert read_evaluation(evaluation["id"])["rating_count"] == 1


def test_the_superintendent_may_never_score_their_own_evaluation():
    """PRD 2.1: "The **`Superintendent`** is the chief executive the board evaluates; the
    superintendent may propose policy text and revoke granted waivers, but may never submit
    a rubric rating and may never advance their own evaluation cycle."

    Design: Corner/rbac/superintendent_cannot_submit_an_evaluation_rating_returns_forbidden_role
    """
    members = seat_board(2)
    evaluation = setup_evaluation_in_goals_set(members)

    response = api_client.create_evaluation_rating(
        evaluation_rating_payload(
            evaluation["id"], members[1]["id"], domain="INSTRUCTIONAL_LEADERSHIP", score=5
        ),
        SUPT,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403
    assert read_evaluation(evaluation["id"])["rating_count"] == 0


def test_a_trustee_may_not_file_another_trustees_rating():
    """PRD 2.1: "Concretely, a disclosure filed by a trustee must carry a
    `board_member_id` equal to `X-User-ID`; a rubric rating must carry a `board_member_id`
    equal to `X-User-ID`; and a committee recommendation is only accepted from the trustee
    whose `X-User-ID` holds a committee seat with `status` `ACTIVE` and `role_on_committee`
    `CHAIR` on the waiver's reviewing committee. Any of these mismatches — including a
    `BoardPresident` caller who is not the seated president — is rejected with
    `ERR_IDENTITY_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/trustee_cannot_submit_a_rating_for_another_trustee_returns_identity_mismatch
    """
    members = seat_board(3)
    evaluation = setup_evaluation_in_goals_set(members)

    response = api_client.create_evaluation_rating(
        evaluation_rating_payload(
            evaluation["id"], members[2]["id"], domain="INSTRUCTIONAL_LEADERSHIP", score=5
        ),
        make_board_member_headers(members[1]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_IDENTITY_MISMATCH.value)
    assert response.status_code == 403
    assert read_evaluation(evaluation["id"])["rating_count"] == 0


def _four_domain_cycle():
    """Four summative-eligible trustees scoring three of the four rubric domains."""
    members = seat_board(4)
    evaluation = setup_evaluation_in_goals_set(members, cycle_year=2027, **WEIGHTS)
    submit_rating(evaluation["id"], members[0]["id"], "INSTRUCTIONAL_LEADERSHIP", 5)
    submit_rating(evaluation["id"], members[1]["id"], "INSTRUCTIONAL_LEADERSHIP", 4)
    submit_rating(evaluation["id"], members[2]["id"], "FISCAL_STEWARDSHIP", 2)
    submit_rating(evaluation["id"], members[3]["id"], "COMMUNITY_RELATIONS", 3)
    return members, evaluation


def test_the_midyear_formative_score_is_one_pooled_unweighted_mean():
    """PRD 3.9: "The **mid-year formative** score pools every rating on the cycle whose
    `phase` is `FORMATIVE` and whose submitting trustee's `status` is `SEATED`; no
    term-expiry filter applies. It is the plain arithmetic mean of those `score` values —
    their sum divided by their count — rounded half up to two decimal places, then clamped.
    Every domain is pooled together and the four rubric weights are not used at all."

    Design: Difficulty/dual_variant_calc/superintendent_midyear_versus_summative_on_identical_ratings
    """
    members, evaluation = _four_domain_cycle()
    midyear = advance_evaluation(evaluation["id"], members[0]["id"], "MIDYEAR")

    assert midyear["midyear_formative_score"] == pytest.approx(3.50, abs=0.005)
    row = read_evaluation(evaluation["id"])
    assert row["rating_count"] == 4
    assert row["eligible_rater_count"] == 4


def test_the_summative_composite_diverges_from_the_midyear_on_the_same_ratings():
    """PRD 3.9: "For each domain that received at least one surviving rating, the mean of
    that domain's `score` values is computed and rounded half up to two decimal places. Each
    rounded domain mean is then multiplied by that domain's weight — `weight_instructional`
    for `INSTRUCTIONAL_LEADERSHIP`, `weight_fiscal` for `FISCAL_STEWARDSHIP`,
    `weight_community` for `COMMUNITY_RELATIONS`, `weight_governance` for
    `GOVERNANCE_SUPPORT` — and those products are summed. That sum is then divided by the
    sum of the weights of only the domains that were actually rated, which renormalizes the
    rubric over the domains present. The quotient is rounded half up to two decimal places
    and clamped."
    PRD 3.9: "On identical rating rows this yields a strictly different number from the
    mid-year formative score whenever the ratings are not evenly distributed across domains."

    Design: Difficulty/dual_variant_calc/superintendent_midyear_versus_summative_on_identical_ratings
    """
    members, evaluation = _four_domain_cycle()
    advance_evaluation(evaluation["id"], members[0]["id"], "MIDYEAR")
    advance_evaluation(evaluation["id"], members[0]["id"], "DRAFT_SUMMATIVE")
    adopted = advance_evaluation(evaluation["id"], members[0]["id"], "ADOPT")

    assert adopted["summative_composite_score"] == pytest.approx(3.33, abs=0.005)
    row = read_evaluation(evaluation["id"])
    assert row["midyear_formative_score"] != row["summative_composite_score"]
    assert row["status"] == "ADOPTED"


def _rounding_order_cycle():
    """Three INSTRUCTIONAL_LEADERSHIP scores of 5 / 4 / 4 and one GOVERNANCE_SUPPORT 1."""
    members = seat_board(4)
    evaluation = setup_evaluation_in_goals_set(members, cycle_year=2028, goal_count=3, **WEIGHTS)
    submit_rating(evaluation["id"], members[0]["id"], "INSTRUCTIONAL_LEADERSHIP", 5)
    submit_rating(evaluation["id"], members[1]["id"], "INSTRUCTIONAL_LEADERSHIP", 4)
    submit_rating(evaluation["id"], members[2]["id"], "INSTRUCTIONAL_LEADERSHIP", 4)
    submit_rating(evaluation["id"], members[3]["id"], "GOVERNANCE_SUPPORT", 1)
    advance_evaluation(evaluation["id"], members[0]["id"], "MIDYEAR")
    advance_evaluation(evaluation["id"], members[0]["id"], "DRAFT_SUMMATIVE")
    return members, evaluation


def test_each_domain_mean_is_rounded_before_it_is_weighted():
    """PRD 3.9: "The rounding order is pinned and must not be collapsed into a single
    rounding at the end. For each domain that received at least one surviving rating, the
    mean of that domain's `score` values is computed and rounded half up to two decimal
    places."
    PRD 2.8: "Superintendent evaluation scores are **decimal, carried to exactly 2 decimal
    places, rounded half up**, and the rounding is applied precisely where the formula below
    says and nowhere else."

    Design: Difficulty/combinatorial_formula/summative_domain_mean_rounded_before_weighting
    """
    members, evaluation = _rounding_order_cycle()
    adopted = advance_evaluation(evaluation["id"], members[0]["id"], "ADOPT")

    assert adopted["summative_composite_score"] == pytest.approx(3.66, abs=0.005)
    assert adopted["status"] == "ADOPTED"


def test_the_unrated_domains_are_renormalised_out_of_the_rubric():
    """PRD 3.9: "That sum is then divided by the sum of the weights of only the domains
    that were actually rated, which renormalizes the rubric over the domains present."
    PRD 3.9: "The **mid-year formative** score pools every rating on the cycle whose
    `phase` is `FORMATIVE` and whose submitting trustee's `status` is `SEATED`; no
    term-expiry filter applies."

    Design: Difficulty/combinatorial_formula/summative_domain_mean_rounded_before_weighting
    """
    members, evaluation = _rounding_order_cycle()
    advance_evaluation(evaluation["id"], members[0]["id"], "ADOPT")

    row = read_evaluation(evaluation["id"])
    assert row["summative_composite_score"] == pytest.approx(3.66, abs=0.005)
    assert row["midyear_formative_score"] == pytest.approx(3.50, abs=0.005)
    assert row["rating_count"] == 4


def test_a_resigned_trustee_may_no_longer_submit_a_rating():
    """PRD 3.9: "The trustee must be `SEATED`, and otherwise the submission is refused
    with `ERR_MEMBER_NOT_SEATED`."
    PRD 3.1: "Resignation is the trustee's exit door, and it is a four-hop cascade. The
    trustee's `status` moves `SEATED → RESIGNED`."

    Design: Difficulty/cross_entity_state_dependency/evaluation_rating_rejected_when_submitting_trustee_has_resigned
    """
    members = seat_board(2)
    evaluation = setup_evaluation_in_goals_set(members)
    resign_trustee(members[1]["id"])

    response = api_client.create_evaluation_rating(
        evaluation_rating_payload(
            evaluation["id"], members[1]["id"], domain="FISCAL_STEWARDSHIP", score=4
        ),
        make_board_member_headers(members[1]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MEMBER_NOT_SEATED.value)
    assert response.status_code == 409
    assert read_board_member(members[1]["id"])["status"] == "RESIGNED"


def test_the_refused_rating_leaves_the_cycle_counters_at_zero():
    """PRD 3.9: "Submitting the rating recomputes the cycle's `rating_count`, the number of
    ratings on that cycle, and its `eligible_rater_count`, the number of distinct trustees
    among those ratings whose `status` is `SEATED` and whose `term_end_date` is at or after
    `window_end_date`."
    PRD 3.9: "`SET_GOALS` moves `PLANNING → GOALS_SET`, permitted while `goal_count` is at
    least 1, after which ratings are stamped `FORMATIVE`."

    Design: Difficulty/cross_entity_state_dependency/evaluation_rating_rejected_when_submitting_trustee_has_resigned
    """
    members = seat_board(2)
    evaluation = setup_evaluation_in_goals_set(members)
    resign_trustee(members[1]["id"])
    api_client.create_evaluation_rating(
        evaluation_rating_payload(
            evaluation["id"], members[1]["id"], domain="FISCAL_STEWARDSHIP", score=4
        ),
        make_board_member_headers(members[1]["id"]),
    )

    row = read_evaluation(evaluation["id"])
    assert row["rating_count"] == 0
    assert row["status"] == "GOALS_SET"
