"""Corner-design section: endpoints."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_region, setup_redeemed_offer, inspect_offer, get_offer,
    make_dealer_headers, NON_EXISTENT_UUID, ApiErrorId,
    is_valid_uuid, is_iso8601_timestamp,
)
from test_helpers.fixtures import ADMIN, DATAOPS


def test_list_endpoints_paginate_with_defaults(api):
    """PRD §2.3: "limit caps the number of items returned; it defaults to 10,
    with a minimum of 1 and a maximum of 100. offset skips that many items
    from the front of the result set and defaults to 0." and "The meta object
    of a list response carries four pagination fields: limit, offset,
    total_count, and has_more."

    Design: Corner/endpoints/list_endpoints_paginate_with_defaults
    """
    for i in range(1, 13):
        validate_success(api.create_region(
            {"region_code": f"R{i:02d}", "name": f"R{i:02d}"}, ADMIN), 201)

    data, meta = validate_paginated(api.list_regions(ADMIN))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert len(data) == 10


def test_error_envelope_shape_is_fixed(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with "The meta object for error responses
    contains only api_request_id and api_request_timestamp", response_type
    "error", and data carrying "error_id" plus "The message provides a
    human-readable explanation of what went wrong."

    Design: Corner/endpoints/error_envelope_shape_is_fixed
    """
    res = api.get_region(NON_EXISTENT_UUID, ADMIN)
    body = res.json()
    assert res.status_code == 404
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {
        "api_request_id", "api_request_timestamp"}
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND.value
    assert isinstance(body["data"]["message"], str)
    assert len(body["data"]["message"]) > 0


def test_offer_inspect_is_conditional_action(api):
    """PRD §3.6: "A DealerPartner inspects a QUOTED offer by supplying an
    inspected_condition_tier" — inspection is defined only from QUOTED, so
    inspecting an already-REDEEMED offer fails the state precondition with
    ERR_INVALID_STATE (HTTP 409).

    Design: Corner/endpoints/offer_inspect_is_conditional_action
    """
    env = setup_redeemed_offer(segment="SEDAN", price_cents=2000000)
    offer = env["offer"]
    source = env["source"]
    assert offer["status"] == "REDEEMED"

    res = api.inspect_cash_offer(
        offer["id"], {"inspected_condition_tier": "FAIR"},
        make_dealer_headers(source["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_offer(offer["id"])["status"] == "REDEEMED"
