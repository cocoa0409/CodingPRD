"""Queue B — immediate consistency, endpoint conditioning and the care gate."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fund, create_open_protocol, create_facility, create_referral,
    screen_referral, arrive_referral, sign_consent, create_hold_payload,
    set_clock, TEST_USERS, ApiErrorId,
    current_protocol_version,
)


class TestHoldConditioning:

    def test_a_draft_protocol_cannot_be_frozen(self, logical_clock):
        """PRD §3.9: "When the institution must stop admitting families to a
        protocol, an `IRBReviewer` raises a hold. The hold is recorded with a
        `hold_reason` of `IRB_REVIEW`, `SAFETY_SIGNAL`, `FUNDING_REVIEW`, or
        `SPONSOR_AUDIT`, and an `initiated_at` instant, and it is born `ACTIVE`"

        Design: Corner/endpoints/ep_hold_on_a_draft_protocol_is_rejected
        """
        fund = create_fund()
        draft = get_success_data(api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-INT-001", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 10_000_000, "capacity": 8},
            TEST_USERS["protocol_coordinator_headers"]))
        assert draft["status"] == "DRAFT"

        res = api_client.raise_hold(
            draft["id"], create_hold_payload(hold_reason="IRB_REVIEW"),
            TEST_USERS["irb_reviewer_headers"])
        validate_error(res, ApiErrorId.ERR_PROTOCOL_NOT_OPEN)
        assert res.status_code == 409

        protocol_after = get_success_data(api_client.get_protocol(
            draft["id"], TEST_USERS["any_headers"]))
        assert protocol_after["status"] == "DRAFT"
        assert protocol_after["is_protocol_held"] is False

        holds = validate_success(api_client.list_protocol_holds(
            draft["id"], TEST_USERS["any_headers"]), 200)
        assert len(holds) == 0


class TestOneToOneCareGate:

    def test_consent_is_refused_when_no_traveler_is_cleared(self, logical_clock):
        """PRD §3.3: "Every traveler holding a `GUARDIAN`-type coverage placed by
        this referral must appear in the referral's `one_to_one_care_capability_codes`,
        and a coverage holder who was not cleared for one-to-one care is refused
        with `ERR_ONE_TO_ONE_CARE_NOT_ELIGIBLE` (HTTP 422)."

        Design: Corner/validations/val_one_to_one_care_gate_blocks_consent
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)

        referral = create_referral(protocol["id"], is_immunosuppressed=True,
                                   one_to_one_care_capability_codes=[])
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])
        enrollment_id = arrived["enrollment_id"]

        # The gate compares a GUARDIAN-type coverage the referral *actually
        # places* against the cleared list, so the precondition is a placed
        # GUARDIAN coverage. Placing one without clearing its holder is exactly
        # the violation the rule describes.
        validate_success(api_client.request_travel(
            enrollment_id,
            {"mode": "GROUND", "traveler_count": 2,
             "departure_at": "2026-09-05T00:00:00Z", "return_at": "2026-09-12T00:00:00Z",
             "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True,
             "placed_coverages": [{"coverage_type": "GUARDIAN", "plan_code": "GD-01",
                                   "coverage_id": None, "coverage_cents": 50000,
                                   "travel_window_start_at": "2026-09-05T00:00:00Z",
                                   "travel_window_end_at": "2026-09-12T00:00:00Z",
                                   "covers_required_travel": True}]},
            TEST_USERS["patient_support_officer_headers"]), 201)

        res = api_client.sign_consent(
            enrollment_id,
            {"consent_signer": "GUARDIAN_AND_CHILD",
             "guardian_consent_signature_code": "GC-1001",
             "child_assent_signature_code": "CA-1001"},
            TEST_USERS["intake_coordinator_headers"])
        error = validate_error(res, ApiErrorId.ERR_ONE_TO_ONE_CARE_NOT_ELIGIBLE)
        assert res.status_code == 422
        assert error["error_id"] != ApiErrorId.ERR_ASSENT_NOT_OBTAINED

        enrollment_after = get_success_data(api_client.get_enrollment(
            enrollment_id, TEST_USERS["any_headers"]))
        assert enrollment_after["status"] == "PENDING_CONSENT"

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["enrolled_count"] == 0

    def test_a_cleared_traveler_lets_the_signature_through(self, logical_clock):
        """PRD §3.3: "A signing operation whose `consent_signer` does not match
        the signer the child's age demands is refused with
        `ERR_INVALID_CONSENT_SIGNER` (HTTP 422)."

        Design: Corner/validations/val_one_to_one_care_gate_blocks_consent
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)

        referral = create_referral(protocol["id"], is_immunosuppressed=True,
                                   one_to_one_care_capability_codes=["GUARDIAN"])
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])

        signed = validate_success(api_client.sign_consent(
            arrived["enrollment_id"],
            {"consent_signer": "GUARDIAN_AND_CHILD",
             "guardian_consent_signature_code": "GC-1001",
             "child_assent_signature_code": "CA-1001"},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert signed["assent_state"] == "OBTAINED"
        assert signed["guardian_consent_signed_at"] is not None


class TestImmediateConsistency:

    def _enrolled_with_occupancy_and_pledge(self):
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
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        sign_consent(enrollment_id)
        pledge = get_success_data(api_client.create_pledge(
            {"enrollment_id": enrollment_id, "patient_support_budget_cents": 400_000},
            TEST_USERS["patient_support_officer_headers"]))
        return referral, enrollment_id, booking, pledge

    def test_the_withdrawal_response_already_reflects_the_new_state(self, logical_clock):
        """PRD §3.2: "A withdrawal from `SUBMITTED` simply moves the row to
        `WITHDRAWN` with a `withdrawal_reason` recorded and nothing else to
        unwind."

        Design: Corner/consistency_model/consistency_withdrawal_is_visible_in_the_same_response
        """
        referral, enrollment_id, booking, pledge = self._enrolled_with_occupancy_and_pledge()
        withdrawn = validate_success(api_client.withdraw_referral(
            referral["id"], {"withdrawal_reason": "FAMILY_RELOCATION"},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert withdrawn["status"] == "WITHDRAWN"

    def test_every_cascaded_write_is_readable_immediately(self, logical_clock):
        """PRD §3.2: "the enrollment on that referral moves to `WITHDRAWN`, every
        `HousingAssignment` on the enrollment is `CANCELLED`, every
        `FamilySupportPledge` on it is `VOIDED`"

        Design: Corner/consistency_model/consistency_withdrawal_is_visible_in_the_same_response
        """
        referral, enrollment_id, booking, pledge = self._enrolled_with_occupancy_and_pledge()
        validate_success(api_client.withdraw_referral(
            referral["id"], {"withdrawal_reason": "FAMILY_RELOCATION"},
            TEST_USERS["intake_coordinator_headers"]), 200)

        enrollment_after = validate_success(api_client.get_enrollment(
            enrollment_id, TEST_USERS["any_headers"]), 200)
        assert enrollment_after["status"] == "WITHDRAWN"

        assignment_after = validate_success(api_client.get_assignment(
            booking["id"], TEST_USERS["any_headers"]), 200)
        assert assignment_after["status"] == "CANCELLED"

        pledge_after = validate_success(api_client.get_pledge(
            pledge["id"], TEST_USERS["any_headers"]), 200)
        assert pledge_after["status"] == "VOIDED"