"""The two four-level cascades: abandonment's write-off, and the greenlight join."""

from prd_bench_local_runner.testing import validate_success
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    CLOCK_STARTUP_DEFAULT_STAMP,
    COLLAPSED_REASON_PROJECT_ABANDONED,
    COMMITTEE_FINANCE,
    DEAL_COMPLETED,
    DEAL_TERMINATED,
    DECISION_APPROVED,
    DEV_ABANDONED,
    DEV_SERIES_ORDERED,
    FEASIBILITY_BASIS_PATTERN,
    GL_APPROVED,
    POSTURE_OPEN,
    PRODUCTION_COLLAPSED,
    STEP_ACCEPTED,
    STEP_CUT_OFF,
    STEP_FIRST_DRAFT,
    STEP_REVISION,
    STEP_STORY,
    TURNAROUND_NONE,
    VERDICT_FEASIBLE,
)
from test_helpers import fixtures as fx
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    USER_BA_2,
    USER_EXEC,
    USER_FIN_1,
    business_affairs_headers,
    development_exec_headers,
    finance_controller_headers,
)

TWO_STEP_DEAL = {
    "steps": [f.step_spec(STEP_STORY, 3000000), f.step_spec(STEP_FIRST_DRAFT, 8000000)],
    "guaranteed_step_count": 1,
}
ABANDON_REASON = "Showrunner attached elsewhere"


def _slate(api, ctx):
    return validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))


def _deal(api, deal_id):
    return validate_success(api.get_script_deal(deal_id, business_affairs_headers()))


def test_abandonment_tears_down_four_levels_including_an_accepted_step(api):
    """The terminated deal cuts off its ACCEPTED step and the ORDERED pilot collapses.

    PRD 3.9: "every step of each terminated deal that is not already `CUT_OFF` becomes
    `CUT_OFF` - `ACCEPTED` steps included, which is the sharpest difference between this
    cascade and the series-order cascade of 3.8."

    Design: Difficulty/transitive_cascade/abandonment_cascade_four_levels_into_slate_writeoff_ledger
    """
    ctx = build_scenario(api, "pilot_ordered", deal=dict(TWO_STEP_DEAL))

    project = validate_success(
        api.abandon_project(
            ctx.project_id, f.abandon_payload(ABANDON_REASON), development_exec_headers()
        )
    )
    assert project["dev_status"] == DEV_ABANDONED
    a.assert_cents(project["writeoff_cents"], 37375000, "writeoff_cents")
    a.assert_instant(project["abandoned_at"], CLOCK_STARTUP_DEFAULT_STAMP, "abandoned_at")
    assert project["abandon_reason"] == ABANDON_REASON
    assert project["turnaround_status"] == TURNAROUND_NONE

    deal = _deal(api, ctx.deal_id)
    assert deal["deal_status"] == DEAL_TERMINATED
    a.assert_cents(deal["encumbered_cents"], 0, "encumbered_cents")
    a.assert_cents(
        deal["guaranteed_commitment_cents"], 4375000, "guaranteed_commitment_cents"
    )
    a.assert_cents(
        deal["full_option_exposure_cents"], 12375000, "full_option_exposure_cents"
    )

    steps = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    assert a.find_step(steps, 1)["status"] == STEP_CUT_OFF, (
        "the accepted guaranteed step is cut off by an abandonment"
    )
    assert a.find_step(steps, 2)["status"] == STEP_CUT_OFF

    pilots = validate_success(
        api.list_project_pilot_orders(ctx.project_id, business_affairs_headers())
    )
    pilot = next(row for row in pilots if row["id"] == ctx.pilot_order_id)
    assert pilot["production_status"] == PRODUCTION_COLLAPSED
    assert pilot["collapsed_reason"] == COLLAPSED_REASON_PROJECT_ABANDONED


def test_the_write_off_holds_the_released_cents_out_of_the_slate(api):
    """committed falls to zero, writeoff takes the whole 37375000 and available never moves.

    PRD 3.9: "Finally the slate's `writeoff_dev_cents` rises by the project's
    `writeoff_cents`, holding those spent development dollars out of
    `available_dev_cents` permanently."

    Design: Difficulty/transitive_cascade/abandonment_cascade_four_levels_into_slate_writeoff_ledger
    """
    ctx = build_scenario(api, "pilot_ordered", deal=dict(TWO_STEP_DEAL))

    before = _slate(api, ctx)
    a.assert_slate_dollar_ledger(
        before, committed=37375000, writeoff=0, recouped=0, available=362625000
    )

    validate_success(
        api.abandon_project(
            ctx.project_id, f.abandon_payload(ABANDON_REASON), development_exec_headers()
        )
    )

    after = _slate(api, ctx)
    a.assert_slate_dollar_ledger(
        after,
        committed=0,
        reserved=0,
        writeoff=37375000,
        recouped=0,
        available=362625000,
    )
    assert after["available_dev_cents"] == before["available_dev_cents"], (
        "the write-off keeps the money spent, so available_dev_cents is unchanged"
    )
    assert after["posture"] == POSTURE_OPEN

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    a.assert_cents(project["cumulative_dev_cost_cents"], 0, "cumulative_dev_cost_cents")
    a.assert_cents(project["writeoff_cents"], 37375000, "writeoff_cents")


def _two_deal_greenlight(api):
    """A PILOT_DELIVERED project with one ACCEPTED deal and one still-PENDING deal."""
    ctx = build_scenario(api, "script_complete")
    deal_b = fx.execute_script_deal(
        api,
        ctx.project_id,
        ctx.writer_id,
        steps=[f.step_spec(STEP_REVISION, 2000000)],
        guaranteed_step_count=1,
    )
    ctx.deal2_id = deal_b["id"]
    ctx.extra["stepB_id"] = fx.deal_step_ids(api, ctx.deal2_id)[0]

    ctx.pilot_order_id = fx.order_pilot(api, ctx.project_id)["id"]
    fx.greenlight_the_shoot(api, ctx.pilot_order_id)
    ctx.pilot_order_version = fx.wrap_pilot(api, ctx.pilot_order_id)["version"]
    ctx.screening_id = fx.field_screening(
        api, ctx.pilot_order_id, ctx.pilot_order_version
    )["id"]
    fx.certify_screening(api, ctx.screening_id)
    ctx.negotiation_id = fx.open_negotiation(api, ctx.project_id)["id"]
    fx.accept_negotiation_as_studio(api, ctx.negotiation_id)
    ctx.project_version = fx.project_version(api, ctx.project_id)
    ctx.greenlight_id = fx.file_greenlight_request(
        api, ctx.project_id, ctx.negotiation_id, ctx.project_version
    )["id"]
    fx.record_creative_decision(api, ctx.greenlight_id, user_id=USER_EXEC)
    fx.record_business_decision(api, ctx.greenlight_id, user_id=USER_BA_2)
    return ctx


def test_the_third_approval_re_runs_feasibility_then_orders_the_series(api):
    """FINANCE approves only because the PATTERN re-check at ten episodes comes back FEASIBLE.

    PRD 3.8: "One further gate applies to a `FINANCE` vote of `APPROVED` only: the
    server re-evaluates the feasibility computation on the `PATTERN` basis at the
    `episode_count` of the negotiation attached to the request, and refuses the approval
    with `ERR_FEASIBILITY_FAILED` when the verdict comes back `INFEASIBLE`."

    Design: Difficulty/transitive_cascade/greenlight_approval_cascade_four_levels_releases_pending_step_money
    """
    ctx = _two_deal_greenlight(api)

    projection = validate_success(
        api.get_feasibility(
            ctx.project_id,
            finance_controller_headers(),
            {"basis": FEASIBILITY_BASIS_PATTERN, "episode_count": 10},
        )
    )
    a.assert_feasibility(
        projection,
        per_episode_cost_cents=36050000,
        tier_factor_bps=9000,
        license_fee_final_cents=30000000,
        deficit_per_episode_cents=6050000,
        verdict=VERDICT_FEASIBLE,
    )

    decided = validate_success(
        api.record_decision(
            ctx.greenlight_id,
            f.decision_payload(COMMITTEE_FINANCE, DECISION_APPROVED),
            finance_controller_headers(USER_FIN_1),
        )
    )
    assert decided["status"] == GL_APPROVED
    a.assert_instant(decided["decided_at"], "2026-09-26T00:00:00.000Z", "decided_at")

    request = validate_success(
        api.get_greenlight_request(ctx.greenlight_id, business_affairs_headers())
    )
    assert request["creative_decision"] == DECISION_APPROVED
    assert request["business_decision"] == DECISION_APPROVED
    assert request["finance_decision"] == DECISION_APPROVED
    deciders = {
        request["creative_decided_by_user_id"],
        request["business_decided_by_user_id"],
        request["finance_decided_by_user_id"],
    }
    assert len(deciders) == 3, f"three distinct deciders are required, got {deciders}"

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    assert project["dev_status"] == DEV_SERIES_ORDERED


def test_the_series_order_releases_only_the_pending_step_money(api):
    """Both deals complete, the PENDING step is cut off and the ACCEPTED step stays encumbered.

    PRD 3.8: "it cuts off only `PENDING` steps and leaves `ACCEPTED`, `EXERCISED`,
    `DELIVERED` and `NOTES_ISSUED` work encumbered, because that writing was done and
    the network owes for it."

    Design: Difficulty/transitive_cascade/greenlight_approval_cascade_four_levels_releases_pending_step_money
    """
    ctx = _two_deal_greenlight(api)

    before = _slate(api, ctx)
    a.assert_slate_dollar_ledger(
        before, committed=40500000, writeoff=0, available=359500000
    )

    validate_success(
        api.record_decision(
            ctx.greenlight_id,
            f.decision_payload(COMMITTEE_FINANCE, DECISION_APPROVED),
            finance_controller_headers(USER_FIN_1),
        )
    )

    deal_a = _deal(api, ctx.deal_id)
    deal_b = _deal(api, ctx.deal2_id)
    assert deal_a["deal_status"] == DEAL_COMPLETED
    assert deal_b["deal_status"] == DEAL_COMPLETED
    a.assert_cents(deal_a["encumbered_cents"], 4375000, "deal A encumbered_cents")
    a.assert_cents(deal_b["encumbered_cents"], 0, "deal B encumbered_cents")

    steps_a = validate_success(api.list_deal_steps(ctx.deal_id, business_affairs_headers()))
    steps_b = validate_success(api.list_deal_steps(ctx.deal2_id, business_affairs_headers()))
    assert a.find_step(steps_a, 1)["status"] == STEP_ACCEPTED
    assert a.find_step(steps_b, 1)["status"] == STEP_CUT_OFF

    after = _slate(api, ctx)
    a.assert_slate_dollar_ledger(
        after, committed=37375000, writeoff=0, recouped=0, available=362625000
    )
    assert before["committed_dev_cents"] - after["committed_dev_cents"] == 3125000, (
        "exactly the cut-off REVISION step's effective fee is released"
    )

    project = validate_success(api.get_project(ctx.project_id, business_affairs_headers()))
    a.assert_cents(
        project["cumulative_dev_cost_cents"], 37375000, "cumulative_dev_cost_cents"
    )
