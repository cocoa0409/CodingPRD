"""Stretch-goal unlock cascade and threshold boundary precision."""
from test_helpers import (
    TEST_USERS,
    charge_pledge,
    create_pledge,
    get_campaign,
    setup_live_campaign,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _campaign_with_goal(threshold_cents, goal_cents=100_000):
    return setup_live_campaign(
        goal_cents=goal_cents,
        closes_at="2026-09-30T00:00:00Z",
        pledge_levels=[
            {
                "name": "L",
                "price_cents": 5000,
                "contents": ["base"],
                "quantity_cap": None,
                "late_pledge_premium_pct": 0.0,
                "status": "OPEN",
            }
        ],
        stretch_goals=[
            {
                "goal_id": "sg-1",
                "threshold_cents": threshold_cents,
                "target_pledge_level_name": "L",
                "bonus_component_sku": "mini-expansion",
            }
        ],
    )


class TestStretchGoalBoundary:
    def test_stretch_goal_locked_below_threshold(self, api):
        """PRD §3.2: "A goal whose threshold is less than or equal to the
        campaign's current `gross_charged_cents` unlocks".

        At gross 5,000c with threshold 10,000c the goal stays LOCKED.

        Design: Difficulty/boundary_precision_check/stretch_goal_threshold_uses_gte
        """
        campaign = _campaign_with_goal(threshold_cents=10_000)
        p1 = create_pledge(campaign["id"], backer_user_id="b1", backer_email="b1@x")
        charge_pledge(p1["id"])
        data = get_campaign(campaign["id"])
        assert data["stretch_goals"][0]["status"] == "LOCKED"

    def test_stretch_goal_unlocks_at_exact_threshold(self, api):
        """PRD §3.2: "A goal whose threshold is less than or equal to the
        campaign's current `gross_charged_cents` unlocks: its `status`
        becomes `UNLOCKED`".

        Two 5,000c charges reach exactly 10,000c — the >= boundary fires.

        Design: Difficulty/boundary_precision_check/stretch_goal_threshold_uses_gte
        """
        campaign = _campaign_with_goal(threshold_cents=10_000)
        p1 = create_pledge(campaign["id"], backer_user_id="b1", backer_email="b1@x")
        charge_pledge(p1["id"])
        p2 = create_pledge(campaign["id"], backer_user_id="b2", backer_email="b2@x")
        charge_pledge(p2["id"])
        data = get_campaign(campaign["id"])
        assert data["stretch_goals"][0]["status"] == "UNLOCKED"


class TestStretchGoalCascade:
    def test_charge_triggers_unlock_then_level_contents_mutation(self, api):
        """PRD §3.2: "its `bonus_component_sku` is appended to the `contents`
        of the pledge level named by `target_pledge_level_name`, deduplicated
        so a SKU already present is not added twice."

        Design: Difficulty/transitive_cascade/charge_triggers_stretch_unlock_then_level_contents_then_sibling_repricing
        """
        campaign = _campaign_with_goal(threshold_cents=15_000)
        p1 = create_pledge(campaign["id"], backer_user_id="b1", backer_email="b1@x")
        charge_pledge(p1["id"])
        p2 = create_pledge(campaign["id"], backer_user_id="b2", backer_email="b2@x")
        charge_pledge(p2["id"])
        before = get_campaign(campaign["id"])
        assert before["stretch_goals"][0]["status"] == "LOCKED"

        p3 = create_pledge(campaign["id"], backer_user_id="b3", backer_email="b3@x")
        charge_pledge(p3["id"])
        after = get_campaign(campaign["id"])
        assert after["stretch_goals"][0]["status"] == "UNLOCKED"
        assert "mini-expansion" in after["pledge_levels"][0]["contents"]

    def test_stretch_goal_unlock_unlocked_at_set(self, api):
        """PRD §3.2: "its `status` becomes `UNLOCKED`, its `unlocked_at` is
        set to the current logical clock".

        Design: Difficulty/transitive_cascade/charge_triggers_stretch_unlock_then_level_contents_then_sibling_repricing
        """
        campaign = _campaign_with_goal(threshold_cents=10_000)
        p1 = create_pledge(campaign["id"], backer_user_id="b1", backer_email="b1@x")
        charge_pledge(p1["id"])
        p2 = create_pledge(campaign["id"], backer_user_id="b2", backer_email="b2@x")
        charge_pledge(p2["id"])
        goal = get_campaign(campaign["id"])["stretch_goals"][0]
        assert goal["status"] == "UNLOCKED"
        assert goal["unlocked_at"] is not None
