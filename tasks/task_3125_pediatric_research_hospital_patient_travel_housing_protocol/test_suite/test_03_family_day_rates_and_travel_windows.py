"""Queue A — family-support day rates, travel stamps and leg windows."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fund, create_open_protocol, create_facility, create_referral,
    screen_referral, arrive_referral, sign_consent, create_pledge, accrue_pledge,
    setup_hiatused_pledge, setup_treated_family, set_clock,
    TEST_USERS, ApiErrorId,
)


class TestFamilyDayStarterVersusTierRate:

    def test_settlement_uses_the_resolved_state_rate(self, logical_clock):
        """PRD §3.5: "Settlement resolves the per-traveler-day rate from the
        family's `household_state_code`: a family from `TX`, `OK`, `AR`, `MS`,
        `AL`, `LA`, `TN`, `MO`, or `KY` resolves to 15000 cents per day"

        Design: Difficulty/dual_variant_calc/dual_variant_family_day_starter_rate_vs_tier_rated
        """
        fund, protocol = setup_fund_and_open_pair()
        _, _, pledge, _ = setup_hiatused_pledge(
            fund, protocol, accrue_days=4, pledge_budget_cents=12000,
            household_state_code="TN", is_immunosuppressed=True,
        )
        # PRD §3.5: "a hiatus settles the current pledge". The hiatus in the
        # preamble already ran the settlement, so the row is already
        # SETTLED_FINAL; re-settling it would report ERR_PLEDGE_SETTLE_NOT_ACTIVE.
        settled = get_success_data(api_client.get_pledge(
            pledge["id"], TEST_USERS["any_headers"]))
        assert settled["covered_days"] == 5
        assert settled["final_settled_cents"] == 75_000
        assert settled["status"] == "SETTLED_FINAL"

    def test_provisional_starter_rate_diverges_from_the_final_rate(self, logical_clock):
        """PRD §3.5: "Each accrual adds the days to `covered_days` and recomputes
        `provisional_settled_cents` as the accrued days multiplied by 450 cents —
        the starter per-family-day rate that applies before the family's home
        state is resolved."

        Design: Difficulty/dual_variant_calc/dual_variant_family_day_starter_rate_vs_tier_rated
        """
        fund, protocol = setup_fund_and_open_pair()
        _, _, pledge, _ = setup_hiatused_pledge(
            fund, protocol, accrue_days=4, pledge_budget_cents=12000,
            household_state_code="TN", is_immunosuppressed=True,
        )
        # PRD §3.5: "a hiatus settles the current pledge". The hiatus in the
        # preamble already ran the settlement, so the row is already
        # SETTLED_FINAL; re-settling it would report ERR_PLEDGE_SETTLE_NOT_ACTIVE.
        settled = get_success_data(api_client.get_pledge(
            pledge["id"], TEST_USERS["any_headers"]))
        assert settled["provisional_settled_cents"] == 2_250
        assert settled["final_settled_cents"] == 75_000
        assert settled["final_settled_cents"] - settled["provisional_settled_cents"] == 72_750
        assert settled["billing_permitted_cents"] == 0

    def test_far_state_rate_is_twenty_two_thousand(self, logical_clock):
        """PRD §3.5: "a family from `CA`, `NY`, `IL`, `WA`, `MA`, `NJ`, `CT`,
        `OR`, or `MD` resolves to 22000 cents per day; every other state resolves
        to 18000 cents per day."

        Design: Difficulty/dual_variant_calc/dual_variant_family_day_starter_rate_vs_tier_rated
        """
        fund, protocol = setup_fund_and_open_pair()
        _, _, pledge, _ = setup_hiatused_pledge(
            fund, protocol, accrue_days=4, pledge_budget_cents=12000,
            household_state_code="MA", is_immunosuppressed=True,
        )
        # PRD §3.5: "a hiatus settles the current pledge". The hiatus in the
        # preamble already ran the settlement, so the row is already
        # SETTLED_FINAL; re-settling it would report ERR_PLEDGE_SETTLE_NOT_ACTIVE.
        settled = get_success_data(api_client.get_pledge(
            pledge["id"], TEST_USERS["any_headers"]))
        assert settled["covered_days"] == 5
        assert settled["final_settled_cents"] == 110_000
        assert settled["final_settled_cents"] != 75_000


def setup_fund_and_open_pair():
    """Clock + fund + one OPEN 10000000-cent protocol, no residences."""
    set_clock()
    fund = create_fund()
    protocol = get_success_data(api_client.create_protocol(
        {
            "fund_id": fund["id"], "protocol_code": "ALL-INT-001",
            "disease_group": "ALL", "age_min_years": 5, "age_max_years": 17,
            "required_stage": "NEWLY_DIAGNOSED",
            "protocol_budget_cents": 10_000_000, "capacity": 8,
        },
        TEST_USERS["protocol_coordinator_headers"],
    ))
    protocol = get_success_data(api_client.open_protocol(
        protocol["id"], TEST_USERS["protocol_coordinator_headers"]))
    return fund, protocol


class TestTravelStampExpiry:

    def test_expired_confirmation_cannot_be_disbursed(self, logical_clock):
        """PRD §3.6: "That stamp is a perishable token: a confirmation is only
        good for 30 days, and a disbursement attempted once the logical clock has
        moved to or past `eligibility_confirmed_at` plus 30 days is refused with
        `ERR_TRAVEL_COVERAGE_EXPIRED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/non_linear_travel_stamp_expiry_then_fresh_request_loop
        """
        fund, protocol = setup_fund_and_open_pair()
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)
        enrollment_id, leg = setup_confirmed_leg(fund, protocol)

        get_success_data(api_client.set_current_utc(
            {"current_utc": "2026-10-05T12:00:00Z"}, TEST_USERS["platform_admin_headers"]))

        res = api_client.disburse_travel(leg["id"], TEST_USERS["patient_support_officer_headers"])
        validate_error(res, ApiErrorId.ERR_TRAVEL_COVERAGE_EXPIRED)

    def test_expired_leg_is_retired_by_cancellation_not_disbursed(self, logical_clock):
        """PRD §3.6: "A plain cancellation is lighter: it is available while the
        leg is `REQUESTED` or `CONFIRMED` — anything else reports
        `ERR_TRAVEL_NOT_CANCELLABLE` (HTTP 409) — moves the leg to `CANCELLED`,
        and, for a leg that had already stamped `eligibility_confirmed_at`,
        reverses no fee."

        Design: Difficulty/non_linear_state_machine/non_linear_travel_stamp_expiry_then_fresh_request_loop
        """
        fund, protocol = setup_fund_and_open_pair()
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)
        enrollment_id, leg = setup_confirmed_leg(fund, protocol)

        get_success_data(api_client.set_current_utc(
            {"current_utc": "2026-10-05T12:00:00Z"}, TEST_USERS["platform_admin_headers"]))
        cancelled = validate_success(
            api_client.cancel_travel(leg["id"], TEST_USERS["patient_support_officer_headers"]), 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["transport_cost_cents"] == 0

        fresh = validate_success(api_client.request_travel(
            enrollment_id,
            {"mode": "AIR_ECONOMY", "traveler_count": 2,
             "departure_at": "2026-10-06T00:00:00Z", "return_at": "2026-10-13T00:00:00Z",
             "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True},
            TEST_USERS["patient_support_officer_headers"]), 201)
        assert fresh["status"] == "REQUESTED"


def setup_confirmed_leg(fund, protocol):
    """Housed, treated family plus one CONFIRMED leg stamped 2026-09-01.

    The pool these tests register is a single campus residence, so the family is
    immunosuppressed and therefore bands to ON_CAMPUS (PRD §2.6).
    """
    _, enrollment_id, _ = setup_treated_family(fund, protocol, is_immunosuppressed=True)
    leg = get_success_data(api_client.request_travel(
        enrollment_id,
        {"mode": "AIR_ECONOMY", "traveler_count": 2,
         "departure_at": "2026-09-05T00:00:00Z", "return_at": "2026-09-12T00:00:00Z",
         "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True},
        TEST_USERS["patient_support_officer_headers"]))
    confirmed = validate_success(
        api_client.confirm_travel(leg["id"], TEST_USERS["patient_support_officer_headers"]), 200)
    assert confirmed["eligibility_confirmed_at"] == "2026-09-01T00:00:00.000Z"
    return enrollment_id, confirmed


class TestTravelLegOverlap:

    def test_adjacent_window_collides_on_the_arrival_boundary(self, logical_clock):
        """PRD §3.6: "no already-confirmed leg for the same enrollment and the
        same mode may have a travel window that collides on the arrival
        boundary, which reports `ERR_TRAVEL_LEG_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_travel_gap_tolerant_mode_window
        """
        fund, protocol = setup_fund_and_open_pair()
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)
        enrollment_id, _ = setup_confirmed_leg(fund, protocol)

        adjacent = get_success_data(api_client.request_travel(
            enrollment_id,
            {"mode": "AIR_ECONOMY", "traveler_count": 2,
             "departure_at": "2026-09-12T00:00:00Z", "return_at": "2026-09-19T00:00:00Z",
             "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True},
            TEST_USERS["patient_support_officer_headers"]))
        res = api_client.confirm_travel(adjacent["id"], TEST_USERS["patient_support_officer_headers"])
        validate_error(res, ApiErrorId.ERR_TRAVEL_LEG_OVERLAP)

        still = get_success_data(api_client.get_travel(adjacent["id"], TEST_USERS["any_headers"]))
        assert still["status"] == "REQUESTED"

    def test_one_day_gap_is_accepted(self, logical_clock):
        """PRD §3.6: "Each element of `placed_coverages` carries a `plan_code`, a
        `coverage_id` that may be null, a `travel_window_start_at`, a
        `travel_window_end_at`, an integer `coverage_cents`, and a
        `covers_required_travel` boolean."

        Design: Difficulty/resource_temporal_overlap/overlap_travel_gap_tolerant_mode_window
        """
        fund, protocol = setup_fund_and_open_pair()
        create_facility(facility_code="ONC-01", total_beds=4, buffer_beds=0)
        enrollment_id, _ = setup_confirmed_leg(fund, protocol)

        gapped = get_success_data(api_client.request_travel(
            enrollment_id,
            {"mode": "AIR_ECONOMY", "traveler_count": 2,
             "departure_at": "2026-09-13T00:00:00Z", "return_at": "2026-09-20T00:00:00Z",
             "trip_reason": "PROTOCOL_REVIEW", "is_required_travel": True},
            TEST_USERS["patient_support_officer_headers"]))
        confirmed = validate_success(
            api_client.confirm_travel(gapped["id"], TEST_USERS["patient_support_officer_headers"]), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["family_day_units"] == 14