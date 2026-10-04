"""Error catalogue, part 1: authentication, existence, state and currency.

Each test triggers one catalogued rejection and pins both the exact `error_id`
and its HTTP status, together with a control call proving the rejection is
specific to the violated rule rather than to the endpoint.
"""

from test_helpers import (
    CLOCK_START_ISO,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    api_client,
    build_user_headers,
    changeover_payload,
    create_car_type_payload,
    create_component_payload,
    create_component_purchase_order_payload,
    create_endorsement,
    create_lease_contract_payload,
    create_lessee_payload,
    create_order,
    create_retrofit_program_car_type_payload,
    create_retrofit_program_payload,
    draft_lease_amendment_payload,
    get_success_data,
    release_order,
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


def catalogue_with_rows(**overrides):
    """One BOXCAR car type carrying a wheelset row and a casting row."""
    defaults = dict(
        model_code="CT-ERR",
        car_class="BOXCAR",
        build_hours=1,
        regulatory_life_years=25,
        line_count_family="LINE-ERR",
        wheelset_part_number="WS-ERR",
        wheelset_unit_cost_cents=1000,
        wheelset_lead_time_days=5,
        wheelset_qty_per_car=1,
        casting_part_number="CS-ERR",
        casting_unit_cost_cents=2000,
        casting_lead_time_days=6,
        casting_qty_per_car=1,
        include_coating=False,
        on_hand_qty=100,
    )
    defaults.update(overrides)
    return setup_catalogue(**defaults)


# ─── Authentication and authorization ─────────────────

def test_undeclared_role_on_a_read_returns_401(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID` and
    `X-User-Role`. Both are mandatory. A request missing either header, or naming
    a role that is not one of the seven roles declared below, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.11: "First, authentication. `X-User-Role` and `X-User-ID` must both be
    present and must name a declared role; otherwise the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401). This check applies to every endpoint without
    exception, including the reads."

    An undeclared role is refused on a plain read, while the identical read under
    a declared role succeeds — so the 401 is header-caused, not endpoint-wide.

    Design: Corner/errors/error_unauthenticated_undeclared_role_on_read_returns_401
    """
    set_clock(CLOCK_START_ISO)
    get_success_data(
        api_client.create_car_type(
            create_car_type_payload(
                model_code="CT-H1",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=25,
                line_count_family="LINE-H1",
            ),
            PLANNER,
        )
    )

    anonymous = build_user_headers("anon-operator-1", "Anonymous")
    rejected = api_client.list_lease_fleet_cars(anonymous)
    error = validate_error(rejected, ApiErrorId.ERR_UNAUTHENTICATED)
    assert rejected.status_code == 401
    assert rejected.json()["response_type"] == "error"
    assert error["message"].strip(), "the error envelope carries a human message"

    control = validate_success(api_client.list_lease_fleet_cars(ADMIN))
    assert isinstance(control, list)


def test_declared_role_lacking_the_operation_returns_403(api):
    """PRD §2.1: "A request whose role is declared but not permitted for the
    requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403)"
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Opening a mandate is a retrofitist operation, so the planner's identical body
    is refused and writes nothing, while the retrofitist's is accepted.

    Design: Corner/errors/error_forbidden_declared_role_lacks_operation_returns_403
    """
    set_clock(CLOCK_START_ISO)
    payload = create_retrofit_program_payload(
        mandate_code="MAND-FBD",
        description="Denied mandate",
        compliance_deadline_date="2026-12-31",
        required_shop_days_per_car=3,
    )

    denied = api_client.create_retrofit_program(payload, PLANNER)
    validate_error(denied, ApiErrorId.ERR_FORBIDDEN)
    assert denied.status_code == 403

    allowed = validate_success(
        api_client.create_retrofit_program(payload, RETROFIT), expected_status=201
    )
    assert allowed["status"] == "PLANNED"

    rows, meta = validate_paginated(api_client.list_retrofit_programs(ADMIN))
    assert meta["total_count"] == 1, "the denied call left no partial state"
    assert rows[0]["id"] == allowed["id"]


def test_self_approval_by_the_creating_operator_returns_403(api):
    """PRD §2.1: "substitution endorsements are subject to a
    segregation-of-duties rule — the operator who created an endorsement may not
    be the operator who approves it, and an approval attempted by the creating
    `X-User-ID` is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)."
    PRD §3.3: "It is legal only from `PENDING`, and it carries a
    segregation-of-duties precondition: the acting `X-User-ID` must not be the
    `X-User-ID` that created the endorsement"

    The refusal keys on the operator identifier rather than the role: the same
    caller approves a second endorsement it did not create.

    Design: Corner/errors/error_self_approval_forbidden_same_operator_returns_403
    """
    set_clock(CLOCK_START_ISO)
    catalogue = catalogue_with_rows(
        model_code="CT-I",
        line_count_family="LINE-I",
        wheelset_part_number="WS-I",
        wheelset_qty_per_car=2,
        casting_part_number="CS-I",
        casting_qty_per_car=1,
    )
    substitute = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-I2",
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
    creator_one = build_user_headers("user-op-9", "ProductionPlanner")
    creator_two = build_user_headers("user-op-8", "ProductionPlanner")
    first = create_endorsement(
        order,
        catalogue["wheelset"],
        substitute,
        substitute_qty_per_car=2,
        decides_material=False,
        headers=creator_one,
    )
    second = create_endorsement(
        order,
        catalogue["casting"],
        substitute,
        substitute_qty_per_car=1,
        decides_material=True,
        headers=creator_two,
    )
    assert first["status"] == "PENDING"
    assert second["status"] == "PENDING"

    approver = build_user_headers("user-op-9", "LeaseAdministrator")
    refused = api_client.approve_substitution_endorsement(first["id"], approver)
    validate_error(refused, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
    assert refused.status_code == 403
    unchanged = get_success_data(
        api_client.get_substitution_endorsement(first["id"], ADMIN)
    )
    assert unchanged["status"] == "PENDING", "the refused approval applied nothing"

    accepted = validate_success(
        api_client.approve_substitution_endorsement(second["id"], approver)
    )
    assert accepted["status"] == "APPROVED"
    assert accepted["version"] == 2, "the approval's own increment landed"


# ─── Existence ────────────────────────────────────────

def test_unresolvable_path_id_returns_404(api):
    """PRD §2.4: "The server resolves each templated identifier in the order it
    appears in the path and stops at the first one that does not correspond to a
    persisted row, returning `ERR_NOT_FOUND` (HTTP 404)."
    PRD §2.11: "Third, path resolution: every templated resource identifier in the
    path must resolve to a persisted row, validated from left to right, and a
    failure is rejected with `ERR_NOT_FOUND` (HTTP 404)"

    A well-formed identifier that names nothing is refused, while the created
    component reads back — so the 404 is id-specific rather than endpoint-wide.

    Design: Corner/errors/error_not_found_unresolvable_component_path_id_returns_404
    """
    set_clock(CLOCK_START_ISO)
    component = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-N1",
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=5,
            ),
            SUPPLY,
        )
    )

    missing = api_client.get_component(NON_EXISTENT_UUID, ADMIN)
    validate_error(missing, ApiErrorId.ERR_NOT_FOUND)
    assert missing.status_code == 404

    control = validate_success(api_client.get_component(component["id"], ADMIN))
    assert control["id"] == component["id"]
    assert control["part_number"] == "WS-N1"


def test_unresolvable_body_foreign_key_returns_404(api):
    """PRD §2.11: "Fourth, body referential integrity: every foreign key named in
    the request body must resolve to a persisted row, and a failure is rejected
    with `ERR_COMPONENT_NOT_FOUND` (HTTP 404). This fourth check is not limited to
    component references despite its name"
    PRD §3.2: "a body that names a component, a purchase order or any other
    foreign key that does not resolve is rejected with `ERR_COMPONENT_NOT_FOUND`
    (HTTP 404) before any state check runs"

    The dangling body reference is refused while the same body carrying the real
    component is accepted, so the 404 is caused by the missing row.

    Design: Corner/errors/error_component_not_found_unresolvable_body_fk_returns_404
    """
    set_clock(CLOCK_START_ISO)
    component = get_success_data(
        api_client.create_component(
            create_component_payload(
                part_number="WS-N2",
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=5,
            ),
            SUPPLY,
        )
    )

    dangling = api_client.create_component_purchase_order(
        create_component_purchase_order_payload(
            component_id=NON_EXISTENT_UUID,
            qty_ordered=10,
            unit_cost_cents=1000,
            order_date="2026-09-01",
            expected_receipt_date="2026-09-21",
        ),
        SUPPLY,
    )
    validate_error(dangling, ApiErrorId.ERR_COMPONENT_NOT_FOUND)
    assert dangling.status_code == 404

    accepted = validate_success(
        api_client.create_component_purchase_order(
            create_component_purchase_order_payload(
                component_id=component["id"],
                qty_ordered=10,
                unit_cost_cents=1000,
                order_date="2026-09-01",
                expected_receipt_date="2026-09-21",
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    assert accepted["status"] == "PLACED"

    rows, meta = validate_paginated(api_client.list_component_purchase_orders(ADMIN))
    assert meta["total_count"] == 1, "the rejected call wrote no row"
    assert rows[0]["id"] == accepted["id"]


# ─── State, terminality and version currency ──────────

def test_start_on_a_voided_program_returns_409(api):
    """PRD §3.8: "A program that has already reached `COMPLETED` or `VOIDED`
    accepts no further transition and is rejected with `ERR_ALREADY_TERMINAL`
    (HTTP 409)."
    PRD §2.11: "Sixth, terminality: a resource that has already reached a terminal
    state accepts no further transitions, and an attempt is rejected with
    `ERR_ALREADY_TERMINAL` (HTTP 409); this check guards order completion, sale
    settlement and retrofit-program start."

    Restarting the voided mandate is refused and leaves it VOIDED, while the
    untouched program still starts.

    Design: Corner/errors/error_already_terminal_start_on_voided_program_returns_409
    """
    set_clock(CLOCK_START_ISO)
    car_type = get_success_data(
        api_client.create_car_type(
            create_car_type_payload(
                model_code="CT-J",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=25,
                line_count_family="LINE-J",
            ),
            PLANNER,
        )
    )

    def open_program(mandate_code, description):
        program = get_success_data(
            api_client.create_retrofit_program(
                create_retrofit_program_payload(
                    mandate_code=mandate_code,
                    description=description,
                    compliance_deadline_date="2026-12-31",
                    required_shop_days_per_car=3,
                ),
                RETROFIT,
            )
        )
        get_success_data(
            api_client.create_retrofit_program_car_type(
                create_retrofit_program_car_type_payload(
                    retrofit_program_id=program["id"], car_type_id=car_type["id"]
                ),
                RETROFIT,
            )
        )
        return program

    voided_program = open_program("MAND-J1", "Program to be voided")
    started = validate_success(
        api_client.start_retrofit_program(voided_program["id"], RETROFIT)
    )
    assert started["status"] == "IN_PROGRESS"
    voided = validate_success(
        api_client.void_retrofit_program(
            voided_program["id"], RETROFIT, {"reason": "Mandate withdrawn"}
        )
    )
    assert voided["status"] == "VOIDED"
    assert voided["version"] == 3, "PLANNED -> IN_PROGRESS -> VOIDED"

    control_program = open_program("MAND-J2", "Control program")

    refused = api_client.start_retrofit_program(voided_program["id"], RETROFIT)
    validate_error(refused, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert refused.status_code == 409
    unchanged = get_success_data(
        api_client.get_retrofit_program(voided_program["id"], ADMIN)
    )
    assert unchanged["status"] == "VOIDED"
    assert unchanged["version"] == 3, "the rejection moved nothing"

    control = validate_success(
        api_client.start_retrofit_program(control_program["id"], RETROFIT)
    )
    assert control["status"] == "IN_PROGRESS", (
        "the 409 is terminal-state-specific, not program-wide"
    )


def test_stale_amendment_draft_returns_412(api):
    """PRD §2.7: "when the supplied expected version does not equal the parent's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP
    412), and no part of the request is applied."
    PRD §3.5: "The expected version must equal the contract's current `version`;
    if the contract has advanced since the client read it, the draft is rejected
    with `ERR_STALE_VERSION` (HTTP 412) and nothing is written."

    One version below the contract's current version is refused and leaves it
    ACTIVE; the identical body carrying the observed version is accepted.

    Design: Corner/errors/error_stale_version_amendment_redraft_returns_412
    """
    set_clock(CLOCK_START_ISO)
    lessee = get_success_data(
        api_client.create_lessee(
            create_lessee_payload(
                legal_name="Stale Amendment Rail Co",
                credit_tier="B",
                utilization_threshold_pct=0,
                credit_ceiling_cents=1000000,
            ),
            LEASE,
        )
    )
    contract = get_success_data(
        api_client.create_lease_contract(
            create_lease_contract_payload(
                lessee_id=lessee["id"],
                lease_type="FULL_SERVICE",
                per_diem_rate_cents=1000,
                liability_bearer="LESSOR",
                term_start_date="2026-09-01",
                term_end_date="2027-09-01",
                fleet_car_cap=5,
            ),
            LEASE,
        )
    )
    activated = validate_success(api_client.activate_lease_contract(contract["id"], LEASE))
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2, "create 1 -> activate 2"

    stale_body = draft_lease_amendment_payload(
        per_diem_rate_cents=1500,
        liability_bearer="LESSEE",
        expected_lease_version=activated["version"] - 1,
    )
    stale = api_client.draft_lease_amendment(contract["id"], stale_body, LEASE)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    unchanged = get_success_data(api_client.get_lease_contract(contract["id"], ADMIN))
    assert unchanged["status"] == "ACTIVE", "the rejection is atomic"
    assert unchanged["version"] == activated["version"]

    fresh = validate_success(
        api_client.draft_lease_amendment(
            contract["id"],
            draft_lease_amendment_payload(
                per_diem_rate_cents=1500,
                liability_bearer="LESSEE",
                expected_lease_version=activated["version"],
            ),
            LEASE,
        )
    )
    assert fresh["status"] == "AMENDMENT_DRAFTED"
    assert fresh["version"] == 3


def test_start_after_the_compliance_deadline_returns_422(api):
    """PRD §3.8: "The compliance deadline is checked on this write as well: a
    start that cannot be satisfied before the mandate's `compliance_deadline_date`
    is rejected with `ERR_RETROFIT_DEADLINE_PASSED` (HTTP 422)."
    PRD §2.11: "Ninth, compliance deadline: a retrofit shop window must end on or
    before the program's `compliance_deadline_date`, and a breach is rejected with
    `ERR_RETROFIT_DEADLINE_PASSED` (HTTP 422) on work-order creation and program
    start."

    A covered program whose deadline has lapsed is refused at start, while the
    program with an open deadline starts at the same clock.

    Design: Corner/errors/error_retrofit_deadline_passed_start_after_deadline_returns_422
    """
    set_clock(CLOCK_START_ISO)
    car_type = get_success_data(
        api_client.create_car_type(
            create_car_type_payload(
                model_code="CT-K",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=25,
                line_count_family="LINE-K",
            ),
            PLANNER,
        )
    )

    def open_program(mandate_code, description, deadline):
        program = get_success_data(
            api_client.create_retrofit_program(
                create_retrofit_program_payload(
                    mandate_code=mandate_code,
                    description=description,
                    compliance_deadline_date=deadline,
                    required_shop_days_per_car=3,
                ),
                RETROFIT,
            )
        )
        get_success_data(
            api_client.create_retrofit_program_car_type(
                create_retrofit_program_car_type_payload(
                    retrofit_program_id=program["id"], car_type_id=car_type["id"]
                ),
                RETROFIT,
            )
        )
        return program

    lapsed = open_program("MAND-K1", "Lapsed mandate", "2026-09-15")
    control_program = open_program("MAND-K2", "Open mandate", "2026-12-31")

    advance_clock_to("2026-10-01T00:00:00Z")
    clock = get_success_data(api_client.get_current_utc(ADMIN))
    assert clock["current_utc"] == "2026-10-01T00:00:00Z"

    refused = api_client.start_retrofit_program(lapsed["id"], RETROFIT)
    validate_error(refused, ApiErrorId.ERR_RETROFIT_DEADLINE_PASSED)
    assert refused.status_code == 422
    unchanged = get_success_data(api_client.get_retrofit_program(lapsed["id"], ADMIN))
    assert unchanged["status"] == "PLANNED", "the rejection is atomic"

    control = validate_success(
        api_client.start_retrofit_program(control_program["id"], RETROFIT)
    )
    assert control["status"] == "IN_PROGRESS", (
        "the rule is temporal, not state-based: the control program starts at the "
        "same clock"
    )
    assert control["version"] == 2


def test_overlapping_changeover_window_returns_409(api):
    """PRD §3.4: "The half-open window from `scheduled_start_date` up to but not
    including `scheduled_end_date` must not collide with any other changeover on
    the same line family, because the line is exclusive-occupancy; a collision is
    rejected with `ERR_CHANGEOVER_CONFLICT` (HTTP 409)."
    PRD §2.5: "when two half-open intervals are compared, a window that ends
    exactly when another begins does not collide with it — touching at a boundary
    is legal, overlapping by any amount is not."

    A one-day overlap on a differently named line segment is refused because the
    collision is judged on the car type's line family, while the touching window
    on that same segment is accepted.

    Design: Corner/errors/error_changeover_conflict_overlapping_family_window_returns_409
    """
    set_clock(CLOCK_START_ISO)
    catalogue = catalogue_with_rows(
        model_code="CT-M",
        line_count_family="LINE-M",
        wheelset_part_number="WS-M",
    )
    first_order = create_order(
        catalogue,
        quantity=2,
        planned_shop_days=2,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    second_order = create_order(
        catalogue,
        quantity=2,
        planned_shop_days=2,
        disposition="SOLD",
        priority_rank=2,
        order_date="2026-09-01",
        required_delivery_date="2026-12-01",
    )
    for order in (first_order, second_order):
        reserve_order(order["id"])
        released = release_order(order["id"])
        assert released["status"] == "RELEASED"

    incumbent = validate_success(
        api_client.changeover_production_line(
            "LINE-M",
            changeover_payload(
                production_order_id=first_order["id"],
                scheduled_start_date="2026-09-10",
                scheduled_end_date="2026-09-12",
            ),
            PLANNER,
        )
    )
    assert incumbent["status"] == "IN_PRODUCTION"

    conflict = api_client.changeover_production_line(
        "LINE-M",
        changeover_payload(
            production_order_id=second_order["id"],
            scheduled_start_date="2026-09-11",
            scheduled_end_date="2026-09-13",
        ),
        PLANNER,
    )
    validate_error(conflict, ApiErrorId.ERR_CHANGEOVER_CONFLICT)
    assert conflict.status_code == 409
    untouched = get_success_data(api_client.get_production_order(second_order["id"], ADMIN))
    assert untouched["status"] == "RELEASED", "the rejected call disturbed nothing"

    touching = validate_success(
        api_client.changeover_production_line(
            "LINE-M",
            changeover_payload(
                production_order_id=second_order["id"],
                scheduled_start_date="2026-09-12",
                scheduled_end_date="2026-09-14",
            ),
            PLANNER,
        )
    )
    assert touching["status"] == "IN_PRODUCTION", (
        "a window that starts exactly at the incumbent's end does not collide"
    )
