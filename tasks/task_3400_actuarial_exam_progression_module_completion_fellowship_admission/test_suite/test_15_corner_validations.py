"""Corner queue — validation protocol.

Auth header gate, role-before-state ordering, ownership, structural schema,
OCC stale versions, and the per-resource 404 sweep (PRD §2.1, §2.6, §2.8).
"""
from test_helpers import (
    ACADEMIC_REVIEWER,
    ANONYMOUS,
    ApiErrorId,
    CLOCK_REGISTRATION_CLOSED,
    DISCIPLINE_BOARD,
    EXAM_COMMITTEE,
    FEE_EARLY_CENTS,
    MODULE_M1_CODE,
    MODULE_M1_TITLE,
    MODULE_PASSING_SCORE,
    NON_EXISTENT_UUID,
    NO_ROLE_HEADERS,
    REGISTRAR,
    SECOND_SYLLABUS_CODE,
    TRACK_QFI,
    UNDECLARED_ROLE_HEADERS,
    activate_syllabus,
    cancel_registration,
    create_discipline_case_payload,
    create_exam_registration_payload,
    create_exam_window_payload,
    create_module_attempt_payload,
    create_pass_mark_setting_payload,
    create_vee_submission_payload,
    get_success_data,
    get_window,
    make_active_exam,
    make_candidate,
    make_candidate_headers,
    make_exam,
    make_grader_headers,
    make_module,
    make_syllabus,
    make_window,
    ratify_pass_mark_payload,
    set_clock,
    setup_associate,
    setup_enrollment,
    setup_registered,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or names no
    declared role — or whose `X-User-ID` header is missing for any role other
    than `Anonymous` — is rejected with `ERR_MISSING_HEADERS` (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    resp = api.get_candidate(NON_EXISTENT_UUID, NO_ROLE_HEADERS)
    validate_error(resp, ApiErrorId.ERR_MISSING_HEADERS)
    resp_bad_role = api.get_candidate(NON_EXISTENT_UUID, UNDECLARED_ROLE_HEADERS)
    validate_error(resp_bad_role, ApiErrorId.ERR_MISSING_HEADERS)


def test_role_beats_state_in_validation_order(api):
    """PRD §2.8: "2. **Role authorization.** The declared role must appear in
    the endpoint's authorized roles — violations yield
    `ERR_UNAUTHORIZED_ROLE`."
    PRD §2.8: "8. **State preconditions.** Target and parent states must admit
    the operation — the state-guard errors of §3, all HTTP 422."

    Design: Corner/validations/role_beats_state_in_validation_order
    """
    _, exam = make_active_exam(api, exam_code="P", title="Probability")
    window = make_window(api, exam["id"], window_code="P-2026-10")
    # Retire the exam so the window is CANCELLED (a state violation is armed).
    syl2 = make_syllabus(api, version_code=SECOND_SYLLABUS_CODE, credit_map={"P": "P2"})
    make_exam(api, syl2["id"], exam_code="P2", title="Probability (2026)")
    activate_syllabus(api, syl2["id"])
    assert get_window(api, window["id"])["status"] == "CANCELLED"

    # Registrar is not an authorized role for registration: the priority-2
    # role check fires long before the priority-8 window-state check.
    resp = api.create_exam_registration(
        create_exam_registration_payload(window["id"]), REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_ownership_forbidden_on_cancel(api):
    """PRD §2.1: "ownership checks on any resource that references a
    `Candidate` compare the resource's foreign-key field (its `candidate_id`,
    or the candidate id appearing in the request path) to `X-User-ID`, and a
    mismatch is rejected with `ERR_FORBIDDEN_OWNER` (HTTP 403)."
    PRD §3.3: "A registration can be cancelled by the owning candidate or by
    a `Registrar`."

    Design: Corner/validations/ownership_forbidden_on_cancel
    """
    ctx = setup_registered(api, num_candidates=1)
    candidate = ctx["candidates"][0]
    registration = ctx["registrations"][0]
    stranger = make_candidate(api)

    resp = api.cancel_exam_registration(
        registration["id"], make_candidate_headers(stranger["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNER)

    cancelled = cancel_registration(api, registration["id"], REGISTRAR)
    assert cancelled["logistics_status"] == "CANCELLED"
    assert cancelled["refund_cents"] == FEE_EARLY_CENTS


def test_schema_violations_return_400(api):
    """PRD §2.8: "3. **Structural schema gate.** The request body must be
    structurally sound: required fields present, types correct, enum values in
    range, conditional requirements met ... All such violations yield
    `ERR_INVALID_REQUEST`."
    PRD §3.4: "the `grade_points` earned on the 4.0 scale, which must lie
    between 0.0 and 4.0 inclusive."
    PRD §3.3: "The four timestamps must be ordered so that registration opens
    no later than the deadline, the deadline is no later than the start of
    testing, and the start of testing is no later than its end; any
    mis-ordering is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/schema_violations_return_400
    """
    candidate = make_candidate(api)
    headers = make_candidate_headers(candidate["id"])
    _, exam = make_active_exam(api)

    resp_missing = api.create_candidate({"full_name": "No Email"}, ANONYMOUS)
    validate_error(resp_missing, ApiErrorId.ERR_INVALID_REQUEST)

    resp_enum = api.create_vee_submission(
        create_vee_submission_payload(topic="PHYSICS"), headers)
    validate_error(resp_enum, ApiErrorId.ERR_INVALID_REQUEST)

    resp_range = api.create_vee_submission(
        create_vee_submission_payload(topic="ECONOMICS", grade_points=5.0), headers)
    validate_error(resp_range, ApiErrorId.ERR_INVALID_REQUEST)

    resp_dates = api.create_exam_window(
        create_exam_window_payload(exam["id"], window_code="BAD-1",
                                   registration_opens_at="2026-10-01T00:00:00Z",
                                   registration_deadline="2026-09-01T00:00:00Z"),
        REGISTRAR)
    validate_error(resp_dates, ApiErrorId.ERR_INVALID_REQUEST)


def test_occ_stale_window_version(api):
    """PRD §2.6: "A `POST /actuarial/exam-windows/{wid}/pass-mark-settings`
    request must carry `expected_exam_window_version` matching the target
    window's current `version`. If the window's version has advanced since the
    client last read it — because another committee writer has just created a
    setting (which legitimately supersedes the prior one), or because a clock
    sweep advanced the window — the create is rejected with
    `ERR_STALE_WINDOW_VERSION` (HTTP 412)."
    PRD §3.3: "The proposal is created `PROPOSED`, its creation supersedes any
    existing setting of the same window in `PROPOSED` or `RATIFIED` (which
    becomes `SUPERSEDED`), and the window's `version` increments by one."

    Design: Corner/validations/occ_stale_window_version
    """
    _, exam = make_active_exam(api)
    window = make_window(api, exam["id"], window_code="P-2026-10")
    set_clock(api, CLOCK_REGISTRATION_CLOSED)
    fresh = get_window(api, window["id"])
    assert fresh["status"] == "REGISTRATION_CLOSED"
    observed = fresh["version"]

    resp = api.create_pass_mark_setting(
        window["id"],
        create_pass_mark_setting_payload(6.0, observed - 1),
        EXAM_COMMITTEE)
    validate_error(resp, ApiErrorId.ERR_STALE_WINDOW_VERSION)

    created = validate_success(api.create_pass_mark_setting(
        window["id"],
        create_pass_mark_setting_payload(6.0, observed),
        EXAM_COMMITTEE), 201)
    assert created["status"] == "PROPOSED"
    assert get_window(api, window["id"])["version"] == observed + 1


def test_not_found_sweep(api):
    """PRD §2.8: "When an endpoint path contains multiple resource
    identifiers, the system resolves each identifier in sequential,
    left-to-right order — candidate, syllabus version, exam, window,
    registration, pass-mark setting, submission, attempt, project, session,
    attendance, attestation, case — and rejects the request immediately with
    the `404 Not Found` error of the *first* identifier that does not resolve,
    before examining anything further down the path."
    PRD §2.8: "Foreign keys supplied in a request body (such as `exam_id`,
    `syllabus_version_id`, `prerequisite_exam_id`, `exam_window_id`,
    `module_id`, `track_enrollment_id`, or `course_session_id`) are likewise
    resolved to existing resources, each failure producing the not-found error
    of the referenced resource type."

    Design: Corner/validations/not_found_sweep
    """
    candidate = make_candidate(api)
    headers = make_candidate_headers(candidate["id"])
    nf = NON_EXISTENT_UUID

    validate_error(api.get_candidate(nf, REGISTRAR), ApiErrorId.ERR_CANDIDATE_NOT_FOUND)
    validate_error(api.get_syllabus_version(nf, REGISTRAR),
                   ApiErrorId.ERR_SYLLABUS_VERSION_NOT_FOUND)
    validate_error(api.get_exam(nf, REGISTRAR), ApiErrorId.ERR_EXAM_NOT_FOUND)
    validate_error(api.get_exam_window(nf, REGISTRAR), ApiErrorId.ERR_EXAM_WINDOW_NOT_FOUND)
    validate_error(
        api.create_exam_window(create_exam_window_payload(nf, window_code="X-1"), REGISTRAR),
        ApiErrorId.ERR_EXAM_NOT_FOUND)
    validate_error(
        api.create_exam_registration(create_exam_registration_payload(nf), headers),
        ApiErrorId.ERR_EXAM_WINDOW_NOT_FOUND)
    validate_error(api.cancel_exam_registration(nf, REGISTRAR),
                   ApiErrorId.ERR_EXAM_REGISTRATION_NOT_FOUND)
    validate_error(
        api.ratify_pass_mark(nf, ratify_pass_mark_payload(6.5), EXAM_COMMITTEE),
        ApiErrorId.ERR_PASS_MARK_SETTING_NOT_FOUND)
    validate_error(
        api.review_vee_submission(nf, {"decision": "APPROVE"}, ACADEMIC_REVIEWER),
        ApiErrorId.ERR_VEE_SUBMISSION_NOT_FOUND)
    validate_error(
        api.submit_module_attempt(nf, {"score": 80}, headers),
        ApiErrorId.ERR_MODULE_ATTEMPT_NOT_FOUND)
    validate_error(
        api.grade_project_assessment(nf, {"score": 80}, make_grader_headers("grader-001")),
        ApiErrorId.ERR_PROJECT_ASSESSMENT_NOT_FOUND)
    validate_error(
        api.create_course_attendance({"course_session_id": nf}, headers),
        ApiErrorId.ERR_COURSE_SESSION_NOT_FOUND)
    validate_error(
        api.verify_course_attendance(nf, {"outcome": "ATTENDED"}, REGISTRAR),
        ApiErrorId.ERR_COURSE_ATTENDANCE_NOT_FOUND)
    validate_error(
        api.verify_cpd_attestation(nf, {"verified_hours": 10}, REGISTRAR),
        ApiErrorId.ERR_CPD_ATTESTATION_NOT_FOUND)
    validate_error(
        api.sanction_discipline_case(nf, {"resolution": "DISMISSED"}, DISCIPLINE_BOARD),
        ApiErrorId.ERR_DISCIPLINE_CASE_NOT_FOUND)

    # Body-FK legs on module-attempt creation, one failing FK at a time.
    associate = setup_associate(api, candidate=candidate)["candidate"]
    enrollment = setup_enrollment(api, associate, with_modules=False)["enrollment"]
    module = make_module(api, module_code=MODULE_M1_CODE, track_code=TRACK_QFI,
                         sequence_index=1, title=MODULE_M1_TITLE,
                         passing_score=MODULE_PASSING_SCORE)
    own = make_candidate_headers(associate["id"])
    validate_error(
        api.create_module_attempt(
            create_module_attempt_payload(enrollment["id"], NON_EXISTENT_UUID), own),
        ApiErrorId.ERR_MODULE_NOT_FOUND)
    validate_error(
        api.create_module_attempt(
            create_module_attempt_payload(NON_EXISTENT_UUID, module["id"]), own),
        ApiErrorId.ERR_TRACK_ENROLLMENT_NOT_FOUND)

    # Filing a case against a candidate id that does not resolve: PRD §2.8
    # body-FK resolution points at the not-found error, while the §3.9 filing
    # narrative names the standing error; either identifier satisfies the
    # reachability probe.
    resp_case = api.create_discipline_case(
        create_discipline_case_payload(NON_EXISTENT_UUID, charge="x", severity=5),
        REGISTRAR)
    assert validate_error_is_one_of(
        resp_case,
        [ApiErrorId.ERR_CANDIDATE_NOT_FOUND, ApiErrorId.ERR_CANDIDATE_NOT_ACTIVE])
