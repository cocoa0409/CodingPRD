"""Cross-cutting API conventions: authentication headers, role authorization
ordering, path/body existence checks, pagination rules and envelope shape,
and the logical clock's monotonicity."""
import pytest

from test_helpers import (
    api_client,
    fixtures,
    factories,
    TEST_USERS,
    make_applicant_headers,
    make_reviewer_headers,
    without_header,
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    ApiErrorId,
)

_PO = TEST_USERS["program_officer_headers"]
_SRO = TEST_USERS["sro_headers"]
_CM = TEST_USERS["council_member_headers"]
_GO = TEST_USERS["grants_officer_headers"]


def test_call_missing_auth_header_rejected():
    """PRD §2.1: "All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or carrying an empty value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/call_missing_auth_header_rejected
    """
    foa = fixtures.make_foa()
    resp = api_client.get_funding_opportunity(
        foa["id"], without_header(_PO, "X-User-ID"))
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_applicant_cannot_close_unknown_foa_role_precedes_existence():
    """PRD §2.7: "Every request is validated against a fixed, priority-ordered pipeline. When several checks could reject the same request, the earliest stage in this ordering wins, so the error a caller observes is always the highest-priority failure:"
    PRD §2.7: "2. **Role authorization.** The supplied role must be listed among the endpoint's authorized roles (`ERR_UNAUTHORIZED_ROLE`, HTTP 403)."
    PRD §2.7: "3. **Path existence, left to right.** Every resource id in the URL path must exist, validated in left-to-right order; the request is rejected with the not-found error (HTTP 404) of the *first* missing id, and a nested path under a missing parent never evaluates the child."
    The role check (stage 2) precedes path existence (stage 3), so an
    Applicant closing an unknown announcement observes the 403, not a 404.

    Design: Corner/validations/applicant_cannot_close_unknown_foa_role_precedes_existence
    """
    pi_a = fixtures.make_applicant()
    resp = api_client.close_funding_opportunity(
        NON_EXISTENT_UUID, make_applicant_headers(pi_a["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_reviewer_cannot_create_assignments():
    """PRD §2.1: "**ScientificReviewOfficer** — runs study sections, recruits reviewers, creates assignments, convenes meetings, and releases scores."
    PRD §2.7: "2. **Role authorization.** The supplied role must be listed among the endpoint's authorized roles (`ERR_UNAUTHORIZED_ROLE`, HTTP 403)."
    The role gate fires before any body foreign-key lookup, so the bogus
    application id in this payload is never evaluated.

    Design: Corner/rbac/reviewer_cannot_create_assignments
    """
    inst = fixtures.make_institution(name="Other College")
    rx = fixtures.make_reviewer(inst["id"], full_name="Rev X")
    resp = api_client.create_assignment(
        factories.create_assignment_payload(NON_EXISTENT_UUID, rx["id"], "PRIMARY"),
        make_reviewer_headers(rx["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_council_member_cannot_adjudicate_modification():
    """PRD §2.1: "**GrantsOfficer** — grants management officer; exercises select pay, adjudicates just-in-time packages, issues awards, accepts progress reports, adjudicates modifications, and drives transfers."
    PRD §2.7: "2. **Role authorization.** The supplied role must be listed among the endpoint's authorized roles (`ERR_UNAUTHORIZED_ROLE`, HTTP 403)."
    The role gate precedes existence, so the modification id is never looked
    up.

    Design: Corner/rbac/council_member_cannot_adjudicate_modification
    """
    resp = api_client.adjudicate_modification(
        NON_EXISTENT_UUID, factories.modification_adjudicate_payload("APPROVE"), _CM)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_unknown_body_fk_rejected():
    """PRD §2.7: "4. **Body foreign keys.** Ids referenced in the request body — `foa_id`, `institution_id`, `requested_study_section_id`, `requested_institute_id`, `reviewer_id`, `application_id`, `to_institution_id` — must exist, rejecting with the same 404 family."

    Design: Corner/errors/unknown_body_fk_rejected
    """
    resp = api_client.create_reviewer(
        factories.create_reviewer_payload(NON_EXISTENT_UUID, full_name="Rev Ghost"),
        _SRO)
    validate_error(resp, ApiErrorId.ERR_INSTITUTION_NOT_FOUND)


def test_resource_not_found_sweep():
    """PRD §2.7: "3. **Path existence, left to right.** Every resource id in the URL path must exist, validated in left-to-right order; the request is rejected with the not-found error (HTTP 404) of the *first* missing id, and a nested path under a missing parent never evaluates the child."
    PRD §2.7: "The not-found family is: `ERR_FOA_NOT_FOUND`, `ERR_INSTITUTE_NOT_FOUND`, `ERR_INSTITUTION_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_STUDY_SECTION_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_JIT_REQUEST_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_PROGRESS_REPORT_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`, `ERR_TRANSFER_REQUEST_NOT_FOUND`."

    Design: Corner/errors/resource_not_found_sweep
    """
    validate_error(api_client.get_funding_opportunity(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_FOA_NOT_FOUND)
    validate_error(api_client.get_institute(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_INSTITUTE_NOT_FOUND)
    validate_error(api_client.get_institution(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_INSTITUTION_NOT_FOUND)
    validate_error(api_client.get_applicant(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_APPLICANT_NOT_FOUND)
    validate_error(api_client.get_reviewer(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_REVIEWER_NOT_FOUND)
    validate_error(api_client.get_assignment(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND)
    validate_error(api_client.get_jit_request(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_JIT_REQUEST_NOT_FOUND)
    validate_error(api_client.get_award(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_AWARD_NOT_FOUND)
    # Award-scoped sub-resource lists resolve the parent award segment first.
    validate_error(api_client.list_progress_reports(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_AWARD_NOT_FOUND)
    validate_error(api_client.list_award_modifications(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_AWARD_NOT_FOUND)
    validate_error(api_client.get_transfer_request(NON_EXISTENT_UUID, _PO),
                   ApiErrorId.ERR_TRANSFER_REQUEST_NOT_FOUND)


def test_progress_report_and_modification_ids_not_found():
    """PRD §2.7: "3. **Path existence, left to right.** Every resource id in the URL path must exist, validated in left-to-right order; the request is rejected with the not-found error (HTTP 404) of the *first* missing id, and a nested path under a missing parent never evaluates the child."
    PRD §2.7: "The not-found family is: `ERR_FOA_NOT_FOUND`, `ERR_INSTITUTE_NOT_FOUND`, `ERR_INSTITUTION_NOT_FOUND`, `ERR_APPLICANT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_STUDY_SECTION_NOT_FOUND`, `ERR_REVIEWER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_JIT_REQUEST_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_PROGRESS_REPORT_NOT_FOUND`, `ERR_MODIFICATION_NOT_FOUND`, `ERR_TRANSFER_REQUEST_NOT_FOUND`."

    Design: Corner/errors/progress_report_and_modification_ids_not_found
    """
    validate_error(api_client.accept_progress_report(NON_EXISTENT_UUID, _GO),
                   ApiErrorId.ERR_PROGRESS_REPORT_NOT_FOUND)
    validate_error(
        api_client.adjudicate_modification(
            NON_EXISTENT_UUID, factories.modification_adjudicate_payload("APPROVE"), _GO),
        ApiErrorId.ERR_MODIFICATION_NOT_FOUND)


def test_list_applications_filter_and_pagination_envelope():
    """PRD §3.1: "The applications collection can be filtered by `foa_id`, `applicant_id`, `institution_id`, `requested_study_section_id`, `requested_institute_id`, `study_section_id`, `institute_id`, or `status`."
    PRD §2.3: "List-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/endpoints/list_applications_filter_and_pagination_envelope
    """
    ctx = fixtures.make_review_context()
    pi1, pi2, pi3 = (fixtures.make_applicant() for _ in range(3))
    foa_id = ctx["foa"]["id"]
    inst_id = ctx["institution"]["id"]
    l1 = fixtures.make_draft_application(foa_id, inst_id, pi1["id"], title="L1")
    l2 = fixtures.make_draft_application(foa_id, inst_id, pi2["id"], title="L2")
    l3 = fixtures.create_submitted_application(foa_id, inst_id, pi3["id"], title="L3")

    data_sub, meta_sub = validate_paginated(
        api_client.list_applications(_PO, params={"foa_id": foa_id, "status": "SUBMITTED"}))
    assert len(data_sub) == 1 and data_sub[0]["id"] == l3["id"]
    assert meta_sub["total_count"] == 1 and meta_sub["has_more"] is False
    assert isinstance(meta_sub["api_request_id"], str) and meta_sub["api_request_id"]
    assert isinstance(meta_sub["api_request_timestamp"], str) and meta_sub["api_request_timestamp"]

    data_page, meta_page = validate_paginated(
        api_client.list_applications(
            _PO, params={"foa_id": foa_id, "status": "DRAFT", "limit": 1, "offset": 1}))
    assert len(data_page) == 1
    assert meta_page["total_count"] == 2 and meta_page["has_more"] is False

    data_all, meta_all = validate_paginated(
        api_client.list_applications(_PO, params={"foa_id": foa_id, "status": "DRAFT"}))
    assert len(data_all) == 2 and meta_all["has_more"] is False
    assert {d["id"] for d in data_all} == {l1["id"], l2["id"]}


def test_invalid_pagination_params_rejected():
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip; it defaults to 0 and may not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_INVALID_PAGINATION_PARAMETERS`."

    Design: Corner/endpoints/invalid_pagination_params_rejected
    """
    inst = fixtures.make_institution(name="Other College")
    fixtures.make_reviewer(inst["id"])
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        resp = api_client.list_reviewers(_PO, params=params)
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS)


def test_clock_regression_rejected():
    """PRD §2.4: "Every deadline, window, and expiry rule in the system reads a **logical clock** rather than wall-clock time. Before any clock operation is performed, the logical clock starts at exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time thereafter."
    PRD §2.4: "A `ProgramOfficer` may advance the clock through an admin-only, test-driving capability mounted outside the business surface at `/_clock/set_current_utc`, supplying `to_iso8601`, which must be a valid ISO 8601 UTC timestamp and must not be earlier than the current logical time: the clock is monotonic non-decreasing, and a malformed or regressive value is rejected with `ERR_INVALID_CLOCK_VALUE`."

    Design: Corner/cross_cutting_layers/clock_regression_rejected
    """
    # 2026-08-01 precedes the startup default 2026-09-01T00:00:00Z.
    regressive = api_client.set_clock(
        factories.set_clock_payload("2026-08-01T00:00:00Z"), _PO)
    validate_error(regressive, ApiErrorId.ERR_INVALID_CLOCK_VALUE)

    forward = api_client.set_clock(
        factories.set_clock_payload("2026-09-15T00:00:00Z"), _PO)
    data = validate_success(forward, 200)
    assert data["current_utc"] == "2026-09-15T00:00:00Z"
