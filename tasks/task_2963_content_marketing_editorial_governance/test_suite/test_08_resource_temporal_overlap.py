"""
Half-open interval geometry for the two exclusive resources.

An expert's review windows may touch but not interleave, and a talent asset's
promotion windows must additionally keep a whole week of clear air, so windows
that merely share an endpoint separate the two rules.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_EXPERT_WINDOW_OVERLAP,
    ERR_TALENT_EXCLUSIVITY_BUFFER,
)
from test_helpers.assertions import (
    assert_asset_rights,
    assert_list_response,
    assert_slot_commitment,
)
from test_helpers.test_users import MANAGING_EDITOR

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"

WINDOW_A = {
    "review_window_start": "2026-08-03T09:00:00.000Z",
    "review_window_end": "2026-08-05T09:00:00.000Z",
}
WINDOW_B = {
    "review_window_start": "2026-08-04T09:00:00.000Z",
    "review_window_end": "2026-08-06T09:00:00.000Z",
}
WINDOW_C = {
    "review_window_start": "2026-08-05T09:00:00.000Z",
    "review_window_end": "2026-08-07T09:00:00.000Z",
}


def _one_expert_holding_the_first_review_window(flow):
    """
    An expert with 40 weekly hours already assigned to brief A.

    Brief B's window opens a day inside A's, brief C's opens at the exact instant
    A's closes, and every brief reserves 3 hours so the weekly capacity rule can
    never be the binding constraint.
    """
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(
        persona="IT_BUYER", primary_funnel_stage="AWARENESS"
    )
    expert = flow.create_expert(expertise_tags=["security"], weekly_capacity_hours=40)
    briefs = [
        flow.create_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            required_expertise_tag="security",
            **window,
        )
        for window in (WINDOW_A, WINDOW_B, WINDOW_C)
    ]
    flow.assign_sme(briefs[0]["id"], expert["id"])
    return {
        "campaign": campaign,
        "expert_id": expert["id"],
        "expert_version": flow.expert_version(expert["id"]),
        "brief_a": briefs[0],
        "brief_b": briefs[1],
        "brief_c": briefs[2],
    }


class TestExpertReviewWindowOverlap:
    """Interior overlap is refused where a shared endpoint is not."""

    def test_a_window_opening_inside_the_held_window_is_refused(self, flow):
        """
        Brief B's window opens one day inside the window the expert already holds,
        so the assignment is refused and brief B keeps its draft state with no
        expert recorded.

        Design: Difficulty/resource_temporal_overlap/expert_review_window_interior_overlap_rejected_but_touching_window_accepted
        """
        chain = _one_expert_holding_the_first_review_window(flow)

        response = flow.api.assign_sme(
            chain["brief_b"]["id"],
            f.assign_sme_payload(chain["expert_id"], chain["expert_version"]),
            MANAGING_EDITOR,
        )

        validate_error(response, ERR_EXPERT_WINDOW_OVERLAP, 409)
        brief_b = flow.read_brief(chain["brief_b"]["id"])
        assert brief_b["state"] == "DRAFT"
        assert brief_b["sme_expert_id"] is None

    def test_a_window_opening_where_the_held_window_ends_is_accepted(self, flow):
        """
        Brief C's window starts at the exact instant brief A's ends, which is not
        interior overlap, so the assignment succeeds on the same expert version the
        rejected attempt used and the reserved hours accumulate to 6.

        Design: Difficulty/resource_temporal_overlap/expert_review_window_interior_overlap_rejected_but_touching_window_accepted
        """
        chain = _one_expert_holding_the_first_review_window(flow)
        validate_error(
            flow.api.assign_sme(
                chain["brief_b"]["id"],
                f.assign_sme_payload(chain["expert_id"], chain["expert_version"]),
                MANAGING_EDITOR,
            ),
            ERR_EXPERT_WINDOW_OVERLAP,
            409,
        )

        assigned = validate_success(
            flow.api.assign_sme(
                chain["brief_c"]["id"],
                f.assign_sme_payload(chain["expert_id"], chain["expert_version"]),
                MANAGING_EDITOR,
            )
        )

        assert assigned["state"] == "SME_ASSIGNED"
        assert assigned["sme_expert_id"] == chain["expert_id"]
        assert assigned["sme_reserved_hours"] == 3
        expert = flow.read_expert(chain["expert_id"])
        assert expert["committed_hours_total"] == 6
        assert expert["status"] == "AVAILABLE"


def _two_assets_on_the_first_of_three_promotion_windows(flow):
    """
    A stock asset and a talent asset both attached to the first item.

    The three items promote over [2026-08-04, 2026-08-07), [2026-08-07, 2026-08-10)
    and [2026-08-14, 2026-08-17), so the second window touches the first and the
    third opens exactly seven days after the first one closes.
    """
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(
        persona="IT_BUYER", primary_funnel_stage="AWARENESS"
    )
    slot_one = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-03",
        funnel_stage="AWARENESS",
        capacity_points=40,
    )
    slot_two = flow.create_slot(
        campaign["id"],
        week_start_date="2026-08-10",
        funnel_stage="AWARENESS",
        capacity_points=40,
    )
    items = []
    for slot_id, publish_at, title in (
        (slot_one["id"], "2026-08-04T00:00:00.000Z", "Zero trust glossary"),
        (slot_one["id"], "2026-08-07T00:00:00.000Z", "Zero trust starter checklist"),
        (slot_two["id"], "2026-08-14T00:00:00.000Z", "Zero trust myth list"),
    ):
        brief, _expert_id = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expertise_tag="security",
        )
        items.append(
            flow.create_item(
                brief["id"],
                slot_id,
                campaign["id"],
                title=title,
                planned_publish_at=publish_at,
                promotion_window_days=3,
            )
        )
    stock_asset = flow.create_asset(
        name="Stock rack photography set",
        asset_type="STOCK",
        licensed_channels=["OWNED"],
        max_licensed_uses=5,
    )
    talent_asset = flow.create_asset(
        name="Spokesperson session with A. Reyes",
        asset_type="TALENT",
        licensed_channels=["OWNED"],
        max_licensed_uses=5,
    )
    stock_usage = flow.attach_usage(items[0]["id"], stock_asset["id"], channel="OWNED")
    talent_usage = flow.attach_usage(items[0]["id"], talent_asset["id"], channel="OWNED")
    return {
        "campaign": campaign,
        "slot_one": slot_one,
        "items": items,
        "stock_asset": stock_asset,
        "talent_asset": talent_asset,
        "stock_usage": stock_usage,
        "talent_usage": talent_usage,
    }


class TestTalentExclusivityBuffer:
    """Touching promotion windows are legal for stock and illegal for talent."""

    def test_touching_windows_are_legal_for_stock_and_illegal_for_talent(self, flow):
        """
        The second item's promotion window starts where the first item's ends: the
        stock asset attaches because that is not interior overlap, while the talent
        asset is refused for want of its seven-day buffer, leaving the second item
        holding the stock usage only.

        Design: Difficulty/resource_temporal_overlap/talent_asset_requires_seven_day_buffer_where_stock_accepts_touching_windows
        """
        chain = _two_assets_on_the_first_of_three_promotion_windows(flow)

        stock_usage = validate_success(
            flow.api.attach_asset_usage(
                chain["items"][1]["id"],
                f.asset_usage_payload(chain["stock_asset"]["id"], channel="OWNED"),
                MANAGING_EDITOR,
            ),
            201,
        )
        refused = flow.api.attach_asset_usage(
            chain["items"][1]["id"],
            f.asset_usage_payload(chain["talent_asset"]["id"], channel="OWNED"),
            MANAGING_EDITOR,
        )

        assert stock_usage["usage_state"] == "ACTIVE"
        assert stock_usage["attached_at"] == SETUP_CLOCK
        assert_asset_rights(
            flow.read_asset(chain["stock_asset"]["id"]),
            active_use_count=2,
            remaining_licensed_uses=3,
        )
        validate_error(refused, ERR_TALENT_EXCLUSIVITY_BUFFER, 409)
        rows = assert_list_response(
            flow.api.list_item_asset_usages(
                chain["items"][1]["id"], MANAGING_EDITOR
            ),
            expected_total_count=1,
        )
        assert rows[0]["id"] == stock_usage["id"]

    def test_a_window_opening_exactly_seven_days_later_clears_the_buffer(self, flow):
        """
        The third item's promotion window opens exactly seven days after the first
        item's closes, which satisfies the buffer at its inclusive boundary, so the
        talent asset attaches a second time while the first usage stays active and
        the shared calendar slot still carries only its two committed items.

        Design: Difficulty/resource_temporal_overlap/talent_asset_requires_seven_day_buffer_where_stock_accepts_touching_windows
        """
        chain = _two_assets_on_the_first_of_three_promotion_windows(flow)

        usage = validate_success(
            flow.api.attach_asset_usage(
                chain["items"][2]["id"],
                f.asset_usage_payload(chain["talent_asset"]["id"], channel="OWNED"),
                MANAGING_EDITOR,
            ),
            201,
        )

        assert usage["usage_state"] == "ACTIVE"
        assert_asset_rights(
            flow.read_asset(chain["talent_asset"]["id"]),
            active_use_count=2,
            remaining_licensed_uses=3,
        )
        first_usages = {row["id"]: row for row in flow.usages(chain["items"][0]["id"])}
        assert first_usages[chain["talent_usage"]["id"]]["usage_state"] == "ACTIVE"
        assert_slot_commitment(flow.read_slot(chain["slot_one"]["id"]), 12, 30.00, "OPEN")
