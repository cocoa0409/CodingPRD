"""Entity basics: creation envelope/defaults, light-resource shape, 404/400
paths, uniqueness, the inspection site XOR rule, pagination meta, and the
authentication floor.

Every test translates one design-index instance; PRD citations are verbatim.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_facility,
    assert_strain,
    create_active_room,
    create_active_customer,
    create_catalog_strain,
    create_registered_facility,
    create_strain_payload,
    create_room_payload,
    create_inspection_payload,
    create_customer_payload,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["admin_headers"]
_FM = TEST_USERS["facility_manager_headers"]
_INSPECTOR = TEST_USERS["inspector_headers"]


def test_facility_creation_defaults_and_envelope():
    """PRD Section 2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body".
    PRD Section 3.1: "A facility is born with `registration_status` set to
    `REGISTERED`, and its `suspension_reason` is null until a suspension
    records one."
    PRD Section 2.4: "`version`, an integer starting at 1 that increments on
    every mutation".

    Design: Corner/entities/facility_creation_defaults_and_envelope
    """
    resp = api_client.create_facility(
        {
            "name": "Site Alpha",
            "site_code": "SA-F1",
            "registration_number": "REG-F1",
            "registration_expires_at": "2027-09-01T00:00:00Z",
        },
        _ADMIN,
    )
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert data["registration_status"] == "REGISTERED"
    assert data["version"] == 1
    assert data["suspension_reason"] is None
    assert_facility(data)


def test_strain_immutable_no_version_field():
    """PRD Section 2.4: "Four resource types are deliberately lighter —
    `ModelStrain`, `HealthScreen`, `Allocation`, and `WelfareInspection` carry
    only `id` and `created_at`; both `updated_at` and `version` are absent on
    those four".

    Design: Corner/entities/strain_immutable_no_version_field
    """
    strain = create_catalog_strain(strain_code="C57BL6J")
    data = validate_success(api_client.get_strain(strain["id"], _ADMIN))
    assert "id" in data and "created_at" in data
    assert "version" not in data
    assert "updated_at" not in data
    assert data["strain_code"] == "C57BL6J"
    assert_strain(data)


def test_room_not_found_returns_404():
    """PRD Section 2.4: "If any path identifier, or any foreign key actually
    present in the request body (`room_id`, `strain_id`, `protocol_id`,
    `colony_id`, `order_id`, `cohort_id`, `facility_id`, `customer_id`,
    `source_strain_id`), does not resolve to an existing record, the request
    is rejected with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/room_not_found_returns_404
    """
    resp = api_client.get_room(NON_EXISTENT_UUID, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_room_missing_capacity_returns_invalid_request():
    """PRD Section 2.7: "Missing or mistyped required fields — including the
    inspection site rule that exactly one of `facility_id` or `customer_id`
    may be set — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD Section 2.4: "A field that is required but entirely absent from the
    body is not a 404 case at all — it is a malformed request caught later by
    the validation ladder as `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/room_missing_capacity_returns_invalid_request
    """
    facility = create_registered_facility()
    payload = create_room_payload(facility["id"])
    payload.pop("cage_capacity")
    resp = api_client.create_room(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_room_invalid_enum_rejected():
    """PRD Section 2.7: "An enum field carrying a value outside its declared
    member set is rejected with `ERR_INVALID_ENUM` (HTTP 400)."

    Design: Corner/entities/room_invalid_enum_rejected
    """
    facility = create_registered_facility()
    payload = create_room_payload(facility["id"], barrier_level="SUPER_CLEAN")
    resp = api_client.create_room(payload, _FM)
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM)


def test_duplicate_strain_code_rejected():
    """PRD Section 3.2: "A `PlatformAdmin` registers each research model strain
    with a unique `strain_code` (a collision with an existing strain is
    `ERR_DUPLICATE_KEY`, HTTP 409)".

    Design: Corner/entities/duplicate_strain_code_rejected
    """
    create_catalog_strain(strain_code="C57BL6J")
    payload = create_strain_payload(
        strain_code="C57BL6J",
        species="RAT",
        immune_class="IMMUNOCOMPROMISED",
        breeding_type="OUTBRED",
        min_barrier_level="VF",
        gestation_days=22,
        typical_litter_size=8,
        base_price_cents=2000,
    )
    resp = api_client.create_strain(payload, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY)


def test_contract_polymorphic_site_xor_enforced():
    """PRD Section 3.9: "A `WelfareInspector` schedules an inspection naming
    exactly one site — a `facility_id` for a production site or a
    `customer_id` for a customer site; setting both or neither is
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/contract_polymorphic_site_xor_enforced
    """
    facility = create_registered_facility()
    customer = create_active_customer()
    payload = create_inspection_payload(
        facility_id=facility["id"],
        customer_id=customer["id"],
        inspection_type="ROUTINE",
        scheduled_date="2026-09-05T00:00:00Z",
    )
    resp = api_client.create_inspection(payload, _INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_list_pagination_limit_offset_has_more():
    """PRD Section 2.3: "The `meta` object of a list response carries exactly
    the four pagination fields `limit`, `offset`, `total_count`, and
    `has_more`, where `total_count` reports the full size of the filtered
    collection and `has_more` indicates whether records exist beyond the
    returned window."

    Design: Corner/endpoints/list_pagination_limit_offset_has_more
    """
    facility = create_registered_facility()
    for _ in range(3):
        create_active_room(facility["id"])

    page1, meta1 = validate_paginated(
        api_client.list_facility_rooms(
            facility["id"], _FM, params={"limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api_client.list_facility_rooms(
            facility["id"], _FM, params={"limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_unauthenticated_missing_role_header_returns_401():
    """PRD Section 2.1: "A request in which either header is missing, or whose
    `X-User-Role` value is not one of these seven declared roles, is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_role_header_returns_401
    """
    resp = api_client.create_strain(create_strain_payload(), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
