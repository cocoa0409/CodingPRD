"""Zone CRUD, envelope, defaults, and validation tests (queue B: entities)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_zone_payload,
    create_sku_payload,
    set_clock,
    create_zone,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]


def test_create_zone_returns_201_with_common_fields(api):
    """PRD §4: "Endpoints that create a new resource respond with HTTP 201 and
    the created resource."
    PRD §2.5: "Every resource carries an `id` (a server-minted UUID with no
    type prefix), a `created_at` and `updated_at` (ISO 8601 UTC timestamps
    with three fractional digits), and an integer `version` starting at 1."
    PRD §3.1: "New zones are born with `posture` `OPEN`."

    Design: Corner/entities/create_zone_returns_201_with_common_fields
    """
    set_clock()
    resp = api.create_zone(
        create_zone_payload(
            zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
            max_human_occupancy=2,
        ),
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["version"] == 1, f"new zone version must be 1, got {data['version']}"
    assert data["posture"] == "OPEN", f"new zone posture must be OPEN, got {data['posture']}"


def test_create_zone_missing_zone_code_fails(api):
    """PRD §2.6: "Generic request-shape failures — a missing required field,
    a bad enum value, a type mismatch, or a negative quantity — are rejected
    with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_zone_missing_zone_code_fails
    """
    set_clock()
    resp = api.create_zone(
        {
            "grid_x": 0, "grid_y": 0, "width": 10, "height": 10,
            "max_human_occupancy": 2,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_zone_by_id_returns_record(api):
    """PRD §4: "list and fetch endpoints respond with HTTP 200."

    Design: Corner/entities/get_zone_by_id_returns_record
    """
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10)
    resp = api.get_zone(zone["id"], ADMIN)
    data = validate_success(resp, expected_status=200)
    assert data["id"] == zone["id"]


def test_get_zone_missing_id_returns_404(api):
    """PRD §2.6: "Path existence — every path-templated identifier resolves
    to an existing entity, evaluated left to right (`ERR_NOT_FOUND`, 404)."

    Design: Corner/entities/get_zone_missing_id_returns_404
    """
    set_clock()
    resp = api.get_zone(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_zone_list_pagination_envelope(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` envelope."

    Design: Corner/entities/zone_list_pagination_envelope
    """
    for i, code in enumerate(("Z1", "Z2", "Z3")):
        create_zone(
            zone_code=code, grid_x=i * 5, grid_y=0, width=5, height=5,
            max_human_occupancy=1,
        )
    resp = api.list_zones(ADMIN, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true with limit=2 of 3"
    assert len(data) == 2


def test_drive_unit_default_status_active(api):
    """PRD §3.1: "A unit is born `ACTIVE` with `battery_pct` 100,
    `odometer_cells` 0, and `charge_cycle_count` 0."

    Design: Corner/entities/drive_unit_default_status_active
    """
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=5, height=5)
    resp = api.create_drive_unit(
        {"unit_code": "DU1", "home_zone_id": zone["id"]}, ADMIN
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["battery_pct"] == 100


def test_invalid_velocity_class_enum_rejected(api):
    """PRD §2.6: "Generic request-shape failures — a missing required field,
    a bad enum value, a type mismatch, or a negative quantity — are rejected
    with `ERR_VALIDATION` (HTTP 400)."
    PRD §3.2: "A `Sku` is created with a unique immutable `sku_code` and a
    `velocity_class` of `HIGH`, `MEDIUM`, or `LOW`."

    Design: Corner/entities/invalid_velocity_class_enum_rejected
    """
    set_clock()
    resp = api.create_sku(
        create_sku_payload(sku_code="SKUX", velocity_class="TURBO"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_child_creation_with_wrong_parent_returns_404(api):
    """PRD §2.6: "Body reference existence — every body-referenced foreign key
    (`pod_id`, `sku_id`, `station_id`, `zone_id`, `exception_id`,
    `charger_id`, `drive_unit_id`, `line_id`, `order_id`) resolves
    (`ERR_NOT_FOUND`, 404)."

    Design: Corner/entities/child_creation_with_wrong_parent_returns_404
    """
    set_clock()
    resp = api.create_pod(
        {"pod_code": "PX", "zone_id": NON_EXISTENT_UUID, "slot_capacity": 5},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
