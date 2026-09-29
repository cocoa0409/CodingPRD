"""
State machines that revisit states they have already left.

A content item can re-enter ``IN_REVIEW`` from ``CHANGES_REQUESTED`` without
disturbing the decisions already banked on the other review dimensions, and an
asset can return to ``LICENSED`` from ``EXPIRED`` while dragging its lapsed
usage and suppressed distribution back with it.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_asset_rights,
    assert_gate,
    assert_gate_dimension_order,
    assert_list_response,
    assert_posture,
)
from test_helpers.test_users import (
    BRAND_REVIEWER,
    MANAGING_EDITOR,
    MANAGING_EDITOR_THREE,
    MANAGING_EDITOR_TWO,
    expert_headers,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
DECISION_CLOCK = "2026-08-03T20:00:00.000Z"
RESUBMIT_CLOCK = "2026-08-04T08:00:00.000Z"


def _item_sent_back_for_changes(flow):
    """
    An item whose first review lap ended in ``CHANGES_REQUESTED``.

    The brand dimension asked for changes while the subject-matter dimension
    was approved and the accessibility dimension was waived, so the second lap
    has exactly one gate to reopen.
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
    sme_gate = flow.gate_of(item["id"], "SME")
    brand_gate = flow.gate_of(item["id"], "BRAND")
    a11y_gate = flow.gate_of(item["id"], "ACCESSIBILITY")

    flow.set_clock(DECISION_CLOCK)
    flow.decide_gate(sme_gate["id"], "APPROVED", expert_headers(expert_id))
    flow.decide_gate(
        a11y_gate["id"],
        "WAIVED",
        MANAGING_EDITOR_THREE,
        decision_notes="Accessibility waived on an open campaign.",
    )
    flow.decide_gate(
        brand_gate["id"],
        "CHANGES_REQUESTED",
        BRAND_REVIEWER,
        decision_notes="Headline breaks the brand voice.",
    )
    flow.set_clock(RESUBMIT_CLOCK)
    return {
        "campaign": campaign,
        "item": item,
        "sme_gate": sme_gate,
        "brand_gate": brand_gate,
        "a11y_gate": a11y_gate,
        "expert_id": expert_id,
    }


class TestContentItemRevisionCycle:
    """``IN_REVIEW`` is reachable a second time through the same submit action."""

    def test_resubmission_reopens_only_the_changes_requested_gate(self, flow):
        """
        Resubmitting takes the item back into ``IN_REVIEW`` and reopens only the
        gate that asked for changes, with a fresh opened instant of
        2026-08-04T08:00:00.000Z, a recomputed 30-hour window and a due instant
        of 2026-08-05T14:00:00.000Z, while the approved and waived dimensions
        keep their first-lap decisions.

        Design: Difficulty/non_linear_state_machine/content_item_revision_cycle_reenters_in_review_from_changes_requested
        """
        chain = _item_sent_back_for_changes(flow)
        assert flow.read_item(chain["item"]["id"])["workflow_state"] == "CHANGES_REQUESTED"

        resubmitted = validate_success(
            flow.api.submit_for_review(chain["item"]["id"], MANAGING_EDITOR)
        )
        assert resubmitted["workflow_state"] == "IN_REVIEW"

        brand = flow.gate_of(chain["item"]["id"], "BRAND")
        assert_gate(
            brand,
            gate_type="BRAND",
            state="PENDING",
            sla_hours=30,
            opened_at=RESUBMIT_CLOCK,
            due_at="2026-08-05T14:00:00.000Z",
            sla_breached=False,
        )
        assert brand["decided_at"] is None
        assert brand["decided_by_user_id"] is None
        assert brand["turnaround_hours"] is None

        sme = flow.gate_of(chain["item"]["id"], "SME")
        assert_gate(
            sme,
            state="APPROVED",
            opened_at=SETUP_CLOCK,
            turnaround_hours=12.00,
            sla_breached=False,
        )
        assert sme["decided_at"] == DECISION_CLOCK
        accessibility = flow.gate_of(chain["item"]["id"], "ACCESSIBILITY")
        assert accessibility["state"] == "WAIVED"
        assert accessibility["decided_at"] == DECISION_CLOCK

    def test_resubmission_leaves_the_revision_number_alone(self, flow):
        """
        The revision number counts refreshes, not resubmissions, so a second lap
        through review leaves it at 1; the gate set is still the three dimensions
        opened for a claim-free item, with no legal dimension among them.

        Design: Difficulty/non_linear_state_machine/content_item_revision_cycle_reenters_in_review_from_changes_requested
        """
        chain = _item_sent_back_for_changes(flow)

        validate_success(flow.api.submit_for_review(chain["item"]["id"], MANAGING_EDITOR))

        refreshed = flow.read_item(chain["item"]["id"])
        assert refreshed["workflow_state"] == "IN_REVIEW"
        assert refreshed["revision_number"] == 1
        gates = assert_list_response(
            flow.api.list_review_gates(chain["item"]["id"], MANAGING_EDITOR),
            expected_total_count=3,
        )
        assert [gate["gate_type"] for gate in gates] == ["SME", "BRAND", "ACCESSIBILITY"]
        assert_gate_dimension_order(gates)
        assert_posture(flow.read_campaign(chain["campaign"]["id"]), "OPEN")


LICENCE_END = "2026-09-10T00:00:00.000Z"
LAPSE_CLOCK = "2026-09-11T00:00:00.000Z"


def _published_item_whose_asset_lapses(flow):
    """A published two-channel item whose only asset expires under a sweep."""
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
        name="Hero photography set A",
        asset_type="STOCK",
        license_start="2026-07-01T00:00:00.000Z",
        license_end=LICENCE_END,
        licensed_channels=["OWNED", "EMAIL"],
        max_licensed_uses=2,
    )
    usage = flow.attach_usage(item["id"], asset["id"], "OWNED")
    flow.submit(item["id"])
    flow.approve_all_gates(item["id"], expert_id)
    validate_success(
        flow.api.publish_content_item(
            item["id"],
            f.publish_payload(
                scheduled_at="2026-08-05T09:00:00.000Z",
                channels=["OWNED", "EMAIL"],
                url_slug="zero-trust-platform-pricing",
            ),
            MANAGING_EDITOR_TWO,
        )
    )
    flow.set_clock(LAPSE_CLOCK)
    flow.sweep()
    distributions = flow.distributions(item["id"])
    return {
        "campaign": campaign,
        "item": item,
        "asset": asset,
        "usage": usage,
        "owned": distributions[0],
        "email": distributions[1],
    }


class TestAssetLicenceCycle:
    """An asset returns to ``LICENSED`` and pulls its dependents back with it."""

    def test_renewal_returns_the_asset_and_its_usage_to_the_licensed_state(
        self, flow
    ):
        """
        Renewing an expired licence to 2026-12-31T00:00:00.000Z stamps the asset
        ``LICENSED`` again, revives the rights-lapsed usage to ``ACTIVE`` with its
        release instant cleared, and returns the remaining use budget to 1.

        Design: Difficulty/non_linear_state_machine/asset_license_cycle_expired_then_renewed_back_to_licensed
        """
        chain = _published_item_whose_asset_lapses(flow)
        before = flow.read_asset(chain["asset"]["id"])
        assert before["status"] == "EXPIRED"

        renewed = validate_success(
            flow.api.renew_asset(
                chain["asset"]["id"], "2026-12-31T00:00:00.000Z", MANAGING_EDITOR
            )
        )
        assert renewed["status"] == "LICENSED"
        assert renewed["license_end"] == "2026-12-31T00:00:00.000Z"
        assert_asset_rights(
            renewed, status="LICENSED", active_use_count=1, remaining_licensed_uses=1
        )

        usages = flow.usages(chain["item"]["id"])
        assert len(usages) == 1
        assert usages[0]["usage_state"] == "ACTIVE"
        assert usages[0]["released_at"] is None

    def test_renewal_restores_the_suppressed_distribution_and_clears_the_posture(
        self, flow
    ):
        """
        Before the renewal the owned distribution reads ``SUPPRESSED`` and the
        campaign is restricted by one expired usage; afterwards the distribution
        is ``LIVE`` with its suppression fields cleared, the item is still
        published and the posture is back to ``OPEN``.

        Design: Difficulty/non_linear_state_machine/asset_license_cycle_expired_then_renewed_back_to_licensed
        """
        chain = _published_item_whose_asset_lapses(flow)
        assert chain["owned"]["state"] == "SUPPRESSED"
        assert chain["email"]["state"] == "LIVE"
        assert_posture(flow.read_campaign(chain["campaign"]["id"]), "RESTRICTED")

        flow.renew_asset(chain["asset"]["id"], "2026-12-31T00:00:00.000Z")

        distributions = {row["channel"]: row for row in flow.distributions(chain["item"]["id"])}
        owned = distributions["OWNED"]
        assert owned["state"] == "LIVE"
        assert owned["suppression_reason"] is None
        assert owned["suppressed_at"] is None
        assert owned["went_live_at"] == LAPSE_CLOCK
        assert distributions["EMAIL"]["state"] == "LIVE"

        assert flow.read_item(chain["item"]["id"])["workflow_state"] == "PUBLISHED"
        campaign = flow.read_campaign(chain["campaign"]["id"])
        assert campaign["expired_usage_count"] == 0
        assert_posture(campaign, "OPEN")
