"""Authentication, role authorization, and applicant ownership (PRD §2.1, §2.7)."""
from test_helpers import (
    ApiErrorId,
    application_transition_payload,
    create_cycle,
    get_application,
    make_applicant_headers,
    patch_application_payload,
    post_campus_quorum_scores,
    register_applicant,
    setup_draft_application,
    setup_submitted_application,
    validate_error,
)


def test_request_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request with missing headers, or with a role value
    outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.7: "1. **Authentication.** The `X-User-ID` and `X-User-Role`
    headers are present and the role is one of the seven declared roles —
    otherwise `ERR_UNAUTHENTICATED` (401). This applies to every endpoint."

    The target cycle exists; authentication precedes every other check.

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    cycle = create_cycle()
    resp = api.get_cycle(cycle["id"], {})  # no X-User-ID / X-User-Role at all
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_applicant_cannot_decide_in_campus_review(api):
    """PRD §2.7: "The role is admitted by the endpoint and matches the action
    family of the requested transition: SUBMIT, WITHDRAW, and DECLINE on
    applications and ACCEPT and DECLINE on placement offers are `Applicant`
    actions; DECIDE belongs to the reviewer family (`CampusReviewer`,
    `NationalReviewer`, `HostCommission`); EXPIRE on an offer, ACCEPT and
    REQUEST_REVISION on a report, and APPROVE_WAIVER and DENY_WAIVER on a
    residency ledger are `ProgramOfficer` actions; RESUBMIT on a report and
    REQUEST_WAIVER on a ledger are `Applicant` actions — violations are
    `ERR_UNAUTHORIZED` (403)."

    Even the owning applicant may not ENDORSE their own file.

    Design: Corner/validations/applicant_cannot_decide_in_campus_review
    """
    bundle = setup_submitted_application(applicant_type="ENROLLED_STUDENT")
    app = bundle["application"]
    assert app["status"] == "CAMPUS_REVIEW"
    post_campus_quorum_scores(app, score=75)  # quorum met; only role blocks

    resp = api.transition_application(
        app["id"], application_transition_payload("DECIDE", outcome="ENDORSE"),
        make_applicant_headers(bundle["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    assert get_application(app)["status"] == "CAMPUS_REVIEW"


def test_applicant_cannot_patch_anothers_application(api, program_officer_headers):
    """PRD §2.1: "When `X-User-Role` is `Applicant`, `X-User-ID` is the `id`
    of the acting Applicant record; ownership checks on any resource that
    references an applicant compare that chain's terminal applicant id to
    `X-User-ID` — `applicant_id` on an application directly, and the
    applicant reached through the foreign-key chain for grants, placement
    rounds, reports, visa sponsorships, and residency ledgers. A mismatch is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    The intruder presents the application's fresh current version, so only
    the ownership check can fail — OCC freshness never substitutes for
    ownership.

    Design: Corner/validations/applicant_cannot_patch_anothers_application
    """
    bundle = setup_draft_application()
    app = bundle["application"]
    intruder = register_applicant()

    current = get_application(app)
    resp = api.patch_application(
        app["id"],
        patch_application_payload(
            current["version"], project_title="Hijacked Title",
        ),
        make_applicant_headers(intruder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    after = get_application(app)
    assert after["project_title"] == app["project_title"]
    assert after["version"] == current["version"], (
        "a rejected patch must not bump the version"
    )
