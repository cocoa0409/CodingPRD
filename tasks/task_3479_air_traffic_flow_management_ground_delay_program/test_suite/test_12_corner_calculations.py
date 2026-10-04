"""Corner queue: calculation constants, input-set filtering, tie-breaks,
overflow, and bucket rollover."""

from test_helpers import (
    ApiErrorId,
    activate_tmi,
    assert_instant,
    at,
    clear_event,
    create_airport,
    create_carrier,
    create_forecast,
    create_published_forecast,
    event_factor,
    expected_hourly_bucket,
    expected_predicted_rate,
    file_flight,
    get_flight,
    ledger_for,
    list_flight_slots,
    list_tmi_ledgers,
    list_tmi_slots,
    propose_gdp,
    publish_tmi,
    report_and_confirm_event,
    reroute_assignment_payload,
    run_compression,
    set_clock,
    setup_active_gdp,
    setup_airport_with_confirmed_events,
    setup_reroute_scenario,
    update_flight,
    assign_reroute,
    validate_error,
    FLOW_MANAGER_HEADERS,
)


class TestForecastFloorClamp:
    def test_multiplier_never_below_ten_percent(self, api):
        """PRD §3.3: "Multiplying all included events' factors together yields
        the raw multiplier; the effective multiplier is the raw multiplier but
        never below `MIN_CAPACITY_FLOOR_PCT` (10) percent, that is, never below
        0.10. The `predicted_acceptance_rate` is then the facility's
        `base_acceptance_rate` times the effective multiplier, floored to a
        whole number of flights per hour, with a minimum of 1 — a facility
        never forecasts below one flight per hour."

        Design: Corner/calculations/forecast_floor_clamp
        """
        world = setup_airport_with_confirmed_events(
            api,
            [
                ("WEATHER", 5, "13:00", "14:00"),
                ("STAFFING", 5, "13:00", "14:00"),
                ("EQUIPMENT", 5, "13:00", "14:00"),
            ],
        )
        forecast = create_forecast(
            api, world["facility"]["id"], variant="PLANNING",
            window_start=at("13:00"), window_end=at("15:00"),
        )
        # raw multiplier 0.25 * 0.50 * 0.75 = 0.09375 < 0.10 -> clamped
        assert forecast["predicted_acceptance_rate"] == 3, (
            "floor(30 * 0.10) = 3; without the clamp this would be 2"
        )
        assert forecast["predicted_acceptance_rate"] == expected_predicted_rate(
            30, [event_factor("WEATHER", 5), event_factor("STAFFING", 5),
                 event_factor("EQUIPMENT", 5)]
        )
        assert set(forecast["included_event_ids"]) == {
            e["id"] for e in world["events"]
        }


class TestForecastExcludesClearedEvents:
    def test_cleared_event_leaves_the_input_set(self, api):
        """PRD §3.3: "The input set is the facility's constraint events whose
        half-open windows overlap the forecast window; `CLEARED` events are
        always excluded."

        Design: Corner/calculations/forecast_excludes_cleared_events
        """
        set_clock(api)
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        event = report_and_confirm_event(
            api, facility["id"], event_type="WEATHER", severity=4,
            window_start=at("13:00"), window_end=at("15:00"),
        )
        clear_event(api, event["id"])
        forecast = create_forecast(
            api, facility["id"], variant="PLANNING",
            window_start=at("13:00"), window_end=at("15:00"),
        )
        assert forecast["predicted_acceptance_rate"] == 30, (
            "including the cleared event would give floor(30 * 0.40) = 12"
        )
        assert forecast["included_event_ids"] == []


class TestRbsTieBreakCreatedAt:
    def test_equal_schedules_rank_by_created_at(self, api):
        """PRD §3.4: "Eligible flights are ranked by `scheduled_arrival`
        ascending with `created_at` ascending as the tie-break — original
        schedule order — and the j-th flight in that order takes the j-th
        non-reserved slot ascending in `slot_time`."

        Design: Corner/calculations/rbs_tie_break_created_at
        """
        set_clock(api)  # 12:00
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        op_a, op_a_headers = create_carrier(api, "Alpha Air")
        op_b, op_b_headers = create_carrier(api, "Bravo Air")
        create_published_forecast(
            api, facility["id"], variant="PLANNING",
            window_start=at("13:00"), window_end=at("15:00"),
        )
        tmi = propose_gdp(
            api, facility["id"], program_start=at("13:00"),
            program_end=at("15:00"), controlled_rate=6,
        )
        publish_tmi(api, tmi["id"])
        earlier = file_flight(
            api, op_b, facility["id"], designator="BAL1",
            scheduled_arrival=at("13:10"), headers=op_b_headers,
        )  # created at 12:00
        set_clock(api, at("12:01"))
        later = file_flight(
            api, op_a, facility["id"], designator="AAL1",
            scheduled_arrival=at("13:10"), headers=op_a_headers,
        )  # created at 12:01, same schedule

        activate_tmi(api, tmi["id"])

        assert_instant(
            get_flight(api, earlier["id"])["controlled_arrival"], at("13:00"),
            "earlier created_at wins the earlier slot",
        )
        assert_instant(
            get_flight(api, later["id"])["controlled_arrival"], at("13:10"),
            "the later-filed flight takes the next slot",
        )


class TestRbsOverflowVirtualCta:
    def test_third_flight_overflows_to_program_end(self, api):
        """PRD §3.4: "Flights beyond the last non-reserved slot are overflow:
        each receives the program's `program_end` as a virtual
        `controlled_arrival` with no ArrivalSlot row, is flagged `is_overflow`,
        and stays `UNCONTROLLED`."
        PRD §3.9: "recording a `flight_count` — the operator's flights holding
        slots or virtual CTAs in the program, set at activation and decremented
        on cancellation removal"

        Design: Corner/calculations/rbs_overflow_virtual_cta
        """
        world = setup_active_gdp(
            api, program_start="13:00", program_end="13:30",
            carrier_names=("Alpha Air",),
            flight_specs=(
                (0, "AAL1", "13:01"), (0, "AAL2", "13:02"), (0, "AAL3", "13:03"),
            ),
        )
        f1, f2, f3 = world["flights"]
        f3_after = get_flight(api, f3["id"])
        assert_instant(f3_after["controlled_arrival"], at("13:30"), "virtual CTA == program_end")
        assert f3_after["is_overflow"] is True
        assert f3_after["control_status"] == "UNCONTROLLED"

        slots, meta = list_tmi_slots(api, world["tmi"]["id"])
        assert meta["total_count"] == 3
        assigned = [s for s in slots if s["status"] == "ASSIGNED"]
        assert {s["assigned_flight_id"] for s in assigned} == {f1["id"], f2["id"]}
        last = {s["slot_index"]: s for s in slots}[2]
        assert last["status"] == "OPEN" and last["is_ga_reserved"] is True

        rows, _ = list_flight_slots(api, f3["id"])
        assert rows == [], "an overflow flight holds no ArrivalSlot row"

        ledger = ledger_for(
            list_tmi_ledgers(api, world["tmi"]["id"]), world["operators"][0]["id"]
        )
        assert ledger["flight_count"] == 3, "overflow flights carry virtual CTAs and still count"


class TestCompressionZeroReleaseNoMoves:
    def test_compression_without_cancellation_is_a_noop_pass(self, api):
        """PRD §3.5: "Passes repeat until a pass makes zero moves or
        `COMPRESSION_MAX_PASSES` (3) passes have run; the recorded
        `passes_executed` counts the final no-move pass and is at least 1. At
        the end, every `RELEASED` slot still unclaimed returns to `OPEN` — the
        only way a released slot comes back — and the **CompressionRun** record
        is written: `released_slot_count` (the number of `RELEASED` slots that
        entered the pool), `moves_made` (total carrier flight moves across all
        passes), `passes_executed`, `promoted_ga_request_ids` (the waitlisted
        requests promoted during the run, possibly empty), and
        `remaining_open_slots` (slots `OPEN` after the run, counting
        never-assigned and unclaimed released slots alike)."

        Design: Corner/calculations/compression_zero_release_no_moves
        """
        world = setup_active_gdp(
            api, carrier_names=("Alpha Air",), flight_specs=((0, "AAL1", "13:05"),)
        )
        run = run_compression(api, world["tmi"]["id"])
        assert run["released_slot_count"] == 0
        assert run["moves_made"] == 0
        assert run["passes_executed"] == 1, "the mandatory first pass finds nothing"
        assert run["remaining_open_slots"] == 11, "12 slots minus 1 ASSIGNED"
        assert_instant(
            get_flight(api, world["flights"][0]["id"])["controlled_arrival"],
            at("13:00"), "the untouched holder keeps its slot",
        )


class TestRerouteHourlyBucketRollover:
    def test_bucket_boundary_and_eta_rollover(self, api):
        """PRD §3.8: "Capacity is enforced per sector per hour: the
        assignment's `hourly_bucket` is the flight's `estimated_arrival`
        truncated to the hour, and the load is the count of existing
        assignments sharing the same `via_sector_id` and `hourly_bucket`. The
        assignment is rejected with `ERR_SECTOR_CAPACITY_EXCEEDED` (HTTP 422)
        whenever the load has already reached the sector's
        `base_acceptance_rate` — the boundary is exact: a load one below the
        rate accepts, a load equal to the rate rejects."

        Design: Corner/calculations/reroute_hourly_bucket_rollover
        """
        world = setup_reroute_scenario(
            api, sector_base_rate=1, flight_etas=("13:59", "13:59")
        )
        sector = world["sector"]
        tmi_id = world["tmi"]["id"]
        x1, x2 = world["flights"]

        first = assign_reroute(api, tmi_id, x1["id"], sector["id"])
        assert_instant(first["hourly_bucket"], at("13:00"), "13:59 truncates to 13:00")

        # load 1 == rate 1: the == case rejects
        resp = api.create_reroute_assignment(
            tmi_id,
            reroute_assignment_payload(
                flight_id=x2["id"], via_sector_id=sector["id"], assigned_route="J60"
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_SECTOR_CAPACITY_EXCEEDED)

        # rolling the ETA into the empty 14:00 bucket admits the same request
        update_flight(api, x2, new_eta=at("14:00"))
        second = assign_reroute(api, tmi_id, x2["id"], sector["id"], assigned_route="J64")
        assert_instant(
            second["hourly_bucket"], expected_hourly_bucket(at("14:00")),
            "the bucket follows the updated ETA",
        )
