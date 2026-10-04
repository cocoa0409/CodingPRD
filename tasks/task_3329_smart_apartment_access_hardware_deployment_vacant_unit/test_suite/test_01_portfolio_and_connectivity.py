"""Portfolio creation, wireless-coverage verdicts and the platform's basic guards."""

import pytest

from test_helpers import (
    ADMIN,
    MANAGER,
    ApiErrorId,
    build_user_headers,
    create_property_payload,
    create_unit_payload,
    get_success_data,
    pin_clock,
    provision_building,
    provision_property,
    provision_unit,
    read_unit,
    unauthenticated_headers,
    unknown_role_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Property creation
# ---------------------------------------------------------------------------

def test_property_creation_returns_declared_fields_and_zero_budget(api):
    """PRD §3.1: "The property is created with `budget_committed_cents` at 0 and
    will accrue from there."
    PRD §2.4: "`id` — a unique, server-minted identifier rendered as a UUID."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/entities/property_create_returns_declared_fields_and_zero_budget
    """
    pin_clock()
    resp = api.create_property(
        create_property_payload(
            name="Southgate", address_line="5 South Way", unit_capacity=8,
            temp_budget_cents_per_day=400,
        ),
        ADMIN,
    )
    data = validate_success(resp, 201)

    assert data["name"] == "Southgate"
    assert data["address_line"] == "5 South Way"
    assert data["unit_capacity"] == 8
    assert data["temp_budget_cents_per_day"] == 400
    assert data["budget_committed_cents"] == 0, (
        "budget_committed_cents starts at 0 and is never client-supplied"
    )
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_property_creation_rejects_client_supplied_budget(api):
    """PRD §3.1: "The property is created with `budget_committed_cents` at 0 and
    will accrue from there."
    PRD §2.12: "the body must carry every required field, must carry no unknown
    field, and must not attempt to supply a computed attribute — otherwise
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/property_create_returns_declared_fields_and_zero_budget
    """
    pin_clock()
    resp = api.create_property(
        create_property_payload(budget_committed_cents=9999), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Building connectivity
# ---------------------------------------------------------------------------

def test_connectivity_ok_is_derived_from_design_threshold(api):
    """PRD §2.5: "A `POINT_TO_POINT` building must reach at least -67 dBm. A
    `FIELD_MESH` building must reach at least -75 dBm. A `HUB_RELAY` building
    must reach at least -80 dBm."

    Design: Corner/entities/building_create_derives_connectivity_ok_from_rssi_and_design
    """
    pin_clock()
    prop = provision_property()

    relay = provision_building(
        prop["id"], wifi_rssi_dbm=-80, network_design="HUB_RELAY", name="Relay Wing"
    )
    p2p = provision_building(
        prop["id"], wifi_rssi_dbm=-80, network_design="POINT_TO_POINT", name="P2P Wing"
    )

    assert relay["connectivity_ok"] is True, (
        "-80 dBm clears the HUB_RELAY threshold of -80"
    )
    assert p2p["connectivity_ok"] is False, (
        "-80 dBm does not clear the POINT_TO_POINT threshold of -67"
    )


def test_field_mesh_threshold_is_inclusive_at_minus_75_dbm(api):
    """PRD §2.5: "The comparison is inclusive on the strong side: a building
    measuring exactly its design threshold counts as connected."

    Design: Difficulty/boundary_precision_check/building_connectivity_threshold_inclusive_boundary
    """
    pin_clock()
    prop = provision_property()

    at_edge = provision_building(
        prop["id"], wifi_rssi_dbm=-75, network_design="FIELD_MESH", name="At Edge"
    )
    below = provision_building(
        prop["id"], wifi_rssi_dbm=-76, network_design="FIELD_MESH", name="Below Edge"
    )

    assert at_edge["connectivity_ok"] is True, "-75 == FIELD_MESH threshold"
    assert below["connectivity_ok"] is False, "-76 is one dBm past the threshold"


def test_point_to_point_threshold_is_inclusive_at_minus_67_dbm(api):
    """PRD §2.5: "The comparison is inclusive on the strong side: a building
    measuring exactly its design threshold counts as connected."

    Design: Difficulty/boundary_precision_check/building_connectivity_threshold_inclusive_boundary
    """
    pin_clock()
    prop = provision_property()

    at_edge = provision_building(
        prop["id"], wifi_rssi_dbm=-67, network_design="POINT_TO_POINT", name="P2P Edge"
    )
    below = provision_building(
        prop["id"], wifi_rssi_dbm=-68, network_design="POINT_TO_POINT", name="P2P Below"
    )

    assert at_edge["connectivity_ok"] is True
    assert below["connectivity_ok"] is False


def test_hub_service_age_penalty_flips_connectivity(api):
    """PRD §2.5: "If `last_hub_service_at` is set, the platform subtracts an age
    penalty equal to 0.1 dB per whole day elapsed between `last_hub_service_at`
    and the current logical clock, where the elapsed day count is rounded down
    to a whole number before multiplication."

    Design: Corner/calculations/connectivity_age_penalty_flips_service_adjusted_building
    """
    pin_clock()
    prop = provision_property()

    fresh = provision_building(
        prop["id"], wifi_rssi_dbm=-74, network_design="FIELD_MESH", name="Fresh",
        last_hub_service_at="2026-08-31T00:00:00Z",
    )
    aged = provision_building(
        prop["id"], wifi_rssi_dbm=-74, network_design="FIELD_MESH", name="Aged",
        last_hub_service_at="2026-08-12T00:00:00Z",
    )

    assert fresh["connectivity_ok"] is True, "1 day old: -74 - 0.1 >= -75"
    assert aged["connectivity_ok"] is False, "20 days old: -74 - 2.0 < -75"


# ---------------------------------------------------------------------------
# Unit listing / pagination / uniqueness
# ---------------------------------------------------------------------------

def test_units_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` sets the maximum number of items returned; when it is
    omitted it defaults to 10, and the accepted range is a minimum of 1 and a
    maximum of 100."
    PRD §2.3: "Paged and unpaged list responses alike carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response envelope."

    Design: Corner/entities/units_list_paginates_and_reports_total_count_and_has_more
    """
    pin_clock()
    prop = provision_property(unit_capacity=3)
    for number in ("U-1", "U-2", "U-3"):
        provision_unit(prop["id"], unit_number=number)

    page_one = validate_paginated(
        api.list_units(MANAGER, {"property_id": prop["id"], "limit": 2, "offset": 0})
    )
    data, meta = page_one
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data, meta = validate_paginated(
        api.list_units(MANAGER, {"property_id": prop["id"], "limit": 2, "offset": 2})
    )
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_units_list_defaults_to_page_size_ten_sorted_oldest_first(api):
    """PRD §2.3: "`offset` sets how many items are skipped and defaults to 0.
    Every list endpoint returns its resources sorted by creation timestamp in
    ascending order — that is, oldest `created_at` first."

    Design: Corner/entities/units_list_paginates_and_reports_total_count_and_has_more
    """
    pin_clock()
    prop = provision_property(unit_capacity=3)
    created = [
        provision_unit(prop["id"], unit_number=number)
        for number in ("U-1", "U-2", "U-3")
    ]

    data, meta = validate_paginated(api.list_units(MANAGER, {"property_id": prop["id"]}))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert [u["id"] for u in data] == [u["id"] for u in created]


def test_duplicate_unit_number_is_rejected_within_a_property_only(api):
    """PRD §3.1: "Supplying a `unit_number` that is already in use within the
    property is refused with `ERR_DUPLICATE_UNIT_NUMBER` (409)."

    Design: Corner/validations/duplicate_unit_number_within_property_rejected
    """
    pin_clock()
    first = provision_property(name="P1", address_line="1 One St")
    second = provision_property(name="P2", address_line="2 Two St")
    provision_unit(first["id"], unit_number="U-1")

    duplicate = api.create_unit(first["id"], create_unit_payload(unit_number="U-1"), MANAGER)
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_UNIT_NUMBER, 409)

    other = api.create_unit(second["id"], create_unit_payload(unit_number="U-1"), MANAGER)
    validate_success(other, 201)


def test_building_not_found_when_creating_unit_under_missing_building(api):
    """PRD §2.12: "The refusal status is 404, and the error identifier names the
    resource class that failed: ... `ERR_BUILDING_NOT_FOUND`."

    Design: Corner/errors/building_not_found_on_unit_creation
    """
    pin_clock()
    prop = provision_property()

    resp = api.create_unit(
        prop["id"],
        create_unit_payload(
            unit_number="U-GB1", building_id="99999999-0000-4000-8000-000000000000"
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_BUILDING_NOT_FOUND, 404)


def test_non_existent_property_returns_not_found(api):
    """PRD §2.12: "The refusal status is 404, and the error identifier names the
    resource class that failed: `ERR_PROPERTY_NOT_FOUND`."

    Design: Corner/entities/non_existent_property_returns_not_found
    """
    pin_clock()
    resp = api.get_property("11111111-2222-4333-8444-555555555555", ADMIN)
    error_data = validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND, 404)
    assert error_data["message"].strip()


# ---------------------------------------------------------------------------
# Resident creation guards and derived occupancy
# ---------------------------------------------------------------------------

def test_resident_creation_without_email_is_rejected_before_side_effects(api):
    """PRD §3.4: "A `Resident` record is created by a `PlatformManager`-class
    operator ... carrying the resident's `full_name` and `email`."
    PRD §2.12: "the body must carry every required field, must carry no unknown
    field, and must not attempt to supply a computed attribute — otherwise
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/resident_create_missing_email_returns_invalid_request
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])

    resp = api.create_resident(
        {"property_id": prop["id"], "unit_id": unit["id"], "full_name": "No Email"},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    assert read_unit(prop["id"], unit["id"])["occupancy_status"] == "VACANT", (
        "a rejected creation must not fire the unit-occupancy side effect"
    )


def test_first_resident_immediately_marks_the_unit_occupied(api):
    """PRD §3.4: "creating the first resident against a unit whose
    `occupancy_status` is `VACANT` and which has no other non-`REVOKED` resident
    moves that unit to `OCCUPIED`, recomputes its `hvac_mode` to `OCCUPIED` and
    its `target_setpoint_c` to 22.0 Celsius — the occupied setpoint — and clears
    `unauthorized_entry_detected` to false."

    Design: Corner/cross_cutting_complexity_layers/resident_creation_immediately_marks_unit_occupied
    """
    pin_clock()
    prop = provision_property()
    unit = provision_unit(prop["id"])

    get_success_data(
        api.create_resident(
            {
                "property_id": prop["id"],
                "unit_id": unit["id"],
                "full_name": "Sasha Sync",
                "email": "sasha@x.com",
            },
            MANAGER,
        )
    )

    listed = get_success_data(api.list_units(MANAGER, {"property_id": prop["id"]}))
    current = next(u for u in listed if u["id"] == unit["id"])
    assert current["occupancy_status"] == "OCCUPIED"
    assert current["hvac_mode"] == "OCCUPIED"
    assert current["target_setpoint_c"] == pytest.approx(22.0, abs=0.01)
    assert current["unauthorized_entry_detected"] is False


# ---------------------------------------------------------------------------
# Authentication and role guards
# ---------------------------------------------------------------------------

def test_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that presents a
    `X-User-Role` value the platform does not recognize, is refused with
    `ERR_UNAUTHENTICATED` and an HTTP status of 401."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    pin_clock()
    resp = api.create_property(create_property_payload(name="No Auth"), unauthenticated_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_request_with_unrecognized_role_is_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that presents a
    `X-User-Role` value the platform does not recognize, is refused with
    `ERR_UNAUTHENTICATED` and an HTTP status of 401."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    pin_clock()
    resp = api.create_property(create_property_payload(name="Bad Role"), unknown_role_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_leasing_agent_cannot_create_a_property(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to
    perform the operation it targets is refused with `ERR_FORBIDDEN` and an HTTP
    status of 403."
    PRD §2.1: "`PlatformAdmin` holds exclusive authority over property creation
    and building creation."

    Design: Corner/rbac/leasing_agent_cannot_create_properties
    """
    pin_clock()
    resp = api.create_property(
        create_property_payload(name="Not Allowed"),
        build_user_headers("op-leasing-1", "LeasingAgent"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_property_manager_cannot_create_a_property(api):
    """PRD §2.1: "`PlatformAdmin` holds exclusive authority over property creation
    and building creation, and shares the remaining provisioning and read
    capabilities listed in §4."

    Design: Corner/rbac/leasing_agent_cannot_create_properties
    """
    pin_clock()
    resp = api.create_property(create_property_payload(name="Manager Made"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)