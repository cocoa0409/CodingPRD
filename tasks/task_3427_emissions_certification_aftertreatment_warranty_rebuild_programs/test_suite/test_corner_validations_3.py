"""Corner coverage — validations, part 3 (PRD §3.2 segregation of duties and
test coverage, §2.1 ownership identity, §3.3 review gate and spec freeze,
§3.6 center authorization staffing, §3.4 serial uniqueness scope).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    ApiErrorId,
    SUBMITTER_USER_ID,
    add_accepted_test_run,
    add_maintenance_record,  # noqa: F401  (documented helper for this workflow)
    add_spec_version,
    add_technician,
    authorize_center,
    begin_family_testing,
    certify_family,
    create_campaign_work_order_payload,
    create_engine_unit_payload,
    create_family,
    create_maintenance_record_payload,
    create_service_center,
    declare_campaign,
    get_family,
    make_certification_engineer_headers,
    make_fleet_manager_headers,
    make_regulatory_officer_headers,
    make_service_advisor_headers,
    occ_spec_payload,
    record_run_results,
    review_run,
    schedule_test_run,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_family_testing,
    setup_family_in_production,
    setup_family_under_review,
    setup_fleet,
    setup_full_environment,
    stamp_family_non_conforming,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_certify_by_submitting_user_segregation_rejected(api):
    """PRD §3.2: "Three gates hold at that instant: accepted coverage for each of `FTP`, `RMC`, and `SET` must still exist (`ERR_REQUIRED_TEST_MISSING`); the officer's `X-User-ID` must differ from the family's `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403) — a check that passes when `submitted_by_user_id` is unset; and the family's regulation standard must still be `PUBLISHED` (`ERR_STANDARD_NOT_PUBLISHED`)."

    The same X-User-ID that submitted the family for review cannot certify it
    (403 ERR_SEGREGATION_OF_DUTIES); a different RegulatoryOfficer user
    certifies successfully.

    Design: Corner/validations/certify_by_submitting_user_segregation_rejected
    """
    env = setup_family_under_review()  # submitted_by_user_id == ce-quinn
    family_id = env["family"]["id"]
    assert env["family"]["submitted_by_user_id"] == SUBMITTER_USER_ID

    refused = api.certify_family(
        family_id, make_regulatory_officer_headers(SUBMITTER_USER_ID)
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    certified = certify_family(family_id)  # CERTIFIER_USER_ID != submitter
    assert certified["certification_status"] == "CERTIFIED", (
        f"a different officer certifies, got {certified['certification_status']}"
    )


def test_fleet_ownership_mismatch_on_maintenance_record(api):
    """PRD §2.1: "When `X-User-Role` is `FleetManager`, `X-User-ID` is the `id` of the acting `Fleet`; ownership checks on any resource that references a fleet compare that resource's `fleet_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FLEET_MISMATCH` (HTTP 403)."
    PRD §3.5: "a `FleetManager` may only append to units whose `fleet_id` matches their own `X-User-ID` (`ERR_FLEET_MISMATCH`)."

    The FleetManager of fleet A posting a maintenance record for fleet B's
    unit fails 403 ERR_FLEET_MISMATCH — entity-backed identity makes the check
    a direct id comparison.

    Design: Corner/validations/fleet_ownership_mismatch_on_maintenance_record
    """
    env = setup_family_in_production()
    fleet_a = setup_fleet()
    fleet_b = setup_fleet()
    unit_b = setup_engine_unit(env["family"]["id"], fleet_b["id"], serial_number="UN-101")

    refused = api.create_maintenance_record(
        unit_b["id"],
        create_maintenance_record_payload(
            performed_at="2026-11-10T00:00:00Z",
            maintenance_type="OIL_CHANGE", odometer_at_service=0,
        ),
        make_fleet_manager_headers(fleet_a["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_FLEET_MISMATCH)


def test_center_ownership_mismatch_on_work_order(api):
    """PRD §2.1: "When `X-User-Role` is `ServiceAdvisor`, `X-User-ID` is the `id` of the acting `ServiceCenter`; any claim, work-order, or reman-order create or transition that names a `service_center_id` compares that field to `X-User-ID`, and a mismatch is rejected with `ERR_CENTER_MISMATCH` (HTTP 403)."
    PRD §3.8: "The advisor's own center ownership applies as well: the `service_center_id` must equal the advisor's `X-User-ID` (`ERR_CENTER_MISMATCH`)."

    A ServiceAdvisor authenticated as center A cannot schedule a work order
    naming center B: 403 ERR_CENTER_MISMATCH.

    Design: Corner/validations/center_ownership_mismatch_on_work_order
    """
    env = setup_full_environment()
    center_a = env["center"]
    center_b = create_service_center(name="Other Center", region="NE", bay_capacity_per_day=3)
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-CC")

    refused = api.create_campaign_work_order(
        campaign["id"],
        create_campaign_work_order_payload(
            engine_unit_id=unit["id"],
            service_center_id=center_b["id"],
            assigned_technician_id=env["technician"]["id"],
        ),
        make_service_advisor_headers(center_a["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_CENTER_MISMATCH)


def test_accept_review_on_failing_run_rejected(api, officer_headers):
    """PRD §3.3: "Accepting requires the run's `result` to be `PASS`; a `decision` of `ACCEPT` on a `FAIL` run is rejected with `ERR_TEST_RESULT_NOT_PASS` (HTTP 409). Either decision stamps `reviewed_by_user_id` with the officer's `X-User-ID`."

    A run whose result is FAIL cannot be reviewed ACCEPT (409
    ERR_TEST_RESULT_NOT_PASS); the same run reviewed REJECT transitions fine —
    the gate keys on the computed result, not the reviewer's intent.

    Design: Corner/validations/accept_review_on_failing_run_rejected
    """
    env = setup_family_testing()
    run = schedule_test_run(env["family"]["id"], test_type="FTP")
    recorded = record_run_results(
        run["id"],
        measured_nox_g_per_bhp_hr=0.40,
        measured_pm_g_per_bhp_hr=0.008,
        deterioration_factor=1.0,
    )
    assert recorded["result"] == "FAIL"

    refused = api.review_test_run(run["id"], {"decision": "ACCEPT"}, officer_headers)
    validate_error(refused, ApiErrorId.ERR_TEST_RESULT_NOT_PASS)

    rejected = review_run(run["id"], "REJECT")
    assert rejected["status"] == "REJECTED", (
        f"REJECT on the same FAIL run succeeds, got {rejected['status']}"
    )


def test_authorize_center_without_certified_technician_rejected(api, admin_headers):
    """PRD §3.6: "Authorization then moves it from `AUDITED` to `AUTHORIZED` at a supplied `authorization_tier` of `BASIC`, `CERTIFIED`, or `MASTER`, and is refused with `ERR_NO_QUALIFIED_TECHNICIAN` (HTTP 409) unless at least one of the center's technicians is `CERT_ACTIVE` with `emissions_endorsed` set true at that moment."

    A center whose only technician lacks the emissions endorsement fails 409
    ERR_NO_QUALIFIED_TECHNICIAN at authorization; adding an endorsed
    technician then authorizes.

    Design: Corner/validations/authorize_center_without_certified_technician_rejected
    """
    center = create_service_center()
    add_technician(
        center["id"],
        full_name="Noah Bland", badge_id="T-09",
        certification_level="LEVEL_2", emissions_endorsed=False,
    )
    validate_success(api.audit_service_center(center["id"], admin_headers))

    refused = api.authorize_service_center(
        center["id"], {"authorization_tier": "CERTIFIED"}, admin_headers
    )
    validate_error(refused, ApiErrorId.ERR_NO_QUALIFIED_TECHNICIAN)

    add_technician(
        center["id"],
        full_name="Tess Adey", badge_id="T-01",
        certification_level="LEVEL_2", emissions_endorsed=True,
    )
    authorized = authorize_center(center["id"], "CERTIFIED")
    assert authorized["auth_status"] == "AUTHORIZED", (
        f"an endorsed CERT_ACTIVE technician satisfies the gate, got {authorized['auth_status']}"
    )


def test_spec_create_blocked_once_family_under_review(api, engineer_headers):
    """PRD §3.3: "The family must be in `DESIGN` or `TESTING`; a family past testing rejects spec creation with `ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING` (HTTP 409)."

    The aftertreatment design freezes when the family enters UNDER_REVIEW:
    creating a new spec version fails 409
    ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING even with a fresh OCC version, and the
    family still has exactly one spec.

    Design: Corner/validations/spec_create_blocked_once_family_under_review
    """
    env = setup_family_under_review()
    family_id = env["family"]["id"]
    family_now = get_family(family_id)

    refused = api.create_aftertreatment_spec(
        family_id,
        occ_spec_payload(
            family_now,
            scr_catalyst_part="SCR-902", dpf_part="DPF-452",
            doser_part="DSR-12", nox_sensor_count=3,
        ),
        engineer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_FAMILY_NOT_IN_DESIGN_OR_TESTING)

    specs, meta = validate_paginated(api.list_family_specs(family_id, engineer_headers))
    assert len(specs) == 1 and meta["total_count"] == 1, (
        f"the rejected create adds no spec version, got {len(specs)}"
    )


def test_submit_review_without_full_test_coverage_rejected(api, officer_headers):
    """PRD §3.2: "Submission requires, for each of the three required test types `FTP`, `RMC`, and `SET`, at least one certification test run in `ACCEPTED` status; a missing type is reported as `ERR_REQUIRED_TEST_MISSING` (HTTP 409)."

    With FTP and RMC ACCEPTED but the SET run merely COMPLETED (PASS, not yet
    reviewed), submit-review fails 409 ERR_REQUIRED_TEST_MISSING; accepting
    the SET run then lets the identical call through.

    Design: Corner/validations/submit_review_without_full_test_coverage_rejected
    """
    env = setup_family_testing()
    family_id = env["family"]["id"]
    add_accepted_test_run(family_id, "FTP")
    add_accepted_test_run(family_id, "RMC")
    set_run = schedule_test_run(family_id, test_type="SET")
    recorded = record_run_results(set_run["id"])
    assert recorded["result"] == "PASS" and recorded["status"] == "COMPLETED"

    refused = api.submit_review(
        family_id, make_certification_engineer_headers(SUBMITTER_USER_ID)
    )
    validate_error(refused, ApiErrorId.ERR_REQUIRED_TEST_MISSING)

    review_run(set_run["id"], "ACCEPT")
    submitted = validate_success(
        api.submit_review(family_id, make_certification_engineer_headers(SUBMITTER_USER_ID))
    )
    assert submitted["certification_status"] == "UNDER_REVIEW", (
        f"with all three types ACCEPTED the submission succeeds, got {submitted['certification_status']}"
    )


def test_duplicate_serial_number_rejected_within_family_only(api, admin_headers, officer_headers):
    """PRD §3.4: "An `EngineUnit` is a serialized engine in the field, registered by a `PlatformAdmin` with its `engine_family_id`, its owning `fleet_id`, a `serial_number` unique within the family (`ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409), and an `in_service_date`."

    Serial uniqueness is scoped per family: reusing UN-101 inside the same
    family fails 409 ERR_DUPLICATE_SERIAL_NUMBER, while a different
    IN_PRODUCTION family may register the same serial without conflict.

    Design: Corner/validations/duplicate_serial_number_rejected_within_family_only
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-101")

    # A second family on the same published standard, driven through the same
    # certification path to IN_PRODUCTION.
    family_b = create_family(
        env["standard"]["id"],
        family_code="G-B", model_year=2028,
        displacement_liters=8.9, architecture="EGR_DOC_DPF_SCR",
    )
    add_spec_version(
        family_b, calibrate_overrides={"observed_def_consumption_g_per_kwh": 4.5},
    )
    begin_family_testing(family_b["id"])
    for test_type in ("FTP", "RMC", "SET"):
        add_accepted_test_run(family_b["id"], test_type)
    validate_success(
        api.submit_review(family_b["id"], make_certification_engineer_headers(SUBMITTER_USER_ID))
    )
    certify_family(family_b["id"])
    validate_success(api.enter_production(family_b["id"], officer_headers))

    refused = api.create_engine_unit(
        create_engine_unit_payload(
            engine_family_id=env["family"]["id"], fleet_id=fleet["id"],
            serial_number="UN-101",
        ),
        admin_headers,
    )
    validate_error(refused, ApiErrorId.ERR_DUPLICATE_SERIAL_NUMBER)

    cross_family = validate_success(
        api.create_engine_unit(
            create_engine_unit_payload(
                engine_family_id=family_b["id"], fleet_id=fleet["id"],
                serial_number="UN-101",
            ),
            admin_headers,
        ),
        201,
    )
    assert cross_family["serial_number"] == "UN-101", (
        "the scope is (family, serial_number): the same serial in another "
        "family is a different unit"
    )
