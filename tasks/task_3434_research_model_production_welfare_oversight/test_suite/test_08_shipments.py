"""Shipments: per-line box accounting, half-open vehicle windows, the
sanitization chronology, the vehicle certification floor, the ALLOCATED-order
gate, and the facility-registration departure gate.
"""
import math

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    allocate_order_to_cohort,
    api_client,
    assert_shipment,
    compute_expected_box_count,
    create_active_customer,
    create_shipment_for_order,
    create_shipment_payload,
    find_shipment_in_order,
    list_allocations_for_order,
    read_order,
    setup_allocated_order,
    setup_colony_with_cohorts,
    setup_production_site,
    setup_scheduled_order,
    setup_sourcing_order,
    create_order_submitted,
    source_order,
    transition_shipment,
    validate_error,
    validate_success,
)

_ADMIN = TEST_USERS["admin_headers"]
_LOGI = TEST_USERS["logistics_headers"]
_VET = TEST_USERS["veterinarian_headers"]
_FM = TEST_USERS["facility_manager_headers"]


def _three_allocated_orders():
    """One 45M/45F HOLD cohort feeding three fully allocated 5M/5F orders."""
    site = setup_production_site()
    bundle = setup_colony_with_cohorts(
        site, cohorts=[{"count_male": 45, "count_female": 45, "hold": True}]
    )
    cohort = bundle["cohorts"][0]
    customer = create_active_customer()
    orders = []
    for _ in range(3):
        order = create_order_submitted(
            customer, site["strain"]["id"], quantity_male=5, quantity_female=5
        )
        order = source_order(order)
        _alloc, order = allocate_order_to_cohort(order, cohort, 5, 5)
        assert order["status"] == "ALLOCATED"
        orders.append(order)
    return {"site": site, "cohort": cohort, "customer": customer, "orders": orders}


def test_shipment_box_count_per_line_ceil_then_sum():
    """PRD Section 3.8: "Each such allocation-and-sex line contributes the
    ceiling of its quantity divided by its per-box capacity, and the
    shipment's `box_count` is the sum of those per-line ceilings."

    Design: Difficulty/combinatorial_formula/shipment_box_count_per_line_ceil_then_sum
    """
    bundle = setup_allocated_order(
        quantity_male=17, quantity_female=3,
        cohorts=[
            {"count_male": 10, "count_female": 10, "hold": True},
            {"count_male": 10, "count_female": 10, "hold": True},
        ],
        allocations=[(0, 7, 3), (1, 10, 0)],
    )
    shipment, order = create_shipment_for_order(bundle["order"])
    # 20.0 g is the standard tier (6 per box): ceil(7/6)+ceil(3/6) on the
    # first allocation and ceil(10/6) on the second -> 3 + 2 = 5 boxes.
    expected = compute_expected_box_count([(7, 20.0), (3, 20.0), (10, 20.0)])
    assert expected == 5
    assert shipment["box_count"] == expected
    assert shipment["status"] == "PLANNED"
    assert order["status"] == "SCHEDULED"
    assert_shipment(shipment)


def test_shipment_box_count_rejects_sum_then_ceil():
    """PRD Section 3.8: "The rounding order is pinned — ceiling per line
    first, then summation — so pooling animals across lines before applying
    one ceiling is a different algorithm and yields a non-conforming, smaller
    box count."

    Design: Difficulty/combinatorial_formula/shipment_box_count_per_line_ceil_then_sum
    """
    bundle = setup_allocated_order(
        quantity_male=17, quantity_female=3,
        cohorts=[
            {"count_male": 10, "count_female": 10, "hold": True},
            {"count_male": 10, "count_female": 10, "hold": True},
        ],
        allocations=[(0, 7, 3), (1, 10, 0)],
    )
    shipment, _order = create_shipment_for_order(bundle["order"])
    # The rejected sum-then-ceil algorithm would give ceil(20/6) = 4 boxes.
    assert math.ceil(20 / 6) == 4
    assert shipment["box_count"] == 5
    assert shipment["box_count"] != math.ceil(20 / 6)

    allocations = list_allocations_for_order(bundle["order"]["id"])
    assert len(allocations) == 2
    assert all(a["status"] == "RESERVED" for a in allocations)


def test_vehicle_window_adjacent_departure_is_legal():
    """PRD Section 3.8: "the half-open transit window from `departure_date`
    inclusive to `planned_arrival_date` exclusive must not overlap the window
    of any other non-`CANCELLED` shipment on the same `vehicle_code` standing
    in `PLANNED`, `LOADED`, or `IN_TRANSIT`; a departure scheduled exactly at
    a predecessor's planned arrival is allowed".

    Design: Difficulty/resource_temporal_overlap/vehicle_transit_window_half_open_overlap
    """
    ctx = _three_allocated_orders()
    o1, o2, _o3 = ctx["orders"]

    # Shipment 1 occupies [2026-10-10T08:00, 2026-10-12T08:00): exactly 48h.
    shipment1, o1 = create_shipment_for_order(
        o1, vehicle_code="VH1",
        sanitized_at="2026-10-10T06:00:00Z",
        departure_date="2026-10-10T08:00:00Z",
        planned_arrival_date="2026-10-12T08:00:00Z",
    )
    assert shipment1["status"] == "PLANNED"

    # Shipment 2 departs exactly at shipment 1's planned arrival: adjacency
    # is legal under half-open windows.
    shipment2, o2 = create_shipment_for_order(
        o2, vehicle_code="VH1",
        sanitized_at="2026-10-12T08:00:00Z",
        departure_date="2026-10-12T08:00:00Z",
        planned_arrival_date="2026-10-13T08:00:00Z",
    )
    assert shipment2["status"] == "PLANNED"


def test_vehicle_window_true_overlap_rejected():
    """PRD Section 3.8: "a departure scheduled exactly at a predecessor's
    planned arrival is allowed, but any true overlap is
    `ERR_VEHICLE_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vehicle_transit_window_half_open_overlap
    """
    ctx = _three_allocated_orders()
    o1, o2, o3 = ctx["orders"]

    _s1, o1 = create_shipment_for_order(
        o1, vehicle_code="VH1",
        sanitized_at="2026-10-10T06:00:00Z",
        departure_date="2026-10-10T08:00:00Z",
        planned_arrival_date="2026-10-12T08:00:00Z",
    )
    _s2, o2 = create_shipment_for_order(
        o2, vehicle_code="VH1",
        sanitized_at="2026-10-12T08:00:00Z",
        departure_date="2026-10-12T08:00:00Z",
        planned_arrival_date="2026-10-13T08:00:00Z",
    )

    # [2026-10-12T12:00, 2026-10-13T06:00) starts 4h inside shipment 2's
    # window [2026-10-12T08:00, 2026-10-13T08:00): a true overlap.
    payload = create_shipment_payload(
        o3["id"], o3["version"], vehicle_code="VH1",
        sanitized_at="2026-10-12T09:00:00Z",
        departure_date="2026-10-12T12:00:00Z",
        planned_arrival_date="2026-10-13T06:00:00Z",
    )
    resp = api_client.create_shipment(payload, _LOGI)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_SCHEDULE_CONFLICT)


def test_departure_blocked_while_facility_under_inspection():
    """PRD Section 3.8: "Departure moves it from `LOADED` to `IN_TRANSIT` and
    is gated on the source facility's standing: the facility housing the
    source cohorts' rooms must hold `registration_status` `REGISTERED`, else
    `ERR_FACILITY_NOT_REGISTERED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/shipment_departure_gated_by_facility_registration
    """
    bundle = setup_scheduled_order()
    shipment = bundle["shipment"]
    facility = bundle["site"]["facility"]

    transition_shipment(shipment["id"], "LOADED", _LOGI)
    resp = api_client.transition_facility(
        facility["id"], {"target_state": "UNDER_INSPECTION"}, _ADMIN
    )
    validate_success(resp)

    resp = api_client.transition_shipment(
        shipment["id"], {"target_state": "IN_TRANSIT"}, _LOGI
    )
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_REGISTERED)
    shipment = find_shipment_in_order(bundle["order"]["id"], shipment["id"])
    assert shipment["status"] == "LOADED"


def test_rejected_departure_leaves_order_and_allocations_untouched():
    """PRD Section 3.8: "Departure is the consumption point: every `RESERVED`
    allocation of the order transitions to `CONSUMED`" — a rejected departure
    is not a consumption point, so the schedule and reservations stand.

    Design: Difficulty/cross_entity_state_dependency/shipment_departure_gated_by_facility_registration
    """
    bundle = setup_scheduled_order()
    shipment = bundle["shipment"]
    facility = bundle["site"]["facility"]

    transition_shipment(shipment["id"], "LOADED", _LOGI)
    validate_success(
        api_client.transition_facility(
            facility["id"], {"target_state": "UNDER_INSPECTION"}, _ADMIN
        )
    )
    validate_error(
        api_client.transition_shipment(
            shipment["id"], {"target_state": "IN_TRANSIT"}, _LOGI
        ),
        ApiErrorId.ERR_FACILITY_NOT_REGISTERED,
    )

    order = read_order(bundle["order"]["id"])
    assert order["status"] == "SCHEDULED"
    allocations = list_allocations_for_order(order["id"])
    assert len(allocations) == 1
    assert allocations[0]["status"] == "RESERVED"


def test_transit_duration_over_limit_rejected():
    """PRD Section 3.8: "`departure_date` must not precede the current logical
    clock, the difference between `planned_arrival_date` and `departure_date`
    must not exceed 48 hours — the platform's maximum transit duration — and
    `planned_arrival_date` must fall on or before the order's
    `required_delivery_date`; any violation is `ERR_TRANSIT_DURATION_EXCEEDED`
    (HTTP 422)."

    Design: Corner/calculations/transit_duration_over_limit_rejected
    """
    bundle = setup_allocated_order(
        quantity_male=2, quantity_female=2,
        order_overrides={
            "min_age_weeks": 4, "max_age_weeks": 7,
            "required_delivery_date": "2026-10-15T00:00:00Z",
        },
    )
    order = bundle["order"]
    # 48h01m of transit; the arrival still lands before the 2026-10-15
    # deadline, so only the duration leg fails.
    payload = create_shipment_payload(
        order["id"], order["version"],
        planned_arrival_date="2026-10-14T08:01:00Z",
    )
    resp = api_client.create_shipment(payload, _LOGI)
    validate_error(resp, ApiErrorId.ERR_TRANSIT_DURATION_EXCEEDED)


def test_vehicle_sanitization_chronology_violation():
    """PRD Section 3.8: "for every prior non-`CANCELLED` shipment on the same
    `vehicle_code` whose planned arrival falls at or before this departure,
    `sanitized_at` must be at or after that earlier shipment's
    `planned_arrival_date`, guaranteeing a fresh sanitization after the
    previous tour; a stale or mis-sequenced timestamp is
    `ERR_VEHICLE_NOT_SANITIZED` (HTTP 422)."

    Design: Corner/validations/vehicle_sanitization_chronology_violation
    """
    bundle = setup_allocated_order(quantity_male=2, quantity_female=2)
    order1 = bundle["order"]
    customer = bundle["customer"]
    cohort = bundle["cohorts"][0]
    site = bundle["site"]

    # Shipment 1 occupies [2026-10-10T08:00, 2026-10-12T08:00) on VH1.
    _shipment1, order1 = create_shipment_for_order(
        order1, vehicle_code="VH1",
        sanitized_at="2026-10-10T06:00:00Z",
        departure_date="2026-10-10T08:00:00Z",
        planned_arrival_date="2026-10-12T08:00:00Z",
    )

    order2 = create_order_submitted(
        customer, site["strain"]["id"], quantity_male=2, quantity_female=2
    )
    order2 = source_order(order2)
    _alloc, order2 = allocate_order_to_cohort(order2, cohort, 2, 2)

    # The successor departs after shipment 1's planned arrival, but its
    # sanitized_at predates that arrival: no fresh sanitization after the
    # previous tour.
    payload = create_shipment_payload(
        order2["id"], order2["version"], vehicle_code="VH1",
        sanitized_at="2026-10-10T06:00:00Z",
        departure_date="2026-10-12T10:00:00Z",
        planned_arrival_date="2026-10-13T08:00:00Z",
    )
    resp = api_client.create_shipment(payload, _LOGI)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_SANITIZED)


def test_vehicle_cert_below_order_health_floor():
    """PRD Section 3.8: "The vehicle's certification must match the cargo: a
    `vehicle_barrier_cert` rank below the order's `min_health_status` rank is
    rejected with `ERR_BARRIER_LEVEL_INSUFFICIENT` (HTTP 422)."

    Design: Corner/validations/vehicle_cert_below_order_health_floor
    """
    bundle = setup_allocated_order(
        quantity_male=2, quantity_female=2,
        order_overrides={"min_health_status": "VF"},
    )
    order = bundle["order"]
    payload = create_shipment_payload(
        order["id"], order["version"], vehicle_barrier_cert="MPF"
    )
    resp = api_client.create_shipment(payload, _LOGI)
    validate_error(resp, ApiErrorId.ERR_BARRIER_LEVEL_INSUFFICIENT)


def test_shipment_create_requires_allocated_order():
    """PRD Section 3.8: "Shipment creation requires the order to stand exactly
    in `ALLOCATED` — any other state, including `SOURCING` or `BACKORDERED`,
    is `ERR_ORDER_NOT_SOURCING` (HTTP 409)".

    Design: Corner/validations/shipment_create_requires_allocated_order
    """
    bundle = setup_sourcing_order(quantity_male=5, quantity_female=5)
    order = bundle["order"]
    assert order["status"] == "SOURCING"

    payload = create_shipment_payload(order["id"], order["version"])
    resp = api_client.create_shipment(payload, _LOGI)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SOURCING)
