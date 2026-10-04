"""Entity contracts, response envelopes, uniqueness, and structure rules."""
from test_helpers import (
    ApiErrorId,
    NONEXISTENT_UUID,
    TEST_USERS,
    create_game,
    create_grant,
    create_market,
    create_offer,
    create_season,
    is_valid_uuid,
    make_subscriber_headers,
    register_account,
    register_account_payload,
    set_clock,
    setup_season_with_offer,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]
OPS = TEST_USERS["league_ops_headers"]


def test_grant_create_returns_active_defaults_and_version_one(api):
    """PRD §3.1: "A new grant is born with `status` `ACTIVE`, and `EXPIRED`
    and `TERMINATED` are its only terminal states." PRD §2.4: "`version` is an
    integer that increments by exactly one on every mutation of the resource".

    Design: Corner/entities/rights_grant_create_returns_defaults_and_version_one
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = validate_success(
        api.create_rights_grant(
            {
                "distributor_name": "StreamMax",
                "scope": "OUT_OF_MARKET",
                "exclusivity": "EXCLUSIVE",
                "effective_from": "2026-01-01T00:00:00Z",
                "effective_until": "2027-06-01T00:00:00Z",
                "max_commercial_occupancy_cap": 2000,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert grant["status"] == "ACTIVE"
    assert grant["version"] == 1
    assert grant["distributor_name"] == "StreamMax"
    assert grant["max_commercial_occupancy_cap"] == 2000
    assert is_valid_uuid(grant["id"])
    assert grant["created_at"]
    assert grant["updated_at"]


def test_market_get_round_trips_arrays(api):
    """PRD §2.5: "Each market has a unique, case-sensitive `code` (for example
    `NYC` or `DAL`), a human-readable `name`, a non-empty array
    `zip_prefixes` of three-digit ZIP prefix strings, and an array
    `home_team_codes` naming the teams whose games count as in-market there
    (this list may be empty)."

    Design: Corner/entities/market_get_returns_stored_row_unchanged
    """
    set_clock("2026-09-01T00:00:00Z")
    created = create_market(code="NYC", name="New York",
                            zip_prefixes=["100", "101"],
                            home_team_codes=["NYC"])
    fetched = validate_success(api.get_market(created["id"], SUPPORT))
    assert fetched["code"] == "NYC"
    assert fetched["zip_prefixes"] == ["100", "101"]
    assert fetched["home_team_codes"] == ["NYC"]


def test_subscriptions_pagination_counts_filtered_set(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`,
    `total_count`, and `has_more` in its `meta` object, where `total_count` is
    the full count of matching resources before pagination and `has_more`
    indicates whether additional rows exist beyond the returned window."

    Design: Corner/entities/subscriptions_list_paginates_total_count_and_has_more
    """
    ctx = setup_season_with_offer()
    offer = ctx["offer"]
    for email in ("p1@x.com", "p2@x.com", "p3@x.com"):
        account = register_account(email=email, billing_zip="10001")
        validate_success(
            api.create_subscription(
                account["id"], offer["id"],
                make_subscriber_headers(account["id"]),
            ),
            expected_status=201,
        )
    page1, meta1 = validate_paginated(
        api.list_subscriptions(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_subscriptions(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_nonexistent_subscription_returns_not_found(api):
    """PRD §2.8: "The first identifier that does not resolve to an existing
    resource fails the whole request with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/nonexistent_subscription_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.get_subscription(NONEXISTENT_UUID, ADMIN)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert err.get("message")

    body = resp.json()
    assert body["meta"].get("api_request_id")


def test_register_missing_billing_zip_rejected_without_creating(api):
    """PRD §3.5: "Anyone may register an **Account** without authentication,
    supplying an `email` (unique across all accounts, compared
    case-insensitively — a collision is `ERR_DUPLICATE_RESOURCE`), a
    `full_name`, an `account_kind` of `RESIDENTIAL` or `COMMERCIAL`, and a
    five-digit `billing_zip`." PRD §2.8: "Payload shape — required fields
    present, enum members valid, ZIPs five numeric digits, datetimes ISO 8601
    UTC (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/account_register_missing_required_field_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    validate_error(
        api.register_account(
            {
                "email": "nozip@x.com",
                "full_name": "No Zip",
                "account_kind": "RESIDENTIAL",
            },
            {},
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    rows, meta = validate_paginated(api.list_accounts(ADMIN))
    assert meta["total_count"] == 0


def test_season_optional_fields_take_declared_defaults(api):
    """PRD §3.2: "Two optional policy knobs ride along: `grace_days`, the
    complaint/refund eligibility window in days after purchase, defaulting to
    7 and bounded between 0 and 30 inclusive; and `student_discount_pct`, the
    whole-percent discount applied to the student tier's base price,
    defaulting to 50 and bounded between 0 and 90."

    Design: Corner/entities/season_optional_fields_take_declared_defaults
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = validate_success(
        api.create_season(
            {
                "rights_grant_id": grant["id"],
                "label": "2026-Regular",
                "regular_season_weeks": 18,
                "season_start_date": "2026-08-05T00:00:00Z",
                "season_end_date": "2026-12-09T00:00:00Z",
            },
            OPS,
        ),
        expected_status=201,
    )
    assert season["grace_days"] == 7
    assert season["student_discount_pct"] == 50


def test_billing_market_code_resolved_and_re_resolved_on_zip_change(api):
    """PRD §2.5: "At account registration, and again whenever the account's
    `billing_zip` is changed through an account update, the system resolves
    and stores `billing_market_code` (null if unmapped)."

    Design: Corner/entities/account_billing_market_code_is_computed_not_client_supplied
    """
    set_clock("2026-09-01T00:00:00Z")
    create_market(code="NYC", name="New York", zip_prefixes=["100"],
                  home_team_codes=["NYC"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    account = register_account(email="mv2@x.com", billing_zip="75023")
    assert account["billing_market_code"] == "DAL"

    updated = validate_success(
        api.update_account(account["id"], {"billing_zip": "10044"}, SUPPORT)
    )
    assert updated["billing_market_code"] == "NYC"


def test_server_mints_id_and_version_regardless_of_client_values(api):
    """PRD §2.4: "`id` is a server-minted UUID with no type prefix — it
    identifies the resource and nothing else." PRD §2.4: "`version` is an
    integer that increments by exactly one on every mutation of the resource".

    Design: Corner/entities/system_fields_ignore_client_input
    """
    set_clock("2026-09-01T00:00:00Z")
    payload = {
        "distributor_name": "StreamMax",
        "scope": "OUT_OF_MARKET",
        "exclusivity": "EXCLUSIVE",
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_until": "2027-06-01T00:00:00Z",
        "max_commercial_occupancy_cap": 2000,
        "id": "client-supplied-id-zzz",
        "version": 99,
        "created_at": "1999-01-01T00:00:00Z",
    }
    grant = validate_success(
        api.create_rights_grant(payload, ADMIN), expected_status=201
    )
    assert is_valid_uuid(grant["id"])
    assert grant["id"] != "client-supplied-id-zzz"
    assert grant["version"] == 1
    assert str(grant["created_at"]).startswith("2026-09-01T00:00:00")


def test_invalid_enum_bad_zip_and_same_team_game_rejected(api):
    """PRD §2.8: "Payload shape — required fields present, enum members valid,
    ZIPs five numeric digits, datetimes ISO 8601 UTC (`ERR_INVALID_REQUEST`)."
    PRD §3.3: "away and home team codes must differ" (surfacing as
    `ERR_SEASON_STRUCTURE`).

    Design: Corner/entities/invalid_enum_and_zip_shape_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])

    validate_error(
        api.register_account(
            register_account_payload(email="bad@x.com",
                                     account_kind="CORPORATE"),
            {},
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.register_account(
            register_account_payload(email="bad2@x.com", billing_zip="7500"),
            {},
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api.create_game(
            {
                "season_id": season["id"],
                "week_index": 4,
                "away_team_code": "DAL",
                "home_team_code": "DAL",
                "kickoff_at": "2026-08-30T17:00:00Z",
                "home_market_code": "DAL",
            },
            OPS,
        ),
        ApiErrorId.ERR_SEASON_STRUCTURE,
    )


def test_child_creation_with_nonexistent_parent_rejected(api):
    """PRD §2.8: "Endpoints that address resources through hierarchical paths
    validate path identifiers left to right — grant before season before
    week-slate or offer; account before subscription, venue license, complaint
    case, student verification, or override. The first identifier that does
    not resolve to an existing resource fails the whole request with
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/child_creation_requires_existing_parent
    """
    set_clock("2026-09-01T00:00:00Z")
    account = register_account(email="orp@x.com", billing_zip="10001")
    validate_error(
        api.create_season(
            {
                "rights_grant_id": NONEXISTENT_UUID,
                "label": "2026-Regular",
                "regular_season_weeks": 18,
                "season_start_date": "2026-08-05T00:00:00Z",
                "season_end_date": "2026-12-09T00:00:00Z",
            },
            OPS,
        ),
        ApiErrorId.ERR_NOT_FOUND,
    )
    validate_error(
        api.create_subscription(
            account["id"], NONEXISTENT_UUID,
            make_subscriber_headers(account["id"]),
        ),
        ApiErrorId.ERR_NOT_FOUND,
    )
    _, seasons_meta = validate_paginated(api.list_seasons(OPS))
    _, subs_meta = validate_paginated(api.list_subscriptions(ADMIN))
    assert seasons_meta["total_count"] == 0
    assert subs_meta["total_count"] == 0


def test_object_and_array_envelope_shapes(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources." PRD §2.3: "`limit` defaults to 10
    when omitted".

    Design: Corner/endpoints/success_envelope_shape_on_object_and_array_responses
    """
    set_clock("2026-09-01T00:00:00Z")
    market = create_market(code="NYC", name="New York", zip_prefixes=["100"],
                           home_team_codes=["NYC"])

    resp_obj = api.get_market(market["id"], OPS)
    body_obj = resp_obj.json()
    assert resp_obj.status_code == 200
    assert body_obj["response_type"] == "object"
    assert body_obj["meta"].get("api_request_id")
    assert body_obj["meta"].get("api_request_timestamp")
    assert body_obj["data"]["code"] == "NYC"

    resp_arr = api.list_markets(OPS)
    body_arr = resp_arr.json()
    assert resp_arr.status_code == 200
    assert body_arr["response_type"] == "array"
    assert body_arr["meta"]["total_count"] == 1
    assert body_arr["meta"]["has_more"] is False
    assert body_arr["meta"]["limit"] == 10
    assert body_arr["meta"]["offset"] == 0


def test_prefix_overlap_rejected_but_adjacent_prefix_admitted(api):
    """PRD §2.5: "One prefix may appear in at most one market across the
    entire system: creating or updating a market so that any of its prefixes
    is already claimed by another market is rejected with
    `ERR_MARKET_PREFIX_OVERLAP` (HTTP 409), which guarantees the lookup below
    is never ambiguous."

    Design: Difficulty/resource_temporal_overlap/market_zip_prefix_exclusion_no_gap_semantics
    """
    set_clock("2026-09-01T00:00:00Z")
    create_market(code="NYC", name="New York", zip_prefixes=["100"],
                  home_team_codes=["NYC"])
    validate_error(
        api.create_market(
            {
                "code": "NYC2",
                "name": "New York Duplicate",
                "zip_prefixes": ["100"],
                "home_team_codes": [],
            },
            OPS,
        ),
        ApiErrorId.ERR_MARKET_PREFIX_OVERLAP,
    )
    alb = validate_success(
        api.create_market(
            {
                "code": "ALB",
                "name": "Albany",
                "zip_prefixes": ["101"],
                "home_team_codes": [],
            },
            OPS,
        ),
        expected_status=201,
    )
    assert alb["code"] == "ALB"


def test_prefix_uniqueness_spans_all_markets_not_just_one(api):
    """PRD §2.5: "One prefix may appear in at most one market across the
    entire system".

    Design: Difficulty/resource_temporal_overlap/market_zip_prefix_exclusion_no_gap_semantics
    """
    set_clock("2026-09-01T00:00:00Z")
    create_market(code="DAL", name="Dallas", zip_prefixes=["750", "751"],
                  home_team_codes=["DAL"])
    validate_error(
        api.create_market(
            {
                "code": "HOU",
                "name": "Houston",
                "zip_prefixes": ["751"],
                "home_team_codes": [],
            },
            OPS,
        ),
        ApiErrorId.ERR_MARKET_PREFIX_OVERLAP,
    )


def test_offer_windows_are_half_open_and_adjacent_windows_hand_off(api):
    """PRD §3.5: "a purchase window [`valid_from`, `valid_until`) — the offer
    is purchasable at or after `valid_from` and strictly before `valid_until`,
    which must be after `valid_from`."

    Design: Difficulty/resource_temporal_overlap/offer_window_half_open_bracket_semantics
    """
    set_clock("2026-08-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    offer_o1 = create_offer(season["id"], valid_from="2026-08-01T00:00:00Z",
                            valid_until="2026-09-01T00:00:00Z")
    offer_o2 = create_offer(season["id"], base_price_cents=22000,
                            valid_from="2026-09-01T00:00:00Z",
                            valid_until="2026-12-31T00:00:00Z")
    acct1 = register_account(email="t1@x.com", billing_zip="10001")
    acct2 = register_account(email="t2@x.com", billing_zip="10001")
    acct3 = register_account(email="t3@x.com", billing_zip="10001")

    # At exactly O1.valid_from: purchasable.
    sub1 = validate_success(
        api.create_subscription(acct1["id"], offer_o1["id"],
                                make_subscriber_headers(acct1["id"])),
        expected_status=201,
    )
    assert sub1["status"] == "PENDING_PAYMENT"

    # At exactly O1.valid_until == O2.valid_from: O1 closed, O2 open.
    set_clock("2026-09-01T00:00:00Z")
    validate_error(
        api.create_subscription(acct2["id"], offer_o1["id"],
                                make_subscriber_headers(acct2["id"])),
        ApiErrorId.ERR_OFFER_NOT_AVAILABLE,
    )
    sub2 = validate_success(
        api.create_subscription(acct2["id"], offer_o2["id"],
                                make_subscriber_headers(acct2["id"])),
        expected_status=201,
    )
    assert sub2["status"] == "PENDING_PAYMENT"

    # At exactly O2.valid_until: closed.
    set_clock("2026-12-31T00:00:00Z")
    validate_error(
        api.create_subscription(acct3["id"], offer_o2["id"],
                                make_subscriber_headers(acct3["id"])),
        ApiErrorId.ERR_OFFER_NOT_AVAILABLE,
    )


def test_offer_purchasable_just_before_valid_until(api):
    """PRD §3.5: "the offer is purchasable at or after `valid_from` and
    strictly before `valid_until`".

    Design: Difficulty/resource_temporal_overlap/offer_window_half_open_bracket_semantics
    """
    set_clock("2026-08-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    offer = create_offer(season["id"], valid_from="2026-08-01T00:00:00Z",
                         valid_until="2026-09-01T00:00:00Z")
    account = register_account(email="edge@x.com", billing_zip="10001")
    set_clock("2026-08-31T23:59:59Z")
    sub = validate_success(
        api.create_subscription(account["id"], offer["id"],
                                make_subscriber_headers(account["id"])),
        expected_status=201,
    )
    assert sub["status"] == "PENDING_PAYMENT"


def test_duplicate_market_code_and_email_rejected(api):
    """PRD §3.3: "Beyond prefix non-overlap, the `code` itself is unique
    across all markets and case-sensitive — reusing an existing `code` on
    creation is `ERR_DUPLICATE_RESOURCE`." PRD §3.5: "supplying an `email`
    (unique across all accounts, compared case-insensitively — a collision is
    `ERR_DUPLICATE_RESOURCE`)".

    Design: Corner/cross_cutting_layers/duplicate_market_code_and_email_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_market(code="NYC", name="New York", zip_prefixes=["100"],
                  home_team_codes=["NYC"])
    register_account(email="dup@x.com", billing_zip="10001")
    validate_error(
        api.create_market(
            {
                "code": "NYC",
                "name": "New York Again",
                "zip_prefixes": ["102"],
                "home_team_codes": [],
            },
            OPS,
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )
    validate_error(
        api.register_account(
            register_account_payload(email="DUP@x.com", billing_zip="75001"),
            {},
        ),
        ApiErrorId.ERR_DUPLICATE_RESOURCE,
    )


def test_terminal_states_lock_down_grant_and_slate(api, league_ops_headers):
    """PRD §2.8: "Source-state legality — the target resource is in a valid
    source state for the requested transition; a transition attempted against
    a terminal state instead yields `ERR_ALREADY_TERMINAL` (both HTTP 409;
    non-terminal wrong-state calls yield `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/terminal_states_lockdown_all_transitions
    """
    set_clock("2026-08-20T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate = validate_success(
        api.create_week_slate(
            {"season_id": season["id"], "week_index": 3}, OPS
        ),
        expected_status=201,
    )
    create_game(season["id"], week_index=3, away_team_code="KC",
                home_team_code="DAL", kickoff_at="2026-08-23T17:00:00Z",
                home_market_code="DAL")
    slate_now = validate_success(api.get_week_slate(slate["id"], OPS))
    validate_success(
        api.finalize_week_slate(slate["id"], slate_now["version"], OPS)
    )
    # PRD §3.4: locking is legal only once the logical clock has reached or
    # passed the week's first kickoff (2026-08-23T17:00:00Z).
    set_clock("2026-08-24T00:00:00Z")
    validate_success(api.lock_week_slate(slate["id"], OPS))

    grant2 = create_grant(distributor_name="SecondDistro",
                          exclusivity="NON_EXCLUSIVE",
                          max_commercial_occupancy_cap=500)
    validate_success(api.terminate_rights_grant(grant2["id"], ADMIN))

    validate_error(
        api.terminate_rights_grant(grant2["id"], ADMIN),
        ApiErrorId.ERR_ALREADY_TERMINAL,
    )
    # PRD §3.4: "selection moves and reopen attempts against a locked slate
    # are rejected with `ERR_SLATE_LOCKED` (HTTP 409)".
    validate_error(
        api.reopen_week_slate(slate["id"], league_ops_headers),
        ApiErrorId.ERR_SLATE_LOCKED,
    )
    validate_error(
        api.lock_week_slate(slate["id"], league_ops_headers),
        ApiErrorId.ERR_ALREADY_TERMINAL,
    )
    grant2_now = validate_success(api.get_rights_grant(grant2["id"], ADMIN))
    assert grant2_now["status"] == "TERMINATED"
    slate_now2 = validate_success(api.get_week_slate(slate["id"], OPS))
    assert slate_now2["slate_status"] == "LOCKED"
