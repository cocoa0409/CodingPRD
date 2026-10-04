"""Validation precedence, band 1-4: authentication, authorization, path and body resolution.

Four instances, one test each.  Each drives a single live failure of the
earliest checks in the fixed sequence and asserts the identifier that belongs to
that check, together with a control call that proves the same request succeeds
once the one broken precondition is repaired.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    create_car_type_component_requirement_payload,
    create_car_type_payload,
    create_component_payload,
    create_order,
    set_clock,
    setup_catalogue,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPLY = TEST_USERS["supply_chain_coordinator_headers"]
PLANNER = TEST_USERS["production_planner_headers"]

# Fixed, syntactically valid UUIDs that name nothing in a freshly started store.
MISSING_ORDER_ID = "00000000-0000-0000-0000-0000000000a1"
MISSING_COMPONENT_ID = "00000000-0000-0000-0000-0000000000b1"
MISSING_CAR_ID = "00000000-0000-0000-0000-0000000000c1"
MISSING_CONTRACT_ID = "00000000-0000-0000-0000-0000000000c2"
MISSING_LESSEE_ID = "00000000-0000-0000-0000-0000000000c3"


def test_undeclared_role_is_rejected_before_any_payload_evaluation(api):
    """PRD §2.1: "A request missing either header, or naming a role that is not
    one of the seven roles declared below, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.11: "First, authentication. `X-User-Role` and `X-User-ID` must both be
    present and must name a declared role; otherwise the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.11: "The checks are evaluated in this fixed sequence, and the first
    failure short-circuits the rest of the evaluation."

    The payload is fully valid, so only the header can be at fault; the same
    request with a declared role is accepted, which is what proves the body was
    never the reason for the rejection.

    Design: Corner/validations/validation_p1_undeclared_role_returns_unauthenticated
    """
    set_clock("2026-09-01T00:00:00Z")
    anonymous = build_user_headers("anon-operator-1", "Anonymous")
    payload = create_car_type_payload(
        model_code="AUTH-100",
        car_class="BOXCAR",
        build_hours=10,
        regulatory_life_years=25,
        line_count_family="AUTH_LINE",
    )

    rejected = api.create_car_type(payload, anonymous)
    validate_error(rejected, ApiErrorId.ERR_UNAUTHENTICATED)
    assert rejected.status_code == 401, "an undeclared role answers 401"
    assert rejected.json()["data"]["error_id"] == "ERR_UNAUTHENTICATED"

    # The identical body under a declared role is accepted, so the 401 came from
    # the header and not from the payload.
    accepted = api.create_car_type(payload, PLANNER)
    created = validate_success(accepted, expected_status=201)
    assert created["model_code"] == "AUTH-100"
    assert created["status"] == "ACTIVE"

    # Exactly one row exists: a second identical registration is a duplicate,
    # which would be impossible had the rejected write persisted anything.
    duplicate = api.create_car_type(payload, PLANNER)
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ROW)


def test_declared_role_without_permission_is_forbidden_not_unauthenticated(api):
    """PRD §2.1: "A request whose role is declared but not permitted for the
    requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403);
    authorization is evaluated against both the role matrix in this section and
    the per-endpoint role list in §4."
    PRD §2.1: "`Lessee` is the exception. When `X-User-Role` is `Lessee`,
    `X-User-ID` is the `id` of the acting `Lessee`; ownership checks on any
    resource that references a `Lessee` compare the resource's foreign-key field
    to `X-User-ID`."
    PRD §2.11: "Second, authorization: the acting role must be permitted for the
    operation by the matrix in §2.1 and by the endpoint's own role list in §4,
    and a role that is declared but not permitted is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.11: "Third, path resolution: every templated resource identifier in
    the path must resolve to a persisted row, validated from left to right, and a
    failure is rejected with `ERR_NOT_FOUND` (HTTP 404)".

    The body names identifiers that resolve to nothing, so the path-resolution
    and referential checks are both live; the authorization check must still be
    the one that reports.

    Design: Corner/validations/validation_p2_declared_role_without_permission_returns_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    lessee_headers = build_user_headers("lessee-opaque-1", "Lessee")
    payload = {
        "lease_fleet_car_id": MISSING_CAR_ID,
        "lease_contract_id": MISSING_CONTRACT_ID,
        "lessee_id": MISSING_LESSEE_ID,
        "start_date": "2026-09-04",
        "end_date": "2026-10-04",
        "mileage_allowance": 1000,
    }

    rejected = api.create_car_assignment(payload, lessee_headers)
    validate_error(rejected, ApiErrorId.ERR_FORBIDDEN)
    assert rejected.status_code == 403
    body = rejected.json()["data"]
    assert body["error_id"] == "ERR_FORBIDDEN"
    assert body["error_id"] != ApiErrorId.ERR_UNAUTHENTICATED.value, (
        "the role is declared, so priority 1 passes and priority 2 rejects"
    )
    assert body["error_id"] != ApiErrorId.ERR_NOT_FOUND.value, (
        "the role check precedes path-id resolution"
    )

    # The denial is per-operation: the same role may read the placement list.
    listed = validate_success(api.list_car_assignments(lessee_headers))
    assert listed == [], "no placement may be written by the rejected call"

    admin_view = validate_success(api.list_car_assignments(ADMIN))
    assert admin_view == []


def test_unresolvable_path_id_returns_not_found_while_the_real_id_reads(api):
    """PRD §2.11: "Third, path resolution: every templated resource identifier in
    the path must resolve to a persisted row, validated from left to right, and a
    failure is rejected with `ERR_NOT_FOUND` (HTTP 404); this check applies to
    every path that carries an `id` or a `line` segment."
    PRD §2.4: "The server resolves each templated identifier in the order it
    appears in the path and stops at the first one that does not correspond to a
    persisted row, returning `ERR_NOT_FOUND` (HTTP 404)."

    A real order exists, so the 404 cannot be blamed on an empty store; the same
    read against that order returns 200.

    Design: Corner/validations/validation_p3_unresolvable_path_id_returns_not_found
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
        quantity=5,
        planned_shop_days=5,
        disposition="SOLD",
        priority_rank=1,
        order_date="2026-09-01",
        required_delivery_date="2026-09-20",
    )

    missing = api.get_production_order(MISSING_ORDER_ID, ADMIN)
    validate_error(missing, ApiErrorId.ERR_NOT_FOUND)
    assert missing.status_code == 404

    found = validate_success(api.get_production_order(order["id"], ADMIN))
    assert found["id"] == order["id"], "the 404 is id-specific, not endpoint-wide"

    rows = validate_success(
        api.list_production_orders(ADMIN, {"car_type_id": catalogue["car_type"]["id"]})
    )
    assert len(rows) == 1, "the failed lookup is side-effect free"
    assert rows[0]["id"] == order["id"]


def test_unresolvable_body_foreign_key_returns_component_not_found(api):
    """PRD §2.11: "Fourth, body referential integrity: every foreign key named in
    the request body must resolve to a persisted row, and a failure is rejected
    with `ERR_COMPONENT_NOT_FOUND` (HTTP 404). This fourth check is not limited
    to component references despite its name — it covers `lease_fleet_car_id`,
    `lease_contract_id`, `lessee_id`, `component_id`, `car_type_id`,
    `production_order_id` and `retrofit_program_id` alike — and it guards the
    creation of production orders, car assignments, lease contracts, substitution
    endorsements, retrofit work orders and component purchase orders."

    The sibling `car_type_id` in the same body resolves, so the rejection is
    caused by the dangling reference rather than by the request as a whole.

    Design: Corner/validations/validation_p4_unresolvable_body_fk_returns_component_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    car_type = validate_success(
        api.create_car_type(
            create_car_type_payload(
                model_code="FLT-100",
                car_class="BOXCAR",
                build_hours=1,
                regulatory_life_years=25,
                line_count_family="FLT_LINE",
            ),
            PLANNER,
        ),
        expected_status=201,
    )

    payload = create_car_type_component_requirement_payload(
        car_type_id=car_type["id"],
        component_id=MISSING_COMPONENT_ID,
        qty_per_car=1,
    )
    rejected = api.create_car_type_component_requirement(payload, PLANNER)
    validate_error(rejected, ApiErrorId.ERR_COMPONENT_NOT_FOUND)
    assert rejected.status_code == 404
    assert rejected.json()["data"]["error_id"] != ApiErrorId.ERR_NOT_FOUND.value, (
        "a body foreign key answers the FK-specific identifier, not the path one"
    )

    rows = validate_success(
        api.list_car_type_component_requirements(
            ADMIN, {"car_type_id": car_type["id"]}
        )
    )
    assert rows == [], "the resolving car_type_id does not rescue the request"

    # The identical body succeeds once the referenced component exists.
    component = validate_success(
        api.create_component(
            create_component_payload(
                part_number="WS-310",
                component_class="WHEELSET",
                unit_cost_cents=1000,
                lead_time_days=5,
                on_hand_qty=1000,
            ),
            SUPPLY,
        ),
        expected_status=201,
    )
    accepted = api.create_car_type_component_requirement(
        create_car_type_component_requirement_payload(
            car_type_id=car_type["id"],
            component_id=component["id"],
            qty_per_car=1,
        ),
        PLANNER,
    )
    created = validate_success(accepted, expected_status=201)
    assert created["component_id"] == component["id"]
