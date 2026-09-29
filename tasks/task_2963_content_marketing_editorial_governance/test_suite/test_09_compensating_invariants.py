"""
The two withdrawal paths compensate to different depths.

Prune unwinds every ledger the commitment touched, while retract unwinds the
rights and the distributions but deliberately leaves the calendar commitment in
place, so the same published shape must end in two different readings.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_asset_rights,
    assert_campaign_counters,
    assert_posture,
    assert_slot_commitment,
    assert_two_decimal_value,
)
from test_helpers.test_users import MANAGING_EDITOR, MANAGING_EDITOR_TWO

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
AUDIT_CLOCK = "2026-10-05T00:00:00.000Z"

PUBLISH_PAYLOAD = f.publish_payload(
    scheduled_at=SETUP_CLOCK,
    channels=["OWNED", "EMAIL"],
    meta_description=(
        "A practical buyer guide to zero trust platform pricing for security "
        "and procurement teams."
    ),
    url_slug="zero-trust-platform-pricing",
    tags=["security", "pricing"],
)


def _published_item_holding_one_of_two_licensed_uses(flow, capacity_points):
    """
    A 16-point item published on two channels with one asset use consumed.

    The asset is licensed for both channels with two permitted uses, so the
    remaining count reads 1 while the single usage is active.
    """
    flow.set_clock(SETUP_CLOCK)
    chain = flow.committed_item(
        funnel_stage="DECISION", persona="IT_BUYER", capacity_points=capacity_points
    )
    asset = flow.create_asset(
        name="Hero photography set C",
        asset_type="STOCK",
        licensed_channels=["OWNED", "EMAIL"],
        max_licensed_uses=2,
    )
    usage = flow.attach_usage(chain["item"]["id"], asset["id"], channel="OWNED")
    flow.submit(chain["item"]["id"])
    flow.approve_all_gates(chain["item"]["id"], chain["expert_id"])
    validate_success(
        flow.api.publish_content_item(
            chain["item"]["id"], PUBLISH_PAYLOAD, MANAGING_EDITOR_TWO
        )
    )
    chain.update({"asset": asset, "usage": usage})
    return chain


def _decayed_item_eligible_for_pruning(flow):
    """
    The published item after a decay audit that returns the prune verdict.

    A 1200-session baseline period and a 100-session trailing period put the decay
    at 91.67 percent, which is at or above the prune threshold.
    """
    chain = _published_item_holding_one_of_two_licensed_uses(flow, 16)
    flow.set_clock(AUDIT_CLOCK)
    flow.snapshot(
        chain["item"]["id"],
        "2026-08-04T00:00:00.000Z",
        "2026-08-11T00:00:00.000Z",
        engaged_sessions=1200,
        conversions=24,
        influenced_opportunity_amount_cents=500000,
        touch_position="LAST",
    )
    flow.snapshot(
        chain["item"]["id"],
        "2026-09-10T00:00:00.000Z",
        "2026-09-17T00:00:00.000Z",
        engaged_sessions=100,
        conversions=2,
        influenced_opportunity_amount_cents=50000,
        touch_position="LAST",
    )
    flow.audit(chain["item"]["id"], audit_type="DECAY")
    return chain


class TestPruneCompensatesEveryLedger:
    """Prune returns the slot points and the licensed use together."""

    def test_prune_returns_the_slot_points_and_the_licensed_use(self, flow):
        """
        The slot was driven to exactly its 16-point capacity and one of the asset's
        two uses was consumed; after the prune the calendar ledger is back at its
        pre-commit reading, the usage is released at the current instant and both
        licensed uses are available again.

        Design: Difficulty/compensating_invariant/prune_returns_slot_points_and_releases_asset_uses_without_drift
        """
        chain = _decayed_item_eligible_for_pruning(flow)
        before = flow.read_item(chain["item"]["id"])
        assert before["workflow_state"] == "NEEDS_REFRESH"
        assert before["last_audit_verdict"] == "PRUNE"
        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 16, 100.00, "FULL")
        assert_asset_rights(
            flow.read_asset(chain["asset"]["id"]), remaining_licensed_uses=1
        )

        validate_success(
            flow.api.prune_content_item(chain["item"]["id"], MANAGING_EDITOR)
        )

        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 0, 0.00, "OPEN")
        campaign = flow.read_campaign(chain["campaign"]["id"])
        assert_campaign_counters(campaign, committed_points_total=0)
        assert_posture(campaign, "OPEN")
        usage = flow.usages(chain["item"]["id"])[0]
        assert usage["id"] == chain["usage"]["id"]
        assert usage["usage_state"] == "RELEASED"
        assert usage["released_at"] == AUDIT_CLOCK
        assert_asset_rights(
            flow.read_asset(chain["asset"]["id"]),
            active_use_count=0,
            remaining_licensed_uses=2,
        )

    def test_prune_preserves_the_measurement_fields_it_acted_on(self, flow):
        """
        The compensation is confined to the ledgers: the pruned item keeps the
        16-point commitment it recorded at creation and the 91.67 percent decay the
        audit measured, and every distribution is retracted.

        Design: Difficulty/compensating_invariant/prune_returns_slot_points_and_releases_asset_uses_without_drift
        """
        chain = _decayed_item_eligible_for_pruning(flow)

        pruned = validate_success(
            flow.api.prune_content_item(chain["item"]["id"], MANAGING_EDITOR)
        )

        assert pruned["workflow_state"] == "PRUNED"
        assert pruned["commit_points"] == 16
        assert_two_decimal_value(pruned["decay_pct"], 91.67)
        assert pruned["last_audit_verdict"] == "PRUNE"
        distributions = flow.distributions(chain["item"]["id"])
        assert len(distributions) == 2
        assert [row["state"] for row in distributions] == ["RETRACTED", "RETRACTED"]


class TestRetractCompensatesPartially:
    """Retract unwinds the rights but not the calendar commitment."""

    def test_retract_releases_the_asset_use_and_retracts_the_distributions(self, flow):
        """
        Retract unwinds the rights exactly as prune does: the item is retracted at
        the current instant, its usage is released, both licensed uses are available
        again and both distributions are retracted.

        Design: Difficulty/compensating_invariant/retract_releases_asset_uses_but_keeps_the_calendar_commitment
        """
        chain = _published_item_holding_one_of_two_licensed_uses(flow, 40)
        before = flow.read_item(chain["item"]["id"])
        assert before["workflow_state"] == "PUBLISHED"
        assert [row["state"] for row in flow.distributions(chain["item"]["id"])] == [
            "LIVE",
            "LIVE",
        ]
        assert all(
            row["went_live_at"] == SETUP_CLOCK
            for row in flow.distributions(chain["item"]["id"])
        )
        assert_asset_rights(
            flow.read_asset(chain["asset"]["id"]), remaining_licensed_uses=1
        )

        retracted = validate_success(
            flow.api.retract_content_item(
                chain["item"]["id"],
                MANAGING_EDITOR,
                reason="Rate card superseded, pricing table withdrawn.",
            )
        )

        assert retracted["workflow_state"] == "RETRACTED"
        assert retracted["retracted_at"] == SETUP_CLOCK
        usage = flow.usages(chain["item"]["id"])[0]
        assert usage["usage_state"] == "RELEASED"
        assert usage["released_at"] == SETUP_CLOCK
        assert_asset_rights(
            flow.read_asset(chain["asset"]["id"]),
            active_use_count=0,
            remaining_licensed_uses=2,
        )
        assert [row["state"] for row in flow.distributions(chain["item"]["id"])] == [
            "RETRACTED",
            "RETRACTED",
        ]

    def test_retract_leaves_the_calendar_commitment_standing(self, flow):
        """
        Unlike prune, retract does not give the slot points back: the 40-point slot
        still carries the item's 16 committed points at 40.00 percent, the campaign
        total still reads 16 and the item still records its commitment.

        Design: Difficulty/compensating_invariant/retract_releases_asset_uses_but_keeps_the_calendar_commitment
        """
        chain = _published_item_holding_one_of_two_licensed_uses(flow, 40)
        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 16, 40.00, "OPEN")

        retracted = validate_success(
            flow.api.retract_content_item(
                chain["item"]["id"],
                MANAGING_EDITOR,
                reason="Rate card superseded, pricing table withdrawn.",
            )
        )

        assert retracted["commit_points"] == 16
        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 16, 40.00, "OPEN")
        assert_campaign_counters(
            flow.read_campaign(chain["campaign"]["id"]), committed_points_total=16
        )
