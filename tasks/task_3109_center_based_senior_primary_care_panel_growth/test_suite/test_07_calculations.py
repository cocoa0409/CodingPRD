"""Settlement accrual variants, cost-booking aggregation, risk-adjusted PMPM
quotes, profitability-tier boundaries, and the outcome-adjusted panel value."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_attribution,
    adjudicate_claim,
    create_appointment,
    create_attribution,
    create_completed_appointment,
    create_cost_claim_payload,
    create_dispatched_ride,
    create_health_plan,
    create_health_plan_payload,
    create_no_show_appointment,
    create_open_center,
    create_open_settlement,
    create_patient,
    create_triage_case_payload,
    create_vehicle_payload,
    get_success_data,
    set_clock,
    setup_panel_with_active_patient,
    validate_success,
)
from test_helpers import TEST_USERS

NET = TEST_USERS["network_operator_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]
FA = TEST_USERS["finance_analyst_headers"]
FC = TEST_USERS["finance_controller_headers"]
FRONT = TEST_USERS["front_desk_headers"]
DISP = TEST_USERS["transport_dispatcher_headers"]


def create_appointment_ride_completion(api, center, team, room, patient, vehicle):
    """Schedule a 20-minute PRIMARY appointment, dispatch a ride, then check in
    and complete so the ride auto-delivers (3200 transport booking)."""
    from test_helpers import make_care_team_lead_headers

    appt = create_appointment(
        team["id"], patient["id"], room["id"],
        start_utc="2026-09-12T14:00:00Z", duration_minutes=20, kind="PRIMARY",
    )
    _, dispatched = create_dispatched_ride(appt["id"], vehicle["id"])
    set_clock("2026-09-12T13:50:00Z")  # inside check-in window [13:30, 14:20]
    validate_success(api.check_in_appointment(appt["id"], FRONT), 200)
    completed = validate_success(
        api.complete_appointment(appt["id"], make_care_team_lead_headers(team["id"])),
        200,
    )
    ride = get_success_data(api.get_ride_request(dispatched["id"], DISP))
    assert ride["status"] == "DELIVERED"
    return completed


class TestAccrualDualVariant:
    def _setup_mid_month_panel(self, api):
        """Center opened 2026-01-01; plan base 90000, factor 1.00, share 1.00.
        Patient PB activated 2026-09-01 (whole month), patient PA activated
        2026-09-15 (16 of 30 days: Sep 15..30 inclusive)."""
        set_clock("2026-09-01T00:00:00Z")
        center, team, room = create_open_center(opened_on="2026-01-01")
        plan = create_health_plan(
            plan_name="MA Gold", base_pmpm_cents=90000,
            risk_adjust_factor=1.00, revenue_share_pct=1.00,
        )
        pa = create_patient(full_name="Ana", risk_score=1.00)
        pb = create_patient(full_name="Bob", risk_score=1.00)
        attr_a = create_attribution(pa["id"], plan["id"], team["id"], effective_month="2026-09")
        attr_b = create_attribution(pb["id"], plan["id"], team["id"], effective_month="2026-09")
        activate_attribution(attr_b["id"])  # activated on 2026-09-01
        set_clock("2026-09-15T00:00:00Z")
        activate_attribution(attr_a["id"])  # activated on 2026-09-15
        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        return center, team, settlement

    def test_provisional_fullmonth_variant(self, api):
        """PRD §3.8: "The two variants differ in how `member_months` are counted: at
        provisional close, any patient active at least one day in the period counts a full
        member month of 1 (late-arriving claims do not change member months); at finalize,
        member months are day-prorated as days active in the period divided by days in the
        period, producing a delta against the provisional figure that posts to the center
        ledger."
        PRD §3.8: "the base per-member-per-month amount is the plan's `base_pmpm_cents`
        multiplied by the plan's `risk_adjust_factor` and the patient's `risk_score`."

        Design: Difficulty/dual_variant_calc/settlement_accrual_fullmonth_vs_dayproration_variants
        """
        center, team, settlement = self._setup_mid_month_panel(api)
        center_now = get_success_data(api.get_center(center["id"], NET))
        provisional = validate_success(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            ),
            200,
        )
        # 2 patients x full month x 90000 x 1.00 x 1.00 x share 1.00
        assert provisional["accrued_revenue_cents"] == 180000

    def test_finalize_day_proration_variant_and_ledger_delta(self, api):
        """PRD §3.8: "The two variants differ in how `member_months` are counted: at
        provisional close, any patient active at least one day in the period counts a full
        member month of 1 (late-arriving claims do not change member months); at finalize,
        member months are day-prorated as days active in the period divided by days in the
        period, producing a delta against the provisional figure that posts to the center
        ledger."
        PRD §3.8: "Each patient's active interval runs from the logical-clock date of the
        `PENDING → ACTIVE` transition (or the period start, whichever is later) through
        the logical-clock date of disenrollment (or the period end, whichever is earlier),
        inclusive of both endpoints, and days-in-month follows the calendar."
        PRD §3.8: "Each patient's contribution is computed at full precision, rounded
        half-up to whole cents **first**, and only then summed into
        `accrued_revenue_cents`."

        Design: Difficulty/dual_variant_calc/settlement_accrual_fullmonth_vs_dayproration_variants
        """
        center, team, settlement = self._setup_mid_month_panel(api)
        center_now = get_success_data(api.get_center(center["id"], NET))
        validate_success(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            ),
            200,
        )
        finalized = validate_success(api.finalize_settlement(settlement["id"], FC), 200)
        # PA: round_half_up(90000 * 16/30) = 48000; PB: 90000.
        assert finalized["accrued_revenue_cents"] == 138000
        assert finalized["contribution_cents"] == (
            finalized["accrued_revenue_cents"] - finalized["total_cost_of_care_cents"]
        )

        center_after = get_success_data(api.get_center(center["id"], NET))
        # Provisional posted 180000, finalize delta -42000 -> net 138000.
        assert center_after["cumulative_contribution_cents"] == 138000


class TestCostBookingAggregation:
    def test_booking_line_then_sum_rounding_vs_sum_then_round(self, api):
        """PRD §2.6: "Where a rule computes a per-line or per-patient amount, each such
        amount is rounded half-up to whole cents first and only then summed into
        aggregates; reversing that order (summing at full precision and rounding once)
        yields different cents and is not the rule."
        PRD §3.8: "An internal visit books at a base by `kind` — 18000 cents for
        `PRIMARY`, 22000 cents for `BEHAVIORAL`, 9000 cents for `CHW_OUTREACH` — scaled by
        duration as a multiplier of `duration_minutes` over 40 (0.5 for 20 minutes, 1.0
        for 40, 1.5 for 60); a no-show books at half the scaled amount, rounded half-up to
        whole cents. Each `DELIVERED` or `FAILED_NO_SHOW` ride books a flat 3200 cents of
        `TRANSPORT` cost."
        PRD §2.8: "the period's `total_cost_of_care_cents` is computed first as the sum of
        adjudicated claims plus internal visit bookings plus transport bookings."

        Design: Difficulty/combinatorial_formula/booking_line_then_sum_rounding_vs_sum_then_round
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        vehicle = get_success_data(
            api.create_vehicle(center["id"], create_vehicle_payload(), NET)
        )

        # No-show PRIMARY 20-minute: 18000 * 0.5 * 0.5 = 4500.
        create_no_show_appointment(
            team, patient["id"], room["id"],
            sweep_utc="2026-09-10T15:00:00Z",
            start_utc="2026-09-10T14:00:00Z", duration_minutes=20, kind="PRIMARY",
        )
        # Completed BEHAVIORAL 60-minute: 22000 * 1.5 = 33000.
        appt_b = create_completed_appointment(
            team, patient["id"], room["id"],
            start_utc="2026-09-11T14:00:00Z", checkin_clock="2026-09-11T14:00:00Z",
            duration_minutes=60, kind="BEHAVIORAL",
        )
        assert appt_b["cost_cents"] == 33000

        # Completed 20-minute PRIMARY whose dispatched ride auto-delivers on
        # completion: visit books 18000 * 0.5 = 9000, ride books 3200 flat.
        appt_r = create_appointment_ride_completion(
            api, center, team, room, patient, vehicle
        )

        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        center_now = get_success_data(api.get_center(center["id"], NET))
        provisional = validate_success(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            ),
            200,
        )
        # Per-line bookings summed after per-line rounding:
        # 4500 (no-show PRIMARY 20) + 33000 (BEHAVIORAL 60)
        # + 9000 (PRIMARY 20) + 3200 (DELIVERED ride) == 49700.
        assert provisional["total_cost_of_care_cents"] == 49700

    def test_per_line_rounding_no_show_chw(self, api):
        """PRD §3.8: "An internal visit books at a base by `kind` — 18000 cents for
        `PRIMARY`, 22000 cents for `BEHAVIORAL`, 9000 cents for `CHW_OUTREACH` — scaled by
        duration as a multiplier of `duration_minutes` over 40 (0.5 for 20 minutes, 1.0
        for 40, 1.5 for 60); a no-show books at half the scaled amount, rounded half-up to
        whole cents."
        PRD §2.6: "Where a rule computes a per-line or per-patient amount, each such
        amount is rounded half-up to whole cents first and only then summed into
        aggregates; reversing that order (summing at full precision and rounding once)
        yields different cents and is not the rule."

        Design: Difficulty/combinatorial_formula/booking_line_then_sum_rounding_vs_sum_then_round
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        appt = create_no_show_appointment(
            team, patient["id"], room["id"],
            sweep_utc="2026-09-10T15:00:00Z",
            start_utc="2026-09-10T14:00:00Z", duration_minutes=20, kind="CHW_OUTREACH",
        )
        # round_half_up(9000 * 0.5 * 0.5) == 2250 at the booking line.
        assert appt["cost_cents"] == 2250


class TestRiskAdjustedQuote:
    def test_quote_nonlinear_three_input_tier_branch(self, api):
        """PRD §3.3: "the quote multiplies the plan's `base_pmpm_cents` by the patient's
        `risk_score` — clamped to the inclusive range 0.50 through 4.00 — and by the
        plan's `risk_adjust_factor`, then applies a maturity multiplier taken from the
        center's `profitability_tier` at quote time: 0.95 while the center is `RAMP`,
        1.00 at `BREAKEVEN`, and 1.05 at `MATURE`. The product is rounded half-up to whole
        cents and returned as `quote_cents`, alongside `tier_applied` naming the tier
        whose multiplier was used."

        Design: Difficulty/combinatorial_formula/quote_nonlinear_three_input_tier_branch
        """
        plan = create_health_plan(
            plan_name="MA Silver", base_pmpm_cents=90000,
            risk_adjust_factor=1.20, revenue_share_pct=0.90,
        )
        # Center A opened 2026-06-01: 3 maturity months at the default clock -> RAMP.
        center_a = get_success_data(
            api.create_center(
                {"name": "A", "neighborhood_code": "CHI-A", "opened_on": "2026-06-01"},
                NET,
            )
        )
        quote = validate_success(
            api.get_plan_quote(
                plan["id"], {"risk_score": 2.00, "center_id": center_a["id"]}, FA
            ),
            200,
        )
        assert quote["tier_applied"] == "RAMP"
        # round_half_up(90000 * 2.00 * 1.20 * 0.95) == 205200
        assert quote["quote_cents"] == 205200

    def test_quote_combines_three_multiplicative_inputs(self, api):
        """PRD §3.3: "the quote multiplies the plan's `base_pmpm_cents` by the patient's
        `risk_score` — clamped to the inclusive range 0.50 through 4.00 — and by the
        plan's `risk_adjust_factor`, then applies a maturity multiplier taken from the
        center's `profitability_tier` at quote time: 0.95 while the center is `RAMP`,
        1.00 at `BREAKEVEN`, and 1.05 at `MATURE`. The product is rounded half-up to whole
        cents and returned as `quote_cents`, alongside `tier_applied` naming the tier
        whose multiplier was used."

        Design: Difficulty/combinatorial_formula/quote_nonlinear_three_input_tier_branch
        """
        plan = create_health_plan(
            plan_name="MA Bronze", base_pmpm_cents=90000,
            risk_adjust_factor=1.20, revenue_share_pct=0.90,
        )
        center = get_success_data(
            api.create_center(
                {"name": "B", "neighborhood_code": "CHI-B", "opened_on": "2026-06-01"},
                NET,
            )
        )
        # Same RAMP center, different risk input: 90000 * 1.50 * 1.20 * 0.95.
        quote = validate_success(
            api.get_plan_quote(
                plan["id"], {"risk_score": 1.50, "center_id": center["id"]}, FA
            ),
            200,
        )
        assert quote["tier_applied"] == "RAMP"
        assert quote["quote_cents"] == 153900

    def test_quote_at_mature_boundary_fill_ratio_exactly_three_quarters(self, api):
        """PRD §3.8: "Boundaries are inclusive on the lower side: a center at exactly 12
        maturity months exits `RAMP` only when cumulative contribution is non-negative,
        and a fill ratio of exactly 0.7500 qualifies for `MATURE`."
        PRD §3.3: "the quote multiplies the plan's `base_pmpm_cents` by the patient's
        `risk_score` — clamped to the inclusive range 0.50 through 4.00 — and by the
        plan's `risk_adjust_factor`, then applies a maturity multiplier taken from the
        center's `profitability_tier` at quote time: 0.95 while the center is `RAMP`,
        1.00 at `BREAKEVEN`, and 1.05 at `MATURE`."

        Design: Corner/calculations/quote_at_mature_boundary_fill_ratio_exactly_three_quarters
        """
        # Opened 2025-01-01 -> maturity_months >= 12 at the 2026-09 clock.
        center, team, room = create_open_center(opened_on="2025-01-01")
        get_success_data(api.patch_care_team(team["id"], {"panel_cap": 4}, NET))
        plan = create_health_plan(
            base_pmpm_cents=90000, risk_adjust_factor=1.00, revenue_share_pct=1.00
        )
        # Fill the panel to exactly 3 active of cap 4 -> fill ratio 0.7500.
        for i in range(3):
            p = create_patient(full_name=f"Panel {i}")
            a = create_attribution(p["id"], plan["id"], team["id"])
            activate_attribution(a["id"])
        # Revenue-only provisional close + finalize at non-negative contribution
        # (revenue exceeds zero cost) recomputes the tier to MATURE.
        settlement = create_open_settlement(center["id"], "2026-09")
        set_clock("2026-10-01T00:00:00Z")
        center_now = get_success_data(api.get_center(center["id"], NET))
        validate_success(
            api.close_provisional_settlement(
                settlement["id"], {"expected_center_version": center_now["version"]}, FA
            ),
            200,
        )
        validate_success(api.finalize_settlement(settlement["id"], FC), 200)

        center_after = get_success_data(api.get_center(center["id"], NET))
        assert center_after["panel_fill_ratio"] == pytest.approx(0.75, abs=1e-9)
        assert center_after["profitability_tier"] == "MATURE"

        quote = validate_success(
            api.get_plan_quote(
                plan["id"], {"risk_score": 1.00, "center_id": center["id"]}, FA
            ),
            200,
        )
        assert quote["tier_applied"] == "MATURE"
        # round_half_up(90000 * 1.00 * 1.00 * 1.05) == 94500
        assert quote["quote_cents"] == 94500
