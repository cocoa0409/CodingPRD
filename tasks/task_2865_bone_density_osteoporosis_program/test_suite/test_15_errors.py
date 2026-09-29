"""Every refusal the program can reach, each raised against a store it must not alter.

The refusals are grouped by the workflow they guard rather than by status code, so
each case also shows which gate answered and which ones never got the chance.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    BMD_FEMORAL_NECK_OSTEOPENIC,
    BMD_FEMORAL_NECK_OSTEOPOROTIC,
    BMD_LUMBAR_OSTEOPENIC,
    BMD_TOTAL_HIP_OSTEOPENIC,
    CLOCK_SCAN_DAY,
    CLOCK_SETUP,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_HEADERS,
    appointment_payload,
    assert_counters,
    assert_four_decimals,
    assert_score_one_decimal,
    assert_two_decimals,
    calibration_event_payload,
    densitometer_payload,
    diagnostic_report_payload,
    frax_payload,
    get_success_data,
    patient_payload,
    payer_policy_payload,
    precision_assessment_payload,
    qc_run_payload,
    report_patch_payload,
    scan_order_payload,
    scan_session_payload,
    site_measurement_payload,
    validate_error,
    validate_paginated,
    validate_success,
    vfa_payload,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"

_OTHER_VENDOR = {
    "manufacturer": "GE_LUNAR",
    "model": "iDXA",
    "site_code": "WEST",
    "phantom_baseline_bmd_g_cm2": 1.0500,
    "phantom_baseline_sd_g_cm2": 0.0120,
    "appointment_buffer_minutes": 20,
    "daily_scan_capacity": 8,
}


class TestEveryAddressableTypeHasItsOwnNotFound:
    """Eight unknown identifiers, eight different codes, all at 404."""

    def test_the_schema_check_still_outranks_the_lookup(self, world: ProgramWorld):
        """A malformed body under an unknown parent is answered 422, not 404.

        "(4) No densitometer with that id, on every endpoint whose path contains a
        densitometer id — `ERR_DENSITOMETER_NOT_FOUND`, 404. (5) No phantom run with
        that id, on `GET /bone-density/qc-runs/{id}` — `ERR_QC_RUN_NOT_FOUND`, 404."
        "(8) No order with that id, on `GET /bone-density/scan-orders/{id}` —
        `ERR_SCAN_ORDER_NOT_FOUND`, 404. (9) No appointment with that id, on every
        endpoint whose path contains a scan appointment id —
        `ERR_SCAN_APPOINTMENT_NOT_FOUND`, 404."
        "(11) No assessment with that id, on `GET /bone-density/frax-assessments/{id}`
        — `ERR_FRAX_ASSESSMENT_NOT_FOUND`, 404. (12) No report with that id, on every
        endpoint whose path contains a diagnostic report id —
        `ERR_DIAGNOSTIC_REPORT_NOT_FOUND`, 404. (13) No plan with that id, on every
        endpoint whose path contains a treatment plan id —
        `ERR_TREATMENT_PLAN_NOT_FOUND`, 404."

        Design: Corner/errors/unknown_path_identifiers_return_type_specific_not_found_after_the_body_check
        """
        lookups = [
            (world.api.get_densitometer(UNKNOWN_ID, ADMIN_HEADERS),
             ApiErrorId.DENSITOMETER_NOT_FOUND.value),
            (world.api.get_qc_run(UNKNOWN_ID, ADMIN_HEADERS),
             ApiErrorId.QC_RUN_NOT_FOUND.value),
            (world.api.get_calibration_event(UNKNOWN_ID, ADMIN_HEADERS),
             ApiErrorId.CALIBRATION_EVENT_NOT_FOUND.value),
            (world.api.get_scan_order(UNKNOWN_ID, ADMIN_HEADERS),
             ApiErrorId.SCAN_ORDER_NOT_FOUND.value),
            (world.api.get_scan_appointment(UNKNOWN_ID, ADMIN_HEADERS),
             ApiErrorId.SCAN_APPOINTMENT_NOT_FOUND.value),
            (world.api.get_frax_assessment(UNKNOWN_ID, ADMIN_HEADERS),
             ApiErrorId.FRAX_ASSESSMENT_NOT_FOUND.value),
            (world.api.get_diagnostic_report(UNKNOWN_ID, ADMIN_HEADERS),
             ApiErrorId.DIAGNOSTIC_REPORT_NOT_FOUND.value),
            (world.api.get_treatment_plan(UNKNOWN_ID, ADMIN_HEADERS),
             ApiErrorId.TREATMENT_PLAN_NOT_FOUND.value),
        ]
        for response, expected_error_id in lookups:
            validate_error(response, expected_error_id, 404)

        malformed = world.api.create_qc_run(
            UNKNOWN_ID, qc_run_payload(purpose="NOT_A_PURPOSE"), ADMIN_HEADERS
        )
        validate_error(malformed, ApiErrorId.INVALID_REQUEST.value, 422)

        well_formed = world.api.create_qc_run(
            UNKNOWN_ID, qc_run_payload(phantom_bmd_g_cm2=1.0000), ADMIN_HEADERS
        )
        validate_error(well_formed, ApiErrorId.DENSITOMETER_NOT_FOUND.value, 404)


class TestTheThreeBusinessKeysAreUniqueAcrossTheStore:
    """A key collision is decided on the key alone."""

    def test_each_duplicate_key_has_its_own_conflict_and_a_new_key_is_accepted(
        self, world: ProgramWorld
    ):
        """Three re-registrations refused, and the fourth differs only in its key.

        "(52) `serial_number` already registered, on `POST /bone-density/densitometers`
        — `ERR_SERIAL_NUMBER_TAKEN`, 409. (53) `mrn` already registered, on `POST
        /bone-density/patients` — `ERR_MRN_TAKEN`, 409. (54) `payer_code` already
        registered, on `POST /bone-density/payer-policies` — `ERR_PAYER_CODE_TAKEN`,
        409."

        Design: Corner/errors/duplicate_serial_number_mrn_and_payer_code_are_rejected
        """
        world.set_clock(CLOCK_SETUP)
        policy = world.create_policy(payer_code="PAY-STD")
        world.create_device(serial_number="HLG-0001")
        world.create_patient(policy["id"], mrn="MRN-6901")

        same_code = world.api.create_payer_policy(
            payer_policy_payload(
                payer_code="PAY-STD",
                name="A Different Plan",
                baseline_screening_min_interval_months=12,
                vfa_covered=False,
                max_lifetime_screening_scans=4,
                appeal_allowed=True,
            ),
            ADMIN_HEADERS,
        )
        validate_error(same_code, ApiErrorId.PAYER_CODE_TAKEN.value, 409)

        same_serial = world.api.create_densitometer(
            densitometer_payload(serial_number="HLG-0001", **_OTHER_VENDOR),
            ADMIN_HEADERS,
        )
        validate_error(same_serial, ApiErrorId.SERIAL_NUMBER_TAKEN.value, 409)

        same_mrn = world.api.create_patient(
            patient_payload(
                policy["id"],
                mrn="MRN-6901",
                birth_date="1970-01-01",
                sex="MALE",
                postmenopausal=False,
                baseline_height_cm=178.0,
            ),
            SCHEDULER_HEADERS,
        )
        validate_error(same_mrn, ApiErrorId.MRN_TAKEN.value, 409)

        accepted = validate_success(
            world.api.create_densitometer(
                densitometer_payload(serial_number="HLG-0002", **_OTHER_VENDOR),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert accepted["serial_number"] == "HLG-0002"
        assert accepted["status"] == "ACTIVE"

        _, policies = validate_paginated(world.api.list_payer_policies(ADMIN_HEADERS))
        assert policies["total_count"] == 1
        _, patients = validate_paginated(world.api.list_patients(SCHEDULER_HEADERS))
        assert patients["total_count"] == 1
        _, devices = validate_paginated(world.api.list_densitometers(ADMIN_HEADERS))
        assert devices["total_count"] == 2


WITHIN_TOLERANCE_PHANTOM = 1.0090


def _uncertified_device_with_a_booked_slot(world: ProgramWorld):
    """A device that never passed a precision study, already carrying a slot."""
    world.set_clock(CLOCK_SETUP)
    policy = world.create_policy()
    device = world.create_device(serial_number="HLG-0002")
    patient = world.create_patient(policy["id"])
    order = world.create_order(patient["id"])
    appointment = world.book(order["id"], device["id"])
    world.set_clock(CLOCK_SCAN_DAY)
    return device, appointment


class TestTheEquipmentQualificationGatesEachRefuseInTurn:
    """Four independent gates guard certification and cross-calibration."""

    def test_an_underpowered_study_leaves_the_device_uncertified(
        self, world: ProgramWorld
    ):
        """Twenty-nine degrees of freedom is refused, and the acquisition cannot start.

        "`precision_degrees_of_freedom` is the patient count multiplied by one less than
        the scans per patient. That product must be **at least thirty**; below thirty the
        study is refused with `ERR_PRECISION_STUDY_UNDERPOWERED` and nothing whatsoever
        is persisted — the device keeps whatever precision state it already had."
        "(37) The appointment's densitometer has a null `lsc_g_cm2`, on `POST
        /bone-density/scan-appointments/{id}/scan-sessions` —
        `ERR_DEVICE_PRECISION_NOT_CERTIFIED`, 409."

        Design: Corner/errors/precision_and_cross_calibration_gates_are_each_rejected_in_turn
        """
        device, appointment = _uncertified_device_with_a_booked_slot(world)

        underpowered = world.api.create_precision_assessment(
            device["id"],
            precision_assessment_payload(device["version"], patient_count=29),
            ADMIN_HEADERS,
        )
        validate_error(
            underpowered, ApiErrorId.PRECISION_STUDY_UNDERPOWERED.value, 422
        )

        reread = world.read_device(device["id"])
        assert reread["lsc_g_cm2"] is None
        assert reread["precision_degrees_of_freedom"] is None

        blocked = world.api.create_scan_session(
            appointment["id"], scan_session_payload(), TECHNOLOGIST_HEADERS
        )
        validate_error(
            blocked, ApiErrorId.DEVICE_PRECISION_NOT_CERTIFIED.value, 409
        )

        event = validate_success(
            world.api.create_calibration_event(
                device["id"],
                calibration_event_payload(change_note="Vendor patch 7.1"),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert event["status"] == "OPEN"
        assert event["required_phantom_runs"] == 3
        assert world.read_device(device["id"])["status"] == "CROSS_CAL_PENDING"

        premature = world.api.adjudicate_calibration_event(event["id"], ADMIN_HEADERS)
        validate_error(premature, ApiErrorId.CALIBRATION_EVENT_NOT_CLOSED.value, 409)

        world.record_cross_cal_runs(
            device["id"], event["id"], "CROSS_CAL_BASELINE", 1.0000, 1
        )
        short_set = world.api.close_calibration_event(event["id"], ADMIN_HEADERS)
        validate_error(short_set, ApiErrorId.PHANTOM_SET_INCOMPLETE.value, 409)

        partial = get_success_data(
            world.api.get_calibration_event(event["id"], ADMIN_HEADERS)
        )
        assert partial["baseline_run_count"] == 1
        assert partial["new_run_count"] == 0

        world.record_cross_cal_runs(
            device["id"], event["id"], "CROSS_CAL_BASELINE", 1.0000, 2
        )
        world.record_cross_cal_runs(
            device["id"], event["id"], "CROSS_CAL_NEW", WITHIN_TOLERANCE_PHANTOM, 3
        )

        closed = validate_success(
            world.api.close_calibration_event(event["id"], ADMIN_HEADERS), 200
        )
        assert closed["status"] == "PHANTOM_SET_COMPLETE"
        assert_four_decimals(
            closed["baseline_mean_bmd_g_cm2"], 1.0000, "baseline_mean_bmd_g_cm2"
        )
        assert_four_decimals(
            closed["new_mean_bmd_g_cm2"], 1.0090, "new_mean_bmd_g_cm2"
        )
        assert_two_decimals(closed["percent_difference"], 0.90, "percent_difference")
        assert closed["outcome_code"] == "WITHIN_TOLERANCE_NO_FACTOR"
        assert_four_decimals(
            closed["proposed_cross_cal_factor"], 1.0000, "proposed_cross_cal_factor"
        )

        closed_twice = world.api.close_calibration_event(event["id"], ADMIN_HEADERS)
        validate_error(closed_twice, ApiErrorId.CALIBRATION_EVENT_NOT_OPEN.value, 409)
        assert (
            get_success_data(
                world.api.get_calibration_event(event["id"], ADMIN_HEADERS)
            )["status"]
            == "PHANTOM_SET_COMPLETE"
        )


def _two_patients_and_a_lumbar_only_session(world: ProgramWorld):
    """Patient A with a superseded profile and a lumbar-only study; patient B alone."""
    world.set_clock(CLOCK_SETUP)
    policy = world.create_policy()
    device = world.create_certified_device()
    patient_a = world.create_patient(policy["id"])
    patient_b = world.create_patient(
        policy["id"], birth_date="1955-02-02", baseline_height_cm=160.0
    )
    profile_a1 = world.create_profile(patient_a, height_cm=166.0, weight_kg=60.0)
    profile_a2 = world.create_profile(patient_a, height_cm=165.0, weight_kg=58.0)
    profile_b1 = world.create_profile(patient_b, height_cm=160.0, weight_kg=55.0)

    order = world.create_order(patient_a["id"], requested_sites=["LUMBAR_SPINE"])
    appointment = world.book(order["id"], device["id"])
    world.set_clock(CLOCK_SCAN_DAY)
    session = world.start_session(appointment["id"])
    world.measure(session["id"], "LUMBAR_SPINE", BMD_LUMBAR_OSTEOPENIC)
    return patient_a, patient_b, profile_a1, profile_a2, profile_b1, session


class TestTheFraxReferenceGatesAnswerBeforeAnyPointsAreSummed:
    """Three reference gates, then the same call succeeds on its own terms."""

    def test_a_superseded_profile_a_foreign_profile_and_a_lumbar_only_session(
        self, world: ProgramWorld
    ):
        """None of the three refusals leaves an assessment behind.

        "The profile must belong to the named patient and must be in `status` `ACTIVE`,
        so a `SUPERSEDED` profile is refused with `ERR_RISK_PROFILE_NOT_ACTIVE` and a
        profile or session belonging to a different patient is refused with
        `ERR_FRAX_PATIENT_MISMATCH`. When a session is supplied it must carry a usable,
        non-superseded `FEMORAL_NECK` measurement, since that is the only site FRAX
        accepts; otherwise the request is refused with `ERR_FEMORAL_NECK_REQUIRED`."
        "That last field alone selects between the two variants: supplying it produces
        `variant` `WITH_BMD`, omitting it produces `WITHOUT_BMD`."

        Design: Corner/errors/frax_assessment_reference_gates_are_rejected_before_any_scoring
        """
        (
            patient_a,
            patient_b,
            profile_a1,
            profile_a2,
            profile_b1,
            session,
        ) = _two_patients_and_a_lumbar_only_session(world)

        profiles, _ = validate_paginated(
            world.api.list_risk_factor_profiles(patient_a["id"], PHYSICIAN_HEADERS)
        )
        by_id = {row["id"]: row["status"] for row in profiles}
        assert by_id[profile_a1["id"]] == "SUPERSEDED"
        assert by_id[profile_a2["id"]] == "ACTIVE"

        superseded = world.api.create_frax_assessment(
            frax_payload(patient_a["id"], profile_a1["id"]), PHYSICIAN_HEADERS
        )
        validate_error(superseded, ApiErrorId.RISK_PROFILE_NOT_ACTIVE.value, 409)

        foreign = world.api.create_frax_assessment(
            frax_payload(patient_b["id"], profile_a2["id"]), PHYSICIAN_HEADERS
        )
        validate_error(foreign, ApiErrorId.FRAX_PATIENT_MISMATCH.value, 409)

        no_femoral_neck = world.api.create_frax_assessment(
            frax_payload(patient_a["id"], profile_a2["id"], session["id"]),
            PHYSICIAN_HEADERS,
        )
        validate_error(no_femoral_neck, ApiErrorId.FEMORAL_NECK_REQUIRED.value, 422)

        without_bmd = validate_success(
            world.api.create_frax_assessment(
                frax_payload(patient_a["id"], profile_a2["id"]), PHYSICIAN_HEADERS
            ),
            201,
        )
        assert without_bmd["variant"] == "WITHOUT_BMD"
        assert_two_decimals(without_bmd["bmd_points"], 0.00, "bmd_points")
        assert_two_decimals(without_bmd["raw_score"], 2.30, "raw_score")
        assert_score_one_decimal(
            without_bmd["major_osteoporotic_10yr_pct"],
            16.8,
            "major_osteoporotic_10yr_pct",
        )
        assert_score_one_decimal(
            without_bmd["hip_fracture_10yr_pct"], 4.1, "hip_fracture_10yr_pct"
        )

        _, for_a = validate_paginated(
            world.api.list_frax_assessments(
                PHYSICIAN_HEADERS, {"patient_id": patient_a["id"]}
            )
        )
        assert for_a["total_count"] == 1

        _, for_b = validate_paginated(
            world.api.list_frax_assessments(
                PHYSICIAN_HEADERS, {"patient_id": patient_b["id"]}
            )
        )
        assert for_b["total_count"] == 0
        assert profile_b1["status"] == "ACTIVE"


class TestOneSessionWalksEveryAcquisitionAndReportingGate:
    """The order asked for two sites, and every shortcut past them is refused."""

    def test_the_gates_fire_in_sequence_and_only_two_rows_survive(
        self, world: ProgramWorld
    ):
        """Six refusals and five acceptances against a single session.

        "(47) A lumbar spine measurement with too few or duplicated vertebral levels, on
        `POST /bone-density/scan-sessions/{id}/site-measurements` —
        `ERR_INSUFFICIENT_VALID_VERTEBRAE`, 422. (48) A non-superseded measurement for
        the same `site_code` already exists on the session, on `POST
        /bone-density/scan-sessions/{id}/site-measurements` —
        `ERR_DUPLICATE_SITE_MEASUREMENT`, 409. (49) The session has zero non-superseded
        measurements, on `POST /bone-density/scan-sessions/{id}/submit-acquisition` —
        `ERR_NO_SITE_MEASUREMENTS`, 422. (50) At least one requested site has no
        non-superseded measurement, on `POST
        /bone-density/scan-sessions/{id}/submit-acquisition` —
        `ERR_REQUESTED_SITES_INCOMPLETE`, 422."
        "(30) The session's `acquisition_status` is `ARCHIVED`, on `POST
        /bone-density/scan-sessions/{id}/site-measurements` ... —
        `ERR_SESSION_ARCHIVED`, 409."
        "(33) Another report on the same `scan_session_id` is already `DRAFT`, on `POST
        /bone-density/diagnostic-reports` and `POST
        /bone-density/diagnostic-reports/{id}/amend` — `ERR_REPORT_ALREADY_EXISTS`, 409."
        "(31) The report is not `DRAFT`, on `PATCH /bone-density/diagnostic-reports/{id}`
        and `POST /bone-density/diagnostic-reports/{id}/finalize` —
        `ERR_REPORT_NOT_DRAFT`, 409."

        Design: Corner/errors/acquisition_and_report_gates_are_rejected_across_the_session_lifecycle
        """
        pipeline = world.build(
            stop_after="session",
            order_overrides={"requested_sites": ["FEMORAL_NECK", "LUMBAR_SPINE"]},
        )
        session_id = pipeline.session_id

        nothing_measured = world.api.submit_acquisition(session_id, TECHNOLOGIST_HEADERS)
        validate_error(nothing_measured, ApiErrorId.NO_SITE_MEASUREMENTS.value, 422)

        one_level = world.api.create_site_measurement(
            session_id,
            site_measurement_payload(
                "LUMBAR_SPINE", BMD_LUMBAR_OSTEOPENIC, included_vertebrae=["L1"]
            ),
            TECHNOLOGIST_HEADERS,
        )
        validate_error(one_level, ApiErrorId.INSUFFICIENT_VALID_VERTEBRAE.value, 422)

        femoral_neck = validate_success(
            world.api.create_site_measurement(
                session_id,
                site_measurement_payload("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )
        assert_score_one_decimal(femoral_neck["t_score"], -2.0, "t_score")
        assert_score_one_decimal(femoral_neck["z_score"], -0.5, "z_score")
        assert femoral_neck["site_usable_for_diagnosis"] is True

        duplicate = world.api.create_site_measurement(
            session_id,
            site_measurement_payload("FEMORAL_NECK", 0.6600),
            TECHNOLOGIST_HEADERS,
        )
        validate_error(duplicate, ApiErrorId.DUPLICATE_SITE_MEASUREMENT.value, 409)

        still_incomplete = world.api.submit_acquisition(session_id, TECHNOLOGIST_HEADERS)
        validate_error(
            still_incomplete, ApiErrorId.REQUESTED_SITES_INCOMPLETE.value, 422
        )

        lumbar = validate_success(
            world.api.create_site_measurement(
                session_id,
                site_measurement_payload(
                    "LUMBAR_SPINE",
                    BMD_LUMBAR_OSTEOPENIC,
                    included_vertebrae=["L1", "L2"],
                ),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )
        assert lumbar["valid_vertebral_count"] == 2
        assert_score_one_decimal(lumbar["t_score"], -1.7, "t_score")

        submitted = validate_success(
            world.api.submit_acquisition(session_id, TECHNOLOGIST_HEADERS), 200
        )
        assert submitted["acquisition_status"] == "SUBMITTED"
        assert submitted["measured_site_count"] == 2
        assert_score_one_decimal(submitted["lowest_t_score"], -2.0, "lowest_t_score")
        assert submitted["lowest_t_score_site"] == "FEMORAL_NECK"

        world.review_positioning(session_id, [])
        report = validate_success(
            world.api.create_diagnostic_report(
                diagnostic_report_payload(session_id), PHYSICIAN_HEADERS
            ),
            201,
        )

        second_draft = world.api.create_diagnostic_report(
            diagnostic_report_payload(session_id), PHYSICIAN_HEADERS
        )
        validate_error(second_draft, ApiErrorId.REPORT_ALREADY_EXISTS.value, 409)

        finalized = validate_success(
            world.api.finalize_diagnostic_report(report["id"], PHYSICIAN_HEADERS), 200
        )
        assert finalized["status"] == "FINALIZED"

        after_archive = world.api.create_site_measurement(
            session_id,
            site_measurement_payload("TOTAL_HIP", BMD_TOTAL_HIP_OSTEOPENIC),
            TECHNOLOGIST_HEADERS,
        )
        validate_error(after_archive, ApiErrorId.SESSION_ARCHIVED.value, 409)

        late_patch = world.api.update_diagnostic_report(
            report["id"],
            report_patch_payload(non_comparability_note="Late addendum attempt."),
            PHYSICIAN_HEADERS,
        )
        validate_error(late_patch, ApiErrorId.REPORT_NOT_DRAFT.value, 409)

        _, meta = validate_paginated(
            world.api.list_site_measurements(session_id, PHYSICIAN_HEADERS)
        )
        assert meta["total_count"] == 2


SERIAL_CLOCK = "2028-03-01T08:00:00Z"
SERIAL_DATE = "2028-03-10"
SERIAL_START = "2028-03-10T09:00:00Z"
SERIAL_END = "2028-03-10T09:30:00Z"


class TestSerialMonitoringIsBoundToTheBaselineInstrument:
    """The pin is written at order creation and enforced at booking.

    "`required_densitometer_id` pins serial work to one instrument: for an
    `indication` of `SERIAL_MONITORING` or `TREATMENT_MONITORING` it is the
    `densitometer_id` of the scan session behind the patient's `baseline_report_id`"
    """

    def test_the_same_slot_is_refused_on_one_device_and_accepted_on_the_other(
        self, world: ProgramWorld
    ):
        """Two equally certified instruments, and only one of them is the right one.

        "If the order carries a non-null `required_densitometer_id` that differs from the
        requested `densitometer_id`, the booking is refused with
        `ERR_SERIAL_DEVICE_MISMATCH`, because a serial comparison performed on a
        different instrument is not a comparison at all."

        Design: Corner/errors/serial_monitoring_order_pins_the_baseline_device_and_another_device_is_rejected
        """
        pipeline = world.build(
            stop_after="finalized",
            sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPOROTIC)],
        )
        other_device = world.create_certified_device()

        patient = world.read_patient(pipeline.patient_id)
        assert patient["next_eligible_scan_date"] == SERIAL_DATE
        assert patient["baseline_report_id"] == pipeline.report_id

        world.set_clock(SERIAL_CLOCK)
        serial_order = world.create_order(
            pipeline.patient_id,
            indication="SERIAL_MONITORING",
            requested_scan_date=SERIAL_DATE,
        )
        assert serial_order["required_densitometer_id"] == pipeline.device_id
        assert serial_order["frequency_eligibility"] == "ELIGIBLE"

        wrong_device = world.api.create_scan_appointment(
            appointment_payload(
                serial_order["id"],
                other_device["id"],
                start_utc=SERIAL_START,
                end_utc=SERIAL_END,
            ),
            SCHEDULER_HEADERS,
        )
        validate_error(wrong_device, ApiErrorId.SERIAL_DEVICE_MISMATCH.value, 409)
        assert (
            get_success_data(
                world.api.get_scan_order(serial_order["id"], SCHEDULER_HEADERS)
            )["status"]
            == "REQUESTED"
        )

        booked = validate_success(
            world.api.create_scan_appointment(
                appointment_payload(
                    serial_order["id"],
                    pipeline.device_id,
                    start_utc=SERIAL_START,
                    end_utc=SERIAL_END,
                ),
                SCHEDULER_HEADERS,
            ),
            201,
        )
        assert booked["densitometer_id"] == pipeline.device_id
        assert booked["status"] == "BOOKED"

        assert (
            get_success_data(
                world.api.get_scan_order(serial_order["id"], SCHEDULER_HEADERS)
            )["status"]
            == "SCHEDULED"
        )
        assert_counters(world.read_patient(pipeline.patient_id), 1, 1)


CAP_CLOCK = "2028-05-01T08:00:00Z"
CAP_REQUESTED_DATE = "2028-06-01"


class TestTheLifetimeCapIsAFiscalRefusalCheckedFirst:
    """A date years past the interval cannot buy a scan the payer will not fund."""

    def test_a_one_scan_policy_refuses_the_second_order_outright(
        self, world: ProgramWorld
    ):
        """The cap is read before the interval, and with appeals off nothing is stored.

        "The **lifetime cap is checked first**: if the patient's
        `lifetime_screening_scan_count` has reached the policy's
        `max_lifetime_screening_scans`, `frequency_eligibility` is
        `INELIGIBLE_LIFETIME_CAP` and `earliest_allowed_date` is copied from
        `next_eligible_scan_date`, even if the requested date is years past that point."
        "When `appeal_allowed` is false the request is rejected outright with
        `ERR_PAYER_FREQUENCY_LIMIT` for a too-soon verdict or
        `ERR_LIFETIME_SCAN_CAP_EXCEEDED` for a cap verdict, both carrying HTTP 402
        Payment Required, and no order is persisted."

        Design: Corner/errors/payer_lifetime_screening_cap_rejects_the_next_order
        """
        pipeline = world.build(
            stop_after="finalized",
            policy_overrides={
                "payer_code": "PAY-CAP1",
                "name": "Single Scan Plan",
                "vfa_covered": False,
                "max_lifetime_screening_scans": 1,
                "appeal_allowed": False,
            },
            sites=[("FEMORAL_NECK", BMD_FEMORAL_NECK_OSTEOPENIC)],
        )

        patient = world.read_patient(pipeline.patient_id)
        assert patient["lifetime_screening_scan_count"] == 1
        assert patient["next_eligible_scan_date"] == SERIAL_DATE

        world.set_clock(CAP_CLOCK)
        capped = world.api.create_scan_order(
            scan_order_payload(
                pipeline.patient_id, requested_scan_date=CAP_REQUESTED_DATE
            ),
            SCHEDULER_HEADERS,
        )
        validate_error(capped, ApiErrorId.LIFETIME_SCAN_CAP_EXCEEDED.value, 402)

        _, meta = validate_paginated(
            world.api.list_scan_orders(
                SCHEDULER_HEADERS, {"patient_id": pipeline.patient_id}
            )
        )
        assert meta["total_count"] == 1


class TestTheCoverageGateIsTheLastOneOnTheVertebralPath:
    """Clinically eligible, correctly ordered, and still not funded."""

    def test_an_uncovered_policy_refuses_the_add_on_at_402(self, world: ProgramWorld):
        """Five centimetres of height loss cannot make an excluded add-on payable.

        "(65) The patient's policy does not cover vertebral fracture assessment, on
        `POST /bone-density/scan-sessions/{id}/vfa` — `ERR_VFA_NOT_COVERED`, 402."
        "`vfa_covered` defaults to true; when it is false the payer never funds the
        vertebral fracture assessment add-on, whatever the clinical picture."

        Design: Corner/errors/vfa_on_an_eligible_patient_is_rejected_when_the_policy_excludes_it
        """
        pipeline = world.build(
            stop_after="session",
            policy_overrides={"payer_code": "PAY-NOVFA", "vfa_covered": False},
            patient_overrides={"baseline_height_cm": 168.0},
            with_profile=True,
            profile_overrides={"height_cm": 163.0},
            order_overrides={"vfa_requested": True},
        )

        refused = world.api.create_vfa(
            pipeline.session_id, vfa_payload([0, 1]), TECHNOLOGIST_HEADERS
        )
        detail = validate_error(refused, ApiErrorId.VFA_NOT_COVERED.value, 402)
        assert detail["error_id"] not in {
            ApiErrorId.VFA_NOT_ORDERED.value,
            ApiErrorId.VFA_NOT_ELIGIBLE.value,
        }

        session = world.read_session(pipeline.session_id)
        assert session["vfa_performed"] is False
        assert session["vfa_eligibility_code"] is None
        assert session["vfa_max_genant_grade"] is None
        assert session["acquisition_status"] == "IN_PROGRESS"
