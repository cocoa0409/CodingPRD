"""Error catalogue, part 2: sourcing gates, endorsement closure and shape.

Each test triggers one catalogued rejection and pins both the exact `error_id`
and its HTTP status, with a control call proving the rejection is specific to the
violated rule.
"""

from test_helpers import (
    CLOCK_START_ISO,
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_endorsement,
    build_user_headers,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_endorsement,
    create_lease_contract_payload,
    create_lessee_payload,
    create_order,
    create_retrofit_program_car_type_payload,
    create_retrofit_program_payload,
    get_success_data,
    patch_substitution_endorsement_payload,
    reserve_order,
    set_clock,
    setup_catalogue,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
LEASE = TEST_USERS["lease_administrator_headers"]
RETROFIT = TEST_USERS["regulatory_retrofitist_headers"]


# ─── Sourcing gates ───────────────────────────────────

def test_reserve_after_a_long_lead_row_lands_returns_422(api):
    """PRD §3.1: "For each gated row, the derived lead time is the component's
    `lead_time_days` divided by the row's `qty_per_car`, rounded up to a whole
    day, and the worst gated lead time is the largest such figure across all
    gated rows."
    PRD §3.1: "The order passes the gate exactly when the horizon is greater than
    or equal to the worst gated lead time; anything shorter is rejected with
    `ERR_LEAD_TIME_INFEASIBLE` (HTTP 422)."
    PRD §2.11: "Fourteenth, lead-time feasibility: the order-to-delivery horizon
    must be at least the worst gated component lead time derived in §3.1, and a
    breach is rejected with `ERR_LEAD_TIME_INFEASIBLE` (HTTP 422) on order
    creation and reservation."

    An order taken against a car type with no bill-of-material rows passes the
    gate by convention, but the same reserve call is refused once a row with a
    60-day lead at two per car makes the worst gated lead ceil(60 / 2) == 30
    against a 10-day horizon.

    Design: Corner/errors/error_lead_time_infeasible_at_reserve_after_bom_row_added
    """
    set_clock(CLOCK_START_ISO)
    catalogue = setup_catalogue(
        model_code="CT-N",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-N",
        wheelset_part_number="WS-N3",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=60,
        wheelset_qty_per_car=2,
        include_bom=False,
        include_coating=False,
        on_hand_qty=100,
    )
    short_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-11",
    )
    assert short_order["status"] == "DRAFT", (
        "with no gated rows the worst gated lead time is zero by convention"
    )

    get_success_data(
        api_client.create_car_type_component_requirement(
            create_car_type_component_requirement_payload(
                car_type_id=catalogue["car_type"]["id"],
                component_id=catalogue["wheelset"]["id"],
                qty_per_car=2,
            ),
            PLANNER,
        )
    )
    control_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=2,
        order_date="2026-09-01",
        required_delivery_date="2026-10-01",
    )

    refused = api_client.reserve_components(short_order["id"], PLANNER)
    validate_error(refused, ApiErrorId.ERR_LEAD_TIME_INFEASIBLE)
    assert refused.status_code == 422
    unchanged = get_success_data(
        api_client.get_production_order(short_order["id"], ADMIN)
    )
    assert unchanged["status"] == "DRAFT", "no stock was committed"

    accepted = validate_success(api_client.reserve_components(control_order["id"], PLANNER))
    assert accepted["status"] == "COMPONENT_RESERVED", (
        "a 30-day horizon meets the worst gated lead of ceil(60 / 2) exactly"
    )


def test_approved_material_endorsement_blocks_release(api):
    """PRD §3.3: "One precondition couples the endorsements on an order together:
    any endorsement on the same order that is `APPROVED` and has
    `decides_material` true must be applied in the same release request, and a
    release that would leave a material endorsement in flight is rejected with
    `ERR_MATERIAL_ENDORSEMENT_PENDING` (HTTP 409)."
    PRD §3.4: "A release that would leave a material endorsement in flight is
    rejected with `ERR_MATERIAL_ENDORSEMENT_PENDING` (HTTP 409)"

    The order carrying an approved non-material endorsement releases and applies
    it; the otherwise identical order whose approved endorsement changes the
    component class is refused and left COMPONENT_RESERVED.

    Design: Corner/errors/error_material_endorsement_pending_blocks_release
    """
    set_clock(CLOCK_START_ISO)
    catalogue = setup_catalogue(
        model_code="CT-O",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-O",
        wheelset_part_number="WS-O",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=2,
        casting_part_number="CS-O",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        include_coating=False,
        on_hand_qty=100,
    )
    same_class_substitute = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-O2",
                component_class="WHEELSET",
                unit_cost_cents=1100,
                lead_time_days=4,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    changed_class_substitute = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="CS-O2",
                component_class="COATING",
                unit_cost_cents=500,
                lead_time_days=3,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    plain_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    material_order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=2,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )

    reserve_order(plain_order["id"])
    plain_endorsement = create_endorsement(
        plain_order,
        catalogue["wheelset"],
        same_class_substitute,
        substitute_qty_per_car=2,
        decides_material=False,
    )
    approved_plain = approve_endorsement(plain_endorsement["id"])

    reserve_order(material_order["id"])
    material_endorsement = create_endorsement(
        material_order,
        catalogue["casting"],
        changed_class_substitute,
        substitute_qty_per_car=1,
        decides_material=True,
    )
    approved_material = approve_endorsement(material_endorsement["id"])
    assert approved_plain["status"] == "APPROVED"
    assert approved_material["status"] == "APPROVED"

    released = validate_success(
        api_client.release_production_order(plain_order["id"], PLANNER)
    )
    assert released["status"] == "RELEASED", (
        "an approved endorsement that decides no material change does not block"
    )
    applied = get_success_data(
        api_client.get_substitution_endorsement(plain_endorsement["id"], ADMIN)
    )
    assert applied["status"] == "APPLIED"

    blocked = api_client.release_production_order(material_order["id"], PLANNER)
    validate_error(blocked, ApiErrorId.ERR_MATERIAL_ENDORSEMENT_PENDING)
    assert blocked.status_code == 409
    unchanged_order = get_success_data(
        api_client.get_production_order(material_order["id"], ADMIN)
    )
    assert unchanged_order["status"] == "COMPONENT_RESERVED", "no partial application"
    unchanged_endorsement = get_success_data(
        api_client.get_substitution_endorsement(material_endorsement["id"], ADMIN)
    )
    assert unchanged_endorsement["status"] == "APPROVED"


def test_second_return_to_pending_returns_409(api):
    """PRD §3.3: "The retry is bounded: an endorsement that has already been
    rejected once may be returned to `PENDING` one time, and the third rejection
    is terminal — an attempt to return it to `PENDING` a second time is rejected
    with `ERR_ENDORSEMENT_RETRY_EXHAUSTED` (HTTP 409)."
    PRD §3.3: "The cycle `PENDING → REJECTED → PENDING → REJECTED` is therefore
    allowed exactly once, and the second return to `PENDING` is the last retry
    the endorsement will ever get."

    The full ladder runs once; the second return to pending is refused and the
    endorsement stays REJECTED.

    Design: Corner/errors/error_endorsement_retry_exhausted_on_second_return_returns_409
    """
    set_clock(CLOCK_START_ISO)
    catalogue = setup_catalogue(
        model_code="CT-P",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-P",
        wheelset_part_number="WS-P",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=2,
        include_coating=False,
        on_hand_qty=100,
    )
    substitute = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-P2",
                component_class="WHEELSET",
                unit_cost_cents=1100,
                lead_time_days=4,
                on_hand_qty=100,
            ),
            SUPPLY,
        )
    )
    order = create_order(
        catalogue,
        quantity=1,
        planned_shop_days=1,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    creator = build_user_headers("user-planner-p", "ProductionPlanner")
    reviewer = build_user_headers("user-lease-p", "LeaseAdministrator")
    endorsement = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=2,
        decides_material=False,
        headers=creator,
    )
    assert endorsement["status"] == "PENDING"

    first_rejection = validate_success(
        api_client.patch_substitution_endorsement(
            endorsement["id"],
            patch_substitution_endorsement_payload(status="REJECTED"),
            reviewer,
        )
    )
    assert first_rejection["status"] == "REJECTED"
    back_to_pending = validate_success(
        api_client.patch_substitution_endorsement(
            endorsement["id"],
            patch_substitution_endorsement_payload(status="PENDING"),
            creator,
        )
    )
    assert back_to_pending["status"] == "PENDING"
    second_rejection = validate_success(
        api_client.patch_substitution_endorsement(
            endorsement["id"],
            patch_substitution_endorsement_payload(status="REJECTED"),
            reviewer,
        )
    )
    assert second_rejection["status"] == "REJECTED"

    exhausted = api_client.patch_substitution_endorsement(
        endorsement["id"],
        patch_substitution_endorsement_payload(status="PENDING"),
        creator,
    )
    validate_error(exhausted, ApiErrorId.ERR_ENDORSEMENT_RETRY_EXHAUSTED)
    assert exhausted.status_code == 409
    unchanged = get_success_data(
        api_client.get_substitution_endorsement(endorsement["id"], ADMIN)
    )
    assert unchanged["status"] == "REJECTED", "the refused retry changed nothing"


def test_start_of_a_program_covering_nothing_returns_409(api):
    """PRD §2.8: "a program that covers no car type at all cannot start, and an
    order whose car type has no bill-of-material rows cannot reserve components;
    both situations are rejected with `ERR_PREREQUISITE_NOT_MET` (HTTP 409),
    because in each case a required upstream aggregate is missing rather than
    merely inconsistent."
    PRD §3.8: "The start action is legal only from `PLANNED`, and it requires the
    program to have at least one covered car type — a program with no coverage is
    rejected with `ERR_PREREQUISITE_NOT_MET` (HTTP 409), because the upstream
    aggregate it depends on is missing."

    The uncovered start is refused and leaves the program PLANNED; attaching one
    coverage row makes the identical call succeed.

    Design: Corner/errors/error_prerequisite_not_met_program_start_without_coverage_returns_409
    """
    set_clock(CLOCK_START_ISO)
    car_type = get_success_data(
        api_client.create_car_type(
            create_car_type_payload(
                model_code="CT-Q2",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=25,
                line_count_family="LINE-Q2",
            ),
            PLANNER,
        )
    )
    program = get_success_data(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-Q2",
                description="Uncovered mandate",
                compliance_deadline_date="2026-12-31",
                required_shop_days_per_car=3,
            ),
            RETROFIT,
        )
    )
    assert program["status"] == "PLANNED"
    coverage, coverage_meta = validate_paginated(
        api_client.list_retrofit_program_car_types(
            ADMIN, {"retrofit_program_id": program["id"]}
        )
    )
    assert coverage == []
    assert coverage_meta["total_count"] == 0

    refused = api_client.start_retrofit_program(program["id"], RETROFIT)
    validate_error(refused, ApiErrorId.ERR_PREREQUISITE_NOT_MET)
    assert refused.status_code == 409
    unchanged = get_success_data(api_client.get_retrofit_program(program["id"], ADMIN))
    assert unchanged["status"] == "PLANNED", "the rejection is atomic"

    covered = validate_success(
        api_client.create_retrofit_program_car_type(
            create_retrofit_program_car_type_payload(
                retrofit_program_id=program["id"], car_type_id=car_type["id"]
            ),
            RETROFIT,
        ),
        expected_status=201,
    )
    assert covered["retrofit_program_id"] == program["id"]

    started = validate_success(api_client.start_retrofit_program(program["id"], RETROFIT))
    assert started["status"] == "IN_PROGRESS"
    assert started["version"] == 2


# ─── Shape and uniqueness ─────────────────────────────

def test_repeated_lessee_name_and_mandate_code_return_409(api):
    """PRD §2.11: "Sixteenth, declared uniqueness: `model_code` on car types,
    `part_number` on components, `legal_name` on lessees, `mandate_code` on
    retrofit programs, and the car-type-and-component pair on bill-of-material
    rows must each be unique, and a collision is rejected with `ERR_DUPLICATE_ROW`
    (HTTP 409) on the corresponding create endpoints."
    PRD §3.5: "A duplicate legal name is rejected with `ERR_DUPLICATE_ROW` (HTTP
    409)."

    The second write under a taken name and the second under a taken mandate code
    are both refused, while a distinct value on each endpoint is accepted.

    Design: Corner/errors/error_duplicate_row_lessee_name_and_mandate_code_return_409
    """
    set_clock(CLOCK_START_ISO)
    incumbent_lessee = get_success_data(
        api_client.create_lessee(
            create_lessee_payload(
                legal_name="Dup Rail Co",
                credit_tier="B",
                utilization_threshold_pct=0,
                credit_ceiling_cents=1000000,
            ),
            LEASE,
        )
    )
    incumbent_program = get_success_data(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-DUP",
                description="Original mandate",
                compliance_deadline_date="2026-12-31",
                required_shop_days_per_car=3,
            ),
            RETROFIT,
        )
    )

    duplicate_lessee = api_client.create_lessee(
        create_lessee_payload(
            legal_name="Dup Rail Co",
            credit_tier="A",
            utilization_threshold_pct=10,
            credit_ceiling_cents=2000000,
        ),
        LEASE,
    )
    validate_error(duplicate_lessee, ApiErrorId.ERR_DUPLICATE_ROW)
    assert duplicate_lessee.status_code == 409

    duplicate_program = api_client.create_retrofit_program(
        create_retrofit_program_payload(
            mandate_code="MAND-DUP",
            description="Duplicate mandate",
            compliance_deadline_date="2027-06-30",
            required_shop_days_per_car=9,
        ),
        RETROFIT,
    )
    validate_error(duplicate_program, ApiErrorId.ERR_DUPLICATE_ROW)
    assert duplicate_program.status_code == 409

    distinct_lessee = validate_success(
        api_client.create_lessee(
            create_lessee_payload(
                legal_name="Dup Rail Co Two",
                credit_tier="A",
                utilization_threshold_pct=10,
                credit_ceiling_cents=2000000,
            ),
            LEASE,
        ),
        expected_status=201,
    )
    assert distinct_lessee["legal_name"] == "Dup Rail Co Two"
    distinct_program = validate_success(
        api_client.create_retrofit_program(
            create_retrofit_program_payload(
                mandate_code="MAND-DUP-2",
                description="Distinct mandate",
                compliance_deadline_date="2027-06-30",
                required_shop_days_per_car=9,
            ),
            RETROFIT,
        ),
        expected_status=201,
    )
    assert distinct_program["mandate_code"] == "MAND-DUP-2"

    unchanged = get_success_data(
        api_client.get_retrofit_program(incumbent_program["id"], ADMIN)
    )
    assert unchanged["mandate_code"] == "MAND-DUP", (
        "the collision did not overwrite the incumbent mandate"
    )
    assert unchanged["description"] == "Original mandate"
    assert incumbent_lessee["legal_name"] == "Dup Rail Co"


def test_term_end_not_after_start_returns_400(api):
    """PRD §2.11: "Seventeenth, request shape: required fields must be present,
    enum members must be legal, and numeric ranges must hold — `quantity` at
    least 1, `planned_shop_days` equal to the car type's `build_hours` multiplied
    by `quantity`, and `term_end_date` strictly after `term_start_date` — with a
    breach rejected as `ERR_INVALID_REQUEST` (HTTP 400) on every write endpoint."
    PRD §3.5: "The term must end strictly after it starts, or the request is
    rejected with `ERR_INVALID_REQUEST` (HTTP 400)"

    A zero-length term is refused while the same body ending one day later is
    accepted, so the rule is enforced on the date pair rather than on either date
    alone.

    Design: Corner/errors/error_invalid_request_term_end_not_after_start_returns_400
    """
    set_clock(CLOCK_START_ISO)
    lessee = get_success_data(
        api_client.create_lessee(
            create_lessee_payload(
                legal_name="Term Rail Co",
                credit_tier="B",
                utilization_threshold_pct=0,
                credit_ceiling_cents=1000000,
            ),
            LEASE,
        )
    )

    zero_length = api_client.create_lease_contract(
        create_lease_contract_payload(
            lessee_id=lessee["id"],
            lease_type="FULL_SERVICE",
            per_diem_rate_cents=1000,
            liability_bearer="LESSOR",
            term_start_date="2026-09-01",
            term_end_date="2026-09-01",
            fleet_car_cap=5,
        ),
        LEASE,
    )
    validate_error(zero_length, ApiErrorId.ERR_INVALID_REQUEST)
    assert zero_length.status_code == 400

    accepted = validate_success(
        api_client.create_lease_contract(
            create_lease_contract_payload(
                lessee_id=lessee["id"],
                lease_type="FULL_SERVICE",
                per_diem_rate_cents=1000,
                liability_bearer="LESSOR",
                term_start_date="2026-09-01",
                term_end_date="2026-09-02",
                fleet_car_cap=5,
            ),
            LEASE,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "DRAFT"
    assert accepted["term_end_date"] == "2026-09-02"

    rows, meta = validate_paginated(api_client.list_lease_contracts(ADMIN))
    assert meta["total_count"] == 1, "the rejected call wrote no row"
    assert rows[0]["id"] == accepted["id"]
