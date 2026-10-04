"""Crash scoring, diagnostics health score, and crash workflow tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_account_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_account_scenario,
    create_tier,
    create_zone,
    create_account,
    create_vehicle,
    create_trial_subscription,
    create_psap,
    create_crash_event,
    create_advisor_connected_event,
    create_dispatched_event,
    create_diagnostic_report,
    convert_subscription,
    drive_to_emergency_retained,
    set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["advisor_headers"]
PSAP_OP = TEST_USERS["psap_operator_headers"]
INGESTION = TEST_USERS["system_ingestion_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestCrashSeverityVariants:
    def test_sensor_reported_adds_airbag_bonus_over_delta_v_only(self, api):
        """PRD §3.3: when both flags come from the raw payload the sensor-reported
        score can reach the SEVERE band without extreme delta-V; when both flags
        are false the score reduces to 0.6 times the capped delta-V alone, which
        for identical delta-V produces a score up to 45.0 points lower than the
        sensor-reported variant.

        Design: Difficulty/dual_variant_calc/crash_severity_sensor_reported_vs_delta_v_only
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        hi = create_crash_event(
            vehicle, delta_v_kph=58.4, rollover_detected=False, airbag_deployed=True,
        )
        lo = create_crash_event(
            vehicle, delta_v_kph=58.4, rollover_detected=False, airbag_deployed=False,
        )
        assert hi["severity_score"] == pytest.approx(60.0, abs=0.01), (
            f"Expected 60.0 (0.6*58.4 + 25), got {hi['severity_score']}"
        )
        assert hi["severity_band"] == "SEVERE"
        assert lo["severity_score"] == pytest.approx(35.0, abs=0.01), (
            f"Expected 35.0 (0.6*58.4), got {lo['severity_score']}"
        )
        assert lo["severity_band"] == "MODERATE"
        assert hi["status"] == "RECEIVED" and lo["status"] == "RECEIVED"
        assert hi["severity_score"] - lo["severity_score"] == pytest.approx(25.0, abs=0.01)

    def test_rollover_flag_bonus_also_diverges_variant(self, api):
        """PRD §3.3: The raw score is the sum of three contributions: 0.6 times
        the smaller of delta_v_kph and 80; 25 if airbag_deployed is true and 0
        otherwise; and 20 if rollover_detected is true and 0 otherwise.

        Design: Difficulty/dual_variant_calc/crash_severity_sensor_reported_vs_delta_v_only
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        flagged = create_crash_event(
            vehicle, delta_v_kph=58.4, rollover_detected=True, airbag_deployed=False,
        )
        plain = create_crash_event(
            vehicle, delta_v_kph=58.4, rollover_detected=False, airbag_deployed=False,
        )
        assert flagged["severity_score"] == pytest.approx(55.0, abs=0.01)
        assert plain["severity_score"] == pytest.approx(35.0, abs=0.01)


class TestSeverityThreshold:
    def test_score_below_threshold_rejected_and_nothing_persisted(self, api):
        """PRD §3.3: A report whose severity_score comes out strictly below 35
        is rejected with ERR_CRASH_THRESHOLD_NOT_MET and no CrashEvent row is
        persisted.

        Design: Difficulty/boundary_precision_check/severity_threshold_34_9_rejected_35_0_accepted
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        resp = api.create_crash_event(
            vehicle["id"],
            {"delta_v_kph": 58.16, "rollover_detected": False,
             "airbag_deployed": False, "location_region_code": "TX"},
            INGESTION,
        )
        validate_error(resp, ApiErrorId.ERR_CRASH_THRESHOLD_NOT_MET)
        _, meta = validate_paginated(
            api.list_vehicle_crash_events(vehicle["id"], ADVISOR)
        )
        assert meta["total_count"] == 0, "rejected report must not persist"

    def test_exactly_threshold_score_accepted_as_moderate(self, api):
        """PRD §3.3: a score of at least 35 bands as MODERATE
        PRD §3.3: The resulting severity_score is rounded half-up to 1 decimal
        place.

        Design: Difficulty/boundary_precision_check/severity_threshold_34_9_rejected_35_0_accepted
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        event = create_crash_event(
            vehicle, delta_v_kph=58.334, rollover_detected=False,
            airbag_deployed=False,
        )
        assert event["severity_score"] == pytest.approx(35.0, abs=0.01)
        assert event["severity_band"] == "MODERATE"
        assert event["status"] == "RECEIVED"


class TestSeverityConstants:
    def test_delta_v_capped_at_eighty_before_weighting(self, api):
        """PRD §3.3: The raw score is the sum of three contributions: 0.6 times
        the smaller of delta_v_kph and 80; 25 if airbag_deployed is true and 0
        otherwise; and 20 if rollover_detected is true and 0 otherwise.

        Design: Corner/calculations/severity_score_constants_applied_at_delta_v_cap
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        event = create_crash_event(
            vehicle, delta_v_kph=120, rollover_detected=False,
            airbag_deployed=True,
        )
        assert event["severity_score"] == pytest.approx(73.0, abs=0.01), (
            f"0.6*min(120,80) + 25 = 73.0, got {event['severity_score']}"
        )
        assert event["severity_band"] == "SEVERE"


class TestHealthScore:
    def test_integer_division_applied_before_clamp_across_oil_boundary(self, api):
        """PRD §3.6: subtracts 1 for every full 5 percent of oil wear —
        computed by integer-dividing the difference between 100 and
        oil_life_pct by 5, truncating toward zero before the clamp.

        Design: Difficulty/combinatorial_formula/health_score_integer_division_and_clamp_order
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        dtcs = ["P0300", "P0420", "B0012"]
        rep_a = create_diagnostic_report(
            vehicle, odometer_km=10000, engine_hours=400,
            dtc_codes=dtcs, oil_life_pct=96,
        )
        rep_b = create_diagnostic_report(
            vehicle, odometer_km=10050, engine_hours=402,
            dtc_codes=dtcs, oil_life_pct=95,
        )
        assert rep_a["health_score"] == 76, (
            f"100 - 24 - 0 = 76 expected (4% wear truncates to 0), got {rep_a['health_score']}"
        )
        assert rep_b["health_score"] == 75, (
            f"100 - 24 - 1 = 75 expected (5% wear truncates to 1), got {rep_b['health_score']}"
        )

    def test_eight_points_per_trouble_code_and_clean_ceiling(self, api):
        """PRD §3.6: The score starts from a base of 100, subtracts 8 for each
        trouble code present in dtc_codes
        PRD §3.6: a clean report — empty dtc_codes and oil_life_pct equal to
        100 — always scores exactly 100 and is the only variant that can hit
        the ceiling

        Design: Difficulty/combinatorial_formula/health_score_integer_division_and_clamp_order
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        clean = create_diagnostic_report(
            vehicle, odometer_km=100, engine_hours=10,
            dtc_codes=[], oil_life_pct=100,
        )
        degraded = create_diagnostic_report(
            vehicle, odometer_km=200, engine_hours=20,
            dtc_codes=["P0300"], oil_life_pct=100,
        )
        assert clean["health_score"] == 100
        assert degraded["health_score"] == 92

    def test_health_score_clamps_at_zero_for_degraded_report(self, api):
        """PRD §3.6: The result is clamped to lie between 0 and 100 inclusive.

        Design: Corner/calculations/health_score_clamps_at_zero_for_degraded_report
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        report = create_diagnostic_report(
            vehicle, odometer_km=90000, engine_hours=4000,
            dtc_codes=["P0300", "P0301", "P0302", "P0303", "P0420", "P0430",
                       "P0171", "P0174", "B0012", "B0013", "U0100", "U0101"],
            oil_life_pct=0,
        )
        assert report["health_score"] == 0, (
            f"100 - 96 - 20 = -16 must clamp to 0, got {report['health_score']}"
        )
        assert report["status"] == "GENERATED"


class TestCrashWorkflowCascade:
    def test_dispatch_acknowledge_bubbles_up_to_close_crash_event(self, api):
        """PRD §3.3: A PSAPOperator acknowledges receipt, moving the dispatch
        from LOCATION_SENT to ACKNOWLEDGED and stamping acknowledged_at from
        the logical clock; the acknowledgement bubbles up to the parent
        CrashEvent, auto-transitioning it from DISPATCH_COORDINATED to the
        terminal CLOSED_DISPATCHED.

        Design: Difficulty/transitive_cascade/crash_dispatch_acknowledge_bubbleup_chain
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        psap = create_psap(name="Austin PSAP", region_code="TX")
        event, dispatch = create_dispatched_event(
            vehicle, psap, delta_v_kph=70, airbag_deployed=True,
        )
        assert event["status"] == "DISPATCH_COORDINATED", (
            f"dispatch must move CrashEvent to DISPATCH_COORDINATED, got {event['status']}"
        )
        assert dispatch["status"] == "LOCATION_SENT"
        assert dispatch["location_payload"] is not None

        resp = api.acknowledge_dispatch(dispatch["id"], PSAP_OP)
        acked = validate_success(resp)
        assert acked["status"] == "ACKNOWLEDGED"
        assert acked["acknowledged_at"] is not None

        after = get_success_data(
            api.get_crash_event(vehicle["id"], event["id"], ADVISOR)
        )
        assert after["status"] == "CLOSED_DISPATCHED", (
            f"bubble-up must close the event, got {after['status']}"
        )

    def test_dispatch_creation_sets_parent_and_snapshot_before_ack(self, api):
        """PRD §3.3: A successful dispatch creates a DispatchRequest in PENDING
        status, immediately transitions it to LOCATION_SENT with a
        location_payload snapshot frozen from the crash location and the
        severity_band, and moves the parent CrashEvent from ADVISOR_CONNECTED
        to DISPATCH_COORDINATED.

        Design: Difficulty/transitive_cascade/crash_dispatch_acknowledge_bubbleup_chain
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        psap = create_psap(name="Austin PSAP", region_code="TX")
        event = create_advisor_connected_event(
            vehicle, delta_v_kph=70, airbag_deployed=True,
        )
        assert event["status"] == "ADVISOR_CONNECTED"
        resp = api.create_dispatch_request(
            vehicle["id"], event["id"], {"psap_id": psap["id"]}, ADVISOR,
        )
        dispatch = validate_success(resp, 201)
        assert dispatch["status"] == "LOCATION_SENT"
        assert dispatch["location_payload"] is not None
        assert dispatch["crash_event_id"] == event["id"]
        assert dispatch["psap_id"] == psap["id"]

    def test_dispatch_lands_location_sent_immediately_after_creation(self, api):
        """PRD §3.3: A successful dispatch creates a DispatchRequest in PENDING
        status, immediately transitions it to LOCATION_SENT with a
        location_payload snapshot frozen from the crash location and the
        severity_band

        Design: Corner/state_machines/acknowledge_on_pending_dispatch_rejected_before_location_sent
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        psap = create_psap(name="Austin PSAP", region_code="TX")
        event = create_advisor_connected_event(
            vehicle, delta_v_kph=70, airbag_deployed=True,
        )
        resp = api.create_dispatch_request(
            vehicle["id"], event["id"], {"psap_id": psap["id"]}, ADVISOR,
        )
        dispatch = validate_success(resp, 201)
        assert dispatch["status"] == "LOCATION_SENT", (
            f"system hop to LOCATION_SENT must execute at creation, got {dispatch['status']}"
        )
        assert dispatch["location_payload"] is not None


class TestAdvisorConnect:
    def test_connect_advisor_moves_received_event_to_advisor_connected(self, api):
        """PRD §3.3: Once RECEIVED, an Advisor connects to the event, moving it
        from RECEIVED to ADVISOR_CONNECTED

        Design: Corner/state_machines/connect_advisor_on_received_event_moves_to_advisor_connected
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        event = create_crash_event(vehicle, delta_v_kph=70, airbag_deployed=True)
        assert event["status"] == "RECEIVED"
        resp = api.connect_advisor(vehicle["id"], event["id"], ADVISOR)
        data = validate_success(resp)
        assert data["status"] == "ADVISOR_CONNECTED"
        assert data["version"] == event["version"] + 1, (
            "one transition increments version by exactly 1"
        )

    def test_connect_advisor_twice_second_attempt_invalid_state(self, api):
        """PRD §3.3: Once RECEIVED, an Advisor connects to the event, moving it
        from RECEIVED to ADVISOR_CONNECTED
        PRD §2.8: (6) state-machine legality — the target resource is in a
        valid from-state for the requested transition, else ERR_INVALID_STATE

        Design: Corner/state_machines/connect_advisor_twice_second_attempt_invalid_state
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        event = create_advisor_connected_event(
            vehicle, delta_v_kph=70, airbag_deployed=True,
        )
        assert event["status"] == "ADVISOR_CONNECTED"
        resp = api.connect_advisor(vehicle["id"], event["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(
            api.get_crash_event(vehicle["id"], event["id"], ADVISOR)
        )
        assert after["status"] == "ADVISOR_CONNECTED"
        assert after["version"] == event["version"], "rejected call must not bump version"


class TestCrashEventCrossEntityGating:
    def test_lapsed_subscription_rejects_crash_event_but_active_accepts(self, api):
        """PRD §3.3: If the resolved subscription is in TRIAL, ACTIVE,
        PAST_DUE, or EMERGENCY_RETAINED and its entitlement bundle has
        allows_emergency true, the event is admitted in RECEIVED status.
        Otherwise — for LAPSED, CANCELLED, or missing subscriptions, or for
        any tier without emergency entitlement — the event is persisted
        directly into the terminal REJECTED_NO_ENTITLEMENT status.

        Design: Difficulty/cross_entity_state_dependency/crash_event_gated_by_subscription_lifecycle_status
        """
        _, _, account_a, vehicle_a, sub_a = setup_account_scenario()
        convert_subscription(account_a, sub_a)
        _, _, account_b, vehicle_b, sub_b = setup_account_scenario()
        convert_subscription(account_b, sub_b)
        get_success_data(api.record_billing_event(
            account_b["id"], sub_b["id"], {"outcome": "PAYMENT_FAILED"}, BILLING,
        ))
        # PAST_DUE entry 2026-09-01 -> LAPSED at 2026-09-11; CANCELLED after
        # the 30-day retention window at 2026-10-11.
        set_clock("2026-10-15T00:00:00Z")

        ok = create_crash_event(vehicle_a, delta_v_kph=60, airbag_deployed=False)
        bad = create_crash_event(vehicle_b, delta_v_kph=60, airbag_deployed=False)
        assert ok["status"] == "RECEIVED"
        assert bad["status"] == "REJECTED_NO_ENTITLEMENT", (
            f"subscription past retention window must reject, got {bad['status']}"
        )
        assert bad["subscription_id"] == sub_b["id"]

    def test_trial_subscription_with_emergency_entitlement_accepts_crash(self, api):
        """PRD §3.3: If the resolved subscription is in TRIAL, ACTIVE,
        PAST_DUE, or EMERGENCY_RETAINED and its entitlement bundle has
        allows_emergency true, the event is admitted in RECEIVED status.

        Design: Difficulty/cross_entity_state_dependency/crash_event_gated_by_subscription_lifecycle_status
        """
        _, _, account, vehicle, subscription = setup_account_scenario()
        assert subscription["status"] == "TRIAL"
        event = create_crash_event(vehicle, delta_v_kph=60, airbag_deployed=False)
        assert event["status"] == "RECEIVED"
        assert event["subscription_id"] == subscription["id"]
