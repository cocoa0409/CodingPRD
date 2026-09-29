"""
Single requests that break two rules at once.

The service resolves competing failures by the fixed rule order, so each case
here builds one request that independently violates two rules and pins the
answer to the higher-priority one.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ASSET_RIGHTS_EXPIRED,
    ERR_CLAIM_NOT_SUBSTANTIATED,
    ERR_EXPERT_CAPACITY_EXCEEDED,
    ERR_EXPERT_UNAVAILABLE,
)
from test_helpers.assertions import (
    assert_list_response,
    assert_posture,
    assert_two_decimal_value,
)
from test_helpers.test_users import MANAGING_EDITOR, MANAGING_EDITOR_TWO

SETUP_CLOCK = "2026-08-03T08:00:00.000Z"
EXPIRED_RIGHTS_CLOCK = "2026-08-09T00:00:00.000Z"


def _brief_and_an_expert_on_leave_without_the_hours(flow):
    """
    A draft brief needing 11 reserved hours and an expert who is both on leave
    and four hours short of the requirement.
    """
    flow.set_clock(SETUP_CLOCK)
    campaign = flow.active_campaign(persona="IT_BUYER", primary_funnel_stage="DECISION")
    expert = flow.create_expert(expertise_tags=["security"], weekly_capacity_hours=4)
    flow.set_availability(expert["id"], "ON_LEAVE")
    brief = flow.create_brief(
        campaign["id"],
        funnel_stage="DECISION",
        required_expertise_tag="security",
        requires_regulated_review=True,
        search_intent="COMMERCIAL",
        target_word_count=1500,
        review_window_start="2026-08-03T09:00:00.000Z",
        review_window_end="2026-08-04T09:00:00.000Z",
    )
    return {"campaign": campaign, "expert": expert, "brief": brief}


class TestAssignSmeRulePriority:
    """Expert availability is checked before the weekly capacity ledger."""

    def test_unavailability_is_reported_rather_than_the_capacity_shortfall(
        self, flow
    ):
        """
        The brief reserves 11 hours against a 4-hour weekly capacity and the
        expert is on leave, so the request breaks both rules; availability sits
        higher in the rule order, so the answer is the unavailability conflict.

        Design: Difficulty/priority_pair_validation_conflict/assign_sme_expert_unavailable_outranks_weekly_capacity_exceeded
        """
        chain = _brief_and_an_expert_on_leave_without_the_hours(flow)
        expert = flow.read_expert(chain["expert"]["id"])
        brief = flow.read_brief(chain["brief"]["id"])
        assert brief["effort_points"] == 21
        assert brief["sme_reserved_hours"] == 11
        # 0 committed hours plus 11 reserved exceeds the 4-hour weekly capacity,
        # so the capacity rule is independently violated by the same request.
        assert expert["weekly_capacity_hours"] == 4
        assert expert["committed_hours_total"] == 0
        assert expert["status"] == "ON_LEAVE"

        response = flow.api.assign_sme(
            chain["brief"]["id"],
            f.assign_sme_payload(expert["id"], expert["version"]),
            MANAGING_EDITOR,
        )

        error = validate_error(response, ERR_EXPERT_UNAVAILABLE, 409)
        assert error["error_id"] != ERR_EXPERT_CAPACITY_EXCEEDED

    def test_the_rejected_assignment_writes_neither_the_brief_nor_the_expert(
        self, flow
    ):
        """
        A refused assignment leaves the brief in ``DRAFT`` with no expert attached
        and leaves the expert row exactly as it was, version included.

        Design: Difficulty/priority_pair_validation_conflict/assign_sme_expert_unavailable_outranks_weekly_capacity_exceeded
        """
        chain = _brief_and_an_expert_on_leave_without_the_hours(flow)
        pinned_version = flow.expert_version(chain["expert"]["id"])

        response = flow.api.assign_sme(
            chain["brief"]["id"],
            f.assign_sme_payload(chain["expert"]["id"], pinned_version),
            MANAGING_EDITOR,
        )
        validate_error(response, ERR_EXPERT_UNAVAILABLE, 409)

        brief = flow.read_brief(chain["brief"]["id"])
        assert brief["state"] == "DRAFT"
        assert brief["sme_expert_id"] is None
        expert = flow.read_expert(chain["expert"]["id"])
        assert expert["version"] == pinned_version
        assert expert["committed_hours_total"] == 0


def _ready_item_with_a_pending_claim_and_lapsed_rights(flow):
    """
    A ready item that carries an undecided claim and an asset usage whose
    licence ended the day before the clock.
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
        planned_publish_at="2026-08-07T09:00:00.000Z",
    )
    claim = flow.create_claim(item["id"], claim_type="PERFORMANCE")
    flow.file_evidence(
        claim["id"],
        source_type="THIRD_PARTY_TEST",
        citation="Northwind Labs comparative benchmark, report NL-2026-118",
        collected_at="2026-06-01T00:00:00.000Z",
        valid_until="2027-06-01T00:00:00.000Z",
    )
    asset = flow.create_asset(
        name="Hero photography set B",
        asset_type="STOCK",
        license_start="2026-07-01T00:00:00.000Z",
        license_end="2026-08-08T00:00:00.000Z",
        licensed_channels=["OWNED"],
        max_licensed_uses=2,
    )
    usage = flow.attach_usage(item["id"], asset["id"], "OWNED")
    flow.submit(item["id"])
    flow.approve_all_gates(item["id"], expert_id)
    flow.set_clock(EXPIRED_RIGHTS_CLOCK)
    return {
        "campaign": campaign,
        "item": item,
        "claim": claim,
        "asset": asset,
        "usage": usage,
    }


PUBLISH_ATTEMPT = f.publish_payload(
    scheduled_at="2026-08-07T09:00:00.000Z",
    channels=["OWNED"],
    url_slug="zero-trust-platform-pricing",
)


class TestPublishRulePriority:
    """Claim substantiation is checked before asset rights validity."""

    def test_the_unsubstantiated_claim_is_reported_rather_than_the_lapsed_rights(
        self, flow
    ):
        """
        The item carries a claim still awaiting a legal decision and a usage whose
        asset licence ended on 2026-08-08, one day before the clock, so the
        request breaks both rules; substantiation sits higher in the rule order,
        so the answer is the substantiation failure.

        Design: Difficulty/priority_pair_validation_conflict/publish_unsubstantiated_claim_outranks_expired_asset_rights
        """
        chain = _ready_item_with_a_pending_claim_and_lapsed_rights(flow)
        # The licence genuinely ended before the clock, so the rights rule is
        # independently violated by the same request.
        assert chain["asset"]["license_end"] == "2026-08-08T00:00:00.000Z"

        response = flow.api.publish_content_item(
            chain["item"]["id"], PUBLISH_ATTEMPT, MANAGING_EDITOR_TWO
        )

        error = validate_error(response, ERR_CLAIM_NOT_SUBSTANTIATED, 422)
        assert error["error_id"] != ERR_ASSET_RIGHTS_EXPIRED

    def test_the_refused_publication_leaves_the_item_ready_with_no_distributions(
        self, flow
    ):
        """
        A refused publication leaves the item in ``READY`` with no publication
        stamps and emits no distribution rows, while the claim keeps its
        2.00 score against a 2.00 requirement and the usage stays active.

        Design: Difficulty/priority_pair_validation_conflict/publish_unsubstantiated_claim_outranks_expired_asset_rights
        """
        chain = _ready_item_with_a_pending_claim_and_lapsed_rights(flow)

        response = flow.api.publish_content_item(
            chain["item"]["id"], PUBLISH_ATTEMPT, MANAGING_EDITOR_TWO
        )
        validate_error(response, ERR_CLAIM_NOT_SUBSTANTIATED, 422)

        item = flow.read_item(chain["item"]["id"])
        assert item["workflow_state"] == "READY"
        assert item["published_at"] is None
        assert item["published_by_user_id"] is None
        assert_list_response(
            flow.api.list_distributions(chain["item"]["id"], MANAGING_EDITOR),
            expected_total_count=0,
        )

        claim = flow.read_claim(chain["claim"]["id"])
        assert claim["substantiation_state"] == "EVIDENCE_PENDING"
        assert_two_decimal_value(claim["evidence_score"], 2.00)
        assert_two_decimal_value(claim["required_score"], 2.00)
        usages = flow.usages(chain["item"]["id"])
        assert usages[0]["usage_state"] == "ACTIVE"
        assert_posture(flow.read_campaign(chain["campaign"]["id"]), "OPEN")
