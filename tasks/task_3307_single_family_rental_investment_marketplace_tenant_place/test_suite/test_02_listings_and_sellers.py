"""Listing lifecycle, seller tiers, and entity-shape corner tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN_HEADERS,
    REVIEWER_HEADERS,
    attach_verified_inspection,
    create_listing_payload,
    get_success_data,
    make_seller_headers,
    setup_certified_listing,
    setup_draft_listing,
    setup_seller,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestListingShape:
    def test_portfolio_listing_without_bulk_price_rejected(self, api):
        """PRD §3.1: "When `listing_kind` is `PORTFOLIO`, an aggregate
        `bulk_price_cents` is required and must be present and positive before
        the listing can be submitted; omitting it on a portfolio draft is a
        shape violation rejected with `ERR_VALIDATION`."

        Design: Corner/entities/create_listing_portfolio_requires_bulk_price
        """
        seller = setup_seller()
        payload = create_listing_payload(
            seller["id"],
            address_line="1 Bulk Way",
            asking_price_cents=50_000_000,
            listing_kind="PORTFOLIO",
        )
        payload.pop("bulk_price_cents", None)
        resp = api.create_listing(payload, make_seller_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_confidential_flag_defaults_to_false(self, api):
        """PRD §3.1: "The draft may optionally name a `certification_program_id`
        — optional at draft time but mandatory before certification — and may set
        the `seller_asks_confidential` feature flag, which defaults to false; when
        true, tenant payment history is redacted in underwriting outputs and the
        REDACTED underwriting variant applies (§3.5)."

        Design: Corner/entities/create_listing_applies_confidential_default
        """
        seller = setup_seller()
        payload = create_listing_payload(seller["id"], address_line="2 Default Dr")
        payload.pop("seller_asks_confidential", None)
        resp = api.create_listing(payload, make_seller_headers(seller["id"]))
        listing = validate_success(resp, expected_status=201)
        assert listing["seller_asks_confidential"] is False
        assert listing["status"] == "DRAFT"

    def test_get_listing_unknown_id_is_not_found(self, api):
        """PRD §2.9: "Nested URL paths are validated left-to-right: each path
        identifier must resolve to an existing resource before the next
        identifier is examined, and the first missing identifier yields
        `ERR_NOT_FOUND`."

        Design: Corner/entities/get_listing_not_found_returns_404
        """
        resp = api.get_listing(NON_EXISTENT_UUID, PLATFORM_ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestListingInvalidTransitions:
    def test_certified_listing_cannot_be_resubmitted(self, api):
        """PRD §2.8: "A request whose `action` is not defined from the entity's
        current state fails the state check with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/listing_certified_cannot_resubmit
        """
        ctx = setup_certified_listing()
        seller_h = make_seller_headers(ctx["seller"]["id"])
        resp = api.transition_listing(ctx["listing"]["id"], {"action": "SUBMIT"}, seller_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        listing = get_success_data(api.get_listing(ctx["listing"]["id"], seller_h))
        assert listing["status"] == "CERTIFIED"


class TestListingsPagination:
    def test_default_page_is_ten_with_total_count(self, api):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum
        of 100. `offset` defaults to 0. All list responses are sorted by
        `created_at` ascending. The `meta` object of a list response includes
        the pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_listings_pagination_defaults
        """
        seller = setup_seller()
        seller_h = make_seller_headers(seller["id"])
        for i in range(12):
            api.create_listing(
                create_listing_payload(seller["id"], address_line=f"P{i + 1}"), seller_h
            )
        resp = api.list_listings(PLATFORM_ADMIN_HEADERS)
        data, meta = validate_paginated(resp)
        assert len(data) == 10
        assert meta["total_count"] == 12
        assert meta["has_more"] is True


class TestBulkDiscountTierBoundary:
    def test_four_listings_earn_100_bps(self, api):
        """PRD §3.1: "The seller's `bulk_discount_bps` derives from `listed_count`
        as a tiered discount in basis points: at least 10 listed properties yields
        500 basis points, at least 5 yields 300, at least 2 yields 100, and fewer
        than 2 yields 0."

        Design: Difficulty/boundary_precision_check/bulk_discount_tier_boundary
        """
        seller = setup_seller()
        seller_h = make_seller_headers(seller["id"])
        for i in range(4):
            listing = setup_draft_listing(seller, address_line=f"{i + 1} Tier St")
            api.transition_listing(listing["id"], {"action": "SUBMIT"}, seller_h)
        data = get_success_data(api.get_seller(seller["id"], PLATFORM_ADMIN_HEADERS))
        assert data["listed_count"] == 4
        assert data["bulk_discount_bps"] == 100

    def test_five_listings_earn_300_bps_inclusive(self, api):
        """PRD §3.1: "Thresholds are inclusive — a seller with exactly 5 listed
        properties earns 300 basis points, and exactly 2 earns 100."

        Design: Difficulty/boundary_precision_check/bulk_discount_tier_boundary
        """
        seller = setup_seller()
        seller_h = make_seller_headers(seller["id"])
        for i in range(5):
            listing = setup_draft_listing(seller, address_line=f"{i + 1} Tier St")
            api.transition_listing(listing["id"], {"action": "SUBMIT"}, seller_h)
        data = get_success_data(api.get_seller(seller["id"], PLATFORM_ADMIN_HEADERS))
        assert data["listed_count"] == 5
        assert data["bulk_discount_bps"] == 300


class TestListedCountConservation:
    def test_submit_then_withdraw_restores_count(self, api):
        """PRD §3.1: "A seller's `listed_count` is the count of that seller's
        listings whose status is anything other than `SOLD` or `WITHDRAWN`, and
        it is recomputed whenever a listing is submitted, withdrawn, or sold."

        Design: Difficulty/compensating_invariant/listed_count_conservation_across_submit_and_withdraw
        """
        seller = setup_seller()
        seller_h = make_seller_headers(seller["id"])
        listing_a = setup_draft_listing(seller, address_line="91 C St")
        listing_b = setup_draft_listing(seller, address_line="92 C St")
        api.transition_listing(listing_a["id"], {"action": "SUBMIT"}, seller_h)
        api.transition_listing(listing_b["id"], {"action": "SUBMIT"}, seller_h)
        pre = get_success_data(api.get_seller(seller["id"], PLATFORM_ADMIN_HEADERS))
        assert pre["listed_count"] == 2 and pre["bulk_discount_bps"] == 100
        # listed_count covers every listing not SOLD/WITHDRAWN (PRD §3.1), so
        # listing C is drafted only after the pre-reading to keep pre at 2.
        listing_c = setup_draft_listing(seller, address_line="93 C St")
        api.transition_listing(listing_c["id"], {"action": "SUBMIT"}, seller_h)
        mid = get_success_data(api.get_seller(seller["id"], PLATFORM_ADMIN_HEADERS))
        assert mid["listed_count"] == 3
        assert mid["bulk_discount_bps"] == 100
        # Withdrawal is defined from IN_REVIEW (PRD §3.2): move C through review first.
        attach_verified_inspection(seller, listing_c)
        api.transition_listing(listing_c["id"], {"action": "BEGIN_REVIEW"}, REVIEWER_HEADERS)
        api.transition_listing(listing_c["id"], {"action": "WITHDRAW"}, seller_h)
        post = get_success_data(api.get_seller(seller["id"], PLATFORM_ADMIN_HEADERS))
        assert post["listed_count"] == pre["listed_count"]
        assert post["bulk_discount_bps"] == pre["bulk_discount_bps"]

    def test_withdraw_from_in_review_recomputes_discount(self, api):
        """PRD §3.2: "At any point from `IN_REVIEW`, the seller may withdraw the
        listing to `WITHDRAWN`, which recomputes `listed_count` and
        `bulk_discount_bps`."

        Design: Difficulty/compensating_invariant/listed_count_conservation_across_submit_and_withdraw
        """
        from test_helpers import REVIEWER_HEADERS

        seller = setup_seller()
        seller_h = make_seller_headers(seller["id"])
        listing_a = setup_draft_listing(seller, address_line="96 C St")
        listing_b = setup_draft_listing(seller, address_line="97 C St")
        listing_c = setup_draft_listing(seller, address_line="98 C St")
        for listing in (listing_a, listing_b):
            api.transition_listing(listing["id"], {"action": "SUBMIT"}, seller_h)
        api.transition_listing(listing_c["id"], {"action": "SUBMIT"}, seller_h)
        # BEGIN_REVIEW requires a VERIFIED inspection report (PRD §3.2).
        attach_verified_inspection(seller, listing_c)
        api.transition_listing(listing_c["id"], {"action": "BEGIN_REVIEW"}, REVIEWER_HEADERS)
        during = get_success_data(api.get_seller(seller["id"], PLATFORM_ADMIN_HEADERS))
        assert during["listed_count"] == 3
        api.transition_listing(listing_c["id"], {"action": "WITHDRAW"}, seller_h)
        after = get_success_data(api.get_seller(seller["id"], PLATFORM_ADMIN_HEADERS))
        assert after["listed_count"] == 2
        assert after["bulk_discount_bps"] == 100
        listing = get_success_data(api.get_listing(listing_c["id"], seller_h))
        assert listing["status"] == "WITHDRAWN"
