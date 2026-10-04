"""Component allocation: on-hand stock, derived reservations and the retrofit hold.

``reserved_qty`` is never patched incrementally: it is re-derived from scratch on
every event from two terms — the bill-of-material rows of orders that have been
released, and the kits held by retrofit work orders that have actually started.
``on_hand_qty`` moves only on reservation, receipt and retrofit consumption, so a
receipt raises the available figure without disturbing the reservations term.

Every expected figure below is recomputed from the PRD's stated formulas.
"""

from test_helpers import (
    CLOCK_START_ISO,
    api_client,
    create_component_payload,
    create_component_purchase_order_payload,
    create_component_receipt_payload,
    create_order,
    create_retrofit_program,
    create_work_order,
    get_success_data,
    release_order,
    reserve_order,
    set_clock,
)

from test_calculations_support import (
    ADMIN,
    PLANNER,
    SUPPLY,
    flat_car_catalogue,
    held_cars,
)


def test_reservation_commits_stock_and_release_derives_the_reservations_term(api):
    """PRD §3.2: "A successful reservation commits the wheelset and casting
    stock: for each covered row, the component's `on_hand_qty` is decremented by
    the effective per-car quantity multiplied by the order quantity, and the
    component's `reserved_qty` is recomputed by the allocation rule below."
    PRD §3.2: "the reservation term is the sum, over every bill-of-material row
    that names that component, of the row's `qty_per_car` multiplied by the total
    quantity of production orders that build that row's car type and are in
    `RELEASED` status; orders in `DRAFT`, `COMPONENT_RESERVED`, `COMPLETED` or
    `CANCELLED` contribute nothing."

    Twenty-five units on hand feed a four-per-car row for five cars: reserving
    takes on-hand to 5 while the reservations term stays empty because the order
    is only `COMPONENT_RESERVED`, and releasing the same order derives 20 without
    moving stock a second time.

    Design: Corner/calculations/component_allocation_correct_result_released_reservations
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue(
        wheelset_part_number="WS-320", wheelset_qty_per_car=4, on_hand_qty=25
    )
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=5,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )

    reserved = reserve_order(order["id"])
    after_reservation = get_success_data(
        api_client.get_component(catalogue["wheelset"]["id"], PLANNER)
    )
    assert reserved["status"] == "COMPONENT_RESERVED"
    assert after_reservation["on_hand_qty"] == 5, "25 - 4 * 5 units committed"
    assert after_reservation["reserved_qty"] == 0, (
        "only RELEASED orders contribute to the reservations term"
    )

    released = release_order(order["id"])
    after_release = get_success_data(
        api_client.get_component(catalogue["wheelset"]["id"], PLANNER)
    )
    assert released["status"] == "RELEASED"
    assert after_release["reserved_qty"] == 20, "4 units per car over 5 cars"
    assert after_release["on_hand_qty"] == 5, (
        "release does not move stock a second time"
    )


def test_scheduled_retrofit_work_order_holds_no_kit_until_it_starts(api):
    """PRD §3.2: "The retrofit term is the sum of `component_qty_consumed` over
    every retrofit work order that is in `IN_PROGRESS` status and whose program
    names this component as its `required_component_id`; work orders in
    `SCHEDULED`, `COMPLETED` or `CANCELLED` contribute nothing."
    PRD §3.8: "when the program names a `required_component_id` — the
    component's `on_hand_qty` is decremented by the work order's
    `component_qty_consumed` and its `reserved_qty` and `shortfall_qty` are
    re-derived by the allocation rule of §3.2."

    A work order consuming seven kit units contributes nothing to the kit's
    reserved figure while it is `SCHEDULED` and exactly seven once it starts, at
    which point the on-hand figure also drops by the seven units consumed.

    Design: Corner/calculations/component_allocation_scheduled_retrofit_excluded_from_holds
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    kit = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-330",
                component_class="WHEELSET",
                unit_cost_cents=2000,
                lead_time_days=10,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    world = held_cars(
        catalogue,
        car_count=2,
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
        required_delivery_date="2026-09-20",
    )
    program = create_retrofit_program(
        catalogue,
        mandate_code="MAND-300",
        compliance_deadline_date="2026-12-31",
        required_shop_days_per_car=5,
        required_component_id=kit["id"],
    )["program"]
    work_order = create_work_order(
        program,
        world["car"],
        shop_line="SHOP-300",
        scheduled_start_date="2026-09-10",
        component_qty_consumed=7,
    )

    while_scheduled = get_success_data(api_client.get_component(kit["id"], SUPPLY))
    assert work_order["status"] == "SCHEDULED"
    assert while_scheduled["reserved_qty"] == 0, (
        "a scheduled work order holds no kit stock"
    )
    assert while_scheduled["on_hand_qty"] == 100

    started = get_success_data(
        api_client.start_retrofit_work_order(work_order["id"], PLANNER)
    )
    after_start = get_success_data(api_client.get_component(kit["id"], SUPPLY))
    assert started["status"] == "IN_PROGRESS"
    assert after_start["reserved_qty"] == 7, (
        "the retrofit term is the consumed quantity of IN_PROGRESS work orders"
    )
    assert after_start["on_hand_qty"] == 93, (
        "starting the work consumes the kit as well as holding it"
    )


def test_receipt_raises_available_stock_without_moving_reservations(api):
    """PRD §3.2: "A read taken after a receipt has landed therefore shows the
    same reservations term with a larger on-hand figure, and consequently a lower
    shortfall."
    PRD §3.2: "On success the purchase order becomes `RECEIVED`, the component's
    `on_hand_qty` is increased by `qty_received`, and `reserved_qty` and
    `shortfall_qty` are recomputed by the allocation rule above."

    A two-per-car row over five released cars reserves 10 units against the 10
    left on hand; receiving 30 units raises the on-hand figure to 40 and leaves
    the reservations term at 10, so only the available side of the allocation
    moves.

    Design: Corner/calculations/component_allocation_variant_divergence_committed_vs_available
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue(
        wheelset_part_number="WS-340",
        wheelset_qty_per_car=2,
        wheelset_lead_time_days=4,
        on_hand_qty=20,
    )
    order = create_order(
        catalogue,
        quantity=5,
        planned_shop_days=5,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    purchase_order = get_success_data(
        api_client.create_component_purchase_order(
            create_component_purchase_order_payload(
                component_id=catalogue["wheelset"]["id"],
                qty_ordered=30,
                unit_cost_cents=1000,
                order_date="2026-09-01",
                expected_receipt_date="2026-09-05",
            ),
            SUPPLY,
        )
    )
    get_success_data(
        api_client.confirm_component_purchase_order(purchase_order["id"], SUPPLY)
    )

    reserve_order(order["id"])
    release_order(order["id"])
    committed = get_success_data(
        api_client.get_component(catalogue["wheelset"]["id"], SUPPLY)
    )
    assert committed["on_hand_qty"] == 10, "20 - 2 * 5 units committed"
    assert committed["reserved_qty"] == 10

    receipt = get_success_data(
        api_client.create_component_receipt(
            create_component_receipt_payload(
                component_purchase_order_id=purchase_order["id"],
                component_id=catalogue["wheelset"]["id"],
                qty_received=30,
                receipt_date="2026-09-05",
            ),
            SUPPLY,
        )
    )
    get_success_data(api_client.receive_component_receipt(receipt["id"], SUPPLY))

    promised = get_success_data(
        api_client.get_component(catalogue["wheelset"]["id"], SUPPLY)
    )
    assert promised["on_hand_qty"] == 40, "the 30 received units land on hand"
    assert promised["reserved_qty"] == 10, (
        "the receipt leaves the reservations term exactly where it stood"
    )
    assert promised["shortfall_qty"] == 0

    closed = get_success_data(
        api_client.get_component_purchase_order(purchase_order["id"], ADMIN)
    )
    assert closed["status"] == "RECEIVED"
