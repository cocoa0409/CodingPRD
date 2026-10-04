"""Reference-data entities (care stations, veterans, TPAs), list pagination,
network scoping, and the error response envelope."""
from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, api_client,
    validate_error, validate_paginated, validate_success,
    assert_care_station, assert_veteran,
    create_care_station_payload, create_veteran_payload,
    create_station, create_tpa, create_veteran, onboard_provider,
    make_veteran_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["eligibility_clerk_headers"]
NETMGR = TEST_USERS["network_manager_headers"]


def test_care_station_creation_returns_all_fields():
    """PRD §4: "Operations that create a new resource return `201 Created`;
    operations that modify an existing resource, drive a state transition, or
    read data return `200 OK`."
    PRD §2.4: "`version` (integer): a system-managed integer that increments by
    one on every mutation of the resource, including mutations performed by
    automatic cascades."

    Design: Corner/entities/care_station_creation_returns_all_fields
    """
    payload = create_care_station_payload(
        name="Station Alpha", primary_wait_days=10, specialty_wait_days=15,
        service_codes=["PT_EVAL", "CARD"],
    )
    resp = api_client.create_care_station(payload, ADMIN)
    data = validate_success(resp, 201)

    assert_care_station(data)
    assert data["name"] == "Station Alpha"
    assert data["latitude"] == 40.0 and data["longitude"] == -75.0
    assert data["primary_wait_days"] == 10
    assert data["specialty_wait_days"] == 15
    assert data["service_codes"] == ["PT_EVAL", "CARD"]
    assert data["version"] == 1


def test_veteran_creation_and_retrieval_round_trip():
    """PRD §3.2: "An `EligibilityClerk` enrolls each **veteran** with a
    `full_name`, the `home_station_id` of the veteran's VA home station (the
    yardstick against which access standards are measured), an integer
    `priority_group` from 1 to 8, and the residence coordinates `home_latitude`
    and `home_longitude` that serve as the drive-time origin."

    Design: Corner/entities/veteran_creation_and_retrieval_round_trip
    """
    station = create_station()
    payload = create_veteran_payload(
        station["id"], full_name="V Round", priority_group=6,
        home_latitude=41.0, home_longitude=-74.5,
    )
    created = validate_success(api_client.create_veteran(payload, CLERK), 201)
    assert_veteran(created)

    got = validate_success(
        api_client.get_veteran(created["id"], make_veteran_headers(created["id"]))
    )
    assert got["full_name"] == "V Round"
    assert got["priority_group"] == 6
    assert got["home_station_id"] == station["id"]
    assert got["home_latitude"] == 41.0 and got["home_longitude"] == -74.5


def test_veteran_create_missing_required_field_returns_invalid_request():
    """PRD §2.8: "Required fields must be present, types must be correct, enum
    members must be valid, arrays that require elements must contain at least
    one, and exactly one of `urgent_care_visit_id` or `appointment_id` must be
    present on a prescription fill request; otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/veteran_create_missing_required_field_returns_invalid_request
    """
    create_station()
    payload = {
        "full_name": "V NoStation",
        "priority_group": 6,
        "home_latitude": 41.0,
        "home_longitude": -74.5,
    }
    resp = api_client.create_veteran(payload, CLERK)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_veteran_create_invalid_request_for_priority_group_range():
    """PRD §3.2: "An `EligibilityClerk` enrolls each **veteran** with a
    `full_name`, the `home_station_id` of the veteran's VA home station (the
    yardstick against which access standards are measured), an integer
    `priority_group` from 1 to 8, and the residence coordinates `home_latitude`
    and `home_longitude` that serve as the drive-time origin."
    PRD §2.8: "Required fields must be present, types must be correct, enum
    members must be valid, arrays that require elements must contain at least
    one, and exactly one of `urgent_care_visit_id` or `appointment_id` must be
    present on a prescription fill request; otherwise `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/veteran_create_invalid_request_for_priority_group_range
    """
    station = create_station()
    payload = create_veteran_payload(station["id"], full_name="V BadPG",
                                     priority_group=9)
    resp = api_client.create_veteran(payload, CLERK)
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_tpa_not_found_returns_404():
    """PRD §2.8: "Path identifiers are validated left to right, and foreign
    keys supplied in the request body must reference existing resources;
    otherwise `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/tpa_not_found_returns_404
    """
    coord = TEST_USERS["care_coordinator_headers"]
    resp = api_client.get_tpa(NON_EXISTENT_UUID, coord)
    validate_error(resp, "ERR_NOT_FOUND")


def test_error_envelope_shape_on_404():
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format:"
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/endpoints/error_envelope_shape_on_404
    """
    resp = api_client.get_tpa(NON_EXISTENT_UUID, ADMIN)
    err = validate_error(resp, "ERR_NOT_FOUND")
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(err["message"], str) and err["message"]
    assert body["meta"]["api_request_id"]


def test_veterans_list_pagination_limit_offset_has_more():
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; it defaults to 10 when omitted, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies how many items to skip and
    defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/veterans_list_pagination_limit_offset_has_more
    """
    station = create_station()
    for i in range(12):
        create_veteran(station, full_name=f"V {i + 1:02d}",
                       priority_group=(i % 8) + 1)

    page1, meta1 = validate_paginated(
        api_client.list_veterans(CLERK, params={"limit": 10, "offset": 0})
    )
    assert len(page1) == 10
    assert meta1["total_count"] == 12 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api_client.list_veterans(CLERK, params={"limit": 10, "offset": 10})
    )
    assert len(page2) == 2
    assert meta2["total_count"] == 12 and meta2["has_more"] is False


def test_tpa_provider_subresource_list_scoped_to_network():
    """PRD §3.1: "The provider's administering `tpa_id` is taken from the
    creation path, not from the payload."
    PRD §3.1: "A network's provider roster can be listed with an optional
    `credentialing_status` filter."

    Design: Corner/endpoints/tpa_provider_subresource_list_scoped_to_network
    """
    tpa_a = create_tpa(name="TPA A", region_code="RA")
    tpa_b = create_tpa(name="TPA B", region_code="RB")
    onboard_provider(tpa_a, name="P-A1")
    onboard_provider(tpa_b, name="P-B1", service_codes=["CARD"],
                     contract_scheduling="VAMC")
    onboard_provider(tpa_b, name="P-B2", service_codes=["CARD"])

    items_b, meta_b = validate_paginated(
        api_client.list_providers(tpa_b["id"], NETMGR)
    )
    assert meta_b["total_count"] == 2 and len(items_b) == 2
    assert all(p["tpa_id"] == tpa_b["id"] for p in items_b)

    items_a, meta_a = validate_paginated(
        api_client.list_providers(tpa_a["id"], NETMGR)
    )
    assert meta_a["total_count"] == 1 and len(items_a) == 1
    assert items_a[0]["tpa_id"] == tpa_a["id"]
