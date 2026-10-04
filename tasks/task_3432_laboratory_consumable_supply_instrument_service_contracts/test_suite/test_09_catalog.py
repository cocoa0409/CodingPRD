"""Catalog: sku uniqueness and the list pagination envelope."""

from test_helpers import (
    SUPPLY_OPS,
    ApiErrorId,
    api_client,
    catalog_item_payload,
    create_catalog_item,
    validate_error,
    validate_paginated,
)


def test_duplicate_sku_rejected(api):
    """PRD section 3.6: "a `sku` that must be unique across the catalog —
    re-creating an existing `sku` fails with `ERR_DUPLICATE_SKU`".

    Design: Corner/entities/duplicate_sku_rejected
    """
    create_catalog_item(sku="DUP-1", base_price_cents=100, stock_on_hand=5)
    response = api_client.create_catalog_item(
        catalog_item_payload(
            sku="DUP-1", item_class="COLD_CHAIN", allocation_group="GROUP_A",
            base_price_cents=200, stock_on_hand=5,
        ),
        headers=SUPPLY_OPS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_SKU)


def test_list_pagination_envelope_fields(api):
    """PRD section 2.3: "The `limit` parameter sets the maximum number of
    items returned; when omitted it defaults to 10, and it accepts a minimum
    of 1 and a maximum of 100. The `offset` parameter sets the number of items
    skipped and defaults to 0." and "The `meta` object of a list response
    carries the pagination fields `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_pagination_envelope_fields
    """
    for sku in ("PG-1", "PG-2", "PG-3"):
        create_catalog_item(sku=sku, base_price_cents=100, stock_on_hand=5)

    first = api_client.list_catalog_items(headers=SUPPLY_OPS, params={"limit": 2})
    page1, meta1 = validate_paginated(first)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0
    body = first.json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)

    second = api_client.list_catalog_items(
        headers=SUPPLY_OPS, params={"limit": 2, "offset": 2}
    )
    page2, meta2 = validate_paginated(second)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert meta2["offset"] == 2

