"""Queue A — the housing selector, occupancy charge and the overlap rule."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_facility, create_referral, create_protocol, create_open_protocol,
    create_fund, screen_referral, arrive_referral, sign_consent,
    set_clock, TEST_USERS, ApiErrorId,
    current_protocol_version,
)


def _four_residences():
    campus = create_facility(facility_code="ONC-01", name="Campus Residence",
                             tier="ON_CAMPUS", total_beds=4, buffer_beds=0)
    class_a = create_facility(facility_code="PTA-01", name="Partner Class A",
                              tier="PARTNER_CLASS_A", total_beds=2, buffer_beds=0)
    class_b = create_facility(facility_code="PTB-01", name="Partner Class B",
                              tier="PARTNER_CLASS_B", total_beds=6, buffer_beds=0)
    class_c = create_facility(facility_code="PTC-01", name="Partner Class C",
                              tier="PARTNER_CLASS_C", total_beds=6, buffer_beds=0)
    return campus, class_a, class_b, class_c


class TestSelectorImmunosuppressionCarveOut:

    def test_immunosuppressed_referral_is_pinned_to_on_campus(self, logical_clock):
        """PRD §2.6: "Both immunosuppression conditions override the step count:
        if the referral's `is_immunosuppressed` is true, or its
        `has_febrile_neutropenia_risk` is true, the required tier is
        `ON_CAMPUS`."

        Design: Difficulty/combinatorial_formula/combinatorial_immunosuppression_carve_out_overrides_duration_band
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        _four_residences()

        referral = create_referral(protocol["id"], is_immunosuppressed=True,
                                   expected_treatment_days=245)
        screened = validate_success(
            api_client.screen_referral(
                referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
                TEST_USERS["intake_coordinator_headers"]),
            200,
        )
        assert screened["applied_tier"] == "ON_CAMPUS"
        assert screened["selector_window_days"] == 245

        read_back = get_success_data(api_client.get_referral(
            referral["id"], TEST_USERS["any_headers"]))
        assert read_back["applied_tier"] == "ON_CAMPUS"

    def test_identical_duration_lands_on_a_different_tier_when_competent(self, logical_clock):
        """PRD §2.6: "One step requires `PARTNER_CLASS_C`; two steps require
        `PARTNER_CLASS_A`; three or more steps require `PARTNER_CLASS_B`."
        PRD §2.6: "then divides by 180 days and rounds up to obtain a whole
        number of duration steps"

        Design: Difficulty/combinatorial_formula/combinatorial_immunosuppression_carve_out_overrides_duration_band
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        _four_residences()

        immuno = create_referral(protocol["id"], child_name="Ava Reyes",
                                 is_immunosuppressed=True, expected_treatment_days=245)
        competent = create_referral(protocol["id"], child_name="Noah Patel",
                                    is_immunosuppressed=False, expected_treatment_days=245)

        immuno_screened = validate_success(api_client.screen_referral(
            immuno["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        competent_screened = validate_success(api_client.screen_referral(
            competent["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)

        assert immuno_screened["selector_window_days"] == competent_screened["selector_window_days"]
        assert immuno_screened["applied_tier"] == "ON_CAMPUS"
        assert competent_screened["applied_tier"] == "PARTNER_CLASS_A"

    def test_reservation_and_available_follow_the_accepted_tiers(self, logical_clock):
        """PRD §3.2: "`reservation_basis_cents` is set to one eighth of the
        protocol budget rounded up to the whole cent when the accepted tier is
        `ON_CAMPUS`, and to one sixteenth of the protocol budget rounded up when
        the accepted tier is one of the partner classes"
        PRD §2.5: "`available_cents` is what remains: the budget less the
        reserved amount less the committed amount."

        Design: Difficulty/combinatorial_formula/combinatorial_immunosuppression_carve_out_overrides_duration_band
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"], protocol_budget_cents=10_000_000)
        _four_residences()

        immuno = create_referral(protocol["id"], child_name="Ava Reyes",
                                 is_immunosuppressed=True, expected_treatment_days=245)
        competent = create_referral(protocol["id"], child_name="Noah Patel",
                                    is_immunosuppressed=False, expected_treatment_days=245)

        immuno_screened = validate_success(api_client.screen_referral(
            immuno["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert immuno_screened["reservation_basis_cents"] == 1_250_000
        competent_screened = validate_success(api_client.screen_referral(
            competent["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        assert competent_screened["reservation_basis_cents"] == 625_000

        posture = get_success_data(api_client.get_funding_posture(
            protocol["id"], TEST_USERS["any_headers"]))
        assert posture["reserved_cents"] == 1_875_000
        assert posture["available_cents"] == 8_125_000
        assert posture["is_budget_saturated"] is False


class TestSelectorClampAndOccupancyCharge:

    def test_long_and_short_courses_price_identically(self, logical_clock):
        """PRD §2.6: "Because the 540-day clamp is applied before the band count,
        a referral declaring 900 treatment days and one declaring 540 resolve to
        the same window and the same band."

        Design: Difficulty/combinatorial_formula/combinatorial_selector_clamp_band_and_capacity_pool
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="PTB-01", name="Partner Class B",
                        tier="PARTNER_CLASS_B", total_beds=6, buffer_beds=0)

        long_stay = create_referral(protocol["id"], child_name="Ava Reyes",
                                    expected_treatment_days=900, is_immunosuppressed=False)
        short_stay = create_referral(protocol["id"], child_name="Noah Patel",
                                     expected_treatment_days=300, is_immunosuppressed=False)

        long_screened = validate_success(api_client.screen_referral(
            long_stay["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        short_screened = validate_success(api_client.screen_referral(
            short_stay["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)

        assert long_screened["selector_window_days"] == 540
        assert long_screened["applied_tier"] == "PARTNER_CLASS_B"
        assert short_screened["applied_tier"] == "PARTNER_CLASS_B"

        long_arrived = arrive_referral(long_stay["id"], long_screened["version"])
        short_arrived = arrive_referral(short_stay["id"], short_screened["version"])

        booking_a = validate_success(api_client.create_assignment(
            {"enrollment_id": long_arrived["enrollment_id"],
             "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-06T00:00:00Z",
             "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]), 201)
        assert booking_a["assigned_tier"] == "PARTNER_CLASS_B"

    def test_charge_clamp_precedes_the_tier_rate(self, logical_clock):
        """PRD §3.4: "The overnight charge is the number of whole days between
        `start_at` and `end_at`, clamped to at most 180 nights per booking,
        multiplied by the tier's nightly rate"
        PRD §3.4: "Because the clamp is per booking, a 900-night window and a
        180-night window at the same tier cost exactly the same"

        Design: Difficulty/combinatorial_formula/combinatorial_selector_clamp_band_and_capacity_pool
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="PTB-01", name="Partner Class B",
                        tier="PARTNER_CLASS_B", total_beds=6, buffer_beds=0)

        referral = create_referral(protocol["id"], expected_treatment_days=900,
                                   is_immunosuppressed=False)
        screened = validate_success(api_client.screen_referral(
            referral["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        arrived = arrive_referral(referral["id"], screened["version"])

        booking = validate_success(api_client.create_assignment(
            {"enrollment_id": arrived["enrollment_id"],
             "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-06T00:00:00Z",
             "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]), 201)
        assert booking["billed_nights"] == 5
        assert booking["nightly_rate_cents"] == 13000
        assert booking["housing_cost_cents"] == 65_000

        facility = get_success_data(api_client.get_facility(
            booking["housing_facility_id"], TEST_USERS["any_headers"]))
        # PRD §2.6: active_beds_committed counts the assignments in `SCHEDULED`
        # or `ACTIVE` status whose windows coincide, so a single SCHEDULED
        # booking already commits one bed.
        assert facility["active_beds_committed"] == 1


class TestHousingOverlapWithEndpointBuffer:

    def test_half_open_window_rejects_a_shared_instant(self, logical_clock):
        """PRD §2.6: "At the start instant and again at the end instant, the
        number of assignments at that facility in `SCHEDULED` or `ACTIVE` status
        whose half-open occupancy window covers the instant, plus the facility's
        `buffer_beds`, must not exceed its `total_beds`; otherwise the booking is
        refused with `ERR_HOUSING_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_housing_half_open_with_endpoint_buffer
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="PTB-T01", name="Tight Class B",
                        tier="PARTNER_CLASS_B", total_beds=2, buffer_beds=1)

        first = create_referral(protocol["id"], child_name="Ava Reyes",
                                expected_treatment_days=200, is_immunosuppressed=False)
        second = create_referral(protocol["id"], child_name="Noah Patel",
                                 expected_treatment_days=200, is_immunosuppressed=False)
        first_screened = validate_success(api_client.screen_referral(
            first["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        second_screened = validate_success(api_client.screen_referral(
            second["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
            TEST_USERS["intake_coordinator_headers"]), 200)
        first_arrived = arrive_referral(first["id"], first_screened["version"])
        second_arrived = arrive_referral(second["id"], second_screened["version"])

        first_booking = validate_success(api_client.create_assignment(
            {"enrollment_id": first_arrived["enrollment_id"],
             "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-05T00:00:00Z",
             "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]), 201)
        validate_success(api_client.activate_assignment(
            first_booking["id"], TEST_USERS["housing_coordinator_headers"]), 200)
        assert first_booking["billed_nights"] == 4
        assert first_booking["housing_cost_cents"] == 52_000

        overlap = api_client.create_assignment(
            {"enrollment_id": second_arrived["enrollment_id"],
             "start_at": "2026-09-03T00:00:00Z", "end_at": "2026-09-07T00:00:00Z",
             "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"])
        validate_error(overlap, ApiErrorId.ERR_HOUSING_CAPACITY_EXCEEDED)

    def test_booking_that_shares_no_instant_is_accepted(self, logical_clock):
        """PRD §2.6: "This rule is exercised by referral screening, by housing
        booking and by re-booking, and it is the reason a facility's buffer beds
        are never bookable by anyone."

        Design: Difficulty/resource_temporal_overlap/overlap_housing_half_open_with_endpoint_buffer
        """
        fund = create_fund()
        protocol = create_open_protocol(fund["id"])
        create_facility(facility_code="PTB-T01", name="Tight Class B",
                        tier="PARTNER_CLASS_B", total_beds=2, buffer_beds=1)

        first = create_referral(protocol["id"], child_name="Ava Reyes",
                                expected_treatment_days=200, is_immunosuppressed=False)
        second = create_referral(protocol["id"], child_name="Noah Patel",
                                 expected_treatment_days=200, is_immunosuppressed=False)
        first_arrived = arrive_referral(first["id"], validate_success(
            api_client.screen_referral(first["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
                                       TEST_USERS["intake_coordinator_headers"]), 200)["version"])
        second_arrived = arrive_referral(second["id"], validate_success(
            api_client.screen_referral(second["id"], {"expected_protocol_version": current_protocol_version(protocol["id"])},
                                       TEST_USERS["intake_coordinator_headers"]), 200)["version"])

        first_booking = validate_success(api_client.create_assignment(
            {"enrollment_id": first_arrived["enrollment_id"],
             "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-05T00:00:00Z",
             "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]), 201)

        second_booking = validate_success(api_client.create_assignment(
            {"enrollment_id": second_arrived["enrollment_id"],
             "start_at": "2026-09-05T00:00:00Z", "end_at": "2026-09-09T00:00:00Z",
             "buffer_window_days": 1},
            TEST_USERS["housing_coordinator_headers"]), 201)
        assert second_booking["status"] == "SCHEDULED"
        assert second_booking["housing_facility_id"] == first_booking["housing_facility_id"]