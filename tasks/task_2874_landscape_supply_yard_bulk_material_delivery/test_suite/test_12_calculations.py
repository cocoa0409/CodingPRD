"""Derived figures probed at their tier edges, their rounding points and their caps."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    CENTS,
    assert_charge_assembly,
    assert_claim_waterfall_sums,
    assert_credit_position,
    assert_inventory_lot,
    assert_order_line,
    assert_queue_positions,
)
from test_helpers.factories import stage_next_payload
from test_helpers.fixtures import (
    decide_claim,
    deliver_load,
    invoice_order,
    read_account,
    read_claim,
    read_line,
    read_lot,
    read_material,
    read_order,
    read_ticket,
    seed_account,
    seed_catalogue,
    seed_claim,
    seed_confirmed_delivery_context,
    seed_dispatched_load,
    seed_fulfilled_delivery_order,
    seed_inventory_lot,
    seed_material,
    seed_prebuy,
    seed_will_call_order,
    seed_will_call_ticket,
    stage_next_ticket,
)
from test_helpers.test_users import make_contractor_headers, make_yard_loader_headers

FLAT_PRICE = {
    "effective_from": "2026-07-01T00:00:00.000Z",
    "bulk_price_per_cubic_yard_cents": 2000,
    "bagged_price_per_bag_cents": 899,
    "seasonal_surcharge_pct": 0.0,
}
STANDARD_LOT = {"gross_cubic_yards": 100.0, "moisture_pct_at_intake": 15.0}
BIG_LOT = {"gross_cubic_yards": 200.0, "moisture_pct_at_intake": 15.0}
AGGREGATE_PROFILE = {
    "offered_forms": ["BULK"],
    "seasonal_category": "AGGREGATE",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
QUEUE_SALT = {
    "sku": "SALT-C1",
    "name": "Queue Salt",
    "offered_forms": ["BULK"],
    "seasonal_category": "SALT",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": True,
}
PLAIN_PICKUP_AT = "2026-07-31T06:00:00.000Z"
PREBUY_PICKUP_AT = "2026-07-31T08:00:00.000Z"


def _queue_priority_landscapes(api):
    """Two queued tickets: the earlier request is plain, the later one draws a season contract."""
    catalogue = seed_catalogue(api, material=QUEUE_SALT, price=FLAT_PRICE, lot=BIG_LOT)
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api, business_name="Queue Priority Landscapes", credit_limit_cents=5000000
    )
    prebuy = seed_prebuy(
        api, account, material_id, 1800, 50.0, "2026-06-01", "2026-12-31"
    )
    plain = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 4.0),), confirm=True
    )
    prebuy_order = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 4.0, True),), confirm=True
    )
    ticket_plain = seed_will_call_ticket(
        api, plain["order"]["id"], account["id"], PLAIN_PICKUP_AT
    )
    ticket_prebuy = seed_will_call_ticket(
        api, prebuy_order["order"]["id"], account["id"], PREBUY_PICKUP_AT
    )
    return {
        "account": account,
        "prebuy": prebuy,
        "order_plain": plain["order"],
        "order_prebuy": prebuy_order["order"],
        "ticket_plain": ticket_plain,
        "ticket_prebuy": ticket_prebuy,
    }


class TestWillCallQueueRanking:
    """Rank keys applied in order: priority first, requested instant second, creation last."""

    def test_a_season_contract_outranks_a_ticket_requested_two_hours_earlier(self, api):
        """Priority class is the first sort key, so the later request is staged first.

        PRD 3.6: "A ticket's `priority_class` is 2 when its order has at least one line
        carrying a `prebuy_contract_id`, and 1 otherwise -- a contractor who paid for the
        season up front gets served ahead of a walk-up."

        PRD 3.6: "A ticket's `queue_position` is its 1-based rank among **all** tickets in
        the yard whose `status` is `QUEUED`, sorted by `priority_class` descending, then by
        `requested_pickup_at` ascending, then by `created_at` ascending as the final
        discriminator; a record's `id` is never consulted as a tie-break."

        PRD 3.4: "Where the line carries a `prebuy_contract_id`, the bulk unit basis is
        instead the contract's `locked_price_per_cubic_yard_cents` and the seasonal
        surcharge is treated as zero, because a locked season price is immune both to later
        price rows and to seasonal uplift."

        Design: Corner/calculations/queue_ranking_puts_prebuy_priority_ahead_of_the_earlier_request
        """
        context = _queue_priority_landscapes(api)

        before_plain = read_ticket(api, context["ticket_plain"]["id"])
        before_prebuy = read_ticket(api, context["ticket_prebuy"]["id"])
        assert before_prebuy["priority_class"] == 2
        assert before_plain["priority_class"] == 1
        assert_queue_positions(
            [before_plain, before_prebuy],
            {context["ticket_prebuy"]["id"]: 1, context["ticket_plain"]["id"]: 2},
        )

        # 4.0 * 1800 locked against 4.0 * 2000 list, and a WILL_CALL order pays no fees
        assert read_order(api, context["order_prebuy"]["id"])["quoted_total_cents"] == 7200
        assert read_order(api, context["order_plain"]["id"])["quoted_total_cents"] == 8000

        staged = stage_next_ticket(
            api, "2026-08-01T09:00:00.000Z", "2026-08-01T10:00:00.000Z", "loader-c1"
        )
        assert staged["id"] == context["ticket_prebuy"]["id"]
        assert staged["status"] == "STAGED"
        assert staged["queue_position"] is None

        # the survivor closes up the gap the staged ticket left behind
        assert read_ticket(api, context["ticket_plain"]["id"])["queue_position"] == 1
        assert (
            read_order(api, context["order_prebuy"]["id"])["fulfillment_status"] == "ALLOCATED"
        )
        assert read_order(api, context["order_plain"]["id"])["fulfillment_status"] == "CONFIRMED"


TIEBREAK_STONE = dict(AGGREGATE_PROFILE, sku="AGG-C2", name="Tiebreak Stone")
SHARED_PICKUP_AT = "2026-07-31T12:00:00.000Z"
FUTURE_PICKUP_AT = "2026-08-02T06:00:00.000Z"


def _tiebreak_grounds(api):
    """Three queued tickets, two tied on the requested instant and one dated past the clock."""
    catalogue = seed_catalogue(api, material=TIEBREAK_STONE, price=FLAT_PRICE, lot=BIG_LOT)
    material_id = catalogue["material"]["id"]
    account = seed_account(api, business_name="Tiebreak Grounds", credit_limit_cents=9000000)
    orders = [
        seed_will_call_order(
            api, account, material_id, lines=(("BULK", 4.0),), confirm=True
        )["order"]
        for _ in range(3)
    ]
    first = seed_will_call_ticket(api, orders[0]["id"], account["id"], SHARED_PICKUP_AT)
    second = seed_will_call_ticket(api, orders[1]["id"], account["id"], SHARED_PICKUP_AT)
    future = seed_will_call_ticket(api, orders[2]["id"], account["id"], FUTURE_PICKUP_AT)
    return {
        "account": account,
        "orders": orders,
        "first": first,
        "second": second,
        "future": future,
    }


class TestWillCallQueueTiebreakAndEligibility:
    """A tie falls to creation order, and a future request is ranked but never staged."""

    def test_creation_order_breaks_the_tie_and_the_future_request_empties_the_queue(self, api):
        """Two identical instants, then a third staging attempt with no candidate left.

        PRD 3.6: "Candidates are sorted by the same three keys that produce `queue_position`
        -- `priority_class` descending, `requested_pickup_at` ascending, `created_at`
        ascending -- and the first row of that sorted list is the ticket staged."

        PRD 3.6: "Eligibility is an explicit predicate -- a ticket is a candidate when its
        own `status` is `QUEUED`, **and** its order's `fulfillment_status` is `CONFIRMED` or
        `ALLOCATED`, **and** that order's account has `account_status` `ACTIVE`, **and** its
        `requested_pickup_at` is at or before the current logical clock."

        PRD 3.6: "When the candidate set is empty, nothing is staged and the request is
        refused with `ERR_WILL_CALL_QUEUE_EMPTY`."

        Design: Corner/calculations/queue_ranking_tiebreaks_on_created_at_and_skips_future_requests
        """
        context = _tiebreak_grounds(api)

        assert_queue_positions(
            [
                read_ticket(api, context["first"]["id"]),
                read_ticket(api, context["second"]["id"]),
                read_ticket(api, context["future"]["id"]),
            ],
            {
                context["first"]["id"]: 1,
                context["second"]["id"]: 2,
                context["future"]["id"]: 3,
            },
        )

        staged_first = stage_next_ticket(
            api, "2026-08-01T09:00:00.000Z", "2026-08-01T10:00:00.000Z", "loader-c2"
        )
        assert staged_first["id"] == context["first"]["id"]

        # a second bay is still free for a window that overlaps the first
        staged_second = stage_next_ticket(
            api, "2026-08-01T09:30:00.000Z", "2026-08-01T10:30:00.000Z", "loader-c2"
        )
        assert staged_second["id"] == context["second"]["id"]

        # the afternoon window overlaps neither bay, so capacity cannot be the reason
        refused = api.stage_next_will_call_ticket(
            stage_next_payload("2026-08-01T14:00:00.000Z", "2026-08-01T15:00:00.000Z"),
            headers=make_yard_loader_headers("loader-c2"),
        )
        validate_error(refused, ApiErrorId.WILL_CALL_QUEUE_EMPTY.value, 409)

        leftover = read_ticket(api, context["future"]["id"])
        assert leftover["status"] == "QUEUED"
        # still ranked, because queue_position counts ineligible tickets too
        assert leftover["queue_position"] == 1


FILTER_STONE = dict(AGGREGATE_PROFILE, sku="AGG-C3", name="Filter Stone")


def _input_set_landscapes(api):
    """Three orders on one account: one left in draft, one live, one confirmed then cancelled."""
    catalogue = seed_catalogue(api, material=FILTER_STONE, price=FLAT_PRICE, lot=STANDARD_LOT)
    material_id = catalogue["material"]["id"]
    account = seed_account(
        api, business_name="Input Set Landscapes", credit_limit_cents=5000000
    )
    draft = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 5.0),), confirm=False
    )
    live = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 6.25),), confirm=True
    )
    gone = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 7.5),), confirm=True
    )
    return {
        "account": account,
        "lot": catalogue["lot"],
        "draft": draft["order"],
        "live": live["order"],
        "gone": gone["order"],
    }


class TestAccountCreditPositionInputSet:
    """The roll-up's input set, not its arithmetic, is what this exercises."""

    def test_only_the_live_confirmed_order_consumes_the_line(self, api):
        """A draft never books credit and a cancellation gives it all back.

        PRD 3.3: "`credit_used_cents` is the sum, over the account's orders whose
        `fulfillment_status` is `CONFIRMED`, `ALLOCATED` or `FULFILLED` **and** whose
        `settlement_status` is `UNBILLED`, `INVOICED` or `CREDIT_MEMO_ISSUED`, of that order's
        final total where one exists and its quoted total otherwise, minus that order's
        `credit_memo_cents`."

        PRD 3.3: "Orders still in `DRAFT` and orders that were `CANCELLED` never consume
        credit, and an order whose `settlement_status` has reached `SETTLED` releases the
        credit it was consuming."

        PRD 3.4: "A new order begins with `fulfillment_status` `DRAFT` and
        `settlement_status` `UNBILLED`, with every money field at 0, with `final_total_cents`
        and `quote_locked_at` null, and with `paid_amount_cents` and `credit_memo_cents` at
        0."

        Design: Corner/calculations/credit_position_counts_only_confirmed_and_live_orders
        """
        context = _input_set_landscapes(api)
        account_id = context["account"]["id"]

        # 12500 + 15000; the 5.0-cubic-yard draft is already outside the input set
        assert read_account(api, account_id)["credit_used_cents"] == 27500

        cancelled = validate_success(
            api.cancel_material_order(
                context["gone"]["id"], headers=make_contractor_headers(account_id)
            ),
            200,
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"
        # the quote survives the cancellation; it simply stops being counted
        assert cancelled["quoted_total_cents"] == 15000

        assert_credit_position(read_account(api, account_id), 12500, 4987500)
        assert read_account(api, account_id)["account_status"] == "ACTIVE"

        draft = read_order(api, context["draft"]["id"])
        assert draft["fulfillment_status"] == "DRAFT"
        assert draft["quoted_total_cents"] == 0
        assert draft["final_total_cents"] is None

        # only the live order's 6.25 cubic yards is still held out of the pile
        assert read_lot(api, context["lot"]["id"])["reserved_cubic_yards"] == pytest.approx(
            6.25, abs=CENTS
        )


TIER_STONE = dict(AGGREGATE_PROFILE, sku="AGG-C4", name="Tier Stone")


def _tier_landscapes(api):
    """Two will-call orders straddling the three-percent discount boundary."""
    catalogue = seed_catalogue(api, material=TIER_STONE, price=FLAT_PRICE, lot=BIG_LOT)
    material_id = catalogue["material"]["id"]
    account = seed_account(api, business_name="Tier Landscapes", credit_limit_cents=5000000)
    at_boundary = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 50.0),), confirm=False
    )
    below_boundary = seed_will_call_order(
        api, account, material_id, lines=(("BULK", 49.99),), confirm=False
    )
    return {
        "account": account,
        "at_boundary": at_boundary["order"],
        "below_boundary": below_boundary["order"],
    }


class TestVolumeDiscountTierBoundary:
    """The middle tier's lower bound is inclusive, and the rate is an average one."""

    def test_a_hundred_dollar_subtotal_earns_three_percent_and_a_cent_less_earns_nothing(
        self, api
    ):
        """The smaller order ends up costing more than the larger one.

        PRD 3.4: "Step three selects `volume_discount_pct` from the yard's volume tiers by
        looking up `bulk_subtotal_cents` -- the pre-discount figure -- where each tier's
        lower bound is inclusive and its upper bound exclusive: bulk business below one
        thousand dollars earns 0.0 percent, bulk business from one thousand dollars up to but
        not including two thousand five hundred dollars earns 3.0 percent, and bulk business
        of two thousand five hundred dollars or more earns 6.0 percent."

        PRD 3.4: "Step four sets `volume_discount_cents` to `bulk_subtotal_cents` multiplied
        by `volume_discount_pct` divided by one hundred, rounded half up to whole cents."

        PRD 3.4: "Step six sets `min_load_fee_cents` to the yard's seventy-five-dollar
        minimum-load fee when all three of the following hold -- the order's
        `fulfillment_mode` is `DELIVERY`, `bulk_subtotal_cents` is greater than zero, and the
        discounted bulk figure from step five is **below** the yard's
        two-hundred-and-fifty-dollar minimum-load threshold -- and to 0 otherwise; a
        `WILL_CALL` order is always exempt from this fee."

        Design: Corner/calculations/volume_discount_tier_boundary_at_one_hundred_thousand_cents
        """
        context = _tier_landscapes(api)
        account_id = context["account"]["id"]
        headers = make_contractor_headers(account_id)

        at_boundary = validate_success(
            api.confirm_material_order(context["at_boundary"]["id"], headers=headers), 200
        )
        below_boundary = validate_success(
            api.confirm_material_order(context["below_boundary"]["id"], headers=headers), 200
        )

        # 50.00 * 2000 lands exactly on the tier's inclusive lower bound
        assert at_boundary["bulk_subtotal_cents"] == 100000
        assert at_boundary["volume_discount_pct"] == pytest.approx(3.0)
        assert at_boundary["volume_discount_cents"] == 3000
        assert at_boundary["quoted_total_cents"] == 97000
        assert_charge_assembly(at_boundary, 97000)

        # 49.99 * 2000 is twenty cents short of the boundary and earns nothing
        assert below_boundary["bulk_subtotal_cents"] == 99980
        assert below_boundary["volume_discount_pct"] == pytest.approx(0.0)
        assert below_boundary["volume_discount_cents"] == 0
        assert below_boundary["quoted_total_cents"] == 99980
        assert_charge_assembly(below_boundary, 99980)

        # the cheaper order costs more than the dearer one
        assert below_boundary["quoted_total_cents"] > at_boundary["quoted_total_cents"]

        for order in (at_boundary, below_boundary):
            assert order["min_load_fee_cents"] == 0
            assert order["delivery_fee_cents"] == 0

        assert read_account(api, account_id)["credit_used_cents"] == 196980


PRECISION_MULCH = {
    "sku": "MULCH-C5",
    "name": "Precision Mulch",
    "offered_forms": ["BULK", "BAGGED"],
    "seasonal_category": "MULCH",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}
SURCHARGED_PRICE = dict(FLAT_PRICE, seasonal_surcharge_pct=5.0)
SMALL_LOT = {"gross_cubic_yards": 10.0, "moisture_pct_at_intake": 15.0}


def _precision_landscapes(api):
    """A single twenty-seven-bag line on a surcharged price row."""
    catalogue = seed_catalogue(
        api, material=PRECISION_MULCH, price=SURCHARGED_PRICE, lot=SMALL_LOT
    )
    account = seed_account(
        api, business_name="Precision Landscapes", credit_limit_cents=5000000
    )
    built = seed_will_call_order(
        api,
        account,
        catalogue["material"]["id"],
        lines=(("BAGGED", 27),),
        confirm=False,
    )
    return {"account": account, "order": built["order"], "line": built["lines"][0]}


class TestBaggedLinePrecision:
    """Bag volume rounds, bag money does not."""

    def test_twenty_seven_bags_round_up_to_a_whole_cubic_yard_and_take_no_surcharge(self, api):
        """0.999 has to become 1.00, and 899 times 27 has to stay exact.

        PRD 3.4: "Line creation immediately computes `line_volume_cubic_yards` -- for a bulk
        line it is simply the `quantity`, and for a bagged line it is the `quantity`
        multiplied by the material's `unit_bag_cubic_yards`, rounded half up to two decimal
        places -- because that figure is what the yard will later reserve out of a stockpile."

        PRD 3.4: "For a bagged line, `unit_price_cents` is simply the in-force row's
        `bagged_price_per_bag_cents` with no surcharge of any kind, and `line_price_cents` is
        that unit price multiplied by the whole bag count, which is exact and needs no
        rounding."

        PRD 3.4: "Step two sets `bagged_subtotal_cents` to the same sum across its bagged
        lines."

        Design: Corner/calculations/bagged_line_volume_rounds_half_up_to_two_decimals
        """
        context = _precision_landscapes(api)

        drafted = context["line"]
        assert_order_line(drafted)
        # 27 * 0.037 is exactly 0.999, which rounds up rather than truncating to 0.99
        assert drafted["line_volume_cubic_yards"] == pytest.approx(1.00, abs=CENTS)
        assert drafted["line_price_cents"] is None

        confirmed = validate_success(
            api.confirm_material_order(
                context["order"]["id"],
                headers=make_contractor_headers(context["account"]["id"]),
            ),
            200,
        )

        priced = read_line(api, drafted["id"])
        assert priced["line_volume_cubic_yards"] == pytest.approx(1.00, abs=CENTS)
        # the five-percent seasonal uplift on the row never touches a bag
        assert priced["unit_price_cents"] == 899
        assert priced["line_price_cents"] == 24273

        assert confirmed["bagged_subtotal_cents"] == 24273
        assert confirmed["bulk_subtotal_cents"] == 0
        assert confirmed["volume_discount_cents"] == 0
        assert confirmed["min_load_fee_cents"] == 0
        assert confirmed["quoted_total_cents"] == 24273
        assert_charge_assembly(confirmed, 24273)


WATERFALL_STONE = dict(AGGREGATE_PROFILE, sku="AGG-C6", name="Waterfall Stone")
WATERFALL_TRUCK = {
    "truck_code": "TND-C6",
    "axle_class": "TANDEM",
    "max_payload_lb": 40000,
    "bed_capacity_cubic_yards": 12.0,
    "min_driveway_access_class": "CLASS_B",
}


def _waterfall_grounds(api):
    """A CLASS_B order of 6.0 then 4.0 cubic yards with a dispatched ten-yard load."""
    context = seed_confirmed_delivery_context(
        api,
        material=WATERFALL_STONE,
        price=FLAT_PRICE,
        lot=STANDARD_LOT,
        account={"business_name": "Waterfall Grounds", "credit_limit_cents": 5000000},
        lines=(("BULK", 6.0), ("BULK", 4.0)),
        driveway_access_class="CLASS_B",
        delivery_distance_miles=10.0,
        truck=WATERFALL_TRUCK,
    )
    context["load"] = seed_dispatched_load(
        api,
        context["order"]["id"],
        context["truck"]["id"],
        10.0,
        "2026-08-02T08:00:00.000Z",
        "2026-08-02T09:00:00.000Z",
        "planner-c6",
    )
    return context


class TestDeliveredVolumeWaterfall:
    """A short delivery fills the oldest line whole before the newest sees a yard of it."""

    def test_seven_yards_against_six_and_four_fills_the_first_line_completely(self, api):
        """No pro-rata split: the earlier line takes 6.0 and the later one takes the 1.0 left.

        PRD 3.5: "In the same hop the delivered volume is distributed across the order's bulk
        lines by a **waterfall in `created_at` ascending order**: working through the bulk
        lines from oldest to newest, each line takes the lesser of the volume still to be
        distributed and its own shortfall -- its `line_volume_cubic_yards` minus its
        `delivered_volume_cubic_yards` -- that amount is added to the line's
        `delivered_volume_cubic_yards`, and the remainder to distribute is reduced
        accordingly; if any volume is still left over after the newest bulk line has been
        filled, the whole leftover is added to that last line's
        `delivered_volume_cubic_yards`."

        PRD 3.5: "The final basis differs from the confirm basis in three respects: the price
        row consulted is the one in force at the **dispatch instant** of the delivering load
        rather than at `quote_locked_at`; the billable quantity for a bulk line is its
        `delivered_volume_cubic_yards` rather than its ordered `quantity`; and the axle base
        in the delivery-fee step is the **actual delivering truck's** `axle_class` rather than
        the largest class the driveway admits."

        PRD 3.5: "When every bulk line's `delivered_volume_cubic_yards` has reached its
        `line_volume_cubic_yards`, the order transitions `ALLOCATED -> FULFILLED`."

        Design: Corner/calculations/delivered_volume_waterfall_fills_the_first_line_before_the_second
        """
        context = _waterfall_grounds(api)
        first, second = context["lines"][0], context["lines"][1]

        quoted = read_order(api, context["order"]["id"])
        # 20000 bulk + 7500 minimum load + TANDEM 9500 + 10 miles at 425
        assert quoted["quoted_total_cents"] == 41250
        assert_charge_assembly(quoted, 41250)

        delivered = deliver_load(
            api,
            context["load"]["id"],
            7.0,
            driveway_protection_used=False,
            spillage_cubic_yards=0.0,
            dispatcher_user_id="planner-c6",
        )
        assert delivered["status"] == "DELIVERED"

        filled = read_line(api, first["id"])
        assert filled["delivered_volume_cubic_yards"] == pytest.approx(6.0, abs=CENTS)
        assert filled["final_line_price_cents"] == 12000

        remainder = read_line(api, second["id"])
        # 1.0 of the 4.0 ordered, not the 2.8 a pro-rata split would have given it
        assert remainder["delivered_volume_cubic_yards"] == pytest.approx(1.0, abs=CENTS)
        assert remainder["final_line_price_cents"] == 2000

        order = read_order(api, context["order"]["id"])
        # 14000 delivered bulk + 7500 minimum load + 13750 on the actual TANDEM truck
        assert order["final_total_cents"] == 35250
        assert order["quoted_total_cents"] == 41250
        # the second line is still owed 3.0 cubic yards
        assert order["fulfillment_status"] == "ALLOCATED"
        assert order["settlement_status"] == "UNBILLED"

        lot = read_lot(api, context["lot"]["id"])
        assert lot["withdrawn_gross_cubic_yards"] == pytest.approx(7.0, abs=CENTS)
        assert lot["status"] == "AVAILABLE"

        # the final total displaces the quote in the credit roll-up
        assert read_account(api, context["account"]["id"])["credit_used_cents"] == 35250


CLAMP_SOIL = {
    "sku": "SOIL-C7",
    "name": "Clamp Soil",
    "offered_forms": ["BULK"],
    "seasonal_category": "SOIL",
    "density_lb_per_cubic_yard": 1000,
    "shrinkage_factor": 0.10,
    "moisture_pct": 15.0,
    "unit_bag_cubic_yards": 0.037,
    "prebuy_eligible": False,
}


class TestMoistureMultiplierClamp:
    """Both ends of the multiplier are pinned, and pinned before any volume is touched."""

    def test_a_soaked_pile_a_pile_on_the_floor_and_a_bone_dry_pile(self, api):
        """Forty percent and thirty-five percent become indistinguishable; ten percent earns no bonus.

        PRD 3.2: "To obtain the multiplier for a moisture percentage, subtract the yard's
        reference moisture of 15.0 percent from that percentage, divide the difference by 100,
        and subtract the result from 1."

        PRD 3.2: "The multiplier is then clamped into the inclusive range from 0.80 to 1.00 --
        a value below 0.80 is raised to 0.80 and a value above 1.00 is lowered to 1.00 -- and
        the clamp is applied to the multiplier **before** it is multiplied by any volume,
        never afterwards."

        PRD 3.2: "While `basis` is `INTAKE` -- meaning no moisture reading has been filed
        since the lot was scaled in -- `net_sellable_cubic_yards` is the `gross_cubic_yards`
        multiplied by one minus the full `shrinkage_factor` of the material, multiplied by the
        moisture multiplier taken from `moisture_pct_at_intake`, with the product rounded half
        up to two decimal places."

        Design: Corner/calculations/moisture_adjust_clamp_pins_both_ends_of_the_curve
        """
        material = seed_material(api, **CLAMP_SOIL)
        material_id = material["id"]

        soaked = seed_inventory_lot(
            api, material_id, gross_cubic_yards=50.0, moisture_pct_at_intake=40.0
        )
        on_the_floor = seed_inventory_lot(
            api, material_id, gross_cubic_yards=50.0, moisture_pct_at_intake=35.0
        )
        bone_dry = seed_inventory_lot(
            api, material_id, gross_cubic_yards=50.0, moisture_pct_at_intake=10.0
        )

        for lot in (soaked, on_the_floor, bone_dry):
            assert_inventory_lot(lot)
            assert lot["basis"] == "INTAKE"

        # 0.75 raised to the 0.80 floor, then 50.0 * 0.90 * 0.80
        assert soaked["net_sellable_cubic_yards"] == pytest.approx(36.00, abs=CENTS)
        # 0.80 exactly on the floor, so the two piles report the same volume
        assert on_the_floor["net_sellable_cubic_yards"] == pytest.approx(36.00, abs=CENTS)
        assert soaked["net_sellable_cubic_yards"] == pytest.approx(
            on_the_floor["net_sellable_cubic_yards"], abs=CENTS
        )
        # 1.05 lowered to the 1.00 ceiling, so 45.00 rather than 47.25
        assert bone_dry["net_sellable_cubic_yards"] == pytest.approx(45.00, abs=CENTS)

        assert read_material(api, material_id)[
            "available_net_cubic_yards"
        ] == pytest.approx(117.00, abs=CENTS)


SPILLAGE_STONE = dict(AGGREGATE_PROFILE, sku="AGG-C8", name="Spillage Stone")
SPILLAGE_TRUCK = {
    "truck_code": "TRI-C8",
    "axle_class": "TRI_AXLE",
    "max_payload_lb": 60000,
    "bed_capacity_cubic_yards": 25.0,
    "min_driveway_access_class": "CLASS_A",
}


def _spillage_landscapes(api):
    """A fulfilled and invoiced 20-yard delivery carrying a 55000-cent spillage claim."""
    context = seed_fulfilled_delivery_order(
        api,
        material=SPILLAGE_STONE,
        price=FLAT_PRICE,
        lot=STANDARD_LOT,
        account={"business_name": "Spillage Landscapes", "credit_limit_cents": 5000000},
        lines=(("BULK", 20.0),),
        driveway_access_class="CLASS_A",
        delivery_distance_miles=10.0,
        truck=SPILLAGE_TRUCK,
        window_start="2026-08-02T08:00:00.000Z",
        window_end="2026-08-02T10:00:00.000Z",
        driveway_protection_used=False,
        dispatcher_user_id="planner-c8",
    )
    invoice_order(api, context["order"]["id"])
    context["claim"] = seed_claim(
        api,
        context["order"]["id"],
        context["account"]["id"],
        "SPILLAGE",
        55000,
        delivery_load_id=context["load"]["id"],
        under_review=True,
        adjuster_user_id="adjuster-c8",
        description="Aggregate spilled across the sidewalk and gutter; street sweeper hired.",
    )
    return context


class TestSpillageClaimCleanupCap:
    """Stage one caps the approval; stage two pours the capped figure, not the approved one."""

    def test_a_fifty_five_thousand_cent_approval_pays_out_the_four_hundred_dollar_cap(self, api):
        """The cap bites first, and the outstanding invoice then swallows the whole payable.

        PRD 3.7: "For a `SPILLAGE` claim, `payable_cents` is the lesser of
        `approved_amount_cents` and the yard's four-hundred-dollar cleanup cap -- the
        contractor is never charged for the spilled material itself, only the cleanup is in
        scope."

        PRD 3.7: "Bucket one is the still-outstanding invoice, computed as the order's final
        total where one exists and its quoted total otherwise, minus its `credit_memo_cents`,
        minus its `paid_amount_cents`, floored at zero; `invoice_offset_cents` takes the lesser
        of the amount still to be allocated and that outstanding figure, and the amount still
        to be allocated is reduced by it."

        PRD 3.7: "Bucket three, `goodwill_credit_cents`, takes whatever is left, and it is
        never negative."

        Design: Corner/calculations/spillage_claim_payable_is_capped_at_the_cleanup_constant
        """
        context = _spillage_landscapes(api)

        order = read_order(api, context["order"]["id"])
        # 40000 bulk with no minimum-load fee, plus TRI_AXLE 13500 and 10 miles at 425
        assert order["final_total_cents"] == 57750
        assert order["settlement_status"] == "INVOICED"

        decided = decide_claim(
            api,
            context["claim"]["id"],
            "APPROVE",
            approved_amount_cents=55000,
            adjuster_user_id="adjuster-c8",
        )
        assert decided["status"] == "APPROVED"
        assert decided["approved_amount_cents"] == 55000
        assert decided["review_round"] == 1
        assert decided["decided_by_user_id"] == "adjuster-c8"

        # the cleanup cap, not the approved figure
        assert decided["payable_cents"] == 40000
        assert decided["invoice_offset_cents"] == 40000
        assert decided["deposit_offset_cents"] == 0
        assert decided["goodwill_credit_cents"] == 0
        assert_claim_waterfall_sums(decided)

        stored = read_claim(api, context["claim"]["id"])
        assert stored["payable_cents"] == 40000

        # nothing moves onto the order until the claim is settled
        after = read_order(api, context["order"]["id"])
        assert after["final_total_cents"] == 57750
        assert after["credit_memo_cents"] == 0
        assert after["settlement_status"] == "INVOICED"
