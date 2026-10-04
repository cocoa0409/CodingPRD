"""Corner tests: member/vehicle entity rules, uniqueness, envelope, ownership."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_member,
    assert_vehicle,
    create_member,
    create_member_payload,
    create_vehicle_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_member_creation_defaults_status_active(api):
    """PRD §3.1: "New members arrive in `ACTIVE` status and can later be moved
    to `SUSPENDED` and back by an administrator without affecting any
    in-flight policies".

    Design: Corner/entities/member_creation_defaults_status_active
    """
    resp = api.create_member(
        create_member_payload(full_name="Rae", email="rae@x.com"), ADMIN
    )
    data = validate_success(resp, expected_status=201)
    assert_member(data)
    assert data["status"] == "ACTIVE", (
        f"New member must arrive in ACTIVE status, got {data['status']}"
    )


def test_vehicle_creation_computed_fields_initialized(api):
    """PRD §3.1: "The vehicle arrives in `REGISTERED` status with its
    documentation dimension at `INCOMPLETE`, and its eligibility is computed
    immediately".
    PRD §3.3: "`accepted_photo_count` counts the vehicle's photos in
    `ACCEPTED` status".

    Design: Corner/entities/vehicle_creation_computed_fields_initialized
    """
    member, m_headers = create_member(full_name="Sam", email="sam@x.com")
    resp = api.create_vehicle(create_vehicle_payload(vin="VIN100"), m_headers)
    data = validate_success(resp, expected_status=201)
    assert_vehicle(data)
    assert data["documentation_status"] == "INCOMPLETE"
    assert data["accepted_photo_count"] == 0
    assert data["status"] == "REGISTERED"


def test_vehicle_invalid_enum_rejected(api):
    """PRD §2.8: "Malformed bodies (missing required field, wrong type,
    invalid enum value) are rejected with `ERR_VALIDATION` (HTTP 400)."
    PRD §3.1: "a `vehicle_class` of `ANTIQUE`, `CLASSIC`, `MODERN_COLLECTIBLE`,
    or `EXOTIC`".

    Design: Corner/entities/vehicle_invalid_enum_rejected
    """
    member, m_headers = create_member(full_name="Tom", email="tom@x.com")
    resp = api.create_vehicle(
        create_vehicle_payload(vin="VIN101", vehicle_class="SUPERCAR"), m_headers
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_member_creation_missing_required_field_rejected(api):
    """PRD §2.8: "Malformed bodies (missing required field, wrong type,
    invalid enum value) are rejected with `ERR_VALIDATION` (HTTP 400)."
    PRD §3.1: "creating a `Member` record carrying the collector's
    `full_name`, a unique `email`".

    Design: Corner/entities/member_creation_missing_required_field_rejected
    """
    resp = api.create_member(
        {"full_name": "NoEmail", "has_daily_driver": True,
         "driving_record_status": "CLEAN"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_get_vehicle_not_found_returns_404(api):
    """PRD §2.8: "Path-templated identifiers are then resolved left to right,
    each missing id producing `ERR_NOT_FOUND`."

    Design: Corner/entities/get_vehicle_not_found_returns_404
    """
    resp = api.get_vehicle(NON_EXISTENT_UUID, UW)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_members_list_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/members_list_pagination_envelope
    """
    validate_success(
        api.create_member(create_member_payload(full_name="P1", email="p1@x.com"), ADMIN),
        expected_status=201,
    )
    validate_success(
        api.create_member(create_member_payload(full_name="P2", email="p2@x.com"), ADMIN),
        expected_status=201,
    )
    resp = api.list_members(ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return one member, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_duplicate_vin_rejected(api):
    """PRD §3.1: "the member registers each collector vehicle by supplying its
    `vin` (unique across the fleet; a duplicate is rejected with
    `ERR_DUPLICATE_VIN`)".

    Design: Corner/entities/duplicate_vin_rejected
    """
    member, m_headers = create_member(full_name="Uma", email="uma@x.com")
    validate_success(
        api.create_vehicle(create_vehicle_payload(vin="DUP1"), m_headers),
        expected_status=201,
    )
    resp = api.create_vehicle(
        create_vehicle_payload(vin="DUP1", year=1971, model="Torino"), m_headers
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VIN)


def test_vehicle_child_requires_owning_member(api):
    """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of
    the acting `Member` record; ownership checks on any resource that
    references a member (vehicles, policies, drivers, usage events, claims,
    restoration projects, roadside dispatches, event registrations) compare
    the resource's owning `member_id` — directly or through its parent chain —
    against `X-User-ID`."

    Design: Corner/entities/vehicle_child_requires_owning_member
    """
    member_a, ma_headers = create_member(full_name="A", email="a2@x.com")
    create_member(full_name="B", email="b2@x.com")
    resp = api.create_vehicle(create_vehicle_payload(vin="VIN102"), ma_headers)
    data = validate_success(resp, expected_status=201)
    assert data["member_id"] == member_a["id"], (
        "Vehicle ownership must be bound to the acting member's X-User-ID"
    )
