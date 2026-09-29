"""
Formulas whose declared step order is externally observable.

The commitment arithmetic on a calendar slot fixes the capacity tier from the
utilization *before* the new commitment is applied, and the assisted pipeline
fold rounds every measurement period to whole cents *before* the periods are
summed. Both orderings change the answer, so both are asserted here.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_campaign_counters,
    assert_slot_commitment,
)
from test_helpers.test_users import MANAGING_EDITOR

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
MEASUREMENT_CLOCK = "2026-09-14T00:00:00.000Z"


def _slot_loaded_to_thirty_of_forty(flow):
    """An active campaign whose 40-point slot already carries a 30-point item."""
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(persona="IT_BUYER", primary_funnel_stage="DECISION")
    slot = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-03",
        funnel_stage="DECISION",
        capacity_points=40,
    )
    filler_brief, _filler_expert = flow.approved_brief(
        campaign["id"], funnel_stage="DECISION", effort_points=30
    )
    target_brief, _target_expert = flow.approved_brief(
        campaign["id"], funnel_stage="DECISION", effort_points=9
    )
    filler_item = flow.create_item(
        filler_brief["id"],
        slot["id"],
        campaign["id"],
        planned_publish_at="2026-08-05T09:00:00.000Z",
    )
    return {
        "campaign": campaign,
        "slot": slot,
        "target_brief": target_brief,
        "filler_item": filler_item,
    }


class TestCommitmentTierOrdering:
    """The tier is read off the pre-commit utilization, never the post-commit one."""

    def test_tier_and_surcharge_come_from_the_utilization_before_the_commit(
        self, flow
    ):
        """
        The slot stands at 30 of 40 points, so the incoming 9-point brief sees a
        pre-commit utilization of 75.00 percent, lands in the ``MEDIUM`` tier and
        picks up a surcharge of 1 for a commitment of 10 points; deriving the
        tier from the post-commit 97.50 percent would make it ``HIGH``.

        Design: Difficulty/combinatorial_formula/slot_commit_tier_pinned_to_pre_commit_utilization
        """
        chain = _slot_loaded_to_thirty_of_forty(flow)
        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 30, 75.00, "OPEN")

        target = flow.create_item(
            chain["target_brief"]["id"],
            chain["slot"]["id"],
            chain["campaign"]["id"],
            planned_publish_at="2026-08-06T09:00:00.000Z",
        )

        assert target["effort_points"] == 9
        assert target["capacity_tier_at_commit"] == "MEDIUM"
        assert target["capacity_tier_at_commit"] != "HIGH"
        assert target["commit_points"] == 10

    def test_the_pre_commit_tier_lets_the_projection_land_exactly_on_capacity(
        self, flow
    ):
        """
        With the surcharge fixed at 1, the projected total is 40 against a
        capacity of 40, so the commitment is accepted and the slot closes to
        ``FULL`` at 100.00 percent; a surcharge of 3 would project 42 and the
        same request would have been refused.

        Design: Difficulty/combinatorial_formula/slot_commit_tier_pinned_to_pre_commit_utilization
        """
        chain = _slot_loaded_to_thirty_of_forty(flow)
        assert chain["filler_item"]["capacity_tier_at_commit"] == "LOW"
        assert chain["filler_item"]["commit_points"] == 30

        response = flow.api.create_content_item(
            {
                "brief_id": chain["target_brief"]["id"],
                "slot_id": chain["slot"]["id"],
                "expected_campaign_version": flow.campaign_version(
                    chain["campaign"]["id"]
                ),
                "title": "Platform sign-in help centre entry",
                "planned_publish_at": "2026-08-06T09:00:00.000Z",
            },
            MANAGING_EDITOR,
        )
        validate_success(response, 201)

        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 40, 100.00, "FULL")
        assert_campaign_counters(
            flow.read_campaign(chain["campaign"]["id"]), committed_points_total=40
        )


MIDDLE_PERIODS = [
    {
        "period_start": "2026-08-03T00:00:00.000Z",
        "period_end": "2026-08-10T00:00:00.000Z",
        "engaged_sessions": 100,
        "conversions": 1,
        "influenced_opportunity_amount_cents": 12343,
        "touch_position": "MIDDLE",
    },
    {
        "period_start": "2026-08-10T00:00:00.000Z",
        "period_end": "2026-08-17T00:00:00.000Z",
        "engaged_sessions": 100,
        "conversions": 1,
        "influenced_opportunity_amount_cents": 12343,
        "touch_position": "MIDDLE",
    },
    {
        "period_start": "2026-08-17T00:00:00.000Z",
        "period_end": "2026-08-24T00:00:00.000Z",
        "engaged_sessions": 100,
        "conversions": 1,
        "influenced_opportunity_amount_cents": 12343,
        "touch_position": "MIDDLE",
    },
    {
        "period_start": "2026-08-24T00:00:00.000Z",
        "period_end": "2026-08-31T00:00:00.000Z",
        "engaged_sessions": 100,
        "conversions": 1,
        "influenced_opportunity_amount_cents": 12343,
        "touch_position": "MIDDLE",
    },
]


def _item_ready_for_measurement(flow):
    """A DRAFT item and a clock parked past every measurement period."""
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(persona="IT_BUYER", primary_funnel_stage="DECISION")
    slot = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-03",
        funnel_stage="DECISION",
        capacity_points=40,
    )
    brief, _expert_id = flow.approved_brief(campaign["id"], funnel_stage="DECISION")
    item = flow.create_item(
        brief["id"],
        slot["id"],
        campaign["id"],
        planned_publish_at="2026-08-05T09:00:00.000Z",
    )
    flow.set_clock(MEASUREMENT_CLOCK)
    return item


class TestAssistedFoldRounding:
    """Each period's weighted share is rounded before the periods are summed."""

    def test_four_equal_middle_periods_sum_to_the_per_period_rounded_total(
        self, flow
    ):
        """
        Four middle periods of 12343 cents weight to 2468.6 cents apiece; rounding
        each share to whole cents first gives 2469 four times over for a total of
        9876, where rounding the 9874.4 fold once would give 9874.

        Design: Difficulty/combinatorial_formula/assisted_attribution_rounds_each_snapshot_before_summing
        """
        item = _item_ready_for_measurement(flow)
        for period in MIDDLE_PERIODS:
            flow.snapshot(item["id"], **period)

        refreshed = flow.read_item(item["id"])
        assert refreshed["assisted_pipeline_cents"] == 9876
        assert refreshed["assisted_pipeline_cents"] != 9874
        assert refreshed["engaged_sessions_total"] == 400
        assert refreshed["conversions_total"] == 4

    def test_each_added_middle_period_moves_the_total_by_its_own_rounded_share(
        self, flow
    ):
        """
        Three of those periods already read 7407, so the fourth adds exactly 2469
        rather than 2468; with no last-position period on the item the last-touch
        figure stays at 0 throughout.

        Design: Difficulty/combinatorial_formula/assisted_attribution_rounds_each_snapshot_before_summing
        """
        item = _item_ready_for_measurement(flow)
        for period in MIDDLE_PERIODS[:3]:
            flow.snapshot(item["id"], **period)

        after_three = flow.read_item(item["id"])
        assert after_three["assisted_pipeline_cents"] == 7407
        assert after_three["last_touch_pipeline_cents"] == 0

        flow.snapshot(item["id"], **MIDDLE_PERIODS[3])
        after_four = flow.read_item(item["id"])
        assert (
            after_four["assisted_pipeline_cents"]
            - after_three["assisted_pipeline_cents"]
        ) == 2469
        assert after_four["assisted_pipeline_cents"] == 9876
        assert after_four["last_touch_pipeline_cents"] == 0
