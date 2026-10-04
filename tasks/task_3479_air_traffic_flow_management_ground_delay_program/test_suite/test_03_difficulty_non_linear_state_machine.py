"""Difficulty queue: non-linear state machines.

The TMI lifecycle cycles ACTIVE -> REVISING -> ACTIVE across separate
requests, and a Flight carries two independent state dimensions that cascades
move separately.
"""

from test_helpers import (
    ApiErrorId,
    apply_revision,
    assert_instant,
    at,
    cancel_tmi,
    get_flight,
    get_tmi,
    list_slot_transactions,
    list_tmi_slots,
    setup_active_gdp,
    substitution_payload,
    tmi_revision_payload,
    transactions_of_type,
    update_flight,
    validate_error,
    validate_success,
    FLOW_MANAGER_HEADERS,
)


class TestTmiRevisionCycle:
    def test_active_revising_active_cycle_rederives_slots(self, api):
        """PRD §3.6: "the initiative moves from `ACTIVE` to `REVISING` while a
        **TMIRevision** record sits unapplied, and a subsequent activation
        applies it and returns the program to `ACTIVE`. While a program sits in
        `REVISING`, substitutions, compression runs, reroute assignments, and
        GA adjudication are all rejected with `ERR_TMI_NOT_ACTIVE`."
        PRD §3.6: "Then a full re-derivation runs: GA-accommodated flights keep
        their slots, every other slot is torn down and rebuilt over the new
        rate and window, the eligible flight set is re-snapshotted, and flights
        whose controlled arrival changed receive `REVISION_MOVE` transactions
        and recomputed `provisional_delay_minutes`."

        Design: Difficulty/non_linear_state_machine/tmi_revision_cycle
        """
        world = setup_active_gdp(api)
        tmi_id = world["tmi"]["id"]
        f1, _, f3, _, f5 = world["flights"]
        op_a_headers = world["operator_headers"][0]
        observed_version = get_tmi(api, tmi_id)["version"]

        # leg 1: ACTIVE -> REVISING with an unapplied MANUAL revision
        resp = api.create_tmi_revision(
            tmi_id,
            tmi_revision_payload(
                expected_tmi_version=observed_version,
                new_controlled_rate=10, reason="weather improving",
            ),
            FLOW_MANAGER_HEADERS,
        )
        revision = validate_success(resp, 201)
        assert revision["applied"] is False
        assert revision["revision_index"] == 1
        assert get_tmi(api, tmi_id)["status"] == "REVISING"

        # REVISING is observable: substitutions are gated even though the
        # flights are SLOTTED and their data is fresh
        resp = api.create_substitution(
            tmi_id, substitution_payload(f1["id"], f3["id"]), op_a_headers
        )
        validate_error(resp, ApiErrorId.ERR_TMI_NOT_ACTIVE)

        # leg 2: activation applies the revision and re-derives at rate 10
        apply_revision(api, tmi_id)
        tmi_after = get_tmi(api, tmi_id)
        assert tmi_after["status"] == "ACTIVE"
        assert tmi_after["controlled_rate"] == 10, (
            f"revision applied on the return leg, got {tmi_after['controlled_rate']}"
        )

        # 3600/10 = 360s slots; BAL5 re-takes position 4 -> 13:00 + 4*360s
        f5_after = get_flight(api, f5["id"])
        assert_instant(f5_after["controlled_arrival"], at("13:24"), "f5 CTA after re-derivation")
        assert f5_after["provisional_delay_minutes"] == 0, (
            "13:24 is before its 13:26 schedule; was CTA 13:40 / delay 14 before"
        )
        transactions, _ = list_slot_transactions(api, tmi_id)
        revision_moves = transactions_of_type(transactions, "REVISION_MOVE")
        assert len(revision_moves) == 4, (
            "F1's CTA 13:00 is unchanged (no transaction); F2/F3/F4/F5 moved"
        )
        _, slots_meta = list_tmi_slots(api, tmi_id)
        assert slots_meta["total_count"] == 20, (
            f"floor(7200/360) slots rebuilt at rate 10, got {slots_meta['total_count']}"
        )


class TestFlightParallelDimensions:
    def test_ops_and_control_dimensions_move_independently(self, api):
        """PRD §3.5: "A filed flight is born with `ops_status` `SCHEDULED` and
        `control_status` `UNCONTROLLED` — two independent dimensions carried on
        the same row — with `controlled_arrival` null, `is_overflow` false,
        `provisional_delay_minutes` 0, `final_delay_minutes` null, and
        `last_eta_reported_at` stamped from the logical clock at filing."
        PRD §3.9: "each release reverts its holder flight — `controlled_arrival`
        to null, `control_status` to `UNCONTROLLED`, `provisional_delay_minutes`
        to 0, `is_overflow` cleared — and writes a `REVERSAL` SlotTransaction
        whose `delay_delta_minutes` is the negation of the flight's previously
        attributed delay;"

        Design: Difficulty/non_linear_state_machine/flight_parallel_dimensions
        """
        world = setup_active_gdp(
            api,
            flight_specs=((0, "AAL3", "13:20"), (1, "BAL4", "13:15")),
        )
        f3, f4 = world["flights"]

        # the operations dimension advances while the control dimension holds
        updated = update_flight(api, f3, new_ops_status="AIRBORNE")
        assert updated["ops_status"] == "AIRBORNE"
        assert updated["control_status"] == "SLOTTED", (
            "a flight may be AIRBORNE and SLOTTED at once"
        )

        # the program-level cancel cascade moves control only
        cancel_tmi(api, world["tmi"]["id"])
        f3_after = get_flight(api, f3["id"])
        assert f3_after["ops_status"] == "AIRBORNE", (
            "the cascade does not touch the operations dimension"
        )
        assert f3_after["control_status"] == "UNCONTROLLED"
        assert f3_after["controlled_arrival"] is None
        f4_after = get_flight(api, f4["id"])
        assert f4_after["ops_status"] == "SCHEDULED"
        assert f4_after["control_status"] == "UNCONTROLLED"
