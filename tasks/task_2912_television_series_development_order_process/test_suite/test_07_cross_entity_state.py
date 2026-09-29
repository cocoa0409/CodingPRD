"""Writes whose admissibility turns on the state of a third, unrelated row."""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    COLLAPSED_REASON_CASTING,
    CONTINGENCY_CASTING,
    CONTINGENCY_FAILED,
    DEV_ACTIVE_DEVELOPMENT,
    DEV_PILOT_ORDERED,
    DEV_SCRIPT_COMPLETE,
    NEG_NETWORK_OFFER,
    POSTURE_OPEN,
    PRODUCTION_COLLAPSED,
    PRODUCTION_ORDERED,
    SCREENING_CERTIFIED,
    SCREENING_INVALIDATED,
)
from test_helpers import fixtures as fx
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    business_affairs_headers,
    development_exec_headers,
    research_analyst_headers,
)

LOW_SCORE_SCREENING = {
    "panel_size": 400,
    "overall_score": 70,
    "intent_to_view_score": 60,
    "appeal_score": 50,
    "comp_norm_index": 100.3,
}
SECOND_PILOT = {
    "budget_cents": 32500000,
    "shoot_start_date": "2026-09-12",
    "shoot_end_date": "2026-09-27",
    "casting_deadline_date": "2026-09-06",
    "location_deadline_date": "2026-09-09",
}


def _two_projects_one_stage(api):
    """One slate with a single stage window, one pilot already ORDERED on it."""
    ctx = build_scenario(api, "script_complete", slate={"max_concurrent_pilot_shoots": 1})
    ctx.pilot_order_id = fx.order_pilot(api, ctx.project_id)["id"]
    fx.second_project_through(api, ctx, "script_complete")
    return ctx


def test_a_sibling_pilot_holding_the_only_stage_blocks_the_second_order(api):
    """P2's order is refused for a reason that lives entirely on P1's pilot row.

    PRD 3.5: "Stage capacity counts how many pilot orders the slate already has whose
    `production_status` is `ORDERED` or `GREEN_TO_SHOOT`; that running count, including
    the new order, may not exceed `max_concurrent_pilot_shoots`."

    Design: Difficulty/cross_entity_state_dependency/pilot_order_refused_while_a_sibling_pilot_occupies_the_slate_stage
    """
    ctx = _two_projects_one_stage(api)

    sibling = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, development_exec_headers())
    )
    assert sibling["production_status"] == PRODUCTION_ORDERED

    before = validate_success(api.get_project(ctx.project2_id, business_affairs_headers()))
    assert before["dev_status"] == DEV_SCRIPT_COMPLETE

    refused = api.create_pilot_order(
        f.pilot_order_payload(ctx.project2_id, **SECOND_PILOT),
        development_exec_headers(),
    )
    validate_error(refused, e.ERR_STAGE_CAPACITY_EXCEEDED, 422)

    after = validate_success(api.get_project(ctx.project2_id, business_affairs_headers()))
    assert after["dev_status"] == DEV_SCRIPT_COMPLETE
    assert after["version"] == before["version"], "P2 is untouched by the refusal"
    assert (
        validate_success(
            api.list_project_pilot_orders(ctx.project2_id, business_affairs_headers())
        )
        == []
    )


def test_collapsing_the_sibling_pilot_frees_the_stage_for_the_retry(api):
    """A FAILED casting clearance vacates the stage and the identical order then succeeds.

    PRD 3.5: "The named dimension is set to `FAILED`, `production_status` becomes
    `COLLAPSED`, and `collapsed_reason` records the kind of contingency that failed - the
    string `CASTING` or `LOCATION`."

    Design: Difficulty/cross_entity_state_dependency/pilot_order_refused_while_a_sibling_pilot_occupies_the_slate_stage
    """
    ctx = _two_projects_one_stage(api)

    collapsed = validate_success(
        api.clear_contingency(
            ctx.pilot_order_id,
            f.contingency_payload(
                CONTINGENCY_CASTING, CONTINGENCY_FAILED, {"note": "Lead pulled out."}
            ),
            development_exec_headers(),
        )
    )
    assert collapsed["production_status"] == PRODUCTION_COLLAPSED
    assert collapsed["casting_status"] == CONTINGENCY_FAILED
    assert collapsed["collapsed_reason"] == COLLAPSED_REASON_CASTING

    project1 = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project1["dev_status"] == DEV_ACTIVE_DEVELOPMENT

    released = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(released, committed=8750000, available=391250000)

    ordered = validate_success(
        api.create_pilot_order(
            f.pilot_order_payload(ctx.project2_id, **SECOND_PILOT),
            development_exec_headers(),
        ),
        201,
    )
    assert ordered["production_status"] == PRODUCTION_ORDERED
    assert ordered["budget_variance_bps"] == 156

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_dollar_ledger(slate, committed=41250000, available=358750000)
    project2 = validate_success(api.get_project(ctx.project2_id, business_affairs_headers()))
    assert project2["dev_status"] == DEV_PILOT_ORDERED


def test_a_certified_screening_one_tenth_below_the_floor_blocks_the_negotiation(api):
    """61.9 is certified research and still refused, so the error names the floor.

    PRD 3.7: "The floor comparison is inclusive: a normalised score of exactly 62.0
    passes, and 61.9 does not."

    Design: Difficulty/cross_entity_state_dependency/negotiation_gated_on_the_governing_certified_screenings_score
    """
    ctx = build_scenario(api, "certified", screening=dict(LOW_SCORE_SCREENING))

    rows = validate_success(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    governing = next(row for row in rows if row["id"] == ctx.screening_id)
    assert governing["status"] == SCREENING_CERTIFIED
    a.assert_score(governing["weighted_raw_score"], 62.08, "weighted_raw_score")
    a.assert_score(governing["norm_adjusted_score"], 61.9, "norm_adjusted_score")
    a.assert_instant(governing["certified_at"], "2026-09-26T00:00:00.000Z", "certified_at")

    refused = api.create_negotiation(
        f.negotiation_payload(ctx.project_id), business_affairs_headers()
    )
    validate_error(refused, e.ERR_TEST_SCORE_BELOW_FLOOR, 422)

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(
        slate, committed=0, reserved=0, available=20, posture=POSTURE_OPEN
    )


def test_fresh_research_exactly_at_the_floor_becomes_the_governing_screening(api):
    """The newer certified screening supersedes the 61.9 one and 62.0 passes.

    PRD 3.7: "the project's most recently certified screening - the one with the highest
    `certified_at`, with ties broken by the lowest `created_at` - must have a
    `norm_adjusted_score` of at least 62.0, else `ERR_TEST_SCORE_BELOW_FLOOR`."

    Design: Difficulty/cross_entity_state_dependency/negotiation_gated_on_the_governing_certified_screenings_score
    """
    ctx = build_scenario(api, "certified", screening=dict(LOW_SCORE_SCREENING))

    fx.set_clock(api, "2026-09-27T00:00:00Z")
    pilot = validate_success(
        api.get_pilot_order(ctx.pilot_order_id, research_analyst_headers())
    )
    edge = validate_success(
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
    a.assert_score(edge["weighted_raw_score"], 62.08, "weighted_raw_score")
    a.assert_score(edge["norm_adjusted_score"], 62.0, "norm_adjusted_score")

    certified = validate_success(
        api.certify_screening(edge["id"], research_analyst_headers())
    )
    a.assert_instant(certified["certified_at"], "2026-09-27T00:00:00.000Z", "certified_at")

    rows = validate_success(
        api.list_screenings(ctx.pilot_order_id, research_analyst_headers())
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[ctx.screening_id]["status"] == SCREENING_INVALIDATED

    opening = validate_success(
        api.create_negotiation(
            f.negotiation_payload(ctx.project_id), business_affairs_headers()
        ),
        201,
    )
    assert opening["status"] == NEG_NETWORK_OFFER
    assert opening["episode_count"] == 10

    slate = validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))
    a.assert_slate_episode_ledger(
        slate, committed=0, reserved=10, available=10, posture=POSTURE_OPEN
    )
