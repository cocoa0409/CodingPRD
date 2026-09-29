"""Haggling with the supplier, sending units back, and the money that must add up.

Three stories are exercised here. A parts line's price negotiation is a loop:
the shop quotes, counters below the standing quote, and the supplier answers
with a revised quote that puts the line back where it already was, one round
further on. Sending units back to the supplier is the compensation of an order
that was already placed: the gross the shop committed can never shrink, so a
restocking fee has to show up as a loss bucket rather than as a hole in the
ledger. And a return against a part that is already bolted to the car reaches
past the parts line: it drags the whole repair order back to the body shop,
cancels the paint booking that was already running, and hands the paint stall
its minutes back.

The last group walks the four ways the negotiation loop refuses to move.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import PARTS_MANAGER_HEADERS

PROMISED_ETA = "2026-08-05T00:00:00Z"


# ---------------------------------------------------------------------------
# Local state builders
# ---------------------------------------------------------------------------
def _quoted_world(api):
    """A locked order with one original-equipment part quoted at 10,000 cents."""
    world = fx.locked_world(api, order_overrides={"deductible_cents": 25000})
    world["vendor"] = fx.create_vendor(
        api, name="Metro OEM Parts", part_types_offered=["OEM"], discount_pct=0
    )
    line = fx.add_parts_line(
        api,
        world["line_ids"][0],
        part_type="OEM",
        part_description="Quarter panel",
        list_price_cents=10000,
        qty=1,
    )
    world["parts_line_id"] = line["id"]
    world["part"] = fx.quote_part(api, line["id"], world["vendor"]["id"], 10000)
    return world


def _countered_world(api):
    """The same order after the shop has countered the 10,000 quote at 9,000."""
    world = _quoted_world(api)
    world["part"] = fx.counter_part(api, world["parts_line_id"], 9000)
    return world


def _received_two_unit_world(api):
    """A two-unit original-equipment line ordered and booked in complete."""
    world = fx.locked_world(api, order_overrides={"deductible_cents": 25000})
    world["vendor"] = fx.create_vendor(
        api,
        name="Metro OEM Parts",
        part_types_offered=["OEM"],
        discount_pct=0,
        restocking_fee_pct=0.2,
        max_qty_per_line=4,
    )
    line = fx.add_parts_line(
        api,
        world["line_ids"][0],
        part_type="OEM",
        part_description="Hinge kit",
        list_price_cents=10000,
        qty=2,
    )
    world["parts_line_id"] = line["id"]
    fx.quote_part(api, line["id"], world["vendor"]["id"], 10000)
    fx.accept_price(api, line["id"])
    fx.place_parts_order(api, line["id"], PROMISED_ETA)
    world["part"] = fx.receive_part(api, line["id"], 2, "CORRECT")
    world["order"] = fx.read_order(api, world["order_id"])
    return world


def _installed_part_in_refinish_world(api):
    """A fitted part on an order that has moved on to the paint booth.

    The body stall carried the repair occupancy and released its minutes when
    the order left `REPAIR`; the paint stall is holding 120 minutes for the
    refinish occupancy that is now running.
    """
    world = fx.locked_world(api, order_overrides={"deductible_cents": 25000})
    world["vendor"] = fx.create_vendor(
        api,
        name="Metro OEM Parts",
        part_types_offered=["OEM"],
        discount_pct=0,
        restocking_fee_pct=0.2,
        max_qty_per_line=4,
    )
    world["body_stall"] = fx.create_stall(api, name="Body 2", stall_type="BODY")
    world["paint_stall"] = fx.create_stall(api, name="Paint 2", stall_type="PAINT")
    line = fx.add_parts_line(
        api,
        world["line_ids"][0],
        part_type="OEM",
        part_description="Fender",
        list_price_cents=10000,
        qty=1,
    )
    world["parts_line_id"] = line["id"]
    fx.quote_part(api, line["id"], world["vendor"]["id"], 10000)
    fx.accept_price(api, line["id"])
    fx.place_parts_order(api, line["id"], PROMISED_ETA)
    fx.advance_stage(api, world["order_id"], "PARTS_STAGED")
    fx.receive_part(api, line["id"], 1, "CORRECT")
    world["repair_assignment"] = fx.book_stall(
        api, world["order_id"], world["body_stall"]["id"], "REPAIR", fx.T0800, fx.T1200
    )
    fx.advance_stage(api, world["order_id"], "REPAIR")
    fx.install_part(api, line["id"])
    world["refinish_assignment"] = fx.book_stall(
        api,
        world["order_id"],
        world["paint_stall"]["id"],
        "REFINISH_CALIBRATION",
        fx.T1300,
        fx.T1500,
    )
    world["order"] = fx.advance_stage(api, world["order_id"], "REFINISH_CALIBRATION")
    return world


# ---------------------------------------------------------------------------
# The price negotiation loop
# ---------------------------------------------------------------------------
class TestPartsPriceNegotiationCycle:
    """The haggle runs QUOTED, COUNTERED, QUOTED again, one round further on."""

    def test_countering_the_supplier_moves_the_quoted_line_to_countered(self, api):
        """A counter under the standing quote parks the line at COUNTERED on the same round.

        PRD: "Countering the supplier takes a `counter_unit_price_cents`, moves the line from `QUOTED` to `COUNTERED`, and increments the line's `version`."
        PRD: "The counter must be **strictly lower** than the standing `quoted_unit_price_cents`; a counter equal to or above the standing quote is refused with `ERR_COUNTER_NOT_LOWER`."
        Design: Difficulty/non_linear_state_machine/parts_line_negotiation_cycle_quoted_countered_quoted
        """
        world = _quoted_world(api)
        before = fx.read_parts_line(api, world["parts_line_id"])
        A.assert_parts_line_state(before, procurement_status="QUOTED")
        A.assert_count(before["quote_round"], 1, "quote_round")

        countered = validate_success(
            api.counter_offer_parts_line(
                world["parts_line_id"],
                f.counter_offer_payload(9000),
                PARTS_MANAGER_HEADERS,
            )
        )
        A.assert_parts_line_state(
            countered,
            procurement_status="COUNTERED",
            authorization_status="INSURER_ALLOWED",
        )
        A.assert_cents(countered["counter_unit_price_cents"], 9000, "counter_unit_price_cents")
        A.assert_cents(countered["quoted_unit_price_cents"], 10000, "quoted_unit_price_cents")
        A.assert_count(countered["quote_round"], 1, "quote_round")
        A.assert_version(countered, before["version"] + 1, "parts line")

    def test_the_suppliers_answer_returns_the_line_to_quoted_at_round_two(self, api):
        """The revised quote puts the line back in a state it already held, one round on.

        PRD: "The supplier's answer to a counter is another quote, and this is the cycle: recording a quote against a `COUNTERED` line returns it to `QUOTED`, overwrites `quoted_unit_price_cents` with the revised figure, clears `counter_unit_price_cents`, and increments `quote_round` by one."
        PRD: "`authorization_status` runs `INSURER_ALLOWED`, `PENDING_CONSENT`, `CUSTOMER_CONSENTED` and the terminal `CUSTOMER_DECLINED`; it is decided at creation from insurer policy, vehicle age and the owner's standing preference, and is thereafter moved only by the owner's consent decision."
        Design: Difficulty/non_linear_state_machine/parts_line_negotiation_cycle_quoted_countered_quoted
        """
        world = _countered_world(api)
        before = fx.read_parts_line(api, world["parts_line_id"])
        A.assert_parts_line_state(before, procurement_status="COUNTERED")
        A.assert_cents(before["counter_unit_price_cents"], 9000, "counter_unit_price_cents")

        requoted = validate_success(
            api.quote_parts_line(
                world["parts_line_id"],
                f.quote_payload(world["vendor"]["id"], 9500),
                PARTS_MANAGER_HEADERS,
            )
        )
        A.assert_parts_line_state(
            requoted,
            procurement_status="QUOTED",
            authorization_status="INSURER_ALLOWED",
        )
        A.assert_count(requoted["quote_round"], 2, "quote_round")
        A.assert_cents(requoted["quoted_unit_price_cents"], 9500, "quoted_unit_price_cents")
        A.assert_null(requoted["counter_unit_price_cents"], "counter_unit_price_cents")
        assert requoted["vendor_id"] == world["vendor"]["id"], (
            "the revised quote keeps the supplier already on the line"
        )
        A.assert_version(requoted, before["version"] + 1, "parts line")

    def test_a_counter_equal_to_the_revised_quote_cannot_spin_the_cycle(self, api):
        """The loop only turns again when the shop concedes on price.

        PRD: "The counter must be **strictly lower** than the standing `quoted_unit_price_cents`; a counter equal to or above the standing quote is refused with `ERR_COUNTER_NOT_LOWER`."
        PRD: "`procurement_status` runs `PLANNED`, `QUOTED`, `COUNTERED`, `PRICE_LOCKED`, `ORDERED`, `RECEIVED`, `INSTALLED`, and terminates at `RETURNED` or `VOID`; it is cyclic between `QUOTED` and `COUNTERED` for as long as the price negotiation runs."
        Design: Difficulty/non_linear_state_machine/parts_line_negotiation_cycle_quoted_countered_quoted
        """
        world = _countered_world(api)
        fx.quote_part(api, world["parts_line_id"], world["vendor"]["id"], 9500)

        refused = api.counter_offer_parts_line(
            world["parts_line_id"],
            f.counter_offer_payload(9500),
            PARTS_MANAGER_HEADERS,
        )
        validate_error(refused, ApiErrorId.COUNTER_NOT_LOWER.value, 422)

        unmoved = fx.read_parts_line(api, world["parts_line_id"])
        A.assert_parts_line_state(unmoved, procurement_status="QUOTED")
        A.assert_count(unmoved["quote_round"], 2, "quote_round")
        A.assert_cents(unmoved["quoted_unit_price_cents"], 9500, "quoted_unit_price_cents")
        A.assert_null(unmoved["counter_unit_price_cents"], "counter_unit_price_cents")


# ---------------------------------------------------------------------------
# The commitment ledger and its three buckets
# ---------------------------------------------------------------------------
class TestPartsReturnLedgerConservation:
    """Whatever the shop committed stays accounted for after units go back."""

    def test_a_full_unused_return_keeps_the_ordered_gross_across_the_three_buckets(self, api):
        """Sending both units back leaves the 20,000 cents split as nil committed, credit and fee.

        PRD: "An order's parts commitment must satisfy a conservation identity at all times: `parts_ordered_gross_cents` equals `parts_committed_cents` plus `parts_return_credit_cents` plus `parts_restocking_loss_cents`."
        PRD: "The gross figure is append-only — it rises at every successful order and is never decremented — so a restocking fee shows up as a loss bucket rather than as a leak in the identity."
        PRD: "The restocking fee is charged **only** when the shop over-ordered: it is `unit_extended_cents` multiplied by the `return_qty` and then by the supplier's `restocking_fee_pct`, rounded half up, when the `return_reason` is `UNUSED`, and zero when the reason is `INCORRECT` or `DAMAGED` — a supplier's own error is free to send back."
        Design: Difficulty/compensating_invariant/full_parts_return_conserves_ordered_gross_across_the_three_buckets
        """
        world = _received_two_unit_world(api)
        A.assert_totals(
            world["order"],
            parts_ordered_gross_cents=20000,
            parts_committed_cents=20000,
            parts_return_credit_cents=0,
            parts_restocking_loss_cents=0,
        )
        A.assert_parts_conservation(world["order"])

        returned = validate_success(
            api.return_parts_line(
                world["parts_line_id"],
                f.return_payload(2, "UNUSED"),
                PARTS_MANAGER_HEADERS,
            )
        )
        A.assert_parts_line_state(returned, procurement_status="RETURNED")
        A.assert_count(returned["returned_qty"], 2, "returned_qty")
        A.assert_cents(returned["restocking_fee_cents"], 4000, "restocking_fee_cents")
        A.assert_extension(returned, 10000, 0)

        after = fx.read_order(api, world["order_id"])
        A.assert_totals(
            after,
            parts_ordered_gross_cents=20000,
            parts_committed_cents=0,
            parts_return_credit_cents=16000,
            parts_restocking_loss_cents=4000,
        )
        A.assert_parts_conservation(after)

    def test_a_partial_unused_return_splits_the_gross_without_losing_a_cent(self, api):
        """One unit back of two leaves the line where it was and still balances the ledger.

        PRD: "A **full** return — a `return_qty` equal to `qty` less the already-`returned_qty` — moves the line to the terminal `RETURNED`; a **partial** return leaves the `procurement_status` exactly where it was and fires the identical ledger cascade over the returned units only."
        PRD: "An order's parts commitment must satisfy a conservation identity at all times: `parts_ordered_gross_cents` equals `parts_committed_cents` plus `parts_return_credit_cents` plus `parts_restocking_loss_cents`."
        PRD: "`parts_committed_cents` is the sum, over the order's parts lines whose `procurement_status` is `ORDERED`, `RECEIVED` or `INSTALLED`, of each line's `unit_extended_cents` multiplied by its `qty` less its `returned_qty`."
        Design: Difficulty/compensating_invariant/full_parts_return_conserves_ordered_gross_across_the_three_buckets
        """
        world = _received_two_unit_world(api)

        returned = validate_success(
            api.return_parts_line(
                world["parts_line_id"],
                f.return_payload(1, "UNUSED"),
                PARTS_MANAGER_HEADERS,
            )
        )
        A.assert_parts_line_state(returned, procurement_status="RECEIVED")
        A.assert_count(returned["returned_qty"], 1, "returned_qty")
        A.assert_cents(returned["restocking_fee_cents"], 2000, "restocking_fee_cents")
        A.assert_extension(returned, 10000, 10000)

        after = fx.read_order(api, world["order_id"])
        A.assert_totals(
            after,
            parts_ordered_gross_cents=20000,
            parts_committed_cents=10000,
            parts_return_credit_cents=8000,
            parts_restocking_loss_cents=2000,
        )
        A.assert_parts_conservation(after)

    def test_the_return_credit_cannot_be_claimed_twice_on_a_returned_line(self, api):
        """A line already sent back in full refuses a second return and the buckets hold.

        PRD: "**Returning units** is available from `RECEIVED` and also from `INSTALLED` — a part already bolted to the car can be pulled back off when it turns out to be the wrong one, and that is the only path by which a return can reach an order that has already left `REPAIR`."
        PRD: "State preconditions in this order: the order's `stage` lies in the operation's declared from-state set (`ERR_STAGE_PRECONDITION`); then, for a stage advance, the requested `to_stage` is the declared successor (`ERR_STAGE_SEQUENCE_INVALID`); then the parts line's `procurement_status` lies in the operation's declared from-state set (`ERR_PARTS_LINE_STATE`); then the order's `authorization_posture` is `OPEN` (`ERR_AUTHORIZATION_POSTURE_BLOCKED`); then the supplement is open for the requested action (`ERR_SUPPLEMENT_NOT_OPEN`); then the procedure record's `calibration_status` permits the requested action (`ERR_CALIBRATION_STATE`); then the stall booking is still `SCHEDULED` (`ERR_ASSIGNMENT_NOT_SCHEDULED`)."
        PRD: "An order's parts commitment must satisfy a conservation identity at all times: `parts_ordered_gross_cents` equals `parts_committed_cents` plus `parts_return_credit_cents` plus `parts_restocking_loss_cents`."
        Design: Difficulty/compensating_invariant/full_parts_return_conserves_ordered_gross_across_the_three_buckets
        """
        world = _received_two_unit_world(api)
        fx.return_units(api, world["parts_line_id"], 2, "UNUSED")

        refused = api.return_parts_line(
            world["parts_line_id"],
            f.return_payload(1, "UNUSED"),
            PARTS_MANAGER_HEADERS,
        )
        validate_error(refused, ApiErrorId.PARTS_LINE_STATE.value, 409)

        line = fx.read_parts_line(api, world["parts_line_id"])
        A.assert_parts_line_state(line, procurement_status="RETURNED")
        A.assert_count(line["returned_qty"], 2, "returned_qty")
        A.assert_cents(line["restocking_fee_cents"], 4000, "restocking_fee_cents")

        after = fx.read_order(api, world["order_id"])
        A.assert_totals(
            after,
            parts_ordered_gross_cents=20000,
            parts_committed_cents=0,
            parts_return_credit_cents=16000,
            parts_restocking_loss_cents=4000,
        )
        A.assert_parts_conservation(after)


# ---------------------------------------------------------------------------
# The return that reaches past the parts line
# ---------------------------------------------------------------------------
class TestPartsReturnDragsTheOrderBack:
    """A part coming off the car pulls the whole order back into the body shop."""

    def test_returning_a_fitted_part_rolls_the_order_back_and_releases_the_paint_stall(self, api):
        """The rollback cancels the running paint occupancy and hands back its 120 minutes.

        PRD: "And when the order had already moved past `REPAIR` — that is, when its `stage` is `REFINISH_CALIBRATION` or `READY_FOR_QC` and the returned line was `RECEIVED` or `INSTALLED` before the return — the return **drags the order back**: `stage` rolls back to `REPAIR`; every stall booking on the order whose `stage` is `REFINISH_CALIBRATION` and whose `status` is `ACTIVE` becomes `CANCELLED`; and each cancelled booking releases exactly its `occupied_minutes` from its stall's `booked_minutes`."
        PRD: "Those three are caused hops in sequence, and each must land."
        Design: Difficulty/transitive_cascade/parts_return_cascades_stage_rollback_assignment_cancel_and_stall_release
        """
        world = _installed_part_in_refinish_world(api)
        A.assert_stage(world["order"], "REFINISH_CALIBRATION")

        paint_booking_before = fx.read_assignment(api, world["refinish_assignment"]["id"])
        assert paint_booking_before["status"] == "ACTIVE", (
            "the refinish occupancy is running before the return: "
            f"{paint_booking_before['status']}"
        )
        A.assert_count(paint_booking_before["occupied_minutes"], 120, "occupied_minutes")
        paint_stall_before = fx.read_stall(api, world["paint_stall"]["id"])
        A.assert_count(paint_stall_before["booked_minutes"], 120, "paint booked_minutes")

        returned = validate_success(
            api.return_parts_line(
                world["parts_line_id"],
                f.return_payload(1, "INCORRECT"),
                PARTS_MANAGER_HEADERS,
            )
        )
        A.assert_parts_line_state(returned, procurement_status="RETURNED")
        A.assert_count(returned["returned_qty"], 1, "returned_qty")
        A.assert_cents(returned["restocking_fee_cents"], 0, "restocking_fee_cents")
        A.assert_extension(returned, 10000, 0)

        order = fx.read_order(api, world["order_id"])
        A.assert_stage(order, "REPAIR")

        paint_booking_after = fx.read_assignment(api, world["refinish_assignment"]["id"])
        assert paint_booking_after["status"] == "CANCELLED", (
            "the refinish occupancy is cancelled, not completed: "
            f"{paint_booking_after['status']}"
        )
        A.assert_version(
            paint_booking_after, paint_booking_before["version"] + 1, "stall booking"
        )

        paint_stall_after = fx.read_stall(api, world["paint_stall"]["id"])
        A.assert_count(paint_stall_after["booked_minutes"], 0, "paint booked_minutes")
        A.assert_version(paint_stall_after, paint_stall_before["version"] + 1, "stall")

        body_stall_after = fx.read_stall(api, world["body_stall"]["id"])
        A.assert_count(body_stall_after["booked_minutes"], 0, "body booked_minutes")

    def test_returning_a_fitted_part_reruns_the_ledger_the_totals_and_the_delay_count(self, api):
        """The money hops land too: committed drains into credit and a delay is opened.

        PRD: "Hop one, caused by the line leaving the committed input set: the commitment ledger reruns, so `parts_committed_cents` falls by the returned value, `parts_return_credit_cents` rises by `unit_extended_cents` multiplied by `return_qty` less `restocking_fee_cents`, and `parts_restocking_loss_cents` rises by `restocking_fee_cents`."
        PRD: "The eight-step totals then rerun, moving `parts_gross_cents`, `parts_subtotal_cents`, `pre_tax_total_cents` and `customer_pay_cents`."
        PRD: "When the `return_reason` is `INCORRECT`, a delay event is opened against the line with `reason` `INCORRECT_PART`, raising the order's `open_parts_delay_count`."
        Design: Difficulty/transitive_cascade/parts_return_cascades_stage_rollback_assignment_cancel_and_stall_release
        """
        world = _installed_part_in_refinish_world(api)
        before = fx.read_order(api, world["order_id"])
        A.assert_totals(
            before,
            parts_ordered_gross_cents=10000,
            parts_committed_cents=10000,
            parts_return_credit_cents=0,
            parts_restocking_loss_cents=0,
            parts_gross_cents=10000,
            pre_tax_total_cents=38080,
        )
        A.assert_parts_conservation(before)
        A.assert_count(before["open_parts_delay_count"], 0, "open_parts_delay_count")

        fx.return_units(api, world["parts_line_id"], 1, "INCORRECT")

        after = fx.read_order(api, world["order_id"])
        A.assert_totals(
            after,
            parts_ordered_gross_cents=10000,
            parts_committed_cents=0,
            parts_return_credit_cents=10000,
            parts_restocking_loss_cents=0,
            parts_gross_cents=0,
            parts_subtotal_cents=0,
            pre_tax_total_cents=28080,
            insurer_authorized_cents=3080,
            customer_pay_cents=25000,
        )
        A.assert_parts_conservation(after)
        A.assert_customer_pay_split(after)
        A.assert_posture(after, "OPEN")
        A.assert_count(after["open_parts_delay_count"], 1, "open_parts_delay_count")

        events, meta = fx.page(
            api.list_parts_line_delay_events(world["parts_line_id"], PARTS_MANAGER_HEADERS)
        )
        A.assert_page(meta, total_count=1)
        assert events[0]["reason"] == "INCORRECT_PART", (
            f"the opened delay names the wrong reason: {events[0]['reason']}"
        )
        A.assert_null(events[0]["closed_at"], "closed_at")


# ---------------------------------------------------------------------------
# Misplaying the haggle
# ---------------------------------------------------------------------------
class TestPartsNegotiationMissteps:
    """The four refusals of the negotiation loop, each reachable on its own."""

    def test_every_misstep_in_the_negotiation_loop_carries_its_own_refusal(self, api):
        """A flat counter, a foreign part type, a swapped supplier and an early acceptance.

        PRD: "The counter must be **strictly lower** than the standing `quoted_unit_price_cents`; a counter equal to or above the standing quote is refused with `ERR_COUNTER_NOT_LOWER`."
        PRD: "Before that transition is allowed, the line's `part_type` must appear in the supplier's `part_types_offered`, or the quote is refused with `ERR_PART_TYPE_NOT_OFFERED`."
        PRD: "The revised quote must name the same `vendor_id` already on the line — you cannot swap suppliers mid-negotiation — and a different supplier is refused with `ERR_VENDOR_MISMATCH`."
        PRD: "Accepting the price moves the line from `QUOTED` to `PRICE_LOCKED` and takes no input at all — the standing quote is what gets frozen."
        PRD: "State preconditions in this order: the order's `stage` lies in the operation's declared from-state set (`ERR_STAGE_PRECONDITION`); then, for a stage advance, the requested `to_stage` is the declared successor (`ERR_STAGE_SEQUENCE_INVALID`); then the parts line's `procurement_status` lies in the operation's declared from-state set (`ERR_PARTS_LINE_STATE`); then the order's `authorization_posture` is `OPEN` (`ERR_AUTHORIZATION_POSTURE_BLOCKED`); then the supplement is open for the requested action (`ERR_SUPPLEMENT_NOT_OPEN`); then the procedure record's `calibration_status` permits the requested action (`ERR_CALIBRATION_STATE`); then the stall booking is still `SCHEDULED` (`ERR_ASSIGNMENT_NOT_SCHEDULED`)."
        Design: Corner/errors/parts_negotiation_missteps_are_rejected
        """
        world = fx.locked_world(
            api,
            order_overrides={"deductible_cents": 25000},
            insurer_overrides={"insurer_code": "CRNR-44", "name": "Cornerstone Mutual"},
        )
        alpha = fx.create_vendor(
            api,
            name="Vendor Alpha",
            part_types_offered=["OEM"],
            discount_pct=0,
            max_qty_per_line=5,
        )
        beta = fx.create_vendor(
            api,
            name="Vendor Beta",
            part_types_offered=["OEM"],
            discount_pct=0,
            max_qty_per_line=5,
        )
        oem_line = fx.add_parts_line(
            api,
            world["line_ids"][0],
            part_type="OEM",
            part_description="Door shell",
            list_price_cents=30000,
            qty=1,
            vendor_id=alpha["id"],
        )
        aftermarket_line = fx.add_parts_line(
            api,
            world["line_ids"][0],
            part_type="AFTERMARKET",
            part_description="Aftermarket mirror",
            list_price_cents=9000,
            qty=1,
        )
        fx.quote_part(api, oem_line["id"], alpha["id"], 20000)

        # A counter at the standing quote, and one above it, are the same refusal.
        for counter_cents in (20000, 20500):
            flat_counter = api.counter_offer_parts_line(
                oem_line["id"],
                f.counter_offer_payload(counter_cents),
                PARTS_MANAGER_HEADERS,
            )
            validate_error(flat_counter, ApiErrorId.COUNTER_NOT_LOWER.value, 422)

        standing = fx.read_parts_line(api, oem_line["id"])
        A.assert_parts_line_state(standing, procurement_status="QUOTED")
        A.assert_count(standing["quote_round"], 1, "quote_round")
        A.assert_null(standing["counter_unit_price_cents"], "counter_unit_price_cents")

        # A supplier that lists original equipment only cannot quote an aftermarket part.
        foreign_channel = api.quote_parts_line(
            aftermarket_line["id"],
            f.quote_payload(alpha["id"], 8000),
            PARTS_MANAGER_HEADERS,
        )
        validate_error(foreign_channel, ApiErrorId.PART_TYPE_NOT_OFFERED.value, 422)
        A.assert_parts_line_state(
            fx.read_parts_line(api, aftermarket_line["id"]), procurement_status="PLANNED"
        )

        countered = fx.counter_part(api, oem_line["id"], 18000)
        A.assert_parts_line_state(countered, procurement_status="COUNTERED")
        A.assert_cents(countered["counter_unit_price_cents"], 18000, "counter_unit_price_cents")

        # The price cannot be frozen while a counter is still on the table.
        early_acceptance = api.accept_parts_price(oem_line["id"], None, PARTS_MANAGER_HEADERS)
        validate_error(early_acceptance, ApiErrorId.PARTS_LINE_STATE.value, 409)

        # Nor can the supplier be swapped mid-negotiation.
        swapped_supplier = api.quote_parts_line(
            oem_line["id"], f.quote_payload(beta["id"], 19000), PARTS_MANAGER_HEADERS
        )
        validate_error(swapped_supplier, ApiErrorId.VENDOR_MISMATCH.value, 422)

        still_countered = fx.read_parts_line(api, oem_line["id"])
        A.assert_parts_line_state(still_countered, procurement_status="COUNTERED")
        A.assert_cents(
            still_countered["counter_unit_price_cents"], 18000, "counter_unit_price_cents"
        )
        A.assert_count(still_countered["quote_round"], 1, "quote_round")

        # The same call from the supplier already on the line is the legal move.
        requoted = validate_success(
            api.quote_parts_line(
                oem_line["id"], f.quote_payload(alpha["id"], 19000), PARTS_MANAGER_HEADERS
            )
        )
        A.assert_parts_line_state(requoted, procurement_status="QUOTED")
        A.assert_count(requoted["quote_round"], 2, "quote_round")
        A.assert_cents(requoted["quoted_unit_price_cents"], 19000, "quoted_unit_price_cents")
        A.assert_null(requoted["counter_unit_price_cents"], "counter_unit_price_cents")
