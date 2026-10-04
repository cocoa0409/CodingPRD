"""Corner queue — RBAC segregation and endpoint conditional gates.

Role authorization violations (PRD §2.1, §4), the candidate-record OCC guard
(PRD §2.6), and endpoint-level gates (PRD §3.2–§3.5).
"""
from test_helpers import (
    ANONYMOUS,
    ApiErrorId,
    CLOCK_REGISTRATION_CLOSED,
    CLOCK_SCORING,
    DISCIPLINE_BOARD,
    EXAM_COMMITTEE,
    NON_EXISTENT_UUID,
    RAW_SCORE_AT_MARK,
    REGISTRAR,
    TRACK_ILA,
    TRACK_QFI,
    activate_syllabus,
    approve_all_vee_topics,
    cancel_registration,
    create_credential_application_payload,
    create_discipline_case_payload,
    create_exam_registration_payload,
    create_exam_window_payload,
    create_pass_mark_setting_payload,
    create_track_enrollment_payload,
    file_case,
    get_candidate,
    get_success_data,
    get_window,
    make_active_exam,
    make_candidate,
    make_candidate_headers,
    make_exam,
    make_grader_headers,
    make_syllabus,
    make_window,
    propose_ratify_publish,
    record_score,
    register,
    set_clock,
    setup_associate,
    setup_open_window,
    setup_registered,
    validate_error,
    validate_success,
)


def test_rbac_committee_cannot_administer_windows(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /actuarial/exam-windows is authorized for Registrar only.

    Design: Corner/rbac/rbac_committee_cannot_administer_windows
    """
    resp = api.create_exam_window(
        create_exam_window_payload(NON_EXISTENT_UUID, window_code="X-1"),
        EXAM_COMMITTEE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_rbac_grader_cannot_review_vee(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /actuarial/vee-submissions/{id}/review is authorized for
    AcademicReviewer only.

    Design: Corner/rbac/rbac_grader_cannot_review_vee
    """
    resp = api.review_vee_submission(
        NON_EXISTENT_UUID, {"decision": "APPROVE"}, make_grader_headers("grader-001"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_rbac_board_cannot_file_case(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /actuarial/discipline-cases is authorized for Registrar only.

    Design: Corner/rbac/rbac_board_cannot_file_case
    """
    candidate = make_candidate(api)
    resp = api.create_discipline_case(
        create_discipline_case_payload(candidate["id"], charge="self-filed", severity=5),
        DISCIPLINE_BOARD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_rbac_registrar_cannot_sanction(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /actuarial/discipline-cases/{id}/sanction is authorized for
    DisciplineBoard only.

    Design: Corner/rbac/rbac_registrar_cannot_sanction
    """
    candidate = make_candidate(api)
    case = file_case(api, candidate["id"], charge="Misconduct", severity=5)
    resp = api.sanction_discipline_case(case["id"], {"resolution": "REPRIMAND"}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_rbac_anonymous_cannot_read_candidates(api):
    """PRD §2.1: "A request whose role is not listed among the roles
    authorized for the target endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: GET /actuarial/candidates/{id} is authorized for Candidate and
    Registrar only.

    Design: Corner/rbac/rbac_anonymous_cannot_read_candidates
    """
    candidate = make_candidate(api)
    resp = api.get_candidate(candidate["id"], ANONYMOUS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_occ_stale_candidate_version(api):
    """PRD §2.6: "A `POST /actuarial/credential-applications` request must
    carry `expected_candidate_version` matching the acting candidate's current
    `version`. Every credential application, whether approved or denied,
    advances the candidate's `version` (the evaluation stamps
    `last_evaluated_at`, and an approval additionally advances the membership
    tier), so a second application carrying a previously observed version is
    stale. A mismatch is rejected with `ERR_STALE_CANDIDATE_VERSION`
    (HTTP 412)."

    Design: Corner/validations/occ_stale_candidate_version
    """
    ctx = setup_open_window(api)
    candidate = make_candidate(api)
    headers = make_candidate_headers(candidate["id"])
    registration = register(api, ctx["window"]["id"], candidate)
    set_clock(api, CLOCK_SCORING)
    record_score(api, registration["id"], RAW_SCORE_AT_MARK)
    propose_ratify_publish(api, ctx["window"]["id"])
    approve_all_vee_topics(api, candidate)

    observed = get_candidate(api, candidate["id"])["version"]
    approved = validate_success(api.create_credential_application(
        create_credential_application_payload("ASA", observed), headers), 201)
    assert approved["status"] == "APPROVED"

    # The approval advanced the candidate version; the pre-approval reading is
    # now stale for the FSA filing.
    resp = api.create_credential_application(
        create_credential_application_payload("FSA", observed), headers)
    validate_error(resp, ApiErrorId.ERR_STALE_CANDIDATE_VERSION)


def test_window_create_requires_active_exam(api):
    """PRD §3.3: "The exam must be `ACTIVE` — scheduling a window for an exam
    in any other state is rejected with `ERR_EXAM_NOT_ACTIVE`."

    Design: Corner/endpoints/window_create_requires_active_exam
    """
    syllabus = make_syllabus(api, version_code="2026-A")
    exam = make_exam(api, syllabus["id"], exam_code="P", title="Probability")
    assert exam["status"] == "DRAFT"
    resp = api.create_exam_window(
        create_exam_window_payload(exam["id"], window_code="P-2026-10"), REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_EXAM_NOT_ACTIVE)

    activate_syllabus(api, syllabus["id"])
    created = validate_success(api.create_exam_window(
        create_exam_window_payload(exam["id"], window_code="P-2026-10"), REGISTRAR), 201)
    assert created["status"] == "SCHEDULED"


def test_duplicate_registration_conflict(api):
    """PRD §3.3: "the candidate must not already hold a registration for the
    same window whose `logistics_status` is `REGISTERED` or `WAITLISTED`; such
    a duplicate is rejected with `ERR_DUPLICATE_REGISTRATION`."

    Design: Corner/endpoints/duplicate_registration_conflict
    """
    ctx = setup_registered(api, num_candidates=1)
    candidate = ctx["candidates"][0]
    registration = ctx["registrations"][0]
    headers = make_candidate_headers(candidate["id"])

    resp = api.create_exam_registration(
        create_exam_registration_payload(ctx["window"]["id"]), headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REGISTRATION)

    cancel_registration(api, registration["id"], headers)
    # The uniqueness gate covers only active rows: after cancellation the
    # candidate may register anew.
    again = validate_success(api.create_exam_registration(
        create_exam_registration_payload(ctx["window"]["id"]), headers), 201)
    assert again["logistics_status"] == "REGISTERED"


def test_enrollment_requires_associate_and_single_active(api):
    """PRD §3.5: "Enrollment requires the candidate to be `ACTIVE` and, per
    the stage gate of §2.9, to hold the `ASSOCIATE` or `FELLOW` tier — a
    `CANDIDATE`-tier attempt is rejected with `ERR_REQUIRES_ASSOCIATE`."
    PRD §3.5: "A candidate may hold only one live enrollment at a time: when
    an enrollment in `ENROLLED` or `CAPSTONE_ELIGIBLE` already exists, another
    enrollment is rejected with `ERR_ENROLLMENT_ACTIVE_EXISTS`."

    Design: Corner/endpoints/enrollment_requires_associate_and_single_active
    """
    candidate = make_candidate(api)
    headers = make_candidate_headers(candidate["id"])
    resp_early = api.create_track_enrollment(
        create_track_enrollment_payload(TRACK_QFI), headers)
    validate_error(resp_early, ApiErrorId.ERR_REQUIRES_ASSOCIATE)

    setup_associate(api, candidate=candidate)
    enrollment = validate_success(api.create_track_enrollment(
        create_track_enrollment_payload(TRACK_QFI), headers), 201)
    assert enrollment["status"] == "ENROLLED"

    resp_dup = api.create_track_enrollment(
        create_track_enrollment_payload(TRACK_ILA), headers)
    validate_error(resp_dup, ApiErrorId.ERR_ENROLLMENT_ACTIVE_EXISTS)


def test_pass_mark_create_too_early_and_supersede(api):
    """PRD §3.3: "the window must be `REGISTRATION_CLOSED`, `TESTING`, or
    `SCORING` — a proposal at any other window state is rejected with
    `ERR_PASS_MARK_INVALID_STATE`."
    PRD §3.3: "The proposal is created `PROPOSED`, its creation supersedes any
    existing setting of the same window in `PROPOSED` or `RATIFIED` (which
    becomes `SUPERSEDED`), and the window's `version` increments by one."

    Design: Corner/endpoints/pass_mark_create_too_early_and_supersede
    """
    ctx = setup_open_window(api)
    window_id = ctx["window"]["id"]

    resp_early = api.create_pass_mark_setting(
        window_id,
        create_pass_mark_setting_payload(6.0, ctx["window"]["version"]),
        EXAM_COMMITTEE)
    validate_error(resp_early, ApiErrorId.ERR_PASS_MARK_INVALID_STATE)

    set_clock(api, CLOCK_REGISTRATION_CLOSED)
    version = get_window(api, window_id)["version"]
    first = validate_success(api.create_pass_mark_setting(
        window_id, create_pass_mark_setting_payload(6.0, version), EXAM_COMMITTEE), 201)
    assert first["status"] == "PROPOSED"

    version = get_window(api, window_id)["version"]
    second = validate_success(api.create_pass_mark_setting(
        window_id, create_pass_mark_setting_payload(6.5, version), EXAM_COMMITTEE), 201)
    assert second["status"] == "PROPOSED"

    rows = get_success_data(api.list_pass_mark_settings(window_id, EXAM_COMMITTEE))
    assert len(rows) == 2
    # created_at ASC: the older setting was superseded by the second create.
    assert rows[0]["id"] == first["id"] and rows[0]["status"] == "SUPERSEDED"
    assert rows[1]["id"] == second["id"] and rows[1]["status"] == "PROPOSED"


def test_response_envelope_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/endpoints/response_envelope_shape
    """
    resp = api.create_candidate(
        {"email": "env@example.com", "full_name": "Env Check"}, ANONYMOUS)
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["data"]["id"] == data["id"]

    resp_err = api.get_candidate(data["id"], EXAM_COMMITTEE)
    error_data = validate_error(resp_err, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    err_body = resp_err.json()
    assert err_body["response_type"] == "error"
    assert error_data["error_id"] == "ERR_UNAUTHORIZED_ROLE"
    assert isinstance(error_data["message"], str) and error_data["message"]
    assert set(err_body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
