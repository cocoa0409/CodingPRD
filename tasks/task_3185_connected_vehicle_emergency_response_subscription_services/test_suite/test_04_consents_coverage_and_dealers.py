"""Consents, insurance score, coverage gating, remote commands, dealers."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
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
    create_diagnostic_report,
    create_consent,
    create_psap,
    create_advisor_connected_event,
    create_dealer,
    create_requested_appointment,
    convert_subscription,
    drive_to_emergency_retained,
    set_clock,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADVISOR = TEST_USERS["advisor_headers"]
DEALER_SVC = TEST_USERS["dealer_service_headers"]
INGESTION = TEST_USERS["system_ingestion_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestInsuranceScore:
    def _account_with_reports(self, api, report_specs):
        create_tier(code="SAFETY")
        create_zone(region_code="TX")
        account = create_account()
        vehicle = create_vehicle(account, region_code="TX", hardware_generation=5)
        for spec in report_specs:
            create_diagnostic_report(vehicle, **spec)
        create_consent(account, "DRIVING_DATA_COLLECTION")
        return account, vehicle

    def test_reports_first_order_and_empty_set_baseline(self, api):
        """PRD §3.7: The evaluation order is pinned — reports are aggregated
        first, then the average is taken
        PRD §3.7: when no qualifying reports exist, the score is the baseline
        value 50.00

        Design: Difficulty/combinatorial_formula/insurance_score_evaluation_order_with_empty_set_baseline
        """
        # Account with reports scoring 75 and 90 -> mean 82.50.
        # PRD §3.6 pins health_score = 100 - 8*len(dtc_codes) - (100-oil)//5:
        #   report 1: 3 codes, oil 95 -> 100 - 24 - 1 = 75
        #   report 2: 1 code,  oil 86 -> 100 - 8 - 2 = 90  (14% wear // 5 = 2)
        account_a, vehicle_a = self._account_with_reports(api, [
            {"odometer_km": 5000, "engine_hours": 200,
             "dtc_codes": ["P0300", "P0420", "B0012"], "oil_life_pct": 95},
            {"odometer_km": 6000, "engine_hours": 240,
             "dtc_codes": ["P0171"], "oil_life_pct": 86},
        ])
        consent_a = create_consent(account_a, "INSURANCE_PROGRAM_SHARING")
        assert consent_a["effective_score"] == pytest.approx(82.50, abs=0.005), (
            f"mean of 75 and 90 must be 82.50, got {consent_a['effective_score']}"
        )
        assert consent_a["status"] == "GRANTED"

        # Account with zero reports -> baseline 50.00.
        account_b, _ = self._account_with_reports(api, [])
        consent_b = create_consent(account_b, "INSURANCE_PROGRAM_SHARING")
        assert consent_b["effective_score"] == pytest.approx(50.00, abs=0.005)
        assert consent_b["status"] == "GRANTED"

    def test_score_uses_raw_health_scores_of_recent_reports(self, api):
        """PRD §3.7: The raw value is the sum of those reports' health_score
        values, and the count is the number of those reports. The
        effective_score is the raw sum divided by the count, rounded half-up
        to 2 decimal places

        Design: Difficulty/combinatorial_formula/insurance_score_evaluation_order_with_empty_set_baseline
        """
        # Single clean report (health 100) -> mean 100.00.
        account, vehicle = self._account_with_reports(api, [
            {"odometer_km": 100, "engine_hours": 10,
             "dtc_codes": [], "oil_life_pct": 100},
        ])
        consent = create_consent(account, "INSURANCE_PROGRAM_SHARING")
        assert consent["effective_score"] == pytest.approx(100.00, abs=0.005)

    def test_reports_older_than_ninety_days_excluded(self, api):
        """PRD §3.7: reports whose creation instant falls between the logical
        clock minus 90 days and the logical clock, inclusive

        Design: Corner/calculations/insurance_score_excludes_reports_older_than_ninety_days
        """
        account, vehicle = self._account_with_reports(api, [
            {"odometer_km": 5000, "engine_hours": 200,
             "dtc_codes": ["P0300", "P0420", "B0012"], "oil_life_pct": 95},
        ])
        set_clock("2026-12-15T00:00:00Z")  # 104 days later
        consent = create_consent(account, "INSURANCE_PROGRAM_SHARING")
        assert consent["effective_score"] == pytest.approx(50.00, abs=0.005), (
            "the 104-day-old report must fall outside the trailing-90-day window"
        )
        assert consent["status"] == "GRANTED"


class TestConsentCycle:
    def _account_with_both_consents(self, api):
        create_tier(code="SAFETY")
        create_zone(region_code="TX")
        account = create_account()
        create_vehicle(account)
        dc = create_consent(account, "DRIVING_DATA_COLLECTION")
        ins = create_consent(account, "INSURANCE_PROGRAM_SHARING")
        return account, dc, ins

    def test_revoke_regrant_cycle_gated_by_sibling_dependency(self, api):
        """PRD §3.7: Re-granting moves a REVOKED consent back to GRANTED — the
        machine is cyclic between these two states — resetting granted_at to
        the logical clock and clearing revoked_at to null.

        Design: Difficulty/non_linear_state_machine/data_consent_revoke_regrant_cycle_gated_by_dependency
        """
        account, dc, ins = self._account_with_both_consents(api)
        headers = make_account_headers(account["id"])
        revoked = validate_success(
            api.revoke_consent(account["id"], ins["id"], headers)
        )
        assert revoked["status"] == "REVOKED"
        assert revoked["revoked_at"] is not None

        regranted = validate_success(
            api.grant_consent(account["id"], ins["id"], headers)
        )
        assert regranted["status"] == "GRANTED"
        assert regranted["granted_at"] >= revoked["revoked_at"]
        assert regranted["revoked_at"] is None
        dc_after = get_success_data(api.get_consent_aliased(dc["id"], headers))
        assert dc_after["status"] == "GRANTED"

    def test_regrant_fails_when_data_collection_dependency_revoked(self, api):
        """PRD §3.7: Re-granting an insurance-sharing consent carries a
        cross-entity dependency: the account's DRIVING_DATA_COLLECTION consent
        must currently be GRANTED; otherwise the grant is rejected with
        ERR_CONSENT_DEPENDENCY_MISSING.

        Design: Difficulty/non_linear_state_machine/data_consent_revoke_regrant_cycle_gated_by_dependency
        """
        account, dc, ins = self._account_with_both_consents(api)
        headers = make_account_headers(account["id"])
        validate_success(api.revoke_consent(account["id"], ins["id"], headers))
        validate_success(api.revoke_consent(account["id"], dc["id"], headers))
        resp = api.grant_consent(account["id"], ins["id"], headers)
        validate_error(resp, ApiErrorId.ERR_CONSENT_DEPENDENCY_MISSING)

    def test_consent_create_supersedes_prior_same_type_consent(self, api):
        """PRD §3.7: if a non-superseded consent of the same consent_type
        already exists for the account, the prior row is automatically moved
        to SUPERSEDED
        PRD §3.7: At most one non-SUPERSEDED consent exists per account and
        consent type at any moment.

        Design: Corner/state_machines/consent_create_supersedes_prior_same_type_consent
        """
        account = create_account()
        headers = make_account_headers(account["id"])
        old = create_consent(account, "DRIVING_DATA_COLLECTION")
        new = create_consent(account, "DRIVING_DATA_COLLECTION")
        assert new["status"] == "GRANTED"
        old_after = get_success_data(api.get_consent_aliased(old["id"], headers))
        assert old_after["status"] == "SUPERSEDED"
        rows, meta = validate_paginated(
            api.list_account_consents(
                account["id"], headers,
                params={"consent_type": "DRIVING_DATA_COLLECTION"},
            )
        )
        granted = [r for r in rows if r["status"] == "GRANTED"]
        assert len(granted) == 1

    def test_insurance_sharing_grant_requires_data_collection_consent(self, api):
        """PRD §3.7: Re-granting an insurance-sharing consent carries a
        cross-entity dependency: the account's DRIVING_DATA_COLLECTION consent
        must currently be GRANTED; otherwise the grant is rejected with
        ERR_CONSENT_DEPENDENCY_MISSING.

        Design: Corner/validations/insurance_sharing_grant_requires_data_collection_consent
        """
        account = create_account()
        headers = make_account_headers(account["id"])
        resp = api.create_consent(
            account["id"], {"consent_type": "INSURANCE_PROGRAM_SHARING"}, headers,
        )
        validate_error(resp, ApiErrorId.ERR_CONSENT_DEPENDENCY_MISSING)
        rows, meta = validate_paginated(
            api.list_account_consents(account["id"], headers)
        )
        assert meta["total_count"] == 0


class TestCoverageGating:
    def test_crash_in_dead_zone_persisted_rejected_no_coverage(self, api):
        """PRD §3.3: If the CoverageZone for location_region_code has
        has_cellular set to false, the event is persisted directly into the
        terminal REJECTED_NO_COVERAGE status — coverage dominates and no
        entitlement check is reached.

        Design: Corner/validations/crash_event_in_dead_zone_created_rejected_no_coverage
        """
        create_tier(code="SAFETY")
        create_zone(region_code="NM", has_cellular=False,
                    supports_data=False, supports_navigation=False)
        account = create_account(
            full_name="Ana Alvarez", email="ana@example.com",
            phone="+15125550101", home_region_code="NM",
        )
        vehicle = create_vehicle(account, region_code="NM", hardware_generation=5)
        create_trial_subscription(account, vehicle, "SAFETY")
        resp = api.create_crash_event(
            vehicle["id"],
            {"delta_v_kph": 70, "rollover_detected": False,
             "airbag_deployed": True, "location_region_code": "NM"},
            INGESTION,
        )
        event = get_success_data(resp, 201)
        assert event["status"] == "REJECTED_NO_COVERAGE"
        assert event["severity_score"] == pytest.approx(67.0, abs=0.01)


class TestEmergencyRetainedCommands:
    def _emergency_retained(self, api):
        _, _, account, vehicle, sub = setup_account_scenario()
        retained = drive_to_emergency_retained(account, sub)
        return account, vehicle, retained

    def test_lock_rejected_but_locate_allowed_under_emergency_retention(self, api):
        """PRD §3.5: unless the subscription is in EMERGENCY_RETAINED, in which
        case only LOCATE is permitted under the emergency-only path and any
        other command type is rejected with ERR_EMERGENCY_ONLY_COMMAND
        PRD §3.5: The is_emergency_command flag is true exactly when the
        command was accepted under the emergency-only path of an
        EMERGENCY_RETAINED subscription — which is to say, when the command
        type is LOCATE.

        Design: Corner/endpoints/emergency_retained_lock_rejected_but_locate_allowed
        """
        account, vehicle, retained = self._emergency_retained(api)
        headers = make_account_headers(account["id"])
        resp = api.create_remote_command(vehicle["id"], {"command_type": "LOCK"}, headers)
        validate_error(resp, ApiErrorId.ERR_EMERGENCY_ONLY_COMMAND)
        resp = api.create_remote_command(vehicle["id"], {"command_type": "LOCATE"}, headers)
        command = validate_success(resp, 201)
        assert command["status"] in {"SENT", "PENDING"}
        assert command["is_emergency_command"] is True
        sub_after = get_success_data(
            api.get_subscription(account["id"], retained["id"], headers)
        )
        assert sub_after["emergency_only_flag"] is True

    def test_emergency_locate_allowed_while_non_locate_still_denied(self, api):
        """PRD §3.2: While a subscription sits in EMERGENCY_RETAINED, its
        entitlements collapse to a fixed bundle: automatic crash notification
        remains, and the emergency LOCATE remote command remains, but every
        other entitlement is denied.

        Design: Corner/endpoints/emergency_retained_lock_rejected_but_locate_allowed
        """
        account, vehicle, retained = self._emergency_retained(api)
        headers = make_account_headers(account["id"])
        resp = api.create_remote_command(vehicle["id"], {"command_type": "UNLOCK"}, headers)
        validate_error(resp, ApiErrorId.ERR_EMERGENCY_ONLY_COMMAND)


class TestExpiredCommandsExcluded:
    def test_expired_remote_commands_never_consume_the_period_cap(self, api):
        """PRD §3.5: Independently, whenever the logical clock reaches a
        command's expires_at, the command flips from PENDING or SENT to the
        terminal EXPIRED — and an EXPIRED command never consumes the cap.

        Design: Corner/calculations/expired_remote_commands_never_consume_the_period_cap
        """
        _, _, account, vehicle, sub = setup_account_scenario(
            tier_code="SAFETY_REMOTE", tier_fee=4000, allows_remote_commands=True,
        )
        sub = convert_subscription(account, sub)
        headers = make_account_headers(account["id"])
        get_success_data(api.create_remote_command(
            vehicle["id"], {"command_type": "LOCK"}, headers,
        ), 201)
        get_success_data(api.create_remote_command(
            vehicle["id"], {"command_type": "UNLOCK"}, headers,
        ), 201)
        set_clock("2026-09-01T00:11:00Z")
        sub_after = get_success_data(
            api.get_subscription(account["id"], sub["id"], headers)
        )
        assert sub_after["period_remote_commands_used"] == 0


class TestDispatchPsapRegion:
    def test_dispatch_to_psap_in_wrong_region_rejected(self, api):
        """PRD §3.3: the chosen PSAP must be in ACTIVE status, must have
        accepts_location_transfer true, and must serve the same region as the
        event's location_region_code — failures are rejected with
        ERR_PSAP_UNAVAILABLE

        Design: Corner/endpoints/dispatch_to_psap_in_wrong_region_rejected
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        create_zone(region_code="OK", has_cellular=True,
                    supports_data=True, supports_navigation=True)
        psap_ok = create_psap(name="Tulsa PSAP", region_code="OK")
        event = create_advisor_connected_event(
            vehicle, delta_v_kph=70, airbag_deployed=True,
        )
        resp = api.create_dispatch_request(
            vehicle["id"], event["id"], {"psap_id": psap_ok["id"]}, ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_PSAP_UNAVAILABLE)
        after = get_success_data(
            api.get_crash_event(vehicle["id"], event["id"], ADVISOR)
        )
        assert after["status"] == "ADVISOR_CONNECTED"
        _, meta = validate_paginated(
            api.list_vehicle_dispatch_requests(vehicle["id"], ADVISOR)
        )
        assert meta["total_count"] == 0


class TestVehicleDecommission:
    def test_decommission_blocked_while_subscription_live(self, api):
        """PRD §3.1: the account may decommission an ACTIVE vehicle by updating
        its status to DECOMMISSIONED — but only when no subscription on that
        vehicle sits in TRIAL, ACTIVE, PAST_DUE, or EMERGENCY_RETAINED. Any
        other vehicle-state update is rejected with ERR_INVALID_STATE.

        Design: Corner/endpoints/vehicle_decommission_blocked_while_subscription_live
        """
        _, _, account, vehicle, sub = setup_account_scenario()
        headers = make_account_headers(account["id"])
        resp = api.update_vehicle(vehicle["id"], {"status": "DECOMMISSIONED"}, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        veh = get_success_data(api.get_vehicle(vehicle["id"], ADMIN))
        assert veh["status"] == "ACTIVE"


class TestDealerAppointments:
    def test_dealer_day_capacity_interval_semantics(self, api):
        """PRD §3.6: the dealer must be in ACTIVE status, and the count of the
        dealer's CONFIRMED appointments whose scheduled_date equals the
        candidate's scheduled_date must be strictly less than the dealer's
        service_capacity_per_day — so a dealer with capacity 1 and 1 confirmed
        appointment on that day rejects the next confirm with
        ERR_DEALER_CAPACITY_REACHED

        Design: Difficulty/resource_temporal_overlap/dealer_day_capacity_aggregate_interval_semantics
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        dealer = create_dealer(name="Capitol Chevrolet", region_code="TX", capacity=2)
        reports = [
            create_diagnostic_report(
                vehicle, odometer_km=30000 + 10 * i, engine_hours=1200 + i,
                dtc_codes=[f"P030{i}"], oil_life_pct=50,
            )
            for i in range(4)
        ]
        ap1 = create_requested_appointment(dealer, vehicle, reports[0], "2026-09-10")
        ap2 = create_requested_appointment(dealer, vehicle, reports[1], "2026-09-10")
        ap3 = create_requested_appointment(dealer, vehicle, reports[2], "2026-09-10")
        ap4 = create_requested_appointment(dealer, vehicle, reports[3], "2026-09-11")
        validate_success(api.confirm_appointment(dealer["id"], ap1["id"], DEALER_SVC))
        validate_success(api.confirm_appointment(dealer["id"], ap2["id"], DEALER_SVC))

        resp = api.confirm_appointment(dealer["id"], ap3["id"], DEALER_SVC)
        validate_error(resp, ApiErrorId.ERR_DEALER_CAPACITY_REACHED)
        ap3_after = get_success_data(
            api.get_service_appointment(ap3["id"], DEALER_SVC)
        )
        assert ap3_after["status"] == "REQUESTED"

        confirmed = validate_success(
            api.confirm_appointment(dealer["id"], ap4["id"], DEALER_SVC)
        )
        assert confirmed["status"] == "CONFIRMED", (
            "adjacent day 2026-09-11 shares no interval occupation"
        )

    def test_capacity_gate_at_confirm_leaves_report_untouched_on_reject(self, api):
        """PRD §3.6: On success the appointment moves from REQUESTED to
        CONFIRMED and the linked DiagnosticReport cascades from GENERATED to
        SERVICE_SCHEDULED.

        Design: Difficulty/resource_temporal_overlap/dealer_day_capacity_aggregate_interval_semantics
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        dealer = create_dealer(name="Capitol Chevrolet", region_code="TX", capacity=1)
        rep1 = create_diagnostic_report(
            vehicle, odometer_km=30000, engine_hours=1200,
            dtc_codes=["P0300"], oil_life_pct=50,
        )
        rep2 = create_diagnostic_report(
            vehicle, odometer_km=30010, engine_hours=1201,
            dtc_codes=["P0301"], oil_life_pct=50,
        )
        ap1 = create_requested_appointment(dealer, vehicle, rep1, "2026-09-10")
        ap2 = create_requested_appointment(dealer, vehicle, rep2, "2026-09-10")
        validate_success(api.confirm_appointment(dealer["id"], ap1["id"], DEALER_SVC))
        resp = api.confirm_appointment(dealer["id"], ap2["id"], DEALER_SVC)
        validate_error(resp, ApiErrorId.ERR_DEALER_CAPACITY_REACHED)
        rep2_after = get_success_data(
            api.get_diagnostic_report(vehicle["id"], rep2["id"], DEALER_SVC)
        )
        assert rep2_after["status"] == "GENERATED", (
            "rejected confirm must not cascade to the report"
        )

    def test_appointment_confirm_cascades_report_to_service_scheduled(self, api):
        """PRD §3.6: On success the appointment moves from REQUESTED to
        CONFIRMED and the linked DiagnosticReport cascades from GENERATED to
        SERVICE_SCHEDULED.

        Design: Difficulty/cross_entity_state_dependency/appointment_confirm_gated_by_dealer_status_and_report_state
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        dealer = create_dealer(name="Capitol Chevrolet", region_code="TX", capacity=2)
        rep1 = create_diagnostic_report(
            vehicle, odometer_km=20000, engine_hours=800,
            dtc_codes=["P0300"], oil_life_pct=40,
        )
        ap1 = create_requested_appointment(dealer, vehicle, rep1, "2026-09-10")
        confirmed = validate_success(
            api.confirm_appointment(dealer["id"], ap1["id"], DEALER_SVC)
        )
        assert confirmed["status"] == "CONFIRMED"
        rep_after = get_success_data(
            api.get_diagnostic_report(vehicle["id"], rep1["id"], DEALER_SVC)
        )
        assert rep_after["status"] == "SERVICE_SCHEDULED"

    def test_confirmed_appointment_completion_moves_to_terminal(self, api):
        """PRD §3.6: Completion moves a CONFIRMED appointment to the terminal
        COMPLETED.

        Design: Difficulty/cross_entity_state_dependency/appointment_confirm_gated_by_dealer_status_and_report_state
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        dealer = create_dealer(name="Capitol Chevrolet", region_code="TX", capacity=2)
        rep = create_diagnostic_report(
            vehicle, odometer_km=20000, engine_hours=800,
            dtc_codes=["P0300"], oil_life_pct=40,
        )
        ap = create_requested_appointment(dealer, vehicle, rep, "2026-09-10")
        validate_success(api.confirm_appointment(dealer["id"], ap["id"], DEALER_SVC))
        completed = validate_success(
            api.complete_appointment(dealer["id"], ap["id"], DEALER_SVC)
        )
        assert completed["status"] == "COMPLETED"

    def test_appointment_cancel_compensates_report_schedule_pointer(self, api):
        """PRD §3.6: Cancelling a CONFIRMED appointment triggers a compensating
        cascade: the linked DiagnosticReport reverts from SERVICE_SCHEDULED
        back to GENERATED, but only if no other non-cancelled appointment still
        references the same report.
        PRD §3.6: Cancellation is permitted from either REQUESTED or CONFIRMED
        and lands in the terminal CANCELLED.

        Design: Difficulty/compensating_invariant/appointment_cancel_compensates_report_schedule_pointer
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        dealer = create_dealer(name="Capitol Chevrolet", region_code="TX", capacity=3)
        rep = create_diagnostic_report(
            vehicle, odometer_km=40000, engine_hours=1600,
            dtc_codes=["P0300"], oil_life_pct=20,
        )
        ap = create_requested_appointment(dealer, vehicle, rep, "2026-09-15")
        validate_success(api.confirm_appointment(dealer["id"], ap["id"], DEALER_SVC))
        rep_mid = get_success_data(
            api.get_diagnostic_report(vehicle["id"], rep["id"], DEALER_SVC)
        )
        assert rep_mid["status"] == "SERVICE_SCHEDULED"

        cancelled = validate_success(
            api.cancel_appointment(dealer["id"], ap["id"], DEALER_SVC)
        )
        assert cancelled["status"] == "CANCELLED"
        rep_after = get_success_data(
            api.get_diagnostic_report(vehicle["id"], rep["id"], DEALER_SVC)
        )
        assert rep_after["status"] == "GENERATED", (
            "compensation must revert the report once no live appointment references it"
        )
        resp = api.confirm_appointment(dealer["id"], ap["id"], DEALER_SVC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cancel_from_requested_has_no_report_side_effect(self, api):
        """PRD §3.6: Cancelling a REQUESTED appointment has no further effect.

        Design: Difficulty/compensating_invariant/appointment_cancel_compensates_report_schedule_pointer
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        dealer = create_dealer(name="Capitol Chevrolet", region_code="TX", capacity=3)
        rep = create_diagnostic_report(
            vehicle, odometer_km=41000, engine_hours=1610,
            dtc_codes=["P0300"], oil_life_pct=20,
        )
        ap = create_requested_appointment(dealer, vehicle, rep, "2026-09-16")
        cancelled = validate_success(
            api.cancel_appointment(dealer["id"], ap["id"], DEALER_SVC)
        )
        assert cancelled["status"] == "CANCELLED"
        rep_after = get_success_data(
            api.get_diagnostic_report(vehicle["id"], rep["id"], DEALER_SVC)
        )
        assert rep_after["status"] == "GENERATED"

    def test_dealer_capacity_aggregate_validation_at_confirm(self, api):
        """PRD §3.6: a dealer with capacity 1 and 1 confirmed appointment on
        that day rejects the next confirm with ERR_DEALER_CAPACITY_REACHED

        Design: Corner/validations/dealer_capacity_aggregate_validation_at_confirm
        """
        _, _, account, vehicle, _ = setup_account_scenario()
        dealer = create_dealer(name="Capitol Chevrolet", region_code="TX", capacity=1)
        rep1 = create_diagnostic_report(
            vehicle, odometer_km=30000, engine_hours=1200,
            dtc_codes=["P0300"], oil_life_pct=50,
        )
        rep2 = create_diagnostic_report(
            vehicle, odometer_km=30010, engine_hours=1201,
            dtc_codes=["P0301"], oil_life_pct=50,
        )
        ap1 = create_requested_appointment(dealer, vehicle, rep1, "2026-09-10")
        ap2 = create_requested_appointment(dealer, vehicle, rep2, "2026-09-10")
        validate_success(api.confirm_appointment(dealer["id"], ap1["id"], DEALER_SVC))
        resp = api.confirm_appointment(dealer["id"], ap2["id"], DEALER_SVC)
        validate_error(resp, ApiErrorId.ERR_DEALER_CAPACITY_REACHED)
        ap2_after = get_success_data(
            api.get_service_appointment(ap2["id"], DEALER_SVC)
        )
        assert ap2_after["status"] == "REQUESTED"
        rep2_after = get_success_data(
            api.get_diagnostic_report(vehicle["id"], rep2["id"], DEALER_SVC)
        )
        assert rep2_after["status"] == "GENERATED"
