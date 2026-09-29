"""
Comparisons pinned at their exact boundary.

The capacity tier boundary is inclusive, so a slot sitting on exactly the high
threshold behaves differently from one a single point below it, and an empty
baseline measurement window short-circuits the decay calculation instead of
dividing by zero.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_SLOT_CAPACITY_EXCEEDED
from test_helpers.assertions import (
    assert_campaign_counters,
    assert_list_response,
    assert_slot_commitment,
    assert_two_decimal_value,
)
from test_helpers.test_users import MANAGING_EDITOR, MANAGING_EDITOR_TWO

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
AUDIT_CLOCK = "2026-10-05T00:00:00.000Z"


def _two_slots_either_side_of_the_high_threshold(flow):
    """
    Two 40-point slots, one loaded to exactly 32 points and one to 31.

    Both carry an identical six-point brief waiting to be committed, so the only
    difference between the two commitments is the utilization they meet.
    """
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(
        persona="IT_BUYER", primary_funnel_stage="AWARENESS"
    )
    slot_a = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-03",
        funnel_stage="AWARENESS",
        capacity_points=40,
    )
    slot_b = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-10",
        funnel_stage="AWARENESS",
        capacity_points=40,
    )
    filler_a, _ea = flow.approved_brief(
        campaign["id"], funnel_stage="AWARENESS", effort_points=32
    )
    filler_b, _eb = flow.approved_brief(
        campaign["id"], funnel_stage="AWARENESS", effort_points=31
    )
    target_a, _ta = flow.approved_brief(
        campaign["id"], funnel_stage="AWARENESS", effort_points=6
    )
    target_b, _tb = flow.approved_brief(
        campaign["id"], funnel_stage="AWARENESS", effort_points=6
    )
    item_a = flow.create_item(
        filler_a["id"],
        slot_a["id"],
        campaign["id"],
        planned_publish_at="2026-08-05T09:00:00.000Z",
    )
    item_b = flow.create_item(
        filler_b["id"],
        slot_b["id"],
        campaign["id"],
        planned_publish_at="2026-08-12T09:00:00.000Z",
    )
    return {
        "campaign": campaign,
        "slot_a": slot_a,
        "slot_b": slot_b,
        "target_a": target_a,
        "target_b": target_b,
        "filler_item_a": item_a,
        "filler_item_b": item_b,
    }


class TestCapacityTierBoundary:
    """The high tier is entered at the threshold, not one point past it."""

    def test_a_slot_at_exactly_eighty_percent_takes_the_high_surcharge(self, flow):
        """
        Slot A stands at 32 of 40 points, exactly 80.00 percent, so the incoming
        six-point brief takes the high surcharge of 3 and projects 41 against a
        capacity of 40; the commitment is refused and the slot is left untouched
        at 32 points and ``OPEN``.

        Design: Difficulty/boundary_precision_check/slot_utilization_exactly_eighty_percent_selects_high_surcharge
        """
        chain = _two_slots_either_side_of_the_high_threshold(flow)
        assert_slot_commitment(flow.read_slot(chain["slot_a"]["id"]), 32, 80.00, "OPEN")
        assert chain["filler_item_a"]["commit_points"] == 32
        assert chain["filler_item_a"]["capacity_tier_at_commit"] == "LOW"

        response = flow.api.create_content_item(
            f.content_item_payload(
                chain["target_a"]["id"],
                chain["slot_a"]["id"],
                flow.campaign_version(chain["campaign"]["id"]),
                title="Cloud landing zone overview",
                planned_publish_at="2026-08-06T09:00:00.000Z",
            ),
            MANAGING_EDITOR,
        )

        validate_error(response, ERR_SLOT_CAPACITY_EXCEEDED, 409)
        assert_slot_commitment(flow.read_slot(chain["slot_a"]["id"]), 32, 80.00, "OPEN")
        assert_list_response(
            flow.api.list_content_items(
                MANAGING_EDITOR, {"slot_id": chain["slot_a"]["id"]}
            ),
            expected_total_count=1,
        )

    def test_a_slot_one_point_below_the_threshold_takes_the_medium_surcharge(
        self, flow
    ):
        """
        Slot B stands at 31 of 40 points, 77.50 percent, so the identical
        six-point brief takes the medium surcharge of 1, commits 7 points and
        leaves the slot at 38 points and 95.00 percent, still ``OPEN``.

        Design: Difficulty/boundary_precision_check/slot_utilization_exactly_eighty_percent_selects_high_surcharge
        """
        chain = _two_slots_either_side_of_the_high_threshold(flow)
        assert_slot_commitment(flow.read_slot(chain["slot_b"]["id"]), 31, 77.50, "OPEN")

        committed = validate_success(
            flow.api.create_content_item(
                f.content_item_payload(
                    chain["target_b"]["id"],
                    chain["slot_b"]["id"],
                    flow.campaign_version(chain["campaign"]["id"]),
                    title="Cloud landing zone glossary",
                    planned_publish_at="2026-08-13T09:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert committed["effort_points"] == 6
        assert committed["capacity_tier_at_commit"] == "MEDIUM"
        assert committed["commit_points"] == 7
        assert_slot_commitment(flow.read_slot(chain["slot_b"]["id"]), 38, 95.00, "OPEN")
        assert_campaign_counters(
            flow.read_campaign(chain["campaign"]["id"]), committed_points_total=70
        )


def _published_item_with_an_empty_baseline_window(flow):
    """
    A published item whose measurement periods both fall outside the baseline.

    One period straddles the publication instant and the other lands well after
    the baseline window closes, so no period is fully contained in the baseline.
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
    flow.set_clock(AUDIT_CLOCK)
    flow.snapshot(
        item["id"],
        "2026-08-01T00:00:00.000Z",
        "2026-08-05T00:00:00.000Z",
        engaged_sessions=1500,
        conversions=30,
        influenced_opportunity_amount_cents=100000,
        touch_position="LAST",
    )
    flow.snapshot(
        item["id"],
        "2026-09-10T00:00:00.000Z",
        "2026-09-17T00:00:00.000Z",
        engaged_sessions=900,
        conversions=12,
        influenced_opportunity_amount_cents=100000,
        touch_position="LAST",
    )
    return {"campaign": campaign, "item": item}


class TestDecayWithAnEmptyBaseline:
    """An empty baseline window short-circuits rather than dividing."""

    def test_a_zero_baseline_yields_zero_decay_and_no_refresh_requirement(
        self, flow
    ):
        """
        No measurement period is fully inside the 28-day baseline that opens at
        the publication instant, so the baseline sessions total is 0 and the decay
        percentage is 0.00 with no refresh required — counting the straddling
        1500-session period would instead report 40.00.

        Design: Difficulty/boundary_precision_check/decay_zero_baseline_window_yields_zero_pct_and_no_refresh
        """
        chain = _published_item_with_an_empty_baseline_window(flow)

        audited = validate_success(
            flow.api.audit_content_item(
                chain["item"]["id"], f.audit_payload(audit_type="DECAY"), MANAGING_EDITOR
            )
        )

        assert_two_decimal_value(audited["decay_pct"], 0.00)
        assert audited["refresh_required"] is False

    def test_the_audit_verdict_is_keep_and_the_item_stays_published(self, flow):
        """
        With no decay recorded the decay audit returns the keep verdict, stamps the
        audit instant at the clock and leaves the item published; the session total
        still counts both periods, because that total is not window-bounded.

        Design: Difficulty/boundary_precision_check/decay_zero_baseline_window_yields_zero_pct_and_no_refresh
        """
        chain = _published_item_with_an_empty_baseline_window(flow)

        flow.audit(chain["item"]["id"], audit_type="DECAY")

        item = flow.read_item(chain["item"]["id"])
        assert item["last_audit_type"] == "DECAY"
        assert item["last_audit_verdict"] == "KEEP"
        assert item["last_audit_at"] == AUDIT_CLOCK
        assert item["workflow_state"] == "PUBLISHED"
        assert item["published_at"] == SETUP_CLOCK
        assert item["engaged_sessions_total"] == 2400
