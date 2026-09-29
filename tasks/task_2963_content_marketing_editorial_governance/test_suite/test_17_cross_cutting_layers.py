"""
Cross-cutting layers: the concurrency token and the rate threshold.

The first case watches the optimistic-concurrency token move: it advances on
the row that was written and on no other, a child insert never restates its
parent, and a refused write advances nothing at all. The second case treats the
usage-count governance trigger as a level rather than a latch — it arms on a
lapsed usage, disarms on the renewal that clears it, and arms again on the next
expiry — while the piece itself stays flagged for refresh throughout.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_CAMPAIGN_STATE_INVALID
from test_helpers.assertions import (
    assert_asset_rights,
    assert_campaign_counters,
    assert_integer_value,
    assert_list_response,
    assert_no_op_sweep,
    assert_posture,
    assert_slot_commitment,
    assert_sweep_tally,
    assert_version,
)
from test_helpers.test_users import (
    MANAGING_EDITOR,
    MANAGING_EDITOR_TWO,
    expert_headers,
)

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
ITEM_TITLE = "Zero trust login guide"
META_DESCRIPTION = (
    "A practical guide to zero trust login rollouts for platform security teams."
)
TAGS = ["security", "zero-trust"]


class TestVersionSequencing:
    """A version is the row's own write counter, not its subtree's."""

    def test_version_moves_only_on_the_accepted_write_and_only_on_its_own_row(
        self, flow
    ):
        """
        Creating a calendar slot or a brief under a campaign leaves the campaign's
        version alone while committing a content item advances it, a refused second
        activation advances nothing, and assigning an expert advances the brief and
        the expert but never the campaign.

        Design: Corner/cross_cutting_complexity_layers/version_increments_only_on_accepted_writes_and_only_on_the_row_that_was_written
        """
        created = validate_success(
            flow.api.create_campaign(
                f.campaign_payload(
                    code="CMP-OCCSEQ",
                    persona="PRACTITIONER",
                    primary_funnel_stage="AWARENESS",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert_version(created, 1)
        campaign_id = created["id"]
        assert_version(
            validate_success(flow.api.activate_campaign(campaign_id, MANAGING_EDITOR)),
            2,
        )

        slot = validate_success(
            flow.api.create_calendar_slot(
                campaign_id,
                f.calendar_slot_payload(
                    week_start_date="2026-08-03",
                    funnel_stage="AWARENESS",
                    capacity_points=40,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert_version(slot, 1)
        # A sibling insert is not a change to the commitment ledger.
        assert_version(flow.read_campaign(campaign_id), 2)

        expert = validate_success(
            flow.api.create_expert(
                f.expert_payload(
                    full_name="Ines Baro",
                    expertise_tags=["security"],
                    weekly_capacity_hours=40,
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert_version(expert, 1)
        expert_id = expert["id"]
        assert_version(flow.set_availability(expert_id, "ON_LEAVE"), 2)
        assert_version(flow.set_availability(expert_id, "AVAILABLE"), 3)

        brief = validate_success(
            flow.api.create_brief(
                f.brief_payload(
                    campaign_id,
                    funnel_stage="AWARENESS",
                    search_intent="NAVIGATIONAL",
                    primary_keyword="zero trust login",
                    target_word_count=100,
                    required_expertise_tag="security",
                    review_window_start="2026-08-03T09:00:00.000Z",
                    review_window_end="2026-08-03T12:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert_version(brief, 1)
        assert_version(flow.read_campaign(campaign_id), 2)

        validate_error(
            flow.api.activate_campaign(campaign_id, MANAGING_EDITOR),
            ERR_CAMPAIGN_STATE_INVALID,
            409,
        )
        assert_version(flow.read_campaign(campaign_id), 2)

        assigned = validate_success(
            flow.api.assign_sme(
                brief["id"], f.assign_sme_payload(expert_id, 3), MANAGING_EDITOR
            )
        )
        assert assigned["sme_expert_id"] == expert_id
        assert_version(assigned, 2)
        after_assign = flow.read_expert(expert_id)
        assert_version(after_assign, 4)
        # The brief reserves half its six clamped effort points, rounded up.
        assert_integer_value(after_assign["committed_hours_total"], 3)
        assert_version(flow.read_campaign(campaign_id), 2)

        approved = validate_success(
            flow.api.approve_brief(brief["id"], expert_headers(expert_id))
        )
        assert_version(approved, 3)
        assert_version(flow.read_expert(expert_id), 4)

        item = validate_success(
            flow.api.create_content_item(
                f.content_item_payload(
                    brief["id"],
                    slot["id"],
                    2,
                    title=ITEM_TITLE,
                    planned_publish_at="2026-08-05T09:00:00.000Z",
                ),
                MANAGING_EDITOR,
            ),
            201,
        )
        assert_version(item, 1)
        assert_integer_value(item["commit_points"], 6)

        after_item = flow.read_campaign(campaign_id)
        assert_version(after_item, 3)
        assert_campaign_counters(after_item, committed_points_total=6)
        after_slot = flow.read_slot(slot["id"])
        assert_slot_commitment(after_slot, 6, 15.00, status="OPEN")
        # The slot keeps its OPEN status, but its committed_points and utilization_pct
        # were rewritten by the commit, and a rewritten row advances its own version.
        assert_version(after_slot, 2)


class TestRightsThresholdLevel:
    """The usage-count trigger tracks the current offending rows, not history."""

    def test_usage_count_trigger_disarms_on_renewal_and_arms_again_on_the_next_expiry(
        self, flow
    ):
        """
        One lapsed usage restricts the campaign, the renewal that revives it walks the
        posture back to open in the very next read, and a second expiry of the renewed
        licence restricts it again — while every replayed sweep at an unmoved clock
        counts nothing and the piece stays flagged for refresh throughout.

        Design: Corner/cross_cutting_complexity_layers/rights_threshold_disarms_on_renewal_and_re_arms_on_the_next_expiry
        """
        flow.set_clock(SETUP_CLOCK)
        campaign = flow.active_campaign(
            code="CMP-RESET", persona="PRACTITIONER", primary_funnel_stage="AWARENESS"
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
            planned_publish_at="2026-08-04T09:00:00.000Z",
        )
        asset = flow.create_asset(
            name="Reset cycle stock photo",
            asset_type="STOCK",
            license_start="2026-07-01T00:00:00.000Z",
            license_end="2026-09-10T00:00:00.000Z",
            licensed_channels=["OWNED"],
            max_licensed_uses=5,
        )
        # The licence ends 38 days out, so it is outside the 30-day warning window.
        assert_asset_rights(asset, status="LICENSED")
        assert_version(asset, 1)
        usage = flow.attach_usage(item["id"], asset["id"], "OWNED")

        flow.submit(item["id"])
        flow.approve_all_gates(item["id"], expert_id)
        flow.set_clock("2026-08-04T10:00:00.000Z")
        validate_success(
            flow.api.publish_content_item(
                item["id"],
                f.publish_payload(
                    scheduled_at="2026-08-04T09:00:00.000Z",
                    channels=["OWNED"],
                    meta_description=META_DESCRIPTION,
                    url_slug="zero-trust-login-guide",
                    tags=TAGS,
                ),
                MANAGING_EDITOR_TWO,
            )
        )
        distributions = flow.distributions(item["id"])
        assert len(distributions) == 1
        distribution_id = distributions[0]["id"]
        assert distributions[0]["state"] == "LIVE"
        assert_version(distributions[0], 1)

        flow.set_clock("2026-09-11T00:00:00.000Z")
        assert_sweep_tally(
            flow.sweep(),
            assets_expired=1,
            usages_lapsed=1,
            distributions_suppressed=1,
            items_flagged_refresh=1,
            campaigns_restricted=1,
        )

        restricted = flow.read_campaign(campaign["id"])
        assert_posture(restricted, "RESTRICTED")
        assert_campaign_counters(restricted, expired_usage_count=1)
        expired_asset = flow.read_asset(asset["id"])
        assert expired_asset["status"] == "EXPIRED"
        # Version 1 at registration, 2 when the attachment recomputed the use budget,
        # 3 for the expiry cascade's single bump.
        assert_version(expired_asset, 3)
        lapsed = flow.usages(item["id"])
        assert len(lapsed) == 1
        assert lapsed[0]["id"] == usage["id"]
        assert lapsed[0]["usage_state"] == "RIGHTS_LAPSED"
        suppressed = flow.distributions(item["id"])[0]
        assert suppressed["state"] == "SUPPRESSED"
        assert suppressed["suppression_reason"] == "ASSET_RIGHTS_LAPSED"
        assert_version(suppressed, 2)
        assert flow.read_item(item["id"])["workflow_state"] == "NEEDS_REFRESH"

        # A replay at the unmoved clock re-counts nothing already accounted for.
        assert_no_op_sweep(flow.sweep())
        assert_posture(flow.read_campaign(campaign["id"]), "RESTRICTED")

        renewed = validate_success(
            flow.api.renew_asset(
                asset["id"], "2026-12-31T00:00:00.000Z", MANAGING_EDITOR
            )
        )
        assert_asset_rights(
            renewed, status="LICENSED", active_use_count=1, remaining_licensed_uses=4
        )
        assert_version(renewed, 4)

        revived = flow.usages(item["id"])[0]
        assert revived["usage_state"] == "ACTIVE"
        assert revived["released_at"] is None
        restored = flow.distributions(item["id"])[0]
        assert restored["id"] == distribution_id
        assert restored["state"] == "LIVE"
        assert restored["suppression_reason"] is None
        assert restored["suppressed_at"] is None
        assert restored["went_live_at"] == "2026-09-11T00:00:00.000Z"
        assert_version(restored, 3)

        reopened = flow.read_campaign(campaign["id"])
        assert_posture(reopened, "OPEN")
        assert_campaign_counters(reopened, expired_usage_count=0)
        # The restoration is deliberately partial: the piece stays flagged.
        assert flow.read_item(item["id"])["workflow_state"] == "NEEDS_REFRESH"
        assert_no_op_sweep(flow.sweep())

        flow.set_clock("2027-01-01T00:00:00.000Z")
        assert_sweep_tally(
            flow.sweep(),
            assets_expired=1,
            usages_lapsed=1,
            distributions_suppressed=1,
            campaigns_restricted=1,
        )
        rearmed = flow.read_campaign(campaign["id"])
        assert_posture(rearmed, "RESTRICTED")
        assert_campaign_counters(rearmed, expired_usage_count=1)
        # 4 after the renewal, 5 for the second expiry cascade.
        assert_version(flow.read_asset(asset["id"]), 5)
        assert_list_response(
            flow.api.list_assets(MANAGING_EDITOR, {"status": "EXPIRED"}),
            expected_total_count=1,
            expected_row_count=1,
        )
