"""Difficulty queue: transitive cascades.

A confirmation mutates forecasts, which mutates programs, which writes a
revision record (depth 3); a program cancel releases slots, each release
reverting its flight and reversing its ledger (depth 2).
"""

from test_helpers import (
    activate_tmi,
    cancel_tmi,
    confirm_event,
    create_airport,
    create_published_forecast,
    get_flight,
    get_operator,
    get_tmi,
    ledger_for,
    list_facility_forecasts,
    list_slot_transactions,
    list_tmi_ledgers,
    list_tmi_revisions,
    list_tmi_slots,
    propose_gdp,
    publish_tmi,
    report_constraint_event,
    set_clock,
    setup_active_gdp,
    transactions_of_type,
    at,
)


class TestConstraintConfirmDowngradesProgram:
    def test_confirm_stales_forecast_then_revises_active_gdp(self, api):
        """PRD §3.2: "Confirming a `REPORTED` event — from any other state the
        request fails with `ERR_INVALID_STATE` (HTTP 409) — moves it to
        `CONFIRMED` and fires a two-link cascade. First, every `PUBLISHED`
        CapacityForecast on the same facility whose window overlaps the event's
        window turns `STALE`. Second, for each `ACTIVE` ground delay program on
        that facility whose window overlaps the event, the system recomputes
        the implied capacity: the facility's `base_acceptance_rate` multiplied
        by the product, over all `CONFIRMED` events overlapping the program
        window, of one minus that event's per-type step times its `severity` —
        with the multiplier never allowed below ten percent of base and the
        resulting rate floored to an integer with a minimum of 1."
        PRD §3.2: "If that implied rate has collapsed below the program's
        `controlled_rate`, the program auto-transitions from `ACTIVE` to
        `REVISING` and the system writes a TMIRevision of origin
        `SYSTEM_AUTO_DOWNGRADE` whose `new_controlled_rate` is the largest
        valid GDP rate not exceeding the implied rate — or 6 when the implied
        rate is below 6."

        Design: Difficulty/transitive_cascade/constraint_confirm_downgrades_program
        """
        set_clock(api)
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        forecast = create_published_forecast(
            api, facility["id"], variant="PLANNING",
            window_start=at("13:00"), window_end=at("15:00"),
        )
        assert forecast["predicted_acceptance_rate"] == 30
        tmi = propose_gdp(
            api, facility["id"], program_start=at("13:00"),
            program_end=at("15:00"), controlled_rate=30,
        )
        publish_tmi(api, tmi["id"])
        activate_tmi(api, tmi["id"])

        event = report_constraint_event(
            api, facility["id"], event_type="WEATHER", severity=4,
            window_start=at("13:00"), window_end=at("15:00"),
        )
        confirm_event(api, event["id"])

        # link 1: the overlapping PUBLISHED forecast is now STALE
        forecasts, _ = list_facility_forecasts(api, facility["id"])
        stale = {f["id"]: f["status"] for f in forecasts}
        assert stale[forecast["id"]] == "STALE", (
            f"forecast should be STALE after the overlapping confirm, got {stale}"
        )

        # link 2: implied rate floor(30 * (1 - 0.15*4)) = 12 < 30 -> REVISING
        tmi_after = get_tmi(api, tmi["id"])
        assert tmi_after["status"] == "REVISING"
        assert tmi_after["revision_count"] == 1

        # link 3: the revision record the cascade itself wrote
        revisions = list_tmi_revisions(api, tmi["id"])
        assert len(revisions) == 1
        revision = revisions[0]
        assert revision["origin"] == "SYSTEM_AUTO_DOWNGRADE"
        assert revision["reason"] == "AUTO_CAPACITY_DOWNGRADE"
        assert revision["previous_controlled_rate"] == 30
        assert revision["new_controlled_rate"] == 12, (
            "largest valid GDP rate <= implied 12 is 12"
        )
        assert revision["applied"] is False


class TestTmiCancelCompensatesSlots:
    def test_cancel_releases_slots_and_reverses_ledgers(self, api):
        """PRD §3.9: "From `ACTIVE` or `REVISING` the full compensation cascade
        runs inside the same request: every `ASSIGNED` ArrivalSlot moves to
        `RELEASED`; each release reverts its holder flight —
        `controlled_arrival` to null, `control_status` to `UNCONTROLLED`,
        `provisional_delay_minutes` to 0, `is_overflow` cleared — and writes a
        `REVERSAL` SlotTransaction whose `delay_delta_minutes` is the negation
        of the flight's previously attributed delay; and the operator's ledger
        has `attributed_delay_minutes` decremented and `reversed_delay_minutes`
        incremented by that same amount, so that after a full cancellation the
        ledger's attributed-minus-reversed balance reads zero."
        PRD §3.1: "Each operator also carries `cumulative_delay_minutes`, a
        computed integer starting at 0 that accumulates the operator's FINAL
        attributed delay minutes across all `COMPLETED` programs, is adjusted
        by compensation reversals when a program is cancelled, and is never
        decremented by provisional activity while a program runs."

        Design: Difficulty/transitive_cascade/tmi_cancel_compensates_slots
        """
        world = setup_active_gdp(api)
        tmi_id = world["tmi"]["id"]
        f1, f2, f3, f4, f5 = world["flights"]
        op_a, op_b = world["operators"]

        cancel_tmi(api, tmi_id)

        # link 1: every formerly ASSIGNED slot is RELEASED
        slots, _ = list_tmi_slots(api, tmi_id)
        by_index = {s["slot_index"]: s for s in slots}
        for index in range(5):
            assert by_index[index]["status"] == "RELEASED", (
                f"slot {index} should be RELEASED, got {by_index[index]['status']}"
            )
            assert by_index[index]["assigned_flight_id"] is None

        # link 2: the holder flight is reverted by its slot's release
        f3_after = get_flight(api, f3["id"])
        assert f3_after["controlled_arrival"] is None
        assert f3_after["control_status"] == "UNCONTROLLED"
        assert f3_after["provisional_delay_minutes"] == 0

        # each release wrote a REVERSAL mirroring the flight's attributed delay
        transactions, _ = list_slot_transactions(api, tmi_id)
        reversals = transactions_of_type(transactions, "REVERSAL")
        assert len(reversals) == 5
        delta_by_flight = {t["flight_id"]: t["delay_delta_minutes"] for t in reversals}
        assert delta_by_flight == {
            f1["id"]: 0, f2["id"]: 0, f3["id"]: -10, f4["id"]: -5, f5["id"]: -14,
        }, f"REVERSAL deltas negate prior attribution: {delta_by_flight}"

        ledgers = list_tmi_ledgers(api, tmi_id)
        ledger_a = ledger_for(ledgers, op_a["id"])
        ledger_b = ledger_for(ledgers, op_b["id"])
        assert ledger_a["attributed_delay_minutes"] == 0
        assert ledger_a["reversed_delay_minutes"] == 10
        assert ledger_b["attributed_delay_minutes"] == 0
        assert ledger_b["reversed_delay_minutes"] == 19

        # a cancel never credits final delay
        assert get_operator(api, op_b["id"])["cumulative_delay_minutes"] == 0
