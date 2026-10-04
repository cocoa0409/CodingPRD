"""Corner coverage: role-based access control.

Exclusive-operation denials, per-action role splits on action-style
endpoints, entity-backed ownership, and authorization running ahead of
existence checks in the validation pipeline.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_program_payload,
    create_release,
    create_cycle,
    create_program,
    enroll,
    get_enrollment,
    make_accredited_media_headers,
    make_respondent_headers,
    register_establishment,
    release_advance_payload,
    set_clock,
    setup_program_with_frozen_frame,
    validate_error,
)

ADMIN = TEST_USERS["program_admin_headers"]
COLLECTOR = TEST_USERS["collection_officer_headers"]
RELEASE_MANAGER = TEST_USERS["release_manager_headers"]


def test_program_create_as_collection_officer_forbidden(api):
    """PRD §2.1: "A request whose role is not permitted on the targeted endpoint — or not permitted for the specific action named within an action-style endpoint — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "A `ProgramAdmin` configures survey programs, sample frames, and monthly cycles, and operates the logical clock."

    Design: Corner/rbac/program_create_as_collection_officer_forbidden
    """
    resp = api_client.create_program(
        create_program_payload(code="CES", name="X", sample_budget=3),
        COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)  # 403


def test_respondent_cannot_accept_own_report_forbidden(api):
    """PRD §2.1: "Within a report advance, `SUBMIT` is reserved to the owning `Respondent`, while `ACCEPT` and `RETURN` belong to the `CollectionOfficer`."
    PRD §2.8: "Every request passes through a fixed pipeline of validation stages, evaluated in the order below. The first failing stage determines the response: its error is returned and no later stage is consulted."

    Design: Corner/rbac/respondent_cannot_accept_own_report_forbidden
    """
    # The authorization stage runs before path existence, so a
    # never-existent report id still surfaces ERR_FORBIDDEN, not 404.
    resp = api_client.advance_report(
        "88888888-8888-4888-8888-888888888888",
        {"action": "ACCEPT"},
        make_respondent_headers("11111111-1111-4111-8111-111111111111"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)  # 403


def test_respondent_acting_on_other_establishment_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Respondent`, `X-User-ID` is the `id` of the acting `Establishment`; ownership checks on any resource that references an establishment compare that resource's `establishment_id` field to `X-User-ID`."
    PRD §3.2: "every `Respondent`-scoped action requires the caller's `X-User-ID` to equal the enrollment's `establishment_id`, enforced with `ERR_FORBIDDEN`."

    Design: Corner/rbac/respondent_acting_on_other_establishment_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_program_with_frozen_frame(code="CES", sample_budget=3)
    e1 = register_establishment()
    e2 = register_establishment()
    en2 = enroll(e2["id"], "CES")  # INVITED, addressed to E2

    resp = api_client.enrollment_lifecycle(
        en2["id"], {"action": "ACCEPT"}, make_respondent_headers(e1["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)  # 403
    assert get_enrollment(en2["id"])["enrollment_status"] == "INVITED"


def test_breach_report_as_accredited_media_forbidden(api):
    """PRD §2.1: "A `ReleaseManager` runs the publication calendar, embargo operations, media accreditation, and breach handling."
    PRD §2.1: "A request whose role is not permitted on the targeted endpoint — or not permitted for the specific action named within an action-style endpoint — is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/breach_report_as_accredited_media_forbidden
    """
    # Role check precedes existence: even a non-existent grant id is 403.
    resp = api_client.report_breach(
        "99999999-9999-4999-8999-999999999999",
        make_accredited_media_headers("11111111-1111-4111-8111-111111111111"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)  # 403


def test_collection_officer_cannot_certify_forbidden(api):
    """PRD §2.1: "Within a survey-cycle advance, `OPEN_COLLECTION` and `CLOSE_COLLECTION` are `CollectionOfficer` actions, while `COMPUTE_ESTIMATES`, `CERTIFY`, and `REOPEN_REVISION` belong to the `EstimationAnalyst`."

    Design: Corner/rbac/collection_officer_cannot_certify_forbidden
    """
    # Authorization precedes existence: 403, not ERR_CYCLE_NOT_FOUND.
    resp = api_client.advance_cycle(
        "11111111-1111-4111-8111-111111111111",
        {"action": "CERTIFY"}, COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)  # 403


def test_release_manager_cannot_approve_disclosure_forbidden(api):
    """PRD §2.1: "Within a release advance, `POSTPONE`, `RESCHEDULE`, `OPEN_EMBARGO`, and `PUBLISH` are `ReleaseManager` actions, while `APPROVE_DISCLOSURE` and `REJECT_DISCLOSURE` belong to the `DisclosureOfficer`."

    Design: Corner/rbac/release_manager_cannot_approve_disclosure_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(code="CES", sample_budget=3)
    cycle = create_cycle("CES", "2026-09")
    release = create_release(cycle["id"], "2026-10-01T13:30:00Z")

    resp = api_client.advance_release(
        release["id"],
        release_advance_payload(
            "APPROVE_DISCLOSURE",
            expected_release_version=release["version"]),
        RELEASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)  # 403: authorization
    # precedes both the concurrency and the state checks.
