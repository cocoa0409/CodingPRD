"""Property creation basics: required fields, enums, not-found, pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    RM,
    ApiErrorId,
    assert_property,
    create_property,
    create_property_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_property_missing_rights_fee_returns_invalid_request(api):
    """PRD §2.5: "4. `ERR_INVALID_REQUEST` (HTTP 400) — missing or unknown
    field, bad enum value, bad datetime format."

    Design: Corner/entities/create_property_missing_required_field_returns_invalid_request
    """
    payload = create_property_payload()
    del payload["rights_fee_cents"]
    resp = api.create_property(payload, RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_property_bad_sport_enum_returns_invalid_request(api):
    """PRD §2.5: "4. `ERR_INVALID_REQUEST` (HTTP 400) — missing or unknown
    field, bad enum value, bad datetime format."
    PRD §3.1: "`sport` (one of `NFL`, `NBA`, `MLB`, `SOCCER`, `GOLF`,
    `RACING`, `TENNIS`)"

    Design: Corner/entities/property_sport_enum_rejects_invalid_value
    """
    payload = create_property_payload(sport="CURLING")
    resp = api.create_property(payload, RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_property_not_found_returns_404(api):
    """PRD §2.5: "3. `ERR_NOT_FOUND` (HTTP 404) — any path-templated or
    body-referenced resource does not exist; validated left-to-right along
    the URL hierarchy."

    Design: Corner/entities/get_property_not_found_returns_404
    """
    resp = api.get_property(NON_EXISTENT_UUID, RM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_properties_pagination_envelope(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum
    of 100. `offset` defaults to 0. Responses for list endpoints include
    `limit`, `offset`, `total_count`, and `has_more` in the `meta` envelope."

    Design: Corner/entities/list_properties_pagination_envelope
    """
    create_property()
    create_property()
    resp = api.list_properties(RM)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(data) == 2
    for row in data:
        assert_property(row)
