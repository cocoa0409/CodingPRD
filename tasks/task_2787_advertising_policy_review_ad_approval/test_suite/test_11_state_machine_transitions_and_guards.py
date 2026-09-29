"""Where the state machines start, where they refuse to go, and what they drag along.

Each case pins one shape of the transition graph: the values a machine is seeded with,
a legal hop that moves two axes at once, an illegal hop that must not be mistaken for an
idempotent replay, a terminal state that admits nothing further, a guard that depends on
history rather than payload, and the cascades that reach sibling rows.
"""

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    make_advertiser_headers,
    make_reviewer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

SPIRITS = "ALC_SPIRITS"
FIN_CREDIT = "FIN_CREDIT"
GAM_CASINO = "GAM_CASINO"


def _fin_credit_rule(**overrides):
    """A REGULATED rule that routes to the STANDARD queue."""
    payload = {
        "title": "Consumer credit offers",
        "confidence_auto_disapprove_threshold": 0.90,
        "confidence_manual_threshold": 0.55,
        "review_sla_hours": 48,
        "default_queue": "STANDARD",
    }
    payload.update(overrides)
    return fixtures.create_policy_rule(FIN_CREDIT, "REGULATED", 4.00, **payload)


def _beacon_creative(advertiser_id, headline, body_text, slug):
    return fixtures.create_creative(
        advertiser_id,
        [FIN_CREDIT],
        ["US"],
        headline=headline,
        body_text=body_text,
        landing_page_url=f"https://www.beaconlending.example/{slug}",
        display_url=f"https://www.beaconlending.example/{slug}",
    )


def test_a_future_dated_licence_and_a_routed_task_start_in_their_declared_states():
    """PRD §3.5: "A certification is born with `status` `SUBMITTED` and a null
    `revocation_reason`, except that when the logical clock is already at or after
    `valid_from` and strictly before `valid_until` it is born `ACTIVE` outright."

    PRD §3.4: "A `ROUTED_MANUAL` outcome advances `SCREENING → PENDING_MANUAL_REVIEW`
    and creates exactly one review task in status `QUEUED`."

    PRD §3.6: "Task `status` runs over `QUEUED`, `CLAIMED`, `RESOLVED`, `ESCALATED` and
    `EXPIRED`, with `RESOLVED` and `EXPIRED` terminal; `resolution` starts at `PENDING`
    and may become `APPROVE`, `APPROVE_WITH_LIMITS`, `DISAPPROVE` or `ESCALATE`."

    PRD §3.6: "Start from a queue base of 30.00 for `STANDARD`, 45.00 for
    `REGULATED_CERT` and 60.00 for `POLITICAL`."

    PRD §3.6: "Add the queue base, the larger of the two components, the verification gap
    and the disclosure gap; round the total half-up to 2 decimals and cap it at 100.00."

    Design: Corner/From Table 2 (State Machines)/initial_state_routed_review_task_and_future_dated_certification_start_in_their_declared_states
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
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Northline Spirits LLC",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    advertiser_id = advertiser["id"]
    certification = fixtures.create_certification(
        advertiser_id,
        rule["id"],
        valid_from="2026-09-01T00:00:00Z",
        valid_until="2026-12-01T00:00:00Z",
        issuing_country_code="US",
        license_number="TTB-NL-2026-902",
        headers=make_advertiser_headers(advertiser_id),
    )
    # The window opens a month after the clock, so activation waits for the sweep.
    assert certification["status"] == "SUBMITTED"

    creative, run = fixtures.screened_creative(
        advertiser_id,
        [SPIRITS],
        [(rule["id"], 0.70)],
        ["US"],
        headline="Single barrel release",
        body_text="Our single barrel bourbon release is available for pre-order.",
        landing_page_url="https://www.northline.example/bourbon",
        display_url="https://www.northline.example/bourbon",
        disclaimer_text="Drink responsibly. 21+",
    )
    assert run["outcome"] == "ROUTED_MANUAL"
    # 6.00 * 1.00 * 0.70, with no country variation to lift the multiplier.
    assert run["provisional_risk_score"] == pytest.approx(4.20, abs=0.01)
    assert creative["review_status"] == "PENDING_MANUAL_REVIEW"
    assert creative["destination_status"] == "DESTINATION_PENDING"

    task = fixtures.only_task_for_creative(creative["id"])
    assert task["status"] == "QUEUED"
    assert task["resolution"] == "PENDING"
    assert task["assigned_reviewer_id"] is None
    assert task["claimed_at"] is None
    assert task["escalation_note"] is None
    assert task["cycle_count"] == 0
    assert task["version"] == 1
    assert task["queue"] == "REGULATED_CERT"
    assert task["primary_policy_rule_id"] == rule["id"]
    # 45.00 base + max(6.00 * 1.00 * 2.00, 0.00) + 0.00 + 0.00.
    assert task["priority_score"] == pytest.approx(57.00, abs=0.01)
    assert_instant_equals(
        task["sla_deadline_at"], "2026-08-03T00:00:00Z", "sla_deadline_at"
    )

    assert fixtures.read_certification(certification["id"])["status"] == "SUBMITTED"


def test_one_submit_call_advances_both_axes_with_a_single_version_increment():
    """PRD §3.3: "Submitting a creative for policy review is the owning advertiser's
    act, and it advances `DRAFT → SCREENING`."

    PRD §3.3: "As a side effect the destination axis moves `NOT_CHECKED →
    DESTINATION_PENDING` when it was still `NOT_CHECKED`, and the creative's `version`
    increments by 1 with `updated_at` refreshed."

    PRD §3.3: "Submission does not itself screen anything — screening arrives separately
    as an ingested classifier run."

    PRD §4: "Operations that modify an existing resource, including every state
    transition, every verification recording, the clock advance and the policy sweep,
    return `200 OK`."

    Design: Corner/From Table 2 (State Machines)/valid_transition_submit_advances_the_review_axis_and_the_destination_axis_together
    """
    _fin_credit_rule()
    advertiser_id = fixtures.create_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )["id"]
    creative = _beacon_creative(
        advertiser_id,
        "Balance transfer",
        "Move your balance and pay no interest for a year.",
        "transfer",
    )
    assert creative["version"] == 1

    submitted = validate_success(
        api_client.submit_ad_creative(
            creative["id"], make_advertiser_headers(advertiser_id)
        ),
        200,
    )
    assert submitted["review_status"] == "SCREENING"
    assert submitted["destination_status"] == "DESTINATION_PENDING"
    assert submitted["version"] == 2
    assert submitted["serving_eligible"] is False
    assert submitted["blocking_reason_codes"] == [
        "REVIEW_NOT_APPROVED",
        "DESTINATION_NOT_CLEARED",
    ]

    # Routing is the screening layer's job, so no task exists yet.
    assert fixtures.list_tasks_for_creative(creative["id"]) == []


def test_a_second_submit_is_a_state_refusal_and_not_an_idempotent_replay():
    """PRD §3.3: "Attempting submission from any `review_status` other than `DRAFT` is
    refused with `ERR_INVALID_CREATIVE_STATE` (HTTP 409); attempting it while the account
    is suspended is refused with `ERR_ADVERTISER_SUSPENDED`."

    PRD §2.10: "When one request breaks several rules, the server reports exactly one
    error — the one earliest in the following order — and performs no side effect
    whatsoever."

    Design: Corner/From Table 2 (State Machines)/invalid_transition_second_submit_on_a_screening_creative_returns_invalid_creative_state
    """
    _fin_credit_rule()
    advertiser_id = fixtures.create_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )["id"]
    creative = _beacon_creative(
        advertiser_id,
        "Balance transfer",
        "Move your balance and pay no interest for a year.",
        "transfer",
    )
    submitted = fixtures.submit_creative(creative["id"], advertiser_id)
    assert submitted["version"] == 2

    validate_error(
        api_client.submit_ad_creative(
            creative["id"], make_advertiser_headers(advertiser_id)
        ),
        ApiErrorId.ERR_INVALID_CREATIVE_STATE,
        409,
    )

    unchanged = fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)
    assert unchanged["version"] == submitted["version"] == 2
    assert unchanged["review_status"] == "SCREENING"
    assert unchanged["destination_status"] == "DESTINATION_PENDING"


def test_a_withdrawn_creative_admits_neither_submission_nor_revision_nor_withdrawal():
    """PRD §3.3: "Withdrawal is the advertiser's escape hatch and is available from every
    non-terminal review state: `DRAFT`, `SCREENING`, `PENDING_MANUAL_REVIEW`,
    `AUTO_APPROVED`, `APPROVED_LIMITED`, `DISAPPROVED` and `SUSPENDED_HOLD` all admit it,
    and it moves `review_status` to the terminal `WITHDRAWN`."

    PRD §3.3: "Only the owning advertiser may withdraw, and a withdrawal attempted on an
    already-`WITHDRAWN` creative reports `ERR_INVALID_CREATIVE_STATE`."

    PRD §3.3: "The owning advertiser may revise the creative, changing any of `headline`,
    `body_text`, `declared_category_codes`, `target_country_codes`, `landing_page_url`,
    `display_url`, `political_flag` and `disclaimer_text`, and a revision is admissible
    while `review_status` is either `DRAFT` or `DISAPPROVED` — from `DISAPPROVED` the
    revision returns the creative to `DRAFT`, closing the revision loop so that a
    corrected creative can be re-submitted and re-screened."

    Design: Corner/From Table 2 (State Machines)/terminal_state_lockdown_a_withdrawn_creative_rejects_submit_and_patch
    """
    _fin_credit_rule()
    advertiser_id = fixtures.create_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )["id"]
    headers = make_advertiser_headers(advertiser_id)
    creative = _beacon_creative(
        advertiser_id,
        "Refinance your loan",
        "Refinance your existing loan at a lower monthly payment.",
        "refi",
    )

    withdrawn = fixtures.withdraw_creative(creative["id"], advertiser_id)
    assert withdrawn["review_status"] == "WITHDRAWN"
    assert withdrawn["version"] == 2

    validate_error(
        api_client.submit_ad_creative(creative["id"], headers),
        ApiErrorId.ERR_INVALID_CREATIVE_STATE,
        409,
    )
    validate_error(
        api_client.revise_ad_creative(
            creative["id"],
            factories.revise_ad_creative_payload(headline="A different headline"),
            headers,
        ),
        ApiErrorId.ERR_INVALID_CREATIVE_STATE,
        409,
    )
    validate_error(
        api_client.withdraw_ad_creative(creative["id"], headers),
        ApiErrorId.ERR_INVALID_CREATIVE_STATE,
        409,
    )

    final = fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)
    assert final["review_status"] == "WITHDRAWN"
    assert final["headline"] == "Refinance your loan"
    # Three refusals, three no-ops.
    assert final["version"] == 2


def test_a_run_against_a_draft_creative_is_refused_on_state_and_not_on_the_pin():
    """PRD §3.4: "A run is admissible only while the creative's `review_status` is
    `SCREENING`; ingesting one against a `DRAFT` creative reports
    `ERR_INVALID_CREATIVE_STATE`."

    PRD §2.10: "State preconditions on the addressed resource — `ERR_INVALID_CREATIVE_STATE`,
    `ERR_INVALID_TASK_STATE`, `ERR_NOTICE_NOT_APPEALABLE`, `ERR_APPEAL_NOT_PENDING`,
    `ERR_INVALID_CERTIFICATION_STATE`."

    PRD §2.10: "Version pinning — `ERR_STALE_CREATIVE_VERSION`,
    `ERR_STALE_ADVERTISER_VERSION`."

    Design: Corner/From Table 2 (State Machines)/precondition_enforcement_screening_run_against_a_draft_creative_returns_invalid_creative_state
    """
    rule = _fin_credit_rule()
    advertiser_id = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )["id"]
    creative = _beacon_creative(
        advertiser_id,
        "Personal loan rates",
        "Compare personal loan rates from our lending desk.",
        "rates",
    )
    assert creative["review_status"] == "DRAFT"
    assert creative["version"] == 1

    validate_error(
        api_client.create_screening_run(
            creative["id"],
            factories.create_screening_run_payload(
                [factories.classifier_decision_payload(rule["id"], 0.70)],
                # Perfectly current, so nothing but the state can be at fault.
                creative["version"],
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_INVALID_CREATIVE_STATE,
        409,
    )

    assert fixtures.runs_for_creative(creative["id"]) == []
    untouched = fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)
    assert untouched["screening_run_count"] == 0
    assert untouched["review_status"] == "DRAFT"
    assert untouched["version"] == 1


def test_the_second_claim_on_a_held_task_is_refused_without_consuming_a_slot():
    """PRD §3.6: "A claim on a task that is not `QUEUED` reports `ERR_INVALID_TASK_STATE`
    (HTTP 409)."

    PRD §3.6: "A successful claim writes `assigned_reviewer_id` from `X-User-ID` and
    `claimed_at` from the logical clock, increments the reviewer's `claimed_task_count` by
    1 and the reviewer's `version` by 1, and increments the task's `version` by 1."

    PRD §2.9: "A reviewer's `claimed_task_count` tracks exactly how many of their tasks
    are currently held, and is conserved by the claim/release pair."

    Design: Corner/From Table 2 (State Machines)/idempotency_claiming_an_already_claimed_task_twice_returns_invalid_task_state
    """
    rule = _fin_credit_rule()
    advertiser_id = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )["id"]
    reviewer_id = fixtures.create_reviewer(
        ["STANDARD"],
        ["US"],
        display_name="Rev Standard US",
        max_concurrent_claims=3,
    )["id"]
    creative, task = fixtures.creative_in_manual_review(
        advertiser_id,
        [FIN_CREDIT],
        [(rule["id"], 0.70)],
        ["US"],
        headline="Debt consolidation",
        body_text="Consolidate your debt into one monthly payment.",
        landing_page_url="https://www.beaconlending.example/consolidate",
        display_url="https://www.beaconlending.example/consolidate",
    )
    claimed = fixtures.claim_task(task["id"], reviewer_id)
    assert claimed["status"] == "CLAIMED"
    assert claimed["version"] == 2

    validate_error(
        api_client.claim_review_task(task["id"], make_reviewer_headers(reviewer_id)),
        ApiErrorId.ERR_INVALID_TASK_STATE,
        409,
    )

    reviewer = fixtures.read_reviewer(reviewer_id)
    # The replay is not an idempotent no-op that re-bills the counter.
    assert reviewer["claimed_task_count"] == 1
    assert reviewer["version"] == 2

    still_held = fixtures.read_task(task["id"])
    assert still_held["status"] == "CLAIMED"
    assert still_held["assigned_reviewer_id"] == reviewer_id
    assert_instant_equals(
        still_held["claimed_at"], "2026-08-01T00:00:00Z", "claimed_at"
    )
    assert still_held["version"] == 2


def test_an_expiring_warning_row_pulls_the_account_posture_back_to_active():
    """PRD §3.2: "Account posture, held in `account_status`, is different in kind: it is
    never written directly but is derived — a pure function of the advertiser's enforcement
    actions that are currently in force."

    PRD §3.2: "Because the posture is recomputed from scratch after any change to any
    enforcement row, it can move any distance in either direction in a single
    re-derivation — `ACTIVE` straight to `SUSPENDED`, or `SUSPENDED` straight back to
    `ACTIVE` — and each such re-derivation increments the advertiser's `version` by 1."

    PRD §3.9: "An action is `EXPIRED` by the sweep's fifth phase once its `effective_until`
    has been reached or passed, which likewise re-derives `account_status` and bumps both
    versions."

    PRD §2.8: "The sweep reports a count for each phase: `activated_certifications`,
    `expired_certifications`, `expired_notices`, `expired_review_tasks`,
    `requeued_review_tasks`, `expired_enforcement_actions`, `lifted_enforcement_actions`,
    `released_hold_creatives` and `decay_refreshed_advertisers`."

    Design: Corner/From Table 2 (State Machines)/compound_shape_advertiser_account_status_is_rederived_when_its_enforcement_row_expires
    """
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    advertiser_id = advertiser["id"]
    # Born at 1, then one increment for each of the two verification recordings.
    assert advertiser["version"] == 3
    assert advertiser["account_status"] == "ACTIVE"

    action = fixtures.mint_enforcement_action(
        advertiser_id,
        "WARNING",
        advertiser["version"],
        trigger_reason="Manual warning issued after an offline audit.",
        effective_until="2026-08-05T00:00:00Z",
    )
    assert action["status"] == "ACTIVE"
    assert action["origin"] == "MANUAL"
    assert action["source_notice_id"] is None
    assert action["prior_action_id"] is None
    assert action["severity_index_at_issue"] == pytest.approx(0.00, abs=0.01)
    assert_instant_equals(
        action["effective_from"], "2026-08-01T00:00:00Z", "effective_from"
    )

    warned = fixtures.read_advertiser(advertiser_id)
    assert warned["account_status"] == "WARNED"
    assert warned["version"] == 4
    # The posture moved on an empty ledger, so no points were ever assessed.
    assert warned["violation_points_raw"] == pytest.approx(0.00, abs=0.01)

    counters = fixtures.advance_clock_and_sweep("2026-08-05T00:00:00Z")
    assert counters["expired_enforcement_actions"] == 1
    assert counters["lifted_enforcement_actions"] == 0

    assert fixtures.read_action(action["id"])["status"] == "EXPIRED"
    restored = fixtures.read_advertiser(advertiser_id)
    # The row left force, so the derived posture followed it back down.
    assert restored["account_status"] == "ACTIVE"
    assert restored["violation_points_raw"] == pytest.approx(0.00, abs=0.01)
    assert restored["violation_points_decayed"] == pytest.approx(0.00, abs=0.01)


def test_cloaking_needs_a_crawler_baseline_before_a_user_fetch_can_prove_it():
    """PRD §3.8: "Second, the result is `CLOAKING` with `mismatch_detail` `UA_DIVERGENCE`
    when this check's `user_agent_variant` is `USER`, a reference crawler check exists, and
    the host of that reference check's `fetched_final_url` differs from the host of this
    check's `fetched_final_url` — the classic bait-and-switch, where the crawler and the
    human are shown different destinations."

    PRD §3.8: "Third, the result is `MISMATCH` with `mismatch_detail` `HOST_MISMATCH` when
    the host of the check's `fetched_final_url` differs from the host of the creative's
    `display_url`, which is the declared reference host."

    PRD §3.8: "A `CLOAKING` result advances `DESTINATION_CLEARED → CLOAKING_CONFIRMED`,
    and that move additionally requires a prior `CRAWLER` check to exist on the creative —
    without a crawler baseline there is nothing for a `USER` fetch to diverge from."

    PRD §3.8: "A `MISMATCH` re-routes the review axis only when the creative was
    `AUTO_APPROVED` or `APPROVED_LIMITED`, in which case the creative moves to
    `PENDING_MANUAL_REVIEW` and gains one new `QUEUED` review task in the `STANDARD` queue
    with `cycle_count` 0."

    Design: Corner/From Table 2 (State Machines)/guarded_transition_cloaking_requires_a_prior_crawler_check_on_the_same_creative
    """
    rule = _fin_credit_rule()
    advertiser_id = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )["id"]
    creative, run = fixtures.screened_creative(
        advertiser_id,
        [FIN_CREDIT],
        [(rule["id"], 0.30)],
        ["US"],
        headline="Rate check tool",
        body_text="Check your personal loan rate without a hard credit pull.",
        landing_page_url="https://www.beaconlending.example/rate-check",
        display_url="https://www.beaconlending.example/rate-check",
    )
    assert run["outcome"] == "AUTO_APPROVED"
    creative_id = creative["id"]

    # A USER fetch with no crawler baseline cannot reach clause two, so it falls
    # through to the display-host comparison instead.
    first = fixtures.record_destination_check(
        creative_id,
        "https://promo.other-host.example/fixed",
        check_type="INITIAL",
        user_agent_variant="USER",
    )
    assert first["result"] == "MISMATCH"
    assert first["mismatch_detail"] == "HOST_MISMATCH"
    flagged = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert flagged["destination_status"] == "MISMATCH_FLAGGED"
    assert flagged["review_status"] == "PENDING_MANUAL_REVIEW"
    rerouted = fixtures.only_task_for_creative(creative_id)
    assert rerouted["status"] == "QUEUED"
    assert rerouted["queue"] == "STANDARD"
    assert rerouted["cycle_count"] == 0

    baseline = fixtures.record_destination_check(
        creative_id,
        "https://www.beaconlending.example/rate-check",
        check_type="RECHECK",
        user_agent_variant="CRAWLER",
    )
    assert baseline["result"] == "CLEARED"
    assert baseline["mismatch_detail"] is None
    cleared = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert cleared["destination_status"] == "DESTINATION_CLEARED"
    # The review axis is not touched by the destination clearing.
    assert cleared["review_status"] == "PENDING_MANUAL_REVIEW"

    # The identical divergent URL now has something to diverge from.
    proof = fixtures.record_destination_check(
        creative_id,
        "https://promo.other-host.example/fixed",
        check_type="RECHECK",
        user_agent_variant="USER",
    )
    assert proof["result"] == "CLOAKING"
    assert proof["mismatch_detail"] == "UA_DIVERGENCE"

    caught = fixtures.read_creative(creative_id, advertiser_id=advertiser_id)
    assert caught["destination_status"] == "CLOAKING_CONFIRMED"
    assert caught["review_status"] == "DISAPPROVED"
    assert fixtures.read_task(rerouted["id"])["status"] == "EXPIRED"

    notice = fixtures.only_notice_for_creative(creative_id)
    assert notice["reason_codes"] == ["CLOAKING"]
    assert notice["decided_by_reviewer_id"] is None
    # 10.00 integrity base * 1.00 strictest multiplier * 2.00, with no finding line
    # because the only classifier row was BELOW_THRESHOLD.
    assert notice["assessed_points"] == pytest.approx(20.00, abs=0.01)
    advertiser = fixtures.read_advertiser(advertiser_id)
    # 20.00 base with no closed action, plus the 3.50 tier chosen from 20.00.
    assert advertiser["severity_index"] == pytest.approx(23.50, abs=0.01)
    assert advertiser["account_status"] == "WARNED"


def test_withdrawing_a_creative_expires_the_held_task_and_frees_the_reviewer():
    """PRD §3.3: "Withdrawal expires every queued or claimed review task on the creative
    and decrements the `claimed_task_count` of each reviewer who was holding one,
    recomputes `serving_eligible` to false, and increments the creative's `version` by 1."

    PRD §3.6: "Task `status` runs over `QUEUED`, `CLAIMED`, `RESOLVED`, `ESCALATED` and
    `EXPIRED`, with `RESOLVED` and `EXPIRED` terminal; `resolution` starts at `PENDING` and
    may become `APPROVE`, `APPROVE_WITH_LIMITS`, `DISAPPROVE` or `ESCALATE`."

    PRD §2.11: "`REVIEW_NOT_APPROVED` — satisfied when `review_status` is either
    `AUTO_APPROVED` or `APPROVED_LIMITED`."

    Design: Corner/From Table 2 (State Machines)/cascade_down_withdrawing_a_creative_expires_its_claimed_task_and_frees_the_reviewer
    """
    rule = _fin_credit_rule()
    advertiser_id = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )["id"]
    reviewer_id = fixtures.create_reviewer(
        ["STANDARD"],
        ["US"],
        display_name="Rev Standard US",
        max_concurrent_claims=3,
    )["id"]
    creative, task = fixtures.creative_in_manual_review(
        advertiser_id,
        [FIN_CREDIT],
        [(rule["id"], 0.70)],
        ["US"],
        headline="Auto loan preapproval",
        body_text="Get preapproved for an auto loan before you visit the lot.",
        landing_page_url="https://www.beaconlending.example/auto",
        display_url="https://www.beaconlending.example/auto",
    )
    fixtures.claim_task(task["id"], reviewer_id)
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 1

    withdrawn = fixtures.withdraw_creative(creative["id"], advertiser_id)
    assert withdrawn["review_status"] == "WITHDRAWN"
    assert withdrawn["serving_eligible"] is False
    assert withdrawn["blocking_reason_codes"] == [
        "REVIEW_NOT_APPROVED",
        "DESTINATION_NOT_CLEARED",
    ]

    expired = fixtures.read_task(task["id"])
    assert expired["status"] == "EXPIRED"
    # Expiry is not a requeue, so the cycle counter never moved.
    assert expired["cycle_count"] == 0
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 0
    # Withdrawal is the advertiser's own act and assesses nothing.
    assert fixtures.list_notices_for_creative(creative["id"]) == []


def test_a_denied_appeal_leaves_the_ledger_and_the_disapproval_exactly_as_they_were():
    """PRD §3.9: "A `DENIED` outcome advances the appeal `SUBMITTED → DENIED` and moves
    the notice `APPEALED → APPEAL_UPHELD`, and it does deliberately less."

    PRD §3.9: "No ledger entry is written, the advertiser's `violation_points_raw` is
    unchanged, the creative stays `DISAPPROVED`, the destination axis is untouched,
    enforcement is untouched, and `reinstated_review_status` stays null."

    PRD §3.9: "Both branches write `decided_by_reviewer_id` and set `decided_at` to the
    logical clock, and both increment the appeal's `version` by 1."

    Design: Corner/From Table 2 (State Machines)/compensation_a_denied_appeal_leaves_the_disapproval_and_the_ledger_untouched
    """
    rule = fixtures.create_policy_rule(
        GAM_CASINO,
        "RESTRICTED",
        6.00,
        title="Casino gambling",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        review_sla_hours=48,
        default_queue="STANDARD",
    )
    advertiser_id = fixtures.create_verified_advertiser(
        legal_name="Riverbend Gaming LLC",
        country_code="US",
        industry_code="GAMING",
    )["id"]
    deciding_reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="Rev First Pass", max_concurrent_claims=2
    )
    appeals_reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="Rev Appeals Desk", max_concurrent_claims=2
    )
    creative, task = fixtures.creative_in_manual_review(
        advertiser_id,
        [GAM_CASINO],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Weekend slots tournament",
        body_text="Join our weekend slots tournament for a shot at the pot.",
        landing_page_url="https://www.riverbendgaming.example/slots",
        display_url="https://www.riverbendgaming.example/slots",
    )
    fixtures.claim_task(task["id"], deciding_reviewer["id"])
    fixtures.decide_task(
        task["id"],
        deciding_reviewer["id"],
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Gambling promotion without local licensing evidence.",
    )
    notice = fixtures.only_notice_for_creative(creative["id"])
    # 6.00 weight * 1.00 country multiplier * 1.00 MANUAL_REVIEW factor.
    assert notice["assessed_points"] == pytest.approx(6.00, abs=0.01)

    before = fixtures.read_advertiser(advertiser_id)
    assert before["violation_points_raw"] == pytest.approx(6.00, abs=0.01)
    assert before["severity_index"] == pytest.approx(6.00, abs=0.01)
    assert before["account_status"] == "ACTIVE"
    assert fixtures.actions_for_advertiser(advertiser_id) == []

    appeal = fixtures.file_appeal(
        notice["id"],
        advertiser_id,
        "We hold a state gaming license and can supply it on request.",
    )
    denied = fixtures.decide_appeal(
        appeal["id"],
        appeals_reviewer["id"],
        "DENIED",
        note="No licensing evidence was attached to the appeal.",
    )
    assert denied["status"] == "DENIED"
    assert denied["decided_by_reviewer_id"] == appeals_reviewer["id"]
    assert_instant_equals(
        denied["decided_at"], "2026-08-01T00:00:00Z", "decided_at"
    )
    assert denied["reinstated_review_status"] is None

    upheld = fixtures.read_notice(notice["id"])
    assert upheld["status"] == "APPEAL_UPHELD"
    assert upheld["assessed_points"] == pytest.approx(6.00, abs=0.01)

    after = fixtures.read_advertiser(advertiser_id)
    assert after["violation_points_raw"] == pytest.approx(6.00, abs=0.01)
    assert after["violation_points_decayed"] == pytest.approx(6.00, abs=0.01)
    assert after["severity_index"] == pytest.approx(6.00, abs=0.01)
    assert after["account_status"] == "ACTIVE"
    assert fixtures.actions_for_advertiser(advertiser_id) == []

    # No compensating row was written, so the single assessment stands alone.
    entries = fixtures.ledger_for_advertiser(advertiser_id)
    assert len(entries) == 1
    assert entries[0]["reason"] == "DISAPPROVAL_ASSESSED"
    assert entries[0]["delta_points"] == pytest.approx(6.00, abs=0.01)
    _rows, pagination = validate_paginated(
        api_client.list_notice_ledger_entries(notice["id"], ADMIN)
    )
    assert pagination["total_count"] == 1

    still_bad = fixtures.read_creative(creative["id"], advertiser_id=advertiser_id)
    assert still_bad["review_status"] == "DISAPPROVED"
    tasks = fixtures.list_tasks_for_creative(creative["id"])
    assert len(tasks) == 1, f"a denial mints no replacement task: {tasks}"
    assert tasks[0]["status"] == "RESOLVED"
