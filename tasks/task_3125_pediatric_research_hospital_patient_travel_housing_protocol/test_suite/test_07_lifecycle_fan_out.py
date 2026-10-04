"""Queue A — the fan-out of complete-treatment and of referral withdrawal."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fund, create_open_protocol, create_facility, create_referral,
    screen_referral, arrive_referral, sign_consent, create_pledge,
    set_clock, TEST_USERS, ApiErrorId, current_protocol_version,
)


def _protocol_with_family(fund, protocol):
    # The caller registers the ONC-01 residence (a `facility_code` is unique
    # across the program per PRD §2.13, so re-creating it here would collide).
    referral = create_referral(protocol["id"], is_immunosuppressed=True)
    screened = validate_success(api_client.screen_referral(
        referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
        TEST_USERS["intake_coordinator_headers"]), 200)
    arrived = arrive_referral(referral["id"], screened["version"])
    return referral, arrived["enrollment_id"]


def _clear_consent(enrollment_id):
    return validate_success(api_client.sign_consent(
        enrollment_id,
        {"consent_signer": "GUARDIAN_AND_CHILD",
         "guardian_consent_signature_code": "GC-1001",
         "child_assent_signature_code": "CA-1001"},
        TEST_USERS["intake_coordinator_headers"]), 200)


class TestCompleteTreatmentFanOut:

    def test_completion_closes_the_enrollment_and_auto_completes_the_sibling(self, logical_clock):
        """PRD §3.8: "Success moves the enrollment to `SURVIVORSHIP`, decrements
        the protocol's `enrolled_count`, creates a `SurvivorshipEnrollment` in
        `ON_STUDY` status with `completed_treatment_at` stamped from the logical
        clock, completes every sibling support service on that enrollment, and
        settles the current pledge."

        Design: Difficulty/cascading_side_effects/cascade_complete_treatment_fans_out_to_three_targets
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
        study = get_success_data(api_client.create_study(protocol["id"], {
            "study_code": "SURV-001", "follow_up_interval_months": 12,
            "min_years_after_completion": 5,
        }, TEST_USERS["survivorship_coordinator_headers"]))

        referral, enrollment_id = _protocol_with_family(fund, protocol)
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        get_success_data(api_client.activate_assignment(
            booking["id"], TEST_USERS["housing_coordinator_headers"]))
        consent = _clear_consent(enrollment_id)
        enrolled_after_sign = consent["protocol_enrolled_count"]
        validate_success(api_client.start_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)

        milestone = get_success_data(api_client.create_milestone(enrollment_id, {
            "milestone_sequence": 1, "description": "Induction",
            "requires_main_campus": True, "target_at": "2026-09-02T00:00:00Z",
        }, TEST_USERS["protocol_coordinator_headers"]))
        validate_success(api_client.execute_milestone(
            milestone["id"], TEST_USERS["affiliate_clinic_coordinator_headers"]), 200)

        sibling = get_success_data(api_client.create_sibling_service(enrollment_id, {
            "sibling_alias": "R-Sib", "service_type": "SIBLING_CAMP",
            "delivery_window_start_at": "2026-09-01T00:00:00Z",
            "delivery_window_end_at": "2026-10-01T00:00:00Z",
        }, TEST_USERS["patient_support_officer_headers"]))
        pledge = create_pledge(enrollment_id, budget_cents=400_000)

        completed = validate_success(api_client.complete_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)
        assert completed["status"] == "SURVIVORSHIP"

        sibling_after = get_success_data(api_client.get_sibling_service(
            sibling["id"], TEST_USERS["any_headers"]))
        assert sibling_after["status"] == "COMPLETED"

        posture = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        assert posture["enrolled_count"] == enrolled_after_sign - 1

    def test_completion_settles_the_pledge_and_opens_follow_up(self, logical_clock):
        """PRD §3.5: "Pledges are also settled automatically, without a
        settlement request. The enrollment's own lifecycle settles them: a hiatus
        settles the current pledge, treatment completion settles the current
        pledge"

        Design: Difficulty/cascading_side_effects/cascade_complete_treatment_fans_out_to_three_targets
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
        get_success_data(api_client.create_study(protocol["id"], {
            "study_code": "SURV-001", "follow_up_interval_months": 12,
            "min_years_after_completion": 5,
        }, TEST_USERS["survivorship_coordinator_headers"]))

        referral, enrollment_id = _protocol_with_family(fund, protocol)
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        get_success_data(api_client.activate_assignment(
            booking["id"], TEST_USERS["housing_coordinator_headers"]))
        _clear_consent(enrollment_id)
        validate_success(api_client.start_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)

        milestone = get_success_data(api_client.create_milestone(enrollment_id, {
            "milestone_sequence": 1, "description": "Induction",
            "requires_main_campus": True, "target_at": "2026-09-02T00:00:00Z",
        }, TEST_USERS["protocol_coordinator_headers"]))
        validate_success(api_client.execute_milestone(
            milestone["id"], TEST_USERS["affiliate_clinic_coordinator_headers"]), 200)
        sibling = get_success_data(api_client.create_sibling_service(enrollment_id, {
            "sibling_alias": "R-Sib", "service_type": "SIBLING_CAMP",
            "delivery_window_start_at": "2026-09-01T00:00:00Z",
            "delivery_window_end_at": "2026-10-01T00:00:00Z",
        }, TEST_USERS["patient_support_officer_headers"]))
        pledge = create_pledge(enrollment_id, budget_cents=400_000)

        validate_success(api_client.complete_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)

        pledge_after = get_success_data(api_client.get_pledge(pledge["id"], TEST_USERS["any_headers"]))
        assert pledge_after["status"] == "SETTLED_FINAL"

        follow_up = validate_success(api_client.list_enrollment_survivorship(
            enrollment_id, TEST_USERS["any_headers"]), 200)
        assert len(follow_up) == 1
        assert follow_up[0]["status"] == "ON_STUDY"
        assert follow_up[0]["next_due_at"] == "2026-09-01T00:00:00.000Z"


class TestWithdrawalFanOut:

    def test_withdrawal_cancels_housing_and_voids_the_pledge(self, logical_clock):
        """PRD §3.2: "when it does proceed it cascades — the enrollment on that
        referral moves to `WITHDRAWN`, every `HousingAssignment` on the
        enrollment is `CANCELLED`, every `FamilySupportPledge` on it is
        `VOIDED`"

        Design: Difficulty/cascading_side_effects/cascade_withdraw_fans_out_across_three_resource_types
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

        referral, enrollment_id = _protocol_with_family(fund, protocol)
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        _clear_consent(enrollment_id)
        pledge = create_pledge(enrollment_id, budget_cents=400_000)

        validate_success(api_client.withdraw_referral(
            referral["id"], {"withdrawal_reason": "FAMILY_RELOCATION"},
            TEST_USERS["intake_coordinator_headers"]), 200)

        assignment_after = get_success_data(api_client.get_assignment(
            booking["id"], TEST_USERS["any_headers"]))
        assert assignment_after["status"] == "CANCELLED"

        pledge_after = get_success_data(api_client.get_pledge(
            pledge["id"], TEST_USERS["any_headers"]))
        assert pledge_after["status"] == "VOIDED"

    def test_withdrawal_closes_the_enrollment_and_releases_the_reservation(self, logical_clock):
        """PRD §3.2: "the enrollment on that referral moves to `WITHDRAWN`, every
        `HousingAssignment` on the enrollment is `CANCELLED`, every
        `FamilySupportPledge` on it is `VOIDED`, and the protocol's
        `enrolled_count` is decremented if the enrollment had reached `ENROLLED`."
        PRD §3.2: "The reservation is released exactly as in the accepted case."

        Design: Difficulty/cascading_side_effects/cascade_withdraw_fans_out_across_three_resource_types
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

        referral, enrollment_id = _protocol_with_family(fund, protocol)
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        consent = _clear_consent(enrollment_id)
        enrolled_after_sign = consent["protocol_enrolled_count"]
        pledge = create_pledge(enrollment_id, budget_cents=400_000)

        withdrawn = validate_success(api_client.withdraw_referral(
            referral["id"], {"withdrawal_reason": "FAMILY_RELOCATION"},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        enrollment_after = get_success_data(api_client.get_enrollment(
            enrollment_id, TEST_USERS["any_headers"]))
        assert enrollment_after["status"] == "WITHDRAWN"

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["enrolled_count"] == enrolled_after_sign - 1
        assert protocol_after["reserved_cents"] == 0

    def test_withdrawal_from_a_live_treatment_state_is_refused(self, logical_clock):
        """PRD §3.2: "A withdrawal from `ARRIVED` is the heaviest: it is refused
        with `ERR_ENROLLMENT_ACTIVE` (HTTP 409) while any enrollment on the
        referral is in `ACTIVE_TREATMENT` or `SURVIVORSHIP`"

        Design: Difficulty/cascading_side_effects/cascade_withdraw_fans_out_across_three_resource_types
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

        referral, enrollment_id = _protocol_with_family(fund, protocol)
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        get_success_data(api_client.activate_assignment(
            booking["id"], TEST_USERS["housing_coordinator_headers"]))
        _clear_consent(enrollment_id)
        validate_success(api_client.start_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)

        res = api_client.withdraw_referral(
            referral["id"], {"withdrawal_reason": "FAMILY_RELOCATION"},
            TEST_USERS["intake_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_ACTIVE)