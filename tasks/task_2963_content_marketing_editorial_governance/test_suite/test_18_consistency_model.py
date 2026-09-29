"""
Read-your-writes: nothing in this service settles later.

Every derived figure a write recomputes is already present in that write's own
response body, and every row a write fans out is readable on the very next call
with no second write, no sweep and no delay: the attach response carries the
recomputed asset counters, the publish response carries the publication stamps
and the stored metadata, and the distribution rows and the recomputed campaign
posture are visible immediately afterwards.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_asset_rights,
    assert_campaign_counters,
    assert_distribution_channel_order,
    assert_instant_precision,
    assert_posture,
    assert_version,
)
from test_helpers.test_users import (
    ACCESSIBILITY_REVIEWER,
    BRAND_REVIEWER,
    EDITOR_TWO_ID,
    MANAGING_EDITOR,
    MANAGING_EDITOR_TWO,
    expert_headers,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
ITEM_TITLE = "Zero trust login guide"
SCHEDULED_AT = "2026-08-05T09:00:00.000Z"
META_DESCRIPTION = (
    "A practical guide to zero trust login rollouts for platform security teams."
)
TAGS = ["security", "zero-trust"]
URL_SLUG = "zero-trust-login-guide"


class TestImmediateVisibility:
    """A write's own response is the authority on everything it just changed."""

    def test_every_derived_field_and_cascade_row_is_readable_immediately(self, flow):
        """
        The attach response and the read that follows it already carry the recomputed
        use budget, the third gate decision has already joined the item to ``READY``,
        and the publish response already carries the publication stamps while its two
        distribution rows and the recomputed campaign posture are readable at once.

        Design: Corner/consistency_model/every_derived_field_and_cascade_row_is_readable_in_the_writes_own_response
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-IMMED", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
        )
        slot = flow.create_slot(
            campaign["id"],
            week_start_date="2026-08-03",
            funnel_stage="AWARENESS",
            capacity_points=40,
        )
        brief, expert_id = flow.approved_brief(
            campaign["id"],
            funnel_stage="AWARENESS",
            effort_points=6,
            expertise_tag="security",
        )
        item = flow.create_item(
            brief["id"],
            slot["id"],
            campaign["id"],
            title=ITEM_TITLE,
            planned_publish_at=SCHEDULED_AT,
        )
        item_id = item["id"]
        assert_version(item, 1)

        asset = flow.create_asset(
            name="Immediate visibility stock photo",
            asset_type="STOCK",
            license_start="2026-07-01T00:00:00.000Z",
            license_end="2026-12-31T00:00:00.000Z",
            licensed_channels=["OWNED", "EMAIL"],
            max_licensed_uses=3,
        )
        # The whole budget is free before any usage exists.
        assert_asset_rights(
            asset, status="LICENSED", active_use_count=0, remaining_licensed_uses=3
        )

        assert_version(flow.submit(item_id), 2)
        flow.decide_gate(
            flow.gate_of(item_id, "SME")["id"], "APPROVED", expert_headers(expert_id)
        )
        flow.decide_gate(
            flow.gate_of(item_id, "BRAND")["id"], "APPROVED", BRAND_REVIEWER
        )
        last_gate = flow.decide_gate(
            flow.gate_of(item_id, "ACCESSIBILITY")["id"],
            "APPROVED",
            ACCESSIBILITY_REVIEWER,
        )
        assert last_gate["state"] == "APPROVED"
        ready = flow.read_item(item_id)
        assert ready["workflow_state"] == "READY"
        # Create, submit and the join into READY each moved the item once.
        assert_version(ready, 3)

        usage = validate_success(
            flow.api.attach_asset_usage(
                item_id, f.asset_usage_payload(asset["id"], "OWNED"), MANAGING_EDITOR
            ),
            201,
        )
        assert usage["usage_state"] == "ACTIVE"
        assert usage["attached_at"] == SETUP_CLOCK
        assert_instant_precision(usage["attached_at"])
        assert_asset_rights(
            flow.read_asset(asset["id"]),
            status="LICENSED",
            active_use_count=1,
            remaining_licensed_uses=2,
        )

        published = validate_success(
            flow.api.publish_content_item(
                item_id,
                f.publish_payload(
                    scheduled_at=SCHEDULED_AT,
                    channels=["OWNED", "EMAIL"],
                    meta_description=META_DESCRIPTION,
                    url_slug=URL_SLUG,
                    tags=TAGS,
                ),
                MANAGING_EDITOR_TWO,
            )
        )
        assert published["workflow_state"] == "PUBLISHED"
        assert published["published_at"] == SETUP_CLOCK
        assert published["published_by_user_id"] == EDITOR_TWO_ID
        assert published["url_slug"] == URL_SLUG
        assert_version(published, 4)

        distributions = flow.distributions(item_id)
        assert len(distributions) == 2
        assert_distribution_channel_order(distributions)
        assert [row["channel"] for row in distributions] == ["OWNED", "EMAIL"]
        for row in distributions:
            assert row["state"] == "SCHEDULED"
            assert row["went_live_at"] is None

        usages = flow.usages(item_id)
        assert len(usages) == 1
        assert usages[0]["id"] == usage["id"]
        assert usages[0]["usage_state"] == "ACTIVE"

        # No sweep runs anywhere in this case.
        settled = flow.read_campaign(campaign["id"])
        assert_posture(settled, "OPEN")
        assert_campaign_counters(settled, committed_points_total=6)

        stored = flow.read_item(item_id)
        assert stored["meta_description"] == META_DESCRIPTION
        assert stored["url_slug"] == URL_SLUG
        assert stored["tags"] == TAGS
        assert len(stored["tags"]) == 2
