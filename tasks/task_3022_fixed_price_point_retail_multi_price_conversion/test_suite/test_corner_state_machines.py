"""Invalid transitions, action repetition, precondition enforcement and terminal lockdown."""

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    DCO_HEADERS,
    E,
    IMPORT_HEADERS,
    SOM_HEADERS,
    api_client,
    factories,
    validate_error,
    validate_success,
    fixtures,
)

DEPART_QUOTE = (
    "Departure moves it from `BOOKED` to `IN_TRANSIT` and is refused from any other status with "
    "`ERR_CONTAINER_NOT_BOOKED`."
)
ARRIVE_QUOTE = (
    "Arrival discharges it at the port, moving it from `IN_TRANSIT` to `AT_PORT` and refused "
    "otherwise with `ERR_CONTAINER_NOT_IN_TRANSIT`."
)
ALLOCATED_QUOTE = (
    "A short moves an `ALLOCATED` line to `SHORTED`, sets its `remaining_units` to zero, "
    "recomputes the affected store's `open_violation_count`, and recomputes the line's container "
    "status."
)
NOT_ALLOCATED_QUOTE = (
    "Both release and short are refused on a line that is not currently `ALLOCATED`, with "
    "`ERR_ALLOCATION_LINE_NOT_ALLOCATED` and HTTP 409."
)
RELEASE_HOP_QUOTE = (
    "this is the cross-entity hop that matters — adds the same quantity to the item's "
    "`on_hand_units`, from which the item's `is_shelf_overflow` flag is recomputed as on-hand "
    "units multiplied by `sqft_per_unit` being greater than `shelf_package_capacity`."
)
CONVERSION_PRECOND_QUOTE = (
    "The first call begins the change: a store currently in `SINGLE_PRICE` may be converted to a "
    "target price point, and if it is not in `SINGLE_PRICE` the attempt is rejected with "
    "`ERR_STORE_NOT_SINGLE_PRICE`; if its `conversion_price_point_id` is already set the attempt "
    "is rejected with `ERR_STORE_ALREADY_CONVERTING`; and if the target price point is not "
    "`ACTIVE` the attempt is rejected with `ERR_PRICE_POINT_NOT_ACTIVE`."
)
NOT_ACTIVE_QUOTE = (
    "A price point becomes issuable only once it has been moved to `ACTIVE`, and until it is "
    "`ACTIVE` every attempt to issue it — to an item, to a store conversion, to a store "
    "reversion, or to an exclusive pack program — is rejected with `ERR_PRICE_POINT_NOT_ACTIVE` "
    "and HTTP 409."
)
AUDIT_RESOLVE_QUOTE = (
    "A `StoreOperationsManager` may resolve it directly once the shelf and the register have been "
    "reconciled; that call requires the audit to be `OPEN` and is refused with "
    "`ERR_AUDIT_ALREADY_RESOLVED` if it is not."
)
AUDIT_CLOSE_QUOTE = (
    "Or the audit closes as a secondary effect of the store's own conversion completing, as "
    "described in §3.8 — every open violation on a converting store closes to `RESOLVED` when "
    "that store completes its change."
)
LAND_GATES_QUOTE = (
    "A freight pass-through is subject to two hard gates on the container it draws on. The "
    "container must be in `RECEIVED`; a pass-through naming a container that is not is rejected "
    "with `ERR_CONTAINER_NOT_RECEIVED` and HTTP 409. The container must also belong to the same "
    "vendor the item is sourced from — the container's vendor must equal the item's sourcing "
    "vendor — and a mismatch is rejected with `ERR_CONTAINER_VENDOR_MISMATCH` and HTTP 409."
)


def test_a_second_departure_from_a_container_already_on_the_water_is_refused(api):
    """IN_TRANSIT has no departure edge, so a repeat is a state error and mutates nothing.

    PRD §3.6: "Departure moves it from `BOOKED` to `IN_TRANSIT` and is refused from any other
    status with `ERR_CONTAINER_NOT_BOOKED`."
    PRD §3.6: "Arrival discharges it at the port, moving it from `IN_TRANSIT` to `AT_PORT` and
    refused otherwise with `ERR_CONTAINER_NOT_IN_TRANSIT`."

    Design: Corner/state_machines/container_depart_from_booked_then_depart_again_returns_invalid_state
    """
    fixtures.set_clock()
    vendor = fixtures.create_vendor()
    container = fixtures.create_booked_container(vendor["id"], total_freight_cents=200)

    sailing = validate_success(api_client.container_depart(container["id"], IMPORT_HEADERS), 200)
    assert sailing["status"] == "IN_TRANSIT"
    version_after_first = sailing["version"]

    validate_error(
        api_client.container_depart(container["id"], IMPORT_HEADERS),
        E.ERR_CONTAINER_NOT_BOOKED.value,
    )

    read = validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)
    assert read["status"] == "IN_TRANSIT", "the refused call did not skip a leg"
    assert read["version"] == version_after_first, "the refused call did not mutate the container"


def test_shorting_a_line_that_has_already_left_allocated_is_refused(api):
    """A partially released line may still be shorted; neither action is repeatable.

    PRD §3.7: "A short moves an `ALLOCATED` line to `SHORTED`, sets its `remaining_units` to
    zero, recomputes the affected store's `open_violation_count`, and recomputes the line's
    container status."
    PRD §3.7: "Both release and short are refused on a line that is not currently `ALLOCATED`,
    with `ERR_ALLOCATION_LINE_NOT_ALLOCATED` and HTTP 409."
    PRD §3.7: "this is the cross-entity hop that matters — adds the same quantity to the item's
    `on_hand_units`, from which the item's `is_shelf_overflow` flag is recomputed as on-hand units
    multiplied by `sqft_per_unit` being greater than `shelf_package_capacity`."

    Design: Corner/state_machines/allocation_line_short_after_release_returns_not_allocated
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="1001", sqft_per_unit=0.1,
        shelf_package_capacity=4.0)
    container = fixtures.create_received_container(vendor["id"], total_freight_cents=0)
    line = fixtures.allocate(container["id"], store["id"], item["id"],
                             sequence=1, requested_units=4)
    fixtures.release_line(line["id"], 2)

    shorted = validate_success(api_client.short_allocation_line(line["id"], DCO_HEADERS), 200)
    assert shorted["status"] == "SHORTED", "a partially released line is still ALLOCATED"
    assert shorted["remaining_units"] == 0
    assert shorted["released_units"] == 2, "the short does not rewind the units already released"

    validate_error(
        api_client.short_allocation_line(line["id"], DCO_HEADERS),
        E.ERR_ALLOCATION_LINE_NOT_ALLOCATED.value,
    )

    item_after = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert item_after["on_hand_units"] == 2, "the short set the remainder to zero without clawing back stock"


def test_each_conversion_begin_precondition_reports_its_own_error(api):
    """A draft target point, then a second begin on an already-converting store.

    PRD §3.8: "The first call begins the change: a store currently in `SINGLE_PRICE` may be
    converted to a target price point, and if it is not in `SINGLE_PRICE` the attempt is rejected
    with `ERR_STORE_NOT_SINGLE_PRICE`; if its `conversion_price_point_id` is already set the
    attempt is rejected with `ERR_STORE_ALREADY_CONVERTING`; and if the target price point is not
    `ACTIVE` the attempt is rejected with `ERR_PRICE_POINT_NOT_ACTIVE`."
    PRD §2.4: "A price point becomes issuable only once it has been moved to `ACTIVE`, and until
    it is `ACTIVE` every attempt to issue it — to an item, to a store conversion, to a store
    reversion, or to an exclusive pack program — is rejected with `ERR_PRICE_POINT_NOT_ACTIVE`
    and HTTP 409."

    Design: Corner/state_machines/conversion_start_requires_a_single_price_store_and_an_active_price_point
    """
    fixtures.set_clock()
    active_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    draft_point = fixtures.create_draft_price_point(300, 0.40, label="THREE_DOLLAR_25")
    store = fixtures.create_store()

    validate_error(
        api.begin_conversion(store["id"], draft_point["id"], SOM_HEADERS),
        E.ERR_PRICE_POINT_NOT_ACTIVE.value,
    )

    validate_success(api.activate_price_point(draft_point["id"], BUYER_HEADERS), 200)
    began = validate_success(api.begin_conversion(store["id"], draft_point["id"], SOM_HEADERS), 200)
    assert began["status"] == "CONVERTING"

    validate_error(
        api.begin_conversion(store["id"], active_point["id"], SOM_HEADERS),
        E.ERR_STORE_NOT_SINGLE_PRICE.value,
    )

    read = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert read["status"] == "CONVERTING"
    assert read["conversion_price_point_id"] == draft_point["id"]


def test_an_audit_closes_once_and_refuses_a_second_resolution(api):
    """RESOLVED is terminal for the audit, and the stored verdict survives the close.

    PRD §3.11: "A `StoreOperationsManager` may resolve it directly once the shelf and the
    register have been reconciled; that call requires the audit to be `OPEN` and is refused with
    `ERR_AUDIT_ALREADY_RESOLVED` if it is not."
    PRD §3.11: "Or the audit closes as a secondary effect of the store's own conversion
    completing, as described in §3.8 — every open violation on a converting store closes to
    `RESOLVED` when that store completes its change."

    Design: Corner/state_machines/audit_resolve_after_auto_resolution_returns_already_resolved
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    store = fixtures.create_store()
    audit = validate_success(
        api.create_audit(factories.create_audit_payload(
            store["id"], price_point["id"], observed_item_count=80, mismatched_item_count=5),
            SOM_HEADERS),
        201,
    )

    first = validate_success(api.resolve_audit(audit["id"], SOM_HEADERS), 200)
    assert first["status"] == "RESOLVED"

    validate_error(api.resolve_audit(audit["id"], SOM_HEADERS), E.ERR_AUDIT_ALREADY_RESOLVED.value)

    read = validate_success(api.get_audit(audit["id"], ANALYST_HEADERS), 200)
    assert read["status"] == "RESOLVED"
    assert read["result"] == "VIOLATION", "resolution does not launder the verdict"

    store_after = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert store_after["open_violation_count"] == 0
    assert store_after["price_integrity_audit_count"] == 1


def test_the_two_landed_cost_safety_gates_report_their_own_reasons(api):
    """A non-received container and a foreign container are two distinct refusals.

    PRD §3.2: "A freight pass-through is subject to two hard gates on the container it draws on.
    The container must be in `RECEIVED`; a pass-through naming a container that is not is
    rejected with `ERR_CONTAINER_NOT_RECEIVED` and HTTP 409. The container must also belong to
    the same vendor the item is sourced from — the container's vendor must equal the item's
    sourcing vendor — and a mismatch is rejected with `ERR_CONTAINER_VENDOR_MISMATCH` and HTTP 409."
    PRD §3.2: "A vendor price change is subject to neither gate because it references no container."

    Design: Corner/state_machines/land_side_gate_rejects_pass_through_before_receipt
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    other_vendor = fixtures.create_vendor(vendor_name="Ho Chi Minh Plastics", country_of_origin="VN")
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="1001", base_landed_cost_cents=105)

    own_container = fixtures.create_container_at_port(vendor["id"], total_freight_cents=0)
    foreign_container = fixtures.create_received_container(other_vendor["id"], total_freight_cents=0)

    validate_error(
        api.apply_landed_cost(
            item["id"],
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 107,
             "container_id": own_container["id"]},
            BUYER_HEADERS),
        E.ERR_CONTAINER_NOT_RECEIVED.value,
    )
    validate_error(
        api.apply_landed_cost(
            item["id"],
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 107,
             "container_id": foreign_container["id"]},
            BUYER_HEADERS),
        E.ERR_CONTAINER_VENDOR_MISMATCH.value,
    )

    state = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert state["status"] == "PRICE_ASSIGNED"
    assert state["landed_cost_cents"] == 0
    history = validate_success(api.list_item_landed_costs(item["id"], ANALYST_HEADERS), 200)
    assert history == [], "neither refusal wrote a cost row"