"""Two quantities that must come back to where they started, without erasing history.

An advertiser's point balance is walked up by a disapproval and back down by a granted
appeal, and the reversal has to be a second ledger row rather than the deletion of the
first. A reviewer's claim counter is walked up to its ceiling and back down by the two
compensating operations, and it must equal the number of tasks actually held after every
single step.
"""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    fixtures,
    make_reviewer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

WEAPONS = "WEAPONS_FIREARMS"
SUPPLEMENTS = "SUPPLEMENTS_CLAIMS"


# ---------------------------------------------------------------------------
# Shared setup for the ledger invariant
# ---------------------------------------------------------------------------
def _appealed_auto_disapproval():
    """A warned advertiser with an auto-issued notice under appeal.

    SE blocks firearms at multiplier 2.00, so screening at 0.95 auto-disapproves and
    assesses 12.00 * 2.00 * 0.80 = 19.20, which is enough for a WARNING. The notice was
    system-issued, so the appeals reviewer is not judging their own decision.
    """
    rule = fixtures.create_policy_rule(
        WEAPONS,
        "PROHIBITED",
        12.00,
        title="Weapons and firearms",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.50,
        review_sla_hours=24,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(
        rule["id"], "SE", "BLOCKED", severity_multiplier=2.00
    )
    fixtures.add_country_override(
        rule["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        severity_multiplier=1.00,
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Ridgeline Sporting Goods",
        country_code="US",
        industry_code="SPORTING_GOODS",
    )
    advertiser_id = advertiser["id"]
    reviewer = fixtures.create_reviewer(
        ["STANDARD"],
        ["SE", "US"],
        display_name="Rev Appeals Desk",
        max_concurrent_claims=2,
    )
    creative, run = fixtures.screened_creative(
        advertiser_id,
        [WEAPONS],
        [(rule["id"], 0.95)],
        ["SE", "US"],
        headline="Hunting season prep",
        body_text="Hunting season prep with rifles, optics and cases.",
        landing_page_url="https://www.ridgeline.example/prep",
        display_url="https://www.ridgeline.example/prep",
    )
    notice = fixtures.only_notice_for_creative(creative["id"])
    action = fixtures.actions_for_advertiser(advertiser_id)[0]
    appeal = fixtures.file_appeal(
        notice["id"],
        advertiser_id,
        "Swedish targeting was added by mistake and the campaign is US only.",
    )
    return {
        "advertiser_id": advertiser_id,
        "reviewer_id": reviewer["id"],
        "creative_id": creative["id"],
        "run": run,
        "notice": notice,
        "action": action,
        "appeal": appeal,
    }


def test_a_granted_appeal_reverses_the_balance_with_a_second_ledger_row():
    """PRD §3.9: "Entries are append-only and carry no status, so nothing is ever
    filtered out of a replay."

    PRD §3.8: "Hop two writes a compensating violation ledger entry with `reason`
    `APPEAL_REVERSAL` and `delta_points` equal to the negative of the notice's
    `assessed_points`."

    PRD §3.9: "an `entry_index` that is a 1-based per-advertiser insertion counter,
    contiguous, and that defines the chronological replay order"

    Design: Difficulty/compensating_invariant/granted_appeal_conserves_the_violation_point_balance_back_to_zero
    """
    case = _appealed_auto_disapproval()
    advertiser_id = case["advertiser_id"]

    assert case["run"]["outcome"] == "AUTO_DISAPPROVED"
    assert case["run"]["provisional_risk_score"] == pytest.approx(22.80, abs=0.01)
    assert case["notice"]["assessed_points"] == pytest.approx(19.20, abs=0.01)
    assert case["notice"]["decided_by_reviewer_id"] is None

    before_entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert len(before_entries) == 1
    assert before_entries[0]["entry_index"] == 1
    assert before_entries[0]["reason"] == "DISAPPROVAL_ASSESSED"
    assert before_entries[0]["delta_points"] == pytest.approx(19.20, abs=0.01)
    assert before_entries[0]["balance_after"] == pytest.approx(19.20, abs=0.01)

    before = fixtures.read_advertiser(advertiser_id)
    assert before["violation_points_raw"] == pytest.approx(19.20, abs=0.01)
    assert before["severity_index"] == pytest.approx(19.20, abs=0.01)
    assert before["account_status"] == "WARNED"
    assert case["action"]["action_type"] == "WARNING"
    assert case["action"]["status"] == "ACTIVE"

    fixtures.decide_appeal(
        case["appeal"]["id"],
        case["reviewer_id"],
        "GRANTED",
        note="Targeting corrected; reinstating for manual review.",
    )

    entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert len(entries) == 2, "the reversal is an insert, never a deletion"
    assert [entry["entry_index"] for entry in entries] == [1, 2]
    # The original row is untouched by the reversal.
    assert entries[0]["reason"] == "DISAPPROVAL_ASSESSED"
    assert entries[0]["delta_points"] == pytest.approx(19.20, abs=0.01)
    assert entries[0]["balance_after"] == pytest.approx(19.20, abs=0.01)
    assert entries[1]["reason"] == "APPEAL_REVERSAL"
    assert entries[1]["delta_points"] == pytest.approx(-19.20, abs=0.01)
    assert entries[1]["balance_after"] == pytest.approx(0.00, abs=0.01)
    assert entries[1]["source_notice_id"] == case["notice"]["id"]

    after = fixtures.read_advertiser(advertiser_id)
    assert after["violation_points_raw"] == pytest.approx(0.00, abs=0.01)
    assert after["violation_points_decayed"] == pytest.approx(0.00, abs=0.01)
    assert after["severity_index"] == pytest.approx(0.00, abs=0.01)


def test_the_lifted_warning_survives_the_grant_as_a_row_and_the_creative_returns():
    """PRD §3.8: "Hop four moves any enforcement action currently in force to `LIFTED`
    when the refreshed `severity_index` has fallen below the threshold of that action's
    own `action_type`, re-deriving `account_status`."

    PRD §3.8: "The reinstatement resets `destination_status` to `DESTINATION_PENDING`
    when it stood at `MISMATCH_FLAGGED` or `CLOAKING_CONFIRMED`, rewrites
    `risk_score_final` with a destination penalty of 0.00, and writes
    `PENDING_MANUAL_REVIEW` into the appeal's `reinstated_review_status`."

    PRD §3.8: "It also creates one fresh review task in status `QUEUED` with
    `cycle_count` 0, copying its `queue` and `primary_policy_rule_id` from the creative's
    most recently created review task whatever that task's status, ranked by `created_at`
    descending, and defaulting to the `STANDARD` queue with a null
    `primary_policy_rule_id` when the creative has no review task at all"

    Design: Difficulty/compensating_invariant/granted_appeal_conserves_the_violation_point_balance_back_to_zero
    """
    case = _appealed_auto_disapproval()
    advertiser_id = case["advertiser_id"]

    granted = fixtures.decide_appeal(
        case["appeal"]["id"],
        case["reviewer_id"],
        "GRANTED",
        note="Targeting corrected; reinstating for manual review.",
    )
    assert granted["status"] == "GRANTED"
    assert granted["decided_by_reviewer_id"] == case["reviewer_id"]
    assert granted["reinstated_review_status"] == "PENDING_MANUAL_REVIEW"

    # The action is lifted, not removed: the audit row stays on the account.
    actions = fixtures.actions_for_advertiser(advertiser_id)
    assert len(actions) == 1
    assert actions[0]["id"] == case["action"]["id"]
    assert actions[0]["status"] == "LIFTED"
    assert fixtures.read_advertiser(advertiser_id)["account_status"] == "ACTIVE"

    assert (
        fixtures.read_notice(case["notice"]["id"])["status"] == "APPEAL_GRANTED"
    )

    creative = fixtures.read_creative(
        case["creative_id"], advertiser_id=advertiser_id
    )
    assert creative["review_status"] == "PENDING_MANUAL_REVIEW"
    # It was never flagged, so the destination reset is a no-op.
    assert creative["destination_status"] == "DESTINATION_PENDING"

    tasks = fixtures.list_tasks_for_creative(case["creative_id"])
    assert len(tasks) == 1, f"the auto-disapproval never minted one: {tasks}"
    assert tasks[0]["status"] == "QUEUED"
    assert tasks[0]["cycle_count"] == 0
    # No earlier task existed to copy from, so both fields take their defaults.
    assert tasks[0]["queue"] == "STANDARD"
    assert tasks[0]["primary_policy_rule_id"] is None


# ---------------------------------------------------------------------------
# Shared setup for the claim-counter invariant
# ---------------------------------------------------------------------------
def _three_queued_tasks_and_one_reviewer_of_two():
    """Three QUEUED STANDARD tasks and one reviewer whose ceiling is 2."""
    rule = fixtures.create_policy_rule(
        SUPPLEMENTS,
        "REGULATED",
        4.02,
        title="Supplement health claims",
        requires_certification=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.50,
        review_sla_hours=48,
        default_queue="STANDARD",
    )
    fixtures.add_country_override(
        rule["id"], "DE", "ALLOWED_WITH_DISCLAIMER", severity_multiplier=1.15
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Alpenkraft Nutrition GmbH",
        country_code="DE",
        industry_code="SUPPLEMENTS",
    )
    advertiser_id = advertiser["id"]
    reviewer = fixtures.create_reviewer(
        ["STANDARD"],
        ["DE"],
        display_name="Rev Capacity Two",
        max_concurrent_claims=2,
    )
    specs = [
        ("Daily greens one", "Daily greens powder for steady energy.", "1"),
        ("Daily greens two", "Second daily greens blend with extra fibre.", "2"),
        ("Daily greens three", "Third daily greens pack with citrus flavour.", "3"),
    ]
    tasks = []
    creatives = []
    for headline, body, slug in specs:
        creative, task = fixtures.creative_in_manual_review(
            advertiser_id,
            [SUPPLEMENTS],
            [(rule["id"], 0.60)],
            ["DE"],
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.alpenkraft.example/{slug}",
            display_url=f"https://www.alpenkraft.example/{slug}",
        )
        creatives.append(creative)
        tasks.append(task)
    return {
        "advertiser_id": advertiser_id,
        "reviewer_id": reviewer["id"],
        "creatives": creatives,
        "tasks": tasks,
    }


def _claimed_task_count(reviewer_id):
    """The number of tasks actually sitting in CLAIMED for this reviewer."""
    _rows, pagination = validate_paginated(
        api_client.list_review_tasks(
            ADMIN, {"assigned_reviewer_id": reviewer_id, "status": "CLAIMED"}
        )
    )
    return pagination["total_count"]


def test_the_ceiling_is_rechecked_against_the_live_counter_after_a_release():
    """PRD §3.6: "Capacity comes last: the reviewer's `claimed_task_count` must be
    strictly less than their `max_concurrent_claims`, and a reviewer already at their
    ceiling is refused with `ERR_REVIEWER_CAPACITY_EXCEEDED` (HTTP 409) — an aggregate
    check, in that each held task is individually legal while the collection may not
    exceed the ceiling."

    PRD §3.6: "Releasing is the exact compensating action for claiming and advances
    `CLAIMED → QUEUED`."

    PRD §3.6: "Release deliberately does *not* recompute `priority_score` or
    `sla_deadline_at` — the task returns to its queue holding the position and the
    deadline it already had, so releasing is not a way to buy time."

    Design: Difficulty/compensating_invariant/release_and_escalate_conserve_the_reviewer_claim_slot_counter
    """
    case = _three_queued_tasks_and_one_reviewer_of_two()
    reviewer_id = case["reviewer_id"]
    t1, t2, t3 = case["tasks"]

    fixtures.claim_task(t1["id"], reviewer_id)
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 1
    assert _claimed_task_count(reviewer_id) == 1

    fixtures.claim_task(t2["id"], reviewer_id)
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 2
    assert _claimed_task_count(reviewer_id) == 2

    validate_error(
        api_client.claim_review_task(t3["id"], make_reviewer_headers(reviewer_id)),
        ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED,
        409,
    )
    refused = fixtures.read_task(t3["id"])
    assert refused["status"] == "QUEUED"
    assert refused["assigned_reviewer_id"] is None
    # The failure consumed no slot.
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 2

    fixtures.release_task(t1["id"], reviewer_id)
    released = fixtures.read_task(t1["id"])
    assert released["status"] == "QUEUED"
    assert released["assigned_reviewer_id"] is None
    assert released["claimed_at"] is None
    assert released["cycle_count"] == 0
    # A release is not a requeue, so the queue position and deadline stand.
    assert released["priority_score"] == pytest.approx(t1["priority_score"], abs=0.01)
    assert released["sla_deadline_at"] == t1["sla_deadline_at"]
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 1

    validate_success(
        api_client.claim_review_task(t3["id"], make_reviewer_headers(reviewer_id))
    )
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 2
    assert _claimed_task_count(reviewer_id) == 2


def test_escalating_returns_the_slot_without_disturbing_the_creative():
    """PRD §3.6: "Choosing the `ESCALATE` resolution requires the task to be `CLAIMED`
    and held by the acting reviewer; it advances `CLAIMED → ESCALATED`, records
    `resolution` `ESCALATE`, writes the supplied `note` into `escalation_note`, clears
    `assigned_reviewer_id` and `claimed_at`, decrements the holder's `claimed_task_count`
    by 1 and increments the reviewer's `version` by 1, and increments the task's `version`
    by 1."

    PRD §3.6: "The creative keeps its `review_status` of `PENDING_MANUAL_REVIEW` and its
    `version` is *not* incremented, because nothing about the creative changed."

    Design: Difficulty/compensating_invariant/release_and_escalate_conserve_the_reviewer_claim_slot_counter
    """
    case = _three_queued_tasks_and_one_reviewer_of_two()
    reviewer_id = case["reviewer_id"]
    t1, t2, t3 = case["tasks"]

    fixtures.claim_task(t1["id"], reviewer_id)
    fixtures.claim_task(t2["id"], reviewer_id)
    fixtures.release_task(t1["id"], reviewer_id)
    fixtures.claim_task(t3["id"], reviewer_id)

    creative_version_before = fixtures.read_creative(
        case["creatives"][1]["id"], advertiser_id=case["advertiser_id"]
    )["version"]

    escalated = fixtures.decide_task(
        t2["id"],
        reviewer_id,
        "ESCALATE",
        note="Sending the health claim to the medical desk.",
    )
    assert escalated["status"] == "ESCALATED"
    assert escalated["resolution"] == "ESCALATE"
    assert escalated["assigned_reviewer_id"] is None
    assert escalated["claimed_at"] is None
    assert escalated["escalation_note"] == (
        "Sending the health claim to the medical desk."
    )

    creative = fixtures.read_creative(
        case["creatives"][1]["id"], advertiser_id=case["advertiser_id"]
    )
    assert creative["review_status"] == "PENDING_MANUAL_REVIEW"
    assert creative["version"] == creative_version_before

    # One slot returned by the release, one by the escalation, one still held.
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 1
    assert _claimed_task_count(reviewer_id) == 1
    assert fixtures.read_task(t1["id"])["status"] == "QUEUED"
    assert fixtures.read_task(t3["id"])["status"] == "CLAIMED"
