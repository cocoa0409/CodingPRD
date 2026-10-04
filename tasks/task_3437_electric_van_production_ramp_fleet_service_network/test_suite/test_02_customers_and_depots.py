"""Fleet customer onboarding and depot establishment: creation shape,
computed-field initialization, existence checks, and entity-backed identity."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_depot,
    assert_fleet_customer,
    create_depot_payload,
    create_fleet_customer,
    create_fleet_customer_payload,
    is_valid_uuid,
    make_fleet_manager_headers,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_fleet_customer_create_returns_common_fields(api, platform_admin_headers):
    """PRD section 2.5: "Every resource in this API — fleet customers,
    depots, ... — carries the same four system-maintained properties. `id` is
    a server-minted UUID with no type prefix."; PRD section 3.1: "A
    `PlatformAdmin` registers a fleet customer with its legal `company_name`,
    a primary operations `contact_email`, and an `account_tier` of either
    `STANDARD` or `PRIORITY`."

    Design: Corner/entities/fleet_customer_create_returns_common_fields
    """
    set_logical_clock()
    resp = api.create_fleet_customer(
        create_fleet_customer_payload(
            company_name="Acme Logistics", contact_email="ops@acme.test", account_tier="STANDARD"
        ),
        platform_admin_headers,
    )
    data = validate_success(resp, 201)
    assert_fleet_customer(data)
    assert data["company_name"] == "Acme Logistics"
    assert data["contact_email"] == "ops@acme.test"
    assert data["account_tier"] == "STANDARD"
    assert data["version"] == 1, "a freshly created resource carries version 1"


def test_depot_create_initializes_committed_capacity_zero(api):
    """PRD section 3.1: "A fresh depot's `committed_capacity_kw` initializes
    to 0 and is maintained automatically thereafter by the capacity accounting
    of section 2.10 — it is never set directly."

    Design: Corner/entities/depot_create_initializes_committed_capacity_zero
    """
    set_logical_clock()
    customer = create_fleet_customer()
    headers = make_fleet_manager_headers(customer["id"])
    resp = api.create_depot(create_depot_payload(customer["id"]), headers)
    data = validate_success(resp, 201)
    assert_depot(data)
    assert data["committed_capacity_kw"] == 0, "committed_capacity_kw initializes to exactly 0"
    assert data["fleet_customer_id"] == customer["id"]
    assert data["version"] == 1


def test_depot_get_unknown_id_returns_not_found(api, platform_admin_headers):
    """PRD section 2.8: "Path-template ids exist, validated left to right
    along the URL; then body-supplied foreign keys — ... — must each reference
    an existing resource (`ERR_NOT_FOUND`, 404)."

    Design: Corner/entities/depot_get_unknown_id_returns_not_found
    """
    set_logical_clock()
    resp = api.get_depot(NON_EXISTENT_UUID, platform_admin_headers)
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error_data["message"].strip(), "error message must be non-empty"


def test_depot_create_missing_required_state_code_returns_validation(api):
    """PRD section 3.1: "Each depot carries a display `name`, a street
    `address`, a two-letter uppercase `state_code` naming the US state the
    depot sits in, and a `total_capacity_kw` strictly greater than zero
    describing the electrical service the site can draw." — a create body
    missing the required state_code cannot produce such a depot and is a
    400 ERR_VALIDATION.

    Design: Corner/entities/depot_create_missing_required_state_code_returns_validation
    """
    set_logical_clock()
    customer = create_fleet_customer()
    headers = make_fleet_manager_headers(customer["id"])
    payload = create_depot_payload(customer["id"], name="Broken Depot")
    del payload["state_code"]
    resp = api.create_depot(payload, headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, _meta = validate_paginated(api.list_fleet_customer_depots(customer["id"], headers))
    assert rows == [], "no depot row may be persisted by a rejected create"


def test_depot_create_extra_field_ignored(api):
    """PRD section 2.5: "`version` is an integer that increments by exactly 1
    on every successful mutation, including mutations caused by a cascade
    rather than a direct write"; PRD section 3.1: "A fresh depot's
    `committed_capacity_kw` initializes to 0 and is maintained automatically
    thereafter" — client-supplied system fields are ignored.

    Design: Corner/entities/depot_create_extra_field_ignored
    """
    set_logical_clock()
    customer = create_fleet_customer()
    headers = make_fleet_manager_headers(customer["id"])
    payload = create_depot_payload(
        customer["id"], name="Sneaky Depot", state_code="NV", address="9 Side St",
        total_capacity_kw=300,
    )
    payload["version"] = 99
    payload["committed_capacity_kw"] = 250
    resp = api.create_depot(payload, headers)
    data = validate_success(resp, 201)
    assert data["version"] == 1, "client-supplied version must be ignored"
    assert data["committed_capacity_kw"] == 0, "client-supplied committed_capacity_kw must be ignored"


def test_depot_create_with_unknown_customer_returns_not_found(api):
    """PRD section 2.8: "then body-supplied foreign keys —
    `fleet_customer_id`, `depot_id`, ... — must each reference an existing
    resource (`ERR_NOT_FOUND`, 404)."

    Design: Corner/entities/depot_create_with_unknown_customer_returns_not_found
    """
    set_logical_clock()
    ghost = "99999999-8888-7777-6666-555555555555"
    resp = api.create_depot(
        create_depot_payload(ghost, name="Ghost Depot", total_capacity_kw=100),
        make_fleet_manager_headers(ghost),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_entity_backed_fleet_manager_identity_binds_customer(api):
    """PRD section 2.1: "When `X-User-Role` is `FleetManager`, `X-User-ID` is
    the `id` of the acting `FleetCustomer`; ownership checks on any resource
    that references a `FleetCustomer` compare the resource's foreign-key field
    to `X-User-ID`."; PRD section 3.1: "Creating a depot requires the
    manager's `fleet_customer_id` to equal their own `X-User-ID`".

    Design: Corner/rbac/entity_backed_fleet_manager_identity_binds_customer
    """
    set_logical_clock()
    customer = create_fleet_customer()
    headers = make_fleet_manager_headers(customer["id"])
    resp = api.create_depot(
        create_depot_payload(
            customer["id"], name="Identity Depot", state_code="OR",
            address="11 Bind Rd", total_capacity_kw=250,
        ),
        headers,
    )
    data = validate_success(resp, 201)
    assert data["fleet_customer_id"] == customer["id"], (
        "the entity-backed X-User-ID binds the created row to the customer"
    )
    assert is_valid_uuid(data["id"])
    fetched = validate_success(api.get_depot(data["id"], headers), 200)
    assert fetched["id"] == data["id"]
    assert fetched["fleet_customer_id"] == customer["id"]
