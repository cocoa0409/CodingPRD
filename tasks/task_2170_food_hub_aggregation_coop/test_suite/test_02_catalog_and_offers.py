"""The catalog: creating items, publishing offer windows, availability
arithmetic and the concurrency guard on the contended supply pool."""

from test_helpers import (
    CLOCK_BASE,
    HUB,
    ApiErrorId,
    add_order_line,
    assert_product,
    assert_product_availability,
    create_buyer,
    create_draft_order,
    create_listed_product,
    create_product_payload,
    make_producer_headers,
    onboard_active_producer,
    publish_offer_payload,
    read_product,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCatalogCreation:
    def test_creating_an_item_without_units_per_pallet_is_a_malformed_request(
        self, api
    ):
        """PRD 3.3: "Creating it requires the owning `producer_id`, a
        `commodity_code` of 1 to 40 characters drawn only from uppercase letters
        and underscores (this is the hub-wide identifier buyers order against,
        such as `CARROT_LOOSE`), a `unit_of_measure` of `CASE`, `LB` or `EACH`,
        a `storage_class` of `AMBIENT`, `CHILL` or `FROZEN`, a `pack_weight_lb`
        greater than zero giving the net weight of one sales unit, a
        `units_per_pallet` of at least 1, and a `producer_unit_price_cents` of
        at least 1 cent — the amount the producer is paid per sales unit before
        any hub margin."
        PRD 2.8: "Request shape — required body fields present, enum values
        legal, numbers inside their declared ranges, datetimes parseable as ISO
        8601 UTC, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_product_missing_required_field_returns_invalid_request
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        payload = create_product_payload(pid)
        payload.pop("units_per_pallet")

        resp = api.create_product(payload, make_producer_headers(pid))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(api.list_products(HUB, params={"producer_id": pid}))
        assert meta["total_count"] == 0

    def test_a_newly_created_item_is_draft_with_no_availability(self, api):
        """PRD 3.3: "A newly created item is `DRAFT`: it has `quantity_offered`
        at 0, `quantity_committed` at 0, `quantity_available` at 0, and both
        `offer_window_start` and `offer_window_end` unset."

        Design: Corner/entities/product_system_defaults_applied_when_offer_not_yet_published
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]

        data = validate_success(
            api.create_product(create_product_payload(pid), make_producer_headers(pid)),
            201,
        )
        assert_product(data)
        assert data["status"] == "DRAFT"
        assert data["quantity_offered"] == 0
        assert data["quantity_committed"] == 0
        assert data["quantity_available"] == 0
        assert data["offer_window_start"] is None
        assert data["offer_window_end"] is None

    def test_the_catalog_list_pages_with_limit_offset_and_total_count(self, api):
        """PRD 2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count` and `has_more`: `total_count` is the number of
        records matching the filters before pagination is applied, and
        `has_more` is true when the offset plus the number of returned records
        is less than `total_count`."
        PRD 2.3: "List results are ordered by `created_at` ascending unless a
        specific narrative below says otherwise, so paging through a collection
        yields a stable oldest-first walk."

        Design: Corner/entities/list_products_paginates_with_limit_offset_and_total_count
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        first = create_listed_product(pid)
        create_listed_product(pid)
        create_listed_product(pid)

        page_one, meta_one = validate_paginated(
            api.list_products(HUB, params={"producer_id": pid, "limit": 2, "offset": 0})
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert page_one[0]["id"] == first["id"]

        page_two, meta_two = validate_paginated(
            api.list_products(HUB, params={"producer_id": pid, "limit": 2, "offset": 2})
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False


class TestAvailabilityArithmetic:
    def test_committing_an_allocation_shrinks_the_available_pool(self, api):
        """PRD 3.3: "`quantity_offered` is what the producer published.
        `quantity_committed` is what allocations currently hold — specifically,
        the summed quantity of every allocation of this item in `RESERVED`,
        `STAGED` or `DELIVERED`. `quantity_available` is the offered quantity
        minus the committed quantity, floored at zero, and it is the pool the
        allocation waterfall draws from."

        Design: Corner/entities/product_quantity_available_is_computed_from_offer_minus_commitment
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        product = create_listed_product(pid, quantity_offered=100)
        buyer = create_buyer()
        order = create_draft_order(buyer["id"])
        add_order_line(order["id"], buyer["id"], quantity_requested=60)

        validate_success(api.aggregate_order(order["id"], HUB))

        refreshed = read_product(product["id"])
        assert refreshed["quantity_offered"] == 100
        assert refreshed["quantity_committed"] == 60
        assert refreshed["quantity_available"] == 40
        assert_product_availability(refreshed)


class TestOfferPublication:
    def test_a_delisted_item_can_be_re_offered_after_reinstatement(self, api):
        """PRD 3.2: "What reinstatement does **not** do is un-delist anything.
        Catalog items delisted by the suspension stay `DELISTED` with zero
        offered quantity until the producer publishes a fresh offer against each
        of them, and the reversed allocations are gone for good; the buyer's
        order must be aggregated again to get supply back."
        PRD 3.3: "And an item that was delisted by a suspension may be
        re-offered once its producer is reinstated, closing the `LISTED →
        DELISTED → LISTED` cycle; that publication carries the same
        expected-version requirement as any other."

        Design: Corner/state_machines/delisted_product_can_be_relisted_after_reinstatement
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        product = create_listed_product(pid, quantity_offered=100)

        validate_success(
            api.review_producer(
                pid, {"decision": "SUSPEND", "note": "paperwork lapse"}, HUB
            )
        )
        validate_success(api.review_producer(pid, {"decision": "REINSTATE"}, HUB))

        mid = read_product(product["id"])
        assert mid["status"] == "DELISTED"

        relisted = validate_success(
            api.publish_offer(
                product["id"],
                publish_offer_payload(mid["version"], quantity_offered=80),
                make_producer_headers(pid),
            )
        )
        assert relisted["status"] == "LISTED"
        assert relisted["quantity_offered"] == 80
        assert relisted["quantity_available"] == 80

        producer = validate_success(api.get_producer(pid, HUB))
        assert producer["onboarding_status"] == "ACTIVE"
        assert producer["suspension_count"] == 1

    def test_publishing_an_offer_against_a_stale_product_version_is_rejected(
        self, api
    ):
        """PRD 2.7: "Publishing an offer — the write at `POST
        /products/{id}/offers` — requires `expected_product_version` in the
        request body, carrying the `version` of the product as the client last
        observed it. If that value does not equal the product's current
        `version`, the request is rejected with `ERR_STALE_PRODUCT_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_product_version_on_a_second_offer_is_rejected
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        headers = make_producer_headers(pid)
        created = validate_success(
            api.create_product(create_product_payload(pid), headers), 201
        )
        stale_version = created["version"]
        validate_success(
            api.publish_offer(
                created["id"], publish_offer_payload(stale_version), headers
            )
        )

        resp = api.publish_offer(
            created["id"],
            publish_offer_payload(stale_version, quantity_offered=7),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PRODUCT_VERSION.value, 412)

        unchanged = read_product(created["id"])
        assert unchanged["quantity_offered"] == 100
        assert unchanged["quantity_available"] == 100
        assert unchanged["status"] == "LISTED"
