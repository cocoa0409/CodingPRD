"""Listing display rules, disputes, RBAC denials, and authentication (PRD §2.1, §3.1, §3.10)."""
from test_helpers import (
    ApiErrorId,
    create_agent,
    create_brokerage,
    create_dispute,
    create_listing,
    create_listing_payload,
    create_market,
    get_agent,
    get_success_data,
    make_agent_headers,
    make_brokerage_user_headers,
    set_clock,
    setup_market_with_active_order,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestDisplayRuleGate:
    def test_idx_limited_blocks_out_of_state_broker_direct_listing(self, api, marketplace_ops_headers):
        """PRD §3.1: "if it is `IDX_LIMITED`, the listing is allowed only when its
        `source_feed` is `MLS` or when the listing brokerage's `primary_state` matches
        the market's `state_code` ... An approval attempt that violates the display rule
        is rejected with `ERR_LISTING_DISPLAY_VIOLATION` (HTTP 422); the same check
        applies at ingestion time as a defensive gate."

        Design: Difficulty/cross_entity_state_dependency/listing_review_depends_on_market_agreement
        """
        set_clock()
        market = create_market(zip_code="94101", state_code="CA",
                               participation_agreement="IDX_LIMITED")
        brokerage = create_brokerage(primary_state="NV")
        agent = create_agent(brokerage["id"], license_state="CA")
        # The ingestion-time defensive gate rejects the violating listing outright.
        resp = api.create_listing(
            create_listing_payload(market["id"], brokerage["id"], agent["id"],
                                   source_feed="BROKER_DIRECT"),
            make_brokerage_user_headers(brokerage["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LISTING_DISPLAY_VIOLATION, 422)

    def test_idx_limited_allows_mls_listing_same_market(self, api, marketplace_ops_headers):
        """PRD §3.1: "if it is `IDX_LIMITED`, the listing is allowed only when its
        `source_feed` is `MLS` or when the listing brokerage's `primary_state` matches
        the market's `state_code`".

        Design: Difficulty/cross_entity_state_dependency/listing_review_depends_on_market_agreement
        """
        set_clock()
        market = create_market(zip_code="94102", state_code="CA",
                               participation_agreement="IDX_LIMITED")
        brokerage = create_brokerage(primary_state="NV")
        agent = create_agent(brokerage["id"], license_state="CA")
        listing = create_listing(market["id"], brokerage["id"], agent["id"], source_feed="MLS")
        reviewed = validate_success(
            api.review_listing(listing["id"], {"outcome": "APPROVE"}, marketplace_ops_headers)
        )
        assert reviewed["listing_status"] == "ACTIVE"


class TestListingTerminalLockdown:
    def test_rejected_listing_cannot_be_rereviewed_or_withdrawn(self, api, marketplace_ops_headers):
        """PRD §3.1: "Rejection moves the listing to `REJECTED` and records the
        `compliance_note`."
        PRD §3.1: "Review is a moderation act by `MarketplaceOps`. ... Approval requires
        the listing's `listing_status` to be `PENDING_REVIEW`".
        PRD §5: "`ERR_ALREADY_TERMINAL` | 409".

        Design: Corner/state_machines/listing_invalid_transition_from_terminal
        """
        set_clock()
        market = create_market(zip_code="97210", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        listing = create_listing(market["id"], brokerage["id"], agent["id"], source_feed="MLS")
        rejected = validate_success(
            api.review_listing(
                listing["id"], {"outcome": "REJECT", "compliance_note": "bad data"},
                marketplace_ops_headers,
            )
        )
        assert rejected["listing_status"] == "REJECTED"
        assert rejected["compliance_note"] == "bad data"
        re_review = api.review_listing(listing["id"], {"outcome": "APPROVE"}, marketplace_ops_headers)
        # PRD §5 lists both ERR_ALREADY_TERMINAL and ERR_INVALID_STATE at 409 without
        # mapping listing terminal rejections to a specific id — accept either.
        validate_error_is_one_of(
            re_review, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
        )
        withdraw = api.withdraw_listing(listing["id"], {}, marketplace_ops_headers)
        validate_error_is_one_of(
            withdraw, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
        )
        fresh = get_success_data(api.get_listing(listing["id"], marketplace_ops_headers))
        assert fresh["listing_status"] == "REJECTED"

    def test_withdrawn_listing_cannot_be_withdrawn_again(self, api, marketplace_ops_headers):
        """PRD §3.1: "An `ACTIVE` listing may later be withdrawn by an operator (or by a
        dispute resolution of `REMOVE`); withdrawal moves it to `WITHDRAWN`, records the
        `compliance_note`".
        PRD §5: "`ERR_ALREADY_TERMINAL` | 409".

        Design: Corner/state_machines/listing_invalid_transition_from_terminal
        """
        set_clock()
        market = create_market(zip_code="97211", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        listing = create_listing(market["id"], brokerage["id"], agent["id"], source_feed="MLS")
        validate_success(
            api.review_listing(listing["id"], {"outcome": "APPROVE"}, marketplace_ops_headers)
        )
        withdrawn = validate_success(api.withdraw_listing(listing["id"], {}, marketplace_ops_headers))
        assert withdrawn["listing_status"] == "WITHDRAWN"
        again = api.withdraw_listing(listing["id"], {}, marketplace_ops_headers)
        validate_error_is_one_of(
            again, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
        )


class TestDisputeResolution:
    def test_remove_resolution_withdraws_listing_same_request(self, api, marketplace_ops_headers):
        """PRD §3.10: "A `REMOVE` resolution on a listing-display dispute withdraws the
        listing (transitioning it to `WITHDRAWN` and recording a `compliance_note`). ...
        The dispute moves to `RESOLVED` with `resolved_at` set to now."

        Design: Corner/endpoints/dispute_resolution_executes_side_effect
        """
        set_clock()
        market = create_market(zip_code="97220", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        listing = create_listing(market["id"], brokerage["id"], agent["id"], source_feed="MLS")
        validate_success(
            api.review_listing(listing["id"], {"outcome": "APPROVE"}, marketplace_ops_headers)
        )
        dispute = create_dispute(
            brokerage["id"], dispute_type="LISTING_DISPLAY", listing_id=listing["id"],
            evidence="display violation",
        )
        resolved = validate_success(
            api.resolve_dispute(dispute["id"], {"resolution": "REMOVE"}, marketplace_ops_headers)
        )
        assert resolved["dispute_status"] == "RESOLVED"
        assert resolved["resolution"] == "REMOVE"
        assert resolved["resolved_at"] is not None
        fresh_listing = get_success_data(api.get_listing(listing["id"], marketplace_ops_headers))
        assert fresh_listing["listing_status"] == "WITHDRAWN"

    def test_keep_resolution_leaves_listing_active(self, api, marketplace_ops_headers):
        """PRD §3.10: "For `LISTING_DISPLAY` the valid resolutions are `KEEP` and
        `REMOVE`".

        Design: Corner/endpoints/dispute_resolution_executes_side_effect
        """
        set_clock()
        market = create_market(zip_code="97221", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        listing = create_listing(market["id"], brokerage["id"], agent["id"], source_feed="MLS")
        validate_success(
            api.review_listing(listing["id"], {"outcome": "APPROVE"}, marketplace_ops_headers)
        )
        dispute = create_dispute(
            brokerage["id"], dispute_type="LISTING_DISPLAY", listing_id=listing["id"],
            evidence="display question",
        )
        resolved = validate_success(
            api.resolve_dispute(dispute["id"], {"resolution": "KEEP"}, marketplace_ops_headers)
        )
        assert resolved["dispute_status"] == "RESOLVED"
        fresh_listing = get_success_data(api.get_listing(listing["id"], marketplace_ops_headers))
        assert fresh_listing["listing_status"] == "ACTIVE"


class TestRbac:
    def test_agent_cannot_resolve_dispute(self, api, marketplace_ops_headers):
        """PRD §2.1: "A request whose authenticated role is not authorized for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/disputes/{id}/resolve` | Resolve dispute | MarketplaceOps,
        PlatformAdmin |".

        Design: Corner/rbac/agent_cannot_resolve_dispute
        """
        set_clock()
        market = create_market(zip_code="97223", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        listing = create_listing(market["id"], brokerage["id"], agent["id"], source_feed="MLS")
        dispute = create_dispute(
            brokerage["id"], dispute_type="LISTING_DISPLAY", listing_id=listing["id"], evidence="x"
        )
        resp = api.resolve_dispute(
            dispute["id"], {"resolution": "REMOVE"}, make_agent_headers(agent["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        fresh = get_success_data(api.get_dispute(dispute["id"], marketplace_ops_headers))
        assert fresh["dispute_status"] == "OPEN"

    def test_agent_cannot_reject_dispute_either(self, api, marketplace_ops_headers):
        """PRD §2.1: "A request whose authenticated role is not authorized for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/agent_cannot_resolve_dispute
        """
        set_clock()
        market = create_market(zip_code="97232", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        listing = create_listing(market["id"], brokerage["id"], agent["id"], source_feed="MLS")
        dispute = create_dispute(
            brokerage["id"], dispute_type="LISTING_DISPLAY", listing_id=listing["id"], evidence="x"
        )
        resp = api.resolve_dispute(
            dispute["id"], {"resolution": "REJECT"}, make_agent_headers(agent["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        fresh = get_success_data(api.get_dispute(dispute["id"], marketplace_ops_headers))
        assert fresh["dispute_status"] == "OPEN"

    def test_brokerage_cannot_buy_share(self, api):
        """PRD §2.1: "A request whose authenticated role is not authorized for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/share-orders` | Create share order and quote deposit | Agent |".

        Design: Corner/rbac/brokerage_cannot_buy_share
        """
        set_clock()
        market = create_market(zip_code="97224", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        resp = api.create_share_order(
            {"market_id": market["id"], "buyer_agent_id": agent["id"],
             "share_bps": 1000, "duration_days": 30},
            make_brokerage_user_headers(brokerage["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        _, meta = validate_paginated(
            api.list_share_orders(
                make_brokerage_user_headers(brokerage["id"]), params={"market_id": market["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_brokerage_cannot_pause_share_order(self, api):
        """PRD §2.1: "A request whose authenticated role is not authorized for the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/share-orders/{id}/pause` | Pause active order | Agent |".

        Design: Corner/rbac/brokerage_cannot_buy_share
        """
        set_clock()
        market, brokerage, agent, order = setup_market_with_active_order(zip_code="97225")
        resp = api.pause_share_order(order["id"], make_brokerage_user_headers(brokerage["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        assert get_success_data(api.get_share_order(order["id"], make_brokerage_user_headers(brokerage["id"])))[
            "order_status"
        ] == "ACTIVE"

    def test_platform_admin_exercises_ops_and_brokerage_exclusive_actions(self, api, platform_admin_headers):
        """PRD §2.1: "PlatformAdmin has access to every endpoint."

        Design: Corner/rbac/platform_admin_superset
        """
        set_clock()
        market = create_market(zip_code="97225", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        listing = validate_success(
            api.create_listing(
                {"external_ref": "E-PA", "market_id": market["id"], "source_feed": "MLS",
                 "brokerage_id": brokerage["id"], "listing_agent_id": agent["id"]},
                platform_admin_headers,
            ),
            201,
        )
        assert listing["listing_status"] == "PENDING_REVIEW"
        run = validate_success(api.run_ops_sweep(platform_admin_headers), 201)
        assert run["seq"] == 1

    def test_platform_admin_can_capture_ops_only_moderation(self, api, platform_admin_headers):
        """PRD §2.1: "PlatformAdmin has access to every endpoint."
        PRD §4: "| POST | `/agents/{id}/suspend` | Suspend agent | MarketplaceOps,
        PlatformAdmin |".

        Design: Corner/rbac/platform_admin_superset
        """
        set_clock()
        market = create_market(zip_code="97234", state_code="OR")
        brokerage = create_brokerage()
        agent = create_agent(brokerage["id"])
        suspended = validate_success(api.suspend_agent(agent["id"], platform_admin_headers))
        assert suspended["agent_status"] == "SUSPENDED"
        assert get_agent(agent["id"])["agent_status"] == "SUSPENDED"


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or with a malformed value, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_401
        """
        set_clock()
        market = create_market(zip_code="10002", state_code="NY")
        resp = api._request("GET", f"/markets/{market['id']}", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

    def test_malformed_role_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or with a malformed value, is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_401
        """
        set_clock()
        market = create_market(zip_code="10003", state_code="NY")
        resp = api._request(
            "GET", f"/markets/{market['id']}", headers={"X-User-Role": "NotARole", "X-User-ID": "x"}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
