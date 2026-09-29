"""Supplier performance scoring and the gates that guard a purchase order.

Every part the shop buys leaves a mark on the supplier that sold it: whether it
landed by the promised instant, whether any of it went back, and how many rounds
of haggling it took to agree the price. Those marks feed two scores that sit side
by side on the supplier row — one over the whole trading history, one over only
the three most recent deliveries — and the purchase order consults the recent one
alone. This file walks whole parts lines through to receipt so that the two
scores genuinely diverge, then pushes the resulting figure against the ordering
floor, and finally checks that a supplier the shop has stopped buying from is
turned away before anyone bothers to look at its quantity cap.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import PARTS_MANAGER_HEADERS

# The trading calendar the histories below are built on: the parts go out on the
# third, the promised arrivals are either the fifth or the tenth, and the van
# actually turns up on the eighth.
_ORDER_DAY = "2026-08-03T00:00:00Z"
_EARLY_ETA = "2026-08-05T00:00:00Z"
_RECEIPT_DAY = "2026-08-08T00:00:00Z"
_LATE_ETA = "2026-08-10T00:00:00Z"
_FIFTH_ETA = "2026-08-15T00:00:00Z"
_RETURN_DAY = "2026-08-20T00:00:00Z"

_DEDUCTIBLE_CENTS = 25000
_LIST_PRICE_CENTS = 10000
_AGREED_UNIT_CENTS = 10000


def _supplier_with_one_early_win(api):
    """Four identical parts lines walked to receipt against a single supplier.

    Only the first line — the one holding `vendor_order_seq` 1 — was promised
    late enough to arrive on time. The other three were promised for the fifth
    and booked in on the eighth, so the supplier's recent record is a clean sweep
    of late deliveries sitting behind one old success.
    """
    fx.set_clock(api, _ORDER_DAY)
    world = fx.locked_world(
        api, order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS}
    )
    vendor = fx.create_vendor(
        api,
        name="Metro OEM Parts",
        vendor_type="OEM_DEALER",
        part_types_offered=["OEM"],
    )
    world["vendor"] = vendor
    world["vendor_id"] = vendor["id"]
    world["labor_line_id"] = world["lines"][0]["id"]

    ordered = []
    for promised_eta in (_LATE_ETA, _EARLY_ETA, _EARLY_ETA, _EARLY_ETA):
        ordered.append(_walk_to_ordered(api, world, promised_eta))

    fx.set_clock(api, _RECEIPT_DAY)
    world["closed_lines"] = [
        fx.receive_part(api, line["id"], 1, "CORRECT") for line in ordered
    ]
    return world


def _walk_to_ordered(api, world, promised_eta, qty=1):
    """One original-equipment line taken from planned all the way to ordered."""
    line = _walk_to_price_locked(api, world, qty=qty)
    return fx.place_parts_order(api, line["id"], promised_eta)


def _walk_to_price_locked(api, world, qty=1):
    """One original-equipment line quoted at list and frozen at that price."""
    line = fx.add_parts_line(
        api,
        world["labor_line_id"],
        part_type="OEM",
        list_price_cents=_LIST_PRICE_CENTS,
        qty=qty,
    )
    fx.quote_part(api, line["id"], world["vendor_id"], _AGREED_UNIT_CENTS)
    return fx.accept_price(api, line["id"])


class TestTheTwoSupplierPerformanceScores:
    """The same four deliveries, read through two different windows."""

    def test_the_recent_window_reports_forty_over_three_late_deliveries(self, api):
        """Three late arrivals in a row drop the recent-window score to forty.

        PRD: "The `LIFETIME` variant takes the whole set as its window; the `ROLLING` variant takes only the three most recent lines in that ordering."
        PRD: "The `ROLLING` score, over sequences 4, 3 and 2 only, is 100 times the quantity 0.6 times zero, plus 0.25 times one, plus 0.15 times one — that is 40."
        Design: Difficulty/dual_variant_calc/vendor_fulfillment_score_rolling_window_versus_lifetime
        """
        world = _supplier_with_one_early_win(api)
        closed = world["closed_lines"]

        assert [line["vendor_order_seq"] for line in closed] == [1, 2, 3, 4]
        assert closed[0]["on_time"] is True
        for line in closed[1:]:
            assert line["on_time"] is False
        for line in closed:
            A.assert_count(line["returned_qty"], 0, "returned_qty")
            A.assert_count(line["quote_round"], 1, "quote_round")

        vendor = fx.read_vendor(api, world["vendor_id"])
        A.assert_count(
            vendor["fulfillment_score_rolling"], 40, "fulfillment_score_rolling"
        )

    def test_the_whole_history_window_reports_fifty_five_on_the_same_deliveries(
        self, api
    ):
        """The old on-time delivery still counts over the whole trading history.

        PRD: "The `LIFETIME` score is 100 times the quantity 0.6 times one quarter, plus 0.25 times one, plus 0.15 times one — that is 55."
        PRD: "The `ROLLING` result is written to `fulfillment_score_rolling`; the `LIFETIME` result is written to `fulfillment_score_lifetime`."
        Design: Difficulty/dual_variant_calc/vendor_fulfillment_score_rolling_window_versus_lifetime
        """
        world = _supplier_with_one_early_win(api)

        vendor = fx.read_vendor(api, world["vendor_id"])
        A.assert_count(
            vendor["fulfillment_score_lifetime"], 55, "fulfillment_score_lifetime"
        )
        A.assert_scores(vendor, rolling=40, lifetime=55)
        assert (
            vendor["fulfillment_score_lifetime"] - vendor["fulfillment_score_rolling"]
            == 15
        ), "identical deliveries must read fifteen points apart across the two windows"


def _supplier_sitting_exactly_on_the_score_floor(api):
    """The four-delivery supplier, plus a fifth line quoted and price-locked.

    The recent-window score is exactly the ordering floor of forty at this point,
    and the fifth line is standing ready to be bought.
    """
    world = _supplier_with_one_early_win(api)
    world["fifth_line"] = _walk_to_price_locked(api, world)
    return world


class TestTheSupplierScoreFloorOnPlacingAnOrder:
    """Exactly forty still buys; a collapsed recent window does not."""

    def test_a_supplier_resting_on_exactly_forty_may_still_be_bought_from(self, api):
        """A recent-window score of exactly forty clears the ordering floor.

        PRD: "The supplier's `fulfillment_score_rolling` must be at least 40, or the request is refused with `ERR_VENDOR_SCORE_BELOW_FLOOR`."
        PRD: "A successful order moves the line from `PRICE_LOCKED` to `ORDERED`, stamps the supplied `promised_eta`, and stamps `vendor_order_seq` from the supplier's `order_seq_counter` after incrementing it — so the sequence numbers a supplier hands out are strictly increasing and unique to that supplier."
        Design: Difficulty/boundary_precision_check/vendor_score_floor_is_inclusive_at_exactly_40_on_order
        """
        world = _supplier_sitting_exactly_on_the_score_floor(api)

        before = fx.read_vendor(api, world["vendor_id"])
        A.assert_count(
            before["fulfillment_score_rolling"],
            C.VENDOR_SCORE_FLOOR,
            "fulfillment_score_rolling",
        )

        response = api.order_parts_line(
            world["fifth_line"]["id"], f.order_payload(_FIFTH_ETA), PARTS_MANAGER_HEADERS
        )
        ordered = get_success_data(response)

        A.assert_parts_line_state(ordered, procurement_status="ORDERED")
        A.assert_count(ordered["vendor_order_seq"], 5, "vendor_order_seq")
        A.assert_instant(ordered["promised_eta"], _FIFTH_ETA, "promised_eta")
        A.assert_count(
            fx.read_vendor(api, world["vendor_id"])["order_seq_counter"],
            5,
            "order_seq_counter",
        )

    def test_a_supplier_under_the_floor_is_refused_despite_a_healthy_lifetime_score(
        self, api
    ):
        """A late-and-returned delivery drags the recent window under the floor.

        PRD: "The supplier's `fulfillment_score_rolling` must be at least 40, or the request is refused with `ERR_VENDOR_SCORE_BELOW_FLOOR`."
        PRD: "The ordering gate at §3.6 tests the `ROLLING` figure and only the `ROLLING` figure: a comfortable lifetime score does not rescue a supplier whose recent window has collapsed."
        Design: Difficulty/boundary_precision_check/vendor_score_floor_is_inclusive_at_exactly_40_on_order
        """
        world = _supplier_sitting_exactly_on_the_score_floor(api)
        fifth_id = world["fifth_line"]["id"]
        fx.place_parts_order(api, fifth_id, _FIFTH_ETA)

        fx.set_clock(api, _RETURN_DAY)
        received = fx.receive_part(api, fifth_id, 1, "CORRECT")
        assert received["on_time"] is False
        returned = fx.return_units(api, fifth_id, 1, "UNUSED")
        A.assert_cents(returned["restocking_fee_cents"], 2000, "restocking_fee_cents")

        dragged = fx.read_vendor(api, world["vendor_id"])
        A.assert_scores(dragged, rolling=32, lifetime=47)
        assert dragged["fulfillment_score_lifetime"] >= C.VENDOR_SCORE_FLOOR, (
            "the lifetime score is meant to stay comfortably above the floor"
        )

        sixth = _walk_to_price_locked(api, world)
        response = api.order_parts_line(
            sixth["id"], f.order_payload(_RETURN_DAY), PARTS_MANAGER_HEADERS
        )
        validate_error(response, ApiErrorId.VENDOR_SCORE_BELOW_FLOOR.value, 422)

        untouched = fx.read_parts_line(api, sixth["id"])
        A.assert_parts_line_state(untouched, procurement_status="PRICE_LOCKED")
        A.assert_null(untouched["vendor_order_seq"], "vendor_order_seq")


def _line_ready_to_buy_from(api, vendor_status):
    """A price-locked line for three units against a supplier capped at one.

    The supplier's own quantity cap is broken by the request whatever its trading
    status, so the two refusals are both live at once and only the reported error
    identifier can tell which rule answered first. The order's money picture is
    deliberately quiet — the owner's share is exactly the deductible — so neither
    the freeze nor the exposure ceiling can mask the pair.
    """
    world = fx.locked_world(
        api, order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS}
    )
    vendor = fx.create_vendor(
        api,
        name="Halted Supply Co",
        vendor_type="OEM_DEALER",
        part_types_offered=["OEM"],
        status=vendor_status,
        max_qty_per_line=1,
    )
    world["vendor"] = vendor
    world["vendor_id"] = vendor["id"]
    world["labor_line_id"] = world["lines"][0]["id"]
    world["parts_line"] = _walk_to_price_locked(api, world, qty=3)
    return world


class TestASuspendedSupplierIsTurnedAwayBeforeItsQuantityCap:
    """Both refusals are live; the trading status answers first."""

    def test_a_suspended_supplier_over_its_quantity_cap_reports_the_suspension(
        self, api
    ):
        """A supplier the shop has stopped buying from is refused on that ground.

        PRD: "The supplier's `status` must be `ACTIVE`, or it is refused with `ERR_VENDOR_SUSPENDED`."
        PRD: "Supplier suspension is ranked above the supplier's own quantity cap because a suspended supplier is not a counterparty at all — its cap is irrelevant."
        Design: Difficulty/priority_pair_validation_conflict/order_vendor_suspension_outranks_vendor_quantity_cap
        """
        world = _line_ready_to_buy_from(api, "SUSPENDED")
        parts_line_id = world["parts_line"]["id"]

        A.assert_posture(fx.read_order(api, world["order_id"]), "OPEN")

        response = api.order_parts_line(
            parts_line_id, f.order_payload(_LATE_ETA), PARTS_MANAGER_HEADERS
        )
        validate_error(response, ApiErrorId.VENDOR_SUSPENDED.value, 422)

        untouched = fx.read_parts_line(api, parts_line_id)
        A.assert_parts_line_state(untouched, procurement_status="PRICE_LOCKED")
        A.assert_null(untouched["vendor_order_seq"], "vendor_order_seq")
        A.assert_count(
            fx.read_vendor(api, world["vendor_id"])["order_seq_counter"],
            C.DEFAULT_ORDER_SEQ_COUNTER,
            "order_seq_counter",
        )

    def test_the_same_over_cap_request_to_an_active_supplier_reports_the_cap(self, api):
        """With the trading status healthy, the quantity cap is what answers.

        PRD: "The line's `qty` must not exceed the supplier's `max_qty_per_line`, or it is refused with `ERR_VENDOR_QTY_CAP_EXCEEDED`."
        PRD: "No side effect of any kind is applied when a check fails."
        Design: Difficulty/priority_pair_validation_conflict/order_vendor_suspension_outranks_vendor_quantity_cap
        """
        world = _line_ready_to_buy_from(api, "ACTIVE")
        parts_line_id = world["parts_line"]["id"]

        response = api.order_parts_line(
            parts_line_id, f.order_payload(_LATE_ETA), PARTS_MANAGER_HEADERS
        )
        validate_error(response, ApiErrorId.VENDOR_QTY_CAP_EXCEEDED.value, 422)

        untouched = fx.read_parts_line(api, parts_line_id)
        A.assert_parts_line_state(untouched, procurement_status="PRICE_LOCKED")
        A.assert_null(untouched["vendor_order_seq"], "vendor_order_seq")
        A.assert_count(
            fx.read_vendor(api, world["vendor_id"])["order_seq_counter"],
            C.DEFAULT_ORDER_SEQ_COUNTER,
            "order_seq_counter",
        )


class TestANewlyRegisteredSupplierHasNoTradingRecordYet:
    """An empty window reads fifty, and the first delivery replaces it outright."""

    def test_a_brand_new_supplier_reads_fifty_until_its_first_delivery_lands(self, api):
        """A supplier with no deliveries carries the default fifty on both windows.

        PRD: "`fulfillment_score_rolling` and `fulfillment_score_lifetime` both start at 50 and are the two variants of the supplier's performance score described in §3.6."
        PRD: "If the window is empty the score is 50, the value a newly registered supplier starts with."
        Design: Corner/calculations/a_brand_new_vendor_carries_the_default_score_until_its_first_receipt
        """
        fx.set_clock(api, C.CLOCK_DEFAULT)
        vendor = fx.create_vendor(
            api,
            name="Northgate Honda",
            vendor_type="OEM_DEALER",
            part_types_offered=["OEM"],
            max_qty_per_line=5,
        )
        A.assert_scores(
            vendor, rolling=C.VENDOR_SCORE_DEFAULT, lifetime=C.VENDOR_SCORE_DEFAULT
        )
        A.assert_count(
            vendor["order_seq_counter"],
            C.DEFAULT_ORDER_SEQ_COUNTER,
            "order_seq_counter",
        )

        world = fx.locked_world(
            api, order_overrides={"deductible_cents": _DEDUCTIBLE_CENTS}
        )
        line = fx.add_parts_line(
            api,
            world["lines"][0]["id"],
            part_type="OEM",
            list_price_cents=30000,
            qty=1,
            vendor_id=vendor["id"],
        )
        fx.quote_part(api, line["id"], vendor["id"], 20000)
        fx.accept_price(api, line["id"])
        ordered = fx.place_parts_order(api, line["id"], _EARLY_ETA)
        A.assert_count(ordered["vendor_order_seq"], 1, "vendor_order_seq")

        # Still no closed outcome: the part has been bought but not delivered.
        A.assert_scores(
            fx.read_vendor(api, vendor["id"]),
            rolling=C.VENDOR_SCORE_DEFAULT,
            lifetime=C.VENDOR_SCORE_DEFAULT,
        )

        received = fx.receive_part(api, line["id"], 1, "CORRECT")
        A.assert_instant(received["received_at"], C.CLOCK_DEFAULT, "received_at")
        assert received["on_time"] is True
        A.assert_count(received["received_qty"], 1, "received_qty")
        A.assert_count(received["returned_qty"], 0, "returned_qty")
        A.assert_count(received["quote_round"], 1, "quote_round")

        scored = fx.read_vendor(api, vendor["id"])
        A.assert_scores(scored, rolling=100, lifetime=100)
        A.assert_count(scored["order_seq_counter"], 1, "order_seq_counter")
