"""Load posting validation and search behavior."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    TEST_USERS, ApiErrorId,
    set_test_clock, setup_verified_broker, setup_verified_carrier,
    post_load, create_load_post_payload,
    make_broker_admin_headers, make_carrier_admin_headers,
    create_broker, create_credit_event, get_broker,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]


def test_load_post_create_missing_origin_returns_invalid_request():
    """PRD §3.3: "A `BrokerAdmin` posts a load by supplying `origin` and
    `destination` market codes, an `equipment_type` of `DRY_VAN`, `REEFER`, or
    `FLATBED`, a pickup window `pickup_window_start` to `pickup_window_end`,
    and a `rate_offer_cents`."

    Design: Corner/entities/load_post_create_missing_origin_returns_invalid_request
    """
    set_test_clock()
    bctx = setup_verified_broker()
    payload = create_load_post_payload()
    del payload["origin"]
    resp = api_client.create_load_post(payload, bctx["broker_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows, meta = validate_paginated(api_client.list_load_posts(
        ADMIN, params={"broker_org_id": bctx["broker"]["id"]}))
    assert rows == []


def test_load_post_create_with_out_of_enum_equipment_returns_invalid_request():
    """PRD §3.3: "A `BrokerAdmin` posts a load by supplying `origin` and
    `destination` market codes, an `equipment_type` of `DRY_VAN`, `REEFER`, or
    `FLATBED`, a pickup window `pickup_window_start` to `pickup_window_end`,
    and a `rate_offer_cents`."

    Design: Corner/entities/load_post_create_with_out_of_enum_equipment_returns_invalid_request
    """
    set_test_clock()
    bctx = setup_verified_broker()
    resp = api_client.create_load_post(
        create_load_post_payload(equipment_type="TANKER"), bctx["broker_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_load_post_list_paginates_with_total_count_and_has_more():
    """PRD §2.3: "List endpoints accept two query parameters: `limit`,
    defaulting to 10 with a minimum of 1 and a maximum of 100, and `offset`,
    defaulting to 0."

    Design: Corner/entities/load_post_list_paginates_with_total_count_and_has_more
    """
    set_test_clock()
    bctx = setup_verified_broker()
    post_load(bctx)
    post_load(bctx)
    post_load(bctx, equipment_type="REEFER", rate_offer_cents=120000)
    bid = bctx["broker"]["id"]

    rows, meta = validate_paginated(api_client.list_load_posts(
        bctx["broker_headers"], params={"broker_org_id": bid, "limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows2, meta2 = validate_paginated(api_client.list_load_posts(
        bctx["broker_headers"], params={"broker_org_id": bid, "limit": 2, "offset": 2}))
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    rows3, meta3 = validate_paginated(api_client.list_load_posts(
        bctx["broker_headers"], params={"broker_org_id": bid, "equipment_type": "REEFER"}))
    assert len(rows3) == 1

    rows4, meta4 = validate_paginated(api_client.list_load_posts(
        bctx["broker_headers"], params={"broker_org_id": bid}))
    assert meta4["limit"] == 10
    assert meta4["offset"] == 0
    assert len(rows4) == 3


def test_broker_search_rows_integrate_credit_badge_and_authority_status():
    """PRD §3.3: "Each returned load row is enriched with two trust signals
    from the posting broker: `broker_credit_badge`, the broker's current
    credit badge, and `broker_authority_status`, the broker's current
    authority verification status"

    Design: Corner/entities/broker_search_rows_integrate_credit_badge_and_authority_status
    """
    set_test_clock()
    bctx = setup_verified_broker()
    cctx = setup_verified_carrier()
    post_load(bctx)
    bid = bctx["broker"]["id"]

    rows, _ = validate_paginated(api_client.list_load_posts(
        cctx["carrier_headers"], params={"broker_org_id": bid}))
    assert len(rows) == 1
    assert rows[0]["broker_credit_badge"] == "STANDARD"
    assert rows[0]["broker_authority_status"] == "VERIFIED"

    create_credit_event(bid, cctx["carrier"]["id"],
                        invoice_amount_cents=100000, days_to_pay=60)
    rows2, _ = validate_paginated(api_client.list_load_posts(
        cctx["carrier_headers"], params={"broker_org_id": bid}))
    assert len(rows2) == 1
    # score: avg 60 -> raw 40, confidence 0.1 -> 67, still STANDARD
    assert rows2[0]["broker_credit_badge"] == "STANDARD"
