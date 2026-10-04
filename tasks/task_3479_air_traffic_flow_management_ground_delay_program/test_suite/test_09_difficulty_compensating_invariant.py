"""Difficulty queue: compensating invariants.

A substitution conserves the assigned-slot multiset exactly while moving
delay; a later cancel then returns every delay ledger to zero.
"""

from test_helpers import (
    assert_instant,
    at,
    cancel_tmi,
    get_flight,
    get_operator,
    ledger_for,
    list_slot_transactions,
    list_tmi_ledgers,
    list_tmi_slots,
    setup_active_gdp,
    substitution_payload,
    sum_delay_deltas,
    transactions_of_type,
    assigned_slot_times,
    validate_success,
)


class TestSubstitutionConservesSlotInventory:
    def test_swap_moves_delay_but_not_the_slot_multiset(self, api):
        """PRD §3.5: "A legal swap exchanges the two flights' controlled
        arrival times, writes two `SUBSTITUTION_SWAP` transactions with
        opposite `delay_delta_minutes` values — the created response returns
        the transaction recorded for `flight_id_1` — recomputes both flights'
        `provisional_delay_minutes`, reconciles the operator's ledger, and
        recomputes fair shares, all while conserving the program's
        assigned-slot multiset exactly."

        Design: Difficulty/compensating_invariant/substitution_conserves_slot_inventory
        """
        world = setup_active_gdp(api)
        tmi_id = world["tmi"]["id"]
        f1, _, f3 = world["flights"][0], world["flights"][1], world["flights"][2]
        op_a = world["operators"][0]
        op_a_headers = world["operator_headers"][0]

        slots_before, _ = list_tmi_slots(api, tmi_id)
        assigned_before = assigned_slot_times(slots_before)
        assert assigned_before == [
            at("13:00"), at("13:10"), at("13:20"), at("13:30"), at("13:40"),
        ]

        resp = api.create_substitution(
            tmi_id, substitution_payload(f1["id"], f3["id"]), op_a_headers
        )
        transaction = validate_success(resp, 201)
        assert transaction["transaction_type"] == "SUBSTITUTION_SWAP"
        assert transaction["flight_id"] == f1["id"], (
            "the response returns the transaction recorded for flight_id_1"
        )

        f1_after = get_flight(api, f1["id"])
        f3_after = get_flight(api, f3["id"])
        assert_instant(f1_after["controlled_arrival"], at("13:30"), "f1 CTA after swap")
        assert f1_after["provisional_delay_minutes"] == 25
        assert_instant(f3_after["controlled_arrival"], at("13:00"), "f3 CTA after swap")
        assert f3_after["provisional_delay_minutes"] == 0

        # the conserved quantity: the ASSIGNED slot_time multiset is untouched
        slots_after, _ = list_tmi_slots(api, tmi_id)
        assert assigned_slot_times(slots_after) == assigned_before, (
            "the swap must leave the assigned-slot multiset bit-identical"
        )

        transactions, _ = list_slot_transactions(api, tmi_id)
        swaps = transactions_of_type(transactions, "SUBSTITUTION_SWAP")
        assert len(swaps) == 2
        deltas = {t["flight_id"]: t["delay_delta_minutes"] for t in swaps}
        assert deltas == {f1["id"]: 25, f3["id"]: -10}

        # delay itself is NOT conserved — it moved to the operator's ledger
        ledger_a = ledger_for(list_tmi_ledgers(api, tmi_id), op_a["id"])
        assert ledger_a["attributed_delay_minutes"] == 25


class TestCancelRestoresDelayLedgers:
    def test_forward_then_compensating_actions_sum_to_zero(self, api):
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

        Design: Difficulty/compensating_invariant/cancel_restores_delay_ledgers
        """
        world = setup_active_gdp(api)
        tmi_id = world["tmi"]["id"]
        f1, f3 = world["flights"][0], world["flights"][2]
        op_a, op_b = world["operators"]
        op_a_headers = world["operator_headers"][0]

        # forward activity: activation (+29 total delay) then a swap (+15 net)
        resp = api.create_substitution(
            tmi_id, substitution_payload(f1["id"], f3["id"]), op_a_headers
        )
        validate_success(resp, 201)

        # the compensating action cancels the whole program
        cancel_tmi(api, tmi_id)

        transactions, _ = list_slot_transactions(api, tmi_id)
        assert sum_delay_deltas(transactions) == 0, (
            "initial +29, substitution net +15, reversals -44: the log balances"
        )

        ledgers = list_tmi_ledgers(api, tmi_id)
        ledger_a = ledger_for(ledgers, op_a["id"])
        ledger_b = ledger_for(ledgers, op_b["id"])
        assert ledger_a["attributed_delay_minutes"] == 0
        assert ledger_a["reversed_delay_minutes"] == 25
        assert ledger_b["attributed_delay_minutes"] == 0
        assert ledger_b["reversed_delay_minutes"] == 19

        assert get_operator(api, op_a["id"])["cumulative_delay_minutes"] == 0, (
            "cumulative delay is bit-identical to its pre-activation value"
        )
