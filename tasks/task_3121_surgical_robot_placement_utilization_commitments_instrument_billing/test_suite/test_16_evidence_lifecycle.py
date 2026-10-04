"""Evidence renewal and the observable expiry-window side effects."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_training_record,
    get_success_data,
    set_clock,
    setup_account_with_review,
    validate_error,
    validate_success,
)


def test_evidence_expiring_inside_thirty_days_opens_as_expiring_soon(api):
    """PRD §3.5: "The record opens at `evidence_status` `VALID` or `EXPIRING_SOON` depending
    on how close the expiry is, and runs `VALID → EXPIRING_SOON → EXPIRED / REVOKED`."

    Design: Corner/endpoints/evidence_renew_side_effect_clears_expiring_status
    """
    ctx = setup_account_with_review(verdict="PASSED")
    record = create_training_record(ctx.account["id"])

    evidence = validate_success(api_client.create_credentialing_evidence(
        record["id"],
        {"evidence_type": "PRIVILEGE_ATTESTATION", "issued_utc": "2026-08-01T00:00:00Z",
         "expires_utc": "2026-09-15T00:00:00Z"},
        ctx.account_headers), 201)

    assert evidence["evidence_status"] == "EXPIRING_SOON", (
        "an expiry inside 30 days of the logical clock is not yet VALID for long"
    )


def test_renewing_the_evidence_restores_valid_with_the_new_expiry(api):
    """PRD §3.5: "A `ComplianceOfficer` may renew a record in `VALID`, `EXPIRING_SOON` or
    `EXPIRED` — statuses outside that set fail with `ERR_EVIDENCE_NOT_RENEWABLE` (HTTP 409,
    checked first) — supplying a fresh `issued_utc` and `expires_utc`, both of which must be
    strictly later than the logical clock and whose end must be strictly later than its start.
    Renewing a lapsed record revives it to `VALID`."

    Design: Corner/endpoints/evidence_renew_side_effect_clears_expiring_status
    """
    ctx = setup_account_with_review(verdict="PASSED")
    record = create_training_record(ctx.account["id"])
    evidence = get_success_data(api_client.create_credentialing_evidence(
        record["id"],
        {"evidence_type": "PRIVILEGE_ATTESTATION", "issued_utc": "2026-08-01T00:00:00Z",
         "expires_utc": "2026-09-15T00:00:00Z"},
        ctx.account_headers), 201)
    set_clock("2026-09-01T00:00:00Z")

    renewed = validate_success(api_client.renew_credentialing_evidence(
        evidence["id"],
        {"issued_utc": "2026-09-02T00:00:00Z", "expires_utc": "2027-09-01T00:00:00Z",
         "expected_evidence_version": evidence["version"]},
        TEST_USERS["compliance_officer_headers"]), 200)

    assert renewed["evidence_status"] == "VALID"
    assert renewed["expires_utc"] == "2027-09-01T00:00:00.000Z"
    fetched = get_success_data(api_client.get_credentialing_evidence(
        evidence["id"], TEST_USERS["compliance_officer_headers"]))
    assert fetched["evidence_status"] == "VALID"
    assert fetched["expires_utc"] == "2027-09-01T00:00:00.000Z"


def test_renewal_with_an_out_of_order_window_is_refused(api):
    """PRD §3.5: "The evidence must be temporally coherent: `issued_utc` must not be later
    than the logical clock, and `expires_utc` must be strictly later than `issued_utc`; a
    violation is `ERR_EVIDENCE_WINDOW_INVALID` (HTTP 422), both on filing and on renewal."

    Design: Corner/endpoints/evidence_renew_side_effect_clears_expiring_status
    """
    ctx = setup_account_with_review(verdict="PASSED")
    record = create_training_record(ctx.account["id"])
    evidence = get_success_data(api_client.create_credentialing_evidence(
        record["id"],
        {"evidence_type": "PRIVILEGE_ATTESTATION", "issued_utc": "2026-08-01T00:00:00Z",
         "expires_utc": "2026-09-15T00:00:00Z"},
        ctx.account_headers), 201)

    res = api_client.renew_credentialing_evidence(
        evidence["id"],
        {"issued_utc": "2026-09-20T00:00:00Z", "expires_utc": "2026-09-10T00:00:00Z",
         "expected_evidence_version": evidence["version"]},
        TEST_USERS["compliance_officer_headers"])

    validate_error(res, "ERR_EVIDENCE_WINDOW_INVALID", expected_status=422)