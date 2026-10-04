"""Corner queue — calculations section: premium constants, storage accrual
day-count, board crush lock/offset math, routing determinism and empty pool,
carry month arithmetic, and the TRUCK per-date capacity boundary
(PRD §3.3/§3.4/§3.5/§3.7).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_board_crush_position,
    assert_carry_assessment,
    assert_delivery_ticket,
    apply_ticket,
    book_shipment,
    confirm_board_position,
    create_and_apply_ticket,
    create_barge_lane,
    create_cash_contract,
    create_crush_plant,
    create_deferred_contract,
    create_rail_lane,
    create_routing_quote_payload,
    create_shipment_payload,
    create_ticket,
    create_truck_lane,
    elect_price,
    enter_board_position,
    offset_board_position,
    post_bean_quote,
    post_crush_quote_set,
    read_contract,
    set_clock,
    setup_elevator_with_stored_bushels,
    setup_origination_site,
    setup_site,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MERCH = TEST_USERS["origination_merchandiser_headers"]
TRADER = TEST_USERS["crush_trader_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


class TestCertifiedPremium:
    def test_certified_ticket_carries_program_premium(self, api):
        """PRD §3.3: "The `premium_cents_per_bushel` is the program's `premium_cents_per_bushel` when the contract carries a `program_id`, and zero for conventional bushels" and a storage position is created with
        "the ticket's `program_id` (a non-null program marks a certified lot that only certified shipments may draw)". PRD §2.10:
        "certified_stored_bushels` is the same sum restricted to positions enrolled in a sustainability program".

        Design: Corner/calculations/certified_ticket_carries_program_premium
        """
        site = setup_origination_site(with_program=True)
        program = site["program"]
        contract = create_cash_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=3000, program_id=program["id"],
        )
        ticket = create_ticket(contract["id"], gross_bushels=3000)
        applied = apply_ticket(ticket["id"])
        assert_delivery_ticket(applied)
        assert applied["premium_cents_per_bushel"] == 25
        assert applied["discount_cents_per_bushel"] == 0

        positions, meta = validate_paginated(
            api_client.list_storage_positions(
                MERCH, params={"elevator_id": site["elevator"]["id"],
                               "program_id": program["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert positions[0]["program_id"] == program["id"]
        assert float(positions[0]["current_bushels"]) == pytest.approx(3000)

        elevator = validate_success(
            api_client.get_elevator(site["elevator"]["id"], MERCH)
        )
        assert float(elevator["certified_stored_bushels"]) == pytest.approx(3000)
        assert float(elevator["stored_bushels"]) == pytest.approx(3000)


class TestDeferredStorageAccrual:
    def test_dp_accrual_day_count_exact(self, api):
        """PRD §3.4: "Whenever a pricing event — client or forced — prices bushels out of the unpriced pool, the pending leg is finalized first: `accrued_storage_cents` grows by `storage_rate_cents_per_bushel_day` multiplied by the pool's `unpriced_pool_bushels` multiplied by the whole days from `last_accrual_date` to the event." 500 bu at 3 cents from
        2026-09-01 to the 2026-09-06 election accrue 3 x 500 x 5 = 7500; the
        emptied pool clears the anchor.

        Design: Corner/calculations/dp_accrual_day_count_exact
        """
        site = setup_origination_site()
        post_bean_quote("2026-12", 1100, "2026-09-01T00:00:00Z")
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=500, futures_month="2026-12",
            pricing_deadline="2026-12-15T00:00:00Z",
            storage_rate_cents_per_bushel_day=3,
        )
        create_and_apply_ticket(contract["id"], gross_bushels=500)
        set_clock("2026-09-06T00:00:00Z")
        elect_price(contract["id"], 500)
        refreshed = read_contract(contract["id"])
        assert refreshed["accrued_storage_cents"] == 7500
        assert refreshed["pricing_status"] == "PRICED"
        assert float(refreshed["unpriced_pool_bushels"]) == pytest.approx(0)
        assert refreshed["last_accrual_date"] is None
        assert refreshed["priced_value_cents"] == 550000


class TestBoardCrushMath:
    def test_hedge_locks_spread_and_margin_with_constants(self, api):
        """PRD §3.7: "locked_spread_cents_per_bushel` is the same crush-spread construction as §3.6 — the oil quote times eleven, plus the meal quote times forty-seven, minus the bean quote, rounded half up to two decimals — and `locked_margin_cents` is that spread multiplied by `bean_lots_long` multiplied by five thousand bushels per bean futures contract, rounded half up to whole cents." Quotes 1200/55/17 lock
        204.00 and 204.00 x 2 x 5000 = 2040000; the entering trader's id is
        recorded.

        Design: Corner/calculations/hedge_locks_spread_and_margin_with_constants
        """
        post_crush_quote_set("2026-11", bean=1200, oil=55, meal=17,
                             quote_date="2026-09-01T00:00:00Z")
        position = enter_board_position(trader_user_id="trader-77")
        assert_board_crush_position(position)
        assert float(position["locked_spread_cents_per_bushel"]) == pytest.approx(204.0)
        assert position["locked_margin_cents"] == 2040000
        assert position["status"] == "ENTERED"
        assert position["entered_by_user_id"] == "trader-77"

    def test_hedge_offset_realizes_pnl_from_spread_move(self, api):
        """PRD §3.7: "The current spread is recomputed with the same formula used at entry, and `realized_pnl_cents` is the spread's move — the current spread minus `locked_spread_cents_per_bushel` — multiplied by `bean_lots_long` multiplied by five thousand, rounded half up to whole cents". Bean 1200 -> 1150 lifts the spread 204.00 -> 254.00, so the
        offset realizes (254 - 204) x 2 x 5000 = 500000.

        Design: Corner/calculations/hedge_offset_realizes_pnl_from_spread_move
        """
        post_crush_quote_set("2026-11", bean=1200, oil=55, meal=17,
                             quote_date="2026-09-01T00:00:00Z")
        position = enter_board_position(trader_user_id="trader-77")
        confirm_board_position(position["id"], "rm-1")
        set_clock("2026-09-05T00:00:00Z")
        post_bean_quote("2026-11", 1150, "2026-09-05T00:00:00Z")
        offset = offset_board_position(position["id"], "trader-77")
        assert offset["status"] == "OFFSET"
        assert offset["realized_pnl_cents"] == 500000
        assert offset["confirmed_by_user_id"] == "rm-1"
        assert offset["entered_by_user_id"] == "trader-77"


class TestRoutingQuotes:
    def test_routing_quote_ranks_by_freight_transit_created(self, api):
        """PRD §3.5: "Eligible lanes rank by `freight_cents_per_bushel` ascending, then `transit_days` ascending, then the lane's `created_at` ascending; no random factor participates and identifiers never break ties" and the candidate set is "every lane from that origin whose destination plant is `ACTIVE". L2 and L3 (transit 1) precede L1
        (transit 3); L2 precedes L3 on creation order; the cheapest lane L4
        drops out entirely because its plant is MAINTENANCE.

        Design: Corner/calculations/routing_quote_ranks_by_freight_transit_created
        """
        site = setup_site()
        plant_a = create_crush_plant(name="Decatur")
        plant_b = create_crush_plant(name="Quincy")
        plant_m = create_crush_plant(name="Mothballed", status="MAINTENANCE")
        lane1 = create_truck_lane(site["elevator"]["id"], plant_a["id"],
                                  freight_cents_per_bushel=20, transit_days=3,
                                  daily_capacity_bushels=5000)
        lane2 = create_rail_lane(site["elevator"]["id"], plant_a["id"],
                                 freight_cents_per_bushel=20, transit_days=1,
                                 daily_capacity_bushels=5000)
        lane3 = create_barge_lane(site["elevator"]["id"], plant_b["id"],
                                  freight_cents_per_bushel=20, transit_days=1,
                                  daily_capacity_bushels=5000)
        lane4 = create_truck_lane(site["elevator"]["id"], plant_m["id"],
                                  freight_cents_per_bushel=1, transit_days=1,
                                  daily_capacity_bushels=5000)
        resp = api_client.create_shipment_routing_quote(
            create_routing_quote_payload(site["elevator"]["id"], 100), LOGISTICS
        )
        ranked = validate_success(resp, 200)
        assert [lane["id"] for lane in ranked] == [
            lane2["id"], lane3["id"], lane1["id"]
        ]
        assert lane4["id"] not in [lane["id"] for lane in ranked]

    def test_routing_quote_empty_pool_rejected(self, api):
        """PRD §3.5: "An empty candidate pool is rejected `ERR_NO_ROUTE_AVAILABLE`." An origin elevator with no lanes at all has
        no eligible lane.

        Design: Corner/calculations/routing_quote_empty_pool_rejected
        """
        site = setup_site()
        resp = api_client.create_shipment_routing_quote(
            create_routing_quote_payload(site["elevator"]["id"], 100), LOGISTICS
        )
        validate_error(resp, ApiErrorId.ERR_NO_ROUTE_AVAILABLE)


class TestCarryMonthArithmetic:
    def test_carry_months_between_computes_storage_cost(self, api):
        """PRD §3.3: "the assessment computes the month gap between the two —
        twelve times the year difference plus the month difference, which must
        be strictly positive or the request is `ERR_INVALID_REQUEST`" and
        "charges five cents per bushel per month of storage across the gap."
        2026-11 to 2027-03 spans 4 months: cost 20, signal 1225 - 1200 - 20 =
        5 -> CARRY.

        Design: Corner/calculations/carry_months_between_computes_storage_cost
        """
        site = setup_site()
        post_bean_quote("2026-11", 1200, "2026-09-01T00:00:00Z")
        post_bean_quote("2027-03", 1225, "2026-09-01T00:00:00Z")
        data = validate_success(
            api_client.get_carry_assessment(
                site["elevator"]["id"], TRADER,
                params={"nearby_month": "2026-11", "deferred_month": "2027-03"},
            )
        )
        assert_carry_assessment(data)
        assert data["storage_cost_cents_per_bushel"] == 20
        assert data["signal_cents_per_bushel"] == 5
        assert data["decision"] == "CARRY"
        assert data["nearby_price_cents"] == 1200
        assert data["deferred_price_cents"] == 1225


class TestTruckLaneDailyCapacity:
    def test_truck_lane_daily_capacity_exact_then_rejected(self, api):
        """PRD §3.5: "for truck and rail, the sum over the lane's non-cancelled shipments sharing the departure date, plus the new booking, must not exceed `daily_capacity_bushels` (`ERR_LANE_DAILY_CAPACITY_EXCEEDED`)". 600 + 400 == 1000 exactly fills
        the date and books; one more bushel that date fails; the same lane on
        the next date is unaffected.

        Design: Corner/calculations/truck_lane_daily_capacity_exact_then_rejected
        """
        base = setup_elevator_with_stored_bushels(2000)
        plant = create_crush_plant()
        lane = create_truck_lane(
            base["site"]["elevator"]["id"], plant["id"],
            freight_cents_per_bushel=12, transit_days=2,
            daily_capacity_bushels=1000,
        )
        ship1 = book_shipment(lane["id"], 600,
                              departure_date="2026-09-10T00:00:00Z")
        ship2 = book_shipment(lane["id"], 400,
                              departure_date="2026-09-10T00:00:00Z")
        assert ship1["status"] == "BOOKED" and ship2["status"] == "BOOKED"
        resp = api_client.create_shipment(
            create_shipment_payload(lane["id"], 1,
                                    departure_date="2026-09-10T00:00:00Z"),
            LOGISTICS,
        )
        validate_error(resp, ApiErrorId.ERR_LANE_DAILY_CAPACITY_EXCEEDED)
        ship4 = book_shipment(lane["id"], 1,
                              departure_date="2026-09-11T00:00:00Z")
        assert ship4["status"] == "BOOKED", (
            "capacity is a per-departure-date aggregate, not cumulative"
        )
