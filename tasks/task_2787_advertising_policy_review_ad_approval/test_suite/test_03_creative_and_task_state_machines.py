"""Two state machines that are not straight lines.

A creative carries two axes on one row that advance on different triggers, and its
destination axis can return to a value it already left. A review task is outright
cyclic, and every lap through the loop is counted and re-scored. Both machines are
driven around their loops here so that a single-axis or linear implementation is
visible.
"""

import pytest

from test_helpers import (
    assert_instant_equals,
    fixtures,
)

SPIRITS = "ALC_SPIRITS"
FIN_CREDIT = "FIN_CREDIT"


# ---------------------------------------------------------------------------
# Shared setup for the two-axes pair
# ---------------------------------------------------------------------------
def _creative_awaiting_manual_review():
    """A US spirits creative parked in PENDING_MANUAL_REVIEW at DESTINATION_PENDING.

    The US variation multiplies severity by 1.50, so screening at confidence 0.80
    publishes 6.00 * 1.50 * 0.80 = 7.20 on both scores while the destination axis is
    still untouched evidence.
    """
    rule = fixtures.create_policy_rule(
        SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
        requires_disclaimer=True,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.55,
        review_sla_hours=48,
        default_queue="REGULATED_CERT",
    )
    fixtures.add_country_override(
        rule["id"],
        "US",
        "RESTRICTED_CERT_REQUIRED",
        requires_license=True,
        requires_disclaimer=True,
        severity_multiplier=1.50,
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="North Harbor Spirits LLC",
        country_code="US",
        industry_code="ALCOHOL",
    )
    reviewer = fixtures.create_reviewer(
        ["REGULATED_CERT"],
        ["US"],
        display_name="Rev Regulated US",
        max_concurrent_claims=2,
    )
    creative, _run = fixtures.screened_creative(
        advertiser["id"],
        [SPIRITS],
        [(rule["id"], 0.80)],
        ["US"],
        headline="Single malt tasting flight",
        body_text="Reserve a single malt tasting flight this weekend.",
        landing_page_url="https://www.northharbor.example/tasting",
        display_url="https://www.northharbor.example/tasting",
        disclaimer_text="Drink responsibly. 21+",
    )
    assert creative["review_status"] == "PENDING_MANUAL_REVIEW"
    assert creative["destination_status"] == "DESTINATION_PENDING"
    assert creative["risk_score_provisional"] == pytest.approx(7.20, abs=0.01)
    assert creative["risk_score_final"] == pytest.approx(7.20, abs=0.01)
    return {
        "rule": rule,
        "advertiser_id": advertiser["id"],
        "reviewer_id": reviewer["id"],
        "creative_id": creative["id"],
        "task": fixtures.only_task_for_creative(creative["id"]),
    }


def test_the_destination_axis_cycles_while_the_review_axis_stands_still():
    """PRD §3.8: "The destination axis is therefore genuinely cyclic: a destination
    that was cleared can be caught mismatching later and cleared again afterwards, any
    number of times."

    PRD §3.8: "A creative already sitting in `PENDING_MANUAL_REVIEW` keeps the review
    task it already has and gains no second one, and a creative in `DISAPPROVED` or
    `SUSPENDED_HOLD` has its review axis left alone entirely."

    PRD §3.8: "Every one of these moves rewrites `risk_score_final` with the
    destination penalty appropriate to the new `destination_status` — 15.00 once
    `MISMATCH_FLAGGED`, 40.00 once `CLOAKING_CONFIRMED`, and 0.00 once
    `DESTINATION_CLEARED` — recomputes `serving_eligible` and `blocking_reason_codes`,
    and increments the creative's `version` by 1."

    Design: Difficulty/non_linear_state_machine/ad_creative_two_axes_advance_independently_with_destination_cycle
    """
    case = _creative_awaiting_manual_review()
    creative_id = case["creative_id"]
    advertiser_id = case["advertiser_id"]

    first = fixtures.record_destination_check(
        creative_id,
        "https://promo-partner.example/lp/whisky",
        check_type="INITIAL",
        user_agent_variant="CRAWLER",
    )
    assert first["result"] == "MISMATCH"
    assert first["mismatch_detail"] == "HOST_MISMATCH"

    flagged = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert flagged["destination_status"] == "MISMATCH_FLAGGED"
    assert flagged["review_status"] == "PENDING_MANUAL_REVIEW"
    assert flagged["risk_score_final"] == pytest.approx(22.20, abs=0.01)
    assert flagged["risk_score_provisional"] == pytest.approx(7.20, abs=0.01)
    tasks = fixtures.list_tasks_for_creative(creative_id)
    assert len(tasks) == 1, f"a mismatch must not mint a second task: {tasks}"
    assert tasks[0]["status"] == "QUEUED"
    assert tasks[0]["cycle_count"] == 0

    second = fixtures.record_destination_check(
        creative_id,
        "https://www.northharbor.example/tasting",
        check_type="RECHECK",
        user_agent_variant="CRAWLER",
    )
    assert second["result"] == "CLEARED"
    assert second["mismatch_detail"] is None

    cleared = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert cleared["destination_status"] == "DESTINATION_CLEARED"
    assert cleared["review_status"] == "PENDING_MANUAL_REVIEW"
    assert cleared["risk_score_final"] == pytest.approx(7.20, abs=0.01)
    assert len(fixtures.list_tasks_for_creative(creative_id)) == 1


def test_a_plain_approval_moves_only_the_review_axis():
    """PRD §3.3: "The creative lifecycle runs on two independent axes that live on the
    same row."

    PRD §3.7: "`APPROVE` advances `PENDING_MANUAL_REVIEW → AUTO_APPROVED`."

    PRD §3.7: "On success the task becomes `RESOLVED` with `resolution` `APPROVE`, a
    political creative gains exactly one archive entry, and the creative's
    `risk_score_final`, `serving_eligible` and `blocking_reason_codes` are recomputed
    before its `version` increments by 1."

    Design: Difficulty/non_linear_state_machine/ad_creative_two_axes_advance_independently_with_destination_cycle
    """
    case = _creative_awaiting_manual_review()
    creative_id = case["creative_id"]
    advertiser_id = case["advertiser_id"]
    reviewer_id = case["reviewer_id"]

    fixtures.record_destination_check(
        creative_id,
        "https://promo-partner.example/lp/whisky",
        check_type="INITIAL",
        user_agent_variant="CRAWLER",
    )
    fixtures.record_destination_check(
        creative_id,
        "https://www.northharbor.example/tasting",
        check_type="RECHECK",
        user_agent_variant="CRAWLER",
    )

    fixtures.claim_task(case["task"]["id"], reviewer_id)
    fixtures.decide_task(
        case["task"]["id"],
        reviewer_id,
        "APPROVE",
        note="Disclaimer present and destination verified.",
    )

    approved = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert approved["review_status"] == "AUTO_APPROVED"
    # The approval touched the review axis only; the destination axis kept its value.
    assert approved["destination_status"] == "DESTINATION_CLEARED"
    assert approved["serving_eligible"] is True
    assert approved["blocking_reason_codes"] == []

    task = fixtures.read_task(case["task"]["id"])
    assert task["status"] == "RESOLVED"
    assert task["resolution"] == "APPROVE"
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 0


# ---------------------------------------------------------------------------
# Shared setup for the task-cycle pair
# ---------------------------------------------------------------------------
def _claimed_credit_task():
    """A REGULATED_CERT task claimed on 2026-08-02, scored while unverified.

    The advertiser is verified only *after* the task exists, so the requeue's re-score
    has a strictly different input than the original routing had.
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        8.00,
        title="Consumer credit offers",
        requires_certification=True,
        requires_disclaimer=True,
        confidence_auto_disapprove_threshold=0.85,
        confidence_manual_threshold=0.40,
        review_sla_hours=72,
        default_queue="REGULATED_CERT",
    )
    fixtures.add_country_override(
        rule["id"], "US", "ALLOWED_WITH_DISCLAIMER", severity_multiplier=1.20
    )
    advertiser = fixtures.create_advertiser(
        legal_name="Pinebrook Lending Co",
        country_code="US",
        industry_code="CONSUMER_CREDIT",
    )
    advertiser_id = advertiser["id"]
    reviewer = fixtures.create_reviewer(
        ["REGULATED_CERT"],
        ["US"],
        display_name="Rev Regulated US",
        max_concurrent_claims=2,
    )
    creative, run = fixtures.screened_creative(
        advertiser_id,
        [FIN_CREDIT],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Refinance in one day",
        body_text="Refinance your balance in one business day with fixed rates.",
        landing_page_url="https://www.pinebrook.example/refi",
        display_url="https://www.pinebrook.example/refi",
        disclaimer_text="APR 9.9%-24.9%. Terms apply.",
    )
    task = fixtures.only_task_for_creative(creative["id"])
    fixtures.verify_advertiser_core_axes(advertiser_id)
    fixtures.set_clock("2026-08-02T00:00:00Z")
    fixtures.claim_task(task["id"], reviewer["id"])
    return {
        "rule": rule,
        "advertiser_id": advertiser_id,
        "reviewer_id": reviewer["id"],
        "creative_id": creative["id"],
        "run": run,
        "task": task,
    }


def test_the_requeue_loop_counts_its_laps_and_rescores_against_current_state():
    """PRD §3.6: "This closes the loop `QUEUED → CLAIMED → ESCALATED → QUEUED`;
    `cycle_count` counts the laps and is never reset."

    PRD §3.6: "Requeueing increments `cycle_count` by 1, resets `resolution` to
    `PENDING`, recomputes `priority_score` against the advertiser's *current* state
    rather than the state at original routing, recomputes `sla_deadline_at` as the
    logical clock plus the primary rule's `review_sla_hours`, and increments the task's
    `version` by 1."

    Design: Difficulty/non_linear_state_machine/review_task_claim_escalate_requeue_cycle_increments_counter_and_rescores
    """
    case = _claimed_credit_task()
    task_id = case["task"]["id"]

    # At routing: 45.00 REGULATED_CERT base + max(8.00 * 1.20 * 2.00, 0.00) + 10.00.
    assert case["task"]["queue"] == "REGULATED_CERT"
    assert case["task"]["primary_policy_rule_id"] == case["rule"]["id"]
    assert case["task"]["cycle_count"] == 0
    assert case["task"]["priority_score"] == pytest.approx(74.20, abs=0.01)
    assert case["run"]["provisional_risk_score"] == pytest.approx(4.80, abs=0.01)

    fixtures.decide_task(
        task_id,
        case["reviewer_id"],
        "ESCALATE",
        note="Needs licensing desk confirmation.",
    )
    escalated = fixtures.read_task(task_id)
    assert escalated["status"] == "ESCALATED"
    assert escalated["resolution"] == "ESCALATE"
    assert escalated["assigned_reviewer_id"] is None
    assert escalated["claimed_at"] is None
    assert escalated["cycle_count"] == 0
    assert fixtures.read_reviewer(case["reviewer_id"])["claimed_task_count"] == 0
    assert (
        fixtures.read_creative(
            case["creative_id"], advertiser_id=case["advertiser_id"]
        )["review_status"]
        == "PENDING_MANUAL_REVIEW"
    )

    fixtures.requeue_task(task_id)
    requeued = fixtures.read_task(task_id)
    assert requeued["status"] == "QUEUED"
    assert requeued["cycle_count"] == 1
    assert requeued["resolution"] == "PENDING"
    # Both axes are VERIFIED now, so the 10.00 verification gap has closed.
    assert requeued["priority_score"] == pytest.approx(64.20, abs=0.01)
    assert requeued["priority_score"] != pytest.approx(74.20, abs=0.01)


def test_the_requeue_rebases_the_deadline_on_the_current_clock():
    """PRD §3.6: "An escalated task returns to circulation only when a `PolicyAdmin`
    requeues it, which advances `ESCALATED → QUEUED` and requires both that the task is
    `ESCALATED` and that the creative is still in `PENDING_MANUAL_REVIEW`."

    PRD §3.6: "A successful claim writes `assigned_reviewer_id` from `X-User-ID` and
    `claimed_at` from the logical clock, increments the reviewer's `claimed_task_count`
    by 1 and the reviewer's `version` by 1, and increments the task's `version` by 1."

    Design: Difficulty/non_linear_state_machine/review_task_claim_escalate_requeue_cycle_increments_counter_and_rescores
    """
    case = _claimed_credit_task()
    task_id = case["task"]["id"]

    # Routed at midnight on 2026-08-01 with a 72-hour SLA.
    assert_instant_equals(
        case["task"]["sla_deadline_at"], "2026-08-04T00:00:00Z", "sla_deadline_at"
    )

    fixtures.decide_task(
        task_id,
        case["reviewer_id"],
        "ESCALATE",
        note="Needs licensing desk confirmation.",
    )
    fixtures.requeue_task(task_id)
    requeued = fixtures.read_task(task_id)
    # Rebased on the 2026-08-02 clock, not on the original creation instant.
    assert_instant_equals(
        requeued["sla_deadline_at"], "2026-08-05T00:00:00Z", "sla_deadline_at"
    )

    fixtures.claim_task(task_id, case["reviewer_id"])
    reclaimed = fixtures.read_task(task_id)
    assert reclaimed["status"] == "CLAIMED"
    assert reclaimed["assigned_reviewer_id"] == case["reviewer_id"]
    assert_instant_equals(
        reclaimed["claimed_at"], "2026-08-02T00:00:00Z", "claimed_at"
    )
    assert reclaimed["cycle_count"] == 1
    assert fixtures.read_reviewer(case["reviewer_id"])["claimed_task_count"] == 1
