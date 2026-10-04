"""Queue A — selector policy, affiliation-gated deferral and arrival under a freeze."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, create_fund, create_open_protocol, create_facility,
    create_referral, screen_referral, arrive_referral, sign_consent,
    create_hold_payload, set_clock, TEST_USERS, ApiErrorId,
    current_protocol_version,
)


class TestSelectorPolicy:

    def _pool(self, protocol, suspended_b_ids=()):
        one = create_facility(facility_code="PTB-A01", name="Partner Class B One",
                              tier="PARTNER_CLASS_B", total_beds=6, buffer_beds=1)
        two = create_facility(facility_code="PTB-A02", name="Partner Class B Two",
                              tier="PARTNER_CLASS_B", total_beds=6, buffer_beds=1)
        for b_id in suspended_b_ids:
            validate_success(api_client.suspend_facility(
                b_id, {"suspension_reason": "FIRE_SAFETY_REMEDIATION"},
                TEST_USERS["housing_coordinator_headers"]), 200)
        return one, two

    def _campus_and_class_c(self):
        """The campus residence and a Class C residence.

        A one-step (short-course) family bands to PARTNER_CLASS_C, and an
        immunosuppressed family bands to ON_CAMPUS, so both tiers need a
        candidate for the band tests to observe their routing.
        """
        create_facility(facility_code="ONC-01", name="Campus Residence",
                        tier="ON_CAMPUS", total_beds=4, buffer_beds=0)
        create_facility(facility_code="PTC-A01", name="Partner Class C One",
                        tier="PARTNER_CLASS_C", total_beds=6, buffer_beds=0)

    def test_duration_bands_route_each_family_to_its_tier(self, logical_clock):
        """PRD §2.6: "Candidate facilities are those whose `status` is `OPEN` and
        whose tier is at least as capable as the required tier, ordered by the
        tier's position in the sequence `ON_CAMPUS`, `PARTNER_CLASS_A`,
        `PARTNER_CLASS_B`, `PARTNER_CLASS_C` — lowest position first"

        Design: Difficulty/selector_policy/selector_capability_ranking_with_created_at_tie_break
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
        self._campus_and_class_c()
        self._pool(protocol)

        immuno = create_referral(protocol["id"], child_name="Ava Reyes",
                                 is_immunosuppressed=True, expected_treatment_days=245)
        long_stay = create_referral(protocol["id"], child_name="Noah Patel",
                                    is_immunosuppressed=False, expected_treatment_days=300)
        short_stay = create_referral(protocol["id"], child_name="Mia Chen",
                                     household_state_code="NV",
                                     is_immunosuppressed=False, expected_treatment_days=60)

        immuno_screened = validate_success(api_client.screen_referral(
            immuno["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        long_screened = validate_success(api_client.screen_referral(
            long_stay["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        short_screened = validate_success(api_client.screen_referral(
            short_stay["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)

        assert immuno_screened["applied_tier"] == "ON_CAMPUS"
        assert long_screened["applied_tier"] == "PARTNER_CLASS_B"
        assert short_screened["applied_tier"] == "PARTNER_CLASS_C"
        assert long_screened["selector_window_days"] == 300
        assert immuno_screened["selector_window_days"] == 245

    def test_tied_candidates_are_broken_by_creation_order(self, logical_clock):
        """PRD §2.6: "An exact tie is broken by the earliest `created_at`, and a
        remaining tie by the lexicographically smallest `facility_code`."

        Design: Difficulty/selector_policy/selector_capability_ranking_with_created_at_tie_break
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
        self._campus_and_class_c()
        one, two = self._pool(protocol)

        long_stay = create_referral(protocol["id"], child_name="Noah Patel",
                                    is_immunosuppressed=False, expected_treatment_days=300)
        screened = validate_success(api_client.screen_referral(
            long_stay["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert screened["applied_tier"] == "PARTNER_CLASS_B"

        arrived = arrive_referral(long_stay["id"], screened["version"])
        booking = validate_success(api_client.create_assignment(
            {"enrollment_id": arrived["enrollment_id"],
             "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-06T00:00:00Z",
             "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]), 201)
        assert booking["housing_facility_id"] == one["id"]
        assert booking["housing_facility_id"] != two["id"]

    def test_empty_candidate_pool_declines_the_referral(self, logical_clock):
        """PRD §2.6: "If the candidate set is empty the screen cannot place the
        family: the referral is declined with `applied_tier` of `DECLINED` and
        the refusal code `ERR_NO_HOUSING_AVAILABLE` (HTTP 409)."

        Design: Difficulty/selector_policy/selector_empty_candidate_pool_declines_the_referral
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
        create_facility(facility_code="ONC-01", name="Campus Residence",
                        tier="ON_CAMPUS", total_beds=4, buffer_beds=0)
        class_b = create_facility(facility_code="PTB-01", name="Partner Class B",
                                  tier="PARTNER_CLASS_B", total_beds=6, buffer_beds=0)
        validate_success(api_client.suspend_facility(
            class_b["id"], {"suspension_reason": "FIRE_SAFETY_REMEDIATION"},
            TEST_USERS["housing_coordinator_headers"]), 200)

        referral = create_referral(protocol["id"], child_name="Noah Patel",
                                   is_immunosuppressed=False, expected_treatment_days=300)
        res = api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_NO_HOUSING_AVAILABLE)

    def test_declined_screen_books_no_reservation(self, logical_clock):
        """PRD §3.2: "A budget failure records no accrual on the protocol at all,
        and a declined referral books no reservation; `reservation_basis_cents`
        is left at zero and `reserved_cents` untouched."

        Design: Difficulty/selector_policy/selector_empty_candidate_pool_declines_the_referral
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
        create_facility(facility_code="ONC-01", name="Campus Residence",
                        tier="ON_CAMPUS", total_beds=4, buffer_beds=0)
        class_b = create_facility(facility_code="PTB-01", name="Partner Class B",
                                  tier="PARTNER_CLASS_B", total_beds=6, buffer_beds=0)
        validate_success(api_client.suspend_facility(
            class_b["id"], {"suspension_reason": "FIRE_SAFETY_REMEDIATION"},
            TEST_USERS["housing_coordinator_headers"]), 200)

        referral = create_referral(protocol["id"], child_name="Noah Patel",
                                   is_immunosuppressed=False, expected_treatment_days=300)
        res = api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_NO_HOUSING_AVAILABLE)

        row = get_success_data(api_client.get_referral(referral["id"], TEST_USERS["any_headers"]))
        assert row["status"] == "DECLINED"
        assert row["applied_tier"] == "DECLINED"
        assert row["reservation_basis_cents"] == 0

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["reserved_cents"] == 0
        assert protocol_after["available_cents"] == 10_000_000


class TestDeferralGatedByAffiliationAgreement:

    def _due_milestone_course(self):
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

        clinic = get_success_data(api_client.create_clinic({
            "clinic_code": "AF-TN-01", "name": "Memphis Affiliate",
            "state_code": "TN", "is_active": True,
        }, TEST_USERS["affiliate_clinic_coordinator_headers"]))
        agreement = get_success_data(api_client.create_affiliation(clinic["id"], {
            "protocol_id": protocol["id"], "protocol_version": "v1",
            "effective_start_at": "2026-09-01T00:00:00Z",
        }, TEST_USERS["affiliate_clinic_coordinator_headers"]))

        referral = create_referral(protocol["id"], is_immunosuppressed=True)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])
        enrollment_id = arrived["enrollment_id"]
        sign_consent(enrollment_id)
        _book_and_activate(enrollment_id)
        validate_success(api_client.start_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)

        first = get_success_data(api_client.create_milestone(enrollment_id, {
            "milestone_sequence": 1, "description": "Induction",
            "requires_main_campus": True, "target_at": "2026-09-02T00:00:00Z",
        }, TEST_USERS["protocol_coordinator_headers"]))
        second = get_success_data(api_client.create_milestone(enrollment_id, {
            "milestone_sequence": 2, "description": "Consolidation",
            "requires_main_campus": False, "target_at": "2026-09-05T00:00:00Z",
        }, TEST_USERS["protocol_coordinator_headers"]))
        validate_success(api_client.execute_milestone(
            first["id"], TEST_USERS["affiliate_clinic_coordinator_headers"]), 200)
        second = get_success_data(api_client.get_milestone(second["id"], TEST_USERS["any_headers"]))
        return protocol, clinic, agreement, first, second

    def test_deferral_fails_while_the_agreement_is_pending(self, logical_clock):
        """PRD §3.7: "an `ACTIVE` affiliation agreement must cover that protocol
        at the requested affiliate (`ERR_NO_ACTIVE_AFFILIATION_AGREEMENT`, HTTP
        409)"

        Design: Difficulty/cross_entity_state_dependency/dependency_deferral_gated_by_active_affiliation_agreement
        """
        protocol, clinic, agreement, first, second = self._due_milestone_course()
        res = api_client.defer_milestone(
            second["id"], {"affiliate_clinic_id": clinic["id"]},
            TEST_USERS["affiliate_clinic_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_NO_ACTIVE_AFFILIATION_AGREEMENT)

    def test_same_deferral_succeeds_once_the_agreement_is_active(self, logical_clock):
        """PRD §3.7: "A successful deferral leaves the milestone `DUE` but
        records `deferred_from_milestone_id` as the enrollment's immediately
        preceding milestone, sets `affiliate_clinic_id` to the coordinating site"

        Design: Difficulty/cross_entity_state_dependency/dependency_deferral_gated_by_active_affiliation_agreement
        """
        protocol, clinic, agreement, first, second = self._due_milestone_course()
        activated = validate_success(api_client.activate_affiliation(
            agreement["id"], TEST_USERS["affiliate_clinic_coordinator_headers"]), 200)
        assert activated["status"] == "ACTIVE"

        deferred = validate_success(api_client.defer_milestone(
            second["id"], {"affiliate_clinic_id": clinic["id"]},
            TEST_USERS["affiliate_clinic_coordinator_headers"]), 200)
        assert deferred["status"] == "DUE"
        assert deferred["affiliate_clinic_id"] == clinic["id"]
        assert deferred["deferred_from_milestone_id"] == first["id"]


class TestArrivalGatedByProtocolState:

    def _accepted_then_frozen(self):
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

        first_hold = validate_success(api_client.raise_hold(
            protocol["id"], create_hold_payload(hold_reason="SPONSOR_AUDIT"),
            TEST_USERS["irb_reviewer_headers"]), 201)
        validate_success(api_client.release_hold(
            first_hold["id"], TEST_USERS["protocol_coordinator_headers"]), 200)

        posture = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        re_screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": posture["protocol_version"]},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert re_screened["status"] == "ACCEPTED"

        validate_success(api_client.raise_hold(
            protocol["id"], create_hold_payload(hold_reason="FUNDING_REVIEW",
                                                initiated_at="2026-09-03T00:00:00Z"),
            TEST_USERS["irb_reviewer_headers"]), 201)
        return protocol, referral, re_screened

    def test_arrival_is_refused_while_the_protocol_is_frozen(self, logical_clock):
        """PRD §3.3: "It requires the referral to be `ACCEPTED` — otherwise
        `ERR_REFERRAL_NOT_ACCEPTED` (HTTP 409) — and the target protocol to be
        `OPEN` and not held, otherwise `ERR_PROTOCOL_NOT_OPEN` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/dependency_arrival_gated_by_open_protocol
        """
        protocol, referral, screened = self._accepted_then_frozen()
        res = api_client.arrive_referral(
            referral["id"], {"expected_referral_version": screened["version"]},
            TEST_USERS["intake_coordinator_headers"])
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_PROTOCOL_NOT_OPEN,
            ApiErrorId.ERR_REFERRAL_NOT_ACCEPTED,
        ])

    def test_the_freeze_is_what_removed_the_acceptance(self, logical_clock):
        """PRD §3.9: "every referral on that protocol currently in `ACCEPTED`
        status reverts to `SUBMITTED` with its `applied_tier` reset to
        `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/dependency_arrival_gated_by_open_protocol
        """
        protocol, referral, screened = self._accepted_then_frozen()

        row = get_success_data(api_client.get_referral(referral["id"], TEST_USERS["any_headers"]))
        assert row["status"] == "SUBMITTED"
        assert row["applied_tier"] == "PENDING"

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["status"] == "HELD"
        assert protocol_after["is_protocol_held"] is True


def _book_and_activate(enrollment_id):
    booking = get_success_data(api_client.create_assignment(
        {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
         "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
        TEST_USERS["housing_coordinator_headers"]))
    return get_success_data(api_client.activate_assignment(
        booking["id"], TEST_USERS["housing_coordinator_headers"]))