"""Queue B — state machine corners and pinned calculation constants."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fund, create_open_protocol, create_facility, create_referral,
    screen_referral, arrive_referral, sign_consent, set_clock,
    TEST_USERS, ApiErrorId,
    current_protocol_version,
)


class TestReferralScreenStateMachine:

    def test_rescreening_a_declined_referral_is_refused(self, logical_clock):
        """PRD §3.2: "A referral that is not in `SUBMITTED` is refused with
        `ERR_REFERRAL_NOT_SUBMITTED` (HTTP 409)."

        Design: Corner/state_machines/sm_screen_from_declined_returns_invalid_state
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="PTB-01", tier="PARTNER_CLASS_B",
                        total_beds=6, buffer_beds=0)

        referral = create_referral(protocol["id"], child_name="Ava Reyes",
                                   child_date_of_birth="2008-09-01T00:00:00Z",
                                   expected_treatment_days=200, is_immunosuppressed=False)
        first = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert first["decline_reason"] == "ELIGIBILITY_AGE"
        assert first["status"] == "DECLINED"

        res = api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_REFERRAL_NOT_SUBMITTED)

        row = get_success_data(api_client.get_referral(referral["id"], TEST_USERS["any_headers"]))
        assert row["status"] == "DECLINED"
        assert row["applied_tier"] == "DECLINED"
        assert row["reservation_basis_cents"] == 0

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["reserved_cents"] == 0

    def test_arriving_the_same_referral_twice_creates_one_enrollment(self, logical_clock):
        """PRD §3.3: "It requires the referral to be `ACCEPTED` — otherwise
        `ERR_REFERRAL_NOT_ACCEPTED` (HTTP 409) — and the target protocol to be
        `OPEN` and not held, otherwise `ERR_PROTOCOL_NOT_OPEN` (HTTP 409)."

        Design: Corner/state_machines/sm_arriving_a_referral_twice_returns_invalid_state
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)
        referral = create_referral(protocol["id"], is_immunosuppressed=True)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)

        validate_success(api_client.arrive_referral(
            referral["id"], {"expected_referral_version": screened["version"]},
            TEST_USERS["intake_coordinator_headers"]), 200)

        current = get_success_data(api_client.get_referral(referral["id"], TEST_USERS["any_headers"]))
        res = api_client.arrive_referral(
            referral["id"], {"expected_referral_version": current["version"]},
            TEST_USERS["intake_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_REFERRAL_NOT_ACCEPTED)

        enrollments = validate_success(api_client.list_referral_enrollments(
            referral["id"], TEST_USERS["any_headers"]), 200)
        assert len(enrollments) == 1

        row = get_success_data(api_client.get_referral(referral["id"], TEST_USERS["any_headers"]))
        assert row["status"] == "ARRIVED"

    def test_withdrawing_a_declined_referral_is_refused(self, logical_clock):
        """PRD §3.2: "Any withdrawal from a state that is not one of the three
        reports `ERR_REFERRAL_NOT_SUBMITTED`."

        Design: Corner/state_machines/sm_withdrawing_a_declined_referral_returns_invalid_state
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)

        referral = create_referral(protocol["id"], child_name="Ava Reyes",
                                   disease_stage="RELAPSED", is_immunosuppressed=False)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert screened["decline_reason"] == "ELIGIBILITY_STAGE"

        res = api_client.withdraw_referral(
            referral["id"], {"withdrawal_reason": "FAMILY_RELOCATION"},
            TEST_USERS["intake_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_REFERRAL_NOT_SUBMITTED)

        row = get_success_data(api_client.get_referral(referral["id"], TEST_USERS["any_headers"]))
        assert row["status"] == "DECLINED"
        assert row["decline_reason"] == "ELIGIBILITY_STAGE"
        assert row["decline_occurred_at"] is not None


class TestFamilyDayChargeConstants:

    def test_far_state_settlement_uses_the_tier_rate(self, logical_clock):
        """PRD §3.5: "a family from `CA`, `NY`, `IL`, `WA`, `MA`, `NJ`, `CT`,
        `OR`, or `MD` resolves to 22000 cents per day"

        Design: Corner/calculations/calc_final_family_day_charge_far_state_rate
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

        referral = create_referral(protocol["id"], child_name="Noah Patel",
                                   household_state_code="MA", is_immunosuppressed=True)
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
        pledge = get_success_data(api_client.create_pledge(
            {"enrollment_id": enrollment_id, "patient_support_budget_cents": 12_000},
            TEST_USERS["patient_support_officer_headers"]))
        validate_success(api_client.accrue_pledge(
            pledge["id"], {"days": 4}, TEST_USERS["patient_support_officer_headers"]), 200)
        validate_success(api_client.hiatus(
            enrollment_id, {"hiatus_reason": "AFFILIATE_TRANSFER"},
            TEST_USERS["intake_coordinator_headers"]), 200)

        # The hiatus above already settled the pledge (PRD §3.5).
        settled = get_success_data(api_client.get_pledge(
            pledge["id"], TEST_USERS["any_headers"]))
        assert settled["covered_days"] == 5
        assert settled["final_settled_cents"] == 110_000
        assert settled["final_settled_cents"] != 75_000
        assert settled["provisional_settled_cents"] == 2_250
        assert settled["status"] == "SETTLED_FINAL"


class TestOccupancyChargeConstants:

    def test_billed_nights_beyond_the_clamp_are_charged_at_180(self, logical_clock):
        """PRD §3.4: "`billed_nights` reports the inclusive night count of the
        window"

        Design: Corner/calculations/calc_occupancy_charge_clamped_at_180_nights
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
        create_facility(facility_code="PTB-01", tier="PARTNER_CLASS_B",
                        total_beds=6, buffer_beds=0)

        referral = create_referral(protocol["id"], child_name="Ava Reyes",
                                   expected_treatment_days=900, is_immunosuppressed=False)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])

        booking = validate_success(api_client.create_assignment(
            {"enrollment_id": arrived["enrollment_id"],
             "start_at": "2026-09-01T00:00:00Z", "end_at": "2029-02-17T00:00:00Z",
             "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]), 201)
        assert booking["assigned_tier"] == "PARTNER_CLASS_B"
        assert booking["billed_nights"] == 900
        assert booking["nightly_rate_cents"] == 13000
        assert booking["housing_cost_cents"] == 2_340_000
        assert booking["housing_cost_cents"] != 11_700_000