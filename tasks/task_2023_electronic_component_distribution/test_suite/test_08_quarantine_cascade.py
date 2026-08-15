"""The quarantine release cascade and the lot unit-conservation invariant
(PRD §3.5 cascade, §3.4 reservation bookkeeping)."""
from test_helpers import (
    SALES,
    advance_clock,
    assert_lot_unit_conservation,
    bake,
    create_allocation_run_for_part,
    get_lot,
    get_order,
    get_order_line,
    get_part,
    open_exposure_interval,
    publish_run,
    seal_exposure_interval,
    setup_allocated_order,
    validate_success,
)


def _setup_allocated_with_open_exposure(quantity=60, lot_qty=100,
                                        floor_life_hours=100,
                                        line_code="LIN-Q"):
    """Allocated order line on a single-lot part, with an open moisture
    exposure started at the default clock. Returns the scenario dict."""
    sc = setup_allocated_order(quantity=quantity, lot_qty=lot_qty,
                               line_code=line_code,
                               part_kw={"floor_life_hours": floor_life_hours})
    exposure = open_exposure_interval(sc["lot"]["id"], note="opened for kitting")
    return {**sc, "exposure": exposure}


class TestQuarantineCascadeDepth3:
    def test_msl_quarantine_cascade_lot_effects(self, api):
        """PRD §3.5: "When the clock sweep finds an `AVAILABLE` lot whose
        recomputed `msl_exposure_hours` has reached its part's
        `floor_life_hours`, the lot moves to `QUARANTINED` and its reservations
        unwind: the lot's `qty_on_hand` absorbs its full `qty_reserved`, which
        is then zeroed."

        Design: Difficulty/transitive_cascade/msl_quarantine_cascade_depth3
        """
        sc = _setup_allocated_with_open_exposure()
        lot_pre = get_lot(sc["lot"]["id"])
        assert lot_pre["qty_reserved"] == 60
        assert lot_pre["qty_on_hand"] == 40

        advance_clock("2026-08-05T04:00:00Z")  # 100 hours >= floor life 100

        lot_after = get_lot(sc["lot"]["id"])
        assert lot_after["status"] == "QUARANTINED"
        assert lot_after["msl_exposure_hours"] == 100
        assert lot_after["qty_on_hand"] == 100, "Reservation released back on hand"
        assert lot_after["qty_reserved"] == 0
        assert_lot_unit_conservation(lot_after)

    def test_msl_quarantine_cascade_order_effects(self, api):
        """PRD §3.5: "Those released units are then clawed back from the part's
        `ALLOCATED` order lines newest first — descending line creation time,
        ties broken by descending ship date — decrementing each line's
        `allocated_qty` by the released amount in turn; a line whose allocation
        falls to zero drops back from `ALLOCATED` to `OPEN`. Every order touched
        by the cascade has its `allocated_value_cents` and
        `open_exposure_cents` recomputed and its `version` and `updated_at`
        bumped".

        Design: Difficulty/transitive_cascade/msl_quarantine_cascade_depth3
        """
        sc = _setup_allocated_with_open_exposure()
        order_pre = get_order(sc["order"]["id"])
        assert order_pre["allocated_value_cents"] == 90000  # 60 * 1500
        assert order_pre["open_exposure_cents"] == 90000

        advance_clock("2026-08-05T04:00:00Z")

        line_after = get_order_line(sc["order_line"]["id"])
        assert line_after["status"] == "OPEN", (
            "Deallocated by the quarantine cascade, not by any client action"
        )
        assert line_after["allocated_qty"] == 0

        order_after = get_order(sc["order"]["id"])
        assert order_after["allocated_value_cents"] == 0, "90000 -> 0"
        assert order_after["open_exposure_cents"] == 90000, (
            "The 60 open units at 1500 cents remain open demand"
        )
        assert order_after["version"] > order_pre["version"], (
            "The cascade bumps the touched order's version"
        )


class TestLotUnitConservation:
    def test_lot_unit_conservation_on_reserve(self, api):
        """PRD §3.4: "the reservation waterfall walks the part's `AVAILABLE`
        lots oldest date code first (ties by creation order), moving units from
        `qty_on_hand` into `qty_reserved` until every allocated unit is
        reserved."

        Design: Difficulty/compensating_invariant/lot_unit_conservation_reserve_release
        """
        sc = setup_allocated_order(quantity=60, lot_qty=100, line_code="LIN-I")
        lot = get_lot(sc["lot"]["id"])
        assert lot["qty_on_hand"] == 40
        assert lot["qty_reserved"] == 60
        assert lot["qty_shipped"] == 0
        assert lot["qty_received"] == 100
        assert_lot_unit_conservation(lot)  # 40 + 60 + 0 == 100

    def test_lot_unit_conservation_through_release_cycle(self, api):
        """PRD §3.5: "the lot's `qty_on_hand` absorbs its full `qty_reserved`,
        which is then zeroed."
        PRD §3.3: "for a line that held an allocation, its reserved units walk
        back across the part's lots — oldest date code first, ties broken by lot
        creation order, considering only lots with `qty_reserved` above zero —
        moving units from `qty_reserved` back into `qty_on_hand`."

        Design: Difficulty/compensating_invariant/lot_unit_conservation_reserve_release
        """
        sc = _setup_allocated_with_open_exposure(line_code="LIN-I")
        lot_id = sc["lot"]["id"]
        assert get_lot(lot_id)["qty_reserved"] == 60  # reserve: 40/60

        # Quarantine release: everything returns to on-hand.
        advance_clock("2026-08-05T04:00:00Z")
        lot_after_q = get_lot(lot_id)
        assert lot_after_q["qty_on_hand"] == 100
        assert lot_after_q["qty_reserved"] == 0
        assert_lot_unit_conservation(lot_after_q)

        # Bake the lot back to AVAILABLE and re-allocate the reopened line.
        seal_exposure_interval(lot_id, sc["exposure"]["id"])
        bake(lot_id)
        publish_run(create_allocation_run_for_part(sc["part"]["id"])["id"])
        line_mid = get_order_line(sc["order_line"]["id"])
        assert line_mid["status"] == "ALLOCATED"
        assert line_mid["allocated_qty"] == 60

        # Cancel the allocated line: reservations release again.
        cancelled = validate_success(
            api.cancel_order_line(sc["order"]["id"], line_mid["id"], SALES), 200)
        assert cancelled["status"] == "CANCELLED"

        lot_final = get_lot(lot_id)
        assert lot_final["qty_received"] == 100
        assert lot_final["qty_shipped"] == 0
        assert lot_final["qty_on_hand"] == 100
        assert lot_final["qty_reserved"] == 0
        assert_lot_unit_conservation(lot_final)

        part_final = get_part(sc["part"]["id"])
        assert part_final["qty_on_hand"] == 100
        assert part_final["qty_reserved"] == 0
