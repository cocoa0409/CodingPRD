"""In-process test recording, OCC, four-eyes verification, supersession, and RBAC."""
from test_helpers import (
    ApiErrorId, TEST_USERS, USER_IDS,
    validate_success, validate_error, validate_paginated,
    setup_batch_upstream, setup_batch_with_verified_upstream, setup_batch_downstream,
    record_test, verify_test_entity, get_batch_entity,
    create_test_payload, close_deviation,
    make_manufacturing_operator_headers, make_quality_control_analyst_headers,
    make_quality_assurance_reviewer_headers,
)

_OP = USER_IDS["operator"]


def _tests_of(api, batch_id, headers):
    rows, _meta = validate_paginated(api.list_tests(batch_id, headers))
    return rows


def test_verify_already_verified_test_rejected(api, quality_control_analyst_2_headers,
                                               platform_admin_headers):
    """PRD §3.4: "Verification is the `QualityControlAnalyst`'s decision on a `RECORDED` test; a test in any other status is rejected with `ERR_TEST_NOT_RECORDED` (HTTP 409)"

    Design: Corner/state_machines/verify_already_verified_test_rejected
    """
    env = setup_batch_with_verified_upstream()
    test_id = env["upstream_test"]["id"]
    resp = api.verify_test(test_id, quality_control_analyst_2_headers)
    validate_error(resp, ApiErrorId.ERR_TEST_NOT_RECORDED)
    rows = _tests_of(api, env["batch"]["id"], platform_admin_headers)
    test = next(row for row in rows if row["id"] == test_id)
    assert test["status"] == "VERIFIED" and test["verified_by_user_id"] == "qc-1"


def test_verify_four_eyes_recorder_cannot_verify(api):
    """PRD §2.10: "The `QualityControlAnalyst` who verifies a recorded test must not be the user who recorded it: if `X-User-ID` equals the test's `recorded_by_user_id`, the verification is rejected with `ERR_FOUR_EYES_VIOLATION` (HTTP 403). The verifying user's identity is then stamped into `verified_by_user_id`."

    Design: Corner/validations/verify_four_eyes_recorder_cannot_verify
    """
    env = setup_batch_upstream()
    test = record_test(env["batch"]["id"], batch_version=env["batch"]["version"])
    resp = api.verify_test(test["id"], make_quality_control_analyst_headers(_OP))
    validate_error(resp, ApiErrorId.ERR_FOUR_EYES_VIOLATION)
    verified = verify_test_entity(test["id"])
    assert verified["status"] == "VERIFIED" and verified["verified_by_user_id"] == "qc-1"


def test_occ_stale_batch_version_rejected_then_fresh_succeeds(api, platform_admin_headers):
    """PRD §2.8: "If `expected_batch_version` does not equal the batch's current `version`, the request is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412), and this check is evaluated before any business rule of the endpoint. Because every recorded test increments the parent batch's `version` by one, a client holding a stale observation"

    Design: Corner/validations/occ_stale_batch_version_rejected_then_fresh_succeeds
    """
    env = setup_batch_upstream()
    batch_id = env["batch"]["id"]
    record_test(batch_id, batch_version=1)  # bumps the batch to version 2
    headers = make_manufacturing_operator_headers(_OP)
    stale = create_test_payload(expected_batch_version=1, measured_value=86.0)
    validate_error(api.create_test(batch_id, stale, headers),
                   ApiErrorId.ERR_STALE_BATCH_VERSION)
    fresh_version = get_batch_entity(batch_id)["version"]
    assert fresh_version == 2
    retry = create_test_payload(expected_batch_version=fresh_version, measured_value=86.0)
    data = validate_success(api.create_test(batch_id, retry, headers), expected_status=201)
    assert data["status"] == "RECORDED"


def test_phase_mismatch_downstream_during_upstream_rejected(api, platform_admin_headers):
    """PRD §3.4: "the test's `phase` must equal the batch's current process phase, and tests may only be recorded while the batch is in `UPSTREAM` or `DOWNSTREAM` (`ERR_TEST_PHASE_MISMATCH`, HTTP 409)."

    Design: Corner/validations/test_phase_mismatch_downstream_during_upstream_rejected
    """
    env = setup_batch_upstream()
    batch_id = env["batch"]["id"]
    record_test(batch_id, batch_version=1)
    payload = create_test_payload(
        expected_batch_version=get_batch_entity(batch_id)["version"],
        test_type="TITER", phase="DOWNSTREAM", measured_value=2.4, unit="G/L",
        spec_min=2.0, spec_max=4.0)
    headers = make_manufacturing_operator_headers(_OP)
    validate_error(api.create_test(batch_id, payload, headers),
                   ApiErrorId.ERR_TEST_PHASE_MISMATCH)
    assert len(_tests_of(api, batch_id, platform_admin_headers)) == 1


def test_supersede_a_verified_test_rejected(api):
    """PRD §3.4: "`supersedes_test_id`, when present, must reference an `INVALIDATED` test on the same batch with the same `test_type` and `phase`, else `ERR_SUPERSEDE_TARGET_NOT_INVALIDATED` (HTTP 409)"

    Design: Corner/validations/supersede_a_verified_test_rejected
    """
    env = setup_batch_with_verified_upstream()
    batch_id = env["batch"]["id"]
    payload = create_test_payload(
        expected_batch_version=get_batch_entity(batch_id)["version"], measured_value=87.0,
        supersedes_test_id=env["upstream_test"]["id"])
    headers = make_manufacturing_operator_headers(_OP)
    validate_error(api.create_test(batch_id, payload, headers),
                   ApiErrorId.ERR_SUPERSEDE_TARGET_NOT_INVALIDATED)


def test_retest_after_invalidation_succeeds(api, platform_admin_headers):
    """PRD §3.5: "An `OOS` deviation closed as `INVALIDATED_TEST` moves its linked test from `OOS_SUSPECT` to `INVALIDATED` — making the test eligible as a `supersedes_test_id` target for a retest."
    PRD §3.4: "An out-of-spec test moves to `OOS_SUSPECT` with `verified_by_user_id` set, and the system immediately opens a deviation on the same batch"

    Design: Corner/validations/retest_after_invalidation_succeeds
    """
    env = setup_batch_downstream()
    batch_id = env["batch"]["id"]
    bad = record_test(batch_id, test_type="PURITY", phase="DOWNSTREAM",
                      measured_value=99.5, unit="PCT", spec_min=95.0, spec_max=96.0)
    assert verify_test_entity(bad["id"])["status"] == "OOS_SUSPECT"
    deviations, _m = validate_paginated(api.list_deviations(batch_id, platform_admin_headers))
    close_deviation(deviations[0]["id"], "INVALIDATED_TEST",
                    capa_summary="Analyst transcription error; raw data supports invalidation")
    rows = _tests_of(api, batch_id, platform_admin_headers)
    assert next(r for r in rows if r["id"] == bad["id"])["status"] == "INVALIDATED"
    payload = create_test_payload(
        expected_batch_version=get_batch_entity(batch_id)["version"],
        test_type="PURITY", phase="DOWNSTREAM", measured_value=95.5, unit="PCT",
        spec_min=95.0, spec_max=96.0, supersedes_test_id=bad["id"])
    headers = make_manufacturing_operator_headers(_OP)
    data = validate_success(api.create_test(batch_id, payload, headers), expected_status=201)
    assert data["status"] == "RECORDED" and data["is_in_spec"] is True
    assert data["supersedes_test_id"] == bad["id"]


def test_test_spec_bounds_inverted_rejected(api):
    """PRD §3.4: "the specification bounds `spec_min` and `spec_max` (the minimum must be strictly below the maximum, else `ERR_INVALID_SPEC_BOUNDS`)"

    Design: Corner/validations/test_spec_bounds_inverted_rejected
    """
    env = setup_batch_upstream()
    payload = create_test_payload(expected_batch_version=env["batch"]["version"],
                                  spec_min=96.0, spec_max=95.0)
    headers = make_manufacturing_operator_headers(_OP)
    validate_error(api.create_test(env["batch"]["id"], payload, headers),
                   ApiErrorId.ERR_INVALID_SPEC_BOUNDS)


def test_batch_advance_with_unverified_test_rejected(api):
    """PRD §3.4: "the upstream evidence must be complete: at least one `VERIFIED` `UPSTREAM` test exists, and every `UPSTREAM` test of the batch is in `VERIFIED` or `INVALIDATED` (`ERR_UNRESOLVED_TESTS`, HTTP 409)."

    Design: Corner/validations/batch_advance_with_unverified_test_rejected
    """
    env = setup_batch_upstream()
    batch_id = env["batch"]["id"]
    record_test(batch_id, batch_version=env["batch"]["version"])
    headers = make_manufacturing_operator_headers(_OP)
    validate_error(api.advance_batch(batch_id, "DOWNSTREAM", headers),
                   ApiErrorId.ERR_UNRESOLVED_TESTS)
    assert get_batch_entity(batch_id)["process_status"] == "UPSTREAM"


def test_qa_reviewer_cannot_record_tests(api, platform_admin_headers):
    """PRD §2.1: "a caller whose `X-User-Role` is not listed for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/batches/{id}/tests` | Record an in-process test result, optionally superseding an INVALIDATED test | ManufacturingOperator |"

    Design: Corner/rbac/qa_reviewer_cannot_record_tests
    """
    env = setup_batch_upstream()
    payload = create_test_payload(expected_batch_version=env["batch"]["version"])
    headers = make_quality_assurance_reviewer_headers(USER_IDS["reviewer"])
    validate_error(api.create_test(env["batch"]["id"], payload, headers),
                   ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert len(_tests_of(api, env["batch"]["id"], platform_admin_headers)) == 0


def test_operator_cannot_verify_tests(api, manufacturing_operator_2_headers,
                                      platform_admin_headers):
    """PRD §2.1: "a caller whose `X-User-Role` is not listed for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/tests/{id}/verify` | Verify a recorded test under four-eyes; out-of-spec auto-creates an OOS deviation | QualityControlAnalyst |"

    Design: Corner/rbac/operator_cannot_verify_tests
    """
    env = setup_batch_upstream()
    test = record_test(env["batch"]["id"], batch_version=env["batch"]["version"])
    validate_error(api.verify_test(test["id"], manufacturing_operator_2_headers),
                   ApiErrorId.ERR_FORBIDDEN_ROLE)
    rows = _tests_of(api, env["batch"]["id"], platform_admin_headers)
    assert rows[0]["status"] == "RECORDED"
