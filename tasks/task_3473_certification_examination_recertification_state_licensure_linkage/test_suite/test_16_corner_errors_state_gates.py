"""Queue B — errors (state-gate addendum): terminal-state and wrong-stage
rejections across the lifecycle machines, plus the compliance gates on new
applications.
"""
from test_helpers import (
    ADMIN,
    PROCTOR,
    TEST_USERS,
    ApiErrorId,
    api_client,
    advance_clock,
    audit_outcome_payload,
    audit_verdict,
    cat_responses_payload,
    ce_entry_payload,
    create_candidate,
    create_exam_application,
    create_exam_application_payload,
    create_level,
    create_program,
    create_reentry_application,
    create_verified_psychomotor,
    decide_license,
    decide_reentry,
    decision_payload,
    finalize_decided_case,
    get_success_data,
    make_candidate_headers,
    open_case,
    record_accreditation_event,
    setup_candidate_with_verified_completion,
    setup_lapsed_certification,
    setup_license_context_state_exam,
    setup_recert_draft_with_entries,
    setup_scored_attempt,
    setup_submitted_recert,
    validate_error,
    walk_case_to_decided,
)


def test_accreditation_event_on_revoked_program_fails(api):
    """PRD §3.2: "The permitted moves are `ACCREDITED` to `PROVISIONAL`,
    `SUSPENDED`, or `REVOKED`; `PROVISIONAL` back to `ACCREDITED` or onward to
    `SUSPENDED` or `REVOKED`; and `SUSPENDED` back to `ACCREDITED` or onward to
    `REVOKED`. `REVOKED` is terminal."
    PRD §2.8: "6. **State preconditions.** The target resource's current state
    must allow the requested transition: the generic `ERR_INVALID_STATE`, or
    the specific state error for the endpoint — `ERR_COMPLETION_NOT_PENDING`,
    `ERR_APPLICATION_NOT_SUBMITTED`, `ERR_APPLICATION_NOT_DENIED`,
    `ERR_ATT_NOT_ISSUABLE`, `ERR_ATTEMPT_NOT_SCHEDULED`, `ERR_RECERT_NOT_DRAFT`,
    `ERR_RECERT_NOT_SUBMITTED`, `ERR_RECERT_NOT_AUDIT_PENDING`,
    `ERR_RECERT_NOT_REOPENABLE`, `ERR_CERTIFICATION_NOT_ACTIVE`,
    `ERR_CERTIFICATION_NOT_LAPSED`, `ERR_LICENSE_NOT_ACTIONABLE`,
    `ERR_LICENSE_NOT_AWAITING_RESPONSE`, `ERR_PSYCHOMOTOR_NOT_SUBMITTED`,
    `ERR_CASE_STAGE_MISMATCH`, or `ERR_REENTRY_NOT_SUBMITTED`."

    Design: Corner/errors/accreditation_event_on_revoked_program_fails
    """
    level = create_level()
    program = create_program(level["id"])
    record_accreditation_event(
        program["id"], "REVOKED", "2026-09-01", reason="Fraudulent records",
    )
    resp = api_client.record_accreditation_event(
        program["id"],
        {"to_status": "ACCREDITED", "effective_date": "2026-09-10", "reason": "Appeal"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_decision_on_denied_application_fails(api):
    """PRD §3.4: "Approval by a `RegistryAdmin` runs the full gate set in the
    precedence order of §2.8. The application must still be `SUBMITTED`
    (`ERR_APPLICATION_NOT_SUBMITTED`)."

    A denied application cannot be decided again without a resubmission.

    Design: Corner/errors/decision_on_denied_application_fails
    """
    ctx = setup_candidate_with_verified_completion()
    application = create_exam_application(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
    )
    get_success_data(api_client.decide_exam_application(
        application["id"], decision_payload("DENIED", reason="docs"), ADMIN,
    ))
    resp = api_client.decide_exam_application(
        application["id"], decision_payload("APPROVED"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_SUBMITTED)


def test_responses_on_scored_attempt_fails(api):
    """PRD §3.4: "The attempt must still be `SCHEDULED`
    (`ERR_ATTEMPT_NOT_SCHEDULED`), and the delivery instant must fall inside the
    window, both bounds inclusive (`ERR_DELIVERY_WINDOW_NOT_OPEN`)".

    A scored attempt is terminal; a second response submission is rejected.

    Design: Corner/errors/responses_on_scored_attempt_fails
    """
    ctx = setup_scored_attempt()
    resp = api_client.deliver_cognitive_exam_responses(
        ctx["attempt"]["id"], cat_responses_payload(1, 1), PROCTOR,
    )
    validate_error(resp, ApiErrorId.ERR_ATTEMPT_NOT_SCHEDULED)


def test_ce_entry_add_on_submitted_recert_fails(api):
    """PRD §3.6: "Only the draft's owner may add entries, and only to a draft —
    adding to an application in any other state is rejected with
    `ERR_RECERT_NOT_DRAFT`."

    Design: Corner/errors/ce_entry_add_on_submitted_recert_fails
    """
    ctx = setup_submitted_recert()
    resp = api_client.add_ce_entry(
        ctx["recert_application"]["id"],
        ce_entry_payload("NATIONAL", 5, "IN_PERSON", "2027-10-05", "AlphaCE"),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RECERT_NOT_DRAFT)


def test_decision_on_draft_recert_fails(api):
    """PRD §3.6: "A `RegistryAdmin` decides a non-audited application, which
    must stand `SUBMITTED` (`ERR_RECERT_NOT_SUBMITTED`)".

    A still-DRAFT application cannot be approved.

    Design: Corner/errors/decision_on_draft_recert_fails
    """
    ctx = setup_recert_draft_with_entries()
    resp = api_client.decide_recert_application(
        ctx["recert_application"]["id"], decision_payload("APPROVED"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_RECERT_NOT_SUBMITTED)


def test_audit_outcome_on_non_audited_fails(api):
    """PRD §3.6: "Recording an outcome against an application that is not
    `AUDIT_PENDING` is rejected with `ERR_RECERT_NOT_AUDIT_PENDING`."

    A plain SUBMITTED (non-selected) application rejects audit verdicts.

    Design: Corner/errors/audit_outcome_on_non_audited_fails
    """
    ctx = setup_submitted_recert()
    assert ctx["recert_application"]["status"] == "SUBMITTED"
    entry_id = ctx["entries"][0]["id"]
    resp = api_client.record_audit_outcome(
        ctx["recert_application"]["id"],
        audit_outcome_payload([audit_verdict(entry_id, "VERIFIED")]),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_RECERT_NOT_AUDIT_PENDING)


def test_reopen_submitted_recert_fails(api):
    """PRD §3.6: "Both `DENIED` and `AUDIT_FAILED` applications can be reopened
    by their owner — any other state draws `ERR_RECERT_NOT_REOPENABLE`, any
    other caller `ERR_FORBIDDEN_ROLE`".

    A live SUBMITTED application cannot be reopened.

    Design: Corner/errors/reopen_submitted_recert_fails
    """
    ctx = setup_submitted_recert()
    resp = api_client.reopen_recert_application(
        ctx["recert_application"]["id"], make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RECERT_NOT_REOPENABLE)


def test_decision_on_granted_license_fails(api):
    """PRD §3.8: "A `StateOfficial` then decides applications standing
    `UNDER_REVIEW` (`ERR_LICENSE_NOT_ACTIONABLE`)."

    GRANTED is terminal; any further decision is rejected.

    Design: Corner/errors/decision_on_granted_license_fails
    """
    ctx = setup_license_context_state_exam(state_exam_overrides={"exam_date": "2026-09-01"})
    decide_license(ctx["license_application"]["id"], "GRANTED")
    resp = api_client.decide_license_application(
        ctx["license_application"]["id"],
        decision_payload("DENIED", reason="changed mind"),
        TEST_USERS["state_official_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIONABLE)


def test_respond_on_under_review_license_fails(api):
    """PRD §3.8: "the owning candidate responds with a `response_note` — any
    other state draws `ERR_LICENSE_NOT_AWAITING_RESPONSE`, any other caller
    `ERR_FORBIDDEN_ROLE`".

    Respond is defined only from MORE_INFO_REQUIRED.

    Design: Corner/errors/respond_on_under_review_license_fails
    """
    ctx = setup_license_context_state_exam(state_exam_overrides={"exam_date": "2026-09-01"})
    resp = api_client.respond_license_application(
        ctx["license_application"]["id"], {"response_note": "unsolicited info"},
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_AWAITING_RESPONSE)


def test_decision_on_verified_psychomotor_fails(api):
    """PRD §3.5: "Verification requires the record to still be `SUBMITTED`
    (`ERR_PSYCHOMOTOR_NOT_SUBMITTED`), every station passed, and
    `documentation_attached` true — anything less is rejected with
    `ERR_PSYCHOMOTOR_REQUIREMENTS_UNMET`. A verified record stamps `verified_at`
    at the decision instant, opening its validity window; rejection ends the
    record `REJECTED`, and both outcomes are terminal."

    A VERIFIED record accepts no second decision.

    Design: Corner/errors/decision_on_verified_psychomotor_fails
    """
    ctx = setup_candidate_with_verified_completion()
    psy = create_verified_psychomotor(
        ctx["candidate"]["id"], ctx["level"]["id"], ctx["completion_record"]["id"],
        exam_date="2026-09-01",
    )
    resp = api_client.decide_psychomotor_verification(
        psy["id"], decision_payload("REJECTED", reason="second thoughts"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PSYCHOMOTOR_NOT_SUBMITTED)


def test_second_decision_on_reentry_fails(api):
    """PRD §3.7: "Approval by a `RegistryAdmin` requires the application to be
    `SUBMITTED` (`ERR_REENTRY_NOT_SUBMITTED`) and the certification to still be
    `LAPSED` (`ERR_CERTIFICATION_NOT_LAPSED`)".

    An APPROVED reentry application is terminal; a second decision is rejected.

    Design: Corner/errors/second_decision_on_reentry_fails
    """
    ctx = setup_lapsed_certification()
    reentry = create_reentry_application(
        ctx["candidate"]["id"], ctx["certification"]["id"], ce_makeup_hours_claimed=40,
    )
    decide_reentry(reentry["id"], "APPROVED")
    resp = api_client.decide_reentry_application(
        reentry["id"], decision_payload("DENIED", reason="audit second thoughts"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REENTRY_NOT_SUBMITTED)


def test_disciplinary_hold_blocks_exam_application(api):
    """PRD §3.9: "`HOLD_NEW_APPLICATIONS` raises the candidate's live
    `disciplinary_hold`, blocking new exam, recertification, reentry, and
    license applications with `ERR_DISCIPLINARY_HOLD` for as long as any such
    case remains non-final."
    PRD §3.4: "Creation is refused for a barred candidate
    (`ERR_PERMANENTLY_BARRED`) or one under a disciplinary hold
    (`ERR_DISCIPLINARY_HOLD`)".

    The interim action applies at case creation, before any notice.

    Design: Corner/errors/disciplinary_hold_blocks_exam_application
    """
    ctx = setup_candidate_with_verified_completion()
    open_case(
        ctx["candidate"]["id"], violation_type="EXAM_SECURITY",
        description="Exam irregularity under review",
        interim_action="HOLD_NEW_APPLICATIONS",
    )
    candidate = get_success_data(api_client.get_candidate(ctx["candidate"]["id"], ADMIN))
    assert candidate["disciplinary_hold"] is True

    resp = api_client.create_exam_application(
        create_exam_application_payload(ctx["level"]["id"], ctx["completion_record"]["id"]),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISCIPLINARY_HOLD)


def test_permanent_bar_blocks_new_application(api):
    """PRD §3.2: "A candidate whose `status` has become `BARRED` — the terminal
    consequence of a finalized permanent-bar sanction — can no longer open
    exam, recertification, reentry, or license applications, each attempt
    rejected with `ERR_PERMANENTLY_BARRED`."
    PRD §3.9: "`PERMANENT_BAR` additionally moves the candidate to `BARRED`."

    Design: Corner/errors/permanent_bar_blocks_new_application
    """
    ctx = setup_candidate_with_verified_completion()
    case = open_case(
        ctx["candidate"]["id"], violation_type="CRIMINAL_CONDUCT",
        description="Violent felony conviction",
    )
    walk_case_to_decided(case["id"], ctx["candidate"]["id"],
                         sanction_type="PERMANENT_BAR", findings="Substantiated")
    finalize_decided_case(case["id"])
    candidate = get_success_data(api_client.get_candidate(ctx["candidate"]["id"], ADMIN))
    assert candidate["status"] == "BARRED"

    resp = api_client.create_exam_application(
        create_exam_application_payload(ctx["level"]["id"], ctx["completion_record"]["id"]),
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PERMANENTLY_BARRED)


def test_recert_submit_before_window_fails(api):
    """PRD §3.6: "Submitting the portfolio re-checks the draft state and
    ownership, requires the submission instant to lie inside the pinned window
    (`ERR_RECERT_WINDOW_NOT_OPEN`)".
    PRD §3.6: "`cycle_window_start` is captured as the instant twelve calendar
    months before the certification's current `expires_on`".

    The certification expires 2028-09-04, so the window opens 2027-09-04; a
    submission at 2027-08-01 is rejected even with a complete portfolio.

    Design: Corner/errors/recert_submit_before_window_fails
    """
    ctx = setup_recert_draft_with_entries(recert_clock="2027-08-01T00:00:00Z")
    resp = api_client.submit_recert_application(
        ctx["recert_application"]["id"], make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RECERT_WINDOW_NOT_OPEN)


def test_reentry_approval_hours_shortfall(api):
    """PRD §3.7: "a `TIER_CE_ONLY` application must claim
    `ce_makeup_hours_claimed` of at least the level's `ce_total_hours`, and a
    `TIER_REFRESHER` application must claim `refresher_hours_claimed` of at
    least the level's `refresher_hours_required`, with shortfalls rejected as
    `ERR_REENTRY_REQUIREMENTS_UNMET`."

    Twenty claimed CE make-up hours fall below the 40-hour level minimum at
    decision time.

    Design: Corner/errors/reentry_approval_hours_shortfall
    """
    ctx = setup_lapsed_certification()
    reentry = create_reentry_application(
        ctx["candidate"]["id"], ctx["certification"]["id"], ce_makeup_hours_claimed=20,
    )
    assert reentry["tier"] == "TIER_CE_ONLY"
    resp = api_client.decide_reentry_application(
        reentry["id"], decision_payload("APPROVED"), ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REENTRY_REQUIREMENTS_UNMET)
    assert get_success_data(
        api_client.get_reentry_application(reentry["id"], ADMIN)
    )["status"] == "SUBMITTED"
