"""Vendor registration, the fill-rate report, listing pagination and the shop cap."""

from test_helpers import (
    ANY, TEST_USERS, api_client, get_success_data, validate_error,
    validate_paginated, validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]


def test_a_new_vendor_starts_excellent_with_every_derived_field_initialised(
        api, merchandiser_headers):
    """PRD §2.6: "A newly registered vendor starts at `EXCELLENT` with a
    `fill_rate_floor_pct` of 0.9000. The two rolling counters
    `rolling_fill_rate_units_shipped` and `rolling_fill_rate_units_ordered` both start
    at 0, and the vendor's `standing_evaluated_at` is null until the first checkpoint
    recomputes the `standing`."

    PRD §2.6: "The tier is one of `STANDARD`, `PREMIER`, or `STRATEGIC`, and defaults
    to `STANDARD` when the caller omits it."

    Design: Corner/entities/vendor_create_returns_every_declared_field_and_starts_excellent
    """
    response = api.create_vendor({"legal_name": "Northwind Outfitters"},
                                 merchandiser_headers)
    vendor = validate_success(response, 201)
    assert response.json()["response_type"] == "object"

    assert vendor["legal_name"] == "Northwind Outfitters"
    assert vendor["vendor_tier"] == "STANDARD", "the tier defaults to STANDARD"
    assert vendor["standing"] == "EXCELLENT"
    assert vendor["fill_rate_floor_pct"] == 0.9000
    assert vendor["rolling_fill_rate_units_shipped"] == 0
    assert vendor["rolling_fill_rate_units_ordered"] == 0
    assert vendor["standing_evaluated_at"] is None, (
        "no checkpoint has run, so the evaluation instant is null")

    body = response.json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)


def test_the_fill_rate_report_carries_both_bases_and_the_derived_standing(
        api, merchandiser_headers):
    """PRD §4: "Fill-rate report returning both fill-rate bases and the derived
    `standing`".

    PRD §3.9: "The ratio is the summed `quantity_shipped` over the scope divided by
    the summed `quantity_ordered` over the scope, rounded half up to four decimal
    places, and it is null when the ordered denominator is zero."

    Design: Corner/endpoints/vendors_list_and_get_carry_the_derived_standing_fields
    """
    vendor = get_success_data(api_client.create_vendor(
        {"legal_name": "Northwind Outfitters", "vendor_tier": "PREMIER"},
        merchandiser_headers))

    payload = validate_success(
        api.get_fill_rate_report(vendor["id"], ANY, {"basis": "UNIT_WEIGHTED",
                                                     "window_days": 90}), 200)
    assert isinstance(payload, dict), "the report is a single object, not a list"
    assert payload["standing"] == "EXCELLENT"
    assert payload["fill_rate_floor_pct"] == 0.9000

    # With no closed buys in the window both bases have a zero denominator, so both
    # are null rather than 0. The report exposes them side by side.
    undefined = [k for k, v in payload.items() if v is None]
    assert len(undefined) >= 2, (
        "both fill-rate bases are reported and both are null on a zero "
        f"denominator, got nulls for {undefined}")

    # The derived standing agrees with the vendor read.
    vendor_now = validate_success(api.get_vendor(vendor["id"], ANY), 200)
    assert payload["standing"] == vendor_now["standing"]
    assert payload["fill_rate_floor_pct"] == vendor_now["fill_rate_floor_pct"]


def test_listings_paginate_with_a_total_count_over_the_whole_filtered_set(
        api, merchandiser_headers):
    """PRD §2.3: "List endpoints accept a `limit` parameter giving the maximum number
    of items to return; when omitted it defaults to 10, and it may be set no lower
    than 1 and no higher than 100."

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/entities/listings_list_paginates_and_reports_total_count_and_has_more
    """
    vendor = get_success_data(api_client.create_vendor(
        {"legal_name": "Northwind Outfitters", "vendor_tier": "STANDARD"},
        merchandiser_headers))
    shop = get_success_data(api_client.create_shop(
        {"vendor_id": vendor["id"], "shop_name": "Northwind Brand Shop"},
        merchandiser_headers))
    event = get_success_data(api_client.create_event({
        "shop_id": shop["id"], "event_title": "Fall Outerwear Daily",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-02T00:00:00Z",
        "ship_time_quote_days": 14}, merchandiser_headers))
    for i in range(3):
        get_success_data(api_client.create_listing({
            "event_id": event["id"], "vendor_sku": f"NW-PG-{i}",
            "unit_price_cents": 100 * (i + 1), "vendor_unit_cost_cents": 60 * (i + 1),
            "allocation_units": 4, "reveal_at": "2026-09-01T00:00:00Z"},
            merchandiser_headers))

    page, meta = validate_paginated(
        api.list_listings(ANY, {"event_id": event["id"], "limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3, "total_count counts the whole filtered set"
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    rest, meta2 = validate_paginated(
        api.list_listings(ANY, {"event_id": event["id"], "limit": 2, "offset": 2}))
    assert len(rest) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_the_shop_assortment_ceiling_is_evaluated_across_its_committed_events(
        api, merchandiser_headers):
    """PRD §3.2: "Neither adding a fresh listing nor reviving a sold-out one may push
    the shop's `curated_sku_count` above 40 active listings across its `SCHEDULED` and
    `LIVE` events; doing so is refused with `ERR_SHOP_SKU_LIMIT_EXCEEDED`."

    PRD §3.2: "`curated_sku_count` is recomputed as the number of `ACTIVE` listings
    across the shop's `SCHEDULED` and `LIVE` events — listings belonging to `DRAFT`
    events do not count toward it."

    Design: Corner/endpoints/shop_sku_limit_refuses_the_forty_first_active_listing
    """
    vendor = get_success_data(api_client.create_vendor(
        {"legal_name": "Northwind Outfitters", "vendor_tier": "STANDARD"},
        merchandiser_headers))
    shop = get_success_data(api_client.create_shop(
        {"vendor_id": vendor["id"], "shop_name": "Northwind Brand Shop"},
        merchandiser_headers))
    event = get_success_data(api_client.create_event({
        "shop_id": shop["id"], "event_title": "Primary Event",
        "starts_at": "2026-09-01T00:00:00Z", "ends_at": "2026-09-03T00:00:00Z",
        "ship_time_quote_days": 14}, merchandiser_headers))

    for i in range(40):
        get_success_data(api_client.create_listing({
            "event_id": event["id"], "vendor_sku": f"NW-CAP-{i:02d}",
            "unit_price_cents": 100, "vendor_unit_cost_cents": 60,
            "allocation_units": 4, "reveal_at": "2026-09-01T00:00:00Z"},
            merchandiser_headers))

    shop_before = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert shop_before["curated_sku_count"] == 0, (
        "a DRAFT event's listings do not count toward the shop's assortment")

    validate_success(api.schedule_event(event["id"], merchandiser_headers), 200)

    shop_after = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert shop_after["curated_sku_count"] == 40

    res = api.create_listing({
        "event_id": event["id"], "vendor_sku": "NW-CAP-41",
        "unit_price_cents": 100, "vendor_unit_cost_cents": 60,
        "allocation_units": 4, "reveal_at": "2026-09-01T00:00:00Z"},
        merchandiser_headers)
    validate_error(res, "ERR_SHOP_SKU_LIMIT_EXCEEDED", expected_status=409)

    shop_final = validate_success(api.get_shop(shop["id"], ANY), 200)
    assert shop_final["curated_sku_count"] == 40, (
        "the refused listing was not persisted")