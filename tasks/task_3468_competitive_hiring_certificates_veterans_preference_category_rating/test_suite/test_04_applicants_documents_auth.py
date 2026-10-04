"""Applicants, eligibility documents, preference verification, and the
authentication / ownership layer.
"""
from test_helpers import (
    HR, NON_EXISTENT_UUID, OPM, ApiErrorId, TEST_USERS,
    assert_applicant, assert_document,
    api_client, get_success_data, make_applicant_headers, register_applicant,
    setup_open_announcement, submit_application,
    upload_document, upload_document_payload, verify_document, validate_error,
    validate_success,
)


def test_applicant_preference_defaults_and_unverified_document(api):
    """PRD §3.3: "`preference_verified` is true exactly when the verified
    documents the claim requires are on file — a `FIVE_POINT` claim needs a
    verified `DD214`, `TEN_POINT_CP` and `TEN_POINT_CPS` each need a verified
    `DD214` plus a verified `VA_LETTER`, and a `NONE` claim is always verified."
    PRD §3.3: "A document arrives unverified: `verified` is false and
    `verified_by` and `verified_at` are null."

    Design: Corner/entities/applicant_preference_defaults_and_unverified_document
    """
    resp = api_client.create_applicant(
        {
            "full_name": "Ann",
            "email": "ann-none@example.com",
            "is_us_citizen": True,
            "is_current_federal_employee": False,
            "veteran_preference_claim": "NONE",
        },
        TEST_USERS["applicant_headers"])
    applicant = validate_success(resp, 201)
    assert_applicant(applicant)
    assert applicant["preference_verified"] is True, "NONE claim is always verified"
    assert applicant["preference_points"] == 0

    resp = api_client.upload_document(
        applicant["id"], upload_document_payload("DD214"),
        make_applicant_headers(applicant["id"]))
    document = validate_success(resp, 201)
    assert_document(document)
    assert document["verified"] is False
    assert document["verified_by"] is None
    assert document["verified_at"] is None


def test_document_under_missing_applicant_not_found(api):
    """PRD §2.8: "Paths that chain identifiers are validated left to right. A
    request naming a position and then an announcement beneath it first resolves
    the position, then the announcement; the first identifier that does not
    resolve to an existing entity produces `ERR_NOT_FOUND` (HTTP 404), and later
    segments are never examined."

    Design: Corner/entities/document_under_missing_applicant_not_found
    """
    resp = api_client.upload_document(
        NON_EXISTENT_UUID, upload_document_payload("DD214"), OPM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_preference_verification_recompute(api):
    """PRD §3.3: "It sets `verified` true, stamps `verified_by` with the
    delegate's `X-User-ID` and `verified_at` with the logical clock, increments
    the document's `version`, and immediately recomputes the owning applicant's
    `preference_verified` and `preference_points`, so a single verification can
    move an applicant from unentitled to entitled mid-process."
    PRD §3.3: "`preference_points` is 0 when the claim is `NONE` or unverified,
    5 for a verified `FIVE_POINT` claim, and 10 for a verified ten-point claim
    of either kind."

    Design: Corner/cross_cutting_layers/preference_verification_recompute
    """
    applicant = register_applicant(veteran_preference_claim="FIVE_POINT")
    assert applicant["preference_verified"] is False
    assert applicant["preference_points"] == 0

    document = upload_document(applicant, "DD214")
    # Possession is not verification: the derived fields are unchanged.
    reread = get_success_data(api_client.get_applicant(applicant["id"], HR))
    assert reread["preference_verified"] is False
    assert reread["preference_points"] == 0

    verified = verify_document(document["id"])
    assert verified["verified"] is True
    assert verified["verified_by"] == "opm-1"
    assert verified["verified_at"]

    reread = get_success_data(api_client.get_applicant(applicant["id"], HR))
    assert reread["preference_verified"] is True
    assert reread["preference_points"] == 5


def test_applicant_cannot_read_others_application(api):
    """PRD §2.1: "An `Applicant` may therefore read only its own applicant
    record, its own applications, its own documents, its own appeals, and offers
    resting on its own applications, and may act — apply, upload, appeal,
    respond — only for itself."

    Design: Corner/rbac/applicant_cannot_read_others_application
    """
    ctx = setup_open_announcement()
    ann = register_applicant()
    application = submit_application(ctx["announcement"], ann)
    bob = register_applicant()

    resp = api_client.get_application(
        application["id"], make_applicant_headers(bob["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request with missing or malformed headers, or whose
    `X-User-Role` is not one of these declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api_client.get_series(NON_EXISTENT_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_applicant_cannot_screen(api):
    """PRD §2.1: "A request whose role is not listed among an endpoint's
    authorized roles, or that violates an entity-backed ownership rule, is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.7: "authentication of the headers first (priority 1); then role
    authorization and entity-backed ownership (2); then request-body shape —
    required fields present, types correct, enum values in range, numeric ranges
    honored" and only then "existence of every identifier in the path and every
    foreign key in the body (4, `ERR_NOT_FOUND`)".

    Design: Corner/rbac/applicant_cannot_screen
    """
    # Authorization (priority 2) precedes existence (priority 4): even a random
    # id meets 403, never 404, under the wrong role.
    resp = api_client.screen_application(
        NON_EXISTENT_UUID, TEST_USERS["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
