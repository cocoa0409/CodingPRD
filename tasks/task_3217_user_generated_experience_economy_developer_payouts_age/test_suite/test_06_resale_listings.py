"""Resale listings: the price floor boundary and optimistic concurrency on the
underlying item version (PRD §2.6, §3.6)."""
from test_helpers import (
    ApiErrorId,
    create_on_sale_limited_item,
    create_resale_listing_payload,
    create_user,
    list_for_resale,
    make_creator_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _fresh_item(api, item_id, platform_admin_headers):
    return validate_success(api.get_marketplace_item(item_id, platform_admin_headers), 200)


class TestResalePriceFloor:
    def test_resale_floor_exactly_at_floor_accepted(self, api, platform_admin_headers):
        """PRD §3.6: "The ask must be at least one half of the item's current
        `price_robux`, rounded down to a whole Robux, and the boundary is inclusive: an
        ask equal to that floor is accepted, one Robux below it is rejected with
        `ERR_RESALE_FLOOR_VIOLATION`. (Concretely, an item priced at 101 Robux has a
        floor of 50: ask 50 passes, ask 49 fails.)"

        Design: Difficulty/boundary_precision_check/resale_floor_exactly_at_floor_accepted
        """
        # Create the seller early so the account is comfortably older than the
        # seven-day resale gate regardless of where it is enforced.
        set_clock("2026-08-20T00:00:00Z")
        seller = create_user(username="cr_h", email="cr_h@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_limited_item(
            seller["id"], title="Rare Cap", price_robux=101, total_supply=5, royalty_pct=10
        )
        set_clock("2026-09-01T00:00:00Z")

        seller_headers = make_creator_headers(seller["id"])
        # floor(101 * 0.5) = floor(50.5) = 50: ask 50 is accepted.
        item_now = _fresh_item(api, item["id"], platform_admin_headers)
        ok = validate_success(
            api.create_resale_listing(
                create_resale_listing_payload(item["id"], 50, item_now["version"]),
                seller_headers,
            ),
            201,
        )
        assert ok["status"] == "ACTIVE"

        # Ask 49 is one Robux below the floor: rejected.
        item_now = _fresh_item(api, item["id"], platform_admin_headers)
        resp = api.create_resale_listing(
            create_resale_listing_payload(item["id"], 49, item_now["version"]),
            seller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESALE_FLOOR_VIOLATION)
        assert resp.status_code == 422

    def test_resale_floor_even_price_boundary(self, api, platform_admin_headers):
        """PRD §3.6: "The ask must be at least one half of the item's current
        `price_robux`, rounded down to a whole Robux, and the boundary is inclusive: an
        ask equal to that floor is accepted, one Robux below it is rejected with
        `ERR_RESALE_FLOOR_VIOLATION`."

        Design: Difficulty/boundary_precision_check/resale_floor_exactly_at_floor_accepted
        """
        set_clock("2026-08-20T00:00:00Z")
        seller = create_user(username="cr_h2", email="cr_h2@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_limited_item(
            seller["id"], title="Even Cap", price_robux=100, total_supply=5, royalty_pct=10
        )
        set_clock("2026-09-01T00:00:00Z")

        seller_headers = make_creator_headers(seller["id"])
        # floor(100 * 0.5) = 50: ask 50 accepted, ask 49 rejected.
        item_now = _fresh_item(api, item["id"], platform_admin_headers)
        ok = validate_success(
            api.create_resale_listing(
                create_resale_listing_payload(item["id"], 50, item_now["version"]),
                seller_headers,
            ),
            201,
        )
        assert ok["status"] == "ACTIVE"

        item_now = _fresh_item(api, item["id"], platform_admin_headers)
        resp = api.create_resale_listing(
            create_resale_listing_payload(item["id"], 49, item_now["version"]),
            seller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESALE_FLOOR_VIOLATION)


class TestResaleOptimisticConcurrency:
    def test_resale_listing_stale_item_version_returns_412(self, api, platform_admin_headers):
        """PRD §2.6: "creating a `ResaleListing` requires `expected_item_version`, the
        `version` of the underlying `MarketplaceItem` last observed by the seller. A
        price edit, a take-off-sale and put-on-sale cycle, or a moderation-driven state
        change each advance the item's `version`, and the listing's ask-price floor is
        computed from that observed price — a mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/resale_listing_stale_item_version_returns_412
        """
        set_clock("2026-08-20T00:00:00Z")
        seller = create_user(username="s_occ", email="s_occ@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_limited_item(
            seller["id"], title="Ltd", price_robux=500, total_supply=5, royalty_pct=10
        )
        set_clock("2026-09-01T00:00:00Z")

        seller_headers = make_creator_headers(seller["id"])
        stale_version = _fresh_item(api, item["id"], platform_admin_headers)["version"]

        # Each sale-state transition advances the item version, making the captured
        # version stale.
        validate_success(api.take_item_off_sale(item["id"], seller_headers), 200)
        validate_success(api.put_item_on_sale(item["id"], seller_headers), 200)

        resp = api.create_resale_listing(
            create_resale_listing_payload(item["id"], 300, stale_version),
            seller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

        # Control: the current version still lists successfully.
        fresh_version = _fresh_item(api, item["id"], platform_admin_headers)["version"]
        assert fresh_version != stale_version, "off-sale/on-sale cycle must advance the version"
        ok = validate_success(
            api.create_resale_listing(
                create_resale_listing_payload(item["id"], 300, fresh_version),
                seller_headers,
            ),
            201,
        )
        assert ok["status"] == "ACTIVE"
