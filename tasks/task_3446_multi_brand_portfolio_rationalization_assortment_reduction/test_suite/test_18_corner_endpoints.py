"""Corner queue: endpoint-surface claims — pagination, the response envelope,
list filters, 201-vs-200 status discipline, and the TSA reverse lookup.
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_plant,
    create_announce_closure_payload,
    create_brand_payload,
    create_item_payload,
    create_plant,
    create_rationalization_case_payload,
    get_tsa_for_divestiture,
    setup_divestiture_spa_signed,
    setup_listed_item,
    validate_created,
    validate_ok,
    validate_paginated,
)

PM = TEST_USERS["portfolio_manager_headers"]
PM_PROPOSER = TEST_USERS["portfolio_manager_proposer_headers"]


def test_pagination_limit_offset_has_more_on_plants():
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return; when not provided it defaults to 10, and its accepted range runs
    from a minimum of 1 to a maximum of 100. The `offset` parameter specifies
    how many items to skip and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the four pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/pagination_limit_offset_has_more_on_plants
    """
    for _ in range(12):
        create_plant(quarterly_capacity_units=1000)
    page1, meta1 = validate_paginated(api_client.list_plants(PM, params={"limit": 10}))
    assert len(page1) == 10
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10 and meta1["offset"] == 0
    for plant in page1:
        assert_plant(plant)
    page2, meta2 = validate_paginated(
        api_client.list_plants(PM, params={"limit": 10, "offset": 10})
    )
    assert len(page2) == 2
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False
    assert meta2["offset"] == 10


def test_response_envelope_shape_on_create_and_list():
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/response_envelope_shape_on_create_and_list
    """
    resp_create = api_client.create_brand(create_brand_payload(name="B-EP2"), PM)
    validate_created(resp_create)
    body_create = resp_create.json()
    assert body_create["response_type"] == "object"
    assert body_create["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body_create["meta"]
    resp_list = api_client.list_brands(PM)
    validate_ok(resp_list)
    body_list = resp_list.json()
    assert body_list["response_type"] == "array"
    assert "api_request_id" in body_list["meta"]
    assert "api_request_timestamp" in body_list["meta"]


def test_filter_items_by_item_status():
    """PRD §4: "List items, optionally filtered by `brand_id`,
    `primary_plant_id`, or `item_status`."

    Design: Corner/endpoints/filter_items_by_item_status
    """
    brand, plant, item1 = setup_listed_item()
    item2 = validate_created(
        api_client.create_item(
            create_item_payload(brand["id"], plant["id"]), PM
        )
    )
    api_client.create_rationalization_case(
        create_rationalization_case_payload(item2["id"]), PM_PROPOSER
    )
    listed, meta_l = validate_paginated(
        api_client.list_items(PM, params={"item_status": "LISTED"})
    )
    assert meta_l["total_count"] == 1
    assert [i["id"] for i in listed] == [item1["id"]]
    cut, meta_c = validate_paginated(
        api_client.list_items(PM, params={"item_status": "CUT_PROPOSED"})
    )
    assert meta_c["total_count"] == 1
    assert [i["id"] for i in cut] == [item2["id"]]


def test_creates_return_201_and_actions_return_200():
    """PRD §4: "Endpoints that create a new resource respond with HTTP 201 and
    the created resource in `data`; endpoints that modify an existing resource,
    record an event, or perform a read respond with HTTP 200."

    Design: Corner/endpoints/creates_return_201_and_actions_return_200
    """
    plant = create_plant(quarterly_capacity_units=1000)
    resp_create = api_client.create_brand(create_brand_payload(name="B-EP4"), PM)
    validate_created(resp_create)  # 201 on creation
    resp_action = api_client.announce_plant_closure(
        plant["id"], create_announce_closure_payload("2027-03-01T00:00:00Z"), PM
    )
    data = validate_ok(resp_action)  # 200 on the state-changing action
    assert data["plant_status"] == "CLOSING"
    assert data["closure_date"] is not None


def test_tsa_reverse_lookup_via_divestiture_filter():
    """PRD §3.5: "The TSA list endpoint, filterable by `divestiture_id` or
    `tsa_status`, is the only read channel for the agreement created here."
    PRD §2.5: "List endpoints that accept foreign-key filters (such as
    `brand_id` on the item list, `item_id` on the case list, or
    `divestiture_id` on the TSA list) provide reverse reachability from a
    parent to its children."

    Design: Corner/endpoints/tsa_reverse_lookup_via_divestiture_filter
    """
    _, divestiture, tsa = setup_divestiture_spa_signed()
    tsas, meta = validate_paginated(
        api_client.list_tsas(PM, params={"divestiture_id": divestiture["id"]})
    )
    assert meta["total_count"] == 1
    assert len(tsas) == 1
    assert tsas[0]["id"] == tsa["id"]
    assert tsas[0]["tsa_status"] == "DRAFT"
    assert tsas[0]["divestiture_id"] == divestiture["id"]
    # Round-trip: GET by id returns the same agreement.
    fetched = validate_ok(api_client.get_tsa(tsa["id"], PM))
    assert fetched["id"] == tsa["id"]
    assert fetched["divestiture_id"] == divestiture["id"]
