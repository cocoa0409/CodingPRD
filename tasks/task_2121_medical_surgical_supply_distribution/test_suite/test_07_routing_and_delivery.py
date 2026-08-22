"""Route planning, stop geometry, dispatch and receipt into the supply room."""

from test_helpers import (
    ApiErrorId,
    activate_contract,
    add_contract_line,
    add_order_line,
    add_route_stop,
    allocate_order,
    approve_formulary_item,
    assert_delivery_route,
    create_contract,
    create_item,
    create_lot,
    create_order,
    create_route,
    create_route_stop_payload,
    create_supply_room,
    dispatch_route,
    deliver_order,
    flag_lot_excursion,
    lot_excursion_payload,
    make_distribution_operator_headers,
    read_contract,
    read_contract_line,
    read_formulary_item,
    read_order,
    read_order_line,
    read_route,
    set_clock,
    setup_glove_order,
    setup_priced_item,
    submit_order,
    transition_contract,
    validate_error,
    validate_paginated,
    validate_success,
    DISTRIBUTION_OPERATOR_USER_ID,
    SECOND_DISTRIBUTION_OPERATOR_USER_ID,
    TEST_USERS,
)

ADMIN = TEST_USERS["contract_admin_headers"]
OPERATOR = TEST_USERS["distribution_operator_headers"]


def _allocated_order_world(room_overrides=None, requested_qty=2, **kwargs):
    """A room with one AMBIENT case item priced at 3000, a 50-unit lot, and one
    order of `requested_qty` cases already ALLOCATED."""
    world = setup_priced_item(
        room_overrides=room_overrides,
        item_overrides=kwargs.get("item_overrides"),
        contract_overrides=kwargs.get("contract_overrides"),
        tier_price_cents=kwargs.get("tier_price_cents", 3000),
        floor_price_cents=kwargs.get("floor_price_cents", 2000),
        formulary_overrides=kwargs.get("formulary_overrides"),
    )
    world["lot"] = create_lot(
        world["item"]["id"], lot_code=kwargs.get("lot_code", "LOT-ROUTE"),
        expiry_date=kwargs.get("lot_expiry", "2027-12-31T00:00:00Z"),
        received_quantity=kwargs.get("received_quantity", 50),
    )
    world["order"] = create_order(world["room"]["id"])
    world["order_line"] = add_order_line(
        world["order"]["id"], world["room"]["id"], world["item"]["id"],
        requested_qty, world["order"]["version"],
    )
    submit_order(world["order"]["id"], world["room"]["id"])
    world["order"] = allocate_order(world["order"]["id"])
    return world


def test_dispatching_an_empty_route_is_refused(api):
    """PRD §3.7: "Dispatch moves the route `PLANNED → DISPATCHED`. It requires
    the route to be `PLANNED`, to carry at least one assigned order, and for
    **every** assigned order to be `ALLOCATED`; a dispatch attempted on a route
    that is not planned, on an empty route, or on a route holding an order in
    any other fulfilment state, is `ERR_ROUTE_STATE_INVALID`."
    PRD §3.7: "The route starts `PLANNED`, with `planned_order_count` and
    `cold_units_loaded` at zero and `dispatched_at` null."

    Design: Corner/state_machines/route_dispatch_with_no_assigned_orders_is_rejected
    """
    route = create_route(
        route_code="RT-SM8", service_date="2026-08-05", vehicle_class="AMBIENT_VAN"
    )
    assert_delivery_route(route)

    response = api.dispatch_route(route["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_ROUTE_STATE_INVALID.value, 409)

    after = read_route(route["id"])
    assert after["status"] == "PLANNED"
    assert after.get("dispatched_at") is None
    assert after["planned_order_count"] == 0


def test_stop_running_past_the_rooms_closing_minute_is_refused(api):
    """PRD §3.7: "The second is the room's own receiving window: the arrival
    minute must be at or after the room's `window_open_min`, and the arrival
    minute plus the service duration must be at or before its
    `window_close_min`. A stop that starts too early or runs past closing is
    `ERR_STOP_OUTSIDE_ROOM_WINDOW` (HTTP 422)."

    Design: Corner/validations/route_stop_outside_room_receiving_window_rejected
    """
    world = _allocated_order_world(
        room_overrides={
            "facility_code": "FAC-402", "room_code": "GEN-402",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
            "window_open_min": 360, "window_close_min": 600,
        },
        item_overrides={
            "sku": "SKU-WIN-CS", "description": "Window probe",
            "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
            "handling_class": "AMBIENT", "units_per_parent": 10,
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": "CTR-WIN",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        formulary_overrides={"facility_item_code": "FAC-WIN", "par_qty": 50,
                             "reorder_point": 10},
        lot_code="LOT-WIN",
    )
    route = create_route(
        route_code="RT-WIN", service_date="2026-08-05", vehicle_class="AMBIENT_VAN"
    )

    too_late = api.create_route_stop(
        route["id"],
        create_route_stop_payload(world["order"]["id"], 580, 30),
        OPERATOR,
    )
    validate_error(too_late, ApiErrorId.ERR_STOP_OUTSIDE_ROOM_WINDOW.value, 422)

    accepted = add_route_stop(route["id"], world["order"]["id"], 570, 30)
    assert accepted["stop_arrival_min"] == 570
    assert accepted["stop_service_minutes"] == 30
    assert read_route(route["id"])["planned_order_count"] == 1


def test_route_cold_ceiling_accepts_exactly_four_hundred_units(api):
    """PRD §3.7: "A `REEFER_VAN` carries at most 400 cold units; an
    `AMBIENT_VAN` has an effective cold capacity of zero, so any incoming order
    carrying cold units at all is refused. Exceeding either ceiling is
    `ERR_ROUTE_COLD_CAPACITY_EXCEEDED` (HTTP 409); a projection exactly equal to
    the ceiling is accepted."
    PRD §3.7: "The gate is evaluated as a **projection before** the stop is
    written: the route's current cold units plus the incoming order's cold
    units, computed the same way, must not exceed the vehicle's capacity."

    Design: Corner/validations/route_cold_capacity_accepts_exactly_400_units_and_rejects_401
    """
    world = setup_priced_item(
        room_overrides={
            "facility_code": "FAC-403", "room_code": "ICU-403",
            "gpo_member_class": "ACUTE", "room_type": "ICU", "refrigerated": True,
        },
        item_overrides={
            "sku": "SKU-COLD-EA", "description": "Cold chain unit",
            "manufacturer_code": "MFR-BIO", "uom": "EA", "wac_cents": 1000,
            "handling_class": "COLD_CHAIN", "units_per_parent": 1,
        },
        contract_overrides={
            "manufacturer_code": "MFR-BIO", "contract_code": "CTR-COLD",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        tier_price_cents=100,
        floor_price_cents=100,
        formulary_overrides={"facility_item_code": "FAC-COLD", "par_qty": 900,
                             "reorder_point": 100},
    )
    room_id = world["room"]["id"]
    create_lot(
        world["item"]["id"], lot_code="LOT-COLD",
        expiry_date="2027-12-31T00:00:00Z", received_quantity=500,
    )

    full_load = create_order(room_id)
    add_order_line(full_load["id"], room_id, world["item"]["id"], 400,
                   full_load["version"])
    submit_order(full_load["id"], room_id)
    full_load = allocate_order(full_load["id"])

    one_more = create_order(room_id)
    add_order_line(one_more["id"], room_id, world["item"]["id"], 1,
                   one_more["version"])
    submit_order(one_more["id"], room_id)
    one_more = allocate_order(one_more["id"])

    route = create_route(
        route_code="RT-COLD", service_date="2026-08-05", vehicle_class="REEFER_VAN"
    )
    add_route_stop(route["id"], full_load["id"], 480, 30)

    loaded = read_route(route["id"])
    assert loaded["cold_units_loaded"] == 400
    assert loaded["planned_order_count"] == 1

    overflow = api.create_route_stop(
        route["id"], create_route_stop_payload(one_more["id"], 540, 20), OPERATOR
    )
    validate_error(overflow, ApiErrorId.ERR_ROUTE_COLD_CAPACITY_EXCEEDED.value, 409)

    unchanged = read_route(route["id"])
    assert unchanged["cold_units_loaded"] == 400
    assert unchanged["planned_order_count"] == 1
    assert read_order(one_more["id"]).get("route_id") is None
    assert read_order(full_load["id"])["order_total_cents"] == 59595


def test_adding_a_stop_returns_the_updated_order(api):
    """PRD §3.7: "An accepted stop writes `route_id`, `stop_arrival_min` and
    `stop_service_minutes` onto the order and copies the route's `service_date`
    onto it, then recomputes the route's `planned_order_count` and
    `cold_units_loaded`. The response is the updated order rather than the
    route."
    PRD §4: "Requests that mutate state return the resource they conceptually act
    on, which for a route stop is the updated order rather than the route."

    Design: Corner/endpoints/route_stop_endpoint_returns_the_updated_order
    """
    world = _allocated_order_world(
        room_overrides={
            "facility_code": "FAC-501", "room_code": "GEN-501",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
        },
        item_overrides={
            "sku": "SKU-LNK-CS", "description": "Link probe",
            "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
            "handling_class": "AMBIENT", "units_per_parent": 10,
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": "CTR-LNK",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        formulary_overrides={"facility_item_code": "FAC-LNK", "par_qty": 50,
                             "reorder_point": 10},
        lot_code="LOT-LNK",
    )
    route = create_route(
        route_code="RT-LNK", service_date="2026-08-05", vehicle_class="AMBIENT_VAN"
    )

    returned = validate_success(
        api.create_route_stop(
            route["id"],
            create_route_stop_payload(world["order"]["id"], 600, 25),
            OPERATOR,
        ),
        200,
    )

    assert returned["id"] == world["order"]["id"], "the response body is the order"
    assert returned["route_id"] == route["id"]
    assert returned["stop_arrival_min"] == 600
    assert returned["stop_service_minutes"] == 25
    assert returned["service_date"] == "2026-08-05"

    _rows, meta = validate_paginated(
        api.list_orders(ADMIN, params={"route_id": route["id"], "limit": 10,
                                       "offset": 0})
    )
    assert meta["total_count"] == 1


def test_held_then_expired_lot_blocks_delivery_with_distinct_error_ids(api):
    """PRD §3.7: "Before anything is written, every `ALLOCATED` line's lot is
    re-examined: its `status` must still be `AVAILABLE`, otherwise
    `ERR_LOT_NOT_ALLOCATABLE` (HTTP 422), and its `expiry_date` must be strictly
    later than the current logical clock, otherwise `ERR_LOT_EXPIRED` (HTTP
    422)."
    PRD §3.5: "Releasing moves an `EXCURSION_HOLD` lot back to `AVAILABLE` and
    clears `excursion_flagged_by_user_id` — and this is where the two-person
    rule of §2.8 bites: an operator may not release the excursion they
    themselves flagged, and an attempt is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/errors/expired_or_held_lot_blocks_delivery_with_distinct_error_ids
    """
    world = _allocated_order_world(
        room_overrides={
            "facility_code": "FAC-601", "room_code": "GEN-601",
            "gpo_member_class": "ACUTE", "room_type": "GENERAL_STORE",
        },
        item_overrides={
            "sku": "SKU-EXP-CS", "description": "Expiry probe",
            "manufacturer_code": "MFR-ACME", "uom": "CS", "wac_cents": 8000,
            "handling_class": "AMBIENT", "units_per_parent": 10,
        },
        contract_overrides={
            "manufacturer_code": "MFR-ACME", "contract_code": "CTR-EXP",
            "tier": "TIER_1", "member_class_scope": "ACUTE",
        },
        formulary_overrides={"facility_item_code": "FAC-EXP", "par_qty": 50,
                             "reorder_point": 10},
        lot_code="LOT-EXP",
        lot_expiry="2026-09-01T00:00:00Z",
    )
    route = create_route(
        route_code="RT-EXP", service_date="2026-08-01", vehicle_class="AMBIENT_VAN"
    )
    add_route_stop(route["id"], world["order"]["id"], 480, 30)
    dispatch_route(route["id"])

    flag_lot_excursion(world["lot"]["id"], DISTRIBUTION_OPERATOR_USER_ID,
                       "Reefer alarm during loading")

    held = api.deliver_order(
        world["order"]["id"],
        make_distribution_operator_headers(SECOND_DISTRIBUTION_OPERATOR_USER_ID),
    )
    validate_error(held, ApiErrorId.ERR_LOT_NOT_ALLOCATABLE.value, 422)

    released = validate_success(
        api.lot_excursion(
            world["lot"]["id"],
            lot_excursion_payload("RELEASE"),
            make_distribution_operator_headers(SECOND_DISTRIBUTION_OPERATOR_USER_ID),
        ),
        200,
    )
    assert released["status"] == "AVAILABLE"
    assert released.get("excursion_flagged_by_user_id") is None

    set_clock("2026-09-02T00:00:00Z")
    expired = api.deliver_order(
        world["order"]["id"],
        make_distribution_operator_headers(SECOND_DISTRIBUTION_OPERATOR_USER_ID),
    )
    validate_error(expired, ApiErrorId.ERR_LOT_EXPIRED.value, 422)

    after = read_order(world["order"]["id"])
    assert after["fulfillment_status"] == "IN_TRANSIT"
    assert after.get("delivered_at") is None
    assert read_formulary_item(world["formulary_item"]["id"])["on_hand_qty"] == 0


class TestSettlementRepriceAfterSupersession:
    """The same formula run at line write and at delivery legitimately
    disagrees when the pinned contract was superseded in between."""

    @staticmethod
    def _superseded_world():
        set_clock("2026-08-01T00:00:00Z")
        room = create_supply_room(
            facility_code="FAC-001", room_code="OR-CORE-1", gpo_member_class="ACUTE",
            room_type="OR_CORE", refrigerated=True, controlled_secured=True,
            controlled_license_status="ACTIVE", window_open_min=360,
            window_close_min=1080, credit_limit_cents=5000000,
        )
        item = create_item(
            sku="SKU-GLOVE-CS", description="Sterile surgical glove, case of 24",
            manufacturer_code="MFR-ACME", uom="CS", wac_cents=12000,
            handling_class="AMBIENT", units_per_parent=24,
        )
        incumbent = create_contract(
            manufacturer_code="MFR-ACME", contract_code="CTR-A", tier="TIER_2",
            member_class_scope="ACUTE", effective_from="2026-01-01T00:00:00Z",
            effective_to="2026-12-31T23:59:59Z",
        )
        incumbent_line = add_contract_line(
            incumbent["id"], item["id"], tier_price_cents=9000,
            floor_price_cents=8000, chargeback_eligible=True,
        )
        activate_contract(incumbent["id"])

        approve_formulary_item(
            room["id"], item["id"], facility_item_code="FAC-GLOVE", par_qty=400,
            reorder_point=100,
        )
        create_lot(
            item["id"], lot_code="LOT-A1", expiry_date="2027-06-30T00:00:00Z",
            received_quantity=100,
        )

        order = create_order(room["id"])
        line = add_order_line(order["id"], room["id"], item["id"], 10,
                              order["version"])
        submit_order(order["id"], room["id"])
        allocate_order(order["id"])

        successor = create_contract(
            manufacturer_code="MFR-ACME", contract_code="CTR-B", tier="TIER_1",
            member_class_scope="ACUTE", effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-12-31T23:59:59Z",
            supersedes_contract_id=incumbent["id"],
        )
        successor_line = add_contract_line(
            successor["id"], item["id"], tier_price_cents=9200,
            floor_price_cents=8000, chargeback_eligible=True,
        )
        transition_contract(successor["id"], "PENDING_ACTIVATION")
        set_clock("2026-09-05T00:00:00Z")
        transition_contract(successor["id"], "ACTIVE")

        route = create_route(
            route_code="RT-1", service_date="2026-09-05", vehicle_class="REEFER_VAN"
        )
        add_route_stop(route["id"], order["id"], 480, 30)
        dispatch_route(route["id"])
        delivered = deliver_order(order["id"])

        return {
            "room": room, "item": item, "incumbent": incumbent,
            "incumbent_line": incumbent_line, "successor": successor,
            "successor_line": successor_line, "order": delivered, "line_id": line["id"],
        }

    def test_settled_price_differs_from_the_pinned_price(self, api):
        """PRD §3.2: "In its **settlement** role it runs again at the delivery
        instant, re-selecting the candidate set from scratch at that moment and
        storing its result in the line's `settled_unit_price_cents`. When the
        pinned contract was superseded between the line write and the delivery,
        the successor contract's tier and prices apply, and the settled price
        legitimately differs from the pinned price for otherwise identical
        inputs."
        PRD §3.2: "A pinned price survives any later supersession, suspension or
        expiry untouched."

        Design: Difficulty/dual_variant_calc/unit_price_pin_at_line_write_vs_settlement_reprice_diverge
        """
        world = self._superseded_world()
        line = read_order_line(world["line_id"])

        assert line["pinned_unit_price_cents"] == 9540, (
            "pinned under the TIER_2 incumbent: 9000 * 1.06"
        )
        assert line["settled_unit_price_cents"] == 9200, (
            "settled under the TIER_1 successor: 9200 * 1.00"
        )
        assert line["pinned_unit_price_cents"] != line["settled_unit_price_cents"]

    def test_order_total_keeps_the_pinned_figure_after_settlement(self, api):
        """PRD §3.2: "The order total is **never** restated from settled prices,
        and the manufacturer chargeback uses **only** the settled price."
        PRD §3.4: "For each participating line the extended price is its
        `pinned_unit_price_cents` multiplied by that quantity basis, and the line
        fee is the distribution fee of 2.75 percent applied to that extended
        price and **rounded half up to a whole cent on that line, before
        anything is summed**."

        Design: Difficulty/dual_variant_calc/unit_price_pin_at_line_write_vs_settlement_reprice_diverge
        """
        world = self._superseded_world()
        line = read_order_line(world["line_id"])

        assert line["extended_price_cents"] == 95400, "9540 pinned times 10 cases"
        assert line["line_fee_cents"] == 2624
        assert read_order(world["order"]["id"])["order_total_cents"] == 98024

    def test_activation_of_the_successor_supersedes_and_blocks_the_incumbent(self, api):
        """PRD §3.2: "If the activating contract names a `supersedes_contract_id`,
        that contract moves `ACTIVE → SUPERSEDED` in the same request and,
        because it has left the active state, every one of *its* lines moves
        `ACTIVE → BLOCKED`."

        Design: Difficulty/dual_variant_calc/unit_price_pin_at_line_write_vs_settlement_reprice_diverge
        """
        world = self._superseded_world()

        assert read_contract(world["incumbent"]["id"])["status"] == "SUPERSEDED"
        assert (
            read_contract_line(world["incumbent_line"]["id"])["activation_state"]
            == "BLOCKED"
        )
        assert (
            read_contract_line(world["successor_line"]["id"])["activation_state"]
            == "ACTIVE"
        )


class TestDeliveryGatedOnRouteDispatch:
    """An allocated order reaches IN_TRANSIT only through its route."""

    def test_allocated_order_cannot_be_delivered_before_dispatch(self, api):
        """PRD §3.7: "Receipt into the room moves the order `IN_TRANSIT →
        DELIVERED` and is where the second pricing pass happens; a delivery
        attempted from any other fulfilment state is `ERR_ORDER_STATE_INVALID`."
        PRD §3.7: "Dispatch moves the route `PLANNED → DISPATCHED`. It requires
        the route to be `PLANNED`, to carry at least one assigned order, and for
        **every** assigned order to be `ALLOCATED`; a dispatch attempted on a
        route that is not planned, on an empty route, or on a route holding an
        order in any other fulfilment state, is `ERR_ROUTE_STATE_INVALID`."

        Design: Difficulty/cross_entity_state_dependency/order_delivery_gated_on_owning_delivery_route_state
        """
        world = setup_glove_order(
            stage="routed",
            room_overrides={"facility_code": "FAC-015", "room_code": "OR-CORE-15"},
            lot_overrides={"lot_code": "LOT-15", "received_quantity": 100},
            route_overrides={"route_code": "RT-15", "service_date": "2026-08-01",
                             "vehicle_class": "AMBIENT_VAN"},
        )

        premature = api.deliver_order(
            world["order"]["id"],
            make_distribution_operator_headers(DISTRIBUTION_OPERATOR_USER_ID),
        )
        validate_error(premature, ApiErrorId.ERR_ORDER_STATE_INVALID.value, 409)

        after = read_order(world["order"]["id"])
        assert after["fulfillment_status"] == "ALLOCATED"
        assert after.get("delivered_at") is None
        assert read_route(world["route"]["id"])["status"] == "PLANNED"

    def test_delivery_after_dispatch_settles_and_receives_into_the_room(self, api):
        """PRD §3.7: "On success `dispatched_at` is stamped with the logical clock
        and every assigned order moves `ALLOCATED → IN_TRANSIT`. No price is
        recomputed at dispatch."
        PRD §3.7: "For each delivered line the destination formulary mapping's
        `on_hand_qty` increases by the line's `allocated_qty` multiplied by the
        item's `units_per_parent` when the item's `uom` is `CS`, and by one
        otherwise — an each-level or box-level line adds its allocated quantity
        unchanged."
        PRD §3.7: "Finally, if every order assigned to the carrying route is now
        `DELIVERED`, the route moves `DISPATCHED → COMPLETED` and its
        `planned_order_count` is left at its final value."

        Design: Difficulty/cross_entity_state_dependency/order_delivery_gated_on_owning_delivery_route_state
        """
        world = setup_glove_order(
            stage="routed",
            room_overrides={"facility_code": "FAC-015", "room_code": "OR-CORE-15"},
            lot_overrides={"lot_code": "LOT-15", "received_quantity": 100},
            route_overrides={"route_code": "RT-15", "service_date": "2026-08-01",
                             "vehicle_class": "AMBIENT_VAN"},
        )
        api.deliver_order(
            world["order"]["id"],
            make_distribution_operator_headers(DISTRIBUTION_OPERATOR_USER_ID),
        )

        dispatched = dispatch_route(world["route"]["id"])
        assert dispatched["status"] == "DISPATCHED"
        assert read_order(world["order"]["id"])["fulfillment_status"] == "IN_TRANSIT"

        delivered = deliver_order(world["order"]["id"])
        assert delivered["fulfillment_status"] == "DELIVERED"
        assert (
            read_order_line(world["order_line"]["id"])["settled_unit_price_cents"]
            == 9540
        )
        assert read_formulary_item(world["formulary_item"]["id"])["on_hand_qty"] == 240
        assert read_route(world["route"]["id"])["status"] == "COMPLETED"


class TestStopTurnoverBuffer:
    """Stops at one room occupy half-open intervals expanded by a 15-minute
    turnover."""

    @staticmethod
    def _two_allocated_orders_and_a_route():
        world = setup_glove_order(
            stage="allocated",
            room_overrides={
                "facility_code": "FAC-016", "room_code": "OR-CORE-16",
                "window_open_min": 360, "window_close_min": 1080,
            },
            lot_overrides={"lot_code": "LOT-16", "received_quantity": 100},
        )
        room_id = world["room"]["id"]
        second = create_order(room_id)
        add_order_line(second["id"], room_id, world["item"]["id"], 10,
                       second["version"])
        submit_order(second["id"], room_id)
        second = allocate_order(second["id"])

        route = create_route(
            route_code="RT-16", service_date="2026-08-05", vehicle_class="AMBIENT_VAN"
        )
        add_route_stop(route["id"], world["order"]["id"], 480, 30)
        return world, second, route

    def test_arrival_one_minute_inside_the_turnover_collides(self, api):
        """PRD §3.7: "A stop occupies the **half-open** interval that begins at
        its arrival minute and ends immediately before its arrival minute plus
        its service duration, and the room additionally demands a 15-minute
        turnover between consecutive stops."
        PRD §3.7: "Two stops at the same supply room on the same service date, on
        any route whose `status` is `PLANNED` or `DISPATCHED`, collide when the
        new stop's arrival minute is earlier than the existing stop's arrival
        minute plus the existing stop's service duration plus 15, **and** the
        existing stop's arrival minute is earlier than the new stop's arrival
        minute plus the new stop's service duration plus 15. A collision is
        `ERR_ROOM_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/supply_room_stop_half_open_interval_plus_turnover_buffer
        """
        _world, second, route = self._two_allocated_orders_and_a_route()

        response = api.create_route_stop(
            route["id"], create_route_stop_payload(second["id"], 524, 30), OPERATOR
        )
        validate_error(response, ApiErrorId.ERR_ROOM_WINDOW_CONFLICT.value, 409)

        assert read_order(second["id"]).get("route_id") is None
        assert read_route(route["id"])["planned_order_count"] == 1

    def test_the_first_legal_arrival_after_the_turnover_is_accepted(self, api):
        """PRD §3.7: "Two stops at the same supply room on the same service date,
        on any route whose `status` is `PLANNED` or `DISPATCHED`, collide when
        the new stop's arrival minute is earlier than the existing stop's arrival
        minute plus the existing stop's service duration plus 15, **and** the
        existing stop's arrival minute is earlier than the new stop's arrival
        minute plus the new stop's service duration plus 15. A collision is
        `ERR_ROOM_WINDOW_CONFLICT` (HTTP 409)."
        PRD §3.7: "An accepted stop writes `route_id`, `stop_arrival_min` and
        `stop_service_minutes` onto the order and copies the route's
        `service_date` onto it, then recomputes the route's `planned_order_count`
        and `cold_units_loaded`."

        Design: Difficulty/resource_temporal_overlap/supply_room_stop_half_open_interval_plus_turnover_buffer
        """
        _world, second, route = self._two_allocated_orders_and_a_route()
        api.create_route_stop(
            route["id"], create_route_stop_payload(second["id"], 524, 30), OPERATOR
        )

        accepted = add_route_stop(route["id"], second["id"], 525, 30)
        assert accepted["stop_arrival_min"] == 525
        assert accepted["stop_service_minutes"] == 30
        assert accepted["service_date"] == "2026-08-05"

        after = read_route(route["id"])
        assert after["planned_order_count"] == 2
        assert after["cold_units_loaded"] == 0
