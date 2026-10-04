"""Queue B — state_machines: valid cycles, invalid transitions, sweep-driven
transitions, and terminal-state lockdown across the registry's lifecycle
machines.
"""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ADMIN,
    PROCTOR,
    ApiErrorId,
    api_client,
    advance_clock,
    appeal_case,
    assert_attempt_budget_invariant,
    case_decide_payload,
    cat_responses_payload,
    create_candidate,
    create_exam_application,
    create_level,
    create_psychomotor,
    create_recert_application_payload,
    create_state_exam_record,
    create_state_policy,
    decide_license,
    decision_payload,
    finalize_decided_case,
    get_success_data,
    issue_notice,
    make_candidate_headers,
    make_hearing_officer_headers,
    open_case,
    refresh_case,
    refresh_certification,
    refresh_completion_record,
    reopen_recert,
    resubmit_application_payload,
    respond_license,
    schedule_attempt,
    setup_approved_application,
    setup_candidate_with_verified_completion,
    setup_certified_candidate,
    setup_license_context_nremt,
    setup_submitted_recert,
    submit_recert,
    validate_error,
    validate_paginated,
    validate_success,
    walk_case_to_decided,
    walk_case_to_under_review,
)


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_completion_second_decision_fails(api):
    """PRD §3.3: "A verify decision requires the record to still be
    `PENDING_VERIFICATION` (`ERR_COMPLETION_NOT_PENDING`) and re-checks the
    accreditation-at-completion condition; on success the record becomes
    `VERIFIED` and `verified_at` is set to the decision instant."

    A record already VERIFIED accepts no further decision.

    Design: Corner/state_machines/completion_second_decision_fails
    """
    ctx = setup_candidate_with_verified_completion()
    resp = api_client.decide_program_completion_record(
        ctx["completion_record"]["id"], decision_payload("REJECTED", reason="late doubt"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_COMPLETION_NOT_PENDING)
    assert refresh_completion_record(ctx["completion_record"]["id"])["status"] == "VERIFIED"


def test_exam_application_deny_resubmit_cycle(api):
    """PRD §3.4: "Denial is not the end of the road: the owning candidate may
    resubmit a `DENIED` application — any other state draws
    `ERR_APPLICATION_NOT_DENIED`, any other caller `ERR_FORBIDDEN_ROLE` —
    optionally swapping in a different `completion_record_id`. Resubmission
    returns the application to `SUBMITTED`, clears the `denial_reason`, and
    increments `resubmission_count` (which starts at zero on creation), and the
    full approval gate set re-runs on the next decision."

    Design: Corner/state_machines/exam_application_deny_resubmit_cycle
    """
    ctx = setup_candidate_with_verified_completion()
    application = create_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    denied = get_success_data(api_client.decide_exam_application(
        application["id"], decision_payload("DENIED", reason="Incomplete documentation"), ADMIN,
    ))
    assert denied["status"] == "DENIED"

    resubmitted = get_success_data(api_client.resubmit_exam_application(
        application["id"], resubmit_application_payload(),
        make_candidate_headers(ctx["candidate"]["id"]),
    ))
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["resubmission_count"] == 1
    assert resubmitted["denial_reason"] is None

    approved = get_success_data(api_client.decide_exam_application(
        application["id"], decision_payload("APPROVED"), ADMIN,
    ))
    assert approved["status"] == "APPROVED"
    assert approved["att_id"], "the re-reviewed application mints an authorization"


def test_resubmit_submitted_application_fails(api):
    """PRD §3.4: "the owning candidate may resubmit a `DENIED` application — any
    other state draws `ERR_APPLICATION_NOT_DENIED`, any other caller
    `ERR_FORBIDDEN_ROLE`".

    Design: Corner/state_machines/resubmit_submitted_application_fails
    """
    ctx = setup_candidate_with_verified_completion()
    application = create_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    resp = api_client.resubmit_exam_application(
        application["id"], resubmit_application_payload(),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DENIED)


def test_att_expiry_sweep_marks_expired(api):
    """PRD §3.4: "Approval mints an **authorization to test**: `issued_on` at the
    approval instant, `expires_on` ninety calendar days later, status `ISSUED`".
    PRD §2.5: "Every advance runs a deterministic sweep in this pinned order:
    1. Authorizations to test still `ISSUED` whose `expires_on` is earlier than
    now become `EXPIRED`."

    Design: Corner/state_machines/att_expiry_sweep_marks_expired
    """
    ctx = setup_approved_application()
    sweep = advance_clock("2026-12-01T00:00:00Z")
    assert sweep["att_expired_count"] == 1

    resp = api_client.list_authorizations_to_test(
        ADMIN, params={"exam_application_id": ctx["exam_application"]["id"]},
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    att = data[0]
    assert att["status"] == "EXPIRED"
    assert _ts(att["expires_on"]) == _ts("2026-11-30T00:00:00Z"), (
        f"expires_on is issued_on + 90 days, got {att['expires_on']}"
    )
    assert _ts(att["expires_on"]) == _ts(att["issued_on"]) + timedelta(days=90)


def test_attempt_no_show_sweep_consumes_att(api):
    """PRD §2.5: "2. Attempts still `SCHEDULED` whose `scheduled_end` is earlier
    than now, and that were never delivered, become `NO_SHOW`, and their
    authorization becomes `CONSUMED`."
    PRD §3.4: "When the delivery window closes with no responses recorded, the
    sweep marks the attempt `NO_SHOW` and consumes the authorization — and a
    no-show never consumes attempt budget."

    Design: Corner/state_machines/attempt_no_show_sweep_consumes_att
    """
    ctx = setup_approved_application()
    attempt = schedule_attempt(
        ctx["candidate"]["id"], ctx["att_id"],
        "2026-09-02T00:00:00Z", "2026-09-04T00:00:00Z",
    )
    sweep = advance_clock("2026-09-05T00:00:00Z")
    assert sweep["attempts_no_show_count"] == 1

    scored = get_success_data(api_client.get_cognitive_exam_attempt(attempt["id"], ADMIN))
    assert scored["status"] == "NO_SHOW"
    resp = api_client.list_authorizations_to_test(
        ADMIN, params={"exam_application_id": ctx["exam_application"]["id"]},
    )
    data, _ = validate_paginated(resp)
    assert data[0]["status"] == "CONSUMED", "a no-show burns the authorization"

    record = refresh_completion_record(ctx["completion_record"]["id"])
    assert record["attempts_consumed"] == 0, "NO_SHOW is excluded from the budget"
    assert record["attempts_remaining"] == 6
    assert_attempt_budget_invariant(record)


def test_delivery_before_window_fails(api):
    """PRD §3.4: "The attempt must still be `SCHEDULED`
    (`ERR_ATTEMPT_NOT_SCHEDULED`), and the delivery instant must fall inside the
    window, both bounds inclusive (`ERR_DELIVERY_WINDOW_NOT_OPEN`)".

    Responses submitted before scheduled_start are rejected even though the
    attempt is SCHEDULED.

    Design: Corner/state_machines/delivery_before_window_fails
    """
    ctx = setup_approved_application()
    attempt = schedule_attempt(ctx["candidate"]["id"], ctx["att_id"])
    resp = api_client.deliver_cognitive_exam_responses(
        attempt["id"], cat_responses_payload(6, 6), PROCTOR,
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_WINDOW_NOT_OPEN)
    assert get_success_data(
        api_client.get_cognitive_exam_attempt(attempt["id"], ADMIN)
    )["status"] == "SCHEDULED"


def test_psychomotor_verify_requires_all_stations(api):
    """PRD §3.5: "Verification requires the record to still be `SUBMITTED`
    (`ERR_PSYCHOMOTOR_NOT_SUBMITTED`), every station passed, and
    `documentation_attached` true — anything less is rejected with
    `ERR_PSYCHOMOTOR_REQUIREMENTS_UNMET`. A verified record stamps `verified_at`
    at the decision instant, opening its validity window; rejection ends the
    record `REJECTED`, and both outcomes are terminal."

    Design: Corner/state_machines/psychomotor_verify_requires_all_stations
    """
    ctx = setup_candidate_with_verified_completion()
    psy = create_psychomotor(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
        exam_date="2026-09-01",
        stations=[{"station_code": "AIRWAY", "passed": True},
                  {"station_code": "BLEEDING", "passed": False}],
    )
    resp = api_client.decide_psychomotor_verification(
        psy["id"], decision_payload("VERIFIED"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PSYCHOMOTOR_REQUIREMENTS_UNMET)

    rejected = get_success_data(api_client.decide_psychomotor_verification(
        psy["id"], decision_payload("REJECTED", reason="BLEEDING station failed"), ADMIN,
    ))
    assert rejected["status"] == "REJECTED"


def test_certification_revoked_terminal_lockdown(api):
    """PRD §3.7: "The candidate applies by naming the `certification_id`; the
    certification must stand `LAPSED` (`ERR_CERTIFICATION_NOT_LAPSED`)".
    PRD §3.6: "The owning candidate opens a draft against an `ACTIVE`
    certification".
    PRD §3.9: "`REVOCATION` or `PERMANENT_BAR` moves the subject's `ACTIVE`,
    `SUSPENDED`, or `LAPSED` certifications to `REVOKED`".

    A REVOKED certification accepts no lifecycle transitions: reentry requires
    LAPSED and recertification requires ACTIVE — both fail.

    Design: Corner/state_machines/certification_revoked_terminal_lockdown
    """
    ctx = setup_certified_candidate()
    case = open_case(
        ctx["candidate"]["id"], violation_type="CRIMINAL_CONDUCT",
        description="Felony conviction disclosed",
    )
    walk_case_to_decided(case["id"], ctx["candidate"]["id"], sanction_type="REVOCATION",
                         findings="Substantiated")
    finalize_decided_case(case["id"])
    cert = refresh_certification(ctx["certification"]["id"])
    assert cert["status"] == "REVOKED"

    reentry_resp = api_client.create_reentry_application(
        {"certification_id": cert["id"]}, make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(reentry_resp, ApiErrorId.ERR_CERTIFICATION_NOT_LAPSED)

    recert_resp = api_client.create_recert_application(
        create_recert_application_payload(cert["id"], "NCCP", cert["version"]),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(recert_resp, ApiErrorId.ERR_CERTIFICATION_NOT_ACTIVE)


def test_recert_deny_reopen_cycle(api):
    """PRD §3.6: "Both `DENIED` and `AUDIT_FAILED` applications can be reopened
    by their owner — any other state draws `ERR_RECERT_NOT_REOPENABLE`, any
    other caller `ERR_FORBIDDEN_ROLE` — returning the application to `DRAFT`. A
    reopened application re-runs the full window check, waterfall, and audit
    selection on its next submission".
    PRD §3.6: "The application's `recert_seq` is one plus the number of prior
    applications for the same certification that ever reached `SUBMITTED`".

    DENIED -> reopen -> DRAFT -> resubmit succeeds.

    Note: the PRD pins recert_seq == 1 on a first submission ("one plus the
    number of prior applications for the same certification that ever reached
    SUBMITTED"), but does not uniquely determine whether a reopened and
    resubmitted application counts its own earlier submission as a "prior
    application" — both readings are PRD-faithful, so no seq value is
    asserted on the resubmission.

    Design: Corner/state_machines/recert_deny_reopen_cycle
    """
    ctx = setup_submitted_recert()
    application = ctx["recert_application"]
    assert application["recert_seq"] == 1
    denied = get_success_data(api_client.decide_recert_application(
        application["id"], decision_payload("DENIED", reason="Provider documentation unclear"),
        ADMIN,
    ))
    assert denied["status"] == "DENIED"

    reopened = reopen_recert(application["id"], ctx["candidate"]["id"])
    assert reopened["status"] == "DRAFT"

    resubmitted = submit_recert(application["id"], ctx["candidate"]["id"])
    assert resubmitted["status"] == "SUBMITTED"


def test_license_more_info_cycle(api):
    """PRD §3.8: "An information request instead moves the application to
    `MORE_INFO_REQUIRED` with a `more_info_note`, and the owning candidate
    responds with a `response_note` — any other state draws
    `ERR_LICENSE_NOT_AWAITING_RESPONSE`, any other caller `ERR_FORBIDDEN_ROLE`
    — cycling the application back to `UNDER_REVIEW` with the policy snapshot
    still pinned."

    UNDER_REVIEW -> MORE_INFO_REQUIRED -> respond -> UNDER_REVIEW -> GRANTED,
    with fees assessed only at the final grant.

    Design: Corner/state_machines/license_more_info_cycle
    """
    ctx = setup_license_context_nremt()
    application = ctx["license_application"]
    asked = decide_license(application["id"], "MORE_INFO_REQUIRED",
                           reason="Provide driving record")
    assert asked["status"] == "MORE_INFO_REQUIRED"

    answered = respond_license(application["id"], ctx["candidate"]["id"],
                               response_note="Driving record attached")
    assert answered["status"] == "UNDER_REVIEW"

    granted = decide_license(application["id"], "GRANTED")
    assert granted["status"] == "GRANTED"
    assert granted["assessed_fee_cents"] == 19980
    assert granted["granted_on"] is not None


def test_case_response_deadline_sweep_advances(api):
    """PRD §3.9: "The administrator issues the notice of allegations, moving the
    case to `NOTICE_ISSUED` and opening the response window: `response_deadline`
    is set thirty calendar days out, and a response arriving exactly at the
    deadline is accepted."
    PRD §2.5: "6. Disciplinary cases in `NOTICE_ISSUED` whose `response_deadline`
    has passed advance to `UNDER_REVIEW`."

    Design: Corner/state_machines/case_response_deadline_sweep_advances
    """
    candidate = create_candidate()
    case = open_case(
        candidate["id"], violation_type="CRIMINAL_CONDUCT",
        description="Charge under review",
    )
    noticed = issue_notice(case["id"])
    assert _ts(noticed["response_deadline"]) == _ts("2026-10-01T00:00:00Z"), (
        f"notice at 2026-09-01 opens a 30-day window, got {noticed['response_deadline']}"
    )

    sweep = advance_clock("2026-10-02T00:00:00Z")
    assert sweep["cases_advanced_count"] == 1
    assert refresh_case(case["id"])["status"] == "UNDER_REVIEW"


def test_decide_before_hearing_fails(api):
    """PRD §3.9: "Due process then proceeds stage by stage, each action
    requiring the exact preceding stage (`ERR_CASE_STAGE_MISMATCH` otherwise)."

    Decide requires HEARING_SCHEDULED; calling it from UNDER_REVIEW fails even
    with the current concurrency token.

    Design: Corner/state_machines/decide_before_hearing_fails
    """
    candidate = create_candidate()
    case = open_case(
        candidate["id"], violation_type="EXAM_SECURITY",
        description="Suspected proxy test taker",
    )
    walk_case_to_under_review(case["id"], candidate["id"])
    current = refresh_case(case["id"])
    resp = api_client.decide_case(
        case["id"],
        case_decide_payload("WARNING", "premature", current["version"]),
        make_hearing_officer_headers("ho-1"),
    )
    validate_error(resp, ApiErrorId.ERR_CASE_STAGE_MISMATCH)


def test_appeal_exactly_at_deadline_allowed(api):
    """PRD §3.9: "The case becomes `DECIDED`, `decided_at` is stamped, an
    `appeal_deadline` opens thirty calendar days later with the boundary
    inclusive".
    PRD §2.5: "7. Disciplinary cases in `DECIDED` whose `appeal_deadline` has
    passed enter `FINAL`, and the sanction cascade of §3.9 applies."

    The deadline is inclusive and the sweep fires only once the deadline has
    strictly passed: at exactly decided_at + 30 days the case is still DECIDED
    and the appeal succeeds.

    Design: Corner/state_machines/appeal_exactly_at_deadline_allowed
    """
    candidate = create_candidate()
    case = open_case(
        candidate["id"], violation_type="CRIMINAL_CONDUCT",
        description="Disclosure review",
    )
    advance_clock("2026-09-10T00:00:00Z")
    decided = walk_case_to_decided(case["id"], candidate["id"], sanction_type="WARNING",
                                   findings="Minor")
    assert _ts(decided["appeal_deadline"]) == _ts("2026-10-10T00:00:00Z")

    sweep = advance_clock("2026-10-10T00:00:00Z")
    assert sweep["cases_finalized_count"] == 0, "the sweep requires the deadline to have passed"

    appealed = appeal_case(case["id"], candidate["id"], appeal_grounds="New evidence")
    assert appealed["status"] == "APPEAL_PENDING"


def test_state_exam_record_voided_by_revocation(api):
    """PRD §3.8: "Such records are born `VALID`; a severe disciplinary
    finalization later voids them, setting `voided_by_case_id`, and `VOIDED` is
    terminal."
    PRD §3.9: "`REVOCATION` or `PERMANENT_BAR` moves the subject's `ACTIVE`,
    `SUSPENDED`, or `LAPSED` certifications to `REVOKED` — each storing
    `pre_sanction_status` and, because the revocation is discipline-driven,
    `revoked_by_case_id`; the subject's still-`ISSUED` authorizations to test
    become `REVOKED`; their still-`SUBMITTED` exam applications are `DENIED`;
    license applications in `UNDER_REVIEW` or `MORE_INFO_REQUIRED` citing a
    certification revoked by this event are `DENIED`; and the subject's `VALID`
    state exam records become `VOIDED`."
    PRD §3.8: "the cited record must match the target state and level
    (`ERR_CROSS_REFERENCE_MISMATCH`) and must be usable — passing, still
    `VALID`, and not stale — with failures rejected as
    `ERR_STATE_EXAM_NOT_PASSING`".

    Design: Corner/state_machines/state_exam_record_voided_by_revocation
    """
    create_state_policy(
        state_code="TX", adoption_mode="STATE_EXAM",
        base_license_fee_cents=10000, state_exam_fee_cents=2500,
    )
    level = create_level()
    candidate = create_candidate()
    record = create_state_exam_record(candidate["id"], "TX", level["id"], exam_date="2026-09-01")
    case = open_case(
        candidate["id"], violation_type="CRIMINAL_CONDUCT",
        description="Felony conviction",
    )
    walk_case_to_decided(case["id"], candidate["id"], sanction_type="REVOCATION",
                         findings="Substantiated")
    finalize_decided_case(case["id"])

    voided = get_success_data(api_client.get_state_exam_record(record["id"], ADMIN))
    assert voided["status"] == "VOIDED"
    assert voided["voided_by_case_id"] == case["id"]

    resp = api_client.create_license_application(
        {"state_code": "TX", "level_id": level["id"], "state_exam_record_id": record["id"]},
        make_candidate_headers(candidate["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STATE_EXAM_NOT_PASSING)
