"""Create-then-undo pairs that must return each slate ledger to the cent and the episode."""

from prd_bench_local_runner.testing import validate_success
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.constants import (
    DEAL_TERMINATED,
    EXCLUSIVITY_FREE,
    GUILD_TIER_LOW,
    HOLDING_ACTIVE,
    HOLDING_TERMINATED,
    NEG_WITHDRAWN,
    POSTURE_OPEN,
    PRODUCTION_WRAPPED,
)
from test_helpers import fixtures as fx
from test_helpers.fixtures import build_scenario
from test_helpers.test_users import (
    agency_rep_headers,
    business_affairs_headers,
    development_exec_headers,
    finance_controller_headers,
)

OWEN_PIKE = {
    "full_name": "Owen Pike",
    "guild_minimum_tier": GUILD_TIER_LOW,
    "quote_per_step_cents": 3000000,
}
WITHDRAW_REASON = "Research would not support the licence fee"
TERMINATION_REASON = "Writer took an overall deal elsewhere"


def _slate(api, ctx):
    return validate_success(api.get_slate(ctx.slate_id, business_affairs_headers()))


def _dealt_slate_with_a_free_writer(api):
    """A slate carrying one 4375000 script deal, plus a second, unattached writer."""
    ctx = build_scenario(api, "deal")
    fx.add_second_writer(api, ctx, dict(OWEN_PIKE))
    return ctx


def test_writing_a_holding_deal_moves_only_the_reservation_bucket(api):
    """The reservation lands in reserved_holding_cents and leaves committed untouched.

    PRD 2.8: "`reserved_holding_cents` is the sum of `annual_cost_cents` over the slate's
    holding deals whose `status` is `ACTIVE`."

    Design: Difficulty/compensating_invariant/holding_deal_create_then_terminate_restores_the_slate_dollar_invariant
    """
    ctx = _dealt_slate_with_a_free_writer(api)

    before = _slate(api, ctx)
    a.assert_slate_dollar_ledger(
        before,
        committed=4375000,
        reserved=0,
        writeoff=0,
        recouped=0,
        available=395625000,
    )

    hold = fx.add_holding_deal(
        api,
        ctx,
        writer_id=ctx.writer2_id,
        annual_cost_cents=20000000,
        start_date="2026-08-01",
        end_date="2027-08-01",
    )
    assert hold["status"] == HOLDING_ACTIVE

    after = _slate(api, ctx)
    a.assert_slate_dollar_ledger(
        after,
        committed=4375000,
        reserved=20000000,
        writeoff=0,
        recouped=0,
        available=375625000,
    )
    assert after["committed_dev_cents"] == before["committed_dev_cents"], (
        "the holding deal never touches the script-deal bucket"
    )


def test_terminating_it_restores_the_dollar_ledger_without_a_cent_of_drift(api):
    """The compensating leg returns available_dev_cents to its exact pre-pair value.

    PRD 2.8: "after every single request, `available_dev_cents` plus
    `committed_dev_cents` plus `reserved_holding_cents` plus `writeoff_dev_cents`, minus
    `recouped_dev_cents`, must equal `total_dev_budget_cents` exactly, with no drift."

    Design: Difficulty/compensating_invariant/holding_deal_create_then_terminate_restores_the_slate_dollar_invariant
    """
    ctx = _dealt_slate_with_a_free_writer(api)
    before = _slate(api, ctx)

    hold = fx.add_holding_deal(
        api,
        ctx,
        writer_id=ctx.writer2_id,
        annual_cost_cents=20000000,
        start_date="2026-08-01",
        end_date="2027-08-01",
    )
    a.assert_slate_dollar_invariant(_slate(api, ctx))

    terminated = validate_success(
        api.terminate_holding_deal(
            hold["id"],
            f.terminate_holding_deal_payload(TERMINATION_REASON),
            business_affairs_headers(),
        )
    )
    assert terminated["status"] == HOLDING_TERMINATED
    assert terminated["termination_reason"] == TERMINATION_REASON

    after = _slate(api, ctx)
    a.assert_slate_dollar_ledger(
        after,
        committed=4375000,
        reserved=0,
        writeoff=0,
        recouped=0,
        available=395625000,
    )
    assert after["available_dev_cents"] == before["available_dev_cents"], (
        "the create/terminate pair introduces no drift into the slate ledger"
    )

    writer = validate_success(
        api.get_writer(ctx.writer2_id, agency_rep_headers(ctx.agency_id))
    )
    assert writer["exclusivity_status"] == EXCLUSIVITY_FREE


def test_an_open_offer_holds_episodes_in_the_reserved_bucket_alone(api):
    """The opening offer reserves ten of twenty episodes and commits none of them.

    PRD 2.8: "`reserved_episode_count` is the sum of `episode_count` over the slate's
    negotiations whose `status` is `NETWORK_OFFER` or `STUDIO_COUNTER`;
    `committed_episode_count` is the same sum over negotiations whose `status` is
    `AGREED`; a `WITHDRAWN` negotiation contributes to neither."

    Design: Difficulty/compensating_invariant/negotiation_open_then_withdrawn_restores_the_slate_episode_invariant
    """
    ctx = build_scenario(api, "negotiation")

    slate = validate_success(api.get_slate(ctx.slate_id, finance_controller_headers()))
    a.assert_slate_episode_ledger(
        slate, committed=0, reserved=10, available=10, posture=POSTURE_OPEN
    )
    assert slate["episode_capacity"] == 20


def test_abandoning_the_project_withdraws_the_offer_and_restores_every_episode(api):
    """Withdrawal is a pure release: nothing moves into committed_episode_count.

    PRD 3.9: "every negotiation of the project whose `status` is `NETWORK_OFFER` or
    `STUDIO_COUNTER` becomes `WITHDRAWN` with `withdrawn_reason` set to the same
    submitted reason, and because of that the slate's `reserved_episode_count` drops by
    those negotiations' `episode_count`".

    Design: Difficulty/compensating_invariant/negotiation_open_then_withdrawn_restores_the_slate_episode_invariant
    """
    ctx = build_scenario(api, "negotiation")

    validate_success(
        api.abandon_project(
            ctx.project_id,
            f.abandon_payload(WITHDRAW_REASON),
            development_exec_headers(),
        )
    )

    rows = validate_success(
        api.list_project_negotiations(ctx.project_id, business_affairs_headers())
    )
    negotiation = next(row for row in rows if row["id"] == ctx.negotiation_id)
    assert negotiation["status"] == NEG_WITHDRAWN
    assert negotiation["withdrawn_reason"] == WITHDRAW_REASON
    assert negotiation["agreed_at"] is None

    slate = validate_success(api.get_slate(ctx.slate_id, finance_controller_headers()))
    a.assert_slate_episode_ledger(
        slate, committed=0, reserved=0, available=20, posture=POSTURE_OPEN
    )

    # The dollar ledger moves independently in the same request: the terminated deal
    # releases its 4375000, while the wrapped pilot's spend stays committed.
    a.assert_slate_dollar_ledger(
        slate,
        committed=33000000,
        reserved=0,
        writeoff=37375000,
        recouped=0,
        available=329625000,
    )
    pilots = validate_success(
        api.list_project_pilot_orders(ctx.project_id, business_affairs_headers())
    )
    assert pilots[0]["production_status"] == PRODUCTION_WRAPPED, (
        "a WRAPPED pilot is left alone, since its money was genuinely spent"
    )
    deal = validate_success(api.get_script_deal(ctx.deal_id, business_affairs_headers()))
    assert deal["deal_status"] == DEAL_TERMINATED
    a.assert_cents(deal["encumbered_cents"], 0, "encumbered_cents")
