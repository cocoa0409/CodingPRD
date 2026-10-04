"""Readiness posture: the device posture ladder, self-test FAIL cascade to
campus posture, and compound posture on a fresh device.

Design: Difficulty/combinatorial_formula/readiness_posture_mode_a_multi_input_nonlinear,
        Difficulty/transitive_cascade/self_test_fail_cascade_two_hop_to_campus_posture,
        Difficulty/non_linear_state_machine/device_compound_posture_driven_by_children.
"""

from test_helpers import (
    create_responder,
    create_self_test_report_payload,
    get_device,
    get_success_data,
    make_inspector_headers,
    schedule_and_pass_inspection,
    set_clock,
    setup_commissioned_device,
    setup_campus_zone_cabinet_device,
    validate_success,
    TEST_USERS,
    create_inspection_payload,
    create_inspection_submit_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["program_manager_headers"]
SYSTEM = TEST_USERS["system_headers"]


class TestSelfTestFailForcesOutOfService:

    def test_fail_selftest_overrides_fresh_consumables_and_current_inspection(self, api):
        """PRD: "Fourth, if the device's `last_selftest_status` is `FAIL`, the
        posture is `OUT_OF_SERVICE`." PRD: "Ingestion updates the device's
        `last_selftest_status` to the reported result and recomputes the device's
        posture — a `FAIL` drives the posture to `OUT_OF_SERVICE` under the
        posture ladder".

        Design: Difficulty/combinatorial_formula/readiness_posture_mode_a_multi_input_nonlinear
        """
        ctx = setup_commissioned_device(serial_number="SN-003",
                                        with_certified_responder=False)
        device = ctx["device"]
        assert device["readiness_posture"] == "READY"
        assert device["last_selftest_status"] == "PASS"

        get_success_data(
            api.create_self_test_report(
                create_self_test_report_payload(
                    device["id"], reported_at="2026-09-01T01:00:00Z",
                    result="FAIL", fault_code="BATT-LOW",
                ),
                SYSTEM,
            )
        )
        after = get_device(device["id"])
        assert after["readiness_posture"] == "OUT_OF_SERVICE"
        assert after["last_selftest_status"] == "FAIL"

    def test_fail_selftest_blocks_commission_even_with_pass_inspection(self, api):
        """PRD: "Fourth, if the device's `last_selftest_status` is `FAIL`, the
        posture is `OUT_OF_SERVICE`." PRD: "the device's `readiness_posture` must
        be `READY`, otherwise the attempt is rejected with
        `ERR_DEVICE_NOT_READY`."

        Design: Difficulty/combinatorial_formula/readiness_posture_mode_a_multi_input_nonlinear
        """
        from test_helpers import (
            ApiErrorId,
            setup_installed_device_with_consumables,
            validate_error,
        )
        ctx = setup_installed_device_with_consumables(serial_number="SN-003C")
        device = ctx["device"]
        inspector = create_responder(
            ctx["campus"]["id"], responder_role="INSPECTOR",
            full_name="Insp I", badge_number="IN-1",
        )
        schedule_and_pass_inspection(device["id"], inspector["id"])
        # FAIL self-test arrives after the passing inspection.
        get_success_data(
            api.create_self_test_report(
                create_self_test_report_payload(
                    device["id"], reported_at="2026-09-01T01:00:00Z",
                    result="FAIL", fault_code="BATT-LOW",
                ),
                SYSTEM,
            )
        )
        after = get_device(device["id"])
        assert after["readiness_posture"] == "OUT_OF_SERVICE"

        res = api.commission_device(device["id"], PM)
        validate_error(res, ApiErrorId.ERR_DEVICE_NOT_READY, expected_status=409)


class TestSelfTestCascadeToCampusPosture:

    def test_fail_selftest_flips_single_device_campus_to_critical(self, api):
        """PRD: "The campus posture is `CRITICAL` when the outage count is at
        least the larger of one and the total device count multiplied by 0.25
        and rounded up to a whole number." PRD: "Ingestion updates the device's
        `last_selftest_status` to the reported result and recomputes the device's
        posture — a `FAIL` drives the posture to `OUT_OF_SERVICE` under the
        posture ladder".

        Design: Difficulty/transitive_cascade/self_test_fail_cascade_two_hop_to_campus_posture
        """
        ctx = setup_commissioned_device(serial_number="SN-008",
                                        with_certified_responder=False)
        campus = ctx["campus"]
        device = ctx["device"]
        campus_before = get_success_data(api.get_campus(campus["id"], PM))
        assert campus_before["readiness_posture"] == "OPERATIONAL"

        get_success_data(
            api.create_self_test_report(
                create_self_test_report_payload(
                    device["id"], reported_at="2026-09-01T01:00:00Z",
                    result="FAIL", fault_code="BATT-LOW",
                ),
                SYSTEM,
            )
        )
        device_after = get_device(device["id"])
        assert device_after["readiness_posture"] == "OUT_OF_SERVICE"
        campus_after = get_success_data(api.get_campus(campus["id"], PM))
        # 1 device, 1 out of service: 1 >= max(1, ceil(1 * 0.25)) == 1.
        assert campus_after["readiness_posture"] == "CRITICAL"

    def test_campus_posture_recovers_after_pass_selftest(self, api):
        """PRD: "Ingestion updates the device's `last_selftest_status` to the
        reported result and recomputes the device's posture". PRD: "Only when
        none of these conditions hold is the posture `READY`." PRD: "Otherwise
        the campus posture is `OPERATIONAL`."

        Design: Difficulty/transitive_cascade/self_test_fail_cascade_two_hop_to_campus_posture
        """
        ctx = setup_commissioned_device(serial_number="SN-008B",
                                        with_certified_responder=False)
        campus = ctx["campus"]
        device = ctx["device"]

        get_success_data(
            api.create_self_test_report(
                create_self_test_report_payload(
                    device["id"], reported_at="2026-09-01T01:00:00Z",
                    result="FAIL", fault_code="BATT-LOW",
                ),
                SYSTEM,
            )
        )
        campus_mid = get_success_data(api.get_campus(campus["id"], PM))
        assert campus_mid["readiness_posture"] == "CRITICAL"

        # A subsequent PASS report clears the FAIL condition; the inspection is
        # current and consumables are fresh, so posture returns to READY and
        # the campus returns to OPERATIONAL.
        get_success_data(
            api.create_self_test_report(
                create_self_test_report_payload(
                    device["id"], reported_at="2026-09-01T02:00:00Z",
                    result="PASS",
                ),
                SYSTEM,
            )
        )
        device_after = get_device(device["id"])
        assert device_after["last_selftest_status"] == "PASS"
        assert device_after["readiness_posture"] == "READY"
        campus_after = get_success_data(api.get_campus(campus["id"], PM))
        assert campus_after["readiness_posture"] == "OPERATIONAL"


class TestCompoundPostureOnFreshDevice:

    def test_registered_device_posture_out_of_service_without_consumables(self, api):
        """PRD: "A freshly registered device starts with lifecycle `status`
        equal to `REGISTERED`, ... and — because it has no consumables — with
        `readiness_posture` equal to `OUT_OF_SERVICE` per the posture ladder in
        §2.5." PRD: "Second, if the device has no active pad install or no
        active battery install, the posture is `OUT_OF_SERVICE`."

        Design: Difficulty/non_linear_state_machine/device_compound_posture_driven_by_children
        """
        _, _, _, device, _ = setup_campus_zone_cabinet_device(
            serial_number="SN-006"
        )
        fetched = get_device(device["id"])
        assert fetched["readiness_posture"] == "OUT_OF_SERVICE"
        assert fetched["status"] == "REGISTERED"

    def test_installing_pad_only_leaves_posture_out_of_service(self, api):
        """PRD: "Second, if the device has no active pad install or no active
        battery install, the posture is `OUT_OF_SERVICE`."

        Design: Difficulty/non_linear_state_machine/device_compound_posture_driven_by_children
        """
        from test_helpers import create_lot, install_consumable
        campus, _, _, device, model = setup_campus_zone_cabinet_device(
            serial_number="SN-006B"
        )
        pad_lot = create_lot(campus["id"], model["id"], kind="PAD")
        install_consumable(device["id"], pad_lot["id"])
        fetched = get_device(device["id"])
        # Battery still missing — posture remains OUT_OF_SERVICE while the
        # primary lifecycle status is untouched by the posture dimension.
        assert fetched["readiness_posture"] == "OUT_OF_SERVICE"
        assert fetched["status"] == "REGISTERED"
