"""Queue B — validation, endpoint, RBAC and cross-cutting corners."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_fund, create_open_protocol, create_facility, create_referral,
    screen_referral, arrive_referral, sign_consent, create_hold_payload,
    set_clock, TEST_USERS, ApiErrorId,
    current_protocol_version,
)


def _enrolled_family(protocol, facility_code="ONC-01", **referral_overrides):
    referral = create_referral(protocol["id"], **referral_overrides)
    screened = validate_success(api_client.screen_referral(
        referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
        TEST_USERS["intake_coordinator_headers"]), 200)
    arrived = arrive_referral(referral["id"], screened["version"])
    return referral, arrived["enrollment_id"]


class TestAgeBandInclusivity:

    def test_band_is_inclusive_at_both_ends(self, logical_clock):
        """PRD §3.2: "The child's `computed_age_years`, measured in whole
        completed years against the logical clock, must lie within the protocol's
        inclusive `age_min_years` to `age_max_years` band or the screen fails
        with `ERR_AGE_OUTSIDE_PROTOCOL_RANGE` (HTTP 422)."

        Design: Corner/validations/val_age_band_is_inclusive_at_both_ends
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="PTB-01", tier="PARTNER_CLASS_B",
                        total_beds=6, buffer_beds=0)

        boundary_in = create_referral(
            protocol["id"], child_name="Boundary In",
            child_date_of_birth="2009-09-01T00:00:00Z",
            traveling_family_member_count=2, expected_treatment_days=200,
            is_immunosuppressed=False)
        boundary_out = create_referral(
            protocol["id"], child_name="Boundary Out",
            child_date_of_birth="2008-09-01T00:00:00Z",
            traveling_family_member_count=2, expected_treatment_days=200,
            is_immunosuppressed=False)

        inside = validate_success(api_client.screen_referral(
            boundary_in["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert inside["computed_age_years"] == 17
        assert inside["status"] == "ACCEPTED"
        assert inside["applied_tier"] == "PARTNER_CLASS_B"

        outside = validate_success(api_client.screen_referral(
            boundary_out["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert outside["computed_age_years"] == 18
        assert outside["status"] == "DECLINED"
        assert outside["decline_reason"] == "ELIGIBILITY_AGE"

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["reserved_cents"] == 625_000


class TestTravelSummaryRead:

    def test_summary_accumulates_only_the_chargeable_legs(self, logical_clock):
        """PRD §3.6: "The enrollment-level travel summary reports the accumulated
        historical charge rather than any single leg: it gathers every leg for the
        enrollment whose status is `CONFIRMED` or `DISBURSED`, orders them
        chronologically by `departure_at`"

        Design: Corner/endpoints/ep_travel_summary_computed_read_matches_the_legs
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

        _, enrollment_id = _enrolled_family(protocol, is_immunosuppressed=True)

        first_leg = get_success_data(api_client.request_travel(
            enrollment_id,
            {"mode": "AIR_ECONOMY", "traveler_count": 2,
             "departure_at": "2026-09-05T00:00:00Z", "return_at": "2026-09-06T00:00:00Z",
             "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True},
            TEST_USERS["patient_support_officer_headers"]))
        validate_success(api_client.confirm_travel(
            first_leg["id"], TEST_USERS["patient_support_officer_headers"]), 200)

        second_leg = get_success_data(api_client.request_travel(
            enrollment_id,
            {"mode": "GROUND", "traveler_count": 3,
             "departure_at": "2026-09-08T00:00:00Z", "return_at": "2026-09-09T00:00:00Z",
             "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True},
            TEST_USERS["patient_support_officer_headers"]))
        validate_success(api_client.confirm_travel(
            second_leg["id"], TEST_USERS["patient_support_officer_headers"]), 200)

        cancelled_leg = get_success_data(api_client.request_travel(
            enrollment_id,
            {"mode": "RAIL", "traveler_count": 2,
             "departure_at": "2026-09-20T00:00:00Z", "return_at": "2026-09-21T00:00:00Z",
             "trip_reason": "FAMILY_REQUEST", "is_required_travel": False},
            TEST_USERS["patient_support_officer_headers"]))
        cancelled = validate_success(api_client.cancel_travel(
            cancelled_leg["id"], TEST_USERS["patient_support_officer_headers"]), 200)
        assert cancelled["status"] == "CANCELLED"

        first_read = get_success_data(api_client.get_travel(first_leg["id"], TEST_USERS["any_headers"]))
        second_read = get_success_data(api_client.get_travel(second_leg["id"], TEST_USERS["any_headers"]))
        assert first_read["family_day_units"] == 2
        assert second_read["family_day_units"] == 3

        summary = validate_success(api_client.get_travel_summary(
            enrollment_id, TEST_USERS["any_headers"]), 200)
        assert summary["chargeable_leg_count"] == 2
        assert summary["accumulated_family_day_charge_cents"] == 75_000
        assert summary["accumulated_family_day_charge_cents"] != 105_000


class TestHeldProtocolBlocksMilestoneExecution:

    def test_execution_under_a_freeze_reports_protocol_not_open(self, logical_clock):
        """PRD §3.7: "The milestone must be `DUE` or the attempt reports
        `ERR_MILESTONE_NOT_DUE`, and the host protocol must be `OPEN` and unheld
        or it reports `ERR_PROTOCOL_NOT_OPEN` (HTTP 409)."

        Design: Corner/errors/err_held_protocol_blocks_milestone_execution
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

        _, enrollment_id = _enrolled_family(protocol, is_immunosuppressed=True)
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        get_success_data(api_client.activate_assignment(
            booking["id"], TEST_USERS["housing_coordinator_headers"]))
        sign_consent(enrollment_id)
        validate_success(api_client.start_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)

        milestone = get_success_data(api_client.create_milestone(enrollment_id, {
            "milestone_sequence": 1, "description": "Induction",
            "requires_main_campus": True, "target_at": "2026-09-02T00:00:00Z",
        }, TEST_USERS["protocol_coordinator_headers"]))
        due = get_success_data(api_client.get_milestone(milestone["id"], TEST_USERS["any_headers"]))
        assert due["status"] == "DUE"

        validate_success(api_client.raise_hold(
            protocol["id"], create_hold_payload(
                hold_reason="FUNDING_REVIEW", initiated_at="2026-09-03T00:00:00Z"),
            TEST_USERS["irb_reviewer_headers"]), 201)

        res = api_client.execute_milestone(
            milestone["id"], TEST_USERS["affiliate_clinic_coordinator_headers"])
        error = validate_error(res, ApiErrorId.ERR_PROTOCOL_NOT_OPEN)
        assert res.status_code == 409
        assert error["error_id"] != ApiErrorId.ERR_MILESTONE_NOT_DUE

        unchanged = get_success_data(api_client.get_milestone(
            milestone["id"], TEST_USERS["any_headers"]))
        assert unchanged["status"] == "DUE"
        assert unchanged["executed_at"] is None

        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["is_protocol_held"] is True


class TestRoleBoundWritesAndSharedReads:

    def test_screening_is_refused_for_the_housing_role(self, logical_clock):
        """PRD §2.1: "An authenticated caller whose role is not permitted for the
        requested operation is refused with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/rbac/rbac_housing_coordinator_cannot_screen_a_referral
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)
        referral = create_referral(protocol["id"], is_immunosuppressed=True)

        res = api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["housing_coordinator_headers"])
        error = validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        assert res.status_code == 403

        row = get_success_data(api_client.get_referral(referral["id"], TEST_USERS["any_headers"]))
        assert row["status"] == "SUBMITTED"
        assert row["screening_fee_cents"] == 0
        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["reserved_cents"] == 0

        allowed = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert allowed["status"] == "ACCEPTED"

    def test_reads_stay_open_to_every_role(self, logical_clock):
        """PRD §2.1: "`Any` is not a grantable persona but the read-visibility
        marker shared by every authenticated role: operations declared for `Any`
        are reachable by any of the eight named roles"

        Design: Corner/rbac/rbac_read_operations_are_open_to_every_role
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)
        referral = create_referral(protocol["id"], is_immunosuppressed=True)

        for role_headers in (
            TEST_USERS["any_headers"],
            TEST_USERS["housing_coordinator_headers"],
            TEST_USERS["patient_support_officer_headers"],
            TEST_USERS["survivorship_coordinator_headers"],
        ):
            res = api_client.list_referrals(role_headers, params={"status": "SUBMITTED"})
            rows, meta = validate_paginated(res)
            assert len(rows) == 1
            assert rows[0]["status"] == "SUBMITTED"
            assert rows[0]["id"] == referral["id"]


class TestStaleProtocolVersion:

    def test_screen_with_a_superseded_protocol_version_is_refused(self, logical_clock):
        """PRD §2.11: "If the protocol's version has moved on since that read —
        because another writer changed its capacity, its reservation posture, or
        its hold posture — the screen is refused with `ERR_STALE_VERSION`
        (HTTP 412) rather than being applied against a stale view."

        Design: Corner/cross_cutting_complexity_layers/occ_screen_with_a_stale_protocol_version_returns_stale_version
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=8, buffer_beds=0)

        first = create_referral(protocol["id"], child_name="Ava Reyes", is_immunosuppressed=True)
        second = create_referral(protocol["id"], child_name="Noah Patel", is_immunosuppressed=True)

        snapshot = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))

        validate_success(api_client.screen_referral(
            first["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)

        res = api_client.screen_referral(
            second["id"], {"expected_protocol_version": snapshot["protocol_version"]},
            TEST_USERS["intake_coordinator_headers"])
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        assert res.status_code == 412

        row = get_success_data(api_client.get_referral(second["id"], TEST_USERS["any_headers"]))
        assert row["status"] == "SUBMITTED"
        protocol_after = get_success_data(api_client.get_protocol(
            protocol["id"], TEST_USERS["any_headers"]))
        assert protocol_after["reserved_cents"] == 1_250_000

    def test_resupplying_the_current_version_lets_the_screen_through(self, logical_clock):
        """PRD §2.11: "The general rule behind both is uniform: whenever an
        `expected_*_version` field is supplied, its value must equal the parent
        entity's current `version`."

        Design: Corner/cross_cutting_complexity_layers/occ_screen_with_a_stale_protocol_version_returns_stale_version
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=8, buffer_beds=0)

        first = create_referral(protocol["id"], child_name="Ava Reyes", is_immunosuppressed=True)
        second = create_referral(protocol["id"], child_name="Noah Patel", is_immunosuppressed=True)

        snapshot = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        validate_success(api_client.screen_referral(
            first["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)

        validate_error(api_client.screen_referral(
            second["id"], {"expected_protocol_version": snapshot["protocol_version"]},
            TEST_USERS["intake_coordinator_headers"]), ApiErrorId.ERR_STALE_VERSION)

        fresh = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        accepted = validate_success(api_client.screen_referral(
            second["id"], {"expected_protocol_version": fresh["protocol_version"]},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["reservation_basis_cents"] == 1_250_000


class TestEnrollmentListVisibility:

    def test_withdrawn_rows_are_hidden_unless_explicitly_filtered(self, logical_clock):
        """PRD §2.3: "The enrollment list omits every row in `WITHDRAWN` status
        when no `enrollment_status` filter is supplied; an explicit
        `enrollment_status` of `WITHDRAWN` is the only way to surface withdrawn
        rows."

        Design: Corner/cross_cutting_complexity_layers/cc_enrollment_list_hides_withdrawn_rows_by_default
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)

        live_referral = create_referral(protocol["id"], child_name="Ava Reyes",
                                        is_immunosuppressed=True)
        live_screened = validate_success(api_client.screen_referral(
            live_referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        live_arrived = arrive_referral(live_referral["id"], live_screened["version"])

        withdrawn_referral = create_referral(protocol["id"], child_name="Noah Patel",
                                             is_immunosuppressed=True)
        withdrawn_screened = validate_success(api_client.screen_referral(
            withdrawn_referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        withdrawn_arrived = arrive_referral(withdrawn_referral["id"], withdrawn_screened["version"])
        validate_success(api_client.withdraw_referral(
            withdrawn_referral["id"], {"withdrawal_reason": "FAMILY_RELOCATION"},
            TEST_USERS["intake_coordinator_headers"]), 200)

        hidden = validate_success(api_client.list_enrollments(
            TEST_USERS["any_headers"],
            params={"referral_id": withdrawn_referral["id"]}), 200)
        assert hidden == [] or len(hidden) == 0

        surfaced = validate_success(api_client.list_enrollments(
            TEST_USERS["any_headers"],
            params={"referral_id": withdrawn_referral["id"],
                    "enrollment_status": "WITHDRAWN"}), 200)
        assert len(surfaced) == 1
        assert surfaced[0]["status"] == "WITHDRAWN"

        still_row = get_success_data(api_client.get_enrollment(
            withdrawn_arrived["enrollment_id"], TEST_USERS["any_headers"]))
        assert still_row["status"] == "WITHDRAWN"

        live = validate_success(api_client.list_enrollments(
            TEST_USERS["any_headers"],
            params={"referral_id": live_referral["id"]}), 200)
        assert len(live) == 1
        assert live[0]["status"] == "PENDING_CONSENT"


class TestLogicalClockDefault:

    def test_milestone_states_follow_the_startup_clock(self):
        """PRD §3.10: "the clock starts at 2026-09-01T00:00:00Z on server startup
        and the service never falls back to real wall-clock time, so every age,
        occupancy and window computation in this document is measured against the
        logical clock rather than the host's calendar."

        Design: Corner/cross_cutting_complexity_layers/cc_logical_clock_defaults_to_the_fixed_startup_instant
        """
        fund = create_fund()
        protocol = get_success_data(api_client.create_protocol(
            {"fund_id": fund["id"], "protocol_code": "ALL-INT-001", "disease_group": "ALL",
             "age_min_years": 5, "age_max_years": 17, "required_stage": "NEWLY_DIAGNOSED",
             "protocol_budget_cents": 10_000_000, "capacity": 8},
            TEST_USERS["protocol_coordinator_headers"]))
        protocol = get_success_data(api_client.open_protocol(
            protocol["id"], TEST_USERS["protocol_coordinator_headers"]))
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)

        _, enrollment_id = _enrolled_family(protocol, is_immunosuppressed=True)
        booking = get_success_data(api_client.create_assignment(
            {"enrollment_id": enrollment_id, "start_at": "2026-09-01T00:00:00Z",
             "end_at": "2026-09-02T00:00:00Z", "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]))
        get_success_data(api_client.activate_assignment(
            booking["id"], TEST_USERS["housing_coordinator_headers"]))
        sign_consent(enrollment_id)
        validate_success(api_client.start_treatment(
            enrollment_id, TEST_USERS["intake_coordinator_headers"]), 200)

        past = get_success_data(api_client.create_milestone(enrollment_id, {
            "milestone_sequence": 1, "description": "Past Due",
            "requires_main_campus": True, "target_at": "2026-08-01T00:00:00Z",
        }, TEST_USERS["protocol_coordinator_headers"]))
        future = get_success_data(api_client.create_milestone(enrollment_id, {
            "milestone_sequence": 2, "description": "Future",
            "requires_main_campus": True, "target_at": "2026-10-01T00:00:00Z",
        }, TEST_USERS["protocol_coordinator_headers"]))

        past_read = get_success_data(api_client.get_milestone(past["id"], TEST_USERS["any_headers"]))
        future_read = get_success_data(api_client.get_milestone(future["id"], TEST_USERS["any_headers"]))
        assert past_read["status"] == "MISSED"
        assert future_read["status"] == "PENDING"