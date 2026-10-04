"""Corner coverage — state machines, part 1 (PRD §2.4 lazy expiry, §3.2
family lifecycle, §3.3 spec and test-run lifecycle, §3.6 technician and
tool windows gating work orders).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    create_family,
    create_published_standard,
    get_family,
    invalidate_test_run_payload,
    make_certification_engineer_headers,
    make_regulatory_officer_headers,
    make_service_advisor_headers,
    occ_spec_payload,
    record_run_results,
    review_run,
    schedule_test_run,
    schedule_work_order,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_family_testing,
    setup_family_under_review,
    setup_full_environment,
    stamp_family_non_conforming,
    validate_error,
    validate_success,
)


def _dt(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant comparison."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_begin_testing_without_active_spec_returns_error(api, engineer_headers):
    """PRD §3.2: "From `DESIGN`, beginning testing moves the family to `TESTING` and is performed by a `CertificationEngineer`; it requires that an `ACTIVE` aftertreatment spec already exist for the family, otherwise the request is rejected with `ERR_NO_ACTIVE_AFTERTREATMENT_SPEC` (HTTP 409)."

    A family with no ACTIVE aftertreatment spec cannot begin testing: the
    transition is blocked until the spec pipeline completes, and the family
    does not move.

    Design: Corner/state_machines/begin_testing_without_active_spec_returns_error
    """
    standard = create_published_standard()
    family = create_family(standard["id"])

    resp = api.begin_testing(family["id"], engineer_headers)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AFTERTREATMENT_SPEC)

    family_now = get_family(family["id"])
    assert family_now["certification_status"] == "DESIGN", (
        f"the family must not move, got {family_now['certification_status']}"
    )


def test_certify_from_design_returns_invalid_state(api, officer_headers):
    """PRD §3.2: "Certification itself is performed by a `RegulatoryOfficer` and moves the family from `UNDER_REVIEW` to `CERTIFIED`."
    PRD §2.8: "State gates: the generic `ERR_INVALID_STATE_TRANSITION`, plus the specific state errors"

    certify on a DESIGN family is not a defined transition and fails 409
    ERR_INVALID_STATE_TRANSITION; the family does not move.

    Design: Corner/state_machines/certify_from_design_returns_invalid_state
    """
    standard = create_published_standard()
    family = create_family(standard["id"])

    resp = api.certify_family(family["id"], officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    family_now = get_family(family["id"])
    assert family_now["certification_status"] == "DESIGN"
    assert family_now["certified_at"] is None, (
        f"certified_at must remain unset, got {family_now['certified_at']!r}"
    )


def test_spec_created_in_draft_uncalibrated_initial_state(api, engineer_headers):
    """PRD §3.3: "The new spec receives a `spec_version` one greater than the family's current maximum — 1 for the family's first spec — starts in `DRAFT` status with `calibration_status` `UNCALIBRATED`, and has both `target_def_dosing_g_per_kwh` and `last_deviation_pct` unset."
    PRD §3.3: "Activation moves a spec from `DRAFT` to `ACTIVE` and requires both that `calibration_status` be `CALIBRATED` (`ERR_SPEC_NOT_CALIBRATED`, HTTP 409) and that the family still be in `DESIGN` or `TESTING` (`ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING`)."

    A freshly created spec is DRAFT and UNCALIBRATED with null
    target_def_dosing_g_per_kwh; activate is refused until calibrate succeeds.

    Design: Corner/state_machines/spec_created_in_draft_uncalibrated_initial_state
    """
    standard = create_published_standard()
    family = create_family(standard["id"])

    resp = api.create_aftertreatment_spec(
        family["id"], occ_spec_payload(family), engineer_headers
    )
    spec = validate_success(resp, 201)
    assert spec["status"] == "DRAFT"
    assert spec["calibration_status"] == "UNCALIBRATED"
    assert spec["spec_version"] == 1
    assert spec["target_def_dosing_g_per_kwh"] is None
    assert spec["last_deviation_pct"] is None

    refused = api.activate_spec(spec["id"], engineer_headers)
    validate_error(refused, ApiErrorId.ERR_SPEC_NOT_CALIBRATED)


def test_return_to_testing_revision_loop_cycles(api, engineer_headers):
    """PRD §3.2: "Should evidence be withdrawn mid-review — for example when an accepted run is invalidated — a `CertificationEngineer` can return the family from `UNDER_REVIEW` to `TESTING` through the revision loop, which carries no preconditions."
    PRD §3.2: "Submission stamps `submitted_by_user_id` with the caller's `X-User-ID`, which becomes the segregation-of-duties anchor for certification."
    PRD §3.2: "the officer's `X-User-ID` must differ from the family's `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)"

    The family loops UNDER_REVIEW -> TESTING -> UNDER_REVIEW; the second
    submission refreshes submitted_by_user_id to ce-lena, and certification by
    that same user id is then refused.

    Design: Corner/state_machines/return_to_testing_revision_loop_cycles
    """
    env = setup_family_under_review()  # submitted by ce-quinn
    family_id = env["family"]["id"]

    back = validate_success(api.return_to_testing(family_id, engineer_headers))
    assert back["certification_status"] == "TESTING", (
        f"return-to-testing lands in TESTING, got {back['certification_status']}"
    )

    resubmitted = validate_success(
        api.submit_review(family_id, make_certification_engineer_headers("ce-lena"))
    )
    assert resubmitted["certification_status"] == "UNDER_REVIEW"
    assert resubmitted["submitted_by_user_id"] == "ce-lena", (
        "submission restamps the anchor with the caller's X-User-ID, "
        f"got {resubmitted['submitted_by_user_id']}"
    )

    refused = api.certify_family(family_id, make_regulatory_officer_headers("ce-lena"))
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_technician_lazy_expiry_blocks_work_order_assignment(api, admin_headers):
    """PRD §3.6: "whenever the logical clock is strictly later than `certification_expires_at`, the technician is `EXPIRED` on next read or use; at the exact expiry instant the technician remains `CERT_ACTIVE`."
    PRD §3.8: "the assigned technician must belong to the named center, must be `CERT_ACTIVE` at the current logical clock, must be `emissions_endorsed`, and — for any work order occupying 3 or more bay days — must hold `LEVEL_2` or `LEVEL_3` certification, with any shortfall rejected as `ERR_TECHNICIAN_NOT_QUALIFIED` (HTTP 409)"
    PRD §3.6: "Recertification — available from either `CERT_ACTIVE` or `EXPIRED` — restamps `certified_at` from the current clock, extends `certification_expires_at` to 730 days after the recertification instant, and applies an optional `new_level` to `certification_level` when one is supplied."

    With the clock at 2028-09-01T00:00:00Z (past the 2028-08-31 expiry) the
    assignment fails ERR_TECHNICIAN_NOT_QUALIFIED; recertify extends validity
    to 2030-09-01T00:00:00Z and the identical assignment then succeeds.

    Design: Corner/state_machines/technician_lazy_expiry_blocks_work_order_assignment
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-C4")

    set_logical_clock("2028-09-01T00:00:00Z")
    refused = api.create_campaign_work_order(
        campaign["id"],
        {
            "engine_unit_id": unit["id"],
            "service_center_id": center_id,
            "assigned_technician_id": env["technician"]["id"],
            "scheduled_start_day": "2028-09-05T00:00:00Z",
            "bay_days": 1,
        },
        make_service_advisor_headers(center_id),
    )
    validate_error(refused, ApiErrorId.ERR_TECHNICIAN_NOT_QUALIFIED)

    renewed = validate_success(
        api.recertify_technician(env["technician"]["id"], {}, admin_headers)
    )
    assert renewed["cert_status"] == "CERT_ACTIVE"
    assert _dt(renewed["certification_expires_at"]) == _dt("2030-09-01T00:00:00Z"), (
        "recertification extends expiry 730 days past the 2028-09-01 clock, "
        f"got {renewed['certification_expires_at']}"
    )

    scheduled = schedule_work_order(
        campaign["id"], unit["id"], center_id, env["technician"]["id"],
        scheduled_start_day="2028-09-05T00:00:00Z", bay_days=1,
    )
    assert scheduled["status"] == "SCHEDULED"


def test_tool_lazy_recal_due_blocks_work_order_start(api, admin_headers):
    """PRD §3.8: "Starting the order moves it from `SCHEDULED` to `IN_BAY` and requires the center to hold at least one diagnostic tool whose effective status is `CALIBRATED_ACTIVE` at that moment (`ERR_TOOL_NOT_CALIBRATED`, HTTP 409) — this is where the lazy `RECAL_DUE` evaluation of §2.4 bites, because a tool whose validity has lapsed does not count."
    PRD §3.6: "recalibration by a `PlatformAdmin` returns it to `CALIBRATED_ACTIVE` and extends `calibration_valid_until` to 365 days after the recalibration instant."

    A tool issued 2026-09-01 turns RECAL_DUE once the clock passes
    2027-09-01T00:00:00Z; starting a work order then fails
    ERR_TOOL_NOT_CALIBRATED until recalibration extends validity to
    2028-09-01T00:00:00Z.

    Design: Corner/state_machines/tool_lazy_recal_due_blocks_work_order_start
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-C5")
    work_order = schedule_work_order(
        campaign["id"], unit["id"], center_id, env["technician"]["id"],
        scheduled_start_day="2027-01-04T00:00:00Z", bay_days=1,
    )

    set_logical_clock("2027-09-02T00:00:00Z")
    refused = api.start_work_order(work_order["id"], make_service_advisor_headers(center_id))
    validate_error(refused, ApiErrorId.ERR_TOOL_NOT_CALIBRATED)

    tool = validate_success(api.recalibrate_tool(env["tool"]["id"], admin_headers))
    assert tool["tool_status"] == "CALIBRATED_ACTIVE"
    assert _dt(tool["calibration_valid_until"]) == _dt("2028-09-01T00:00:00Z"), (
        "recalibration extends validity 365 days past the 2027-09-02 clock, "
        f"got {tool['calibration_valid_until']}"
    )

    started = validate_success(
        api.start_work_order(work_order["id"], make_service_advisor_headers(center_id))
    )
    assert started["status"] == "IN_BAY", (
        f"start after recalibration succeeds, got {started['status']}"
    )


def test_rejected_test_run_is_terminal(api, officer_headers):
    """PRD §3.3: "Review belongs to a `RegulatoryOfficer`, whose `decision` — exactly `ACCEPT` or `REJECT` — moves a `COMPLETED` run to `ACCEPTED` or `REJECTED` respectively."
    PRD §3.3: "Finally, an `ACCEPTED` run may be invalidated by a `RegulatoryOfficer`, moving it to `INVALIDATED` and capturing the supplied `reason` into `invalidated_reason`."
    PRD §2.8: "State gates: the generic `ERR_INVALID_STATE_TRANSITION`, plus the specific state errors"

    A REJECTED run accepts no further transitions: invalidate on REJECTED
    fails 409 ERR_INVALID_STATE_TRANSITION and the run remains REJECTED.

    Design: Corner/state_machines/rejected_test_run_is_terminal
    """
    env = setup_family_testing()
    run = schedule_test_run(env["family"]["id"], test_type="FTP")
    recorded = record_run_results(
        run["id"],
        measured_nox_g_per_bhp_hr=0.40,
        measured_pm_g_per_bhp_hr=0.008,
        deterioration_factor=1.0,
    )
    assert recorded["adjusted_nox_g_per_bhp_hr"] == 0.4, (
        f"0.40 x 1.0 rounds to 0.4, got {recorded['adjusted_nox_g_per_bhp_hr']}"
    )
    assert recorded["result"] == "FAIL", (
        f"0.4 exceeds the 0.35 NOx limit, got {recorded['result']}"
    )
    rejected = review_run(run["id"], "REJECT")
    assert rejected["status"] == "REJECTED"

    refused = api.invalidate_test_run(
        run["id"], invalidate_test_run_payload("lab audit finding"), officer_headers
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    run_now = validate_success(api.get_test_run(run["id"], officer_headers))
    assert run_now["status"] == "REJECTED"


def test_invalidating_accepted_run_drops_certify_coverage(api, officer_headers):
    """PRD §3.3: "Invalidation does not itself re-open the family; the family's accepted test coverage is re-evaluated lazily at the next submit-review or certify, which is where a newly missing test type surfaces as `ERR_REQUIRED_TEST_MISSING`."
    PRD §3.2: "Three gates hold at that instant: accepted coverage for each of `FTP`, `RMC`, and `SET` must still exist (`ERR_REQUIRED_TEST_MISSING`)"

    Invalidating the family's only ACCEPTED FTP run after submit-review makes
    certify fail with ERR_REQUIRED_TEST_MISSING even though submit-review had
    passed; the family stays UNDER_REVIEW.

    Design: Corner/state_machines/invalidating_accepted_run_drops_certify_coverage
    """
    env = setup_family_under_review()  # one ACCEPTED run per required type
    family_id = env["family"]["id"]
    ftp_run_id = env["runs"]["FTP"]["id"]

    invalidated = validate_success(
        api.invalidate_test_run(
            ftp_run_id,
            invalidate_test_run_payload("dilution tunnel calibration lapsed"),
            officer_headers,
        )
    )
    assert invalidated["status"] == "INVALIDATED"

    refused = api.certify_family(family_id, make_regulatory_officer_headers("ro-mara"))
    validate_error(refused, ApiErrorId.ERR_REQUIRED_TEST_MISSING)

    family_now = get_family(family_id)
    assert family_now["certification_status"] == "UNDER_REVIEW", (
        f"the family must not move, got {family_now['certification_status']}"
    )
