"""Quantities that must return to their pre-write value after the compensating
action, and totals that must hold at every intermediate step.

The bay ledger is capacity in whole minutes mirrored on two rows; the merchant
ledger is money in integer cents split across three buckets. Both are walked
forward and back with the sum re-checked after every individual write.
"""
from test_helpers import (
    ARRIVAL_CLOCK_UTC,
    DISPATCHER,
    add_depot_bay,
    add_order,
    assert_bay_minutes_ledgers,
    assert_merchant_fee_buckets_sum,
    dispatch_mission,
    load_mission,
    mission_action,
    read_bay,
    read_merchant,
    read_order,
    read_reservation,
    read_zone,
    reservation_action,
    reserve_bay,
    set_clock,
    setup_available_robot,
    setup_received_order,
    submit_route_plan,
    validate_and_activate_plan,
    validate_paginated,
    validate_success,
)

FIRST_WINDOW = {
    "window_start_utc": "2026-08-03T10:00:00.000Z",
    "window_end_utc": "2026-08-03T11:00:00.000Z",
}
SECOND_WINDOW = {
    "window_start_utc": "2026-08-03T11:15:00.000Z",
    "window_end_utc": "2026-08-03T12:00:00.000Z",
}
LARGE_ORDER = {
    "customer_ref": "C-9",
    "payload_liters": 40.0,
    "declared_value_cents": 9004,
    "promised_by_utc": "2026-08-03T11:00:00.000Z",
}


def _two_windows_of_different_lengths() -> dict:
    """One open charge bay holding a sixty-minute window and a forty-five minute
    window, so the ledger stands at 105 minutes on both rows."""
    ctx = setup_available_robot()
    bay = add_depot_bay(ctx["z"], "B1", bay_type="CHARGE", power_kw=22.0, state="OPEN")
    ctx["b"] = bay["id"]
    ctx["res_x"] = reserve_bay(bay, ctx["r"], **FIRST_WINDOW)
    ctx["x"] = ctx["res_x"]["id"]
    ctx["res_y"] = reserve_bay(read_bay(bay["id"]), ctx["r"], **SECOND_WINDOW)
    ctx["y"] = ctx["res_y"]["id"]
    return ctx


class TestBayMinutesLedgerRestoredByCancel:
    def test_cancelling_the_shorter_window_subtracts_exactly_its_own_minutes(self, api):
        """PRD §3.4: "`RELEASE` carries a reservation from `ACTIVE` to the
        terminal `RELEASED`, and `CANCEL` carries a reservation from `HELD` to
        the terminal `CANCELLED`; each of those two subtracts exactly
        `window_minutes` from both the bay's `committed_minutes` and the zone's
        `reserved_bay_minutes`, advances the bay's and the zone's `version` by one
        each, and clears the robot's `current_bay_reservation_id` when it was
        pointing at that reservation."

        Design: Difficulty/compensating_invariant/bay_minutes_ledger_restored_by_cancel
        """
        ctx = _two_windows_of_different_lengths()
        assert_bay_minutes_ledgers(read_bay(ctx["b"]), read_zone(ctx["z"]), 105)

        cancelled = reservation_action(ctx["y"], "CANCEL")

        assert cancelled["state"] == "CANCELLED"
        assert_bay_minutes_ledgers(read_bay(ctx["b"]), read_zone(ctx["z"]), 60)

    def test_cancelling_both_windows_returns_the_ledger_to_its_pre_create_value(self, api):
        """PRD §3.4: "Because `RELEASED` and `CANCELLED` are both terminal, the
        subtraction can never be applied twice, which is what makes both round
        trips exact: create-then-cancel and create-activate-release each return
        both ledgers to their precise pre-create values with no drift."
        PRD §3.4: "At every instant a bay's `committed_minutes` equals the sum of
        `window_minutes` over that bay's reservations whose `state` is `HELD` or
        `ACTIVE`, and a zone's `reserved_bay_minutes` equals the sum of
        `committed_minutes` over that zone's bays, which is the same as the sum of
        `window_minutes` over every live reservation anywhere in the zone."

        Design: Difficulty/compensating_invariant/bay_minutes_ledger_restored_by_cancel
        """
        ctx = _two_windows_of_different_lengths()

        reservation_action(ctx["y"], "CANCEL")
        cancelled_x = reservation_action(ctx["x"], "CANCEL")

        rows, _meta = validate_paginated(
            api.list_bay_reservations(DISPATCHER, {"bay_id": ctx["b"], "state": "HELD"})
        )
        assert cancelled_x["state"] == "CANCELLED"
        assert_bay_minutes_ledgers(read_bay(ctx["b"]), read_zone(ctx["z"]), 0)
        assert rows == []

    def test_the_frozen_window_minutes_survive_the_cancellations(self, api):
        """PRD §3.4: "From that window the server derives `window_minutes` as the
        number of whole minutes from start to end, discarding any partial minute,
        and that value is frozen for the life of the reservation even though the
        window fields themselves are also immutable."
        PRD §3.4: "Reservations already in `RELEASED` or `CANCELLED` are invisible
        to this test, so a cancelled booking frees its slot immediately."

        Design: Difficulty/compensating_invariant/bay_minutes_ledger_restored_by_cancel
        """
        ctx = _two_windows_of_different_lengths()
        assert ctx["res_x"]["window_minutes"] == 60
        assert ctx["res_y"]["window_minutes"] == 45

        reservation_action(ctx["y"], "CANCEL")
        reservation_action(ctx["x"], "CANCEL")

        assert read_reservation(ctx["x"])["window_minutes"] == 60
        assert read_reservation(ctx["y"])["window_minutes"] == 45


def _two_received_orders() -> dict:
    """One merchant holding the canonical 22 litre order quoted at 850 and a
    second 40 litre order quoted at 812, so escrow stands at 1662."""
    ctx = setup_received_order()
    large = add_order(ctx["m"], ctx["s5"], **LARGE_ORDER)
    ctx["order_large"] = large
    ctx["ol"] = large["id"]
    return ctx


def _deliver_the_canonical_order(ctx: dict) -> dict:
    """Carry the 22 litre order all the way to DELIVERED, arriving twelve
    minutes after departure."""
    mission = dispatch_mission(ctx["order"], ctx["r"])
    mission = load_mission(mission["id"], ctx["m"], 22.0)
    plan = submit_route_plan(mission, [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]])
    validate_and_activate_plan(plan["id"])
    mission_action(mission["id"], "DEPART")
    set_clock(ARRIVAL_CLOCK_UTC)
    mission_action(mission["id"], "ARRIVE")
    return mission_action(mission["id"], "COMPLETE", lid_access_code=mission["lid_access_code"])


class TestMerchantFeeBucketsConservedAcrossCancel:
    def test_a_cancellation_moves_the_quote_from_escrow_into_released(self, api):
        """PRD §3.3: "On success `order_state` becomes the terminal `CANCELLED`,
        the quoted amount leaves `escrowed_fee_cents` and enters
        `released_fee_cents` — the compensating half of the merchant fee
        invariant, after which escrow has returned to its pre-intake value while
        the three buckets together still equal the sum of `quoted_fee_cents` over
        every order the merchant ever created — and both the merchant's and the
        order's versions advance by one."
        PRD §2.8: "The invariant is that the three buckets together equal the sum
        of `quoted_fee_cents` over every delivery order the merchant ever
        created."

        Design: Difficulty/compensating_invariant/merchant_fee_buckets_conserved_across_cancel
        """
        ctx = _two_received_orders()
        assert ctx["order"]["quoted_fee_cents"] == 850
        assert ctx["order_large"]["quoted_fee_cents"] == 812
        assert_merchant_fee_buckets_sum(read_merchant(ctx["m"]), 1662)

        cancelled = validate_success(
            api.cancel_delivery_order(
                ctx["ol"], ctx["merchant_headers"], {"reason": "customer stood down"}
            )
        )

        merchant = read_merchant(ctx["m"])
        assert cancelled["order_state"] == "CANCELLED"
        assert merchant["escrowed_fee_cents"] == 850
        assert merchant["released_fee_cents"] == 812
        assert merchant["recognized_fee_cents"] == 0
        assert_merchant_fee_buckets_sum(merchant, 1662)

    def test_the_delivery_recognises_the_quote_and_parks_the_variance_outside(self, api):
        """PRD §3.7: "The merchant's money then moves from escrow into revenue:
        `escrowed_fee_cents` decreases by `quoted_fee_cents`,
        `recognized_fee_cents` increases by the same `quoted_fee_cents`, and
        `settlement_variance_cents` accumulates the signed difference of
        `settled_fee_cents` minus `quoted_fee_cents`, so a reroute that lengthened
        the haul pushes the variance positive while a large blockage credit can
        push it negative."
        PRD §3.7: "Note carefully that the two money buckets move by the quote,
        never by the settlement; the variance field is the only place the
        difference is recorded."
        PRD §2.8: "Separately from the invariant, `settlement_variance_cents`
        accumulates the signed difference between the settled fee and the quoted
        fee on each delivery: a reroute that lengthened the haul pushes it
        positive, and a blockage credit can push it negative."

        Design: Difficulty/compensating_invariant/merchant_fee_buckets_conserved_across_cancel
        """
        ctx = _two_received_orders()
        validate_success(
            api.cancel_delivery_order(
                ctx["ol"], ctx["merchant_headers"], {"reason": "customer stood down"}
            )
        )
        assert_merchant_fee_buckets_sum(read_merchant(ctx["m"]), 1662)

        _deliver_the_canonical_order(ctx)

        merchant = read_merchant(ctx["m"])
        assert merchant["escrowed_fee_cents"] == 0
        assert merchant["recognized_fee_cents"] == 850
        assert merchant["released_fee_cents"] == 812
        assert_merchant_fee_buckets_sum(merchant, 1662)
        assert merchant["settlement_variance_cents"] == -33
        assert read_order(ctx["o"])["settled_fee_cents"] == 817
