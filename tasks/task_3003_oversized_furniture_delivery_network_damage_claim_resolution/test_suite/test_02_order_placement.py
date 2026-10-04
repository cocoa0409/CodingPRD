"""Order placement: routing branches, pricing, fee split, promised dates."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    set_clock,
    create_supplier,
    create_hub,
    create_freight_lane,
    create_item,
    create_customer,
    create_linehaul,
    place_order,
    get_shipment_for_order,
    setup_reference_data,
    api_client,
    TEST_USERS,
    make_customer_headers,
    SETUP_CLOCK,
)

ADMIN = TEST_USERS["network_admin_headers"]


class TestShippingPriceAndFeeSplit:
    def test_shipping_price_ceil_weight_and_fee_split_literals(self, api):
        """PRD §3.3: "The `shipping_amount_cents` is taken from the `ACTIVE`
        freight lane matching the shipment's `leg_mode` and the customer's
        `destination_zone`: the lane's `base_rate_cents` plus its
        `per_lb_rate_cents` multiplied by the item's weight rounded up to a
        whole pound."
        PRD §3.3: "The `order_total_cents` is computed first, as the item's
        `declared_value_cents` plus the `shipping_amount_cents`, before any
        fee component exists."
        PRD §3.3: "The `oversized_surcharge_cents` comes second: it is zero
        when the item's `freight_class` is `PARCEL_ELIGIBLE`, and otherwise
        5% of the `order_total_cents` rounded half-up to whole cents."
        PRD §3.3: "The `handling_fee_cents` comes third: 8% applied to the
        remainder after subtracting the surcharge from the total — that is,
        8% of (`order_total_cents` minus `oversized_surcharge_cents`) —
        rounded half-up to whole cents."

        Design: Corner/calculations/shipping_price_ceil_weight_and_fee_split_literals
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        hub = create_hub()  # routing needs a hub serving the zone
        create_freight_lane()  # LTL ZONE_NE base 40000, per-lb 50, transit 3
        item = create_item(
            supplier["id"], sku="SKU-W30", weight_lb=30.4,
            white_glove_eligible=False,
        )
        customer = create_customer()
        create_linehaul(hub["id"])
        order = place_order(customer, item["id"], "THRESHOLD")
        assert order["shipping_amount_cents"] == 41550, (
            "40000 + 50 * ceil(30.4) == 41550"
        )
        assert order["order_total_cents"] == 121550
        assert order["oversized_surcharge_cents"] == 6078, (
            "round_half_up(121550 * 0.05) == 6078"
        )
        assert order["handling_fee_cents"] == 9238, (
            "round_half_up((121550 - 6078) * 0.08) == 9238"
        )


class TestParcelBranchRouting:
    def test_parcel_branch_skips_hub_dwell(self, api):
        """PRD §3.3: "Branch one is parcel: if the item's `freight_class` is
        `PARCEL_ELIGIBLE`, its `parcel_ok` flag is true, and an `ACTIVE`
        `PARCEL` lane exists for the customer's `destination_zone`, the
        shipment's `fulfillment_mode` and `leg_mode` are both set to `PARCEL`,
        and the shipment carries no hub or linehaul binding."
        PRD §3.3: "its `promised_date` is computed as the order creation date
        plus 2 handling days plus the selected lane's `transit_days`, plus 1
        additional hub-dwell day when the `fulfillment_mode` is
        `OWNED_FINAL_MILE`."

        Design: Corner/calculations/promised_date_base_and_parcel_branch_routing
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        create_freight_lane(
            leg_mode="PARCEL", dest_zone="ZONE_NE",
            base_rate_cents=1500, per_lb_rate_cents=10, transit_days=2,
        )
        item = create_item(
            supplier["id"], sku="SKU-SM-1",
            dim_length_in=20, dim_width_in=16, dim_height_in=12,
            weight_lb=12, declared_value_cents=9000, white_glove_eligible=False,
        )
        customer = create_customer()
        order = place_order(customer, item["id"], "THRESHOLD")
        shipment = get_shipment_for_order(order["id"])
        assert shipment["fulfillment_mode"] == "PARCEL"
        assert shipment["hub_id"] is None
        assert shipment["promised_date"] == "2026-09-09", (
            "2026-09-05 + 2 handling + 2 transit, no hub dwell"
        )
        assert order["shipping_amount_cents"] == 1620, "1500 + 10 * 12"
        assert order["oversized_surcharge_cents"] == 0, (
            "surcharge is zero for PARCEL_ELIGIBLE"
        )
        assert order["handling_fee_cents"] == 850, (
            "round_half_up(10620 * 0.08) == 850"
        )

    def test_owned_final_mile_base_promised_date_adds_hub_dwell(self, api):
        """PRD §3.3: "its `promised_date` is computed as the order creation
        date plus 2 handling days plus the selected lane's `transit_days`,
        plus 1 additional hub-dwell day when the `fulfillment_mode` is
        `OWNED_FINAL_MILE`."

        Design: Corner/calculations/promised_date_base_and_parcel_branch_routing
        """
        refs = setup_reference_data()
        order = place_order(refs["customer"], refs["item"]["id"], "THRESHOLD")
        shipment = get_shipment_for_order(order["id"])
        assert shipment["fulfillment_mode"] == "OWNED_FINAL_MILE"
        assert shipment["promised_date"] == "2026-09-11", (
            "2026-09-05 + 2 handling + 3 transit + 1 hub dwell"
        )


class TestOrderCreateValidation:
    def test_missing_item_id_is_invalid_request_and_unknown_item_is_not_found(self, api):
        """PRD §2.7: "third, whether every path and body identifier resolves
        to an existing resource, validated left-to-right with path segments
        first and body fields in their declared input order
        (`ERR_NOT_FOUND`); fourth, whether required fields are present,
        well-typed, and carry enum values inside their declared sets
        (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/order_create_missing_item_id_returns_invalid_request
        """
        set_clock(SETUP_CLOCK)
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        resp_missing = api.create_order(
            {"customer_id": customer["id"], "service_level": "THRESHOLD"}, headers
        )
        validate_error(resp_missing, ApiErrorId.ERR_INVALID_REQUEST)
        resp_unknown = api.create_order(
            {"customer_id": customer["id"], "item_id": NON_EXISTENT_UUID,
             "service_level": "THRESHOLD"},
            headers,
        )
        validate_error(resp_unknown, ApiErrorId.ERR_NOT_FOUND)
        rows, meta = validate_paginated(
            api.list_orders(ADMIN, params={"customer_id": customer["id"]})
        )
        assert len(rows) == 0

    def test_out_of_enum_service_level_returns_invalid_request(self, api):
        """PRD §2.7: "fourth, whether required fields are present, well-typed,
        and carry enum values inside their declared sets
        (`ERR_INVALID_REQUEST`)"
        PRD §3.3: "A `Customer` places an order with a payload naming the
        `customer_id`, the `item_id`, and the desired `service_level`, which
        is either `THRESHOLD` or `ROOM_OF_CHOICE`."

        Design: Corner/entities/order_create_with_out_of_enum_service_level_returns_invalid_request
        """
        refs = setup_reference_data()
        headers = make_customer_headers(refs["customer"]["id"])
        resp = api.create_order(
            {"customer_id": refs["customer"]["id"],
             "item_id": refs["item"]["id"],
             "service_level": "WHITE_GLOVE"},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, _meta = validate_paginated(api.list_shipments(ADMIN))
        assert len(rows) == 0, "no shipment may be created for a rejected order"


class TestOrderBusinessChecks:
    def test_room_of_choice_on_ineligible_item_returns_service_level_error(self, api):
        """PRD §3.3: "first the service-level check — `ROOM_OF_CHOICE`
        requires the item's `white_glove_eligible` to be true, else
        `ERR_SERVICE_LEVEL_NOT_AVAILABLE`"

        Design: Corner/validations/room_of_choice_on_ineligible_item_returns_service_level_error
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        create_hub()
        create_freight_lane()
        item = create_item(
            supplier["id"], sku="SKU-NWG", white_glove_eligible=False
        )
        customer = create_customer()
        create_linehaul(api.list_hubs(ADMIN).json()["data"][0]["id"])
        headers = make_customer_headers(customer["id"])
        resp = api.create_order(
            {"customer_id": customer["id"], "item_id": item["id"],
             "service_level": "ROOM_OF_CHOICE"},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_LEVEL_NOT_AVAILABLE)
        rows, _meta = validate_paginated(api.list_shipments(ADMIN))
        assert len(rows) == 0

    def test_order_to_zone_without_hub_returns_no_route(self, api):
        """PRD §3.3: "then routability — some hub/lane combination must be
        able to serve the customer's zone for the chosen service level, else
        `ERR_NO_ROUTE`"

        Design: Corner/validations/order_to_zone_without_hub_returns_no_route
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        item = create_item(supplier["id"])
        customer = create_customer(
            email="c9@example.com", full_name="Customer Nine",
            destination_zone="ZONE_NOWHERE",
        )
        headers = make_customer_headers(customer["id"])
        resp = api.create_order(
            {"customer_id": customer["id"], "item_id": item["id"],
             "service_level": "THRESHOLD"},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ROUTE)
        rows, _meta = validate_paginated(api.list_shipments(ADMIN))
        assert len(rows) == 0

    def test_order_on_delisted_item_returns_item_not_listed(self, api):
        """PRD §3.1: "A delisted item moves to `DELISTED` — a terminal state
        — and future orders against it are rejected with
        `ERR_ITEM_NOT_LISTED`."
        PRD §3.3: "then the listing check — the item must be `LISTED` and its
        supplier must not be `SUSPENDED`, else `ERR_ITEM_NOT_LISTED`"

        Design: Corner/validations/order_on_delisted_item_returns_item_not_listed
        """
        refs = setup_reference_data()
        resp = api.delist_item(refs["item"]["id"], ADMIN)
        validate_success(resp, 200)
        headers = make_customer_headers(refs["customer"]["id"])
        resp2 = api.create_order(
            {"customer_id": refs["customer"]["id"],
             "item_id": refs["item"]["id"],
             "service_level": "THRESHOLD"},
            headers,
        )
        validate_error(resp2, ApiErrorId.ERR_ITEM_NOT_LISTED)


class TestHubSelectorPolicy:
    def test_hub_selector_ranks_transit_then_earliest_created(self, api):
        """PRD §3.3: "Branch four is the LTL network fallback: the candidates
        are all `ACTIVE` hubs serving the zone, selected by the same
        transit-days-then-creation-time rule as branch two, with an empty set
        again producing `ERR_NO_ROUTE`"
        PRD §3.3: "the selector chooses the candidate whose
        `OWNED_FINAL_MILE` lane to the zone has the fewest `transit_days`,
        breaking ties by the hub's `created_at` ascending — never by
        identifier."

        Design: Corner/cross_cutting_complexity_layers/hub_selector_ranks_transit_then_earliest_created
        """
        set_clock(SETUP_CLOCK)
        supplier = create_supplier()
        create_freight_lane(
            leg_mode="LTL", dest_zone="ZONE_SW",
            base_rate_cents=40000, per_lb_rate_cents=50, transit_days=3,
        )
        hub_x = create_hub(
            hub_code="HUB-X", name="First Hub", serves_zones=["ZONE_SW"],
            white_glove_capable=False, daily_capacity=5,
        )
        hub_y = create_hub(
            hub_code="HUB-Y", name="Second Hub", serves_zones=["ZONE_SW"],
            white_glove_capable=False, daily_capacity=5,
        )
        item = create_item(supplier["id"])
        customer = create_customer(
            email="c5@example.com", full_name="Customer Five",
            destination_zone="ZONE_SW",
        )
        create_linehaul(hub_x["id"])
        create_linehaul(hub_y["id"])
        order = place_order(customer, item["id"], "THRESHOLD")
        shipment = get_shipment_for_order(order["id"])
        assert shipment["hub_id"] == hub_x["id"], (
            "created_at ASC tie-break selects the earlier-created hub"
        )
        assert shipment["hub_id"] != hub_y["id"]


class TestOrderCreateImmediateConsistency:
    def test_order_create_response_is_immediately_consistent(self, api):
        """PRD §3.3: "Pricing follows routing."
        PRD §3.3: "The order itself moves from `PENDING` to `ROUTED`
        automatically as routing succeeds"
        PRD §2.9: "These cascades are part of the API contract: a client that
        performs the triggering action observes all of the side effects in a
        single response cycle."

        Design: Corner/consistency_model/order_create_response_is_immediately_consistent
        """
        refs = setup_reference_data()
        resp = api.create_order(
            {"customer_id": refs["customer"]["id"],
             "item_id": refs["item"]["id"],
             "service_level": "THRESHOLD"},
            make_customer_headers(refs["customer"]["id"]),
        )
        data = validate_success(resp, 201)
        assert data["order_state"] == "ROUTED", (
            "PENDING → ROUTED is atomic within order creation"
        )
        # 30lb item: 40000 + 50*30 = 41500 shipping; total 121500
        assert data["order_total_cents"] == 121500
        assert data["oversized_surcharge_cents"] == 6075
        assert data["handling_fee_cents"] == 9234
        rows, _meta = validate_paginated(
            api.list_shipments(ADMIN, params={"order_id": data["id"]})
        )
        assert len(rows) == 1
        assert rows[0]["promised_date"] == "2026-09-11"
