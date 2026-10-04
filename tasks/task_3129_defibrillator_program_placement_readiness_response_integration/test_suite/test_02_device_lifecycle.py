"""Device lifecycle: state machine, OCC, prescription gating, cabinet
cascades, and posture derivation on install.

Design: Difficulty/cross_entity_state_dependency/*,
        Corner/state_machines/*, Corner/validations/stale_device_version_returns_412,
        Corner/validations/prescription_required_blocks_install,
        Corner/cross_cutting_complexity_layers/occ_device_version_increments_on_each_mutation,
        Corner/cross_cutting_complexity_layers/derived_field_readiness_posture_recomputed_on_install,
        Corner/consistency_model/immediate_consistency_device_readiness_visible_same_request,
        Corner/entities/device_get_returns_stored_fields_and_computed_posture (initial posture).
"""

from test_helpers import (
    ApiErrorId,
    create_cabinet,
    create_campus,
    create_device,
    create_device_model,
    create_lot,
    create_responder,
    create_zone,
    get_device,
    get_success_data,
    install_device_into_cabinet,
    make_inspector_headers,
    schedule_and_pass_inspection,
    set_clock,
    setup_campus_zone_cabinet_device,
    setup_installed_device_with_consumables,
    validate_error,
    validate_success,
    TEST_USERS,
    create_inspection_payload,
    create_inspection_submit_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["program_manager_headers"]


class TestDeviceInitialStateAndInvalidTransitions:

    def test_device_initial_state_registered(self, api):
        """PRD: "A freshly registered device starts with lifecycle `status` equal
        to `REGISTERED`".

        Design: Corner/state_machines/device_initial_state_registered
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        res = api.create_device(
            {"campus_id": campus["id"], "device_model_id": model["id"],
             "serial_number": "SN-IS-1"},
            PM,
        )
        device = validate_success(res, expected_status=201)
        assert device["status"] == "REGISTERED"

    def test_commission_on_registered_device_rejected(self, api):
        """PRD: "Commissioning advances the device from `INSTALLED` to
        `IN_SERVICE`" — a REGISTERED device has no INSTALLED state to advance
        from, so the operation violates the lifecycle state rule:
        "`ERR_INVALID_STATE` | 409".

        Design: Corner/state_machines/device_invalid_transition_registered_to_in_service_skips_installed
        """
        _, _, _, device, _ = setup_campus_zone_cabinet_device(
            serial_number="SN-IV-1"
        )
        res = api.commission_device(device["id"], PM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_device(device["id"])["status"] == "REGISTERED"

    def test_decommissioned_device_rejects_install(self, api):
        """PRD: "The device's terminal `status` is `DECOMMISSIONED`" — terminal
        states permit no further transitions, so installing a decommissioned
        device violates the lifecycle state rule: "`ERR_INVALID_STATE` | 409".
        PRD: "A device still in `REGISTERED` — never installed — may be
        decommissioned directly with no preconditions."

        Design: Corner/state_machines/terminal_state_decommissioned_device_rejects_all_transitions
        """
        campus, zone, cabinet, device, _ = setup_campus_zone_cabinet_device(
            serial_number="SN-TL-1"
        )
        get_success_data(api.decommission_device(device["id"], PM))
        current = get_device(device["id"])
        assert current["status"] == "DECOMMISSIONED"
        res = api.install_device(
            device["id"],
            {"cabinet_id": cabinet["id"],
             "expected_device_version": current["version"]},
            PM,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestDeviceInstallCascade:

    def test_install_cascades_down_to_cabinet(self, api):
        """PRD: "On success the device's `status` moves from `REGISTERED` to
        `INSTALLED`, its `cabinet_id` is set, its `version` increments, the
        cabinet's `status` becomes `OCCUPIED` with `installed_device_id`
        pointing at the device, and the device's `readiness_posture` is
        recomputed."

        Design: Corner/state_machines/device_install_cascade_down_to_cabinet
        """
        campus, zone, cabinet, device, _ = setup_campus_zone_cabinet_device(
            serial_number="SN-CD-1"
        )
        updated = install_device_into_cabinet(
            device["id"], cabinet["id"], device["version"]
        )
        assert updated["status"] == "INSTALLED"
        assert updated["cabinet_id"] == cabinet["id"]

        cab = get_success_data(api.get_cabinet(cabinet["id"], PM))
        assert cab["status"] == "OCCUPIED"
        assert cab["installed_device_id"] == device["id"]


class TestDeviceOcc:

    def test_install_with_stale_device_version_rejected(self, api):
        """PRD: "If the supplied value does not equal the device's current
        `version` at the moment the write is evaluated — because another writer
        has advanced the version since the client last read the device — the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/validations/stale_device_version_returns_412
        """
        campus, zone, cabinet_a, device, _ = setup_campus_zone_cabinet_device(
            serial_number="SN-OCC-1"
        )
        cabinet_b = create_cabinet(zone["id"], location_label="L2",
                                   centroid_x_m=5.0, centroid_y_m=5.0)
        stale_version = device["version"]
        install_device_into_cabinet(device["id"], cabinet_a["id"], stale_version)

        res = api.install_device(
            device["id"],
            {"cabinet_id": cabinet_b["id"],
             "expected_device_version": stale_version},
            PM,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_device_version_starts_at_one_on_creation(self, api):
        """PRD: "The `version` field is an integer that starts at its initial
        value at creation and increments by one on every mutation of the
        resource, including mutations driven by cascades and recomputed fields
        rather than direct client writes."

        Design: Corner/cross_cutting_complexity_layers/occ_device_version_increments_on_each_mutation
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-OCV-1")
        assert device["version"] == 1
        fetched = get_device(device["id"])
        assert fetched["version"] == 1


class TestPrescriptionGating:

    def test_prescription_required_model_blocks_install_without_prescription(self, api):
        """PRD: "when the device model's `prescription_required` is true the
        device must carry a valid `prescription_number`, else the operation is
        rejected with `ERR_PRESCRIPTION_REQUIRED`."

        Design: Corner/validations/prescription_required_blocks_install
        """
        _, _, cabinet, device, _ = setup_campus_zone_cabinet_device(
            prescription_required=True, serial_number="SN-RX-1"
        )
        res = api.install_device(
            device["id"],
            {"cabinet_id": cabinet["id"],
             "expected_device_version": device["version"]},
            PM,
        )
        validate_error(res, ApiErrorId.ERR_PRESCRIPTION_REQUIRED,
                       expected_status=422)


class TestCommissionGatedByInspection:

    def test_commission_blocked_by_failed_inspection(self, api):
        """PRD: "When any item fails, the outcome becomes `FAIL`, the
        `fail_reason` is recorded, and the device's `readiness_posture` is
        forced to `OUT_OF_SERVICE` until the underlying problem is corrected and
        a passing inspection restores it." PRD: "the device's `readiness_posture`
        must be `READY`, otherwise the attempt is rejected with
        `ERR_DEVICE_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/device_commission_gated_by_inspection_outcome
        """
        ctx = setup_installed_device_with_consumables(serial_number="SN-013")
        device = ctx["device"]
        inspector = create_responder(
            ctx["campus"]["id"], responder_role="INSPECTOR",
            full_name="Insp", badge_number="IN-13",
        )
        headers = make_inspector_headers(inspector["id"])
        insp = get_success_data(
            api.create_inspection(
                create_inspection_payload(device["id"], inspector["id"],
                                          scheduled_for="2026-09-01T00:00:00Z"),
                headers,
            )
        )
        get_success_data(
            api.submit_inspection(
                insp["id"],
                {"checklist_items": [{"item_code": "PADS_OK", "result": "FAIL"}],
                 "fail_reason": "Pads packaging damaged"},
                headers,
            )
        )

        res = api.commission_device(device["id"], PM)
        validate_error(res, ApiErrorId.ERR_DEVICE_NOT_READY, expected_status=409)
        current = get_device(device["id"])
        assert current["status"] == "INSTALLED"
        assert current["readiness_posture"] == "OUT_OF_SERVICE"

    def test_commission_blocked_without_any_inspection(self, api):
        """PRD: "Fifth, if the device has never had a passing inspection — its
        `last_inspection_at` is null — or the current time is later than thirty
        days after `last_inspection_at`, the posture is `DEGRADED`." PRD:
        "Commissioning advances the device from `INSTALLED` to `IN_SERVICE` and
        is gated entirely on posture: the device's `readiness_posture` must be
        `READY`, otherwise the attempt is rejected with `ERR_DEVICE_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/device_commission_gated_by_inspection_outcome
        """
        ctx = setup_installed_device_with_consumables(serial_number="SN-013B")
        device = ctx["device"]
        assert device["readiness_posture"] == "DEGRADED"
        res = api.commission_device(device["id"], PM)
        validate_error(res, ApiErrorId.ERR_DEVICE_NOT_READY, expected_status=409)
        assert get_device(device["id"])["status"] == "INSTALLED"


class TestDerivedPostureOnInstall:

    def test_posture_degraded_after_consumable_installs_without_inspection(self, api):
        """PRD: "Fifth, if the device has never had a passing inspection — its
        `last_inspection_at` is null — or the current time is later than thirty
        days after `last_inspection_at`, the posture is `DEGRADED`." PRD:
        "readiness is never asserted, only derived."

        Design: Corner/cross_cutting_complexity_layers/derived_field_readiness_posture_recomputed_on_install
        """
        ctx = setup_installed_device_with_consumables(serial_number="SN-DF-1")
        device = ctx["device"]
        # No inspection performed — posture must reflect that.
        assert device["last_inspection_at"] is None
        assert device["readiness_posture"] == "DEGRADED"

    def test_install_response_carries_computed_expires_at_immediately(self, api):
        """PRD: "The install's `expires_at` is computed at creation and never
        recalculated." PRD: "Unless otherwise noted, operations that create or
        modify a resource will return the created or updated resource object in
        the data field."

        Design: Corner/consistency_model/immediate_consistency_device_readiness_visible_same_request
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        device = create_device(campus["id"], model["id"],
                               serial_number="SN-IC-1")
        lot = create_lot(campus["id"], model["id"], kind="PAD",
                         lot_code="P-IC")
        res = api.create_install(
            {"device_id": device["id"], "consumable_lot_id": lot["id"],
             "expected_device_version": device["version"]},
            PM,
        )
        install = validate_success(res, expected_status=201)
        # expires_at must be present in the mutation response itself.
        assert "expires_at" in install
        # Pad shelf life is 24 months from install at 2026-09-01, earlier than
        # the lot's manufacturer expiration of 2030-01-01.
        assert install["expires_at"] == "2028-09-01T00:00:00Z"
