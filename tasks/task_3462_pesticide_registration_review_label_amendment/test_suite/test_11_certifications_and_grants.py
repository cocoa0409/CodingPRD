"""Applicator certifications and the restricted-use grant gate: the expiry
sweep, the renewal cycle, the renewal-instant rule, the inclusive validity
boundary, and the no-certification grant failure (PRD §2.4, §3.9).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    apply_state_registration,
    assert_certification,
    assert_iso_instant_equal,
    create_certification,
    create_registered_product,
    make_certification_renewal_payload,
    make_state_decision_payload,
    renew_certification,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
STATE_AGENCY = TEST_USERS["state_agency_headers"]
CERT_AUTHORITY = TEST_USERS["certification_authority_headers"]


def _get_certification(certification_id):
    """Fetch one certification row through the list endpoint (no single-GET
    endpoint exists for certifications in the PRD §4 index)."""
    rows, _ = validate_paginated(api_client.list_certifications(ADMIN))
    return [c for c in rows if c["id"] == certification_id][0]


def test_certification_expiry_boundary_is_inclusive(api):
    """PRD §3.9: "when the product's `classification` is `RESTRICTED_USE`, it
    requires at least one applicator certification whose `state_code` equals the
    registration's state, whose `status` is `ACTIVE`, and whose `certified_until`
    is at or after the current clock — without one, the grant fails
    `ERR_NO_VALID_APPLICATOR_CERTIFICATION` (HTTP 422)."
    PRD §2.4: "Every applicator certification in `ACTIVE` whose `certified_until`
    is strictly earlier than the new time flips to `EXPIRED`."
    PRD §3.9: "an expiry exactly equal to the clock does not expire"

    Design: Difficulty/boundary_precision_check/certification_expiry_boundary_is_inclusive
    """
    ctx = create_registered_product(use_pattern="FOOD_USE",
                                    final_classification="RESTRICTED_USE")
    product_id = ctx["product"]["id"]
    cert_tx = create_certification("TX", "2027-01-15T12:00:00Z",
                                   applicator_name="W. Fields")
    cert_ca = create_certification("CA", "2027-01-15T12:00:00Z",
                                   applicator_name="J. Ramos")
    sreg_tx = apply_state_registration(product_id, "TX", REGISTRANT)
    sreg_ca = apply_state_registration(product_id, "CA", REGISTRANT)

    # At clock == certified_until the certification is still valid (inclusive).
    set_clock("2027-01-15T12:00:00Z")
    granted = validate_success(api_client.decide_state_registration(
        sreg_tx["id"], make_state_decision_payload("GRANT"), STATE_AGENCY))
    assert granted["status"] == "GRANTED"
    assert_iso_instant_equal(granted["renewal_due_at"], "2028-01-15T12:00:00Z",
                             "renewal_due_at")

    # One second later the sweep (strict <) expires both certifications.
    set_clock("2027-01-15T12:00:01Z")
    assert _get_certification(cert_tx["id"])["status"] == "EXPIRED"
    assert _get_certification(cert_ca["id"])["status"] == "EXPIRED"

    resp = api_client.decide_state_registration(
        sreg_ca["id"], make_state_decision_payload("GRANT"), STATE_AGENCY)
    validate_error(resp, ApiErrorId.ERR_NO_VALID_APPLICATOR_CERTIFICATION)
    data = validate_success(api_client.get_state_registration(sreg_ca["id"], ADMIN))
    assert data["status"] == "SUBMITTED"


def test_certification_expiry_and_renew_cycle(api):
    """PRD §3.9: "A certification is born `ACTIVE` with `renewed_count` zero, and
    the clock sweep (§2.4, step 3) flips it to `EXPIRED` once its `certified_until`
    is strictly earlier than the current time"
    PRD §3.9: "Renewal is allowed from both `ACTIVE` (early renewal) and
    `EXPIRED`, under identical rules: the supplied `new_certified_until` must be
    strictly later than the logical clock, failing
    `ERR_CERTIFICATION_RENEWAL_INVALID` (HTTP 400) otherwise, and a successful
    renewal writes `certified_until`, increments `renewed_count` by one, and
    returns the row to `ACTIVE`."

    Design: Corner/state_machines/certification_expiry_and_renew_cycle
    """
    cert = create_certification("TX", "2027-01-01T00:00:00Z",
                                applicator_name="W. Fields")
    assert_certification(cert)
    assert cert["status"] == "ACTIVE"

    set_clock("2027-01-02T00:00:00Z")
    assert _get_certification(cert["id"])["status"] == "EXPIRED"

    renewed = renew_certification(cert["id"], "2028-06-01T00:00:00Z",
                                  CERT_AUTHORITY)
    assert renewed["status"] == "ACTIVE"
    assert_iso_instant_equal(renewed["certified_until"], "2028-06-01T00:00:00Z",
                             "certified_until")
    assert renewed["renewed_count"] == 1

    # Early renewal from ACTIVE follows the same rule.
    renewed = renew_certification(cert["id"], "2029-01-01T00:00:00Z",
                                  CERT_AUTHORITY)
    assert renewed["status"] == "ACTIVE"
    assert_iso_instant_equal(renewed["certified_until"], "2029-01-01T00:00:00Z",
                             "certified_until")
    assert renewed["renewed_count"] == 2


def test_certification_renew_with_past_date_returns_renewal_invalid(api):
    """PRD §3.9: "the supplied `new_certified_until` must be strictly later than
    the logical clock, failing `ERR_CERTIFICATION_RENEWAL_INVALID` (HTTP 400)
    otherwise"

    Design: Corner/validations/certification_renew_with_past_date_returns_renewal_invalid
    """
    cert = create_certification("TX", "2027-06-01T00:00:00Z",
                                applicator_name="W. Fields")
    # The logical clock sits at 2026-09-01; 2026-08-31 is not strictly later.
    resp = api_client.renew_certification(
        cert["id"], make_certification_renewal_payload("2026-08-31T00:00:00Z"),
        CERT_AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_RENEWAL_INVALID)

    cert = _get_certification(cert["id"])
    assert_iso_instant_equal(cert["certified_until"], "2027-06-01T00:00:00Z",
                             "certified_until")
    assert cert["renewed_count"] == 0
    assert cert["status"] == "ACTIVE"


def test_grant_restricted_use_without_certification_returns_no_valid_cert(api):
    """PRD §3.9: "when the product's `classification` is `RESTRICTED_USE`, it
    requires at least one applicator certification whose `state_code` equals the
    registration's state, whose `status` is `ACTIVE`, and whose `certified_until`
    is at or after the current clock — without one, the grant fails
    `ERR_NO_VALID_APPLICATOR_CERTIFICATION` (HTTP 422)."

    Design: Corner/validations/grant_restricted_use_without_certification_returns_no_valid_cert
    """
    ctx = create_registered_product(use_pattern="FOOD_USE",
                                    final_classification="RESTRICTED_USE")
    sreg = apply_state_registration(ctx["product"]["id"], "FL", REGISTRANT)

    resp = api_client.decide_state_registration(
        sreg["id"], make_state_decision_payload("GRANT"), STATE_AGENCY)
    validate_error(resp, ApiErrorId.ERR_NO_VALID_APPLICATOR_CERTIFICATION)
    data = validate_success(api_client.get_state_registration(sreg["id"], ADMIN))
    assert data["status"] == "SUBMITTED"
