"""Patient registration, type-and-screen lifecycle, and typing side effects."""
from test_helpers import (
    ApiErrorId,
    assert_patient,
    assert_same_instant,
    assert_three_fractional_digits,
    collect_ts,
    get_patient,
    get_success_data,
    get_ts,
    is_valid_uuid,
    make_stock,
    make_typed_patient,
    make_verified_order,
    receive_unit_descriptor,
    result_ts,
    run_sweep,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    validate_ts,
    TECH_A,
    TECH_B,
    COORDINATOR,
    api_client,
)
from test_helpers import create_patient_payload, create_type_and_screen_payload


class TestPatientCreation:
    def test_patient_creation_defaults_and_system_fields(self, api):
        """PRD §3.1: "Typing fields are entirely computed: a fresh patient has
        `current_abo_type` and `current_rh_type` of `UNKNOWN`, `antibody_status` of
        `UNKNOWN`, an empty `identified_antibodies`, `abo_confirmed` false,
        `has_active_type_and_screen` false, `active_mtp` false, and
        `total_units_transfused` of zero."
        PRD §2.5: "**`id` (string):** a unique, server-minted identifier formatted
        as a UUID, with no type prefix."

        Design: Corner/entities/patient_creation_defaults_and_system_fields
        """
        created = validate_success(
            api.create_patient(create_patient_payload(
                mrn="M-1001", full_name="Alex Doe", date_of_birth="1980-01-01"),
                TECH_A), 201)
        assert_patient(created)

        fetched = validate_success(api.get_patient(created["id"], COORDINATOR))
        assert fetched["special_requirements"] == [], "default is an empty array"
        assert fetched["current_abo_type"] == "UNKNOWN"
        assert fetched["current_rh_type"] == "UNKNOWN"
        assert fetched["antibody_status"] == "UNKNOWN"
        assert fetched["identified_antibodies"] == []
        assert fetched["abo_confirmed"] is False
        assert fetched["has_active_type_and_screen"] is False
        assert fetched["active_mtp"] is False
        assert fetched["total_units_transfused"] == 0
        assert is_valid_uuid(fetched["id"]), "id is a bare UUID with no type prefix"
        assert_three_fractional_digits(fetched["created_at"], "created_at")
        assert_three_fractional_digits(fetched["updated_at"], "updated_at")
        assert isinstance(fetched["version"], int), "version is an integer"

    def test_patient_missing_mrn_returns_invalid_request(self, api):
        """PRD §2.9: "Fourth, request-schema conformance — required fields present,
        types correct, enum values within their declared sets, integer ranges
        respected — under `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `BloodBankTechnologist` or `BloodBankSupervisor` registers a
        **Patient** blood-bank record with a medical record number `mrn` (unique
        across all patients), the patient's `full_name`, and `date_of_birth` in
        YYYY-MM-DD form"

        Design: Corner/entities/patient_missing_mrn_returns_invalid_request
        """
        resp = api.create_patient(
            {"full_name": "No Mrn", "date_of_birth": "1990-01-01"}, TECH_A)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestImmediateConsistency:
    def test_immediate_consistency_create_then_get(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.1: "an optional `special_requirements` array defaults to empty and
        may list any subset of `IRRADIATED`, `CMV_NEGATIVE`, and `WASHED`."

        Design: Corner/consistency_model/immediate_consistency_create_then_get
        """
        created = validate_success(api.create_patient(
            create_patient_payload(mrn="M-7001", full_name="Gus Doe",
                                   date_of_birth="1965-05-05",
                                   special_requirements=["IRRADIATED"]),
            TECH_A), 201)
        assert created["current_abo_type"] == "UNKNOWN", (
            "the create response already carries computed typing fields"
        )
        assert created["special_requirements"] == ["IRRADIATED"]

        fetched = validate_success(api.get_patient(created["id"], COORDINATOR))
        assert fetched["version"] == created["version"], (
            "an immediate re-read shows the same version — no lag"
        )
        assert fetched["current_abo_type"] == created["current_abo_type"]
        assert fetched["updated_at"] == fetched["created_at"], (
            "a resource with no mutations yet has updated_at == created_at"
        )


class TestTypeAndScreenLifecycle:
    def test_ts_expires_at_computed_72h(self, api):
        """PRD §3.1: "Collection lands the record in `COLLECTED` status, computes
        its `expires_at` as exactly seventy-two hours (three days) after
        `specimen_collected_at`, and — because a pending specimen changes the
        clinical picture — increments the patient's `version` by one."

        Design: Corner/entities/ts_expires_at_computed_72h
        """
        set_clock("2026-08-10T09:00:00Z")
        patient = get_success_data(api.create_patient(
            create_patient_payload(mrn="M-1002", full_name="Bea Doe",
                                   date_of_birth="1985-05-05"), TECH_A))
        ts = validate_success(api.create_type_and_screen(
            create_type_and_screen_payload(patient["id"], "2026-08-10T08:00:00Z",
                                           patient["version"]),
            TECH_A), 201)
        assert ts["status"] == "COLLECTED", "a fresh specimen opens COLLECTED"
        assert_same_instant(ts["expires_at"], "2026-08-13T08:00:00Z",
                            "expires_at must be specimen_collected_at + 72h")
        assert_three_fractional_digits(ts["created_at"], "created_at")

    def test_occ_ts_create_stale_patient_version(self, api):
        """PRD §2.8: "Creating a type-and-screen specimen requires the request to
        carry `expected_patient_version`, the `version` of the target patient as
        last observed by the caller; if the patient's current `version` has
        advanced past that value — for instance because another technologist has
        just collected or validated a specimen for the same patient, each of which
        moves the patient's summary and version — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the caller from typing against
        a patient record it has not observed."

        Design: Corner/cross_cutting_layers/occ_ts_create_stale_patient_version
        """
        set_clock("2026-08-10T09:00:00Z")
        patient = get_success_data(api.create_patient(
            create_patient_payload(mrn="M-6001", full_name="Zach Doe",
                                   date_of_birth="1988-08-08"), TECH_A))
        stale_version = patient["version"]
        collect_ts(patient, "2026-08-10T08:00:00Z")  # advances the version

        resp = api.create_type_and_screen(
            create_type_and_screen_payload(patient["id"], "2026-08-10T08:30:00Z",
                                           stale_version),
            TECH_A)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        data, meta = validate_paginated(
            api.list_type_and_screens(TECH_A, params={"patient_id": patient["id"]}))
        assert meta["total_count"] == 1, "the stale create added no specimen"

    def test_crossmatch_method_electronic_when_abo_confirmed(self, api):
        """PRD §3.1: "if another type-and-screen of the same patient exists in
        `ACTIVE`, `SUPERSEDED`, or `EXPIRED` status with the same `abo_result` but
        a different `specimen_collected_at`, the patient's `abo_confirmed` flips to
        true — and once latched it never auto-clears, even if both specimens later
        expire."
        PRD §3.4: "computes its `method` — `ELECTRONIC` exactly when the patient's
        `abo_confirmed` is latched and their `antibody_status` is `NEGATIVE`, and
        `SEROLOGIC_AHG` otherwise."
        PRD §3.1: "Validation is the moment the patient's typing is recomputed: any
        other `ACTIVE` specimen of the same patient is superseded to `SUPERSEDED`"

        Design: Corner/entities/crossmatch_method_electronic_when_abo_confirmed
        """
        stock = make_stock([receive_unit_descriptor("U-100")])
        unit = stock["units"]["U-100"]
        patient = get_success_data(api.create_patient(
            create_patient_payload(mrn="M-1004", full_name="Dana Doe",
                                   date_of_birth="1976-06-06"), TECH_A))
        ts1 = collect_ts(patient, "2026-08-09T08:00:00Z")
        result_ts(ts1["id"], abo_result="A", rh_result="POS")
        validate_ts(ts1["id"])
        ts2 = collect_ts(get_patient(patient["id"]), "2026-08-10T08:00:00Z")
        result_ts(ts2["id"], abo_result="A", rh_result="POS")
        validate_ts(ts2["id"])

        patient = get_patient(patient["id"])
        assert patient["abo_confirmed"] is True, (
            "two distinct specimens with the same ABO result latch abo_confirmed"
        )
        assert get_ts(ts1["id"])["status"] == "SUPERSEDED", (
            "the first specimen is superseded when the second validates"
        )

        order = make_verified_order(patient["id"], product_type="RBC",
                                    units_requested=1)
        xm = get_success_data(api_client.create_crossmatch(
            {"order_id": order["id"], "unit_id": unit["id"]}, TECH_A))
        assert xm["method"] == "ELECTRONIC", (
            "abo_confirmed plus NEGATIVE screen switches the method to ELECTRONIC"
        )

    def test_derived_field_patient_summary_on_expiry(self, api):
        """PRD §3.1: "The patient's `current_abo_type`, `current_rh_type`, and
        `antibody_status` are retained as historical facts after expiry — they
        describe what was last validated, not what is currently valid."
        PRD §3.1: "When that expiry strips a patient of their last `ACTIVE`
        specimen, `has_active_type_and_screen` falls to false and the
        **T&S-expiry cascade** fires across the patient's open work"

        Design: Corner/cross_cutting_layers/derived_field_patient_summary_on_expiry
        """
        set_clock("2026-08-10T09:00:00Z")
        patient, _ts = make_typed_patient(mrn="M-6007", full_name="Finn Doe",
                                          date_of_birth="1971-07-07", abo="B",
                                          rh="NEG")
        assert patient["has_active_type_and_screen"] is True

        set_clock("2026-08-14T09:00:00Z")
        sweep = run_sweep()
        assert sweep["ts_expired_count"] == 1, "the single specimen expired"

        patient = get_patient(patient["id"])
        assert patient["has_active_type_and_screen"] is False
        assert patient["current_abo_type"] == "B", (
            "historical typing is retained after expiry"
        )
        assert patient["current_rh_type"] == "NEG"
