"""Response envelope shape and read-after-write visibility."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_community,
    get_community,
    get_department_of,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
)

COORD = TEST_USERS["evaluation_coordinator_headers"]
INSURER = TEST_USERS["insurer_headers"]


def test_envelope_success_shape_object(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." and "The `response_type` is
    either "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/envelope_success_shape_object
    """
    resp = api.create_community(
        {
            "name": "Envelope", "state_code": "TX", "population": 4000,
            "area_sq_miles": 40, "rural_area_pct": 20, "dept_type": "CAREER",
            "needed_fire_flow_gpm": 1000, "storage_capacity_gal": 0,
            "supply_works_capacity_gpm": 500, "daily_consumption_gpm": 100,
        },
        COORD,
    )
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]
    assert data["id"]


def test_envelope_error_shape_on_404(api):
    """PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error." and "The `message` provides a
    human-readable explanation of what went wrong."

    Design: Corner/endpoints/envelope_error_shape_on_404
    """
    resp = api.get_community(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_COMMUNITY_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_COMMUNITY_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_list_envelope_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned;
    when omitted it defaults to 10" and "The `offset` parameter skips a
    number of items and defaults to 0."

    Design: Corner/endpoints/list_envelope_pagination_defaults
    """
    create_community(api, name="Solo")
    resp = api.list_communities(COORD)
    rows, meta = validate_paginated(resp)
    assert len(rows) == 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_immediate_read_after_write_visibility(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." A created community is fully visible through its single-resource
    GET within the same logical instant.

    Design: Corner/consistency_model/immediate_read_after_write_visibility
    """
    community = create_community(api, name="Immediate", state_code="WA", dept_type="VOLUNTEER")
    fetched = get_community(api, community["id"])
    assert fetched["id"] == community["id"]
    assert fetched["state_code"] == "WA"
    assert fetched["status"] == "REGISTERED"
    department = get_department_of(api, community["id"])
    assert department["dept_type"] == "VOLUNTEER"
    assert department["community_id"] == community["id"]
