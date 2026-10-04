"""License issuance gates, the two-dimension verification machine, denial
terminality, and the disqualification safety gate."""

from test_helpers import (
    FEDERAL_VERIFIER_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_created,
    assert_error,
    assert_license,
    assert_ok,
    claim_driver_record,
    current_driver_version,
    issue_license,
    license_payload,
    license_transfer_payload,
    list_licenses,
    make_jurisdiction_registrar_headers,
    post_conviction,
    read_license,
    register_driver,
    setup_certified_jurisdiction,
    setup_conviction_world,
    setup_driver_record,
    verification_result_payload,
)


def _pointer_world(api, code="AA"):
    ctx = setup_certified_jurisdiction(api, code=code, systems=("POINTER_NETWORK",))
    return setup_driver_record(api, ctx)


def test_license_activates_only_after_both_verifications(api):
    """PRD §3.5: "A new license is created in `PENDING_VERIFICATION` with its
    `record_id` bound to that backing record, its `issuing_jurisdiction_id` set to the
    caller's jurisdiction, and both verification dimensions — `ssn_check_status` and
    `lawful_status_check_status` — reading `PENDING`."
    PRD §3.5: "When the second of the two dimensions lands `VERIFIED` — both now
    verified — the system moves the license `PENDING_VERIFICATION` → `ACTIVE`".

    Design: Corner/state_machines/license_activates_only_after_both_verifications
    """
    ctx = _pointer_world(api)
    license_body = issue_license(api, ctx["driver_id"], ctx["jurisdiction_id"], "STANDARD")
    assert license_body["status"] == "PENDING_VERIFICATION"
    assert license_body["ssn_check_status"] == "PENDING"
    assert license_body["lawful_status_check_status"] == "PENDING"

    resp = api.post_verification_result(
        license_body["id"],
        verification_result_payload("SSN", "VERIFIED"),
        FEDERAL_VERIFIER_HEADERS,
    )
    midway = assert_ok(resp)
    assert midway["status"] == "PENDING_VERIFICATION", (
        "one verified dimension does not activate the license"
    )
    assert midway["ssn_check_status"] == "VERIFIED"
    assert midway["lawful_status_check_status"] == "PENDING"

    resp = api.post_verification_result(
        license_body["id"],
        verification_result_payload("LAWFUL_STATUS", "VERIFIED"),
        FEDERAL_VERIFIER_HEADERS,
    )
    final = assert_ok(resp)
    assert_license(final)
    assert final["status"] == "ACTIVE"


def test_license_denied_on_failed_check_and_is_terminal(api):
    """PRD §3.5: "the moment any dimension lands `FAILED`, the license goes
    `PENDING_VERIFICATION` → `DENIED`, a terminal state. Posting against a license that
    has left `PENDING_VERIFICATION`, or re-posting a dimension already decided, is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/license_denied_on_failed_check_and_is_terminal
    """
    ctx = _pointer_world(api)
    license_body = issue_license(api, ctx["driver_id"], ctx["jurisdiction_id"], "STANDARD")

    resp = api.post_verification_result(
        license_body["id"],
        verification_result_payload("LAWFUL_STATUS", "FAILED"),
        FEDERAL_VERIFIER_HEADERS,
    )
    denied = assert_ok(resp)
    assert denied["status"] == "DENIED"

    resp = api.post_verification_result(
        license_body["id"],
        verification_result_payload("SSN", "VERIFIED"),
        FEDERAL_VERIFIER_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_license_issuance_requires_active_record(api):
    """PRD §3.5: "The driver must have an `ACTIVE` record held by the caller's own
    jurisdiction: when no such record exists the request fails with
    `ERR_RECORD_NOT_FOUND`".

    Design: Difficulty/cross_entity_state_dependency/license_issuance_requires_active_record
    """
    ctx = setup_certified_jurisdiction(api, code="AA", systems=("POINTER_NETWORK",))
    driver = register_driver(
        api, ctx["jurisdiction_id"], full_name="Driver Nine",
        lawful_status_basis="TEMPORARY_STATUS",
    )
    resp = api.create_license(
        license_payload(driver["id"], "STANDARD"),
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_RECORD_NOT_FOUND)

    record = claim_driver_record(api, driver["id"], ctx["jurisdiction_id"])
    resp = api.create_license(
        license_payload(driver["id"], "STANDARD"),
        make_jurisdiction_registrar_headers(ctx["jurisdiction_id"]),
    )
    license_body = assert_created(resp)
    assert license_body["status"] == "PENDING_VERIFICATION"
    assert license_body["record_id"] == record["id"], (
        "the license binds the record that satisfied the dependency"
    )


def test_license_issuance_blocked_record_held_elsewhere(api):
    """PRD §3.5: "when the driver's `ACTIVE` record is held by a different jurisdiction
    the request fails with `ERR_RECORD_HELD_BY_OTHER_JURISDICTION` — the remedy is the
    transfer protocol of §3.6, not a second issuance."

    Design: Corner/errors/license_issuance_blocked_record_held_elsewhere
    """
    ctx_a = _pointer_world(api, code="AA")
    ctx_b = setup_certified_jurisdiction(api, code="BB", systems=("POINTER_NETWORK",))
    resp = api.create_license(
        license_payload(ctx_a["driver_id"], "STANDARD"),
        make_jurisdiction_registrar_headers(ctx_b["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_RECORD_HELD_BY_OTHER_JURISDICTION)


def test_transfer_initiate_requires_active_prior_license(api):
    """PRD §3.6: "The prior license must be `ACTIVE` — a non-active one yields
    `ERR_LICENSE_NOT_ACTIVE`".

    Design: Corner/errors/transfer_initiate_requires_active_prior_license
    """
    ctx_a = _pointer_world(api, code="AA")
    # Issued but never verified: still PENDING_VERIFICATION.
    license_body = issue_license(api, ctx_a["driver_id"], ctx_a["jurisdiction_id"], "STANDARD")
    ctx_b = setup_certified_jurisdiction(api, code="BB", systems=("POINTER_NETWORK",))
    resp = api.create_license_transfer(
        license_transfer_payload(
            ctx_a["driver_id"],
            license_body["id"],
            current_driver_version(api, ctx_a["driver_id"]),
        ),
        make_jurisdiction_registrar_headers(ctx_b["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)


def test_verification_results_unknown_license_not_found(api):
    """PRD §2.6: "Path identifiers and body foreign keys must reference existing
    resources, validated left to right; the first missing reference yields the
    corresponding not-found error" — here `ERR_LICENSE_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/verification_results_unknown_license_not_found
    """
    resp = api.post_verification_result(
        NON_EXISTENT_UUID,
        verification_result_payload("SSN", "VERIFIED"),
        FEDERAL_VERIFIER_HEADERS,
    )
    assert_error(resp, ApiErrorId.ERR_LICENSE_NOT_FOUND)


def test_issuance_dq_safety_beats_record_constraint(api):
    """PRD §2.6: "Every mutating request passes through the same ordered gauntlet of
    checks, and the order is part of the contract: when several checks could reject the
    same request, the first failing rung on this ladder determines which error
    surfaces."
    PRD §2.6: "**Credentialing and brand safety.** Commercial credentialing and
    brand-washing gates: `ERR_ACTIVE_DISQUALIFICATION` and
    `ERR_BRAND_DISCLOSURE_MISMATCH` (HTTP 409)." (rung 7) sits above "**Uniqueness and
    exclusivity.**" (rung 8, home of `ERR_RECORD_HELD_BY_OTHER_JURISDICTION`).
    PRD §3.5: "for the `COMMERCIAL` class a further safety gate applies: no
    disqualification on the backing record may have derived status `ACTIVE`, else
    `ERR_ACTIVE_DISQUALIFICATION`."

    Design: Difficulty/priority_pair_validation_conflict/issuance_dq_safety_beats_record_constraint
    """
    # AA holds the driver's ACTIVE record with a derived-ACTIVE AUTO_MAJOR
    # disqualification on it; BB is fully certified but holds no record.
    ctx_a = setup_conviction_world(api, code="AA")
    post_conviction(
        api, ctx_a["record_id"], ctx_a["jurisdiction_id"],
        offense_date="2026-08-15", conviction_date="2026-08-25",
        severity="CMV_MAJOR", points=6,
    )
    ctx_b = setup_certified_jurisdiction(api, code="BB", systems=("POINTER_NETWORK",))

    resp = api.create_license(
        license_payload(ctx_a["driver_id"], "COMMERCIAL"),
        make_jurisdiction_registrar_headers(ctx_b["jurisdiction_id"]),
    )
    assert_error(resp, ApiErrorId.ERR_ACTIVE_DISQUALIFICATION)
    rows, meta = list_licenses(api, params={"driver_id": ctx_a["driver_id"]})
    assert meta["total_count"] == 0 and rows == [], "no license was persisted"
