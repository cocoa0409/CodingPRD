"""
Guards that must be read from a neighbouring entity, not from the item itself.

A content item carries no copy of its brief's state and no copy of its campaign's
governance posture, so both transitions here have to be resolved by reading the
related row at decision time.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ASSET_RIGHTS_EXPIRED,
    ERR_BRIEF_NOT_APPROVED,
    ERR_CAMPAIGN_POSTURE_FROZEN,
)
from test_helpers.assertions import (
    assert_asset_rights,
    assert_campaign_counters,
    assert_list_response,
    assert_posture,
    assert_slot_commitment,
)
from test_helpers.test_users import MANAGING_EDITOR, MANAGING_EDITOR_TWO, expert_headers

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
LAPSE_CLOCK = "2026-08-11T00:00:00.000Z"


def _draft_item_whose_brief_regressed_after_creation(flow):
    """
    A legal DRAFT item whose parent brief has fallen back to DRAFT.

    The item is created while the brief is APPROVED and only then does the
    assigned expert request changes, and because that cascade reaches items in
    review or ready only, this DRAFT item is left exactly as created.
    """
    flow.set_clock(SETUP_CLOCK)
    chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")
    validate_success(
        flow.api.request_brief_changes(
            chain["brief"]["id"],
            expert_headers(chain["expert_id"]),
            notes="Pricing table must be re-sourced from the current rate card.",
        )
    )
    return chain


class TestSubmitReadsTheLiveBriefState:
    """The submit guard consults the brief row, not a snapshot of it."""

    def test_submit_is_refused_once_the_parent_brief_falls_back_to_draft(self, flow):
        """
        The brief that authorised this item is back in ``DRAFT`` with its expert
        cleared, so moving the item into review is refused even though the item is
        a perfectly legal ``DRAFT`` and the caller holds the editor role.

        Design: Difficulty/cross_entity_state_dependency/submit_for_review_requires_brief_state_approved
        """
        chain = _draft_item_whose_brief_regressed_after_creation(flow)
        brief = flow.read_brief(chain["brief"]["id"])
        assert brief["state"] == "DRAFT"
        assert brief["sme_expert_id"] is None

        response = flow.api.submit_for_review(chain["item"]["id"], MANAGING_EDITOR)

        validate_error(response, ERR_BRIEF_NOT_APPROVED, 409)

    def test_the_refused_submit_fans_out_no_review_gates(self, flow):
        """
        Nothing is written by the rejected transition: the item stays ``DRAFT`` on
        its first revision, no gate rows exist, and the calendar commitment the
        item took at creation is untouched.

        Design: Difficulty/cross_entity_state_dependency/submit_for_review_requires_brief_state_approved
        """
        chain = _draft_item_whose_brief_regressed_after_creation(flow)

        validate_error(
            flow.api.submit_for_review(chain["item"]["id"], MANAGING_EDITOR),
            ERR_BRIEF_NOT_APPROVED,
            409,
        )

        item = flow.read_item(chain["item"]["id"])
        assert item["workflow_state"] == "DRAFT"
        assert item["revision_number"] == 1
        assert_list_response(
            flow.api.list_review_gates(chain["item"]["id"], MANAGING_EDITOR),
            expected_total_count=0,
        )
        assert_slot_commitment(flow.read_slot(chain["slot"]["id"]), 16, 40.00, "OPEN")


def _ready_item_on_a_campaign_frozen_by_two_lapsed_usages(flow):
    """
    A ready item on a campaign whose posture has been frozen by sibling usages.

    Two assets each carrying one active usage expire together, so the campaign's
    expired usage count reaches the freeze threshold rather than the restrict one.
    """
    flow.set_clock(SETUP_CLOCK)
    chain = flow.committed_item(funnel_stage="DECISION", persona="IT_BUYER")
    owned_asset = flow.create_asset(
        name="Zero trust rack photography",
        asset_type="STOCK",
        license_end="2026-08-10T00:00:00.000Z",
        licensed_channels=["OWNED"],
        max_licensed_uses=5,
    )
    email_asset = flow.create_asset(
        name="Zero trust email header art",
        asset_type="STOCK",
        license_end="2026-08-10T00:00:00.000Z",
        licensed_channels=["EMAIL"],
        max_licensed_uses=5,
    )
    owned_usage = flow.attach_usage(
        chain["item"]["id"], owned_asset["id"], channel="OWNED"
    )
    email_usage = flow.attach_usage(
        chain["item"]["id"], email_asset["id"], channel="EMAIL"
    )
    flow.submit(chain["item"]["id"])
    flow.approve_all_gates(chain["item"]["id"], chain["expert_id"])
    flow.set_clock(LAPSE_CLOCK)
    tally = flow.sweep()
    chain.update(
        {
            "owned_asset": owned_asset,
            "email_asset": email_asset,
            "owned_usage": owned_usage,
            "email_usage": email_usage,
            "tally": tally,
        }
    )
    return chain


PUBLISH_ATTEMPT = f.publish_payload(
    scheduled_at=LAPSE_CLOCK,
    channels=["OWNED", "EMAIL"],
    meta_description=(
        "A practical buyer guide to zero trust platform pricing for security "
        "and procurement teams."
    ),
    url_slug="zero-trust-platform-pricing",
    tags=["security", "pricing"],
)


class TestPublishReadsTheCampaignPosture:
    """The frozen posture derived from sibling usages outranks the item's own rights check."""

    def test_publish_is_refused_by_the_frozen_posture_two_entities_away(self, flow):
        """
        Expiring the two assets lapses their two usages and freezes the parent
        campaign, and publish reports the frozen posture rather than the expired
        rights of the very same assets, because the posture guard is ordered ahead
        of the asset rights guard.

        Design: Difficulty/cross_entity_state_dependency/publish_blocked_while_campaign_posture_frozen_by_lapsed_usages
        """
        chain = _ready_item_on_a_campaign_frozen_by_two_lapsed_usages(flow)
        assert chain["tally"]["assets_expired"] == 2
        assert chain["tally"]["usages_lapsed"] == 2
        assert chain["tally"]["campaigns_frozen"] == 1

        response = flow.api.publish_content_item(
            chain["item"]["id"], PUBLISH_ATTEMPT, MANAGING_EDITOR_TWO
        )

        error = validate_error(response, ERR_CAMPAIGN_POSTURE_FROZEN, 409)
        assert error["error_id"] != ERR_ASSET_RIGHTS_EXPIRED

    def test_the_frozen_campaign_leaves_the_item_ready_and_undistributed(self, flow):
        """
        The refused publish writes nothing: the campaign is frozen on an expired
        usage count of 2, both assets are expired with their usages lapsed, and the
        item is still ``READY`` with no publication instant and no distributions.

        Design: Difficulty/cross_entity_state_dependency/publish_blocked_while_campaign_posture_frozen_by_lapsed_usages
        """
        chain = _ready_item_on_a_campaign_frozen_by_two_lapsed_usages(flow)

        validate_error(
            flow.api.publish_content_item(
                chain["item"]["id"], PUBLISH_ATTEMPT, MANAGING_EDITOR_TWO
            ),
            ERR_CAMPAIGN_POSTURE_FROZEN,
            409,
        )

        campaign = flow.read_campaign(chain["campaign"]["id"])
        assert_posture(campaign, "FROZEN")
        assert_campaign_counters(campaign, expired_usage_count=2, committed_points_total=16)
        assert_asset_rights(flow.read_asset(chain["owned_asset"]["id"]), status="EXPIRED")
        assert_asset_rights(flow.read_asset(chain["email_asset"]["id"]), status="EXPIRED")
        usages = {row["id"]: row for row in flow.usages(chain["item"]["id"])}
        assert usages[chain["owned_usage"]["id"]]["usage_state"] == "RIGHTS_LAPSED"
        assert usages[chain["email_usage"]["id"]]["usage_state"] == "RIGHTS_LAPSED"
        item = flow.read_item(chain["item"]["id"])
        assert item["workflow_state"] == "READY"
        assert item["published_at"] is None
        assert_list_response(
            flow.api.list_distributions(chain["item"]["id"], MANAGING_EDITOR),
            expected_total_count=0,
        )
