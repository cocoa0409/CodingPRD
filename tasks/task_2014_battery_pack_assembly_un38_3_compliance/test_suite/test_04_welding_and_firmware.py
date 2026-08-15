"""Welding records, heat-dose computation, weld certification, and firmware governance."""
import pytest

from test_helpers import (
    ApiErrorId,
    STANDARD_WELD_HEAT_DOSE_J,
    TEST_USERS,
    assert_welding_record,
    certify_weld,
    create_battery_pack,
    create_program,
    create_welding_record_payload,
    drive_pack_to_bms_flashed,
    drive_pack_to_test_queued,
    get_battery_pack,
    get_bms_firmware,
    make_assembly_lead_headers,
    make_quality_engineer_headers,
    make_safety_officer_headers,
    record_weld,
    setup_program_with_bom,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestWeldingHeatDose:
    def test_four_input_nonlinear_heat_dose(self, api):
        """PRD §3.4: "Each welding profile carries a base dose — 12.0 joules for
        `WELD_PROFILE_A`, 18.0 for `WELD_PROFILE_B`, 25.0 for `WELD_PROFILE_C` — and a
        force factor modulates the physics: one plus the amount by which
        `electrode_force_n` deviates from the 30-newton nominal, divided by 100, clamped
        so the factor never falls below 0.7 nor rises above 1.4. The raw joules are the
        `weld_count` multiplied by the `current_amps`, multiplied by the pulse duration
        expressed in seconds (the `pulse_ms` divided by 1000), multiplied by the profile's
        base dose; the force factor is then applied to that product, and only at the end
        is the result rounded half-up to two decimal places."
        Profile B, 10 welds, 100.0 A, 20 ms, 50.0 N: raw = 10*100*0.02*18 = 360,
        force factor = 1.2, dose = 432.00 J (under the 700 J ceiling).

        Design: Difficulty/combinatorial_formula/welding_heat_dose_four_input_nonlinear_mode_a
        """
        bundle = setup_program_with_bom(welding_profile="WELD_PROFILE_B")
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        resp = api.create_welding_record(
            program_id,
            pack["id"],
            create_welding_record_payload(
                "WELD_PROFILE_B", weld_count=10, current_amps=100.0, pulse_ms=20,
                electrode_force_n=50.0,
            ),
            TEST_USERS["assembly_lead_headers"],
        )
        record = validate_success(resp, 201)
        assert_welding_record(record)
        assert record["heat_dose_j"] == pytest.approx(432.00)
        assert record["is_certified"] is False

    def test_heat_dose_propagated_to_pack(self, api):
        """PRD §3.4: "Recording a weld computes its `heat_dose_j`, the total thermal
        energy deposited, which is also propagated onto the pack as `welding_heat_dose_j`
        as the pack's assembly status moves `BUILT` → `WELD_RECORDED`."

        Design: Difficulty/combinatorial_formula/welding_heat_dose_four_input_nonlinear_mode_a
        """
        bundle = setup_program_with_bom(welding_profile="WELD_PROFILE_B")
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        record_weld(
            program_id, pack["id"], weld_profile_used="WELD_PROFILE_B",
            weld_count=10, current_amps=100.0, pulse_ms=20, electrode_force_n=50.0,
        )
        pack_after = get_battery_pack(program_id, pack["id"])
        assert pack_after["assembly_status"] == "WELD_RECORDED"
        assert pack_after["welding_heat_dose_j"] == pytest.approx(432.00)

    def test_heat_dose_rounds_half_up_to_two_decimals(self, api):
        """PRD §3.4: "the force factor is then applied to that product, and only at the
        end is the result rounded half-up to two decimal places."
        7 welds, 80.5 A, 13 ms, 30.0 N, profile A: raw = 7*80.5*0.013*12 = 87.906,
        force factor = 1.0 → 87.906 rounds HALF_UP to 87.91.

        Design: Corner/calculations/weld_heat_dose_precision_two_decimals
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        resp = api.create_welding_record(
            program_id,
            pack["id"],
            create_welding_record_payload(
                "WELD_PROFILE_A", weld_count=7, current_amps=80.5, pulse_ms=13,
                electrode_force_n=30.0,
            ),
            TEST_USERS["assembly_lead_headers"],
        )
        record = validate_success(resp, 201)
        assert record["heat_dose_j"] == pytest.approx(87.91)


class TestWeldingRecordPersistence:
    def test_get_returns_immutable_fields(self, api):
        """PRD §3.4: "The record is persisted immutably, stamped with the operator's
        identifier as `operator_id` and the pack's `battery_pack_id` and `program_id`,
        with `is_certified` initially false and `certified_by_id` null."
        PRD §2.4: "Each of these carries only `id` and `created_at`; both `updated_at` and
        `version` are absent, because the record is never modified after it is persisted."
        Standard weld 8 x 80.0 A x 15 ms, profile A, 30.0 N: 8*80*0.015*12 = 115.20 J.

        Design: Corner/endpoints/weld_record_get_returns_immutable_fields
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        created = record_weld(program_id, pack["id"], operator_id="al-weld-1")
        resp = api.get_welding_record(
            program_id, pack["id"], created["id"], TEST_USERS["any_headers"]
        )
        record = validate_success(resp, 200)
        assert_welding_record(record)
        assert record["operator_id"] == "al-weld-1"
        assert record["heat_dose_j"] == pytest.approx(STANDARD_WELD_HEAT_DOSE_J)
        assert record["is_certified"] is False
        assert record["certified_by_id"] is None
        # Repeated reads return identical values (immutable record).
        reread = validate_success(
            api.get_welding_record(program_id, pack["id"], created["id"], TEST_USERS["any_headers"]),
            200,
        )
        assert reread == record

    def test_second_weld_record_rejected_after_recording(self, api):
        """PRD §3.4: "An `AssemblyLead` records a weld on a pack that is still `BUILT` —
        any other assembly state is rejected with `ERR_PACK_NOT_BUILT`".

        Design: Corner/state_machines/battery_pack_invalid_from_state_on_weld_record
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        record_weld(program_id, pack["id"])  # pack now WELD_RECORDED
        resp = api.create_welding_record(
            program_id,
            pack["id"],
            create_welding_record_payload("WELD_PROFILE_A", weld_count=4, current_amps=50.0,
                                          pulse_ms=10),
            TEST_USERS["assembly_lead_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PACK_NOT_BUILT)


class TestWeldCertification:
    def test_same_operator_certify_blocked_by_sod(self, api):
        """PRD §2.11: "The `QualityEngineer` certifying a weld must not be the
        `AssemblyLead` who recorded it: if the certifier's `X-User-ID` equals the record's
        `operator_id`, certification is rejected with `ERR_SOD_WELD_CERTIFY`."

        Design: Corner/rbac/sod_weld_certify_same_operator_blocked
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        record = record_weld(program_id, pack["id"], operator_id="al-weld-1")
        resp = api.certify_welding_record(
            program_id, pack["id"], record["id"], make_quality_engineer_headers("al-weld-1")
        )
        validate_error(resp, ApiErrorId.ERR_SOD_WELD_CERTIFY)
        record_after = validate_success(
            api.get_welding_record(program_id, pack["id"], record["id"], TEST_USERS["any_headers"]),
            200,
        )
        assert record_after["is_certified"] is False

    def test_certify_from_bms_flashed_reports_state_error_not_sod(self, api):
        """PRD §2.12: "When several checks could reject the same request, the server
        evaluates them in a fixed global order so that the error a client receives is
        deterministic." State preconditions ("5. Resource state preconditions for the
        attempted transition") are evaluated before "6. Segregation of duties
        (`ERR_SOD_WELD_CERTIFY`, `ERR_SOD_FIRMWARE_APPROVE`, `ERR_SOD_RMA_APPROVE`)": a
        certify attempt on a pack already past WELD_RECORDED reports the state error even
        when the certifier id matches the weld operator.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_weld_certify_from_wrong_state_and_sod
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        driven = drive_pack_to_bms_flashed(program_id, bundle["bom"], weld_operator_id="al-weld-1")
        pack = driven["pack"]
        record = driven["weld_record"]
        assert pack["assembly_status"] == "BMS_FLASHED"
        resp = api.certify_welding_record(
            program_id, pack["id"], record["id"], make_quality_engineer_headers("al-weld-1")
        )
        assert resp.status_code == 409
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_PACK_NOT_WELD_RECORDED, ApiErrorId.ERR_WELD_ALREADY_CERTIFIED]
        )
        assert actual != ApiErrorId.ERR_SOD_WELD_CERTIFY.value

    def test_certify_already_certified_record_reports_state_error_not_sod(self, api):
        """PRD §3.4: "The record must not already be certified (`ERR_WELD_ALREADY_CERTIFIED`);
        segregation of duties forbids the certifier from being the operator who laid the
        weld (`ERR_SOD_WELD_CERTIFY`, §2.11)". PRD §2.12 orders "5. Resource state
        preconditions for the attempted transition" before "6. Segregation of duties", so
        re-certifying an already-certified record — even by the original operator —
        reports a state error, never the SoD error.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_weld_certify_from_wrong_state_and_sod
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        record = record_weld(program_id, pack["id"], operator_id="al-weld-1")
        certify_weld(program_id, pack["id"], record["id"], certifier_id="qe-cert-1")
        pack_after = get_battery_pack(program_id, pack["id"])
        assert pack_after["assembly_status"] == "WELD_CERTIFIED"
        resp = api.certify_welding_record(
            program_id, pack["id"], record["id"], make_quality_engineer_headers("al-weld-1")
        )
        assert resp.status_code == 409
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_PACK_NOT_WELD_RECORDED, ApiErrorId.ERR_WELD_ALREADY_CERTIFIED]
        )
        assert actual != ApiErrorId.ERR_SOD_WELD_CERTIFY.value


class TestFirmwareGovernance:
    def test_assembly_lead_cannot_approve_firmware(self, api):
        """PRD §2.1: "An authenticated operator who attempts an operation reserved for a
        different role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §3.5: "A `SafetyOfficer` then records an immutable decision with a `decision`
        of `APPROVE` or `REJECT` and a free-text `rationale` of at least 20 characters."

        Design: Corner/rbac/assembly_lead_cannot_approve_firmware
        """
        program = create_program()
        fw = validate_success(
            api.create_bms_firmware(program["id"], {"firmware_version": "1.0.0",
                                                    "binary_sha256": "d" * 64,
                                                    "supports_soc_hysteresis": False},
                                    make_assembly_lead_headers("al-fw-1")),
            201,
        )
        validate_success(
            api.submit_firmware_review(program["id"], fw["id"], make_assembly_lead_headers("al-fw-1"))
        )
        resp = api.create_firmware_approval(
            program["id"], fw["id"],
            {"decision": "APPROVE", "rationale": "Self-approve attempt by assembly lead."},
            make_assembly_lead_headers("al-fw-2"),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_deprecate_blocked_when_pack_in_test_queued(self, api):
        """PRD §3.5: "Deprecation is how an `APPROVED` firmware leaves service: a
        `SafetyOfficer` deprecates it, which requires the firmware to be `APPROVED`
        (`ERR_FIRMWARE_NOT_APPROVED`) and is refused with `ERR_FIRMWARE_IN_USE` whenever
        any pack that has not reached a terminal assembly state references the firmware
        and has progressed to `TEST_QUEUED` or beyond."

        Design: Corner/state_machines/firmware_deprecate_blocked_when_pack_in_use
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        driven = drive_pack_to_test_queued(program_id, bundle["bom"])
        firmware = driven["firmware"]
        assert driven["pack"]["assembly_status"] == "TEST_QUEUED"
        resp = api.deprecate_firmware(
            program_id, firmware["id"], make_safety_officer_headers("so-1")
        )
        validate_error(resp, ApiErrorId.ERR_FIRMWARE_IN_USE)
        assert get_bms_firmware(program_id, firmware["id"])["status"] == "APPROVED"

    def test_flash_pending_review_firmware_rejected(self, api):
        """PRD §3.5: "the firmware must exist in the same program and be `APPROVED`, with
        any other state rejected as `ERR_FIRMWARE_NOT_APPROVED`". A firmware that has been
        submitted but not yet decided sits in `PENDING_REVIEW`, so the flash is refused by
        the referential rule before any pack state change.

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_safety_firmware_unapproved_and_sod
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        record = record_weld(program_id, pack["id"])
        certify_weld(program_id, pack["id"], record["id"])
        fw = validate_success(
            api.create_bms_firmware(program_id, {"firmware_version": "9.9.9",
                                                 "binary_sha256": "e" * 64,
                                                 "supports_soc_hysteresis": False},
                                    make_assembly_lead_headers("al-fw-1")),
            201,
        )
        validate_success(
            api.submit_firmware_review(program_id, fw["id"], make_assembly_lead_headers("al-fw-1"))
        )
        resp = api.create_bms_flash_record(
            program_id, pack["id"], {"bms_firmware_id": fw["id"]},
            make_assembly_lead_headers("al-flash-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FIRMWARE_NOT_APPROVED)

    def test_flash_draft_firmware_rejected_and_pack_unchanged(self, api):
        """PRD §3.5: "the firmware must exist in the same program and be `APPROVED`, with
        any other state rejected as `ERR_FIRMWARE_NOT_APPROVED`". A firmware still in its
        born `DRAFT` state is equally not approved; the pack must remain `WELD_CERTIFIED`.

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_safety_firmware_unapproved_and_sod
        """
        bundle = setup_program_with_bom()
        program_id = bundle["program"]["id"]
        pack = create_battery_pack(program_id, bundle["bom"]["id"])
        record = record_weld(program_id, pack["id"])
        certify_weld(program_id, pack["id"], record["id"])
        fw = validate_success(
            api.create_bms_firmware(program_id, {"firmware_version": "0.1.0",
                                                 "binary_sha256": "f" * 64,
                                                 "supports_soc_hysteresis": False},
                                    make_assembly_lead_headers("al-fw-1")),
            201,
        )
        assert fw["status"] == "DRAFT"
        resp = api.create_bms_flash_record(
            program_id, pack["id"], {"bms_firmware_id": fw["id"]},
            make_assembly_lead_headers("al-flash-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FIRMWARE_NOT_APPROVED)
        assert get_battery_pack(program_id, pack["id"])["assembly_status"] == "WELD_CERTIFIED"
