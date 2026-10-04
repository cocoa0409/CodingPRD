"""Access control (PRD §2.1, §2.8): authentication, endpoint-level and
action-level role gates, Specifier/Installer ownership, and both
segregation-of-duties pairs (report verification, claim review).
"""
from test_helpers import (
    ApiErrorId,
    allocate_to_batch,
    api_client,
    assign_report,
    clear_report,
    create_batch,
    create_collection,
    create_collection_payload,
    create_installed_site,
    create_offset_payload,
    create_order,
    create_qc_passed_lot,
    create_report,
    create_review_payload,
    create_takeback,
    create_verification_payload,
    lay_zone,
    make_approver_headers,
    make_installer_headers,
    make_manager_headers,
    make_specifier_headers,
    make_verifier_headers,
    set_clock,
    setup_claim_in_review,
    setup_collection_with_batch,
    setup_published_report,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
    ALT_SPECIFIER_ID,
    DEFAULT_MANAGER_ID,
    DEFAULT_VERIFIER_ID,
)

MANAGER = make_manager_headers(DEFAULT_MANAGER_ID)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting an
    `X-User-Role` value that does not name one of the declared roles, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_collection(
        {
            "name": "NoAuth",
            "pattern_code": "NAU",
            "backing_type": "STANDARD",
            "lifecycle_boundary": "CRADLE_TO_GATE",
        },
        None,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["data"]["message"].strip()


def test_installer_cannot_create_collection_returns_forbidden(api, installer_headers):
    """PRD §2.1: "An authenticated request whose role is not listed among an
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /carpetloop/collections is authorized for PlatformAdmin only.

    Design: Corner/rbac/installer_cannot_create_collection_returns_forbidden
    """
    set_clock()
    resp = api.create_collection(
        {
            "name": "Sneaky",
            "pattern_code": "SNK",
            "backing_type": "STANDARD",
            "lifecycle_boundary": "CRADLE_TO_GATE",
        },
        installer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_specifier_cannot_release_batch_returns_forbidden(
    api, admin_headers, specifier_headers
):
    """PRD §2.1: "An authenticated request whose role is not listed among an
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /carpetloop/batches/{batch_id}/release is authorized for
    PlatformAdmin only.

    Design: Corner/rbac/specifier_cannot_release_batch_returns_forbidden
    """
    set_clock()
    col = create_collection()
    batch = create_batch(col["id"])
    lot1 = create_qc_passed_lot()
    lot2 = create_qc_passed_lot(
        supplier_name="POLYCO", source_type="VIRGIN",
        quantity_kg=200, carbon_factor_kgco2e_per_kg=2.10,
    )
    allocate_to_batch(lot1["id"], batch["id"], 200)
    allocate_to_batch(lot2["id"], batch["id"], 200)
    # The mix is mass-balanced, so only the role gate can fire.
    resp = api.release_batch(batch["id"], specifier_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    data = validate_success(api.get_batch(batch["id"], admin_headers))
    assert data["status"] == "QUARANTINE"


def test_verification_action_role_split_enforced(
    api, admin_headers, verifier_headers
):
    """PRD §2.1: "One endpoint is action-split: on the report verification
    endpoint, the action `ASSIGN` requires the `SustainabilityManager` role
    while the actions `CLEAR` and `FAIL` require the `Verifier` role, and a
    role that is valid for the endpoint but wrong for the requested action is
    likewise rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/verification_action_role_split_enforced
    """
    set_clock()
    built = setup_collection_with_batch()
    rep = create_report_via_manager(built)
    submit_report(rep)
    # ASSIGN is the manager's action: the Verifier role is rejected.
    resp = api.verify_pcf_report(
        rep["id"],
        create_verification_payload("ASSIGN", verifier_org="EcoAssure"),
        verifier_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    # The legal ASSIGN lands...
    rep = assign_report(rep)
    # ...and CLEAR is the verifier's action: the manager role is rejected.
    resp = api.verify_pcf_report(
        rep["id"], create_verification_payload("CLEAR"), MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    data = validate_success(api.get_pcf_report(rep["id"], admin_headers))
    assert data["status"] == "IN_VERIFICATION"


def create_report_via_manager(built):
    """Open a DRAFT report on the fixture collection (CRADLE_TO_GATE)."""
    return create_report(built["collection"]["id"], boundary="CRADLE_TO_GATE")


def test_claim_review_requires_approver_role(api, admin_headers):
    """PRD §2.1: "An authenticated request whose role is not listed among an
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /carpetloop/carbon-claims/{claim_id}/review is authorized for
    ClaimsApprover only.

    Design: Corner/rbac/claim_review_requires_approver_role
    """
    set_clock()
    built = setup_collection_with_batch()
    rep = setup_published_report(built["collection"]["id"], boundary="CRADLE_TO_GATE")
    claim = setup_claim_in_review(built["collection"]["id"], rep["id"])
    resp = api.review_carbon_claim(
        claim["id"], create_review_payload("APPROVE"), make_manager_headers("sm-other")
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    data = validate_success(api.get_carbon_claim(claim["id"], admin_headers))
    assert data["status"] == "IN_REVIEW"


def test_sod_verifier_cannot_clear_own_submission(api, admin_headers):
    """PRD §3.6: "From there a `Verifier` either clears or fails the report,
    and in both cases the verifier's `X-User-ID` must differ from the report's
    `submitted_by`; a verifier reviewing their own submission is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/sod_verifier_cannot_clear_own_submission
    """
    set_clock()
    built = setup_collection_with_batch()
    rep = create_report_via_manager(built)
    rep = submit_report(rep)  # submitted_by sm-carol
    rep = assign_report(rep)
    # A Verifier whose identity equals submitted_by is rejected.
    resp = api.verify_pcf_report(
        rep["id"],
        create_verification_payload("CLEAR"),
        make_verifier_headers(DEFAULT_MANAGER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # A distinct verifier clears the same report immediately after.
    rep = clear_report(rep, verifier_id=DEFAULT_VERIFIER_ID)
    assert rep["status"] == "VERIFIED"
    assert rep["verified_by"] == DEFAULT_VERIFIER_ID


def test_sod_reviewer_cannot_approve_own_claim_and_vintage_floor(
    api, admin_headers, approver_headers
):
    """PRD §3.7: "the reviewer's `X-User-ID` must differ from the claim's
    `created_by`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.7: "the `vintage_year`, which must be 2020 or later (otherwise
    `ERR_INVALID_REQUEST`)"

    Design: Corner/rbac/sod_reviewer_cannot_approve_own_claim_and_vintage_floor
    """
    set_clock()
    built = setup_collection_with_batch()
    rep = setup_published_report(built["collection"]["id"], boundary="CRADLE_TO_GATE")
    claim = setup_claim_in_review(built["collection"]["id"], rep["id"])
    assert claim["created_by"] == DEFAULT_MANAGER_ID
    # A reviewer whose identity equals the claim's created_by is rejected.
    resp = api.review_carbon_claim(
        claim["id"],
        create_review_payload("APPROVE"),
        make_approver_headers(DEFAULT_MANAGER_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    # Vintage below the 2020 floor is a plain request-shape error.
    resp = api.create_offset_retirement(
        claim["id"],
        create_offset_payload(vintage_year=2019, quantity_kgco2e=5),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    # A distinct approver succeeds.
    resp = api.review_carbon_claim(
        claim["id"], create_review_payload("APPROVE"), approver_headers
    )
    data = validate_success(resp)
    assert data["status"] == "APPROVED"
    assert data["reviewed_by"] == "ap-erin"


def test_specifier_ownership_mismatch_returns_forbidden(api, admin_headers):
    """PRD §3.4: "A `Specifier` cancels an order they created — `X-User-ID`
    must equal the order's `created_by`, otherwise `ERR_FORBIDDEN`"
    PRD §3.5: "A `Specifier` may cancel a take-back they created — `X-User-ID`
    equal to the request's `created_by`, otherwise `ERR_FORBIDDEN`"
    PRD §2.8 (rule 3): "Specifier operations require `X-User-ID` equal to the
    resource's `created_by`; Installer operations require `X-User-ID` equal to
    the site's `contractor_name`; otherwise `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/specifier_ownership_mismatch_returns_forbidden
    """
    set_clock()
    built = setup_collection_with_batch()
    site = create_installed_site()
    zone = lay_zone(site, built["batch"]["id"], zone_code="Z-1", area_m2=10)
    order = create_order(site, zone, reason="WEAR", new_zone_code="Z-9")
    tb = create_takeback(site, built["collection"]["id"])

    # spec-eve did not create the order: cancelling it is forbidden.
    resp = api.cancel_replacement_order(
        order["id"], make_specifier_headers(ALT_SPECIFIER_ID)
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    # Nor can spec-eve cancel spec-ada's take-back.
    resp = api.cancel_takeback(tb["id"], make_specifier_headers(ALT_SPECIFIER_ID))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    rows, meta = validate_paginated(
        api.list_replacement_orders(admin_headers, params={"site_id": site["id"]})
    )
    assert [row["status"] for row in rows] == ["DRAFT"]
    assert meta["total_count"] == 1
    data = validate_success(api.get_takeback_request(tb["id"], admin_headers))
    assert data["status"] == "REQUESTED"
