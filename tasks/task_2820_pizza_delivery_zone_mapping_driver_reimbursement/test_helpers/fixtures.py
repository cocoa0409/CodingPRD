"""Composite setup helpers.

Every helper here builds state exclusively through the documented endpoints —
there is no direct database access anywhere — because the harness restarts the
service before each test and each test therefore starts from an empty store.

The helpers are deliberately layered: the thin wrappers at the top perform one
call each and hand back the unwrapped ``data`` object, and the composites lower
down chain those wrappers into the recurring worlds (an operational store, a
committed route, a delivered stop, a settled route) that most scenarios need.
Anything a scenario wants to vary is a keyword argument, so a caller never has
to reach around a composite to reshape it.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    ADDRESS_COORDS,
    CAR_COST_MODEL,
    DEFAULT_CLOCK,
)
from .test_users import (
    BOOTSTRAP_MANAGER_HEADERS,
    CARE_HEADERS,
    COMPLIANCE_HEADERS,
    DISPATCHER_HEADERS,
    SECOND_COMPLIANCE_HEADERS,
    make_driver_headers,
    make_manager_headers,
)

# An off-peak planned departure comfortably inside the shared insurance window.
DEFAULT_DEPART_AT = "2026-08-05T10:00:00Z"
# A dispute-grant expiry comfortably ahead of the default working clock.
DEFAULT_GRANTED_UNTIL = "2026-08-06T00:00:00Z"


# --- Clock --------------------------------------------------------------------


def set_clock(current_utc: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the server-owned logical clock that every instant in the system reads."""
    return get_success_data(
        api_client.set_clock(current_utc, headers or DISPATCHER_HEADERS), 200
    )


# --- Store --------------------------------------------------------------------


def register_store(**overrides) -> Dict[str, Any]:
    """Register a franchise store. Store registration accepts any non-empty caller
    identity; every later manager call must present the store's own identifier."""
    return get_success_data(
        api_client.create_store(f.create_store_payload(**overrides), BOOTSTRAP_MANAGER_HEADERS),
        201,
    )


def read_store(store_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a store, which is the call that hands back a fresh expected store version."""
    return get_success_data(
        api_client.get_store(store_id, headers or make_manager_headers(store_id)), 200
    )


def edit_store(store_id: str, **overrides) -> Dict[str, Any]:
    """Edit store policy."""
    return get_success_data(
        api_client.update_store(
            store_id, f.update_store_payload(**overrides), make_manager_headers(store_id)
        ),
        200,
    )


def read_cash_reconciliation(store_id: str) -> Dict[str, Any]:
    """Read the computed proof of the store-wide cash conservation identity."""
    return get_success_data(
        api_client.get_cash_reconciliation(store_id, make_manager_headers(store_id)), 200
    )


# --- Delivery-area versions ---------------------------------------------------


def publish_zone_version(store_id: str, **overrides) -> Dict[str, Any]:
    """Publish a draft delivery-area version, reading the store first so the
    version guard carries the store's current version."""
    store = read_store(store_id)
    payload = f.create_zone_version_payload(store_id, store["version"], **overrides)
    return get_success_data(
        api_client.create_zone_version(payload, make_manager_headers(store_id)), 201
    )


def activate_zone_version(zone_version_id: str, store_id: str) -> Dict[str, Any]:
    """Put a draft delivery-area version in force."""
    return get_success_data(
        api_client.activate_zone_version(zone_version_id, make_manager_headers(store_id)), 200
    )


def publish_active_zone_version(store_id: str, **overrides) -> Dict[str, Any]:
    """Publish a delivery-area version and immediately put it in force."""
    draft = publish_zone_version(store_id, **overrides)
    return activate_zone_version(draft["id"], store_id)


def bootstrap(
    clock: str = DEFAULT_CLOCK,
    store_overrides: Optional[Dict[str, Any]] = None,
    zone_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Set the clock, register a store and put one delivery-area version in force.

    Returns the store as it read back at registration together with the active
    delivery-area version.
    """
    set_clock(clock)
    store = register_store(**(store_overrides or {}))
    zone_version = publish_active_zone_version(store["id"], **(zone_overrides or {}))
    return store, zone_version


# --- Service addresses and disputes -------------------------------------------


def add_address(store_id: str, key: str = "A", **overrides) -> Dict[str, Any]:
    """File and classify one address, naming it by its shared-geometry key."""
    latitude_micro, longitude_micro = ADDRESS_COORDS[key]
    payload = f.create_service_address_payload(
        store_id, latitude_micro, longitude_micro, **overrides
    )
    return get_success_data(api_client.create_service_address(payload, DISPATCHER_HEADERS), 201)


def add_address_at(
    store_id: str, latitude_micro: int, longitude_micro: int, **overrides
) -> Dict[str, Any]:
    """File and classify one address at explicit coordinates."""
    payload = f.create_service_address_payload(
        store_id, latitude_micro, longitude_micro, **overrides
    )
    return get_success_data(api_client.create_service_address(payload, DISPATCHER_HEADERS), 201)


def read_address(service_address_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read an address, whose effective zone state is re-derived on every read."""
    return get_success_data(
        api_client.get_service_address(service_address_id, headers or DISPATCHER_HEADERS), 200
    )


def open_dispute(service_address_id: str, **overrides) -> Dict[str, Any]:
    """Open an edge-address dispute on behalf of the customer."""
    payload = f.create_address_dispute_payload(service_address_id, **overrides)
    return get_success_data(api_client.create_address_dispute(payload, CARE_HEADERS), 201)


def review_dispute(
    address_dispute_id: str,
    action: str,
    store_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Drive one step of the dispute cycle. Review, information request, grant and
    deny are manager acts; withdrawal belongs to the care agent."""
    if headers is None:
        headers = CARE_HEADERS if action == "WITHDRAW" else make_manager_headers(store_id)
    payload = f.review_dispute_payload(action, **overrides)
    return get_success_data(
        api_client.review_address_dispute(address_dispute_id, payload, headers), 200
    )


def grant_dispute(
    service_address_id: str,
    store_id: str,
    granted_until: str = DEFAULT_GRANTED_UNTIL,
    **overrides,
) -> Dict[str, Any]:
    """Walk an address dispute all the way to a grant, which is what puts an
    override on the disputed address. A grant demands a granted_until strictly
    later than the logical clock."""
    dispute = open_dispute(service_address_id)
    review_dispute(dispute["id"], "START_REVIEW", store_id)
    return review_dispute(
        dispute["id"], "GRANT", store_id, granted_until=granted_until, **overrides
    )


# --- Drivers ------------------------------------------------------------------


def hire_driver(store_id: str, **overrides) -> Dict[str, Any]:
    """Hire a driver, who begins as an applicant with no checks on file."""
    payload = f.create_driver_payload(store_id, **overrides)
    return get_success_data(
        api_client.create_driver(payload, make_manager_headers(store_id)), 201
    )


def read_driver(driver_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a driver, the call that hands back a usable expected driver version
    alongside every re-derived driver figure."""
    return get_success_data(
        api_client.get_driver(driver_id, headers or COMPLIANCE_HEADERS), 200
    )


def record_mvr_check(
    driver_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    """Record a motor-vehicle-record pull, an immutable audit record."""
    payload = f.create_mvr_check_payload(**overrides)
    return get_success_data(
        api_client.create_mvr_check(driver_id, payload, headers or COMPLIANCE_HEADERS), 201
    )


def file_insurance(
    driver_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    """File a certificate of insurance, re-reading the driver first so the version
    guard carries the driver's current version."""
    driver = read_driver(driver_id)
    payload = f.create_insurance_verification_payload(driver["version"], **overrides)
    return get_success_data(
        api_client.create_insurance_verification(
            driver_id, payload, headers or COMPLIANCE_HEADERS
        ),
        201,
    )


def sign_decision(
    driver_id: str, decision: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    """Sign a qualification decision on a driver."""
    payload = f.qualification_decision_payload(decision, **overrides)
    return get_success_data(
        api_client.create_qualification_decision(
            driver_id, payload, headers or SECOND_COMPLIANCE_HEADERS
        ),
        201,
    )


def add_qualified_driver(store_id: str, **overrides) -> Dict[str, Any]:
    """Hire a driver and carry them all the way to qualified.

    The record pull is signed by one officer and the qualification decision by a
    different one, because the officer who pulled the record may not sign the
    decision that relies on it.
    """
    mvr_overrides = overrides.pop("mvr_overrides", {})
    insurance_overrides = overrides.pop("insurance_overrides", {})
    driver = hire_driver(store_id, **overrides)
    record_mvr_check(driver["id"], COMPLIANCE_HEADERS, **mvr_overrides)
    file_insurance(driver["id"], COMPLIANCE_HEADERS, **insurance_overrides)
    sign_decision(driver["id"], "QUALIFY", SECOND_COMPLIANCE_HEADERS)
    return read_driver(driver["id"])


# --- Reimbursement schedules --------------------------------------------------


def add_cost_model(store_id: str, **overrides) -> Dict[str, Any]:
    """Publish a reimbursement schedule for one vehicle class."""
    payload = f.create_vehicle_cost_model_payload(store_id, **overrides)
    return get_success_data(
        api_client.create_vehicle_cost_model(payload, make_manager_headers(store_id)), 201
    )


# --- Safe drops ---------------------------------------------------------------


def record_safe_drop(driver_id: str, amount_cents: int, **overrides) -> Dict[str, Any]:
    """Move cash from the driver's pouch into the store safe."""
    payload = f.create_safe_drop_payload(amount_cents, **overrides)
    return get_success_data(
        api_client.create_safe_drop(driver_id, payload, make_driver_headers(driver_id)), 201
    )


def void_safe_drop(safe_drop_id: str, store_id: str, **overrides) -> Dict[str, Any]:
    """Reverse a mis-keyed drop as the exact compensating inverse of the drop."""
    payload = f.void_safe_drop_payload(**overrides)
    return get_success_data(
        api_client.void_safe_drop(safe_drop_id, payload, make_manager_headers(store_id)), 200
    )


# --- Orders -------------------------------------------------------------------


def place_order(store_id: str, service_address_id: str, **overrides) -> Dict[str, Any]:
    """Take a delivery order, which prices itself from the address snapshot."""
    payload = f.create_order_payload(store_id, service_address_id, **overrides)
    return get_success_data(api_client.create_order(payload, DISPATCHER_HEADERS), 201)


def read_order(order_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read an order with both state dimensions and every computed figure."""
    return get_success_data(api_client.get_order(order_id, headers or DISPATCHER_HEADERS), 200)


def decide_zone(order_id: str, action: str, **overrides) -> Dict[str, Any]:
    """Disposition an order against the delivery area."""
    payload = f.zone_decision_payload(action, **overrides)
    return get_success_data(api_client.zone_decision(order_id, payload, DISPATCHER_HEADERS), 200)


def disclose_fee(
    order: Dict[str, Any],
    disclosed_fee_cents: Optional[int] = None,
    disclosed_tip_cents: Optional[int] = None,
    driver_tip_notice_given: bool = True,
) -> Dict[str, Any]:
    """Record the fee-versus-tip disclosure. Left to its defaults the quote matches
    the order exactly, which is what makes the disclosure accurate."""
    if disclosed_fee_cents is None:
        disclosed_fee_cents = order["delivery_fee_cents"]
    if disclosed_tip_cents is None:
        disclosed_tip_cents = order["tip_cents"]
    payload = f.disclose_fee_payload(
        disclosed_fee_cents, disclosed_tip_cents, driver_tip_notice_given
    )
    return get_success_data(api_client.disclose_fee(order["id"], payload, DISPATCHER_HEADERS), 200)


def produce(order_id: str, action: str) -> Dict[str, Any]:
    """Drive one make-line step: production start or ready."""
    return get_success_data(
        api_client.production(order_id, f.production_payload(action), DISPATCHER_HEADERS), 200
    )


def queue_remake(order_id: str, store_id: str, reason: str = "LATE") -> Dict[str, Any]:
    """Queue a remake on a delivered order."""
    return get_success_data(
        api_client.remake_order(order_id, f.remake_payload(reason), make_manager_headers(store_id)),
        200,
    )


def add_ready_order(
    store_id: str, service_address_id: str, disclose: bool = True, **overrides
) -> Dict[str, Any]:
    """Take an order and walk it to ready, disclosing the fee on the way.

    Ready with a disclosed settlement dimension is exactly the shape a route
    builder is looking for, since disclosure gates the commitment rather than
    the delivery.
    """
    order = place_order(store_id, service_address_id, **overrides)
    decide_zone(order["id"], "CLEAR")
    if disclose:
        disclose_fee(order)
    produce(order["id"], "START")
    produce(order["id"], "READY")
    return read_order(order["id"])


# --- Routes -------------------------------------------------------------------


def open_dispatch(
    driver_id: str, planned_depart_at: str = DEFAULT_DEPART_AT, **overrides
) -> Dict[str, Any]:
    """Open an empty draft route for a driver at a planned departure instant."""
    payload = f.create_dispatch_payload(driver_id, planned_depart_at, **overrides)
    return get_success_data(api_client.create_dispatch(payload, DISPATCHER_HEADERS), 201)


def stack_stop(
    dispatch_id: str, order_id: str, hot_bag_slots: Optional[int] = None
) -> Dict[str, Any]:
    """Stack a ready order onto a draft or stacked route."""
    payload = f.create_dispatch_stop_payload(order_id, hot_bag_slots)
    return get_success_data(
        api_client.create_dispatch_stop(dispatch_id, payload, DISPATCHER_HEADERS), 201
    )


def unstack_stop(dispatch_id: str, dispatch_stop_id: str) -> Dict[str, Any]:
    """Un-stack a pending stop, which answers with the parent route."""
    return get_success_data(
        api_client.delete_dispatch_stop(dispatch_id, dispatch_stop_id, DISPATCHER_HEADERS), 200
    )


def lock_route(dispatch_id: str) -> Dict[str, Any]:
    """Commit the route: price it and reserve the driver and the bags."""
    return get_success_data(api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS), 200)


def unlock_route(dispatch_id: str) -> Dict[str, Any]:
    """Release a committed route back to stacked, clearing everything the
    commitment computed."""
    return get_success_data(api_client.unlock_dispatch(dispatch_id, DISPATCHER_HEADERS), 200)


def depart_route(dispatch_id: str, driver_id: str) -> Dict[str, Any]:
    """Send the driver out of the door. Departure is the driver's own act."""
    return get_success_data(
        api_client.depart_dispatch(dispatch_id, make_driver_headers(driver_id)), 200
    )


def arrive_at_door(
    dispatch_id: str,
    dispatch_stop_id: str,
    driver_id: str,
    actual_miles: Optional[float] = None,
    cash_collected_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Record the handoff at one door."""
    payload = f.door_arrival_payload(actual_miles, cash_collected_cents)
    return get_success_data(
        api_client.door_arrival(
            dispatch_id, dispatch_stop_id, payload, make_driver_headers(driver_id)
        ),
        200,
    )


def check_in_route(dispatch_id: str, driver_id: str) -> Dict[str, Any]:
    """Check the route back in, which frees the store's bag reservation."""
    return get_success_data(
        api_client.return_dispatch(dispatch_id, make_driver_headers(driver_id)), 200
    )


def settle_route(dispatch_id: str, store_id: str) -> Dict[str, Any]:
    """Run payroll on a route that has been checked in."""
    return get_success_data(
        api_client.settle_dispatch(dispatch_id, make_manager_headers(store_id)), 200
    )


def recall_route(dispatch_id: str, **overrides) -> Dict[str, Any]:
    """Abort a route. A recall pays nothing."""
    return get_success_data(
        api_client.recall_dispatch(dispatch_id, f.recall_payload(**overrides), DISPATCHER_HEADERS),
        200,
    )


def read_dispatch(dispatch_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read a route with its stop count, committed slots and every figure."""
    return get_success_data(
        api_client.get_dispatch(dispatch_id, headers or DISPATCHER_HEADERS), 200
    )


def read_stop(dispatch_stop_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Read one stop with its sequence, planned and actual miles, and cash taken."""
    return get_success_data(
        api_client.get_dispatch_stop(dispatch_stop_id, headers or DISPATCHER_HEADERS), 200
    )


def list_route_stops(dispatch_id: str, headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """List a route's stops, which walks the route in sequence ascending."""
    from prd_bench_local_runner.testing import validate_paginated

    response = api_client.list_dispatch_stops(
        headers or DISPATCHER_HEADERS, {"dispatch_id": dispatch_id, "limit": 100}
    )
    data, _meta = validate_paginated(response)
    return data


def list_route_lines(dispatch_id: str, headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """List a route's reimbursement ledger lines."""
    from prd_bench_local_runner.testing import validate_paginated

    response = api_client.list_reimbursement_lines(
        headers or COMPLIANCE_HEADERS, {"dispatch_id": dispatch_id, "limit": 100}
    )
    data, _meta = validate_paginated(response)
    return data


# --- Service recovery ---------------------------------------------------------


def log_complaint(order_id: str, category: str = "LATE", **overrides) -> Dict[str, Any]:
    """Log a customer complaint against an order."""
    payload = f.create_complaint_payload(order_id, category, **overrides)
    return get_success_data(api_client.create_complaint(payload, CARE_HEADERS), 201)


def propose_remedy(complaint_id: str) -> Dict[str, Any]:
    """Size the goodwill credit under the remedy formula."""
    return get_success_data(api_client.propose_remedy(complaint_id, CARE_HEADERS), 200)


def resolve_complaint(complaint_id: str, action: str, store_id: str, **overrides) -> Dict[str, Any]:
    """Resolve a complaint: approve, reject back to open, or dismiss."""
    payload = f.resolve_complaint_payload(action, **overrides)
    return get_success_data(
        api_client.resolve_complaint(complaint_id, payload, make_manager_headers(store_id)), 200
    )


# --- Composite worlds ---------------------------------------------------------


def setup_operational_store(
    clock: str = DEFAULT_CLOCK,
    address_keys: Sequence[str] = ("A",),
    store_overrides: Optional[Dict[str, Any]] = None,
    zone_overrides: Optional[Dict[str, Any]] = None,
    cost_model_overrides: Optional[Dict[str, Any]] = None,
    driver_overrides: Optional[Dict[str, Any]] = None,
    with_cost_model: bool = True,
    with_driver: bool = True,
) -> Dict[str, Any]:
    """A store that can actually run a delivery: a delivery-area version in force,
    a reimbursement schedule for the driver's vehicle class, a qualified driver and
    a set of classified addresses.

    The returned mapping carries ``store``, ``zone_version``, ``cost_model``,
    ``driver``, ``addresses`` (keyed by shared-geometry key) and the two identity
    header sets a scenario needs most often.
    """
    store, zone_version = bootstrap(clock, store_overrides, zone_overrides)
    store_id = store["id"]
    cost_model = add_cost_model(store_id, **(cost_model_overrides or {})) if with_cost_model else None
    driver = add_qualified_driver(store_id, **(driver_overrides or {})) if with_driver else None
    addresses = {key: add_address(store_id, key) for key in dict.fromkeys(address_keys)}
    return {
        "store": read_store(store_id),
        "zone_version": zone_version,
        "cost_model": cost_model,
        "driver": driver,
        "addresses": addresses,
        "manager_headers": make_manager_headers(store_id),
        "driver_headers": make_driver_headers(driver["id"]) if driver else None,
    }


def _per_stop_overrides(
    order_overrides: Any, count: int
) -> List[Dict[str, Any]]:
    """Normalise per-order overrides into one mapping per stop."""
    if order_overrides is None:
        return [{} for _ in range(count)]
    if isinstance(order_overrides, dict):
        return [dict(order_overrides) for _ in range(count)]
    normalised = [dict(entry or {}) for entry in order_overrides]
    assert len(normalised) == count, "one override mapping per stop is required"
    return normalised


def setup_route(
    stage: str = "LOCKED",
    stop_keys: Sequence[str] = ("A",),
    world: Optional[Dict[str, Any]] = None,
    planned_depart_at: str = DEFAULT_DEPART_AT,
    hot_bag_slots: Optional[Sequence[Optional[int]]] = None,
    order_overrides: Any = None,
    actual_miles: Optional[Sequence[Optional[float]]] = None,
    disclose: bool = True,
    **world_kwargs,
) -> Dict[str, Any]:
    """Build a route and drive it to the requested stage.

    ``stage`` is one of ``STACKED``, ``LOCKED``, ``EN_ROUTE``, ``DELIVERED``,
    ``RETURNED`` or ``SETTLED``. One order is taken per entry in ``stop_keys``, so
    repeating a key stacks two stops on the same address. The returned mapping
    extends the operational-store mapping with ``orders``, ``dispatch`` and
    ``stops``.
    """
    stages = ("STACKED", "LOCKED", "EN_ROUTE", "DELIVERED", "RETURNED", "SETTLED")
    assert stage in stages, f"unknown stage {stage}"
    reach = stages.index(stage)

    if world is None:
        world = setup_operational_store(address_keys=tuple(stop_keys), **world_kwargs)
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]

    overrides = _per_stop_overrides(order_overrides, len(stop_keys))
    orders: List[Dict[str, Any]] = []
    for key, extra in zip(stop_keys, overrides):
        address = world["addresses"].get(key) or add_address(store_id, key)
        world["addresses"][key] = address
        orders.append(add_ready_order(store_id, address["id"], disclose=disclose, **extra))

    dispatch = open_dispatch(driver_id, planned_depart_at)
    stops: List[Dict[str, Any]] = []
    for index, order in enumerate(orders):
        slots = hot_bag_slots[index] if hot_bag_slots is not None else None
        stops.append(stack_stop(dispatch["id"], order["id"], slots))

    result = dict(world)
    result.update({"orders": orders, "dispatch": read_dispatch(dispatch["id"]), "stops": stops})
    if reach == 0:
        return result

    dispatch = lock_route(dispatch["id"])
    result["dispatch"] = dispatch
    if reach == 1:
        return result

    dispatch = depart_route(dispatch["id"], driver_id)
    result["dispatch"] = dispatch
    if reach == 2:
        return result

    for index, stop in enumerate(stops):
        order = orders[index]
        miles = actual_miles[index] if actual_miles is not None else stop["planned_miles"]
        cash = order["total_charge_cents"] if order["payment_method"] == "CASH" else None
        arrive_at_door(dispatch["id"], stop["id"], driver_id, miles, cash)
    result["stops"] = list_route_stops(dispatch["id"])
    result["orders"] = [read_order(order["id"]) for order in orders]
    result["dispatch"] = read_dispatch(dispatch["id"])
    if reach == 3:
        return result

    result["dispatch"] = check_in_route(dispatch["id"], driver_id)
    if reach == 4:
        return result

    result["dispatch"] = settle_route(dispatch["id"], store_id)
    result["orders"] = [read_order(order["id"]) for order in orders]
    result["stops"] = list_route_stops(dispatch["id"])
    result["driver"] = read_driver(driver_id)
    return result


def setup_stacked_route(stop_keys: Sequence[str] = ("A",), **kwargs) -> Dict[str, Any]:
    """A route holding stops but not yet committed."""
    return setup_route("STACKED", stop_keys, **kwargs)


def setup_locked_route(stop_keys: Sequence[str] = ("A",), **kwargs) -> Dict[str, Any]:
    """A committed route: priced, with the driver and the bags reserved."""
    return setup_route("LOCKED", stop_keys, **kwargs)


def setup_departed_route(stop_keys: Sequence[str] = ("A",), **kwargs) -> Dict[str, Any]:
    """A route whose driver is out of the door."""
    return setup_route("EN_ROUTE", stop_keys, **kwargs)


def setup_delivered_route(stop_keys: Sequence[str] = ("A",), **kwargs) -> Dict[str, Any]:
    """A route where every door has been knocked on and every stop is delivered."""
    return setup_route("DELIVERED", stop_keys, **kwargs)


def setup_returned_route(stop_keys: Sequence[str] = ("A",), **kwargs) -> Dict[str, Any]:
    """A route checked back in and awaiting payroll."""
    return setup_route("RETURNED", stop_keys, **kwargs)


def setup_settled_route(stop_keys: Sequence[str] = ("A",), **kwargs) -> Dict[str, Any]:
    """A route that has been through payroll, with accrued ledger lines on file."""
    return setup_route("SETTLED", stop_keys, **kwargs)


def setup_delivered_order(**kwargs) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A single delivered order together with the world that produced it, which is
    the precondition a remake or a complaint needs."""
    world = setup_delivered_route(("A",), **kwargs)
    return world["orders"][0], world
