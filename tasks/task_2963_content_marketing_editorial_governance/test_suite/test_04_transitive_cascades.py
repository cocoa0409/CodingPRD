"""
One write propagating across several entity levels.

Putting an expert on leave walks expert, brief, item, gates and campaign in a
single request, and the governance sweep walks asset, usage, distribution, item
and campaign in one pass. Both cases assert every level, including the level
that moves in the counter-intuitive direction.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_asset_rights,
    assert_campaign_counters,
    assert_list_response,
    assert_posture,
    assert_slot_commitment,
    assert_sweep_tally,
)
from test_helpers.test_users import MANAGING_EDITOR, MANAGING_EDITOR_TWO

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
BREACH_CLOCK = "2026-08-06T00:00:00.000Z"
LAPSE_CLOCK = "2026-09-11T00:00:00.000Z"


def _restricted_campaign_with_breached_gates(flow):
    """
    A campaign restricted by three breached review gates.

    The gates were opened by a submit and left undecided until the clock passed
    every due instant, so a sweep marks all three breached and the campaign is
    restricted on the breached-gate count alone.
    """
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(persona="IT_BUYER", primary_funnel_stage="DECISION")
    slot = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-03",
        funnel_stage="DECISION",
        capacity_points=40,
    )
    brief, expert_id = flow.approved_brief(campaign["id"], funnel_stage="DECISION")
    item = flow.create_item(
        brief["id"],
        slot["id"],
        campaign["id"],
        planned_publish_at="2026-08-05T09:00:00.000Z",
    )
    flow.submit(item["id"])
    flow.set_clock(BREACH_CLOCK)
    tally = flow.sweep()
    return {
        "campaign": campaign,
        "slot": slot,
        "brief": brief,
        "item": item,
        "expert_id": expert_id,
        "tally": tally,
    }


class TestExpertLeaveCascade:
    """Availability is one write that reaches five levels of dependents."""

    def test_leave_detaches_the_brief_and_resets_the_item_and_its_gates(self, flow):
        """
        Putting the expert on leave zeroes the committed hours, walks the brief
        back to ``DRAFT`` with its expert cleared, pulls the item out of review
        into ``CHANGES_REQUESTED``, and voids every pending gate with its decision
        fields cleared and its breach flag reset.

        Design: Difficulty/transitive_cascade/expert_leave_cascades_brief_item_gates_and_campaign_posture
        """
        chain = _restricted_campaign_with_breached_gates(flow)

        expert = validate_success(
            flow.api.set_expert_availability(
                chain["expert_id"], "ON_LEAVE", MANAGING_EDITOR
            )
        )
        assert expert["status"] == "ON_LEAVE"
        assert expert["committed_hours_total"] == 0

        brief = flow.read_brief(chain["brief"]["id"])
        assert brief["state"] == "DRAFT"
        assert brief["sme_expert_id"] is None
        assert flow.read_item(chain["item"]["id"])["workflow_state"] == "CHANGES_REQUESTED"

        gates = flow.gates(chain["item"]["id"])
        assert len(gates) == 3
        for gate in gates:
            assert gate["state"] == "VOIDED"
            assert gate["sla_breached"] is False
            assert gate["decided_at"] is None

    def test_voiding_the_breached_gates_moves_the_posture_back_down_to_open(
        self, flow
    ):
        """
        The campaign was restricted by three breached gates; voiding those same
        gates removes the rows the posture was derived from, so the fifth level of
        the cascade moves down to ``OPEN`` while the calendar commitment behind the
        item is left untouched at 16 points and 40.00 percent.

        Design: Difficulty/transitive_cascade/expert_leave_cascades_brief_item_gates_and_campaign_posture
        """
        chain = _restricted_campaign_with_breached_gates(flow)
        assert_sweep_tally(chain["tally"], gates_breached=3, campaigns_restricted=1)
        before = flow.read_campaign(chain["campaign"]["id"])
        assert before["breached_gate_count"] == 3
        assert_posture(before, "RESTRICTED")
        for gate in flow.gates(chain["item"]["id"]):
            assert gate["state"] == "PENDING"
            assert gate["sla_breached"] is True

        flow.set_availability(chain["expert_id"], "ON_LEAVE")

        after = flow.read_campaign(chain["campaign"]["id"])
        assert_campaign_counters(after, breached_gate_count=0)
        assert_posture(after, "OPEN")
        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 16, 40.00)


def _published_item_on_a_talent_licence_about_to_lapse(flow):
    """A published single-channel item whose talent licence ends before the clock."""
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(persona="IT_BUYER", primary_funnel_stage="DECISION")
    slot = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-03",
        funnel_stage="DECISION",
        capacity_points=40,
    )
    brief, expert_id = flow.approved_brief(campaign["id"], funnel_stage="DECISION")
    item = flow.create_item(
        brief["id"],
        slot["id"],
        campaign["id"],
        planned_publish_at="2026-08-05T09:00:00.000Z",
    )
    asset = flow.create_asset(
        name="Spokesperson session with A. Reyes",
        asset_type="TALENT",
        license_start="2026-07-01T00:00:00.000Z",
        license_end="2026-09-10T00:00:00.000Z",
        licensed_channels=["OWNED"],
        max_licensed_uses=1,
    )
    usage = flow.attach_usage(item["id"], asset["id"], "OWNED")
    flow.submit(item["id"])
    flow.approve_all_gates(item["id"], expert_id)
    validate_success(
        flow.api.publish_content_item(
            item["id"],
            f.publish_payload(
                scheduled_at="2026-08-05T09:00:00.000Z",
                channels=["OWNED"],
                url_slug="zero-trust-platform-pricing",
            ),
            MANAGING_EDITOR_TWO,
        )
    )
    distributions = flow.distributions(item["id"])
    flow.set_clock(LAPSE_CLOCK)
    return {
        "campaign": campaign,
        "slot": slot,
        "item": item,
        "asset": asset,
        "usage": usage,
        "distribution": distributions[0],
    }


class TestSweepAssetExpiryCascade:
    """The sweep's counters and rows expose one ordered five-level walk."""

    def test_the_counters_show_suppression_running_before_activation(self, flow):
        """
        The owned distribution was scheduled for an instant already in the past,
        yet the sweep reports one suppression and no activation, because rights
        suppression runs earlier in the pass than scheduled activation; expiry,
        lapse, refresh flagging and restriction each report exactly one row.

        Design: Difficulty/transitive_cascade/sweep_asset_expiry_cascades_usage_distribution_item_and_posture
        """
        chain = _published_item_on_a_talent_licence_about_to_lapse(flow)
        assert chain["distribution"]["state"] == "SCHEDULED"

        tally = validate_success(flow.api.run_governance_sweep(MANAGING_EDITOR))

        assert_sweep_tally(
            tally,
            assets_expired=1,
            usages_lapsed=1,
            distributions_suppressed=1,
            items_flagged_refresh=1,
            campaigns_restricted=1,
        )
        assert tally["distributions_activated"] == 0
        assert tally["campaigns_frozen"] == 0

    def test_the_pass_walks_asset_usage_distribution_item_and_campaign(self, flow):
        """
        One sweep with no request body expires the asset, lapses its usage,
        suppresses the distribution with the rights-lapse reason, flags the
        published item as needing a refresh, and restricts the campaign on its
        single expired usage, all without touching the calendar commitment.

        Design: Difficulty/transitive_cascade/sweep_asset_expiry_cascades_usage_distribution_item_and_posture
        """
        chain = _published_item_on_a_talent_licence_about_to_lapse(flow)

        flow.sweep()

        assert_asset_rights(
            flow.read_asset(chain["asset"]["id"]),
            status="EXPIRED",
            active_use_count=0,
            remaining_licensed_uses=1,
        )
        usages = flow.usages(chain["item"]["id"])
        assert usages[0]["usage_state"] == "RIGHTS_LAPSED"

        rows = assert_list_response(
            flow.api.list_distributions(chain["item"]["id"], MANAGING_EDITOR),
            expected_total_count=1,
        )
        assert rows[0]["state"] == "SUPPRESSED"
        assert rows[0]["suppression_reason"] == "ASSET_RIGHTS_LAPSED"
        assert rows[0]["suppressed_at"] == LAPSE_CLOCK
        assert rows[0]["went_live_at"] is None

        assert flow.read_item(chain["item"]["id"])["workflow_state"] == "NEEDS_REFRESH"
        campaign = flow.read_campaign(chain["campaign"]["id"])
        assert campaign["expired_usage_count"] == 1
        assert_posture(campaign, "RESTRICTED")
        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 16, 40.00)
