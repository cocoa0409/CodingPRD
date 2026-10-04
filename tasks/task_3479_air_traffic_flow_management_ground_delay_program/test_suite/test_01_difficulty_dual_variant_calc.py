"""Difficulty queue: dual-variant calculations.

Two computed readouts exist in planning/operational (forecast) and
provisional/final (flight delay) variants; each pair must diverge exactly the
way the PRD pins down.
"""

from test_helpers import (
    assert_instant,
    at,
    complete_tmi,
    create_airport,
    create_forecast,
    event_factor,
    expected_delay_minutes,
    expected_predicted_rate,
    get_flight,
    get_operator,
    report_and_confirm_event,
    report_constraint_event,
    set_clock,
    setup_active_gdp,
    update_flight,
)


class TestCapacityForecastVariants:
    def test_planning_vs_operational_variants_diverge(self, api):
        """PRD §3.3: "The two variants therefore differ exactly this way:
        `PLANNING` includes `CONFIRMED` events only, while `OPERATIONAL`
        additionally includes `REPORTED` events at half weight, so identical
        facility data yields a lower-or-equal predicted rate under
        `OPERATIONAL`."
        PRD §3.3: "The `predicted_acceptance_rate` is then the facility's
        `base_acceptance_rate` times the effective multiplier, floored to a
        whole number of flights per hour, with a minimum of 1 — a facility
        never forecasts below one flight per hour."

        Design: Difficulty/dual_variant_calc/capacity_forecast_planning_vs_operational
        """
        set_clock(api)
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        confirmed = report_and_confirm_event(
            api, facility["id"], event_type="WEATHER", severity=2,
            window_start=at("13:00"), window_end=at("16:00"),
        )
        reported = report_constraint_event(
            api, facility["id"], event_type="STAFFING", severity=3,
            window_start=at("13:00"), window_end=at("16:00"),
        )

        planning = create_forecast(
            api, facility["id"], variant="PLANNING",
            window_start=at("13:00"), window_end=at("16:00"),
        )
        operational = create_forecast(
            api, facility["id"], variant="OPERATIONAL",
            window_start=at("13:00"), window_end=at("16:00"),
        )

        assert planning["predicted_acceptance_rate"] == 21, (
            "PLANNING: floor(30 * (1 - 0.15*2)) = 21, got "
            f"{planning['predicted_acceptance_rate']}"
        )
        assert planning["predicted_acceptance_rate"] == expected_predicted_rate(
            30, [event_factor("WEATHER", 2)]
        )
        assert operational["predicted_acceptance_rate"] == 17, (
            "OPERATIONAL: floor(30 * 0.70 * (1 - 0.10*3*0.5)) = 17, got "
            f"{operational['predicted_acceptance_rate']}"
        )
        assert operational["predicted_acceptance_rate"] == expected_predicted_rate(
            30, [event_factor("WEATHER", 2), event_factor("STAFFING", 3, 0.5)]
        )
        assert planning["predicted_acceptance_rate"] != operational["predicted_acceptance_rate"], (
            "identical inputs must diverge by variant selection alone"
        )
        assert planning["included_event_ids"] == [confirmed["id"]], (
            "PLANNING includes CONFIRMED events only"
        )
        assert set(operational["included_event_ids"]) == {confirmed["id"], reported["id"]}, (
            "OPERATIONAL additionally includes the REPORTED event"
        )


class TestFlightDelayVariants:
    def test_provisional_vs_final_delay_diverge(self, api):
        """PRD §3.9: "Completion performs the FINAL delay attribution for each
        controlled flight: the flight's self-inflicted minutes are the
        whole-minute floor of its `estimated_arrival` minus `scheduled_arrival`,
        never below zero, counting only when the operator's last ETA report
        pushed the estimate beyond the schedule — otherwise zero — and its
        `final_delay_minutes` is then its `provisional_delay_minutes` minus
        those self-inflicted minutes, never below zero."
        PRD §3.9: "Each operator's `cumulative_delay_minutes` grows by the sum
        of `final_delay_minutes` over that operator's flights in the program,
        and the ledgers are reconciled."

        Design: Difficulty/dual_variant_calc/flight_delay_provisional_vs_final
        """
        world = setup_active_gdp(api)
        flights = world["flights"]
        f4, f5 = flights[3], flights[4]  # BAL4 sched 13:15, BAL5 sched 13:26
        op_b = world["operators"][1]

        # BAL4's operator reports an ETA 10 minutes beyond schedule and goes
        # AIRBORNE; the helper re-reads the OCC version first.
        update_flight(api, f4, new_eta=at("13:25"), new_ops_status="AIRBORNE")

        complete_tmi(api, world["tmi"]["id"])

        f4_after = get_flight(api, f4["id"])
        f5_after = get_flight(api, f5["id"])
        assert f4_after["provisional_delay_minutes"] == 5, (
            f"CTA 13:20 vs schedule 13:15 -> 5, got {f4_after['provisional_delay_minutes']}"
        )
        assert f4_after["final_delay_minutes"] == 0, (
            "max(0, 5 - self_inflicted 10) = 0, got "
            f"{f4_after['final_delay_minutes']}"
        )
        assert f5_after["provisional_delay_minutes"] == 14
        assert f5_after["final_delay_minutes"] == 14, (
            "no ETA slip (estimated == scheduled 13:26) keeps final == provisional"
        )
        assert f5_after["final_delay_minutes"] == expected_delay_minutes(
            f5_after["controlled_arrival"], f5_after["scheduled_arrival"]
        )
        assert_instant(f4_after["controlled_arrival"], at("13:20"), "f4 CTA")
        op_b_after = get_operator(api, op_b["id"])
        assert op_b_after["cumulative_delay_minutes"] == 14, (
            f"0 from BAL4 + 14 from BAL5, got {op_b_after['cumulative_delay_minutes']}"
        )
