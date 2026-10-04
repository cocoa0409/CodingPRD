"""Endpoint-shape corners: pagination defaults and offsets, FK filtering,
and the success/error response envelopes (PRD §2.2, §2.3, §3.5)."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_and_activate_agreement,
    create_configuration,
    create_dealer,
    create_order,
    make_dealer_headers,
    setup_dealer_world,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_pagination_defaults_and_offset(api):
    """PRD §2.3: "The `limit` parameter defaults to 10, with a minimum of 1
    and a maximum of 100; the `offset` parameter defaults to 0. List
    responses carry the pagination fields `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object."

    Design: Corner/endpoints/ep_pagination_defaults_and_offset
    """
    dealer = create_dealer(api)
    for i in range(1, 12):
        create_configuration(api, dealer["id"], name=f"C{i:02d}")

    headers = make_dealer_headers(dealer["id"])
    data, meta = validate_paginated(api.list_configurations(headers))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 11
    assert meta["has_more"] is True
    assert len(data) == 10

    data2, meta2 = validate_paginated(
        api.list_configurations(headers, params={"offset": 10})
    )
    assert meta2["offset"] == 10
    assert meta2["total_count"] == 11
    assert meta2["has_more"] is False
    assert len(data2) == 1


def test_filter_project_orders_by_agreement(api):
    """PRD §3.5: "The order list filters by `dealer_id`,
    `volume_agreement_id`, `configuration_id`, and `status`".

    Design: Corner/endpoints/ep_filter_project_orders_by_agreement
    """
    ctx = setup_dealer_world(api)
    dealer_id = ctx["dealer"]["id"]
    agreement_b, _end_user_b = create_and_activate_agreement(api)
    spec = create_configuration(api, dealer_id, name="Chairs")

    order_a = create_order(api, ctx["agreement"]["id"], spec["id"], dealer_id)
    create_order(api, agreement_b["id"], spec["id"], dealer_id)

    data, meta = validate_paginated(
        api.list_project_orders(
            make_dealer_headers(dealer_id),
            params={"volume_agreement_id": ctx["agreement"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == order_a["id"]
    assert data[0]["volume_agreement_id"] == ctx["agreement"]["id"]


def test_response_envelope_shapes(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`." — success bodies
    carry `meta`, `response_type` and `data`; on errors, "The `error_id` is
    a unique, machine-readable string that identifies the specific error."
    and "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/ep_response_envelope_shapes
    """
    created = api.create_dealer(
        {
            "name": "Dealer Alpha",
            "territory_codes": ["MI"],
            "service_capability_level": 4,
        },
        ADMIN,
    )
    dealer = validate_success(created, 201)
    body = created.json()
    assert body["response_type"] == "object"
    assert body["data"]["id"] == dealer["id"]
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)

    missing = api.get_configuration(
        NON_EXISTENT_UUID, make_dealer_headers(dealer["id"])
    )
    validate_error(missing, ApiErrorId.ERR_CONFIGURATION_NOT_FOUND)
    err_body = missing.json()
    assert err_body["response_type"] == "error"
    assert isinstance(err_body["meta"]["api_request_id"], str)
    assert isinstance(err_body["data"]["message"], str)
    assert err_body["data"]["message"].strip()
