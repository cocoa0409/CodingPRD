"""Queue A — the operations checkpoint, ledger freezing, sibling windows and
the conserved travel pair."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fund, create_open_protocol, create_facility, create_referral,
    screen_referral, arrive_referral, sign_consent, create_pledge,
    setup_three_tiered_ledgers, setup_fund_and_open_protocol,
    set_clock, TEST_USERS, ApiErrorId,
    current_protocol_version,
)


class TestCheckpointThreshold:

    def test_only_a_strictly_over_cap_ledger_is_frozen(self, logical_clock):
        """PRD §3.10: "it advances every ledger's `ledger_epoch` to a supplied
        `advance_to_epoch` and freezes every ledger whose `accumulated_cents`
        exceeds its service's `stimulation_cap_cents`, reporting back the
        resulting `ledger_epoch` and a `frozen_ledger_count`."

        Design: Difficulty/rate_threshold_trigger/threshold_checkpoint_freezes_only_strictly_over_cap_ledgers
        """
        set_clock()
        fund = create_fund()
        service_a, service_b, service_c, ledger_a, ledger_b, ledger_c = (
            setup_three_tiered_ledgers(fund))

        result = validate_success(api_client.run_checkpoint(
            {"advance_to_epoch": 1}, TEST_USERS["platform_admin_headers"]), 200)
        assert result["ledger_epoch"] == 1
        assert result["frozen_ledger_count"] == 1

        ledger_c_after = get_success_data(api_client.get_ledger(
            ledger_c, TEST_USERS["any_headers"]))
        assert ledger_c_after["status"] == "FROZEN"

    def test_a_ledger_exactly_on_the_cap_survives_the_run(self, logical_clock):
        """PRD §3.10: "The stimulation markup is the base allowance multiplied
        by the service's `stimulation_rate`, rounded half up to the cent, capped
        at the service's `stimulation_cap_cents`."

        Design: Difficulty/rate_threshold_trigger/threshold_checkpoint_freezes_only_strictly_over_cap_ledgers
        """
        set_clock()
        fund = create_fund()
        service_a, service_b, service_c, ledger_a, ledger_b, ledger_c = (
            setup_three_tiered_ledgers(fund))

        validate_success(api_client.run_checkpoint(
            {"advance_to_epoch": 1}, TEST_USERS["platform_admin_headers"]), 200)

        ledger_a_after = get_success_data(api_client.get_ledger(ledger_a, TEST_USERS["any_headers"]))
        assert ledger_a_after["status"] == "ACTIVE"
        assert ledger_a_after["accumulated_cents"] == 20_000

        ledger_b_after = get_success_data(api_client.get_ledger(ledger_b, TEST_USERS["any_headers"]))
        assert ledger_b_after["status"] == "ACTIVE"
        assert ledger_b_after["accumulated_cents"] == 40_000
        assert ledger_b_after["ledger_epoch"] == 1


class TestFrozenLedgerMarkup:

    def test_freeze_stops_the_markup_but_not_the_base_allowance(self, logical_clock):
        """PRD §3.10: "The markup is contributed only when two conditions hold
        together: the service is `is_stimulation_eligible` and the ledger's
        status is `ACTIVE`."
        PRD §3.10: "in every case `ResearchFund.patient_support_balance_cents` is
        reduced by the allowance."

        Design: Difficulty/rate_threshold_trigger/threshold_freeze_blocks_markup_but_not_base_allowances
        """
        set_clock()
        fund = create_fund()
        service = get_success_data(api_client.create_service({
            "fund_id": fund["id"], "service_code": "MEALS", "display_name": "Meals",
            "base_allowance_cents": 20_000, "is_stimulation_eligible": True,
            "stimulation_rate": 0.3, "stimulation_cap_cents": 5_000,
        }, TEST_USERS["patient_support_officer_headers"]))
        first = validate_success(api_client.accrue_allowance(
            service["id"], {"family_count": 1},
            TEST_USERS["patient_support_officer_headers"]), 201)
        assert first["markup_cents"] == 5_000
        ledger_id = first["family_service_ledger_id"]

        frozen = validate_success(api_client.freeze_ledger(
            ledger_id, TEST_USERS["patient_support_officer_headers"]), 200)
        assert frozen["status"] == "FROZEN"

        second = validate_success(api_client.accrue_allowance(
            service["id"], {"family_count": 2},
            TEST_USERS["patient_support_officer_headers"]), 201)
        assert second["markup_cents"] == 0
        assert second["allowance_cents"] == 40_000

    def test_frozen_ledger_keeps_accumulating_and_debits_only_the_allowance(self, logical_clock):
        """PRD §3.10: "A `PatientSupportOfficer` can freeze a ledger, which moves
        it to `FROZEN` and pauses markup accrual on it"

        Design: Difficulty/rate_threshold_trigger/threshold_freeze_blocks_markup_but_not_base_allowances
        """
        set_clock()
        fund = create_fund()
        service = get_success_data(api_client.create_service({
            "fund_id": fund["id"], "service_code": "MEALS", "display_name": "Meals",
            "base_allowance_cents": 20_000, "is_stimulation_eligible": True,
            "stimulation_rate": 0.3, "stimulation_cap_cents": 5_000,
        }, TEST_USERS["patient_support_officer_headers"]))
        first = validate_success(api_client.accrue_allowance(
            service["id"], {"family_count": 1},
            TEST_USERS["patient_support_officer_headers"]), 201)
        ledger_id = first["family_service_ledger_id"]
        research_after_first = first["fund_research_balance_cents"]

        validate_success(api_client.freeze_ledger(
            ledger_id, TEST_USERS["patient_support_officer_headers"]), 200)
        second = validate_success(api_client.accrue_allowance(
            service["id"], {"family_count": 2},
            TEST_USERS["patient_support_officer_headers"]), 201)

        assert second["fund_research_balance_cents"] == research_after_first
        ledger_after = get_success_data(api_client.get_ledger(ledger_id, TEST_USERS["any_headers"]))
        assert ledger_after["accumulated_cents"] == 60_000
        assert ledger_after["status"] == "FROZEN"


class TestSiblingWindowLimit:

    def _pair(self):
        set_clock()
        fund = create_fund()
        protocol = get_success_data(api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-INT-001", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 10_000_000, "capacity": 8},
            TEST_USERS["protocol_coordinator_headers"]))
        protocol = get_success_data(api_client.open_protocol(
            protocol["id"], TEST_USERS["protocol_coordinator_headers"]))
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)

        households = {}
        for state, name, alias in (("TN", "Ava Reyes", "R-Sib"), ("MA", "Noah Patel", "P-Sib")):
            referral = create_referral(protocol["id"], child_name=name,
                                       household_state_code=state, is_immunosuppressed=True)
            screened = validate_success(api_client.screen_referral(
                referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
                TEST_USERS["intake_coordinator_headers"]), 200)
            arrived = arrive_referral(referral["id"], screened["version"])
            enrollment_id = arrived["enrollment_id"]
            validate_success(api_client.sign_consent(
                enrollment_id,
                {"consent_signer": "GUARDIAN_AND_CHILD",
                 "guardian_consent_signature_code": "GC-1001",
                 "child_assent_signature_code": "CA-1001"},
                TEST_USERS["intake_coordinator_headers"]), 200)
            booking = get_success_data(api_client.create_assignment(
                {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
                 "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
                TEST_USERS["housing_coordinator_headers"]))
            get_success_data(api_client.activate_assignment(
                booking["id"], TEST_USERS["housing_coordinator_headers"]))
            validate_success(api_client.start_treatment(
                enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)
            sibling = get_success_data(api_client.create_sibling_service(
                enrollment_id,
                {"sibling_alias": alias, "service_type": "SIBLING_CAMP",
                 "delivery_window_start_at": "2026-09-01T00:00:00Z",
                 "delivery_window_end_at": "2026-10-01T00:00:00Z"},
                TEST_USERS["patient_support_officer_headers"]))
            validate_success(api_client.deliver_sibling_sessions(
                sibling["id"], {"session_count": 3},
                TEST_USERS["patient_support_officer_headers"]), 200)
            households[state] = {"enrollment_id": enrollment_id,
                                 "assignment": booking, "sibling": sibling}
        return households

    def test_the_window_limit_is_state_dependent_and_inclusive(self, logical_clock):
        """PRD §3.10: "That allowance is 4 sessions when the household's
        `household_state_code` is one of the near states `TX`, `OK`, `AR`, `MS`,
        `AL`, `LA`, `TN`, `MO`, or `KY`, and 6 sessions otherwise; the boundary
        is inclusive at the limit"

        Design: Difficulty/boundary_precision_check/boundary_sibling_window_inclusive_at_state_dependent_modulus
        """
        households = self._pair()

        tn = validate_success(api_client.deliver_sibling_sessions(
            households["TN"]["sibling"]["id"], {"session_count": 1},
            TEST_USERS["patient_support_officer_headers"]), 200)
        assert tn["sessions_delivered"] == 4
        assert tn["has_reached_monthly_limit"] is True

        ma = validate_success(api_client.deliver_sibling_sessions(
            households["MA"]["sibling"]["id"], {"session_count": 1},
            TEST_USERS["patient_support_officer_headers"]), 200)
        assert ma["sessions_delivered"] == 4
        assert ma["has_reached_monthly_limit"] is False

    def test_the_counter_resets_when_the_occupancy_ends(self, logical_clock):
        """PRD §3.10: "The counter is cumulative within the window and resets to
        zero when the enrollment's housing occupancy ends — that reset is driven
        by the housing vacation path in §3.4, not by the sibling service itself."

        Design: Difficulty/boundary_precision_check/boundary_sibling_window_inclusive_at_state_dependent_modulus
        """
        households = self._pair()
        validate_success(api_client.deliver_sibling_sessions(
            households["TN"]["sibling"]["id"], {"session_count": 1},
            TEST_USERS["patient_support_officer_headers"]), 200)

        validate_success(api_client.vacate_assignment(
            households["TN"]["assignment"]["id"],
            {"vacated_reason": "TRANSFERRED_AFFILIATE"},
            TEST_USERS["housing_coordinator_headers"]), 200)

        sibling_after = get_success_data(api_client.get_sibling_service(
            households["TN"]["sibling"]["id"], TEST_USERS["any_headers"]))
        assert sibling_after["sessions_delivered"] == 0


class TestTravelPairInvariant:

    def test_reversal_restores_the_pool_and_the_ledger(self, logical_clock):
        """PRD §3.6: "The reversal takes a `reversal_reason`, refunds
        `ResearchFund.patient_support_balance_cents` by the leg's
        `transport_cost_cents`, reduces the protocol's `committed_cents` by the
        leg's research-day accrual, reduces the enrollment's pledge `covered_days`
        by the leg's billed days, resets `transport_cost_cents` to zero, advances
        the protocol's version, and ends the leg at `CANCELLED`."

        Design: Difficulty/compensating_invariant/invariant_travel_pair_conserves_the_family_support_pool
        """
        set_clock()
        fund = create_fund()
        protocol = get_success_data(api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-INT-001", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 10_000_000, "capacity": 8},
            TEST_USERS["protocol_coordinator_headers"]))
        protocol = get_success_data(api_client.open_protocol(
            protocol["id"], TEST_USERS["protocol_coordinator_headers"]))
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)

        referral = create_referral(protocol["id"], is_immunosuppressed=True)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])
        enrollment_id = arrived["enrollment_id"]
        validate_success(api_client.sign_consent(
            enrollment_id,
            {"consent_signer": "GUARDIAN_AND_CHILD",
             "guardian_consent_signature_code": "GC-1001",
             "child_assent_signature_code": "CA-1001"},
            TEST_USERS["intake_coordinator_headers"]), 200)
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        get_success_data(api_client.activate_assignment(
            booking["id"], TEST_USERS["housing_coordinator_headers"]))
        validate_success(api_client.start_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)
        create_pledge(enrollment_id, budget_cents=400_000)

        leg = get_success_data(api_client.request_travel(
            enrollment_id,
            {"mode": "AIR_ECONOMY", "traveler_count": 2,
             "departure_at": "2026-09-05T00:00:00Z", "return_at": "2026-09-12T00:00:00Z",
             "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True},
            TEST_USERS["patient_support_officer_headers"]))
        validate_success(api_client.confirm_travel(
            leg["id"], TEST_USERS["patient_support_officer_headers"]), 200)

        disbursed = validate_success(api_client.disburse_travel(
            leg["id"], TEST_USERS["patient_support_officer_headers"]), 200)
        # PRD §3.6: a 7-day leg for 2 travelers gives family_day_units 14, and a
        # TN household (near state) resolves to 15000 cents per traveler-day, so
        # transport_cost_cents is 14 * 15000.
        assert disbursed["transport_cost_cents"] == 210_000

        reversed_leg = validate_success(api_client.reverse_travel_disbursement(
            leg["id"], {"reversal_reason": "FAMILY_REQUEST"},
            TEST_USERS["patient_support_officer_headers"]), 200)
        assert reversed_leg["transport_cost_cents"] == 0
        assert reversed_leg["status"] == "CANCELLED"

    def test_the_conserved_quantities_return_to_their_starting_values(self, logical_clock):
        """PRD §3.6: "A leg exposes `fund_patient_support_balance_cents` and
        `fund_research_balance_cents` reflecting the fund after the leg was last
        disbursed or reversed."

        Design: Difficulty/compensating_invariant/invariant_travel_pair_conserves_the_family_support_pool
        """
        set_clock()
        fund = create_fund()
        protocol = get_success_data(api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-INT-001", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 10_000_000, "capacity": 8},
            TEST_USERS["protocol_coordinator_headers"]))
        protocol = get_success_data(api_client.open_protocol(
            protocol["id"], TEST_USERS["protocol_coordinator_headers"]))
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)

        pool_before = get_success_data(api_client.get_fund(
            fund["id"], TEST_USERS["any_headers"]))["patient_support_balance_cents"]

        referral = create_referral(protocol["id"], is_immunosuppressed=True)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])
        enrollment_id = arrived["enrollment_id"]
        validate_success(api_client.sign_consent(
            enrollment_id,
            {"consent_signer": "GUARDIAN_AND_CHILD",
             "guardian_consent_signature_code": "GC-1001",
             "child_assent_signature_code": "CA-1001"},
            TEST_USERS["intake_coordinator_headers"]), 200)
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        get_success_data(api_client.activate_assignment(
            booking["id"], TEST_USERS["housing_coordinator_headers"]))
        validate_success(api_client.start_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)
        create_pledge(enrollment_id, budget_cents=400_000)

        leg = get_success_data(api_client.request_travel(
            enrollment_id,
            {"mode": "AIR_ECONOMY", "traveler_count": 2,
             "departure_at": "2026-09-05T00:00:00Z", "return_at": "2026-09-12T00:00:00Z",
             "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True},
            TEST_USERS["patient_support_officer_headers"]))
        validate_success(api_client.confirm_travel(
            leg["id"], TEST_USERS["patient_support_officer_headers"]), 200)
        validate_success(api_client.disburse_travel(
            leg["id"], TEST_USERS["patient_support_officer_headers"]), 200)
        validate_success(api_client.reverse_travel_disbursement(
            leg["id"], {"reversal_reason": "FAMILY_REQUEST"},
            TEST_USERS["patient_support_officer_headers"]), 200)

        pool_after = get_success_data(api_client.get_fund(
            fund["id"], TEST_USERS["any_headers"]))["patient_support_balance_cents"]
        assert pool_after == pool_before

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["committed_cents"] == 0