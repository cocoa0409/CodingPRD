"""VIN registration: system defaults on the new vehicle, uniqueness and
pack-match cross-checks, role and OCC guards, the weekly ramp gate, and the
immediate visibility of the allocation cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_fresh_vehicle_defaults,
    create_confirmed_order,
    create_passed_module,
    create_supplier,
    create_vehicle_payload,
    make_fleet_manager_headers,
    make_vin,
    read_order,
    register_module,
    register_vehicle,
    register_vehicle_raw,
    set_logical_clock,
    setup_base_fleet,
    setup_customer_with_depot,
    transition_module,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLANNER = TEST_USERS["production_planner_headers"]
_INSPECTOR = TEST_USERS["quality_inspector_headers"]
_DISPATCHER = TEST_USERS["service_dispatcher_headers"]


def _module_by_id(api, supplier_id, module_id):
    rows, _meta = validate_paginated(api.list_supplier_battery_modules(supplier_id, _PLANNER))
    for row in rows:
        if row["id"] == module_id:
            return row
    raise AssertionError(f"module {module_id} not listed for supplier {supplier_id}")


def test_vehicle_readback_shows_system_defaults(api):
    """PRD section 3.6: "A freshly registered vehicle carries two parallel,
    independent state dimensions plus a telemetry profile. The delivery
    dimension starts at `ASSEMBLED`; the telematics dimension starts at
    `OFFLINE`. Its `software_version` begins at the `1.0.0` factory baseline,
    `software_hold` is false, `current_soh_pct` starts at 100.0,
    `battery_eol_status` is `NONE`, both end-of-life valuation fields
    (`eol_valuation_refurbish_cents`, `eol_valuation_recovery_cents`) are
    null, and `last_battery_report_at` is null until the first report."

    Design: Corner/entities/vehicle_readback_shows_system_defaults
    """
    fleet = setup_base_fleet(quantity=2)
    vehicle = validate_success(api.get_vehicle(fleet["vehicles"][0]["id"], _DISPATCHER), 200)
    assert_fresh_vehicle_defaults(vehicle)
    assert vehicle["vehicle_order_id"] == fleet["order"]["id"]
    assert vehicle["battery_module_id"] == fleet["modules"][0]["id"]


def test_duplicate_vin_rejected(api):
    """PRD section 3.5: a registration names "a globally unique `vin` (a
    duplicate anywhere in the fleet is `ERR_DUPLICATE_VIN`)".

    Design: Corner/validations/duplicate_vin_rejected
    """
    fleet = setup_base_fleet(quantity=2, register_count=1)
    order = fleet["order"]
    fresh_version = read_order(order["id"])["version"]
    resp = register_vehicle_raw(
        order["id"], fleet["modules"][1]["id"], make_vin(1), fresh_version
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VIN)
    module2 = _module_by_id(api, fleet["supplier"]["id"], fleet["modules"][1]["id"])
    assert module2["quality_status"] == "PASSED", "rejection happens before allocation"
    assert read_order(order["id"])["registered_count"] == 1


def test_module_pack_mismatch_rejected(api):
    """PRD section 3.5: "the module's `pack_kwh` must equal the order's
    `battery_pack_kwh` (`ERR_MODULE_PACK_MISMATCH`)".

    Design: Corner/validations/module_pack_mismatch_rejected
    """
    fleet = setup_base_fleet(quantity=2, register_count=0)
    order = fleet["order"]
    mod52 = create_passed_module(fleet["supplier"]["id"], module_serial="M-052", pack_kwh=52)
    resp = register_vehicle_raw(
        order["id"], mod52["id"], "VIN-ACME-052", read_order(order["id"])["version"]
    )
    validate_error(resp, ApiErrorId.ERR_MODULE_PACK_MISMATCH)
    assert _module_by_id(api, fleet["supplier"]["id"], mod52["id"])["quality_status"] == "PASSED"
    assert read_order(order["id"])["registered_count"] == 0


def test_quality_inspector_cannot_register_vehicle_forbidden(api):
    """PRD section 2.1: "A request whose role is not listed for the endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)"; the PRD section 4 routing
    table lists ProductionPlanner as the only authorized role for POST
    /evfleet/vehicles.

    Design: Corner/rbac/quality_inspector_cannot_register_vehicle_forbidden
    """
    fleet = setup_base_fleet(quantity=2, register_count=0)
    order = fleet["order"]
    payload = create_vehicle_payload(
        order["id"], fleet["modules"][0]["id"], "VIN-ACME-901", order["version"]
    )
    resp = api.create_vehicle(payload, _INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert read_order(order["id"])["registered_count"] == 0
    module1 = _module_by_id(api, fleet["supplier"]["id"], fleet["modules"][0]["id"])
    assert module1["quality_status"] == "PASSED"


def test_stale_order_version_rejected_on_vin_registration(api):
    """PRD section 2.6: "Registering a vehicle VIN requires
    `expected_vehicle_order_version` matching the target order's current
    `version`. The client's belief that a registration slot remains
    (`registered_count` versus `quantity`) is stale when the versions
    disagree, and the registration is refused." — the refusal is
    `ERR_STALE_VERSION` (HTTP 412).

    Design: Corner/validations/stale_order_version_rejected_on_vin_registration
    """
    fleet = setup_base_fleet(quantity=2, register_count=1)
    order = fleet["order"]  # CONFIRMED snapshot, version 3; now stale after registration 1
    resp = register_vehicle_raw(
        order["id"], fleet["modules"][1]["id"], make_vin(2), order["version"]
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    vehicle = register_vehicle(order, fleet["modules"][1]["id"], make_vin(2))
    assert vehicle["vin"] == make_vin(2)
    order_after = read_order(order["id"])
    assert order_after["registered_count"] == 2
    assert order_after["status"] == "FULFILLED"


def test_ramp_capacity_allows_eighth_and_rejects_ninth_registration(api):
    """PRD section 3.5: "The ramp gate is a shared production ceiling: the
    weekly capacity is 8 base units plus, summed over every supplier, 24 units
    for each supplier at tier `A`, 10 for each at `B`, and 0 for `C` or
    `UNAUDITED`. A registration is allowed only while the count of vehicles
    already registered in the current ISO week (Monday 00:00:00Z to the next
    Monday 00:00:00Z on the logical clock), across all customers' orders, is
    strictly below that capacity; when the count equals capacity the next
    registration is rejected with `ERR_RAMP_CAPACITY_EXCEEDED`."

    Design: Corner/calculations/ramp_capacity_allows_eighth_and_rejects_ninth_registration
    """
    fleet = setup_base_fleet(quantity=9, register_count=8)
    order = fleet["order"]
    resp = register_vehicle_raw(
        order["id"], fleet["modules"][8]["id"], make_vin(9), read_order(order["id"])["version"]
    )
    validate_error(resp, ApiErrorId.ERR_RAMP_CAPACITY_EXCEEDED)
    order_after = read_order(order["id"])
    assert order_after["registered_count"] == 8, "eight registrations filled the base-8 week"
    assert order_after["status"] == "IN_PRODUCTION", "8 < 9, not yet FULFILLED"
    module9 = _module_by_id(api, fleet["supplier"]["id"], fleet["modules"][8]["id"])
    assert module9["quality_status"] == "PASSED", "the rejected registration did not allocate"


def test_registration_side_effects_visible_immediately(api):
    """PRD section 1: "First, immediate consistency: every mutation and every
    cascade it triggers is visible in the same response, so a client never has
    to poll for side effects."; PRD section 3.5: "Each accepted registration
    cascades within the same response: the module moves `PASSED → ALLOCATED`,
    the order's `registered_count` increments by 1, and the order's `version`
    increments by 1."

    Design: Corner/consistency_model/registration_side_effects_visible_immediately
    """
    fleet = setup_base_fleet(quantity=2, register_count=0)
    order = fleet["order"]
    vehicle = register_vehicle(order, fleet["modules"][0]["id"], make_vin(1))
    module1 = _module_by_id(api, fleet["supplier"]["id"], fleet["modules"][0]["id"])
    assert module1["quality_status"] == "ALLOCATED", "module cascade visible in the very next read"
    order_after = read_order(order["id"])
    assert order_after["registered_count"] == 1
    assert order_after["status"] == "IN_PRODUCTION"
    assert order_after["version"] == order["version"] + 1
    assert vehicle["created_at"].startswith("2026-09-01T00:00:00"), (
        "created_at reads the logical clock's current instant"
    )


def _setup_order_with_in_qa_module():
    """Customer + depot + supplier + one module advanced only to IN_QA +
    a CONFIRMED quantity-2 order. Returns (supplier, module, order)."""
    customer, depot = setup_customer_with_depot()
    supplier = create_supplier()
    module = register_module(supplier["id"], module_serial="M-201")
    transition_module(module["id"], "IN_QA")
    order = create_confirmed_order(customer, depot, supplier)
    return customer, supplier, module, order


def test_vin_registration_blocked_while_module_in_qa(api):
    """PRD section 3.5: "Three cross-checks fire, in section 2.8 priority
    order: the module's `pack_kwh` must equal the order's `battery_pack_kwh`
    (`ERR_MODULE_PACK_MISMATCH`), the module must be `PASSED`
    (`ERR_MODULE_NOT_PASSED`)".

    Design: Difficulty/cross_entity_state_dependency/vin_registration_requires_passed_module
    """
    _customer, supplier, module, order = _setup_order_with_in_qa_module()
    resp = register_vehicle_raw(order["id"], module["id"], "VIN-ACME-801", order["version"])
    validate_error(resp, ApiErrorId.ERR_MODULE_NOT_PASSED)
    assert read_order(order["id"])["registered_count"] == 0
    assert _module_by_id(api, supplier["id"], module["id"])["quality_status"] == "IN_QA"


def test_vin_registration_succeeds_once_module_passed(api):
    """PRD section 3.5: "the module's `pack_kwh` must equal the order's
    `battery_pack_kwh` (`ERR_MODULE_PACK_MISMATCH`), the module must be
    `PASSED` (`ERR_MODULE_NOT_PASSED`), and the weekly ramp gate must have
    room." and "Each accepted registration cascades within the same response:
    the module moves `PASSED → ALLOCATED`".

    Design: Difficulty/cross_entity_state_dependency/vin_registration_requires_passed_module
    """
    _customer, supplier, module, order = _setup_order_with_in_qa_module()
    resp = register_vehicle_raw(order["id"], module["id"], "VIN-ACME-801", order["version"])
    validate_error(resp, ApiErrorId.ERR_MODULE_NOT_PASSED)
    transition_module(module["id"], "PASSED")
    vehicle = register_vehicle(order, module["id"], "VIN-ACME-801")
    assert vehicle["battery_module_id"] == module["id"]
    assert _module_by_id(api, supplier["id"], module["id"])["quality_status"] == "ALLOCATED"
