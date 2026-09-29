"""What each endpoint promises to change, and what it promises to leave alone.

A reviewer amendment narrows who may claim tomorrow without touching what is held today.
A requeue is admissible from exactly one state, so firing it from the other three has to
be three refusals with no drift. An appeal resolves both of the rows it links before it
writes either of them. Three read endpoints have to agree on a single four-point
disapproval. And the sweep, the only call that moves many rows at once, has to report
nine zeros while nothing is due and then exactly the phases that fired once the clock has
moved past everything.
"""

import pytest

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
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

FIN_CREDIT = "FIN_CREDIT"
ALC_SPIRITS = "ALC_SPIRITS"


# ---------------------------------------------------------------------------
# Shared setup for the reviewer amendment
# ---------------------------------------------------------------------------
def _two_standard_tasks_and_a_reviewer_at_its_defaults():
    """Two QUEUED STANDARD tasks and one reviewer created without any ceiling given.

    FIN_CREDIT needs no licence and no disclaimer, so a 0.50 confidence lands between the
    0.20 manual threshold and the 0.90 auto threshold and routes each creative into the
    STANDARD queue with nothing else to satisfy.
    """
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R. Alvarez"
    )
    tasks = []
    for headline, body, slug in (
        ("Offer one", "The first credit offer routed into the standard queue.", "one"),
        ("Offer two", "The second credit offer routed into the standard queue.", "two"),
    ):
        _creative, task = fixtures.creative_in_manual_review(
            advertiser["id"],
            [FIN_CREDIT],
            [(rule["id"], 0.50)],
            ["US"],
            headline=headline,
            body_text=body,
            landing_page_url=f"https://www.beaconlending.example/{slug}",
            display_url=f"https://www.beaconlending.example/{slug}",
        )
        tasks.append(task)
    return {"reviewer": reviewer, "tasks": tasks}


def test_taking_a_reviewer_offline_leaves_the_task_they_already_hold_alone():
    """PRD §3.6: "A reviewer carries a `display_name` of 1 to 120 characters that appears
    on notices and audit trails, a non-empty `queue_specialties` array of distinct values
    drawn from `STANDARD`, `REGULATED_CERT` and `POLITICAL` naming the queues they may
    pull from, a non-empty `country_authorizations` array of distinct two-letter uppercase
    codes naming the countries they are competent to adjudicate, and
    `max_concurrent_claims`, an integer from 1 to 10 defaulting to 3 that ceilings how
    many tasks they may hold at once."

    PRD §3.6: "A new reviewer begins with `claimed_task_count` at 0 and `status`
    `ACTIVE`; the only other availability value is `OFFLINE`."

    PRD §3.6: "A `PolicyAdmin` may later amend `status`, `max_concurrent_claims`,
    `queue_specialties` or `country_authorizations`, which increments the reviewer's
    `version` by 1; narrowing specialties or authorizations does not release tasks the
    reviewer already holds, so a reviewer can legitimately finish work they could no
    longer claim today."

    PRD §3.6: "Availability comes second: the reviewer's `status` must be `ACTIVE`, and
    an `OFFLINE` reviewer is refused with `ERR_REVIEWER_OFFLINE` (HTTP 409)."

    Design: Corner/From Table 5 (Endpoints)/standard_crud_reviewer_patch_changes_availability_without_disturbing_held_tasks
    """
    case = _two_standard_tasks_and_a_reviewer_at_its_defaults()
    reviewer = case["reviewer"]
    reviewer_id = reviewer["id"]
    held, other = case["tasks"]

    # Nothing in the create payload named a ceiling or an availability.
    assert reviewer["max_concurrent_claims"] == 3
    assert reviewer["status"] == "ACTIVE"
    assert reviewer["claimed_task_count"] == 0
    assert reviewer["version"] == 1

    fixtures.claim_task(held["id"], reviewer_id)
    after_claim = fixtures.read_reviewer(reviewer_id)
    assert after_claim["claimed_task_count"] == 1
    assert after_claim["version"] == 2

    amended = fixtures.patch_reviewer(
        reviewer_id,
        status="OFFLINE",
        max_concurrent_claims=1,
        queue_specialties=["POLITICAL"],
    )
    assert amended["status"] == "OFFLINE"
    assert amended["max_concurrent_claims"] == 1
    assert amended["queue_specialties"] == ["POLITICAL"]
    assert amended["version"] == 3
    # The amendment would have made the standing claim impossible, and yet:
    assert amended["claimed_task_count"] == 1

    still_held = fixtures.read_task(held["id"])
    assert still_held["status"] == "CLAIMED"
    assert still_held["assigned_reviewer_id"] == reviewer_id

    # The next claim breaches availability, speciality and the new ceiling at once.
    validate_error(
        api_client.claim_review_task(
            other["id"], make_reviewer_headers(reviewer_id)
        ),
        ApiErrorId.ERR_REVIEWER_OFFLINE,
        409,
    )
    assert fixtures.read_task(other["id"])["status"] == "QUEUED"
    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 1


# ---------------------------------------------------------------------------
# Shared setup for the single-task endpoint walks
# ---------------------------------------------------------------------------
def _a_queued_standard_task():
    """One QUEUED STANDARD task on a verified account, with a reviewer able to take it."""
    rule = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Beacon Lending Co",
        country_code="US",
        industry_code="CONSUMER_FINANCE",
    )
    reviewer = fixtures.create_reviewer(
        ["STANDARD"], ["US"], display_name="R. Alvarez", max_concurrent_claims=3
    )
    creative, task = fixtures.creative_in_manual_review(
        advertiser["id"],
        [FIN_CREDIT],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Single offer",
        body_text="One offer that walks a single task through the endpoints.",
        landing_page_url="https://www.beaconlending.example/one",
        display_url="https://www.beaconlending.example/one",
    )
    return {
        "rule_id": rule["id"],
        "advertiser_id": advertiser["id"],
        "reviewer_id": reviewer["id"],
        "creative_id": creative["id"],
        "task": task,
    }


def test_requeue_is_refused_from_queued_from_claimed_and_from_resolved():
    """PRD §3.6: "An escalated task returns to circulation only when a `PolicyAdmin`
    requeues it, which advances `ESCALATED → QUEUED` and requires both that the task is
    `ESCALATED` and that the creative is still in `PENDING_MANUAL_REVIEW`."

    PRD §3.6: "Requeueing increments `cycle_count` by 1, resets `resolution` to
    `PENDING`, recomputes `priority_score` against the advertiser's *current* state rather
    than the state at original routing, recomputes `sla_deadline_at` as the logical clock
    plus the primary rule's `review_sla_hours`, and increments the task's `version` by 1."

    PRD §3.6: "A requeue attempted on a task that is not `ESCALATED` reports
    `ERR_INVALID_TASK_STATE`."

    Design: Corner/From Table 5 (Endpoints)/conditional_action_requeue_is_rejected_from_queued_claimed_and_resolved
    """
    case = _a_queued_standard_task()
    task_id = case["task"]["id"]
    reviewer_id = case["reviewer_id"]

    # From QUEUED.
    validate_error(
        api_client.requeue_review_task(task_id, ADMIN),
        ApiErrorId.ERR_INVALID_TASK_STATE,
        409,
    )
    from_queued = fixtures.read_task(task_id)
    assert from_queued["status"] == "QUEUED"
    assert from_queued["cycle_count"] == 0
    assert from_queued["resolution"] == "PENDING"
    assert from_queued["version"] == case["task"]["version"]

    # From CLAIMED.
    fixtures.claim_task(task_id, reviewer_id)
    validate_error(
        api_client.requeue_review_task(task_id, ADMIN),
        ApiErrorId.ERR_INVALID_TASK_STATE,
        409,
    )
    from_claimed = fixtures.read_task(task_id)
    assert from_claimed["status"] == "CLAIMED"
    assert from_claimed["assigned_reviewer_id"] == reviewer_id
    assert from_claimed["cycle_count"] == 0

    # From RESOLVED.
    resolved = fixtures.decide_task(
        task_id, reviewer_id, "APPROVE", note="Approved so the task reaches RESOLVED."
    )
    assert resolved["status"] == "RESOLVED"
    validate_error(
        api_client.requeue_review_task(task_id, ADMIN),
        ApiErrorId.ERR_INVALID_TASK_STATE,
        409,
    )

    final = fixtures.read_task(task_id)
    assert final["status"] == "RESOLVED"
    assert final["resolution"] == "APPROVE"
    # A refused requeue never bumps the loop counter and never touches the row.
    assert final["cycle_count"] == 0
    assert final["version"] == resolved["version"]

    assert fixtures.read_reviewer(reviewer_id)["claimed_task_count"] == 0
    assert (
        fixtures.read_creative(
            case["creative_id"], advertiser_id=case["advertiser_id"]
        )["review_status"]
        == "AUTO_APPROVED"
    )


def test_the_notice_the_ledger_and_the_account_agree_on_one_four_point_line():
    """PRD §3.9: "Each finding line records the matched rule's code as its
    `policy_rule_code`, the source reason as its `reason_code`, and as its `line_points`
    the matched rule's `base_severity_weight` multiplied by the country multiplier of that
    rule for this creative and then multiplied by the reason factor of the source reason,
    rounded half-up to 2 decimals."

    PRD §3.7: "Hop three has that notice write a violation ledger entry with `reason`
    `DISAPPROVAL_ASSESSED`, `delta_points` equal to the notice's `assessed_points` and
    `balance_after` set to the advertiser's new raw balance."

    PRD §3.9: "The notice also records `disclosed_points_total`, which is the advertiser's
    `violation_points_raw` immediately after this notice's ledger entry has landed, so the
    advertiser sees the balance the notice actually produced."

    PRD §3.9: "Step four selects an action type keyed on the post-surcharge
    `severity_index`: `SUSPENSION` when it is at least 40.00, otherwise `RESTRICTION` when
    it is at least 25.00, otherwise `WARNING` when it is at least 10.00, and otherwise
    none at all."

    PRD §3.2: "When no action on the account is in force, the posture is `ACTIVE`."

    Design: Corner/From Table 5 (Endpoints)/computed_read_advertiser_balances_and_the_notice_ledger_agree_after_one_disapproval
    """
    case = _a_queued_standard_task()
    advertiser_id = case["advertiser_id"]
    reviewer_id = case["reviewer_id"]

    fixtures.claim_task(case["task"]["id"], reviewer_id)
    fixtures.decide_task(
        case["task"]["id"],
        reviewer_id,
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Claims in the body are not substantiated.",
    )

    notice = fixtures.only_notice_for_creative(case["creative_id"])
    assert notice["decided_by_reviewer_id"] == reviewer_id
    assert notice["reason_codes"] == ["MANUAL_REVIEW"]
    assert notice["policy_rule_codes"] == [FIN_CREDIT]
    # 4.00 weight * 1.00 country multiplier * 1.00 MANUAL_REVIEW factor.
    assert notice["assessment_lines"] == [
        {
            "policy_rule_code": FIN_CREDIT,
            "reason_code": "MANUAL_REVIEW",
            "line_points": pytest.approx(4.00, abs=0.01),
        }
    ]
    assert notice["assessed_points"] == pytest.approx(4.00, abs=0.01)
    assert notice["disclosed_points_total"] == pytest.approx(4.00, abs=0.01)
    assert_instant_equals(
        notice["appeal_deadline_at"], "2026-08-04T00:00:00Z", "appeal_deadline_at"
    )

    per_notice = fixtures.ledger_for_notice(notice["id"])
    assert len(per_notice) == 1
    assert per_notice[0]["entry_index"] == 1
    assert per_notice[0]["reason"] == "DISAPPROVAL_ASSESSED"
    assert per_notice[0]["delta_points"] == pytest.approx(4.00, abs=0.01)
    assert per_notice[0]["balance_after"] == pytest.approx(4.00, abs=0.01)

    # The per-advertiser projection is the same single row.
    per_advertiser = fixtures.ledger_for_advertiser(advertiser_id)
    assert [entry["id"] for entry in per_advertiser] == [per_notice[0]["id"]]

    advertiser = fixtures.read_advertiser(advertiser_id)
    assert advertiser["violation_points_raw"] == pytest.approx(4.00, abs=0.01)
    assert advertiser["violation_points_decayed"] == pytest.approx(4.00, abs=0.01)
    assert advertiser["severity_index"] == pytest.approx(4.00, abs=0.01)
    assert advertiser["ledger_entry_count"] == 1
    assert advertiser["account_status"] == "ACTIVE"

    # 4.00 never reaches the 10.00 warning threshold, so nothing was minted.
    _rows, pagination = validate_paginated(
        api_client.list_enforcement_actions(ADMIN, {"advertiser_id": advertiser_id})
    )
    assert pagination["total_count"] == 0


# ---------------------------------------------------------------------------
# Shared setup for the appeal's two links
# ---------------------------------------------------------------------------
def _issued_notice_and_a_licence_on_file():
    """An ISSUED notice on a holder who also owns one ACTIVE licence for the same rule.

    The licence is admissible evidence for the appeal, and `CERT_MISSING` is an admissible
    reason for the disapproval because the matched rule demands certification — the two
    facts are independent, which is exactly what makes the pair of links worth resolving.
    """
    rule = fixtures.create_policy_rule(
        ALC_SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
        requires_disclaimer=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
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
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-12-31T00:00:00Z",
        issuing_country_code="US",
        license_number="TTB-NL-2026-01",
        headers=make_advertiser_headers(advertiser_id),
    )
    reviewer = fixtures.create_reviewer(
        ["REGULATED_CERT"], ["US"], display_name="C. Mbeki", max_concurrent_claims=3
    )
    creative, task = fixtures.creative_in_manual_review(
        advertiser_id,
        [ALC_SPIRITS],
        [(rule["id"], 0.50)],
        ["US"],
        headline="Cask finish",
        body_text="Our cask finish spirit is bottled in limited numbers each season.",
        landing_page_url="https://www.northline.example/cask",
        display_url="https://www.northline.example/cask",
    )
    fixtures.claim_task(task["id"], reviewer["id"])
    fixtures.decide_task(
        task["id"],
        reviewer["id"],
        "DISAPPROVE",
        reason_codes=["CERT_MISSING"],
        note="License evidence not located at review time.",
    )
    return {
        "advertiser_id": advertiser_id,
        "certification": certification,
        "creative_id": creative["id"],
        "notice": fixtures.only_notice_for_creative(creative["id"]),
    }


def test_an_appeal_resolves_its_notice_and_its_evidence_before_it_writes_anything():
    """PRD §2.5: "The same discipline applies to foreign keys arriving in a request body.
    A body-supplied `advertiser_id`, `policy_rule_id`, `prior_action_id`,
    `disapproval_notice_id` or `evidence_certification_id` must resolve, and every element
    of `declared_category_codes` must match the `code` of an existing policy rule — a miss
    there reports `ERR_POLICY_RULE_NOT_FOUND`."

    PRD §2.5: "Each identifier position has its own dedicated not-found error, all of them
    HTTP 404: an unresolvable `advertiser_id` yields `ERR_ADVERTISER_NOT_FOUND`, an
    unresolvable `ad_creative_id` yields `ERR_AD_CREATIVE_NOT_FOUND`, an unresolvable
    `policy_rule_id` yields `ERR_POLICY_RULE_NOT_FOUND`, an unresolvable `reviewer_id`
    yields `ERR_REVIEWER_NOT_FOUND`, an unresolvable `screening_run_id` yields
    `ERR_SCREENING_RUN_NOT_FOUND`, an unresolvable `review_task_id` yields
    `ERR_REVIEW_TASK_NOT_FOUND`, an unresolvable `certification_id` yields
    `ERR_CERTIFICATION_NOT_FOUND`, an unresolvable `disapproval_notice_id` yields
    `ERR_DISAPPROVAL_NOTICE_NOT_FOUND`, an unresolvable `appeal_id` yields
    `ERR_APPEAL_NOT_FOUND`, and an unresolvable `enforcement_action_id` yields
    `ERR_ENFORCEMENT_ACTION_NOT_FOUND`."

    PRD §4: "Operations that bring a new resource into existence — a policy rule, a
    country variation, an advertiser, an enforcement action, a reviewer, a creative, a
    screening run, a destination check, a certification or an appeal — return
    `201 Created`."

    PRD §3.9: "A successful filing creates the appeal in status `SUBMITTED` with a null
    `decided_by_reviewer_id`, a null `decided_at` and a null `reinstated_review_status`,
    and advances the notice `ISSUED → APPEALED` with its `version` incremented by 1."

    PRD §3.9: "Appeals can be listed filtered by `disapproval_notice_id`, by
    `evidence_certification_id`, by `decided_by_reviewer_id` or by `status`."

    Design: Corner/From Table 5 (Endpoints)/cross_reference_link_an_appeal_binds_a_notice_to_an_evidence_certification
    """
    case = _issued_notice_and_a_licence_on_file()
    advertiser_id = case["advertiser_id"]
    certification_id = case["certification"]["id"]
    notice_id = case["notice"]["id"]
    owner = make_advertiser_headers(advertiser_id)

    assert case["certification"]["status"] == "ACTIVE"
    assert case["notice"]["status"] == "ISSUED"
    assert case["notice"]["version"] == 1

    # The notice link is read first, so the real certification cannot save the call.
    validate_error(
        api_client.create_appeal(
            factories.create_appeal_payload(
                NON_EXISTENT_UUID,
                "The notice id in this call does not exist at all.",
                certification_id,
            ),
            owner,
        ),
        ApiErrorId.ERR_DISAPPROVAL_NOTICE_NOT_FOUND,
        404,
    )

    validate_error(
        api_client.create_appeal(
            factories.create_appeal_payload(
                notice_id,
                "The certification id in this call does not exist at all.",
                NON_EXISTENT_UUID,
            ),
            owner,
        ),
        ApiErrorId.ERR_CERTIFICATION_NOT_FOUND,
        404,
    )
    # Neither refusal touched the notice.
    untouched = fixtures.read_notice(notice_id)
    assert untouched["status"] == "ISSUED"
    assert untouched["version"] == 1

    appeal = validate_success(
        api_client.create_appeal(
            factories.create_appeal_payload(
                notice_id,
                "Our TTB license was active for the whole review window.",
                certification_id,
            ),
            owner,
        ),
        201,
    )
    assert appeal["status"] == "SUBMITTED"
    assert appeal["disapproval_notice_id"] == notice_id
    assert appeal["evidence_certification_id"] == certification_id
    assert appeal["decided_by_reviewer_id"] is None
    assert appeal["decided_at"] is None
    assert appeal["reinstated_review_status"] is None

    appealed = fixtures.read_notice(notice_id)
    assert appealed["status"] == "APPEALED"
    assert appealed["version"] == 2

    # Exactly one row is reachable through the evidence link: no 404 left a trace.
    rows, pagination = validate_paginated(
        api_client.list_appeals(
            ADMIN, {"evidence_certification_id": certification_id}
        )
    )
    assert pagination["total_count"] == 1
    assert [row["id"] for row in rows] == [appeal["id"]]


# ---------------------------------------------------------------------------
# Shared setup for the sweep
# ---------------------------------------------------------------------------
PHASE_COUNTERS = (
    "activated_certifications",
    "expired_certifications",
    "expired_notices",
    "expired_review_tasks",
    "requeued_review_tasks",
    "expired_enforcement_actions",
    "lifted_enforcement_actions",
    "released_hold_creatives",
)


def _a_licence_a_task_and_a_notice_all_dated_ahead():
    """Three time-gated rows, none of them due at the opening clock.

    A future-dated licence opens on 2026-08-05, a REGULATED_CERT task falls due at
    2026-08-03, and an ISSUED notice's appeal window shuts at 2026-08-04. One jump of the
    clock to 2026-08-06 puts all three behind it at once.
    """
    alcohol = fixtures.create_policy_rule(
        ALC_SPIRITS,
        "RESTRICTED",
        6.00,
        title="Alcohol - spirits",
        requires_certification=True,
        requires_disclaimer=False,
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        review_sla_hours=48,
        default_queue="REGULATED_CERT",
    )
    credit = fixtures.create_policy_rule(
        FIN_CREDIT,
        "REGULATED",
        4.00,
        title="Consumer credit offers",
        confidence_auto_disapprove_threshold=0.90,
        confidence_manual_threshold=0.20,
        default_queue="STANDARD",
    )
    advertiser = fixtures.create_verified_advertiser(
        legal_name="Northline Spirits LLC",
        country_code="US",
        industry_code="ALCOHOL_RETAIL",
    )
    advertiser_id = advertiser["id"]
    certification = fixtures.create_certification(
        advertiser_id,
        alcohol["id"],
        valid_from="2026-08-05T00:00:00Z",
        valid_until="2026-09-05T00:00:00Z",
        issuing_country_code="US",
        license_number="TTB-NL-2026-09",
        headers=make_advertiser_headers(advertiser_id),
    )
    reviewer = fixtures.create_reviewer(
        ["REGULATED_CERT", "STANDARD"],
        ["US"],
        display_name="C. Mbeki",
        max_concurrent_claims=3,
    )
    waiting_creative, waiting_task = fixtures.creative_in_manual_review(
        advertiser_id,
        [ALC_SPIRITS],
        [(alcohol["id"], 0.50)],
        ["US"],
        headline="Cask finish",
        body_text="Our cask finish spirit waits in the regulated certification queue.",
        landing_page_url="https://www.northline.example/cask",
        display_url="https://www.northline.example/cask",
    )
    doomed_creative, doomed_task = fixtures.creative_in_manual_review(
        advertiser_id,
        [FIN_CREDIT],
        [(credit["id"], 0.50)],
        ["US"],
        headline="Bar tab financing",
        body_text="A credit offer that will be disapproved to produce one notice.",
        landing_page_url="https://www.northline.example/finance",
        display_url="https://www.northline.example/finance",
    )
    fixtures.claim_task(doomed_task["id"], reviewer["id"])
    fixtures.decide_task(
        doomed_task["id"],
        reviewer["id"],
        "DISAPPROVE",
        reason_codes=["MANUAL_REVIEW"],
        note="Unsubstantiated financing claims.",
    )
    return {
        "alcohol_rule_id": alcohol["id"],
        "advertiser_id": advertiser_id,
        "certification": certification,
        "waiting_creative_id": waiting_creative["id"],
        "waiting_task": waiting_task,
        "notice": fixtures.only_notice_for_creative(doomed_creative["id"]),
    }


def test_the_sweep_reports_nothing_and_touches_nothing_before_anything_is_due():
    """PRD §2.8: "The sweep reports a count for each phase: `activated_certifications`,
    `expired_certifications`, `expired_notices`, `expired_review_tasks`,
    `requeued_review_tasks`, `expired_enforcement_actions`, `lifted_enforcement_actions`,
    `released_hold_creatives` and `decay_refreshed_advertisers`."

    PRD §2.8: "Every entity the sweep touches has its `version` incremented by 1."

    PRD §3.5: "A certification is born with `status` `SUBMITTED` and a null
    `revocation_reason`, except that when the logical clock is already at or after
    `valid_from` and strictly before `valid_until` it is born `ACTIVE` outright."

    Design: Corner/From Table 5 (Endpoints)/bulk_action_the_policy_sweep_is_a_no_op_before_anything_is_due_and_reports_per_phase_counters_after
    """
    case = _a_licence_a_task_and_a_notice_all_dated_ahead()
    waiting_task = case["waiting_task"]

    assert case["certification"]["status"] == "SUBMITTED"
    assert case["certification"]["revocation_reason"] is None
    assert_instant_equals(
        waiting_task["sla_deadline_at"], "2026-08-03T00:00:00Z", "sla_deadline_at"
    )
    assert_instant_equals(
        case["notice"]["appeal_deadline_at"],
        "2026-08-04T00:00:00Z",
        "appeal_deadline_at",
    )

    counters = fixtures.run_sweep()
    for counter in PHASE_COUNTERS:
        assert counters[counter] == 0, f"{counter} fired with nothing due: {counters}"

    # Inspecting a row is not touching it.
    unmoved_task = fixtures.read_task(waiting_task["id"])
    assert unmoved_task["status"] == "QUEUED"
    assert unmoved_task["version"] == waiting_task["version"]
    assert (
        fixtures.read_certification(case["certification"]["id"])["version"]
        == case["certification"]["version"]
    )
    unmoved_notice = fixtures.read_notice(case["notice"]["id"])
    assert unmoved_notice["status"] == "ISSUED"
    assert unmoved_notice["version"] == case["notice"]["version"]


def test_after_the_clock_jumps_the_same_sweep_reports_exactly_the_phases_that_fired():
    """PRD §2.8: "A `PolicyAdmin` moves it forward by supplying `to_iso8601`, and the
    response reports `current_utc` alongside `previous_utc`."

    PRD §2.8: "Time-gated consequences are realized only by the policy sweep, an
    admin-only capability that runs eight phases in this fixed order at the current logical
    clock: (1) activation of certifications whose validity interval now contains the clock;
    (2) expiry of certifications whose validity has ended, together with the re-routing of
    creatives that relied on them; (3) expiry of disapproval notices whose appeal window
    has closed; (4) SLA expiry of review tasks, together with creation of their replacement
    tasks; (5) expiry of enforcement actions whose window has ended; (6) refresh of every
    advertiser's decayed points balance and severity index; (7) lifting of enforcement
    actions whose threshold the refreshed severity index no longer reaches; and (8) release
    of creatives held under suspension once the account is no longer suspended."

    PRD §3.6: "Only on this SLA path does the sweep create a replacement task: a fresh
    `QUEUED` task with the same `queue` and the same `primary_policy_rule_id`, whose
    `cycle_count` is one greater than the expired task's."

    Design: Corner/From Table 5 (Endpoints)/bulk_action_the_policy_sweep_is_a_no_op_before_anything_is_due_and_reports_per_phase_counters_after
    """
    case = _a_licence_a_task_and_a_notice_all_dated_ahead()
    expired_task_id = case["waiting_task"]["id"]
    fixtures.run_sweep()

    moved = fixtures.set_clock("2026-08-06T00:00:00Z")
    assert_instant_equals(moved["current_utc"], "2026-08-06T00:00:00Z", "current_utc")
    assert_instant_equals(moved["previous_utc"], "2026-08-01T00:00:00Z", "previous_utc")

    counters = fixtures.run_sweep()
    assert counters["activated_certifications"] == 1
    assert counters["expired_certifications"] == 0
    assert counters["expired_notices"] == 1
    assert counters["expired_review_tasks"] == 1
    assert counters["requeued_review_tasks"] == 1
    assert counters["expired_enforcement_actions"] == 0
    assert counters["lifted_enforcement_actions"] == 0
    assert counters["released_hold_creatives"] == 0

    licence = fixtures.read_certification(case["certification"]["id"])
    assert licence["status"] == "ACTIVE"
    assert licence["version"] == case["certification"]["version"] + 1

    notice = fixtures.read_notice(case["notice"]["id"])
    assert notice["status"] == "EXPIRED"
    assert notice["version"] == case["notice"]["version"] + 1

    tasks = fixtures.list_tasks_for_creative(case["waiting_creative_id"])
    assert len(tasks) == 2, f"the SLA path mints exactly one replacement: {tasks}"
    by_id = {task["id"]: task for task in tasks}
    expired = by_id[expired_task_id]
    assert expired["status"] == "EXPIRED"
    assert expired["assigned_reviewer_id"] is None
    assert expired["cycle_count"] == 0

    replacement = [task for task in tasks if task["id"] != expired_task_id][0]
    assert replacement["status"] == "QUEUED"
    assert replacement["cycle_count"] == 1
    assert replacement["queue"] == "REGULATED_CERT"
    assert replacement["primary_policy_rule_id"] == case["alcohol_rule_id"]
    assert_instant_equals(
        replacement["sla_deadline_at"], "2026-08-08T00:00:00Z", "sla_deadline_at"
    )

    # An SLA expiry re-queues the work; it does not resolve the creative.
    assert (
        fixtures.read_creative(
            case["waiting_creative_id"], advertiser_id=case["advertiser_id"]
        )["review_status"]
        == "PENDING_MANUAL_REVIEW"
    )
