"""Clubs, members, catalog items, and instant-savings offers."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    MANAGER,
    UNKNOWN_ID,
    create_club,
    create_club_payload,
    create_item,
    create_member,
    create_offer,
    get_member,
    validate_error,
    validate_success,
)


class TestClubDefaults:
    def test_club_creation_applies_documented_defaults_on_create(self, api):
        """PRD §2.9: "Separately, the `scan_go_enabled` flag on a club — defaulting to
        enabled — is a static kill switch"; PRD §2.10: "`lp_unscanned_threshold`
        (default 2) is the minimum count of apparently-unscanned physical items
        that flips a computer-vision exit check to a mismatch and opens a case,
        and `lp_suspend_strikes` (default 3) is the number of accumulated strikes
        at which a member is automatically suspended. Two TTL values, also
        club-tunable, govern expiry: `receipt_code_ttl_minutes` (default 30) bounds
        how long a receipt code remains valid after payment, and
        `intercept_ttl_minutes` (default 10) bounds how long a pending
        restricted-item intercept may await an associate before it expires at
        closeout. A final club setting, `staging_slot_capacity` (default 2),
        bounds how many curbside orders may concurrently occupy one staging slot
        label across overlapping windows."

        Design: Corner/entities/club_creation_applies_documented_defaults
        """
        resp = api.create_club(
            create_club_payload(name="Club Defaults"), ADMIN,
        )
        club = validate_success(resp, expected_status=201)
        assert club["scan_go_enabled"] is True
        assert club["allow_offline_payment"] is False
        assert club["connectivity_posture"] == "ONLINE"
        assert club["lp_unscanned_threshold"] == 2
        assert club["lp_suspend_strikes"] == 3
        assert club["staging_slot_capacity"] == 2
        assert club["receipt_code_ttl_minutes"] == 30
        assert club["intercept_ttl_minutes"] == 10

    def test_club_defaults_persist_on_readback(self, api):
        """PRD §2.10: "Two club-tunable thresholds drive loss prevention:
        `lp_unscanned_threshold` (default 2) is the minimum count of
        apparently-unscanned physical items that flips a computer-vision exit
        check to a mismatch and opens a case, and `lp_suspend_strikes`
        (default 3) is the number of accumulated strikes at which a member is
        automatically suspended."

        Design: Corner/entities/club_creation_applies_documented_defaults
        """
        club = create_club(name="Club Defaults Readback")
        resp = api.get_club(club["id"], ADMIN)
        reread = validate_success(resp)
        assert reread["lp_unscanned_threshold"] == 2
        assert reread["lp_suspend_strikes"] == 3
        assert reread["receipt_code_ttl_minutes"] == 30
        assert reread["intercept_ttl_minutes"] == 10


class TestMemberDefaults:
    def test_member_creation_defaults_active_with_zero_balances(self, api):
        """PRD §3.1: "A new member is `ACTIVE` with zeroed reward balances, zero
        lifetime charges, and zero strikes."

        Design: Corner/entities/member_creation_defaults_active_with_zero_balances
        """
        club = create_club(name="Club MD")
        resp = api.create_member(
            {"tier": "CLUB", "birth_year": 1990, "home_club_id": club["id"]}, ADMIN,
        )
        member = validate_success(resp, expected_status=201)
        assert member["status"] == "ACTIVE"
        assert member["cash_rewards_pending_cents"] == 0
        assert member["cash_rewards_posted_cents"] == 0
        assert member["lifetime_charged_cents"] == 0
        assert member["unscanned_strikes"] == 0

    def test_member_tender_status_defaults_to_ok(self, api):
        """PRD §3.1: "registration records the member's `tier` (`CLUB` or
        `PLUS`), their four-digit `birth_year` used later for age verification,
        the `home_club_id` of their home club, and an optional `tender_status`
        that defaults to `OK`."

        Design: Corner/entities/member_creation_defaults_active_with_zero_balances
        """
        club = create_club(name="Club MD2")
        member = create_member(club["id"], tier="CLUB", birth_year=1988)
        assert member["tender_status"] == "OK"
        reread = get_member(member["id"])
        assert reread["tender_status"] == "OK"


class TestCatalogItemRules:
    def test_weighted_item_missing_price_rejected(self, api):
        """PRD §3.1: "a `WEIGHTED` item must be priced through
        `price_per_pound_cents`, the price per pound — each field is required
        exactly when the item has the matching pricing mode, and a payload
        inconsistent with the item's pricing mode is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/catalog_item_weighted_missing_price_rejected
        """
        club = create_club(name="Club RF")
        resp = api.create_catalog_item(
            club["id"],
            {"sku": "APL", "item_name": "Apples", "pricing_mode": "WEIGHTED"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_unit_item_missing_price_rejected(self, api):
        """PRD §3.1: "A `UNIT` item must be priced through `unit_price_cents`,
        the price per piece; a `WEIGHTED` item must be priced through
        `price_per_pound_cents`, the price per pound — each field is required
        exactly when the item has the matching pricing mode, and a payload
        inconsistent with the item's pricing mode is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/catalog_item_weighted_missing_price_rejected
        """
        club = create_club(name="Club RF2")
        resp = api.create_catalog_item(
            club["id"],
            {"sku": "MLK", "item_name": "Milk", "pricing_mode": "UNIT"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_catalog_list_pagination_limit_offset_has_more(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to
        10, with a minimum of 1 and a maximum of 100. `offset` skips that many
        items from the front of the result set and defaults to 0."

        Design: Corner/endpoints/catalog_list_pagination_limit_offset_has_more
        """
        club = create_club(name="Club PG")
        create_item(club["id"], sku="A-1", unit_price_cents=100)
        create_item(club["id"], sku="B-2", unit_price_cents=200)

        page1, meta1 = _paged(
            api.list_club_catalog_items(
                club["id"], ADMIN, params={"limit": 1, "offset": 0},
            )
        )
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = _paged(
            api.list_club_catalog_items(
                club["id"], ADMIN, params={"limit": 1, "offset": 1},
            )
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"]


def _paged(resp):
    from test_helpers import validate_paginated

    return validate_paginated(resp)


class TestOfferWindowRules:
    def test_offer_window_inverted_rejected(self, api):
        """PRD §3.1: "The window must be internally sane: a `valid_to_iso`
        earlier than `valid_from_iso` is rejected with
        `ERR_OFFER_WINDOW_INVALID`."

        Design: Corner/validations/offer_window_inverted_rejected
        """
        club = create_club(name="Club OI")
        item = create_item(club["id"])
        resp = api.create_instant_savings_offer(
            club["id"],
            {
                "catalog_item_id": item["id"],
                "discount_cents": 100,
                "valid_from_iso": "2026-09-10T00:00:00Z",
                "valid_to_iso": "2026-09-01T00:00:00Z",
                "per_member_limit": 5,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_WINDOW_INVALID)

    def test_touching_window_endpoints_conflict(self, api):
        """PRD §3.1: "Windows for the same club and item may never overlap, and
        because they are closed intervals, touching endpoints count as overlap:
        an existing window ending at a given instant blocks a new window
        beginning at that same instant, and any such conflict is rejected with
        `ERR_OFFER_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/offer_window_closed_interval_touching_endpoints_conflict
        """
        club = create_club(name="Club TO1")
        item = create_item(club["id"], sku="COFFEE", unit_price_cents=800)
        create_offer(
            club["id"], item["id"],
            discount_cents=100,
            valid_from_iso="2026-09-01T00:00:00Z",
            valid_to_iso="2026-09-10T00:00:00Z",
        )
        resp = api.create_instant_savings_offer(
            club["id"],
            {
                "catalog_item_id": item["id"],
                "discount_cents": 120,
                "valid_from_iso": "2026-09-10T00:00:00Z",
                "valid_to_iso": "2026-09-20T00:00:00Z",
                "per_member_limit": 5,
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_WINDOW_CONFLICT)

    def test_window_starting_one_instant_after_end_is_accepted(self, api):
        """PRD §3.1: "a validity window from `valid_from_iso` to `valid_to_iso`
        that is closed at both ends — the offer applies at exactly its start
        instant and at exactly its end instant"; PRD §3.1: "an existing window
        ending at a given instant blocks a new window beginning at that same
        instant, and any such conflict is rejected with
        `ERR_OFFER_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/offer_window_closed_interval_touching_endpoints_conflict
        """
        club = create_club(name="Club TO1b")
        item = create_item(club["id"], sku="COFFEE", unit_price_cents=800)
        create_offer(
            club["id"], item["id"],
            discount_cents=100,
            valid_from_iso="2026-09-01T00:00:00Z",
            valid_to_iso="2026-09-10T00:00:00Z",
        )
        resp = api.create_instant_savings_offer(
            club["id"],
            {
                "catalog_item_id": item["id"],
                "discount_cents": 120,
                "valid_from_iso": "2026-09-10T00:00:01Z",
                "valid_to_iso": "2026-09-20T00:00:00Z",
                "per_member_limit": 5,
            },
            MANAGER,
        )
        second = validate_success(resp, expected_status=201)
        assert second["id"]
        assert second["valid_from_iso"] == "2026-09-10T00:00:01Z"


class TestValidationOrder:
    def test_nested_existence_validated_left_to_right(self, api):
        """PRD §2.8: "When an endpoint path contains multiple resource
        identifiers, the system validates their existence left to right — the
        club before the catalog item beneath it, the session before the line
        beneath it — and rejects with the not-found error for the first missing
        identifier."

        Design: Corner/validations/nested_existence_validated_left_to_right
        """
        resp = api.list_club_catalog_items(UNKNOWN_ID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLUB_NOT_FOUND)
