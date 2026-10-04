"""Validation precedence, bands 6-15: terminality, version currency and endorsement closure.

Three instances, one test each.  The first drives a repeat completion against a
terminal order, the second a stale endorsement create, and the third a release
that would leave a material endorsement in flight.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    complete_production_order_payload,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_order,
    create_production_order_payload,
    create_substitution_endorsement_payload,
    get_success_data,
    release_order,
    reserve_order,
    set_clock,
    setup_catalogue,
    start_production,
    complete_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def test_second_completion_of_a_terminal_order_is_rejected(api):
    """PRD §2.11: "Sixth, terminality: a resource that has already reached a
    terminal state accepts no further transitions, and an attempt is rejected
    with `ERR_ALREADY_TERMINAL` (HTTP 409); this check guards order completion,
    sale settlement and retrofit-program start."
    PRD §3.4: "An order that has already reached `COMPLETED` or `CANCELLED`
    accepts no further transition and is rejected with `ERR_ALREADY_TERMINAL`
    (HTTP 409)".

    The order is walked all the way to COMPLETED first, so the second completion
    is the only live failure and the completed quantity must not move.

    Design: Corner/validations/validation_p6_terminal_order_rejects_second_completion
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="FLT-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="FLT_LINE",
        wheelset_part_number="WS-310",
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=1,
        lead_time_days=5,
        include_coating=False,
        on_hand_qty=1000,
    )
    order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    reserve_order(order["id"])
    release_order(order["id"])
    start_production(order["id"], "FLT_LINE", window_start="2026-09-02", window_days=1)

    first = complete_order(
        order["id"], completed_qty=1, completion_date="2026-09-03"
    )
    assert first["status"] == "COMPLETED"
    assert first["completed_qty"] == 1

    repeat = api.complete_production_order(
        order["id"],
        complete_production_order_payload(
            completed_qty=1, completion_date="2026-09-03"
        ),
        PLANNER,
    )
    validate_error(repeat, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert repeat.status_code == 409

    after = get_success_data(api.get_production_order(order["id"], ADMIN))
    assert after["status"] == "COMPLETED", "the terminal state is unchanged"
    assert after["completed_qty"] == 1, "completed_qty does not move on the rejection"

    cars = get_success_data(
        api.list_lease_fleet_cars(ADMIN, {"production_order_id": order["id"]})
    )
    assert cars == [], "the rejected call created no additional fleet car"


def test_endorsement_created_with_a_stale_order_version_is_rejected(api):
    """PRD §2.7: "The second guard protects substitution-endorsement creation. A
    `POST /substitution-endorsements` request must carry
    `expected_production_order_version`, holding the client's last observed
    `version` of that order. If the order's version has advanced since the client
    read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.11: "Seventh, version currency: a supplied expected version must equal
    the parent's current `version`, and a mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412); this check guards amendment drafting and
    substitution-endorsement creation."
    PRD §3.3: "A successful create starts the endorsement in `PENDING`, supersedes
    any earlier `PENDING` endorsement for the same original component on that
    order, and increments the production order's `version`."

    The stale value is one below the live version rather than a literal, so the
    test survives any cascade that bumps the order's version.

    Design: Corner/validations/validation_p7_stale_production_order_version_returns_stale_version
    """
    set_clock("2026-09-01T00:00:00Z")
    catalogue = setup_catalogue(
        model_code="FLT-100",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="FLT_LINE",
        wheelset_part_number="WS-310",
        wheelset_unit_cost_cents=1000,
        wheelset_qty_per_car=1,
        lead_time_days=5,
        include_coating=False,
        on_hand_qty=1000,
    )
    substitute = validate_success(
        api.create_component(
            create_component_payload(
                part_number="WS-320",
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=5,
                on_hand_qty=1000,
            ),
            SUPPLY,
        ),
        expected_status=201,
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
    reserve_order(order["id"])
    live = get_success_data(api.get_production_order(order["id"], ADMIN))
    live_version = live["version"]

    planner_one = build_user_headers("planner_1", "ProductionPlanner")
    base = {
        "production_order_id": order["id"],
        "original_component_id": catalogue["wheelset"]["id"],
        "substitute_component_id": substitute["id"],
        "substitute_qty_per_car": 1,
        "decides_material": False,
    }

    stale = api.create_substitution_endorsement(
        create_substitution_endorsement_payload(
            **base, expected_production_order_version=live_version - 1
        ),
        planner_one,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    accepted = api.create_substitution_endorsement(
        create_substitution_endorsement_payload(
            **base, expected_production_order_version=live_version
        ),
        planner_one,
    )
    created = validate_success(accepted, expected_status=201)
    assert created["status"] == "PENDING", (
        "only the observed version differs between the two writes"
    )

    rows = validate_success(
        api.list_substitution_endorsements(
            ADMIN, {"production_order_id": order["id"]}
        )
    )
    assert len(rows) == 1, "the rejected call persisted no endorsement"


def test_approved_material_endorsement_blocks_release(api):
    """PRD §3.3: "One precondition couples the endorsements on an order
    together: any endorsement on the same order that is `APPROVED` and has
    `decides_material` true must be applied in the same release request, and a
    release that would leave a material endorsement in flight is rejected with
    `ERR_MATERIAL_ENDORSEMENT_PENDING` (HTTP 409)."
    PRD §3.4: "A release that would leave a material endorsement in flight is
    rejected with `ERR_MATERIAL_ENDORSEMENT_PENDING` (HTTP 409)".
    PRD §3.3: "Approval is a second-person action and belongs to a
    `LeaseAdministrator`. It is legal only from `PENDING`, and it carries a
    segregation-of-duties precondition: the acting `X-User-ID` must not be the
    `X-User-ID` that created the endorsement".

    Every other release precondition holds — the stock is committed and the
    window is feasible — so the endorsement is the only blocker.

    Design: Corner/validations/validation_p15_approved_material_endorsement_blocks_release
    """
    set_clock("2026-09-01T00:00:00Z")
    car_type = validate_success(
        api.create_car_type(
            create_car_type_payload(
                model_code="E15-100",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=15,
                line_count_family="E15_LINE",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    original = validate_success(
        api.create_component(
            create_component_payload(
                part_number="WS-E15-A",
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=5,
                on_hand_qty=100,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    substitute = validate_success(
        api.create_component(
            create_component_payload(
                part_number="CS-E15-B",
                component_class="CASTING",
                unit_cost_cents=2000,
                lead_time_days=5,
                on_hand_qty=100,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    bom_row = validate_success(
        api.create_car_type_component_requirement(
            create_car_type_component_requirement_payload(
                car_type_id=car_type["id"],
                component_id=original["id"],
                qty_per_car=1,
            ),
            PLANNER,
        ),
        expected_status=201,
    )

    order = validate_success(
        api.create_production_order(
            create_production_order_payload(
                car_type_id=car_type["id"],
                quantity=1,
                planned_shop_days=1,
                disposition="SOLD",
                priority_rank=1,
                order_date="2026-09-01",
                required_delivery_date="2026-09-20",
            ),
            PLANNER,
        ),
        expected_status=201,
    )

    planner_fifteen = build_user_headers("planner-15", "ProductionPlanner")
    lease_fifteen = build_user_headers("lease-admin-15", "LeaseAdministrator")

    endorsement = validate_success(
        api.create_substitution_endorsement(
            create_substitution_endorsement_payload(
                production_order_id=order["id"],
                original_component_id=original["id"],
                substitute_component_id=substitute["id"],
                substitute_qty_per_car=1,
                decides_material=True,
                expected_production_order_version=order["version"],
            ),
            planner_fifteen,
        ),
        expected_status=201,
    )
    assert endorsement["status"] == "PENDING"

    reserved = validate_success(api.reserve_components(order["id"], PLANNER))
    assert reserved["status"] == "COMPONENT_RESERVED", (
        "the original wheelset is in stock, so reservation does not auto-approve"
    )

    approved = validate_success(
        api.approve_substitution_endorsement(endorsement["id"], lease_fifteen)
    )
    assert approved["status"] == "APPROVED"

    rejected = api.release_production_order(order["id"], PLANNER)
    validate_error(rejected, ApiErrorId.ERR_MATERIAL_ENDORSEMENT_PENDING)
    assert rejected.status_code == 409

    order_after = get_success_data(api.get_production_order(order["id"], ADMIN))
    assert order_after["status"] == "COMPONENT_RESERVED", "the order does not advance"

    endorsement_after = get_success_data(
        api.get_substitution_endorsement(endorsement["id"], ADMIN)
    )
    assert endorsement_after["status"] == "APPROVED"
    assert endorsement_after["decides_material"] is True

    component_after = get_success_data(api.get_component(original["id"], ADMIN))
    assert component_after["on_hand_qty"] == 99, "the reservation committed 1 unit"
    assert component_after["reserved_qty"] == 0, (
        "only RELEASED orders contribute to the reservation term"
    )
    assert bom_row["qty_per_car"] == 1
