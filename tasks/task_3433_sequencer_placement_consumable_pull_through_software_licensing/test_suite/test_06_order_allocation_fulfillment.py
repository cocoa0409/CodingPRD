"""Reagent order allocation and fulfillment: FEFO waterfall, created_at
tie-break, all-or-nothing rejection, double-submit guard, cold-chain ship
gate, expiry sweep cascade, re-allocation sweep, and the reserve/cancel
conservation invariant (PRD sections 2.4, 2.9, 3.4, 3.5).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    assert_lot_invariants,
    create_account,
    create_kit,
    create_lot,
    create_order,
    create_passed_lot,
    lot_qc_payload,
    make_lab_operator_headers,
    order_advance_payload,
    order_line,
    submit_order,
    validate_error,
    validate_success,
)
from test_helpers import api_client

SP = TEST_USERS["supply_planner_headers"]


def _get_lot(lot_id: str) -> dict:
    return validate_success(api_client.get_reagent_lot(lot_id, SP))


def _get_order(order_id: str) -> dict:
    return validate_success(api_client.get_reagent_order(order_id, SP))


class TestFefoAllocation:
    def test_earliest_expiry_drained_first(self, api):
        """An order of 4 against lots expiring 2026-10-09 (3 units) and
        2026-10-14 (10 units) drains the earlier-expiring lot first and
        spills 1 unit into the later one.

        PRD §3.5: "For a line, the candidate lots are those of the named kit that are usable per §3.4, sorted by `expiry_date` ascending with `created_at` ascending as the tie-break — never by identifier."
        PRD §3.5: "The walk takes from each lot the smaller of the line's remaining need and the lot's `available_units` until the need reaches zero, and each take is recorded as one reservation."

        Design: Corner/calculations/fefo_allocation_earliest_expiry_first
        """
        account = create_account()
        kit = create_kit()
        # lot1 created FIRST but expires LATER — creation order must not win.
        lot1 = create_passed_lot(
            kit_id=kit["id"], lot_number="FF-1",
            manufacture_date="2026-08-15T00:00:00Z", quantity_units=10,
        )
        lot2 = create_passed_lot(
            kit_id=kit["id"], lot_number="FF-2",
            manufacture_date="2026-08-10T00:00:00Z", quantity_units=3,
        )
        order = create_order(account["id"], [order_line(kit["kit_code"], 4)])
        submitted = submit_order(order["id"], account["id"])
        reservations = {
            (r["lot_id"], r["quantity"]) for r in submitted["line_reservations"]
        }
        assert reservations == {(lot2["id"], 3), (lot1["id"], 1)}, (
            f"FEFO must take 3 from the earlier-expiring lot then 1 from the "
            f"later one, got {submitted['line_reservations']}"
        )
        assert _get_lot(lot2["id"])["reserved_units"] == 3
        assert _get_lot(lot1["id"])["reserved_units"] == 1

    def test_same_expiry_tie_breaks_by_created_at(self, api):
        """Two lots with identical expiry dates allocate from the one created
        earlier; the later lot is untouched. The logical clock is advanced
        between registrations so the created_at ordering is unambiguous.

        PRD §3.5: "For a line, the candidate lots are those of the named kit that are usable per §3.4, sorted by `expiry_date` ascending with `created_at` ascending as the tie-break — never by identifier."

        Design: Corner/calculations/allocation_tie_break_created_at
        """
        account = create_account()
        kit = create_kit()
        lot_a = create_passed_lot(kit_id=kit["id"], lot_number="TB-A",
                                  quantity_units=5)
        advance_clock("2026-09-01T00:01:00Z")
        lot_b = create_passed_lot(kit_id=kit["id"], lot_number="TB-B",
                                  quantity_units=5)
        order = create_order(account["id"], [order_line(kit["kit_code"], 2)])
        submit_order(order["id"], account["id"])
        assert _get_lot(lot_a["id"])["reserved_units"] == 2, (
            "identical expiry: the earlier-created lot must take the whole allocation"
        )
        assert _get_lot(lot_b["id"])["reserved_units"] == 0

    def test_insufficient_stock_is_all_or_nothing(self, api):
        """Total usable 3 < requested 5 fails the whole SUBMIT and retains
        zero reservations anywhere.

        PRD §3.5: "Submission is the heavy gate, and its checks have a definite order after the generic tiers of §2.9: if `program_id` is set, the referenced program must be `ACTIVE`, else `ERR_PROGRAM_NOT_ACTIVE`; the account's `credit_hold` must be false, else `ERR_CREDIT_HOLD` (HTTP 402); and allocation must be able to fully satisfy every line, else `ERR_ALLOCATION_IMPOSSIBLE` (HTTP 422) with no partial reservation retained anywhere."

        Design: Corner/calculations/allocation_insufficient_all_or_nothing_rejected
        """
        account = create_account()
        kit = create_kit()
        lot = create_passed_lot(kit_id=kit["id"], quantity_units=3)
        order = create_order(account["id"], [order_line(kit["kit_code"], 5)])
        resp = api_client.advance_reagent_order(
            order["id"],
            order_advance_payload("SUBMIT"),
            make_lab_operator_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_IMPOSSIBLE)
        assert _get_lot(lot["id"])["reserved_units"] == 0, (
            "no partial reservation may be retained"
        )
        assert _get_order(order["id"])["order_state"] == "DRAFT"


class TestOrderStateGuards:
    def test_double_submit_rejected(self, api):
        """SUBMIT is defined only from DRAFT; a second SUBMIT on the
        ALLOCATED order fails and no second reservation is taken.

        PRD §3.5: "The order moves `DRAFT` to `ALLOCATED` and stamps `submitted_at` with the current logical clock."
        PRD §2.9: "Eighth, the generic state-machine check that the attempted trigger is defined for the resource's current state, which also enforces terminal-state lockdown, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/order_double_submit_rejected
        """
        account = create_account()
        kit = create_kit()
        lot = create_passed_lot(kit_id=kit["id"], quantity_units=10)
        order = create_order(account["id"], [order_line(kit["kit_code"], 2)])
        submit_order(order["id"], account["id"])
        resp = api_client.advance_reagent_order(
            order["id"],
            order_advance_payload("SUBMIT"),
            make_lab_operator_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert _get_lot(lot["id"])["reserved_units"] == 2, (
            "the rejected second SUBMIT must not double-reserve"
        )

    def test_cold_chain_breach_blocks_shipment(self, api):
        """A COLD_CHAIN_BREACH verdict keeps the lot's reservations in place
        but blocks the SHIP leg; the order stays ALLOCATED.

        PRD §3.4: "A `COLD_CHAIN_BREACH` verdict behaves differently from a failure: it is a self-transition available from both `PENDING_QC` and `QC_PASSED` that sets `cold_chain_status` to `BREACHED` while leaving `qc_status` untouched."
        PRD §3.4: "Existing reservations are explicitly not released — the breach instead blocks the affected orders at shipment time (§3.5)."
        PRD §3.5: "Shipping is `SupplyPlanner` work and re-validates the physical gates: every reserved lot must still have `cold_chain_status` `INTACT`, else `ERR_COLD_CHAIN_BREACHED` (HTTP 422), and every reserved lot's `expiry_date` must still be strictly after the current logical clock, else `ERR_LOT_EXPIRED` (HTTP 422)."

        Design: Corner/validations/cold_chain_breach_blocks_shipment
        """
        account = create_account()
        kit = create_kit()
        lot = create_passed_lot(kit_id=kit["id"], quantity_units=5)
        order = create_order(account["id"], [order_line(kit["kit_code"], 1)])
        submit_order(order["id"], account["id"])
        breached = validate_success(
            api_client.post_lot_qc(lot["id"], lot_qc_payload("COLD_CHAIN_BREACH"), SP)
        )
        assert breached["cold_chain_status"] == "BREACHED"
        assert breached["reserved_units"] == 1, (
            "a breach must NOT release existing reservations"
        )
        resp = api_client.advance_reagent_order(
            order["id"], order_advance_payload("SHIP"), SP
        )
        validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_BREACHED)
        assert _get_order(order["id"])["order_state"] == "ALLOCATED"


class TestLotCascadeSweeps:
    def test_lot_expiry_sweep_releases_and_backorders(self, api):
        """Advancing the clock past a lot's expiry flips it EXPIRED and runs
        the release-and-backorder cascade: the reserved order goes
        BACKORDERED with its reservations released.

        PRD §2.4: "Reagent lots in `QC_PASSED` whose `expiry_date` has been reached become `EXPIRED` and run the release-and-backorder cascade described in §3.4."
        PRD §3.4: "Finally, the clock sweep of §2.4 expires lots: a `QC_PASSED` lot whose `expiry_date` has been reached moves to `EXPIRED` and runs the same release-and-backorder cascade as a field corrective action."

        Design: Corner/state_machines/lot_expiry_sweep_releases_and_backorders
        """
        account = create_account()
        kit = create_kit()
        # manufacture 2026-07-07 + 60 days shelf life -> expiry 2026-09-05
        lot = create_passed_lot(
            kit_id=kit["id"], manufacture_date="2026-07-07T00:00:00Z",
            quantity_units=5,
        )
        order = create_order(account["id"], [order_line(kit["kit_code"], 2)])
        submit_order(order["id"], account["id"])
        result = advance_clock("2026-09-06T00:00:00Z")
        assert result["lots_expired"] == 1
        lot_after = _get_lot(lot["id"])
        assert lot_after["qc_status"] == "EXPIRED"
        assert lot_after["reserved_units"] == 0
        assert _get_order(order["id"])["order_state"] == "BACKORDERED"

    def test_backordered_order_reallocated_on_lot_qc_pass(self, api):
        """The re-allocation sweep fires from a lot's QC_PASSED verdict, not
        from any order endpoint: the backordered order returns to ALLOCATED
        with a reservation on the newly released lot.

        PRD §3.4: "A `PASSED` verdict on a `PENDING_QC` lot moves it to `QC_PASSED` and fires the re-allocation sweep: every `BACKORDERED` order whose lines can now be fully satisfied from usable lots is re-allocated in order-`created_at` ascending order, first-expiry-first-out per line, transitioning each re-allocated order from `BACKORDERED` back to `ALLOCATED` and adding its `attributed_total_cents` back into its program's `pipeline_spend_cents`."
        PRD §3.5: "A `BACKORDERED` order returns to `ALLOCATED` through the re-allocation sweep on a later `QC_PASSED` verdict, re-running the same first-expiry-first-out allocation, rewriting `line_reservations`, and restoring its attributed amount to `pipeline_spend_cents`."

        Design: Corner/state_machines/backordered_order_auto_reallocated_on_lot_release
        """
        account = create_account()
        kit = create_kit()
        lot_a = create_passed_lot(kit_id=kit["id"], lot_number="RA-A",
                                  quantity_units=1)
        order = create_order(account["id"], [order_line(kit["kit_code"], 1)])
        submit_order(order["id"], account["id"])
        validate_success(
            api_client.post_lot_qc(lot_a["id"], lot_qc_payload("FAILED"), SP)
        )
        assert _get_order(order["id"])["order_state"] == "BACKORDERED"
        lot_b = create_lot(
            kit_id=kit["id"], lot_number="RA-B",
            manufacture_date="2026-08-20T00:00:00Z", quantity_units=1,
        )
        validate_success(
            api_client.post_lot_qc(lot_b["id"], lot_qc_payload("PASSED"), SP)
        )
        order_after = _get_order(order["id"])
        assert order_after["order_state"] == "ALLOCATED", (
            "the QC_PASSED verdict on lot B must sweep the backordered order"
        )
        reservations = order_after["line_reservations"]
        assert len(reservations) == 1
        assert reservations[0]["lot_id"] == lot_b["id"]
        assert reservations[0]["kit_code"] == kit["kit_code"]
        assert reservations[0]["quantity"] == 1
        assert _get_lot(lot_b["id"])["reserved_units"] == 1


class TestReserveCancelConservation:
    def _reserve_then_cancel(self):
        """Lot of 10 QC_PASSED; order of 4 SUBMITTED (reserve), then
        CANCELLED (release). Returns (lot_id, order_id, account_id)."""
        account = create_account()
        kit = create_kit()
        lot = create_passed_lot(kit_id=kit["id"], quantity_units=10)
        order = create_order(account["id"], [order_line(kit["kit_code"], 4)])
        return lot, order, account

    def test_reserve_then_cancel_restores_available_units(self, api):
        """SUBMIT takes available 10 -> 6; CANCEL returns the lot to exactly
        its pre-order state: reserved 0, consumed 0, available 10.

        PRD §3.4: "The lot's `available_units` is always derived: `quantity_units` minus `reserved_units` minus `consumed_units`."
        PRD §3.5: "A `LabOperator` cancels an order from `DRAFT`, `ALLOCATED`, or `BACKORDERED` into `CANCELLED`; cancelling an `ALLOCATED` order releases all of its `line_reservations` — each lot's `reserved_units` drops — and, when a program is attached, withdraws the `attributed_total_cents` from `pipeline_spend_cents`."

        Design: Difficulty/compensating_invariant/reserve_cancel_conserves_available_units
        """
        lot, order, account = self._reserve_then_cancel()
        submit_order(order["id"], account["id"])
        mid = _get_lot(lot["id"])
        assert mid["reserved_units"] == 4 and mid["available_units"] == 6

        resp = api_client.advance_reagent_order(
            order["id"],
            order_advance_payload("CANCEL"),
            make_lab_operator_headers(account["id"]),
        )
        cancelled = validate_success(resp)
        assert cancelled["order_state"] == "CANCELLED"
        end = _get_lot(lot["id"])
        assert end["reserved_units"] == 0
        assert end["consumed_units"] == 0
        assert end["available_units"] == 10, (
            "reserve-then-cancel must conserve available_units exactly"
        )

    def test_derived_availability_invariant_holds_at_each_step(self, api):
        """available_units == quantity - reserved - consumed after the
        reservation and again after the cancellation.

        PRD §3.4: "The lot's `available_units` is always derived: `quantity_units` minus `reserved_units` minus `consumed_units`."
        PRD §3.5: "A `LabOperator` cancels an order from `DRAFT`, `ALLOCATED`, or `BACKORDERED` into `CANCELLED`; cancelling an `ALLOCATED` order releases all of its `line_reservations` — each lot's `reserved_units` drops — and, when a program is attached, withdraws the `attributed_total_cents` from `pipeline_spend_cents`."

        Design: Difficulty/compensating_invariant/reserve_cancel_conserves_available_units
        """
        lot, order, account = self._reserve_then_cancel()
        submit_order(order["id"], account["id"])
        assert_lot_invariants(_get_lot(lot["id"]))
        validate_success(
            api_client.advance_reagent_order(
                order["id"],
                order_advance_payload("CANCEL"),
                make_lab_operator_headers(account["id"]),
            )
        )
        assert_lot_invariants(_get_lot(lot["id"]))
