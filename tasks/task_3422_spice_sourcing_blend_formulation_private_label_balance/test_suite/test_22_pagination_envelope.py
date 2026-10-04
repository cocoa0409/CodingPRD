"""List pagination meta and the success/error response envelopes."""
from test_helpers import (
    api_client, validate_paginated, validate_error, ApiErrorId, TEST_USERS,
    NON_EXISTENT_UUID, create_supplier, create_received_lot,
)


def test_list_pagination_and_response_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`, where
    `total_count` is the full number of matching records and `has_more`
    indicates whether any records exist beyond the returned page." PRD §2.2:
    "The `response_type` is either "object" for a single resource or "array"
    for a list of resources." PRD §2.2 error envelope: the data carries
    "`error_id`" and "`message`".

    Three lots, limit 2: page 1 has 2 rows with has_more true, page 2 has 1
    row with has_more false; an unknown id yields the error envelope.

    Design: Corner/endpoints/list_pagination_and_response_envelope
    """
    supplier = create_supplier()
    for qty in (10, 20, 30):
        create_received_lot(supplier["id"], spice_code="CUMIN",
                            origin_region="Aleppo", quantity_kg=qty,
                            flavor_intensity_units=50.0)
    headers = TEST_USERS["supply_planner_headers"]

    resp = api_client.list_lots(headers, params={"limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    assert meta1["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in meta1

    resp = api_client.list_lots(headers, params={"limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp)
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2

    resp = api_client.get_lot(NON_EXISTENT_UUID, headers)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert err["message"]
    assert "api_request_id" in body["meta"]
