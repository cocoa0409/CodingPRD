"""Queue B — validations: the §2.8 tier order (headers, role, shape, existence,
OCC, state) and the quota gates at exam-application approval.
"""
from test_helpers import (
    ADMIN,
    ANONYMOUS_HEADERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    advance_clock,
    cat_fail_responses,
    create_approved_exam_application,
    create_candidate,
    create_completion_record_payload,
    create_exam_application,
    create_level,
    create_program,
    create_remedial_record,
    decision_payload,
    deliver_attempt,
    get_success_data,
    make_candidate_headers,
    make_program_director_headers,
    record_accreditation_event,
    refresh_certification,
    schedule_attempt,
    setup_candidate_with_consumed_attempts,
    setup_certified_candidate,
    validate_error,
)


def test_missing_auth_headers_fail(api):
    """PRD §2.1: "Every request other than candidate self-registration must
    carry two HTTP headers: `X-User-ID`, identifying the acting user, and
    `X-User-Role`, naming their operational capacity. A request to any
    authenticated endpoint that arrives with either header missing or empty is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_headers_fail
    """
    create_level()
    resp = api_client.list_level_definitions(ANONYMOUS_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_shape_error_beats_existence(api):
    """PRD §2.8: "When several checks could reject the same request, the system
    evaluates them in a fixed tier order and reports the first failure:"
    PRD §2.8: "3. **Request shape.** Required fields are present, types match,
    enum values are valid, station lists are non-empty, a scheduling window's
    end is strictly after its start, examination dates are not in the future,
    hour quantities are positive, and a response-delivery payload carries no
    more than twelve item responses (`ERR_INVALID_REQUEST`)."
    PRD §2.8: "4. **Existence.** Path identifiers must exist, validated left to
    right so that the first missing identifier in the path is the one reported,
    and every record referenced in the body must exist (`ERR_NOT_FOUND`)."

    A request missing the required level_id AND referencing a nonexistent
    completion record fails shape validation, never existence.

    Design: Corner/validations/shape_error_beats_existence
    """
    candidate = create_candidate()
    resp = api_client.create_exam_application(
        {"completion_record_id": NON_EXISTENT_UUID},
        make_candidate_headers(candidate["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_occ_checked_before_state(api):
    """PRD §2.7: "The concurrency check is evaluated immediately after existence
    checks and before any state-machine precondition."
    PRD §2.9: "Every mutation, whether client-driven, sweep-driven, or
    cascade-driven, refreshes the mutated resource's `updated_at` and
    increments its `version` on the resources that carry those fields."
    PRD §2.5: "Certifications `ACTIVE` whose `expires_on` is earlier than now
    become `LAPSED`."

    The lapse sweep advances the certification's version, so a recertification
    create carrying the pre-lapse version fails the concurrency check (412)
    before the state gate (409) is ever evaluated.

    Design: Corner/validations/occ_checked_before_state
    """
    ctx = setup_certified_candidate()
    stale_version = ctx["certification"]["version"]
    advance_clock("2028-09-05T00:00:00Z")
    cert = refresh_certification(ctx["certification"]["id"])
    assert cert["status"] == "LAPSED"
    assert cert["version"] > stale_version

    resp = api_client.create_recert_application(
        {"certification_id": cert["id"], "model": "NCCP",
         "expected_certification_version": stale_version},
        make_candidate_headers(ctx["candidate"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_program_suspended_at_completion_fails(api):
    """PRD §3.3: "the program's accreditation status effective at the completion
    date — read from the accreditation history by each entry's `effective_date`
    — must have been `ACCREDITED` or `PROVISIONAL`, otherwise the attestation is
    rejected with `ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION`."

    A completion dated inside a SUSPENDED interval is rejected at creation.

    Design: Corner/validations/program_suspended_at_completion_fails
    """
    level = create_level()
    program = create_program(level["id"])
    record_accreditation_event(
        program["id"], "SUSPENDED", "2026-09-15", reason="Site visit failures",
    )
    candidate = create_candidate()
    resp = api_client.create_program_completion_record(
        create_completion_record_payload(
            candidate["id"], program["id"], completion_date="2026-10-01",
        ),
        make_program_director_headers(program["director_user_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION)


def test_remedial_gate_then_attempt_cap(api):
    """PRD §3.4: "Two quota gates close the review: the basis must have consumed
    fewer than six attempts (`ERR_ATTEMPT_LIMIT_REACHED`), and once three or
    more attempts have been consumed on the basis, a **remedial education
    record** must exist for this candidate and level with `hours` of at least
    the level's `remedial_hours_required` and a `completed_date` strictly after
    the delivered date of the third failed attempt on the basis
    (`ERR_REMEDIAL_REQUIRED`)."

    The fourth approval is rejected until a qualifying remedial record exists;
    the seventh approval hits the hard cap of six consumed attempts.

    Design: Corner/validations/remedial_gate_then_attempt_cap
    """
    ctx = setup_candidate_with_consumed_attempts(3)
    candidate_id = ctx["candidate"]["id"]
    level_id = ctx["level"]["id"]
    record_id = ctx["completion_record"]["id"]

    app4 = create_exam_application(candidate_id, level_id, record_id)
    resp = api_client.decide_exam_application(app4["id"], decision_payload("APPROVED"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_REMEDIAL_REQUIRED)

    # The third failure was delivered 2026-10-07; remediation completed the day
    # after satisfies the strictly-after requirement.
    create_remedial_record(candidate_id, level_id, hours=20, completed_date="2026-10-08")
    approved4 = get_success_data(api_client.decide_exam_application(
        app4["id"], decision_payload("APPROVED"), ADMIN,
    ))
    attempt4 = schedule_attempt(
        candidate_id, approved4["att_id"], "2026-10-23T00:00:00Z", "2026-10-25T00:00:00Z",
    )
    advance_clock("2026-10-24T12:00:00Z")
    deliver_attempt(attempt4["id"], cat_fail_responses())

    app5 = create_approved_exam_application(candidate_id, level_id, record_id)
    attempt5 = schedule_attempt(
        candidate_id, app5["att_id"], "2026-11-09T00:00:00Z", "2026-11-11T00:00:00Z",
    )
    advance_clock("2026-11-10T12:00:00Z")
    deliver_attempt(attempt5["id"], cat_fail_responses())

    app6 = create_approved_exam_application(candidate_id, level_id, record_id)
    attempt6 = schedule_attempt(
        candidate_id, app6["att_id"], "2026-11-26T00:00:00Z", "2026-11-28T00:00:00Z",
    )
    advance_clock("2026-11-27T12:00:00Z")
    scored6 = deliver_attempt(attempt6["id"], cat_fail_responses())
    assert scored6["attempt_number"] == 6

    app7 = create_exam_application(candidate_id, level_id, record_id)
    resp7 = api_client.decide_exam_application(app7["id"], decision_payload("APPROVED"), ADMIN)
    validate_error(resp7, ApiErrorId.ERR_ATTEMPT_LIMIT_REACHED)
