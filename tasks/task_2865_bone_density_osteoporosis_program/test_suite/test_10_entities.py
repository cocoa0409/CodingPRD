"""Resource shape: what a row stores, what it refuses, and what it derives.

These cases stay close to the data model — echoed inputs, defaulted optionals,
server-owned fields, foreign keys and the append-only rows — rather than the
workflows built on top of it.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    MISSING_PATIENT_ID,
    MISSING_POLICY_ID,
    MISSING_PROFILE_ID,
    MISSING_SESSION_ID,
    PHYSICIAN_HEADERS,
    ProgramWorld,
    SCHEDULER_HEADERS,
    TECHNOLOGIST_HEADERS,
    assert_append_only_resource,
    assert_contains_ids,
    assert_echoes,
    assert_excludes_ids,
    assert_fresh_densitometer,
    assert_fresh_patient,
    assert_instant_equals,
    assert_score_one_decimal,
    assert_three_decimals,
    assert_versioned_resource,
    densitometer_payload,
    frax_payload,
    minimal_patient_payload,
    patient_payload,
    payer_policy_payload,
    qc_run_payload,
    risk_profile_payload,
    scan_order_payload,
    site_measurement_payload,
    unique_mrn,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_CLOCK = "2026-03-02T08:00:00Z"


class TestPayerPolicyCreation:
    """A policy is a flat immutable row, so creation is pure echo."""

    def test_every_declared_input_comes_back_unchanged(self, world: ProgramWorld):
        """Ten inputs including a one-decimal number and two booleans.

        "Policies are immutable once registered: there is no update operation, and
        a policy row exposes only its `id` and `created_at`, with no `updated_at`
        and no `version`." "`vfa_requires_height_loss_cm` defaults to 4.0
        centimetres, must lie between 0.0 and 20.0 inclusive with at most one
        decimal place".

        Design: Corner/entities/payer_policy_creation_echoes_every_input_field
        """
        world.set_clock(SETUP_CLOCK)
        payload = payer_policy_payload(payer_code="PAY-STD")

        policy = validate_success(
            world.api.create_payer_policy(payload, ADMIN_HEADERS), 201
        )

        assert_echoes(policy, payload)
        assert_append_only_resource(policy)
        assert_instant_equals(policy["created_at"], SETUP_CLOCK, "created_at")


class TestDensitometerRetrieval:
    """A GET by id has to return the row registration wrote, nothing more."""

    def test_a_fresh_device_reads_back_active_and_uncertified(
        self, world: ProgramWorld
    ):
        """Everything precision-related is still null on a device nobody has studied.

        "A newly registered device is `ACTIVE`, at `calibration_generation` 1, with
        `cross_cal_factor` 1.0 and `consecutive_qc_pass_count` 0. Everything
        precision-related is still empty: `rms_sd_g_cm2`,
        `precision_degrees_of_freedom`, `lsc_g_cm2`,
        `precision_technologist_user_id` and `precision_certified_at` are all null,
        as are `last_qc_result`, `last_qc_run_at`, `qc_hold_started_at` and
        `qc_hold_reason_code`."

        Design: Corner/entities/densitometer_retrieval_returns_the_stored_row
        """
        world.set_clock(SETUP_CLOCK)
        payload = densitometer_payload(serial_number="HLG-0001")
        created = validate_success(
            world.api.create_densitometer(payload, ADMIN_HEADERS), 201
        )

        stored = validate_success(
            world.api.get_densitometer(created["id"], TECHNOLOGIST_HEADERS), 200
        )

        assert stored["id"] == created["id"]
        assert stored["serial_number"] == "HLG-0001"
        assert_fresh_densitometer(stored)
        assert_versioned_resource(stored, 1)
        assert_instant_equals(stored["created_at"], SETUP_CLOCK, "created_at")


class TestDensitometerListing:
    """The count in `meta` describes the filtered set, never the page."""

    def test_pagination_reports_the_filtered_total_and_the_remainder_flag(
        self, world: ProgramWorld
    ):
        """Two pages over three rows, then a domain filter that narrows to two.

        "Both values are echoed back in `meta` alongside `total_count`, the number
        of rows the filter matched before pagination was applied, and `has_more`,
        which is true exactly when rows remain beyond the current page." "The
        device inventory filters on `status` and `site_code`."

        Design: Corner/entities/densitometer_listing_paginates_with_total_count_and_has_more
        """
        world.set_clock(SETUP_CLOCK)
        first = world.create_device(serial_number="HLG-0001", site_code="MAIN")
        second = world.create_device(
            serial_number="GEL-0002",
            manufacturer="GE_LUNAR",
            model="iDXA",
            site_code="WEST",
            appointment_buffer_minutes=10,
            daily_scan_capacity=8,
        )
        third = world.create_device(serial_number="HLG-0003", site_code="MAIN")

        page_one, meta_one = validate_paginated(
            world.api.list_densitometers(ADMIN_HEADERS, {"limit": 2, "offset": 0})
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0
        assert meta_one["has_more"] is True

        page_two, meta_two = validate_paginated(
            world.api.list_densitometers(ADMIN_HEADERS, {"limit": 2, "offset": 2})
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["offset"] == 2
        assert meta_two["has_more"] is False

        main_site, meta_main = validate_paginated(
            world.api.list_densitometers(ADMIN_HEADERS, {"site_code": "MAIN"})
        )
        assert meta_main["total_count"] == 2
        assert_contains_ids(main_site, [first["id"], third["id"]])
        assert_excludes_ids(main_site, [second["id"]])


class TestPatientRetrievalOfAnUnknownId:
    """A well-formed but unused identifier is a not-found, not a validation fault."""

    def test_an_unused_patient_id_is_a_typed_not_found(self, world: ProgramWorld):
        """404 with the patient-specific code in the error envelope.

        "(7) No patient with that id, on every endpoint whose path contains a
        patient id — `ERR_PATIENT_NOT_FOUND`, 404." "The `error_id` is a unique,
        machine-readable string that identifies the specific error."

        Design: Corner/entities/patient_get_with_unknown_id_returns_not_found
        """
        world.set_clock(SETUP_CLOCK)

        response = world.api.get_patient(MISSING_PATIENT_ID, SCHEDULER_HEADERS)

        validate_error(response, ApiErrorId.PATIENT_NOT_FOUND.value, 404)
        assert response.json()["response_type"] == "error"


class TestPatientCreationRequiredFields:
    """The mandatory five are mandatory; the optional flag is not."""

    def test_omitting_the_medical_record_number_is_rejected_and_stores_nothing(
        self, world: ProgramWorld
    ):
        """The same body with the identifier restored is accepted.

        "(3) On any write endpoint: a required body field absent, a field of the
        wrong JSON type, an enum value outside its declared set, a numeric value
        outside its declared range, or a date or instant string that is not valid
        ISO-8601 — `ERR_INVALID_REQUEST`, 422." "The patient roster filters on
        `primary_payer_policy_id`, `baseline_report_id`, `last_finalized_report_id`
        and `mrn`."

        Design: Corner/entities/patient_create_missing_required_field_rejected
        """
        world.set_clock(SETUP_CLOCK)
        policy = world.create_policy()

        mrn = unique_mrn()
        without_mrn = minimal_patient_payload(policy["id"], mrn=mrn)
        without_mrn.pop("mrn")

        rejected = world.api.create_patient(without_mrn, SCHEDULER_HEADERS)
        validate_error(rejected, ApiErrorId.INVALID_REQUEST.value, 422)

        accepted = validate_success(
            world.api.create_patient(
                minimal_patient_payload(policy["id"], mrn=mrn), SCHEDULER_HEADERS
            ),
            201,
        )
        assert accepted["mrn"] == mrn

        _, meta = validate_paginated(
            world.api.list_patients(SCHEDULER_HEADERS, {"mrn": mrn})
        )
        assert meta["total_count"] == 1


class TestOptionalFlagsDefaultToFalse:
    """Every omitted boolean has to read false, and the numeric default zero."""

    def test_omitted_optionals_default_across_patient_profile_and_order(
        self, world: ProgramWorld
    ):
        """A profile sending only height and weight still counts zero risk factors.

        "an optional `postmenopausal` flag defaulting to false" "`rheumatoid_arthritis`,
        `secondary_osteoporosis` for a disorder strongly associated with bone loss
        — all six booleans defaulting to false — and `alcohol_units_per_day`, a
        number defaulting to zero" "`clinical_risk_factor_count` is the number of
        the six booleans that are true, plus one more when `alcohol_units_per_day`
        is at least 3.0."

        Design: Corner/entities/optional_flags_default_to_false_when_omitted
        """
        world.set_clock(SETUP_CLOCK)
        policy = world.create_policy()
        patient = validate_success(
            world.api.create_patient(
                minimal_patient_payload(policy["id"]), SCHEDULER_HEADERS
            ),
            201,
        )
        assert patient["postmenopausal"] is False
        assert_fresh_patient(patient)

        profile = validate_success(
            world.api.create_risk_factor_profile(
                patient["id"],
                risk_profile_payload(patient["version"], weight_kg=60.0),
                SCHEDULER_HEADERS,
            ),
            201,
        )
        for flag in (
            "prior_fragility_fracture",
            "parental_hip_fracture",
            "current_smoker",
            "glucocorticoid_use",
            "rheumatoid_arthritis",
            "secondary_osteoporosis",
        ):
            assert profile[flag] is False, f"{flag} should default to false"
        assert profile["alcohol_units_per_day"] == 0.0
        assert profile["clinical_risk_factor_count"] == 0
        assert profile["status"] == "ACTIVE"

        order_payload = scan_order_payload(patient["id"])
        order_payload.pop("vfa_requested")
        order = validate_success(
            world.api.create_scan_order(order_payload, SCHEDULER_HEADERS), 201
        )
        assert order["vfa_requested"] is False
        assert order["status"] == "REQUESTED"
        assert order["frequency_eligibility"] == "ELIGIBLE"
        assert order["earliest_allowed_date"] is None
        assert order["required_densitometer_id"] is None


class TestComputedScoresIgnoreClientSuppliedValues:
    """T-score and Z-score are derived, so a client cannot dictate them."""

    def test_the_stored_scores_come_from_the_reference_figures(
        self, world: ProgramWorld
    ):
        """A body claiming 9.9 for both scores still stores the derived pair.

        "Each accepted row computes `t_score` as the measured density minus
        `reference_mean_bmd_g_cm2` divided by `reference_sd_g_cm2`, rounded half up
        to **one** decimal place, and `z_score` the same way against
        `age_matched_mean_bmd_g_cm2` and `age_matched_sd_g_cm2`." "
        `valid_vertebral_count` is the length of that array for a lumbar row and
        zero for every other site."

        Design: Corner/entities/site_measurement_computed_t_score_ignores_extra_field
        """
        pipeline = world.build(
            stop_after="session", order_overrides={"requested_sites": ["LUMBAR_SPINE"]}
        )

        measurement = validate_success(
            world.api.create_site_measurement(
                pipeline.session_id,
                site_measurement_payload(
                    "LUMBAR_SPINE", 0.9000, ["L1", "L2", "L3", "L4"], t_score=9.9, z_score=9.9
                ),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )

        assert_score_one_decimal(measurement["t_score"], -1.7, "t_score")
        assert_score_one_decimal(measurement["z_score"], -0.4, "z_score")
        assert measurement["valid_vertebral_count"] == 4
        assert measurement["site_usable_for_diagnosis"] is True
        assert measurement["superseded"] is False
        assert_append_only_resource(measurement)

        session = world.read_session(pipeline.session_id)
        assert session["measured_site_count"] == 1


class TestSystemOwnedFieldsAreNotAcceptedFromTheClient:
    """Identity, creation stamp and version are minted by the server."""

    def test_a_client_supplied_id_created_at_and_version_are_all_ignored(
        self, world: ProgramWorld
    ):
        """The row comes back with a server id, the clock's stamp and version one.

        "Every resource carries an `id` that is a server-minted UUID with no type
        prefix, generated by the server and never accepted from a client." "Every
        resource also carries `created_at`, an ISO 8601 UTC timestamp with exactly
        three fractional digits, stamped from the logical clock at the moment of
        creation" "`version`, an integer that begins at 1 on creation".

        Design: Corner/entities/patient_system_fields_ignore_extra_field_input
        """
        world.set_clock(SETUP_CLOCK)
        policy = world.create_policy()

        patient = validate_success(
            world.api.create_patient(
                patient_payload(
                    policy["id"],
                    id=MISSING_PATIENT_ID,
                    created_at="2001-01-01T00:00:00Z",
                    version=77,
                ),
                SCHEDULER_HEADERS,
            ),
            201,
        )

        assert patient["id"] != MISSING_PATIENT_ID
        assert_versioned_resource(patient, 1)
        assert_instant_equals(patient["created_at"], SETUP_CLOCK, "created_at")
        assert_fresh_patient(patient)


class TestEnumAndRangeValidation:
    """Enums accept only their members and numbers only their declared range."""

    def test_three_malformed_bodies_are_each_refused_and_nothing_is_stored(
        self, world: ProgramWorld
    ):
        """An unknown indication, a negative capacity and a string for a decimal.

        "(3) On any write endpoint: a required body field absent, a field of the
        wrong JSON type, an enum value outside its declared set, a numeric value
        outside its declared range, or a date or instant string that is not valid
        ISO-8601 — `ERR_INVALID_REQUEST`, 422." "`daily_scan_capacity`, defaulting
        to twelve and accepted from 1 through 60".

        Design: Corner/entities/write_endpoint_rejects_unknown_enum_and_negative_number
        """
        world.set_clock(SETUP_CLOCK)
        policy = world.create_policy()
        patient = world.create_patient(policy["id"])

        bad_enum = world.api.create_scan_order(
            scan_order_payload(patient["id"], indication="SCREENING_X"),
            SCHEDULER_HEADERS,
        )
        validate_error(bad_enum, ApiErrorId.INVALID_REQUEST.value, 422)

        bad_range = world.api.create_densitometer(
            densitometer_payload(serial_number="HLG-0009", daily_scan_capacity=-1),
            ADMIN_HEADERS,
        )
        validate_error(bad_range, ApiErrorId.INVALID_REQUEST.value, 422)

        bad_type = world.api.create_densitometer(
            densitometer_payload(
                serial_number="HLG-0010", phantom_baseline_bmd_g_cm2="one point zero"
            ),
            ADMIN_HEADERS,
        )
        validate_error(bad_type, ApiErrorId.INVALID_REQUEST.value, 422)

        _, order_meta = validate_paginated(
            world.api.list_scan_orders(SCHEDULER_HEADERS, {"patient_id": patient["id"]})
        )
        assert order_meta["total_count"] == 0

        _, device_meta = validate_paginated(world.api.list_densitometers(ADMIN_HEADERS))
        assert device_meta["total_count"] == 0


class TestAppendOnlyRowsCarryNoMutationPair:
    """A phantom run is a historical fact, so it has no version and no update stamp."""

    def test_a_recorded_phantom_run_exposes_only_identity_and_creation(
        self, world: ProgramWorld
    ):
        """The row is readable, scored, and carries neither `version` nor `updated_at`.

        "`PayerPolicy`, `QcRun`, `SiteMeasurement` and `AdherenceRefill` carry only
        `id` and `created_at`. For those four, `updated_at` and `version` are absent
        from the response entirely — not null, not zero, absent." "a phantom run, a
        site measurement and a refill row are historical facts."

        Design: Corner/entities/qc_run_and_site_measurement_are_immutable_rows
        """
        world.set_clock("2026-03-05T08:00:00Z")
        device = world.create_device(serial_number="HLG-0001")

        created = validate_success(
            world.api.create_qc_run(
                device["id"],
                qc_run_payload(phantom_bmd_g_cm2=1.0100),
                TECHNOLOGIST_HEADERS,
            ),
            201,
        )

        stored = validate_success(
            world.api.get_qc_run(created["id"], ADMIN_HEADERS), 200
        )

        assert_append_only_resource(stored)
        assert_instant_equals(stored["created_at"], "2026-03-05T08:00:00Z", "created_at")
        assert_instant_equals(
            stored["performed_at_utc"], "2026-03-05T08:00:00Z", "performed_at_utc"
        )
        assert stored["performed_by_user_id"] == "tech-001"
        assert_three_decimals(stored["deviation_sd_units"], 1.000, "deviation_sd_units")
        assert stored["result"] == "PASS"


class TestSubResourceParentResolution:
    """A sub-resource cannot exist without the parent named in its path."""

    def test_a_measurement_under_an_unknown_session_is_a_session_not_found(
        self, world: ProgramWorld
    ):
        """The path identifier resolves before the body is looked at.

        "Path identifiers are always resolved before the request body is
        inspected." "(10) No session with that id, on every endpoint whose path
        contains a scan session id — `ERR_SCAN_SESSION_NOT_FOUND`, 404."

        Design: Corner/entities/site_measurement_parent_session_not_found
        """
        world.set_clock("2026-03-10T09:05:00Z")

        response = world.api.create_site_measurement(
            MISSING_SESSION_ID,
            site_measurement_payload("FEMORAL_NECK"),
            TECHNOLOGIST_HEADERS,
        )

        validate_error(response, ApiErrorId.SCAN_SESSION_NOT_FOUND.value, 404)


class TestBodyForeignKeyResolution:
    """A dangling body reference gets the referenced type's own not-found code."""

    def test_an_unknown_payer_policy_on_patient_creation_is_a_policy_not_found(
        self, world: ProgramWorld
    ):
        """404 naming the policy, not a 422 about the body being malformed.

        "(14) `primary_payer_policy_id` not referencing an existing policy, on
        `POST /bone-density/patients` — `ERR_PAYER_POLICY_NOT_FOUND`, 404."

        Design: Corner/entities/patient_create_with_unknown_payer_policy_not_found
        """
        world.set_clock(SETUP_CLOCK)
        mrn = unique_mrn()

        response = world.api.create_patient(
            patient_payload(MISSING_POLICY_ID, mrn=mrn), SCHEDULER_HEADERS
        )

        validate_error(response, ApiErrorId.PAYER_POLICY_NOT_FOUND.value, 404)

        _, meta = validate_paginated(
            world.api.list_patients(SCHEDULER_HEADERS, {"mrn": mrn})
        )
        assert meta["total_count"] == 0


class TestFraxAssessmentReferenceIntegrity:
    """Two independent references, each resolved on its own terms."""

    def test_each_dangling_reference_names_its_own_entity(self, world: ProgramWorld):
        """An unknown profile and an unknown patient give two different codes.

        "(15) `risk_factor_profile_id` not referencing an existing profile, on
        `POST /bone-density/frax-assessments` — `ERR_RISK_FACTOR_PROFILE_NOT_FOUND`,
        404." "After every path parameter has resolved, body foreign keys are
        resolved in the order the endpoint declares its input fields, and a miss
        returns the same per-entity not-found code declared at priorities 4 through
        15."

        Design: Corner/entities/frax_assessment_cross_reference_integrity_not_found
        """
        pipeline = world.foundation(
            with_profile=True, profile_overrides={"height_cm": 160.0, "weight_kg": 52.0}
        )

        unknown_profile = world.api.create_frax_assessment(
            frax_payload(pipeline.patient_id, MISSING_PROFILE_ID), PHYSICIAN_HEADERS
        )
        validate_error(
            unknown_profile, ApiErrorId.RISK_FACTOR_PROFILE_NOT_FOUND.value, 404
        )

        unknown_patient = world.api.create_frax_assessment(
            frax_payload(MISSING_PATIENT_ID, pipeline.profile_id), PHYSICIAN_HEADERS
        )
        validate_error(unknown_patient, ApiErrorId.PATIENT_NOT_FOUND.value, 404)

        _, meta = validate_paginated(
            world.api.list_frax_assessments(
                PHYSICIAN_HEADERS, {"patient_id": pipeline.patient_id}
            )
        )
        assert meta["total_count"] == 0
