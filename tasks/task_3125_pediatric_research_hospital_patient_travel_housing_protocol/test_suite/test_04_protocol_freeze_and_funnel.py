"""Queue A — the freeze cascade, OCC guards, screening fees and the funnel cascade."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fund, create_open_protocol, create_facility, create_referral,
    screen_referral, arrive_referral, sign_consent, create_hold_payload,
    setup_fund_and_open_protocol, open_protocol_with_reservations,
    set_clock, TEST_USERS, ApiErrorId,
    current_protocol_version,
)


class TestProtocolFreezeCycle:

    def _protocol_with_acceptance(self):
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)
        referral = create_referral(protocol["id"], is_immunosuppressed=True)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert screened["status"] == "ACCEPTED"
        return fund, protocol, referral, screened

    def test_raise_then_release_returns_the_protocol_to_open(self, logical_clock):
        """PRD §3.9: "A successful release stamps `released_at` from the logical
        clock and refreshes the hold's recorded `protocol_version` to the host
        protocol's current version."
        PRD §3.9: "The protocol's `is_protocol_held` flag is set false, and the
        protocol returns to `OPEN` only if no other `ACTIVE` hold remains on it"

        Design: Difficulty/non_linear_state_machine/non_linear_protocol_hold_cycle_with_asymmetric_thaw
        """
        fund, protocol, referral, screened = self._protocol_with_acceptance()

        hold = validate_success(api_client.raise_hold(
            protocol["id"], create_hold_payload(hold_reason="IRB_REVIEW"),
            TEST_USERS["irb_reviewer_headers"]), 201)
        held = get_success_data(api_client.get_protocol(protocol["id"], TEST_USERS["any_headers"]))
        assert held["status"] == "HELD"
        assert held["is_protocol_held"] is True

        released_hold = validate_success(api_client.release_hold(
            hold["id"], TEST_USERS["protocol_coordinator_headers"]), 200)
        assert released_hold["status"] == "RELEASED"

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["status"] == "OPEN"
        assert protocol_after["is_protocol_held"] is False

    def test_thaw_does_not_restore_the_acceptance(self, logical_clock):
        """PRD §3.9: "That revert is unconditional on acceptance and costs
        nothing: those reverts charge no screening fee and advance no budget."
        PRD §3.9: "each reverted referral has its `reservation_basis_cents`
        subtracted from the protocol's `reserved_cents` and then reset to zero,
        and `is_budget_saturated` is recomputed."

        Design: Difficulty/non_linear_state_machine/non_linear_protocol_hold_cycle_with_asymmetric_thaw
        """
        fund, protocol, referral, screened = self._protocol_with_acceptance()
        assert screened["reservation_basis_cents"] == 1_250_000

        hold = validate_success(api_client.raise_hold(
            protocol["id"], create_hold_payload(hold_reason="IRB_REVIEW"),
            TEST_USERS["irb_reviewer_headers"]), 201)
        validate_success(api_client.release_hold(
            hold["id"], TEST_USERS["protocol_coordinator_headers"]), 200)

        referral_after = get_success_data(api_client.get_referral(
            referral["id"], TEST_USERS["any_headers"]))
        assert referral_after["status"] == "SUBMITTED"
        assert referral_after["applied_tier"] == "PENDING"
        assert referral_after["reservation_basis_cents"] == 0

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["reserved_cents"] == 0


class TestFreezeRevertsAndReleasesReservations:

    def test_hold_reverts_three_accepted_referrals(self, logical_clock):
        """PRD §3.9: "every referral on that protocol currently in `ACCEPTED`
        status reverts to `SUBMITTED` with its `applied_tier` reset to
        `PENDING`."

        Design: Difficulty/transitive_cascade/cascade_hold_freeze_reverts_and_releases_reservation
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
        create_facility(facility_code="ONC-01", total_beds=12, buffer_beds=0)

        accepted = []
        for index in range(3):
            referral = create_referral(protocol["id"], child_name=f"Seed {index + 1}",
                                       is_immunosuppressed=True)
            posture = get_success_data(api_client.get_funding_posture(
                protocol["id"], TEST_USERS["any_headers"]))
            accepted.append(validate_success(api_client.screen_referral(
                referral["id"], {"expected_protocol_version": posture["protocol_version"]},
                TEST_USERS["intake_coordinator_headers"]), 200))

        before = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        assert before["reserved_cents"] == 3_750_000

        validate_success(api_client.raise_hold(
            protocol["id"], create_hold_payload(hold_reason="SAFETY_SIGNAL"),
            TEST_USERS["irb_reviewer_headers"]), 201)

        after = get_success_data(api_client.get_protocol(protocol["id"], TEST_USERS["any_headers"]))
        assert after["status"] == "HELD"
        assert after["is_protocol_held"] is True
        assert after["reserved_cents"] == 0
        assert after["available_cents"] == 10_000_000
        assert after["is_budget_saturated"] is False

    def test_reverted_referrals_keep_no_reservation_basis(self, logical_clock):
        """PRD §2.12: "While a hold is active the protocol's `is_protocol_held`
        flag is true."
        PRD §3.9: "An accepted screen is therefore not a durable claim on a bed
        or a budget while a hold is in the air."

        Design: Difficulty/transitive_cascade/cascade_hold_freeze_reverts_and_releases_reservation
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
        create_facility(facility_code="ONC-01", total_beds=12, buffer_beds=0)

        referrals = []
        for index in range(3):
            referral = create_referral(protocol["id"], child_name=f"Seed {index + 1}",
                                       is_immunosuppressed=True)
            posture = get_success_data(api_client.get_funding_posture(
                protocol["id"], TEST_USERS["any_headers"]))
            screen_referral(referral["id"], posture["protocol_version"])
            referrals.append(referral)

        validate_success(api_client.raise_hold(
            protocol["id"], create_hold_payload(hold_reason="SAFETY_SIGNAL"),
            TEST_USERS["irb_reviewer_headers"]), 201)

        for referral in referrals:
            row = get_success_data(api_client.get_referral(referral["id"], TEST_USERS["any_headers"]))
            assert row["status"] == "SUBMITTED"
            assert row["reservation_basis_cents"] == 0


class TestScreenReservationSaturationCascade:

    def test_eighth_acceptance_crosses_into_saturation(self, logical_clock):
        """PRD §2.5: "A protocol is flagged `is_budget_saturated` once
        `available_cents` is above zero but no larger than three point seven
        five percent of the protocol budget, rounded up to the next whole cent."

        Design: Difficulty/transitive_cascade/cascade_oncampus_screen_reservation_saturation
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
        create_facility(facility_code="ONC-01", total_beds=12, buffer_beds=0)

        for index in range(7):
            referral = create_referral(protocol["id"], child_name=f"Seed {index + 1}",
                                       is_immunosuppressed=True)
            posture = get_success_data(api_client.get_funding_posture(
                protocol["id"], TEST_USERS["any_headers"]))
            screen_referral(referral["id"], posture["protocol_version"])

        before = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        assert before["reserved_cents"] == 8_750_000
        assert before["is_budget_saturated"] is False

        last = create_referral(protocol["id"], child_name="Ava Reyes", is_immunosuppressed=True)
        last_screened = validate_success(api_client.screen_referral(
            last["id"], {"expected_protocol_version": before["protocol_version"]},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert last_screened["status"] == "ACCEPTED"

        after = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        assert after["is_budget_saturated"] is True

    def test_eighth_acceptance_reservation_moves_the_counters(self, logical_clock):
        """PRD §3.2: "that amount is added to `reserved_cents`, and
        `is_budget_saturated` is recomputed."

        Design: Difficulty/transitive_cascade/cascade_oncampus_screen_reservation_saturation
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
        create_facility(facility_code="ONC-01", total_beds=12, buffer_beds=0)

        for index in range(7):
            referral = create_referral(protocol["id"], child_name=f"Seed {index + 1}",
                                       is_immunosuppressed=True)
            posture = get_success_data(api_client.get_funding_posture(
                protocol["id"], TEST_USERS["any_headers"]))
            screen_referral(referral["id"], posture["protocol_version"])

        last = create_referral(protocol["id"], child_name="Ava Reyes", is_immunosuppressed=True)
        posture = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        last_screened = validate_success(api_client.screen_referral(
            last["id"], {"expected_protocol_version": posture["protocol_version"]},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert last_screened["reservation_basis_cents"] == 1_250_000

        after = get_success_data(api_client.get_protocol(protocol["id"], TEST_USERS["any_headers"]))
        assert after["reserved_cents"] == 10_000_000
        assert after["available_cents"] == 0


class TestSaturationFlagReconcilesBothWays:

    def test_saturation_flips_off_when_a_hold_releases_reservations(self, logical_clock):
        """PRD §2.12: "While a protocol is frozen — by an active hold or by a
        review lock — the screen, arrival, consent signing, arm-assent recording,
        milestone deferral, and milestone execution operations are all refused
        with `ERR_PROTOCOL_HELD` (HTTP 409)"

        Design: Difficulty/derived_field_reconciliation/derived_saturation_flag_reconciles_in_both_directions
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
        create_facility(facility_code="ONC-01", total_beds=12, buffer_beds=0)

        for index in range(8):
            referral = create_referral(protocol["id"], child_name=f"Seed {index + 1}",
                                       is_immunosuppressed=True)
            posture = get_success_data(api_client.get_funding_posture(
                protocol["id"], TEST_USERS["any_headers"]))
            screen_referral(referral["id"], posture["protocol_version"])

        saturated = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        assert saturated["is_budget_saturated"] is True

        validate_success(api_client.raise_hold(
            protocol["id"], create_hold_payload(hold_reason="IRB_REVIEW"),
            TEST_USERS["irb_reviewer_headers"]), 201)

        after = get_success_data(api_client.get_protocol(protocol["id"], TEST_USERS["any_headers"]))
        assert after["reserved_cents"] == 0
        assert after["available_cents"] == 10_000_000
        assert after["is_budget_saturated"] is False

    def test_saturation_tracks_available_not_reserved(self, logical_clock):
        """PRD §2.5: "The flag is recomputed after every event that touches the
        counters."

        Design: Difficulty/derived_field_reconciliation/derived_saturation_flag_reconciles_in_both_directions
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
        create_facility(facility_code="ONC-01", total_beds=12, buffer_beds=0)

        for index in range(7):
            referral = create_referral(protocol["id"], child_name=f"Seed {index + 1}",
                                       is_immunosuppressed=True)
            posture = get_success_data(api_client.get_funding_posture(
                protocol["id"], TEST_USERS["any_headers"]))
            screen_referral(referral["id"], posture["protocol_version"])

        at_seven = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        assert at_seven["available_cents"] == 1_250_000
        assert at_seven["is_budget_saturated"] is False

        eighth = create_referral(protocol["id"], child_name="Ava Reyes", is_immunosuppressed=True)
        screen_referral(eighth["id"], at_seven["protocol_version"])

        at_eight = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        assert at_eight["available_cents"] == 0
        assert at_eight["is_budget_saturated"] is True


class TestOccupancyNotStarted:

    def test_activation_before_the_start_instant_is_refused(self, logical_clock):
        """PRD §3.4: "`start_at` must not be later than the logical clock, or it
        reports `ERR_OCCUPANCY_NOT_STARTED` (HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_precondition_beats_business_safety
        """
        set_clock()
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
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

        booking = validate_success(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-20T00:00:00Z",
             "end_at": "2026-09-27T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]), 201)

        res = api_client.activate_assignment(
            booking["id"], TEST_USERS["housing_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_OCCUPANCY_NOT_STARTED)

        unchanged = get_success_data(api_client.get_assignment(
            booking["id"], TEST_USERS["any_headers"]))
        assert unchanged["status"] == "SCHEDULED"
        assert unchanged["start_at"] == "2026-09-20T00:00:00Z"

    def test_rebooking_an_active_assignment_is_refused(self, logical_clock):
        """PRD §3.4: "A re-booking replaces the window, recomputes
        `housing_cost_cents`, re-runs both gates, and advances the enrollment's
        version by one."

        Design: Difficulty/priority_pair_validation_conflict/conflict_state_precondition_beats_business_safety
        """
        set_clock()
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
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

        booking = validate_success(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]), 201)
        validate_success(api_client.activate_assignment(
            booking["id"], TEST_USERS["housing_coordinator_headers"]), 200)

        res = api_client.rebook_assignment(
            booking["id"],
            {"start_at": "2026-09-20T00:00:00Z", "end_at": "2026-09-27T00:00:00Z"},
            TEST_USERS["housing_coordinator_headers"],
        )
        assert res.status_code == 409
        error_data = res.json()["data"]
        assert error_data["error_id"] == ApiErrorId.ERR_INVALID_STATE
        assert error_data["error_id"] != ApiErrorId.ERR_STEP_DOWN_NOT_PERMITTED
        assert error_data["error_id"] != ApiErrorId.ERR_HOUSING_IMMUNOSUPPRESSION_INCOMPATIBLE


class TestScreenPriorityCapacityOverBudget:

    def test_full_residence_is_reported_ahead_of_an_exhausted_budget(self, logical_clock):
        """PRD §3.2: "Capacity comes next: the protocol's `enrolled_count` must
        be strictly below its `capacity`, else `ERR_PROTOCOL_CAPACITY_EXCEEDED`
        (HTTP 409). Budget comes last: the protocol's `available_cents` must be
        strictly above zero, else `ERR_PROTOCOL_BUDGET_EXHAUSTED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/conflict_capacity_gate_beats_fiscal_gate
        """
        set_clock()
        fund = create_fund()
        protocol = get_success_data(api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-TIGHT-002", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 1_000_000, "capacity": 8},
            TEST_USERS["protocol_coordinator_headers"]))
        protocol = get_success_data(api_client.open_protocol(
            protocol["id"], TEST_USERS["protocol_coordinator_headers"]))
        create_facility(facility_code="ONC-T01", name="Single Bed Campus",
                        tier="ON_CAMPUS", total_beds=1, buffer_beds=0)

        first = create_referral(protocol["id"], child_name="Ava Reyes", is_immunosuppressed=True)
        first_screened = validate_success(api_client.screen_referral(
            first["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert first_screened["reservation_basis_cents"] == 125_000

        second = create_referral(protocol["id"], child_name="Noah Patel", is_immunosuppressed=True)
        posture = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        res = api_client.screen_referral(
            second["id"], {"expected_protocol_version": posture["protocol_version"]},
            TEST_USERS["intake_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_HOUSING_CAPACITY_EXCEEDED)

    def test_rejected_screen_still_charges_the_fee_and_writes_nothing_else(self, logical_clock):
        """PRD §3.2: "this fee is charged on every screen attempt, accepted or
        declined alike; it never moves the protocol's `available_cents` and it is
        never refunded."
        PRD §3.2: "A budget failure records no accrual on the protocol at all,
        and a declined referral books no reservation; `reservation_basis_cents`
        is left at zero and `reserved_cents` untouched."

        Design: Difficulty/priority_pair_validation_conflict/conflict_capacity_gate_beats_fiscal_gate
        """
        set_clock()
        fund = create_fund()
        protocol = get_success_data(api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-TIGHT-002", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 1_000_000, "capacity": 8},
            TEST_USERS["protocol_coordinator_headers"]))
        protocol = get_success_data(api_client.open_protocol(
            protocol["id"], TEST_USERS["protocol_coordinator_headers"]))
        create_facility(facility_code="ONC-T01", name="Single Bed Campus",
                        tier="ON_CAMPUS", total_beds=1, buffer_beds=0)

        first = create_referral(protocol["id"], child_name="Ava Reyes", is_immunosuppressed=True)
        validate_success(api_client.screen_referral(
            first["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)

        second = create_referral(protocol["id"], child_name="Noah Patel", is_immunosuppressed=True)
        posture = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        res = api_client.screen_referral(
            second["id"], {"expected_protocol_version": posture["protocol_version"]},
            TEST_USERS["intake_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_HOUSING_CAPACITY_EXCEEDED)

        declined = get_success_data(api_client.get_referral(second["id"], TEST_USERS["any_headers"]))
        assert declined["screening_fee_cents"] == 100_000
        assert declined["reservation_basis_cents"] == 0
        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["reserved_cents"] == 125_000


class TestScreeningFeeBoundaries:

    def test_zero_coverage_charges_no_fee(self, logical_clock):
        """PRD §3.2: "It recomputes `screening_fee_cents` as one fortieth of the
        `insurance_coverage_cents` — the ceiling of two and a half percent of
        that coverage"

        Design: Difficulty/boundary_precision_check/boundary_screening_fee_at_the_cent
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="PTB-01", tier="PARTNER_CLASS_B",
                        total_beds=6, buffer_beds=0)

        referral = create_referral(protocol["id"], child_name="Ava Reyes",
                                   expected_treatment_days=200,
                                   is_immunosuppressed=False, insurance_coverage_cents=0)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert screened["screening_fee_cents"] == 0
        assert screened["status"] == "ACCEPTED"

    def test_fee_ceiling_is_exact_at_the_cent(self, logical_clock):
        """PRD §3.2: "An accepted screen does five things at once. It moves the
        referral to `ACCEPTED`."

        Design: Difficulty/boundary_precision_check/boundary_screening_fee_at_the_cent
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="PTB-01", tier="PARTNER_CLASS_B",
                        total_beds=6, buffer_beds=0)

        referral = create_referral(protocol["id"], child_name="Noah Patel",
                                   expected_treatment_days=200,
                                   is_immunosuppressed=False,
                                   insurance_coverage_cents=9_999_999)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert screened["screening_fee_cents"] == 250_000
        assert screened["screening_fee_cents"] not in (249_999, 250_001)
        assert screened["status"] == "ACCEPTED"

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["reserved_cents"] == 625_000