"""Difficulty queue: combinatorial formulas.

Three modes of non-trivial arithmetic: the nested min/subtract/ground-stop
capacity gate, the floor-then-largest-remainder fair-share rounding, and the
pinned waterfall evaluation order of a compression run.
"""

from test_helpers import (
    COMMAND_CENTER_HEADERS,
    ApiErrorId,
    activate_tmi,
    assert_instant,
    at,
    cancel_tmi,
    create_airport,
    create_published_forecast,
    get_flight,
    ledger_for,
    list_tmi_ledgers,
    list_tmi_slots,
    propose_gdp,
    propose_tmi,
    publish_tmi,
    report_and_confirm_event,
    run_compression,
    set_clock,
    setup_active_gdp,
    setup_compression_scenario,
    validate_error,
)


class TestMaxFeasibleRateGate:
    def test_gate_combines_forecast_min_base_afp_load_and_ground_stop(self, api):
        """PRD §3.4: "If any `GROUND_STOP` initiative other than the candidate
        itself sits on the facility in `PUBLISHED`, `ACTIVE`, or `REVISING` with
        a window overlapping the candidate's, the answer is 0 — a live ground
        stop zeroes everything. Otherwise the gate forecast's
        `predicted_acceptance_rate` is taken, capped from above by the
        facility's `base_acceptance_rate`; from that, the aggregate load of
        every `AIRSPACE_FLOW_PROGRAM` on the facility in `PUBLISHED`, `ACTIVE`,
        or `REVISING` overlapping the candidate window — summed
        `controlled_rate` values, excluding the candidate itself — is
        subtracted; the result is floored at 0."
        PRD §2.6 item 20: "The `controlled_rate` must not exceed the maximum
        feasible rate for the facility and window, recomputed at gate time, for
        `GROUND_DELAY_PROGRAM` and `AIRSPACE_FLOW_PROGRAM` initiatives;
        `GROUND_STOP` and `REROUTE` are exempt. Failure yields
        `ERR_RATE_EXCEEDS_CAPACITY` (HTTP 422)."

        Design: Difficulty/combinatorial_formula/max_feasible_rate_gate
        """
        set_clock(api)
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        report_and_confirm_event(
            api, facility["id"], event_type="WEATHER", severity=2,
            window_start=at("13:00"), window_end=at("15:00"),
        )
        # predicted = floor(30 * 0.70) = 21
        create_published_forecast(
            api, facility["id"], variant="PLANNING",
            window_start=at("13:00"), window_end=at("15:00"),
        )
        afp = propose_tmi(
            api, facility["id"], tmi_type="AIRSPACE_FLOW_PROGRAM",
            program_start=at("13:00"), program_end=at("15:00"), controlled_rate=4,
        )
        publish_tmi(api, afp["id"])
        activate_tmi(api, afp["id"])

        # max_feasible = max(0, min(21, 30) - 4) = 17 -> rate 18 must fail
        gdp_over = propose_gdp(
            api, facility["id"], program_start=at("13:00"),
            program_end=at("14:00"), controlled_rate=18,
        )
        resp = api.publish_tmi(gdp_over["id"], COMMAND_CENTER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_RATE_EXCEEDS_CAPACITY)
        cancel_tmi(api, gdp_over["id"])

        # boundary value admitted: 16 <= 17
        gdp_ok = propose_gdp(
            api, facility["id"], program_start=at("14:00"),
            program_end=at("15:00"), controlled_rate=16,
        )
        published = publish_tmi(api, gdp_ok["id"])
        assert published["status"] == "PUBLISHED", (
            f"16 <= 17 must pass the gate, got {published['status']}"
        )
        cancel_tmi(api, gdp_ok["id"])

        # ground-stop zero-branch: while a GS is PUBLISHED the answer is 0
        ground_stop = propose_tmi(
            api, facility["id"], tmi_type="GROUND_STOP",
            program_start=at("13:30"), program_end=at("14:30"), controlled_rate=0,
        )
        publish_tmi(api, ground_stop["id"])
        afp2 = propose_tmi(
            api, facility["id"], tmi_type="AIRSPACE_FLOW_PROGRAM",
            program_start=at("13:30"), program_end=at("15:00"), controlled_rate=60,
        )
        resp = api.publish_tmi(afp2["id"], COMMAND_CENTER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_RATE_EXCEEDS_CAPACITY)


class TestDelayDistributionLargestRemainder:
    def test_fair_share_floors_then_largest_remainder(self, api):
        """PRD §3.9: "The rounding order is pinned: each raw share is floored
        first, and the leftover minutes — the total delay minus the sum of
        those floors — are distributed one minute per ledger in order of
        largest fractional remainder, with ties broken toward the operator
        whose earliest in-program flight has the earliest `scheduled_arrival`,
        and then by operator `created_at` ascending. The result is stored as
        `fair_share_minutes`, and `deviation_minutes` — the signed difference
        between `attributed_delay_minutes` and `fair_share_minutes` — exposes
        how far each operator sits from its proportional share."

        Design: Difficulty/combinatorial_formula/delay_distribution_largest_remainder
        """
        world = setup_active_gdp(
            api, controlled_rate=12, program_start="13:00", program_end="14:00",
            flight_specs=(
                (0, "AAL1", "13:02"),
                (0, "AAL2", "13:04"),
                (0, "AAL3", "13:06"),
                (1, "BAL1", "13:08"),
                (1, "BAL2", "13:10"),
                (1, "BAL3", "13:12"),
            ),
        )
        op_a, op_b = world["operators"]
        ledgers = list_tmi_ledgers(api, world["tmi"]["id"])
        ledger_a = ledger_for(ledgers, op_a["id"])
        ledger_b = ledger_for(ledgers, op_b["id"])

        # RBS CTAs 13:00/13:05/13:10/13:15/13:20/13:25 -> delays 0,1,4 / 7,10,13
        assert ledger_a["flight_count"] == 3
        assert ledger_a["attributed_delay_minutes"] == 5, (
            f"0+1+4, got {ledger_a['attributed_delay_minutes']}"
        )
        assert ledger_b["flight_count"] == 3
        assert ledger_b["attributed_delay_minutes"] == 30, (
            f"7+10+13, got {ledger_b['attributed_delay_minutes']}"
        )
        # raw shares 35*3/6 == 17.5 each; floors sum to 34, leftover 1 goes to
        # the operator whose earliest in-program flight is earliest (13:02)
        assert ledger_a["fair_share_minutes"] == 18
        assert ledger_b["fair_share_minutes"] == 17
        assert (
            ledger_a["fair_share_minutes"] + ledger_b["fair_share_minutes"] == 35
        ), "floor-then-largest-remainder conserves the 35-minute total"
        assert ledger_a["deviation_minutes"] == -13
        assert ledger_b["deviation_minutes"] == 13


class TestCompressionEvaluationOrder:
    def test_freed_slot_reenters_pool_within_same_pass(self, api):
        """PRD §3.5: "Only then do carrier moves begin: candidate flights —
        those holding `ASSIGNED` slots and not operationally `CANCELLED` — are
        walked in ration-by-schedule order (`scheduled_arrival` ascending, ties
        by `created_at` ascending), and each candidate takes the earliest pool
        slot strictly earlier than its current `slot_time`; the slot it frees
        is inserted back into the pool, kept in `slot_time` order, and is
        reusable by later candidates in the same pass — which is how a freed
        mid-compression slot transitions from `ASSIGNED` back to `OPEN` and
        re-enters the pool."
        PRD §3.5: "Passes repeat until a pass makes zero moves or
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

        Design: Difficulty/combinatorial_formula/compression_evaluation_order
        """
        world = setup_compression_scenario(api)  # A1 cancelled; slot 13:00 RELEASED
        tmi_id = world["tmi"]["id"]
        _, a2, a3, _, b2 = world["flights"]

        run = run_compression(api, tmi_id)

        assert run["released_slot_count"] == 1, "only the cancelled holder's 13:00 slot"
        assert run["moves_made"] == 4, (
            f"pass 1 moves A2,A3,B1,B2; pass 2 finds nothing, got {run['moves_made']}"
        )
        assert run["passes_executed"] == 2, (
            "the final no-move pass is counted; the run stops there"
        )
        assert run["remaining_open_slots"] == 8, (
            "six never-assigned carrier slots + reopened 13:20 + reserved 13:55"
        )
        assert_instant(get_flight(api, a2["id"])["controlled_arrival"], at("13:00"), "A2 CTA")
        # A3 at 13:05 is only reachable if A2's freed slot re-entered the pool
        # within the SAME pass (pinned waterfall order)
        assert_instant(get_flight(api, a3["id"])["controlled_arrival"], at("13:05"), "A3 CTA")
        assert_instant(get_flight(api, b2["id"])["controlled_arrival"], at("13:15"), "B2 CTA")

        slots, meta = list_tmi_slots(api, tmi_id)
        assert meta["total_count"] == 12
        assigned = [s for s in slots if s["status"] == "ASSIGNED"]
        assert len(assigned) == 4, (
            "slot-count conservation through compression: 5 initial - 1 cancelled"
        )
