"""Stolen-vehicle workflow: verification cascade, slowdown, recovery, SoD."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_account_headers,
    make_law_enforcement_headers,
    make_emergency_operator_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_account_scenario,
    create_zone,
    create_account,
    create_vehicle,
    create_trial_subscription,
    create_tier,
    report_stolen_case,
    verify_stolen_case,
    arm_slowdown,
    execute_slowdown,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


class TestStolenVehicleCascade:
    def test_verify_cascades_vehicle_and_arms_slowdown_eligibility(self, api):
        """PRD §3.4: Successful verification moves the case from REPORTED to
        VERIFIED, records the verifier's identity in verified_by_user_id, and
        cascades to the vehicle, moving it from ACTIVE to STOLEN_REPORTED —
        this cascade is what arms slowdown eligibility downstream.

        Design: Difficulty/transitive_cascade/stolen_verify_to_recovery_restores_vehicle_chain
        """
        _, _, account, vehicle, _ = setup_account_scenario(hardware_generation=5)
        case = report_stolen_case(
            vehicle, reporter_id="le-officer-1",
            police_report_number="TX-2026-0001", reporting_agency="Austin PD",
        )
        verified = verify_stolen_case(vehicle, case, verifier_id="le-officer-2")
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "le-officer-2"
        veh = get_success_data(api.get_vehicle(vehicle["id"], ADMIN))
        assert veh["status"] == "STOLEN_REPORTED", (
            f"verify must cascade to the vehicle, got {veh['status']}"
        )
        armed = arm_slowdown(vehicle, case)
        assert armed["status"] == "SLOWDOWN_ARMED"

    def test_arm_slowdown_before_verify_rejected_and_state_untouched(self, api):
        """PRD §3.4: the case is in VERIFIED (law-enforcement verification must
        precede any slowdown; an attempt against an unverified case is
        rejected with ERR_SLOWDOWN_NOT_VERIFIED)

        Design: Difficulty/transitive_cascade/stolen_verify_to_recovery_restores_vehicle_chain
        """
        _, _, account, vehicle, _ = setup_account_scenario(hardware_generation=5)
        case = report_stolen_case(
            vehicle, reporter_id="le-officer-1",
            police_report_number="TX-2026-0002", reporting_agency="Austin PD",
        )
        resp = api.arm_slowdown(
            vehicle["id"], case["id"], make_emergency_operator_headers("eo-ops-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SLOWDOWN_NOT_VERIFIED)
        after = get_success_data(
            api.get_stolen_case(vehicle["id"], case["id"],
                                make_law_enforcement_headers("le-officer-1"))
        )
        assert after["status"] == "REPORTED"


class TestSlowdownRecoveryCompensation:
    def test_full_slowdown_cycle_restores_vehicle_operability(self, api):
        """PRD §3.4: From SLOWDOWN_EXECUTED, closing as recovered moves the
        case to the terminal CLOSED_RECOVERED and cascades to the vehicle,
        restoring it from STOLEN_REPORTED to RECOVERED.
        PRD §3.1: the account may then update the vehicle from RECOVERED back
        to ACTIVE

        Design: Difficulty/compensating_invariant/vehicle_operability_restored_after_recovery_compensation
        """
        _, _, account, vehicle, _ = setup_account_scenario(hardware_generation=5)
        case = report_stolen_case(
            vehicle, reporter_id="le-officer-1",
            police_report_number="TX-2026-0042", reporting_agency="Austin PD",
        )
        verify_stolen_case(vehicle, case, verifier_id="le-officer-2")
        arm_slowdown(vehicle, case)
        executed = execute_slowdown(vehicle, case)
        assert executed["status"] == "SLOWDOWN_EXECUTED"
        assert executed["slowdown_executed_at"] is not None
        mid = get_success_data(api.get_vehicle(vehicle["id"], ADMIN))
        assert mid["status"] == "STOLEN_REPORTED"

        resp = api.close_case_recovered(
            vehicle["id"], case["id"], make_law_enforcement_headers("le-officer-2"),
        )
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED_RECOVERED"
        recovered = get_success_data(api.get_vehicle(vehicle["id"], ADMIN))
        assert recovered["status"] == "RECOVERED"

        headers = make_account_headers(account["id"])
        resp = api.update_vehicle(vehicle["id"], {"status": "ACTIVE"}, headers)
        restored = validate_success(resp)
        assert restored["status"] == "ACTIVE"
        history = get_success_data(
            api.get_stolen_case(vehicle["id"], case["id"],
                                make_law_enforcement_headers("le-officer-2"))
        )
        assert history["slowdown_executed_at"] is not None, (
            "compensation must not erase the execution timestamp"
        )

    def test_close_recovered_from_verified_also_restores_vehicle(self, api):
        """PRD §3.4: From VERIFIED, closing as recovered — when the vehicle was
        located before any slowdown — also moves the case to CLOSED_RECOVERED
        and performs the same vehicle restoration cascade.

        Design: Difficulty/compensating_invariant/vehicle_operability_restored_after_recovery_compensation
        """
        _, _, account, vehicle, _ = setup_account_scenario(hardware_generation=5)
        case = report_stolen_case(
            vehicle, reporter_id="le-officer-1",
            police_report_number="TX-2026-0055", reporting_agency="Austin PD",
        )
        verify_stolen_case(vehicle, case, verifier_id="le-officer-2")
        assert get_success_data(api.get_vehicle(vehicle["id"], ADMIN))["status"] == "STOLEN_REPORTED"
        resp = api.close_case_recovered(
            vehicle["id"], case["id"], make_law_enforcement_headers("le-officer-2"),
        )
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED_RECOVERED"
        assert get_success_data(api.get_vehicle(vehicle["id"], ADMIN))["status"] == "RECOVERED"


class TestSegregationOfDuties:
    def test_same_officer_verify_rejected(self, api):
        """PRD §3.4: the verifier's X-User-ID must differ from the reporter's
        recorded X-User-ID. A verification attempt where the two identifiers
        coincide is rejected with ERR_SEGREGATION_OF_DUTIES.

        Design: Corner/errors/same_officer_verify_rejected_by_segregation_of_duties
        """
        _, _, account, vehicle, _ = setup_account_scenario(hardware_generation=5)
        case = report_stolen_case(
            vehicle, reporter_id="le-officer-1",
            police_report_number="TX-2026-0009", reporting_agency="Austin PD",
        )
        resp = api.verify_stolen_case(
            vehicle["id"], case["id"], make_law_enforcement_headers("le-officer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_success_data(
            api.get_stolen_case(vehicle["id"], case["id"],
                                make_law_enforcement_headers("le-officer-2"))
        )
        assert after["status"] == "REPORTED"
        assert after["verified_by_user_id"] is None
        veh = get_success_data(api.get_vehicle(vehicle["id"], ADMIN))
        assert veh["status"] == "ACTIVE"

    def test_verify_and_arm_structurally_segregated_by_role(self, api):
        """PRD §3.4: Arming slowdown is performed by an EmergencyOperator —
        never by the verifying officer
        PRD §2.1: Any attempt to invoke an operation outside the caller's
        role — or, for an entity-backed role, to act on a resource owned by
        another principal — is rejected with ERR_UNAUTHORIZED (HTTP 403).

        Design: Corner/roles/segregation_of_duties_between_verifier_and_slowdown_operator
        """
        _, _, account, vehicle, _ = setup_account_scenario(hardware_generation=5)
        case = report_stolen_case(
            vehicle, reporter_id="le-officer-1",
            police_report_number="TX-2026-0011", reporting_agency="Austin PD",
        )
        # Arm by EmergencyOperator on an unverified case: order-of-operations.
        resp = api.arm_slowdown(
            vehicle["id"], case["id"], make_emergency_operator_headers("eo-ops-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SLOWDOWN_NOT_VERIFIED)
        # Verify by EmergencyOperator: role boundary enforces segregation.
        resp = api.verify_stolen_case(
            vehicle["id"], case["id"], make_emergency_operator_headers("eo-ops-1"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = get_success_data(
            api.get_stolen_case(vehicle["id"], case["id"],
                                make_law_enforcement_headers("le-officer-1"))
        )
        assert after["status"] == "REPORTED"

    def test_law_enforcement_cannot_arm_slowdown(self, api):
        """PRD §2.1: Any attempt to invoke an operation outside the caller's
        role — or, for an entity-backed role, to act on a resource owned by
        another principal — is rejected with ERR_UNAUTHORIZED (HTTP 403).
        PRD §3.4: Arming slowdown is performed by an EmergencyOperator

        Design: Corner/roles/law_enforcement_cannot_arm_slowdown
        """
        _, _, account, vehicle, _ = setup_account_scenario(hardware_generation=5)
        case = report_stolen_case(
            vehicle, reporter_id="le-officer-1",
            police_report_number="TX-2026-0010", reporting_agency="Austin PD",
        )
        verify_stolen_case(vehicle, case, verifier_id="le-officer-2")
        resp = api.arm_slowdown(
            vehicle["id"], case["id"], make_law_enforcement_headers("le-officer-3"),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = get_success_data(
            api.get_stolen_case(vehicle["id"], case["id"],
                                make_law_enforcement_headers("le-officer-2"))
        )
        assert after["status"] == "VERIFIED"


class TestValidationPriorityPairs:
    # NOTE: the cancelled-subscription + tier-lacking remote-command pairing is
    # intentionally not tested: the PRD names ERR_TIER_CAPABILITY_MISSING for
    # "a tier lacking remote-command entitlement" (§3.5) and never states that
    # a CANCELLED subscription on command creation is a priority-6
    # ERR_INVALID_STATE, so the asserted outcome is not uniquely derivable.

    def test_safety_gate_beats_coverage_on_arm_slowdown(self, api):
        """PRD §2.8: (7) safety gates on stolen-vehicle slowdown — verification
        precedes arming, generation-5 hardware present, cellular coverage in
        the vehicle's region, and reporter distinct from verifier — else the
        matching safety error
        PRD §2.8: (10) coverage and entitlement gates — cellular coverage
        dominates, emergency entitlement, tier capability flags, emergency-only
        command restriction
        PRD §2.8: Later rules are consulted only after all earlier rules pass.

        Design: Difficulty/priority_pair_validation_conflict/safety_gate_beats_temporal_window_on_stolen_case
        """
        create_tier(code="SAFETY")
        create_zone(region_code="NM", has_cellular=False,
                    supports_data=False, supports_navigation=False)
        account = create_account(
            full_name="Fay Flores", email="fay@example.com",
            phone="+15125550106", home_region_code="NM",
        )
        vehicle = create_vehicle(account, region_code="NM", hardware_generation=5)
        create_trial_subscription(account, vehicle, "SAFETY")
        case = report_stolen_case(
            vehicle, reporter_id="le-officer-3",
            police_report_number="NM-2026-0007", reporting_agency="Santa Fe PD",
        )
        resp = api.arm_slowdown(
            vehicle["id"], case["id"], make_emergency_operator_headers("eo-ops-1"),
        )
        err = validate_error(resp, ApiErrorId.ERR_SLOWDOWN_NOT_VERIFIED)
        assert err["error_id"] != "ERR_NO_CELLULAR_COVERAGE"
        after = get_success_data(
            api.get_stolen_case(vehicle["id"], case["id"],
                                make_law_enforcement_headers("le-officer-3"))
        )
        assert after["status"] == "REPORTED"

    def test_unverified_case_rejected_even_with_full_coverage(self, api):
        """PRD §3.4: the case is in VERIFIED (law-enforcement verification must
        precede any slowdown; an attempt against an unverified case is
        rejected with ERR_SLOWDOWN_NOT_VERIFIED)

        Design: Difficulty/priority_pair_validation_conflict/safety_gate_beats_temporal_window_on_stolen_case
        """
        # Same safety gate but with cellular coverage satisfied: the safety
        # error is the sole applicable failure, isolating the gate.
        _, _, account, vehicle, _ = setup_account_scenario(hardware_generation=5)
        case = report_stolen_case(
            vehicle, reporter_id="le-officer-1",
            police_report_number="TX-2026-0077", reporting_agency="Austin PD",
        )
        resp = api.arm_slowdown(
            vehicle["id"], case["id"], make_emergency_operator_headers("eo-ops-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SLOWDOWN_NOT_VERIFIED)
        after = get_success_data(
            api.get_stolen_case(vehicle["id"], case["id"],
                                make_law_enforcement_headers("le-officer-1"))
        )
        assert after["status"] == "REPORTED"
