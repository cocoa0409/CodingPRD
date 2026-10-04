"""Mill creation corner cases (PRD §3.1, §2.4, §2.7)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error, validate_paginated,
    assert_mill, create_mill_payload,
)

PM = TEST_USERS["plant_manager_headers"]


def test_mill_create_returns_common_fields_and_normal_posture():
    """PRD §3.1: "The new mill starts in `posture` `NORMAL` and answers HTTP 201."
    PRD §2.4: "Resources flagged as carrying the common field set additionally carry
    `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional
    digits, and `version`, an integer that starts at 1 and increments by exactly 1
    on every mutation of that resource."

    Design: Corner/entities/mill_create_returns_common_fields_and_normal_posture
    """
    resp = api_client.create_mill(
        create_mill_payload(name="Berkshire Bar Mill", division="CONSTRUCTION"), PM
    )
    data = validate_success(resp, 201)
    assert_mill(data)
    assert data["posture"] == "NORMAL"
    assert data["version"] == 1
    assert resp.json()["meta"]["api_request_id"].startswith("req_")
    assert resp.json()["meta"]["api_request_timestamp"]


def test_mill_create_with_out_of_enum_division_returns_invalid_request():
    """PRD §3.1: "a `division` value of `CONSTRUCTION`, `AUTOMOTIVE`, or `ENERGY`
    naming the market the division primarily serves"
    PRD §2.7: "(3) request well-formedness — malformed body, missing required field,
    out-of-enum value, or out-of-range number ... yields `ERR_INVALID_REQUEST`"

    Design: Corner/entities/mill_create_with_out_of_enum_division_returns_invalid_request
    """
    resp = api_client.create_mill(
        create_mill_payload(name="Bad Division Mill", division="SOLAR"), PM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    rows, meta = validate_paginated(api_client.list_mills(PM))
    assert meta["total_count"] == 0, f"no mill may persist after a 400, got {meta['total_count']}"
