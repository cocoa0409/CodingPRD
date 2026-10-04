"""Validation precedence, bands 16-17: declared uniqueness and request shape.

Two instances, one test each.  The first walks all five declared uniqueness
surfaces; the second walks every shape of request-shape violation named by the
contract, each against an endpoint whose foreign keys all resolve so the shape
check is the one that reports.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_lease_contract_payload,
    create_lessee_payload,
    create_production_order_payload,
    create_retrofit_program_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


def test_every_declared_uniqueness_surface_rejects_its_second_row(api):
    """PRD §2.11: "Sixteenth, declared uniqueness: `model_code` on car types,
    `part_number` on components, `legal_name` on lessees, `mandate_code` on
    retrofit programs, and the car-type-and-component pair on bill-of-material
    rows must each be unique, and a collision is rejected with
    `ERR_DUPLICATE_ROW` (HTTP 409) on the corresponding create endpoints."
    PRD §2.4: "The pair of car type and component is unique — a second row for
    the same pair is a duplicate, not an additional requirement."
    PRD §3.1: "All three creates are subject to the declared uniqueness rules — a
    repeated model code, part number, or car-type-and-component pair is rejected
    with `ERR_DUPLICATE_ROW` (HTTP 409)".

    Each duplicate body is otherwise legal and every foreign key it names
    resolves to the row created in the same test, so the uniqueness check is the
    only live one; the first row of each surface must survive untouched.

    Design: Corner/validations/validation_p16_declared_uniqueness_violations_return_duplicate_row
    """
    set_clock("2026-09-01T00:00:00Z")
    car_type = validate_success(
        api.create_car_type(
            create_car_type_payload(
                model_code="DUP-100",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=15,
                line_count_family="DUP_LINE",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    component = validate_success(
        api.create_component(
            create_component_payload(
                part_number="DUP-WS-1",
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=5,
                on_hand_qty=10,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_car_type_component_requirement(
            create_car_type_component_requirement_payload(
                car_type_id=car_type["id"],
                component_id=component["id"],
                qty_per_car=1,
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_lessee(
            create_lessee_payload(
                legal_name="Dup Row Rail Co",
                credit_tier="A",
                utilization_threshold_pct=50,
                credit_ceiling_cents=1000000,
            ),
            LEASE,
        ),
        expected_status=201,
    )
    validate_success(
        api.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="DUP-MAND-1",
                description="Uniqueness probe mandate",
                compliance_deadline_date="2027-01-01",
                required_shop_days_per_car=3,
            ),
            RETROFIT,
        ),
        expected_status=201,
    )

    duplicates = [
        (
            "car type model_code",
            api.create_car_type(
                create_car_type_payload(
                    model_code="DUP-100",
                    car_class="TANK",
                    build_hours=2,
                    regulatory_life_years=20,
                    line_count_family="DUP_OTHER_LINE",
                ),
                PLANNER,
            ),
        ),
        (
            "component part_number",
            api.create_component(
                create_component_payload(
                    part_number="DUP-WS-1",
                    component_class="CASTING",
                    unit_cost_cents=2000,
                    lead_time_days=7,
                    on_hand_qty=10,
                ),
                SUPPLY,
            ),
        ),
        (
            "car-type-and-component pair",
            api.create_car_type_component_requirement(
                create_car_type_component_requirement_payload(
                    car_type_id=car_type["id"],
                    component_id=component["id"],
                    qty_per_car=2,
                ),
                PLANNER,
            ),
        ),
        (
            "lessee legal_name",
            api.create_lessee(
                create_lessee_payload(
                    legal_name="Dup Row Rail Co",
                    credit_tier="C",
                    utilization_threshold_pct=10,
                    credit_ceiling_cents=500,
                ),
                LEASE,
            ),
        ),
        (
            "retrofit mandate_code",
            api.create_retrofit_program(
                create_retrofit_program_payload(
                    mandate_code="DUP-MAND-1",
                    description="Second mandate under the same code",
                    compliance_deadline_date="2028-01-01",
                    required_shop_days_per_car=9,
                ),
                RETROFIT,
            ),
        ),
    ]
    for surface, response in duplicates:
        validate_error(response, ApiErrorId.ERR_DUPLICATE_ROW)
        assert response.status_code == 409, f"{surface} answers 409"
        assert response.json()["data"]["error_id"] == "ERR_DUPLICATE_ROW", surface

    kept = get_success_data(api.get_car_type(car_type["id"], ADMIN))
    assert kept["model_code"] == "DUP-100"
    assert kept["build_hours"] == 1, "the stored row, not the rejected payload"


def test_request_shape_violations_return_invalid_request(api):
    """PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours` multiplied
    by `quantity`, and `term_end_date` strictly after `term_start_date` — with a
    breach rejected as `ERR_INVALID_REQUEST` (HTTP 400) on every write endpoint."
    PRD §3.1: "The request shape must hold — `quantity` at least 1,
    `priority_rank` at least 1, `planned_shop_days` at least 1 and equal to the
    car type's `build_hours` multiplied by `quantity` — or the request is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §2.4: "its `car_class` is one of `BOXCAR`, `TANK`, `HOPPER`, `FLATCARS`
    or `GONDOLA`, its `build_hours` is the standard shop time to build one car
    and is at least 1, its `regulatory_life_years` is the service life granted
    from the car's build date and is at least 10".

    Every referenced foreign key resolves, so the shape check is the only live
    one; the conforming setup payload was accepted, proving the endpoint rejects
    only the malformed bodies.

    Design: Corner/validations/validation_p17_missing_enum_and_range_violations_return_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    car_type = validate_success(
        api.create_car_type(
            create_car_type_payload(
                model_code="VAL-100",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=15,
                line_count_family="VAL_LINE",
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    assert car_type["status"] == "ACTIVE"
    lessee = validate_success(
        api.create_lessee(
            create_lessee_payload(
                legal_name="Valid Request Rail Co",
                credit_tier="A",
                utilization_threshold_pct=50,
                credit_ceiling_cents=1000000,
            ),
            LEASE,
        ),
        expected_status=201,
    )

    missing_car_type = create_production_order_payload(
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )
    missing_car_type.pop("car_type_id")

    violations = [
        (
            "illegal car_class",
            api.create_car_type(
                create_car_type_payload(
                    model_code="VAL-BAD-ENUM",
                    car_class="SUBMARINE",
                    build_hours=1,
                    regulatory_life_years=15,
                    line_count_family="VAL_LINE",
                ),
                PLANNER,
            ),
        ),
        (
            "regulatory_life_years below the minimum",
            api.create_car_type(
                create_car_type_payload(
                    model_code="VAL-BAD-RANGE",
                    car_class="BOXCAR",
                    build_hours=1,
                    regulatory_life_years=5,
                    line_count_family="VAL_LINE",
                ),
                PLANNER,
            ),
        ),
        (
            "illegal component_class",
            api.create_component(
                create_component_payload(
                    part_number="VAL-BAD-CLASS",
                    component_class="BOLT",
                    unit_cost_cents=1000,
                    lead_time_days=5,
                    on_hand_qty=10,
                ),
                SUPPLY,
            ),
        ),
        (
            "quantity below the minimum",
            api.create_production_order(
                create_production_order_payload(
                    car_type_id=car_type["id"],
                    quantity=0,
                    planned_shop_days=0,
                    disposition="SOLD",
                    priority_rank=1,
                    order_date="2026-09-01",
                    required_delivery_date="2026-09-20",
                ),
                PLANNER,
            ),
        ),
        (
            "planned_shop_days not equal to build_hours times quantity",
            api.create_production_order(
                create_production_order_payload(
                    car_type_id=car_type["id"],
                    quantity=3,
                    planned_shop_days=5,
                    disposition="SOLD",
                    priority_rank=1,
                    order_date="2026-09-01",
                    required_delivery_date="2026-09-20",
                ),
                PLANNER,
            ),
        ),
        (
            "missing required car_type_id",
            api.create_production_order(missing_car_type, PLANNER),
        ),
        (
            "term_end_date not strictly after term_start_date",
            api.create_lease_contract(
                create_lease_contract_payload(
                    lessee_id=lessee["id"],
                    lease_type="NET",
                    per_diem_rate_cents=2000,
                    liability_bearer="LESSEE",
                    term_start_date="2026-09-01",
                    term_end_date="2026-09-01",
                    fleet_car_cap=10,
                ),
                LEASE,
            ),
        ),
    ]
    for label, response in violations:
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        assert response.status_code == 400, f"{label} answers 400"
        assert response.json()["data"]["error_id"] == "ERR_INVALID_REQUEST", label

    still_there = get_success_data(api.get_car_type(car_type["id"], ADMIN))
    assert still_there["status"] == "ACTIVE"
    assert still_there["model_code"] == "VAL-100"
