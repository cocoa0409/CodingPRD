"""Member registration, eligibility verification, and member-scoped RBAC tests."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    build_user_headers, validate_error, validate_paginated, validate_success,
)
from test_helpers import factories, fixtures

INTAKE = TEST_USERS["intake_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_member_create_returns_declared_fields(api):
    """PRD section 3.1: "At registration the member's `verification_status` is
    `UNVERIFIED` and their `engagement_status` is `INACTIVE`; the system-maintained
    `verified_service_era` and `verified_injury_connection` remain null until a
    case decision sets them, and the computed `total_monthly_compensation_cents`
    starts at 0."
    PRD section 2.4: "an integer `version` that starts at its initial value and
    increments by 1 on every mutation of that resource."

    Design: Corner/entities/member_create_returns_declared_fields
    """
    fixtures.reset_clock()
    payload = factories.create_member_payload(full_name="Jordan Lee", branch_of_service="ARMY")
    resp = api.create_member(payload, INTAKE)
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"].get("api_request_id"), "success envelope must carry meta.api_request_id"
    assert body["meta"].get("api_request_timestamp"), "success envelope must carry meta.api_request_timestamp"
    assert data["full_name"] == "Jordan Lee"
    assert data["branch_of_service"] == "ARMY"
    assert data["verification_status"] == "UNVERIFIED"
    assert data["engagement_status"] == "INACTIVE"
    assert data["total_monthly_compensation_cents"] == 0
    assert data["version"] == 1
    assert data["verified_service_era"] is None
    assert data["verified_injury_connection"] is None


def test_eligibility_case_starts_under_review(api):
    """PRD section 3.1: "Creating a case has a blunt consequence: any existing
    case for the same member in `UNDER_REVIEW` or `PENDED` is automatically moved
    to `SUPERSEDED`, the member's `version` increments by 1, and the new case
    starts in `UNDER_REVIEW`."
    PRD section 3.1: "A decision takes the case from `UNDER_REVIEW` to either
    `VERIFIED` or `DENIED`; both stamp `decided_at` from the logical clock."

    Design: Corner/state_machines/eligibility_case_starts_under_review
    """
    fixtures.reset_clock()
    member = fixtures.create_member(full_name="Init Vet")
    resp = api.create_eligibility_case(
        factories.create_eligibility_case_payload(member["id"], member["version"]), INTAKE)
    case = validate_success(resp, 201)
    assert case["status"] == "UNDER_REVIEW"
    assert case["version"] == 1
    assert case["decided_at"] is None


def test_eligibility_pend_resume_cycle(api):
    """PRD section 3.1: "From `UNDER_REVIEW`, an `IntakeCoordinator` may pend the
    case, moving it to `PENDED` and recording the supplied `pend_reason`; a pended
    case can later resume to `UNDER_REVIEW`. Attempting either step from the wrong
    state fails with `ERR_INVALID_STATE`."
    PRD section 3.1: "`VERIFIED`, `DENIED`, and `SUPERSEDED` are terminal for a case."

    Design: Difficulty/non_linear_state_machine/eligibility_pend_resume_cycle
    """
    fixtures.reset_clock()
    member = fixtures.create_member(full_name="Cycle Member")
    case = fixtures.open_eligibility_case(member["id"], member["version"])

    r1 = validate_success(api.transition_eligibility_case(
        case["id"], factories.case_transition_payload("PENDED", pend_reason="awaiting DD-214"), INTAKE))
    assert r1["status"] == "PENDED"
    r2 = validate_success(api.transition_eligibility_case(
        case["id"], factories.case_transition_payload("UNDER_REVIEW"), INTAKE))
    assert r2["status"] == "UNDER_REVIEW"
    r3 = validate_success(api.transition_eligibility_case(
        case["id"], factories.case_transition_payload("PENDED", pend_reason="awaiting medical nexus letter"), INTAKE))
    assert r3["status"] == "PENDED"
    r4 = validate_success(api.transition_eligibility_case(
        case["id"], factories.case_transition_payload("UNDER_REVIEW"), INTAKE))
    assert r4["status"] == "UNDER_REVIEW"

    r5 = validate_success(api.transition_eligibility_case(
        case["id"], factories.verify_decision_payload(), INTAKE))
    assert r5["status"] == "VERIFIED"
    assert r5["version"] == 6, "creation version 1 plus five transitions"

    err_resp = api.transition_eligibility_case(
        case["id"], factories.case_transition_payload("PENDED", pend_reason="too late"), INTAKE)
    validate_error(err_resp, ApiErrorId.ERR_INVALID_STATE)

    cases = fixtures.list_eligibility_cases(member["id"])
    assert cases[0]["pend_reason"] == "awaiting medical nexus letter", "the latest pend wins"
    member_after = fixtures.get_member(member["id"])
    assert member_after["verification_status"] == "VERIFIED"


def test_member_parallel_dimensions_evolve_independently(api):
    """PRD section 3.1: "When verification succeeds, the member's
    `verification_status` becomes `VERIFIED`, the case's `verified_service_era`
    and `verified_injury_connection` are copied onto the member record, and the
    member's `version` increments by 1."
    PRD section 3.2: "it is `ENGAGED` while the member holds at least one
    enrollment in `INTAKE`, `ACTIVE`, or `SUSPENDED`; `GRADUATED` when no
    enrollment remains in those states and at least one sits in `COMPLETED`; and
    `INACTIVE` when none remain active and none are completed."

    Design: Difficulty/non_linear_state_machine/member_parallel_dimensions_evolve_independently
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=5)
    member = fixtures.create_member(full_name="Parallel Member")
    assert member["verification_status"] == "UNVERIFIED"
    assert member["engagement_status"] == "INACTIVE"

    verified = fixtures.verify_member(member)
    assert verified["verification_status"] == "VERIFIED"
    assert verified["engagement_status"] == "INACTIVE", "verification moved alone"

    enrollment = fixtures.create_enrollment(verified["id"], track["id"])
    engaged = fixtures.get_member(member["id"])
    assert engaged["engagement_status"] == "ENGAGED"
    assert engaged["verification_status"] == "VERIFIED", "engagement moved alone"

    fixtures.add_assessment(enrollment["id"])
    fixtures.complete_enrollment(enrollment["id"])
    graduated = fixtures.get_member(member["id"])
    assert graduated["engagement_status"] == "GRADUATED"
    assert graduated["verification_status"] == "VERIFIED"


def test_enrollment_requires_member_verified(api):
    """PRD section 3.2: "First, the member's `verification_status` must be
    `VERIFIED` — otherwise `ERR_MEMBER_NOT_VERIFIED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_member_verified
    """
    fixtures.reset_clock()
    track = fixtures.create_program_track(track_code="MENTAL_HEALTH", capacity=5)
    member = fixtures.create_member(full_name="Gate Vet")

    err_resp = api.create_enrollment(
        factories.create_enrollment_payload(member["id"], track["id"]), INTAKE)
    validate_error(err_resp, ApiErrorId.ERR_MEMBER_NOT_VERIFIED)
    assert fixtures.list_enrollments(member_id=member["id"]) == []

    verified = fixtures.verify_member(member)
    ok_resp = api.create_enrollment(
        factories.create_enrollment_payload(verified["id"], track["id"]), INTAKE)
    enrollment = validate_success(ok_resp, 201)
    assert enrollment["status"] == "INTAKE"
    assert fixtures.get_track_by_code("MENTAL_HEALTH")["active_enrollment_count"] == 1


def test_verify_pre911_veteran_rejected(api):
    """PRD section 3.1: "the decision payload's `verified_service_era` must be
    `POST_911`, and either the member's `member_type` must be `FAMILY_SUPPORT` or
    the payload's `verified_injury_connection` must be `SERVICE_CONNECTED`. A
    decision that fails this policy is rejected with
    `ERR_ELIGIBILITY_CRITERIA_NOT_MET` (HTTP 409)."

    Design: Corner/validations/verify_pre911_veteran_rejected
    """
    fixtures.reset_clock()
    member = fixtures.create_member(full_name="Gulf Era Vet", service_era_claimed="PRE_911_GULF")
    case = fixtures.open_eligibility_case(member["id"], member["version"])

    err_resp = api.transition_eligibility_case(
        case["id"],
        factories.verify_decision_payload(verified_service_era="PRE_911_GULF",
                                          verified_injury_connection="SERVICE_CONNECTED"),
        INTAKE)
    validate_error(err_resp, ApiErrorId.ERR_ELIGIBILITY_CRITERIA_NOT_MET)

    cases = fixtures.list_eligibility_cases(member["id"])
    assert cases[0]["status"] == "UNDER_REVIEW"
    assert fixtures.get_member(member["id"])["verification_status"] == "UNVERIFIED"


def test_family_support_injury_exemption_passes(api):
    """PRD section 3.1: "the decision payload's `verified_service_era` must be
    `POST_911`, and either the member's `member_type` must be `FAMILY_SUPPORT` or
    the payload's `verified_injury_connection` must be `SERVICE_CONNECTED`."

    Design: Corner/validations/family_support_injury_exemption_passes
    """
    fixtures.reset_clock()
    member = fixtures.create_member(
        full_name="Family Fay", member_type="FAMILY_SUPPORT",
        injury_connection_claimed="NON_SERVICE_CONNECTED")
    case = fixtures.open_eligibility_case(member["id"], member["version"])

    resp = api.transition_eligibility_case(
        case["id"],
        factories.verify_decision_payload(verified_service_era="POST_911",
                                          verified_injury_connection="NON_SERVICE_CONNECTED"),
        INTAKE)
    decided = validate_success(resp)
    assert decided["status"] == "VERIFIED"

    member_after = fixtures.get_member(member["id"])
    assert member_after["verification_status"] == "VERIFIED"
    assert member_after["verified_injury_connection"] == "NON_SERVICE_CONNECTED"


def test_member_create_family_with_branch_returns_invalid_request(api):
    """PRD section 3.1: "A `branch_of_service` (`ARMY`, `NAVY`, `AIR_FORCE`,
    `MARINES`, `COAST_GUARD`, or `SPACE_FORCE`) may be supplied for a veteran; it
    must be null for a `FAMILY_SUPPORT` member and defaults to null when omitted."
    PRD section 2.7: "All required input fields are present, enum values fall
    within their declared sets, integer ranges are honored (domain scores 0
    through 10, Likert items 1 through 5, disability rating steps of 10 within 0
    through 100, non-negative amounts), datetime fields parse, `treatment_end` is
    strictly after `treatment_start`, `ends_at` is strictly after `starts_at`,
    `period_end` is greater than or equal to `period_start`, and a supplied
    `track_weights` map sums to exactly 1.0 — otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/member_create_family_with_branch_returns_invalid_request
    """
    fixtures.reset_clock()
    payload = factories.create_family_member_payload(
        full_name="Branch Fam", branch_of_service="ARMY")
    resp = api.create_member(payload, INTAKE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_occ_eligibility_case_stale_member_version(api):
    """PRD section 2.6: "The request must carry `expected_member_version`, holding
    the `version` of the target `Member` as the client last observed it. If the
    member's current `version` has advanced since then, the create is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."
    PRD section 3.1: "any existing case for the same member in `UNDER_REVIEW` or
    `PENDED` is automatically moved to `SUPERSEDED`, the member's `version`
    increments by 1, and the new case starts in `UNDER_REVIEW`."

    Design: Corner/cross_cutting_layers/occ_eligibility_case_stale_member_version
    """
    fixtures.reset_clock()
    member = fixtures.create_member(full_name="Occ Vet")
    assert member["version"] == 1

    case1 = fixtures.open_eligibility_case(member["id"], member["version"])
    assert case1["status"] == "UNDER_REVIEW"

    fresh_version = fixtures.get_member_version(member["id"])
    assert fresh_version == 2, "case creation increments the member's version"
    case2 = fixtures.open_eligibility_case(member["id"], fresh_version)

    stale_resp = api.create_eligibility_case(
        factories.create_eligibility_case_payload(member["id"], fresh_version), INTAKE)
    validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION)

    assert fixtures.get_member_version(member["id"]) == 3
    cases = fixtures.list_eligibility_cases(member["id"])
    assert len(cases) == 2
    by_id = {c["id"]: c for c in cases}
    assert by_id[case1["id"]]["status"] == "SUPERSEDED"
    assert by_id[case2["id"]]["status"] == "UNDER_REVIEW"


def test_program_member_reading_other_member_forbidden(api):
    """PRD section 2.1: "A `ProgramMember` may read only their own member record,
    list only their own eligibility cases, and submit only surveys belonging to
    one of their own enrollments."
    PRD section 2.1: "ownership checks on any resource that references a `Member`
    compare the resource's foreign-key field to `X-User-ID`, and a mismatch is
    rejected with `ERR_RESOURCE_NOT_OWNED` (HTTP 403)."

    Design: Corner/rbac/program_member_reading_other_member_forbidden
    """
    fixtures.reset_clock()
    member1 = fixtures.create_member(full_name="Self One")
    member2 = fixtures.create_member(full_name="Other Two")

    err_resp = api.get_member(
        member2["id"], fixtures.make_program_member_headers(member1["id"]))
    validate_error(err_resp, ApiErrorId.ERR_RESOURCE_NOT_OWNED)

    ok_resp = api.get_member(
        member1["id"], fixtures.make_program_member_headers(member1["id"]))
    data = validate_success(ok_resp)
    assert data["full_name"] == "Self One"


def test_program_member_cannot_create_program_track(api):
    """PRD section 2.1: "A caller who is authenticated but whose role is not
    listed for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/program_member_cannot_create_program_track
    """
    fixtures.reset_clock()
    member = fixtures.create_member(full_name="Role Vet")
    resp = api.create_program_track(
        factories.create_program_track_payload(track_code="CAREER", name="Nope Track", capacity=5),
        fixtures.make_program_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert fixtures.list_program_tracks() == []


def test_unknown_role_header_returns_unauthenticated(api):
    """PRD section 2.1: "If either header is missing, or if `X-User-Role` does not
    name one of the declared roles below, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unknown_role_header_returns_unauthenticated
    """
    fixtures.reset_clock()
    ghost_headers = build_user_headers("ghost-1", "SuperUser")
    resp = api.create_program_track(
        factories.create_program_track_payload(track_code="CAREER", name="Ghost Track", capacity=5),
        ghost_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_eligibility_transition_unknown_id_returns_case_not_found(api):
    """PRD section 2.7: "A missing reference yields the matching 404 identifier —
    `ERR_MEMBER_NOT_FOUND`, `ERR_ELIGIBILITY_CASE_NOT_FOUND`,
    `ERR_PROGRAM_TRACK_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_EMPLOYER_NOT_FOUND`, `ERR_PLACEMENT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_REGISTRATION_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND`, or
    `ERR_REPORT_NOT_FOUND` (all HTTP 404)."

    Design: Corner/entities/eligibility_transition_unknown_id_returns_case_not_found
    """
    fixtures.reset_clock()
    resp = api.transition_eligibility_case(
        NON_EXISTENT_UUID,
        factories.case_transition_payload("PENDED", pend_reason="ghost"),
        INTAKE)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_CASE_NOT_FOUND)
