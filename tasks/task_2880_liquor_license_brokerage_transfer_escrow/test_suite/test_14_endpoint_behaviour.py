"""Endpoint mechanics: the clock capability, a computed read, a link create and a round trip.

These four exercises fix what an endpoint is allowed to touch — the clock writes
only what "now" returns, the valuation preview writes nothing at all, a
disclosure create refuses a dangling foreign key before writing, and a license
create is fully recoverable through both the read and the filtered list.
"""

from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    activate_listing,
    assert_instant_equals,
    assert_license,
    create_brokerage,
    create_county,
    create_disclosure_payload,
    create_license,
    create_listing,
    create_seller,
    file_disclosure,
    make_broker_headers,
    make_regulator_analyst_headers,
    make_seller_headers,
    preview_valuation,
    read_county,
    read_listing,
    set_clock,
    setup_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_setting_the_clock_moves_later_writes_and_rewrites_no_stored_row():
    """A county written first keeps created_at 2026-08-01; a seller written after gets 09-15.

    PRD: "Nothing in this system reads wall-clock time. Every deadline, posting
    window, protest deadline, contingency expiry, safekeeping window and nonuse
    computation reads a server-held **logical clock**. At server startup the
    logical clock reads exactly `2026-08-01T00:00:00Z`, and it must not fall back
    to real time under any circumstance. A `PlatformAdmin` moves it by supplying
    a `to_iso8601` instant to the clock-setting capability, which answers with
    the resulting `current_utc`. Setting the clock changes only what subsequent
    reads of "now" return; no already-stored record is recomputed retroactively,
    so a window that was open when it was written stays written as it was."

    PRD: "Every resource the API returns carries a server-minted `id`, formatted
    as a UUID with no type prefix of any kind, and a `created_at` timestamp
    rendered as an ISO 8601 UTC instant with exactly three fractional-second
    digits."

    Design: Corner/endpoints/clock_set_shifts_created_at_of_every_later_write
    """
    county = create_county()
    assert_instant_equals(county["created_at"], "2026-08-01T00:00:00Z",
                          "County.created_at at the default clock")

    moved = set_clock("2026-09-15T00:00:00Z")
    assert_instant_equals(moved["current_utc"], "2026-09-15T00:00:00Z", "current_utc")

    later_seller = create_seller(legal_name="Late Vines LLC",
                                contact_email="late@example.com")
    assert_instant_equals(later_seller["created_at"], "2026-09-15T00:00:00Z",
                          "SellerProfile.created_at after the clock moved")

    reread = read_county(county["id"])
    assert reread["created_at"] == county["created_at"]
    assert reread["updated_at"] == county["updated_at"]
    assert reread["version"] == county["version"]


def test_the_valuation_preview_computes_twice_and_writes_nothing():
    """Two previews agree, the listing stays DRAFT at version 1, activation copies the figure.

    PRD: "Because the two variants can differ dramatically, a read-only preview
    capability lets a `PlatformAdmin`, a `Broker` or a `RegulatorAnalyst` run both
    variants against the current comparable set and the license's current
    receipts without writing anything to the listing."

    PRD: "A draft listing carries `open_offer_count` of 0 and has
    `valuation_basis`, `market_price_cents`, `scarcity_bps_at_activation`,
    `comp_count_at_activation` and `activated_at` all null; no valuation is
    computed while the listing is a draft."

    PRD: "The broker may supply a `valuation_basis` to select the variant; when
    omitted, the county's `default_valuation_basis` is used."

    Design: Corner/endpoints/valuation_preview_is_a_side_effect_free_computed_read
    """
    county = create_county()
    seller = create_seller()
    brokerage = create_brokerage()
    subject = create_license(county["id"], seller["id"],
                             annual_gross_receipts_cents=120000000)
    listing = create_listing(subject["id"], brokerage["id"])
    create_license(county["id"], seller["id"], license_number="SON-COMP-1",
                   annual_gross_receipts_cents=40000000,
                   last_transfer_price_cents=16000000)
    create_license(county["id"], seller["id"], license_number="SON-COMP-2",
                   annual_gross_receipts_cents=40000000,
                   last_transfer_price_cents=21000000)

    as_broker = preview_valuation(listing["id"], make_broker_headers(brokerage["id"]))
    as_analyst = preview_valuation(listing["id"],
                                   make_regulator_analyst_headers("analyst-1"))
    assert as_broker["comparable_sales_price_cents"] == 18500000
    assert as_analyst["comparable_sales_price_cents"] == 18500000
    assert as_analyst["income_multiple_price_cents"] == 21600000
    assert as_broker["default_valuation_basis"] == "COMPARABLE_SALES"

    before = read_listing(listing["id"])
    assert before["version"] == 1
    assert before["status"] == "DRAFT"
    assert before["market_price_cents"] is None
    assert before["valuation_basis"] is None
    assert before["activated_at"] is None

    after = activate_listing(listing["id"], brokerage["id"],
                             valuation_basis="COMPARABLE_SALES")
    assert after["market_price_cents"] == as_broker["comparable_sales_price_cents"]
    assert after["version"] == 2


def test_a_disclosure_refuses_a_dangling_agreement_and_then_links_one_row():
    """The unknown agreement_id is a 404 that writes nothing; the real one appears in both lists.

    PRD: "The resource-specific not-found codes are `ERR_COUNTY_NOT_FOUND`,
    `ERR_SELLER_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_BROKERAGE_NOT_FOUND`,
    `ERR_LICENSE_NOT_FOUND`, `ERR_PREMISES_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_PROTEST_NOT_FOUND` and
    `ERR_FILING_NOT_FOUND`, each carrying HTTP 404."

    PRD: "A `Broker` files a **Dual Agency Disclosure** against an agreement by
    naming the `agreement_id` and asserting two booleans: `represents_seller`,
    true when the listing brokerage represents the seller on this agreement, and
    `represents_buyer`, true when the same brokerage also represents the buyer."

    PRD: "`total_count` reflects the number of records matching the caller's
    filters before the page window is applied, and `has_more` is true whenever
    records matching those filters remain beyond the current window."

    Design: Corner/endpoints/disclosure_create_links_only_an_existing_agreement
    """
    scenario = setup_scenario(stage="agreement_draft")

    dangling = api_client.create_disclosure(
        create_disclosure_payload(NON_EXISTENT_UUID, represents_seller=True,
                                  represents_buyer=False),
        scenario["broker_headers"],
    )
    validate_error(dangling, ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value, 404)

    disclosure = file_disclosure(scenario["agreement_id"], scenario["brokerage_id"])
    assert disclosure["agreement_id"] == scenario["agreement_id"]
    assert disclosure["status"] == "PENDING_ACKS"

    sub_rows, sub_meta = validate_paginated(api_client.list_agreement_disclosures(
        scenario["agreement_id"], scenario["broker_headers"]
    ))
    assert sub_meta["total_count"] == 1
    assert sub_rows[0]["id"] == disclosure["id"]

    all_rows, all_meta = validate_paginated(
        api_client.list_disclosures(scenario["seller_headers"])
    )
    assert all_meta["total_count"] == 1
    assert all_rows[0]["id"] == disclosure["id"]

    filtered_rows, filtered_meta = validate_paginated(api_client.list_disclosures(
        ADMIN, params={"agreement_id": scenario["agreement_id"]}
    ))
    assert filtered_meta["total_count"] == 1
    assert filtered_rows[0]["id"] == disclosure["id"]


def test_a_license_survives_the_read_and_every_declared_list_filter():
    """The stored row comes back unchanged, and county, class and status all narrow the list.

    PRD: "The license inventory can be filtered by `county_id`, by
    `owner_seller_id`, by `transferred_to_buyer_id`, by `status` and by
    `license_class`, alongside the usual `limit` and `offset`."

    PRD: "Unless a specific endpoint states otherwise, list results are ordered
    by `created_at` ascending."

    PRD: "A license enters the inventory with `status` of `ACTIVE`,
    `transferred_to_buyer_id` null, `safekeeping_expires_at` null,
    `safekeeping_extensions_count` of 0 and `safekeeping_filing_pending` false."

    Design: Corner/endpoints/license_read_and_filtered_list_round_trip
    """
    county = create_county()
    seller = create_seller()
    general = create_license(county["id"], seller["id"], license_number="SON-47-1",
                             annual_gross_receipts_cents=120000000,
                             last_transfer_price_cents=17000000)
    set_clock("2026-08-02T00:00:00Z")
    beer_wine = create_license(county["id"], seller["id"], license_number="SON-41-1",
                               license_class="CLASS_41_ONSALE_BEER_WINE",
                               annual_gross_receipts_cents=20000000)

    read_back = validate_success(
        api_client.get_license(general["id"], make_seller_headers(seller["id"]))
    )
    assert_license(read_back)
    assert read_back["license_number"] == "SON-47-1"
    assert read_back["license_class"] == "CLASS_47_ONSALE_GENERAL"
    assert read_back["annual_gross_receipts_cents"] == 120000000
    assert read_back["last_transfer_price_cents"] == 17000000
    assert read_back["status"] == "ACTIVE"
    assert read_back["transferred_to_buyer_id"] is None
    assert read_back == general

    rows, meta = validate_paginated(api_client.list_licenses(ADMIN))
    assert meta["total_count"] == 2
    assert [row["license_number"] for row in rows] == ["SON-47-1", "SON-41-1"]

    by_class, class_meta = validate_paginated(api_client.list_licenses(
        ADMIN, params={"license_class": "CLASS_41_ONSALE_BEER_WINE"}
    ))
    assert class_meta["total_count"] == 1
    assert by_class[0]["id"] == beer_wine["id"]

    _, active_meta = validate_paginated(api_client.list_licenses(
        ADMIN, params={"county_id": county["id"], "status": "ACTIVE"}
    ))
    assert active_meta["total_count"] == 2

    _, safe_meta = validate_paginated(api_client.list_licenses(
        ADMIN, params={"county_id": county["id"], "status": "SAFEKEEPING"}
    ))
    assert safe_meta["total_count"] == 0

    page, page_meta = validate_paginated(api_client.list_licenses(
        ADMIN, params={"limit": 1, "offset": 0}
    ))
    assert len(page) == 1
    assert page[0]["license_number"] == "SON-47-1"
    assert page_meta["limit"] == 1
    assert page_meta["offset"] == 0
    assert page_meta["has_more"] is True
