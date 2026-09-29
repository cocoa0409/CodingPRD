"""Two-stage weighted score rounding, and the notes-round loop inside one deal step."""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    CLOCK_STARTUP_DEFAULT_STAMP,
    DEV_SCRIPT_COMPLETE,
    REVIEW_ACCEPT,
    REVIEW_NOTES,
    SCREENING_FIELDED,
    SCREENING_INVALIDATED,
    STEP_ACCEPTED,
    STEP_DELIVERED,
    STEP_FIRST_DRAFT,
    STEP_NOTES_ISSUED,
    STEP_STORY,
)
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    agency_rep_headers,
    business_affairs_headers,
    development_exec_headers,
    research_analyst_headers,
)

TWO_STEP_DEAL = {
    "steps": [f.step_spec(STEP_STORY, 3000000), f.step_spec(STEP_FIRST_DRAFT, 8000000)],
    "guaranteed_step_count": 1,
}


def _wrapped(api):
    return build_scenario(api, "wrapped", deal=dict(TWO_STEP_DEAL))


def test_each_weighted_component_is_rounded_before_the_three_are_summed(api):
    """71/64/58 against the pinned weights sums to 65.71, not the 65.70 of unrounded products.

    PRD 3.6: "Summing the three unrounded products and rounding the total afterwards
    produces a different number and is not the specified answer."

    Design: Difficulty/combinatorial_formula/test_score_rounds_each_weighted_component_before_summing
    """
    ctx = _wrapped(api)

    screening = validate_success(
        api.field_screening(
            ctx.pilot_order_id,
            f.screening_payload(
                ctx.pilot_order_version,
                panel_size=320,
                overall_score=71,
                intent_to_view_score=64,
                appeal_score=58,
                comp_norm_index=103.0,
            ),
            research_analyst_headers(),
        ),
        201,
    )
    a.assert_score(screening["weighted_raw_score"], 65.71, "weighted_raw_score")
    assert abs(float(screening["weighted_raw_score"]) - 65.70) > 0.001, (
        "65.70 is the sum-then-round answer the contract explicitly rules out"
    )
    a.assert_score(screening["norm_adjusted_score"], 63.8, "norm_adjusted_score")
    assert screening["status"] == SCREENING_FIELDED


def test_the_normalised_score_lands_exactly_on_the_floor_from_below(api):
    """70/60/50 against 100.1 gives 62.08 raw and a normalised 62.0 after 1-decimal rounding.

    PRD 3.6: "`norm_adjusted_score` follows from it: multiply `weighted_raw_score` by
    100, divide by `comp_norm_index`, and round the quotient half up to 1 decimal place."

    Design: Difficulty/combinatorial_formula/test_score_rounds_each_weighted_component_before_summing
    """
    ctx = _wrapped(api)

    first = validate_success(
        api.field_screening(
            ctx.pilot_order_id,
            f.screening_payload(ctx.pilot_order_version),
            research_analyst_headers(),
        ),
        201,
    )
    pilot = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, research_analyst_headers())
    )

    second = validate_success(
        api.field_screening(
            ctx.pilot_order_id,
            f.screening_payload(
                pilot["version"],
                panel_size=400,
                overall_score=70,
                intent_to_view_score=60,
                appeal_score=50,
                comp_norm_index=100.1,
            ),
            research_analyst_headers(),
        ),
        201,
    )
    a.assert_score(second["weighted_raw_score"], 62.08, "weighted_raw_score")
    a.assert_score(second["norm_adjusted_score"], 62.0, "norm_adjusted_score")
    assert second["status"] == SCREENING_FIELDED

    rows = validate_success(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[first["id"]]["status"] == SCREENING_INVALIDATED, (
        "fielding a fresh screening invalidates every earlier FIELDED one"
    )
    assert by_id[second["id"]]["status"] == SCREENING_FIELDED


def test_the_notes_loop_returns_the_step_to_delivered_without_recharging_the_slate(api):
    """NOTES and redelivery cycle DELIVERED -> NOTES_ISSUED -> DELIVERED twice over.

    PRD 3.4: "The pair `NOTES_ISSUED -> DELIVERED -> NOTES_ISSUED` may therefore cycle
    until that ceiling is hit."

    Design: Difficulty/non_linear_state_machine/deal_step_notes_cycle_returns_to_delivered_then_exhausts_at_two_rounds
    """
    ctx = build_scenario(api, "deal", deal=dict(TWO_STEP_DEAL))
    step_id = ctx.step1_id
    validate_success(api.exercise_step(ctx.deal_id, step_id, business_affairs_headers()))
    validate_success(api.deliver_step(ctx.deal_id, step_id, development_exec_headers()))

    def encumbered():
        deal = validate_success(api.get_script_deal(ctx.deal_id, business_affairs_headers()))
        return deal["encumbered_cents"]

    def open_steps():
        writer = validate_success(
            api.get_writer(ctx.writer_id, agency_rep_headers(ctx.agency_id))
        )
        return writer["open_step_count"]

    assert encumbered() == 4375000
    assert open_steps() == 1

    step = validate_success(
        api.review_step(
            ctx.deal_id,
            step_id,
            f.review_payload(REVIEW_NOTES, {"notes_summary": "Act two needs a real antagonist."}),
            development_exec_headers(),
        )
    )
    assert step["status"] == STEP_NOTES_ISSUED
    assert step["notes_round"] == 1

    step = validate_success(
        api.deliver_step(ctx.deal_id, step_id, development_exec_headers())
    )
    assert step["status"] == STEP_DELIVERED
    assert step["notes_round"] == 1, "redelivery leaves notes_round untouched"

    step = validate_success(
        api.review_step(
            ctx.deal_id,
            step_id,
            f.review_payload(REVIEW_NOTES, {"notes_summary": "Closer, but the ending still lands flat."}),
            development_exec_headers(),
        )
    )
    assert step["status"] == STEP_NOTES_ISSUED
    assert step["notes_round"] == 2

    step = validate_success(
        api.deliver_step(ctx.deal_id, step_id, development_exec_headers())
    )
    assert step["status"] == STEP_DELIVERED
    assert step["notes_round"] == 2

    assert encumbered() == 4375000, "looping never re-charges the slate"
    assert open_steps() == 1, "the step stayed open through every notes round"


def test_the_third_notes_round_is_refused_and_accept_is_the_escape(api):
    """At notes_round 2 a further NOTES is exhausted, while ACCEPT still closes the step.

    PRD 3.4: "because a step may carry at most two notes rounds, a third is refused
    with `ERR_NOTES_ROUNDS_EXHAUSTED` once `notes_round` has reached 2."

    Design: Difficulty/non_linear_state_machine/deal_step_notes_cycle_returns_to_delivered_then_exhausts_at_two_rounds
    """
    ctx = build_scenario(api, "deal", deal=dict(TWO_STEP_DEAL))
    step_id = ctx.step1_id
    validate_success(api.exercise_step(ctx.deal_id, step_id, business_affairs_headers()))
    for _ in range(2):
        validate_success(api.deliver_step(ctx.deal_id, step_id, development_exec_headers()))
        validate_success(
            api.review_step(
                ctx.deal_id, step_id, f.review_payload(REVIEW_NOTES), development_exec_headers()
            )
        )
    validate_success(api.deliver_step(ctx.deal_id, step_id, development_exec_headers()))

    response = api.review_step(
        ctx.deal_id,
        step_id,
        f.review_payload(REVIEW_NOTES, {"notes_summary": "One more pass."}),
        development_exec_headers(),
    )
    validate_error(response, e.ERR_NOTES_ROUNDS_EXHAUSTED, 422)

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    blocked = a.find_step(steps, 1)
    assert blocked["status"] == STEP_DELIVERED, "the refused review changed nothing"
    assert blocked["notes_round"] == 2

    accepted = validate_success(
        api.review_step(
            ctx.deal_id, step_id, f.review_payload(REVIEW_ACCEPT), development_exec_headers()
        )
    )
    assert accepted["status"] == STEP_ACCEPTED
    a.assert_instant(accepted["accepted_at"], CLOCK_STARTUP_DEFAULT_STAMP, "accepted_at")

    writer = validate_success(
        api.get_writer(ctx.writer_id, agency_rep_headers(ctx.agency_id))
    )
    assert writer["open_step_count"] == 0, "acceptance frees the writer's desk"

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_SCRIPT_COMPLETE
