"""Corner queue — validations section: quantity caps, delivery windows,
quality specs, the feedstock quota, missing market quotes, plant inventory,
drawable bushels, certified chain of custody, and the barge interval freed by
cancellation (PRD §3.4/§3.5/§3.6/§3.8).
"""
import pytest

from test_helpers import (
    ENDPOINT_SUCCESS_STATUS,
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_product_sales_contract,
    book_shipment,
    cancel_shipment,
    create_barge_lane,
    create_crush_plant,
    create_deferred_contract,
    create_pricing_election_payload,
    create_sales_contract_payload,
    create_sales_delivery_payload,
    create_shipment_payload,
    create_truck_lane,
    elect_price,
    post_bean_quote,
    post_crush_quote_set,
    read_contract,
    read_crush_run,
    read_sales_contract,
    schedule_run,
    set_clock,
    setup_elevator_with_mixed_lots,
    setup_elevator_with_stored_bushels,
    setup_origination_site,
    setup_sales_scenario,
    create_crush_run,
    validate_error,
    validate_paginated,
    validate_success,
)

MERCH = TEST_USERS["origination_merchandiser_headers"]
SCHEDULER = TEST_USERS["plant_scheduler_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
PRODUCT_MERCH = TEST_USERS["product_merchandiser_headers"]


class TestPricingQuantityCap:
    def test_election_beyond_unpriced_rejected(self, api):
        """PRD §3.4: "The elected bushels must be positive and must not push `priced_bushels` past `quantity_bushels`, or the election is `ERR_PRICING_EXCEEDS_QUANTITY`." 800 priced of 2000; a further 1500
        fails 422 and priced_bushels stays 800.

        Design: Corner/validations/election_beyond_unpriced_rejected
        """
        site = setup_origination_site()
        post_bean_quote("2026-12", 1100, "2026-09-01T00:00:00Z")
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=2000, futures_month="2026-12",
            pricing_deadline="2026-12-15T00:00:00Z",
            storage_rate_cents_per_bushel_day=1,
        )
        elect_price(contract["id"], 800)
        current = read_contract(contract["id"])
        resp = api_client.create_pricing_election(
            contract["id"],
            create_pricing_election_payload(1500, current["version"]),
            MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_PRICING_EXCEEDS_QUANTITY)
        after = read_contract(contract["id"])
        assert float(after["priced_bushels"]) == pytest.approx(800)


class TestDeliveryWindow:
    def test_delivery_before_window_rejected(self, api):
        """PRD §3.8: "The date must fall inside the window, both ends inclusive (`ERR_DELIVERY_OUTSIDE_WINDOW`)". 2026-09-10 is outside
        [09-15, 09-30] and fails 422; a delivery exactly on 2026-09-15 is
        accepted and lands on delivered_lbs.

        Design: Corner/validations/delivery_before_window_rejected
        """
        base = setup_sales_scenario(
            product="SOY_OIL", quantity_lbs=1000, price_cents_per_lb=20,
            delivery_window_start="2026-09-15T00:00:00Z",
            delivery_window_end="2026-09-30T00:00:00Z", max_ffa_pct=0.5,
        )
        set_clock("2026-09-10T00:00:00Z")
        resp = api_client.deliver_product_sales_contract(
            base["contract"]["id"],
            create_sales_delivery_payload(
                "2026-09-10T00:00:00Z", 100, product="SOY_OIL",
                actual_ffa_pct=0.3,
            ),
            PRODUCT_MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_OUTSIDE_WINDOW)
        set_clock("2026-09-15T00:00:00Z")
        accepted = api_client.deliver_product_sales_contract(
            base["contract"]["id"],
            create_sales_delivery_payload(
                "2026-09-15T00:00:00Z", 100, product="SOY_OIL",
                actual_ffa_pct=0.3,
            ),
            PRODUCT_MERCH,
        )
        updated = validate_success(
            accepted, ENDPOINT_SUCCESS_STATUS["deliver_product_sales_contract"]
        )
        assert updated["delivered_lbs"] == 100
        assert updated["status"] == "DELIVERING"

    def test_sales_window_end_before_start_rejected(self, api):
        """PRD §3.8: "The window must be well-formed: the end must come after the start and the span must not exceed sixty-two days, otherwise `ERR_DELIVERY_WINDOW_INVALID`." End-before-start and a 121-day span both
        fail 422 at creation.

        Design: Corner/validations/sales_window_end_before_start_rejected
        """
        base = setup_sales_scenario(product="SOY_OIL")
        resp_inverted = api_client.create_product_sales_contract(
            create_sales_contract_payload(
                base["buyer"]["id"], base["plant"]["id"], product="SOY_OIL",
                quantity_lbs=1000, price_cents_per_lb=20,
                delivery_window_start="2026-09-15T00:00:00Z",
                delivery_window_end="2026-09-10T00:00:00Z", max_ffa_pct=0.5,
            ),
            PRODUCT_MERCH,
        )
        validate_error(resp_inverted, ApiErrorId.ERR_DELIVERY_WINDOW_INVALID)
        resp_long = api_client.create_product_sales_contract(
            create_sales_contract_payload(
                base["buyer"]["id"], base["plant"]["id"], product="SOY_OIL",
                quantity_lbs=1000, price_cents_per_lb=20,
                delivery_window_start="2026-09-01T00:00:00Z",
                delivery_window_end="2026-12-31T00:00:00Z", max_ffa_pct=0.5,
            ),
            PRODUCT_MERCH,
        )
        validate_error(resp_long, ApiErrorId.ERR_DELIVERY_WINDOW_INVALID)


class TestQualitySpec:
    def test_meal_delivery_below_protein_spec_rejected(self, api):
        """PRD §3.8: "the product's spec must hold — protein at least `min_protein_pct` for meal, free fatty acids at most `max_ffa_pct` for oil and feedstock (`ERR_QUALITY_SPEC_FAILED`)". Protein 45.5 against a 46.0
        minimum fails 422 and records nothing.

        Design: Corner/validations/meal_delivery_below_protein_spec_rejected
        """
        base = setup_sales_scenario(
            product="SOY_MEAL", quantity_lbs=2000, price_cents_per_lb=15,
            delivery_window_start="2026-09-10T00:00:00Z",
            delivery_window_end="2026-09-20T00:00:00Z", min_protein_pct=46.0,
        )
        set_clock("2026-09-12T00:00:00Z")
        resp = api_client.deliver_product_sales_contract(
            base["contract"]["id"],
            create_sales_delivery_payload(
                "2026-09-12T00:00:00Z", 500, product="SOY_MEAL",
                actual_protein_pct=45.5,
            ),
            PRODUCT_MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_QUALITY_SPEC_FAILED)
        contract = read_sales_contract(base["contract"]["id"])
        assert_product_sales_contract(contract)
        assert contract["delivered_lbs"] == 0
        assert contract["deliveries"] == []
        assert contract["status"] == "OPEN"


class TestFeedstockQuota:
    def test_biodiesel_feedstock_quota_enforced(self, api):
        """PRD §3.8: "the sum of `quantity_lbs` over every feedstock contract at that plant that has not defaulted, plus the new contract's quantity, must not exceed the plant's `daily_refinery_capacity_lbs` multiplied by its `biodiesel_feedstock_share_pct` divided by one hundred, multiplied across a thirty-day horizon — a breach is `ERR_FEEDSTOCK_QUOTA_EXCEEDED`." 1000000 x 10% x 30 = 3000000; 2000000
        books, and a further 1000001 breaches.

        Design: Corner/validations/biodiesel_feedstock_quota_enforced
        """
        base = setup_sales_scenario(
            product="BIODIESEL_FEEDSTOCK", quantity_lbs=2000000,
            price_cents_per_lb=60,
            delivery_window_start="2026-09-15T00:00:00Z",
            delivery_window_end="2026-10-15T00:00:00Z", max_ffa_pct=1.0,
        )
        assert base["contract"]["status"] == "OPEN"
        resp = api_client.create_product_sales_contract(
            create_sales_contract_payload(
                base["buyer"]["id"], base["plant"]["id"],
                product="BIODIESEL_FEEDSTOCK", quantity_lbs=1000001,
                price_cents_per_lb=60,
                delivery_window_start="2026-09-15T00:00:00Z",
                delivery_window_end="2026-10-15T00:00:00Z", max_ffa_pct=1.0,
            ),
            PRODUCT_MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_FEEDSTOCK_QUOTA_EXCEEDED)


class TestMissingMarketQuote:
    def test_election_without_futures_quote_rejected(self, api):
        """PRD §3.4: "Finally, the as-of bean quote for the contract's `futures_month` must exist (`ERR_NO_MARKET_QUOTE`)." No BEAN 2027-05
        quote is on file, so the election fails 422 and the contract stays
        UNPRICED with priced_bushels 0.

        Design: Corner/validations/election_without_futures_quote_rejected
        """
        site = setup_origination_site()
        contract = create_deferred_contract(
            site["farmer"]["id"], site["elevator"]["id"],
            quantity_bushels=100, futures_month="2027-05",
            pricing_deadline="2027-04-15T00:00:00Z",
            storage_rate_cents_per_bushel_day=1,
        )
        resp = api_client.create_pricing_election(
            contract["id"],
            create_pricing_election_payload(100, contract["version"]),
            MERCH,
        )
        validate_error(resp, ApiErrorId.ERR_NO_MARKET_QUOTE)
        after = read_contract(contract["id"])
        assert after["pricing_status"] == "UNPRICED"
        assert float(after["priced_bushels"]) == pytest.approx(0)


class TestPlantInventoryAtRunStart:
    def test_run_start_without_inventory_rejected(self, api):
        """PRD §3.6: "Starting the run (`to_status` `RUNNING`) is legal from `SCHEDULED`, requires the plant's `bean_inventory_bushels` to be at least `planned_bushels` (`ERR_INSUFFICIENT_PLANT_INVENTORY`)". A 5000-bu
        scheduled run at an empty plant fails 422 and stays SCHEDULED.

        Design: Corner/validations/run_start_without_inventory_rejected
        """
        plant = create_crush_plant()
        post_crush_quote_set("2026-11")
        run = create_crush_run(plant["id"], run_date="2026-09-10T00:00:00Z",
                               planned_bushels=5000, futures_month="2026-11")
        schedule_run(run["id"], expected_run_version=run["version"])
        resp = api_client.transition_crush_run(
            run["id"], {"to_status": "RUNNING"}, SCHEDULER
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PLANT_INVENTORY)
        after = read_crush_run(run["id"])
        assert after["status"] == "SCHEDULED"
        plant_after = validate_success(
            api_client.get_crush_plant(plant["id"], SCHEDULER)
        )
        assert float(plant_after["bean_inventory_bushels"]) == pytest.approx(0)


class TestDrawableBushels:
    def test_shipment_beyond_stored_bushels_rejected(self, api):
        """PRD §3.5: "a shipment without it may draw only conventional lots, and any shortfall of drawable bushels within the requested certification class is `ERR_INSUFFICIENT_STORED_BUSHELS`." Booking 6000
        against 5000 stored fails 422 and draws nothing.

        Design: Corner/validations/shipment_beyond_stored_bushels_rejected
        """
        base = setup_elevator_with_stored_bushels(5000)
        plant = create_crush_plant()
        lane = create_truck_lane(
            base["site"]["elevator"]["id"], plant["id"],
            daily_capacity_bushels=50000,
        )
        resp = api_client.create_shipment(
            create_shipment_payload(lane["id"], 6000,
                                    departure_date="2026-09-10T00:00:00Z"),
            LOGISTICS,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STORED_BUSHELS)
        elevator = validate_success(
            api_client.get_elevator(base["site"]["elevator"]["id"], LOGISTICS)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(5000), (
            "a rejected booking draws no lots"
        )

    def test_certified_shipment_draws_only_certified_lots(self, api):
        """PRD §3.5: "a shipment carrying `certified_program_id` may draw only lots of that same program, and when the certified supply cannot fill the booking the request is `ERR_CERTIFICATION_BREAK". With 3000
        certified and 2000 conventional bushels in store, a 4000-bu certified
        booking fails; a 3000-bu one drains the certified lot only.

        Design: Corner/validations/certified_shipment_draws_only_certified_lots
        """
        base = setup_elevator_with_mixed_lots(
            certified_bushels=3000, conventional_bushels=2000
        )
        program_id = base["site"]["program"]["id"]
        plant = create_crush_plant()
        lane = create_truck_lane(
            base["site"]["elevator"]["id"], plant["id"],
            daily_capacity_bushels=50000,
        )
        resp = api_client.create_shipment(
            create_shipment_payload(
                lane["id"], 4000, departure_date="2026-09-10T00:00:00Z",
                certified_program_id=program_id,
            ),
            LOGISTICS,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_BREAK)
        booked = book_shipment(
            lane["id"], 3000, departure_date="2026-09-10T00:00:00Z",
            certified_program_id=program_id,
        )
        assert booked["status"] == "BOOKED"
        positions, _ = validate_paginated(
            api_client.list_storage_positions(
                LOGISTICS, params={"elevator_id": base["site"]["elevator"]["id"]}
            )
        )
        certified = [p for p in positions if p["program_id"] == program_id]
        conventional = [p for p in positions if p["program_id"] is None]
        assert len(certified) == 1 and len(conventional) == 1
        assert float(certified[0]["current_bushels"]) == pytest.approx(0)
        assert certified[0]["status"] == "DEPLETED"
        assert float(conventional[0]["current_bushels"]) == pytest.approx(2000)
        elevator = validate_success(
            api_client.get_elevator(base["site"]["elevator"]["id"], LOGISTICS)
        )
        assert float(elevator["certified_stored_bushels"]) == pytest.approx(0)
        assert float(elevator["stored_bushels"]) == pytest.approx(2000)


class TestBargeCancelFreesInterval:
    def test_barge_cancel_frees_interval_for_rebooking(self, api):
        """PRD §3.5: cancellation of a BOOKED shipment means "the lane occupancy frees for rebooking". A 2026-09-12 departure inside shipment
        1's [09-10, 09-15) interval is refused while shipment 1 stands and
        books cleanly once shipment 1 is cancelled.

        Design: Corner/validations/barge_cancel_frees_interval_for_rebooking
        """
        base = setup_elevator_with_stored_bushels(20000)
        plant = create_crush_plant()
        lane = create_barge_lane(
            base["site"]["elevator"]["id"], plant["id"],
            transit_days=5, daily_capacity_bushels=50000,
        )
        ship1 = book_shipment(lane["id"], 5000,
                              departure_date="2026-09-10T00:00:00Z")
        resp = api_client.create_shipment(
            create_shipment_payload(lane["id"], 5000,
                                    departure_date="2026-09-12T00:00:00Z"),
            LOGISTICS,
        )
        validate_error(resp, ApiErrorId.ERR_BARGE_SCHEDULE_OVERLAP)
        cancel_shipment(ship1["id"])
        rebooked = book_shipment(lane["id"], 5000,
                                 departure_date="2026-09-12T00:00:00Z")
        assert rebooked["status"] == "BOOKED"
        elevator = validate_success(
            api_client.get_elevator(base["site"]["elevator"]["id"], LOGISTICS)
        )
        assert float(elevator["stored_bushels"]) == pytest.approx(15000), (
            "cancel restored 5000, the rebook drew 5000"
        )
