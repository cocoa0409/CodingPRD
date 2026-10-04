"""Disposition access controls: segregation of duties, role denial, posture and shelf-life."""
from test_helpers import (
    ApiErrorId, TEST_USERS, USER_IDS,
    validate_success, validate_error,
    setup_batch_pending_disposition, setup_released_batch, setup_batch_upstream,
    create_deviation_entity, record_and_verify_test, advance_batch,
    submit_batch_for_review, disposition_batch, get_batch_entity,
    make_quality_assurance_reviewer_headers, set_logical_clock,
)


def _disposition_payload(rationale):
    return {"decision": "RELEASED", "rationale": rationale}


def test_disposition_sod_manufacturer_cannot_release_own_batch(api):
    """PRD §2.10: "The `QualityAssuranceReviewer` who dispositions a batch must not be the user recorded as the batch's `manufactured_by_user_id`, and must not be the `verified_by_user_id` of any `VERIFIED` test on that batch. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/disposition_sod_manufacturer_cannot_release_own_batch
    """
    env = setup_batch_pending_disposition()
    batch_id = env["batch"]["id"]
    headers = make_quality_assurance_reviewer_headers(USER_IDS["operator"])
    resp = api.disposition_batch(batch_id, _disposition_payload(
        "Manufacturer attempting to release own batch"), headers)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_batch_entity(batch_id)["quality_status"] == "PENDING_DISPOSITION"


def test_disposition_sod_test_verifier_cannot_release(api):
    """PRD §2.10: "The `QualityAssuranceReviewer` who dispositions a batch must not be the user recorded as the batch's `manufactured_by_user_id`, and must not be the `verified_by_user_id` of any `VERIFIED` test on that batch. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/validations/disposition_sod_test_verifier_cannot_release
    """
    env = setup_batch_pending_disposition()
    batch_id = env["batch"]["id"]
    headers = make_quality_assurance_reviewer_headers(USER_IDS["analyst"])
    resp = api.disposition_batch(batch_id, _disposition_payload(
        "Verifier attempting to release"), headers)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_batch_entity(batch_id)["quality_status"] == "PENDING_DISPOSITION"


def test_process_engineer_cannot_disposition(api, process_engineer_headers):
    """PRD §2.1: "a caller whose `X-User-Role` is not listed for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/batches/{id}/disposition` | Disposition decision on a batch (release or reject) | QualityAssuranceReviewer |"

    Design: Corner/rbac/process_engineer_cannot_disposition
    """
    env = setup_batch_pending_disposition()
    batch_id = env["batch"]["id"]
    resp = api.disposition_batch(batch_id, _disposition_payload("Engineer attempting release"),
                                 process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert get_batch_entity(batch_id)["quality_status"] == "PENDING_DISPOSITION"


def test_disposition_on_released_batch_terminal_lockdown(api):
    """PRD §3.5: "The disposition decision itself carries a `decision` of `RELEASED` or `REJECTED` with a free-text `rationale`, and is admitted only from `PENDING_DISPOSITION` — the state check runs before every business check below (`ERR_INVALID_BATCH_STATE`, HTTP 409)."

    Design: Corner/state_machines/disposition_on_released_batch_terminal_lockdown
    """
    env = setup_released_batch()
    batch_id = env["batch"]["id"]
    headers = make_quality_assurance_reviewer_headers(USER_IDS["reviewer_2"])
    resp = api.disposition_batch(
        batch_id, {"decision": "REJECTED",
                   "rationale": "Second disposition attempt on a released batch"}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_BATCH_STATE)
    assert get_batch_entity(batch_id)["quality_status"] == "RELEASED"


def test_posture_conditional_still_allows_commercial_release(api, platform_admin_headers):
    """PRD §2.9: "It is `CONDITIONAL` when `open_critical_deviation_count` is exactly 1 (and no critical finding is open)."
    PRD §3.5: "the site release posture must not be `FROZEN` (`ERR_SITE_RELEASE_FROZEN`, HTTP 409)"

    Design: Corner/calculations/posture_conditional_still_allows_commercial_release
    """
    env = setup_batch_upstream()
    batch_id = env["batch"]["id"]
    create_deviation_entity(batch_id, kind="PROCESS", severity="CRITICAL",
                            description="Single open critical under investigation")
    record_and_verify_test(batch_id, test_type="CELL_VIABILITY", phase="UPSTREAM",
                           measured_value=85.0, unit="PCT", spec_min=80.0, spec_max=100.0)
    env["batch"] = advance_batch(batch_id, "DOWNSTREAM")
    version = env["batch"]["version"]
    for value in (2.4, 2.6):
        _test, version = record_and_verify_test(
            batch_id, batch_version=version, test_type="TITER", phase="DOWNSTREAM",
            measured_value=value, unit="G/L", spec_min=2.0, spec_max=4.0)
    advance_batch(batch_id, "PROCESS_COMPLETE")
    submit_batch_for_review(batch_id)
    site = validate_success(api.get_site(env["site"]["id"], platform_admin_headers))
    assert site["open_critical_deviation_count"] == 1
    assert site["release_posture"] == "CONDITIONAL"
    released = disposition_batch(batch_id, decision="RELEASED",
                                 rationale="One open critical documented; conditional permits")
    assert released["quality_status"] == "RELEASED"


def test_commercial_release_with_short_remaining_shelf_life_rejected(api):
    """PRD §3.5: "then, again for `COMMERCIAL` only, at least 720 hours must remain between the logical clock and the batch's `expiry_utc` — exactly 720 hours remaining is allowed, and fewer is `ERR_INSUFFICIENT_REMAINING_SHELF_LIFE` (HTTP 409)"

    Design: Corner/validations/commercial_release_with_short_remaining_shelf_life_rejected
    """
    env = setup_batch_pending_disposition(
        stage_durations=(10,),
        product_overrides={"product_code": "MAB-800", "shelf_life_hours": 800})
    batch_id = env["batch"]["id"]
    # Completion stamped at 2026-10-01T10:00Z; expiry +800 h; at 10-04T19:00Z 719 h remain.
    set_logical_clock("2026-10-04T19:00:00Z")
    headers = make_quality_assurance_reviewer_headers(USER_IDS["reviewer"])
    resp = api.disposition_batch(batch_id, _disposition_payload(
        "Attempted release with 719 hours remaining"), headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REMAINING_SHELF_LIFE)
    assert get_batch_entity(batch_id)["quality_status"] == "PENDING_DISPOSITION"
