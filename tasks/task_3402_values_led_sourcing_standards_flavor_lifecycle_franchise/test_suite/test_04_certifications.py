"""Certifications: window rules, clock expiry, revocation cascade (PRD §3.1, §2.5, §3.5)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_certification_payload,
    make_supplier, create_approved_supplier, make_certification,
    make_verified_certification, verify_certification,
    make_limited_run_flavor, make_published_claim_flavor,
)

SM = TEST_USERS["sourcing_manager_headers"]
FM = TEST_USERS["flavor_manager_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]



def test_cert_window_invalid_rejected(api):
    """PRD §3.1: "second, `valid_until` must be strictly later than `issued_at`,
    or the create fails with `ERR_CERT_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/cert_window_invalid_rejected
    """
    supplier = make_supplier(name="Bad Window Supplier")
    resp = api.create_certification(
        supplier["id"],
        create_certification_payload(
            scheme="ORGANIC", certificate_number="OG-BW",
            issued_at="2026-01-01T00:00:00Z", valid_until="2026-01-01T00:00:00Z",
            declared_coverage_pct=90), SM)
    validate_error(resp, ApiErrorId.ERR_CERT_WINDOW_INVALID)


def test_cert_window_halfopen_adjacency_allowed_overlap_rejected(api):
    """PRD §3.1: "first, the half-open window must not overlap another certification in `PENDING` or `VERIFIED` for the same supplier, scheme, and scope — overlap is rejected with `ERR_CERT_WINDOW_OVERLAP` (HTTP 409), while pure adjacency, where one certificate's `valid_until` equals the next one's `issued_at`, is allowed because the window end is exclusive; second, `valid_until` must be strictly later than `issued_at`, or the create fails with `ERR_CERT_WINDOW_INVALID` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/cert_window_halfopen_overlap
    """
    supplier = make_supplier(name="Window Supplier")
    c1 = validate_success(api.create_certification(
        supplier["id"],
        create_certification_payload(
            certificate_number="FT-W1",
            issued_at="2026-01-01T00:00:00Z", valid_until="2026-07-01T00:00:00Z",
            declared_coverage_pct=90), SM),
        expected_status=201)
    assert c1["status"] == "PENDING"

    # Adjacent: issued_at == prior valid_until -> accepted (window end exclusive).
    c2 = validate_success(api.create_certification(
        supplier["id"],
        create_certification_payload(
            certificate_number="FT-W2",
            issued_at="2026-07-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z",
            declared_coverage_pct=90), SM),
        expected_status=201)
    assert c2["status"] == "PENDING"

    # One day earlier: [2026-06-30, 2026-12-31) overlaps both -> rejected.
    resp = api.create_certification(
        supplier["id"],
        create_certification_payload(
            certificate_number="FT-W3",
            issued_at="2026-06-30T00:00:00Z", valid_until="2026-12-31T00:00:00Z",
            declared_coverage_pct=90), SM)
    validate_error(resp, ApiErrorId.ERR_CERT_WINDOW_OVERLAP)


def test_cert_window_overlap_pool_scoped_and_excludes_revoked(api):
    """PRD §3.1: "first, the half-open window must not overlap another certification in `PENDING` or `VERIFIED` for the same supplier, scheme, and scope — overlap is rejected with `ERR_CERT_WINDOW_OVERLAP` (HTTP 409), while pure adjacency, where one certificate's `valid_until` equals the next one's `issued_at`, is allowed because the window end is exclusive; second, `valid_until` must be strictly later than `issued_at`, or the create fails with `ERR_CERT_WINDOW_INVALID` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/cert_window_halfopen_overlap
    """
    supplier = make_supplier(name="Scoped Windows")
    # Same dates but a DIFFERENT scope does not share the overlap pool.
    make_certification(supplier["id"], scheme="FAIR_TRADE", scope="DAIRY",
                       declared=90, certificate_number="FT-S1")
    ok = api.create_certification(
        supplier["id"],
        create_certification_payload(
            scheme="FAIR_TRADE", ingredient_scope="COCOA",
            certificate_number="FT-S2", declared_coverage_pct=90), SM)
    validate_success(ok, expected_status=201)

    # A REVOKED cert leaves the PENDING/VERIFIED pool and stops blocking.
    cert = make_certification(supplier["id"], scheme="ORGANIC", scope="SUGAR",
                              declared=90, certificate_number="OG-R1")
    validate_success(api.revoke_certification(
        cert["id"], TEST_USERS["audit_verifier_headers"]))
    ok2 = api.create_certification(
        supplier["id"],
        create_certification_payload(
            scheme="ORGANIC", ingredient_scope="SUGAR",
            certificate_number="OG-R2", declared_coverage_pct=90), SM)
    validate_success(ok2, expected_status=201)


def test_clock_default_is_fixed_epoch(api):
    """PRD §2.5: "Before any client touches it, the clock reads exactly
    `2026-09-01T00:00:00Z`; the server never consults wall-clock time for
    business rules."
    PRD §2.5: "A certification in `PENDING` or `VERIFIED` whose `valid_until` is
    strictly earlier than the current logical time transitions to `EXPIRED`."

    Design: Corner/endpoints/clock_default_is_fixed_epoch
    """
    supplier = make_supplier(name="Epoch Supplier")
    cert = make_certification(
        supplier["id"], scheme="ORGANIC", certificate_number="OG-E1",
        declared=90, valid_until="2026-08-01T00:00:00Z")
    # No clock call at all: the default logical time is already past valid_until.
    data, _ = validate_paginated(api.list_certifications(supplier["id"], SM))
    by_id = {c["id"]: c for c in data}
    assert by_id[cert["id"]]["status"] == "EXPIRED"


def test_cert_revoke_challenges_citing_claim(api):
    """PRD §3.1: "An `AuditVerifier` may instead revoke a `PENDING` or `VERIFIED`
    certification, moving it to the terminal `REVOKED`; every flavor claim in
    `SUBSTANTIATED` or `PUBLISHED` that cites the revoked certification is
    challenged to `CHALLENGED` (§3.5)."

    Design: Corner/cross_cutting_layers/cert_revoke_challenges_citing_claim
    """
    supplier = create_approved_supplier(name="Revoke Dairy")
    cert = make_verified_certification(supplier["id"], declared=95, verified=95)
    flavor = make_published_claim_flavor([cert["id"]], name="Revoked Ripple")
    assert flavor["claim_status"] == "PUBLISHED"

    revoked = validate_success(api.revoke_certification(
        cert["id"], TEST_USERS["audit_verifier_headers"]))
    assert revoked["status"] == "REVOKED"
    after = get_success_data(api.get_flavor(flavor["id"], FM))
    assert after["claim_status"] == "CHALLENGED", \
        "revocation challenges; only clock expiry retracts"
