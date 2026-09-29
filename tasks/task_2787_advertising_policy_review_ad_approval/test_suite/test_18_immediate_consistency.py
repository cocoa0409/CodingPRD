"""One disapproval, then a sweep of reads that must already agree with it.

The system has no deferred tail: the six-hop cascade behind a manual disapproval is finished
by the time the decision responds, so the notice, the ledger, both advertiser balances, the
severity index, the minted enforcement action, the account posture, the serving gate and the
reviewer's freed slot are all readable in the very next request. Nothing here advances the
logical clock and nothing here runs the sweep.
"""

import pytest

from test_helpers import (
    ADMIN,
    api_client,
    assert_instant_equals,
    fixtures,
    validate_paginated,
)

SEV_TWELVE = "SEV_TWELVE"


def test_every_artefact_of_a_disapproval_is_readable_in_the_very_next_request():
    """PRD §2.9: "First, a cascade is immediate and complete within the request that
    triggered it — there is no deferred or eventually-consistent tail, and a read issued after
    the response reflects every hop."

    PRD §3.7: "Once the reason codes pass, the cascade runs in six hops. Hop one moves the
    task to `RESOLVED` with `resolution` `DISAPPROVE` and decrements the holding reviewer's
    `claimed_task_count` by 1. Hop two creates a disapproval notice in status `ISSUED` whose
    `decided_by_reviewer_id` is the acting reviewer and whose `reason_codes` are the supplied
    ones. Hop three has that notice write a violation ledger entry with `reason`
    `DISAPPROVAL_ASSESSED`, `delta_points` equal to the notice's `assessed_points` and
    `balance_after` set to the advertiser's new raw balance. Hop four recomputes the
    advertiser's `violation_points_raw`, `violation_points_decayed` and `severity_index` from
    the whole ledger. Hop five lets the refreshed `severity_index` possibly create an
    enforcement action, supersede whatever action was previously in force, and re-derive
    `account_status`."

    PRD §3.9: "Its `appeal_window_hours` is 168 hours — seven days — when `political_at_issue`
    is true, and 72 hours — three days — otherwise; its `appeal_deadline_at` is the notice's
    `created_at` plus that many whole hours."

    PRD §3.9: "The notice also records `disclosed_points_total`, which is the advertiser's
    `violation_points_raw` immediately after this notice's ledger entry has landed, so the
    advertiser sees the balance the notice actually produced."

    PRD §3.2: "When the most severe action in force is a warning, the posture is `WARNED`;
    when it is a restriction, the posture is `RESTRICTED`; when it is a suspension, the
    posture is `SUSPENDED`, with severity running warning first, then restriction, then
    suspension."

    Design: Corner/From Consistency Model/immediate_consistency_one_disapproval_is_fully_visible_before_any_sweep_runs
    """
    rule = fixtures.create_policy_rule(
        SEV_TWELVE,
        "REGULATED",
        12.00,
        title="Twelve point category",
        requires_disclaimer=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    advertiser_id = advertiser["id"]
    reviewer = fixtures.create_reviewer(
        ["STANDARD"],
        ["US"],
        display_name="R. Alvarez",
        max_concurrent_claims=3,
    )
    reviewer_id = reviewer["id"]
    creative, task = fixtures.creative_in_manual_review(
        advertiser_id,
        [SEV_TWELVE],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Twelve point offer",
        body_text="One offer whose disapproval must be visible immediately.",
        landing_page_url="https://www.beaconlending.example/twelve",
        display_url="https://www.beaconlending.example/twelve",
    )
    fixtures.claim_task(task["id"], reviewer_id)
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 1

    decided = fixtures.decide_task(
        task["id"],
        reviewer_id,
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Unsubstantiated savings claim",
    )
    # The decision response is itself the first read, and it is already final.
    assert decided["status"] == "RESOLVED"
    assert decided["resolution"] == "DISAPPROVE"

    notice = fixtures.only_notice_for_creative(creative["id"])
    assert notice["status"] == "ISSUED"
    assert notice["reason_codes"] == ["MANUAL_REVIEW"]
    assert notice["decided_by_reviewer_id"] == reviewer_id
    # 12.00 * 1.00 * 1.00 for the single MANUAL_REVIEW finding line.
    assert notice["assessed_points"] == pytest.approx(12.00, abs=0.01)
    assert notice["disclosed_points_total"] == pytest.approx(12.00, abs=0.01)
    assert_instant_equals(
        notice["appeal_deadline_at"], "2026-08-04T00:00:00Z", "appeal_deadline_at"
    )

    entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert len(entries) == 1
    assert entries[0]["entry_index"] == 1
    assert entries[0]["reason"] == "DISAPPROVAL_ASSESSED"
    assert entries[0]["source_notice_id"] == notice["id"]
    assert entries[0]["delta_points"] == pytest.approx(12.00, abs=0.01)
    assert entries[0]["balance_after"] == pytest.approx(12.00, abs=0.01)

    account = fixtures.read_advertiser(advertiser_id)
    assert account["violation_points_raw"] == pytest.approx(12.00, abs=0.01)
    assert account["violation_points_decayed"] == pytest.approx(12.00, abs=0.01)
    assert account["severity_index"] == pytest.approx(12.00, abs=0.01)
    assert account["account_status"] == "WARNED"

    actions, action_page = validate_paginated(
        api_client.list_enforcement_actions(ADMIN, {"advertiser_id": advertiser_id})
    )
    assert action_page["total_count"] == 1, "hop five did not run inside the request"
    assert actions[0]["action_type"] == "WARNING"
    assert actions[0]["origin"] == "SYSTEM_CASCADE"
    assert actions[0]["status"] == "ACTIVE"
    assert actions[0]["source_notice_id"] == notice["id"]
    assert_instant_equals(
        actions[0]["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
    )
    assert_instant_equals(
        actions[0]["effective_until"], "2026-08-31T00:00:00Z", "effective_until"
    )

    gated = fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)
    assert gated["review_status"] == "DISAPPROVED"
    assert gated["serving_eligible"] is False
    # A WARNED account still satisfies the enforcement conjunct, so only two codes land.
    assert gated["blocking_reason_codes"] == [
        "REVIEW_NOT_APPROVED",
        "DESTINATION_NOT_CLEARED",
    ]

    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 0
