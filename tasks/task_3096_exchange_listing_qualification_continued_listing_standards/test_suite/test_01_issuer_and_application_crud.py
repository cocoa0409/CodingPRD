"""Issuer registration and listing-application CRUD corners (PRD §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    create_application,
    create_application_payload,
    create_issuer,
    create_issuer_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_issuer_officer_headers,
    reset_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers import TEST_USERS

ANALYST = TEST_USERS["listing_analyst_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


def test_issuer_create_returns_every_declared_field_and_starts_pre_listing(api):
    """PRD §3.1: "A `ListingAnalyst` registers a new issuer by supplying its `legal_name` and `ticker_symbol`."
    PRD §3.1: "The issuer begins in `PRE_LISTING` status."
    PRD §2.4: "Every entity carries an id field, a server-minted UUID with no type prefix.
    Entities with common_fields: true also carry created_at ... updated_at ... and version
    (an integer starting at 1, incremented on every mutation)."

    Design: Corner/entities/issuer_create_returns_every_declared_field_and_starts_pre_listing
    """
    reset_clock()
    resp = api.create_issuer(
        {"legal_name": "Corner Creation Corp", "ticker_symbol": "CCRT"}, ANALYST)
    data = validate_success(resp, 201)
    assert data["legal_name"] == "Corner Creation Corp"
    assert data["ticker_symbol"] == "CCRT"
    assert data["status"] == "PRE_LISTING"
    assert data["version"] == 1
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_issuer_get_returns_stored_fields_unchanged(api):
    """PRD §4 endpoint table: "GET /issuers/{issuerId} | Get an issuer | ListingAnalyst,
    IssuerOfficer, HearingsOfficer, ListingsCouncil, FinanceOfficer" — a GET by any
    permitted role round-trips the stored row.

    Design: Corner/entities/issuer_get_returns_stored_fields_unchanged
    """
    reset_clock()
    issuer = create_issuer(legal_name="Corner Creation Corp", ticker_symbol="CCRT")
    resp = api.get_issuer(issuer["id"], FINANCE)
    data = validate_success(resp, 200)
    assert data["legal_name"] == "Corner Creation Corp"
    assert data["ticker_symbol"] == "CCRT"
    assert data["status"] == "PRE_LISTING"


def test_issuers_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The default limit is 10, with a minimum of 1 and a maximum of 100;
    the default offset is 0. The meta object of a list response includes limit, offset,
    total_count, and has_more."

    Design: Corner/entities/issuers_list_paginates_with_total_count_and_has_more
    """
    reset_clock()
    create_issuer(legal_name="Corner Creation Corp", ticker_symbol="CCRT")
    create_issuer(legal_name="Second Corner Corp", ticker_symbol="CRN2")
    create_issuer(legal_name="Third Corner Corp", ticker_symbol="CRN3")

    rows, meta = validate_paginated(api.list_issuers(ANALYST, params={"limit": 2, "offset": 0}))
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(api.list_issuers(ANALYST, params={"limit": 2, "offset": 2}))
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, _ = validate_paginated(api.list_issuers(ANALYST, params={"status": "PRE_LISTING"}))
    assert len(rows) == 3
    rows, _ = validate_paginated(api.list_issuers(ANALYST, params={"status": "LISTED"}))
    assert len(rows) == 0

    rows, meta = validate_paginated(api.list_issuers(ANALYST))
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_issuer_get_unknown_id_returns_issuer_not_found(api):
    """PRD §2.9: "URL path parameters are validated left-to-right: the issuer is resolved
    before any nested resource. An unknown nested identifier yields the entity-specific
    404 error—ERR_ISSUER_NOT_FOUND ...—depending on which path segment failed to resolve."

    Design: Corner/entities/issuer_get_unknown_id_returns_issuer_not_found
    """
    reset_clock()
    resp = api.get_issuer("00000000-0000-4000-8000-000000000000", ANALYST)
    err = validate_error(resp, ApiErrorId.ERR_ISSUER_NOT_FOUND)
    assert err["error_id"] == "ERR_ISSUER_NOT_FOUND"
    assert err["message"]
    assert resp.json()["response_type"] == "error"


def test_nested_application_under_unknown_issuer_returns_issuer_not_found(api):
    """PRD §2.9: "URL path parameters are validated left-to-right: the issuer is resolved
    before any nested resource. An unknown nested identifier yields the entity-specific
    404 error ... depending on which path segment failed to resolve."

    Design: Corner/entities/nested_application_under_unknown_issuer_returns_issuer_not_found
    """
    reset_clock()
    resp = api.get_listing_application(
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
        ANALYST)
    err = validate_error(resp, ApiErrorId.ERR_ISSUER_NOT_FOUND)
    assert err["error_id"] == "ERR_ISSUER_NOT_FOUND"
    assert err["error_id"] != "ERR_APPLICATION_NOT_FOUND"


def test_application_create_missing_audit_committee_returns_invalid_request(api):
    """PRD §3.1: "An IssuerOfficer files a listing application for their issuer, providing
    the target_tier ..., the full board_directors array, the audit_committee and
    compensation_committee arrays, and a comprehensive set of financial and liquidity
    metrics: ..." — audit_committee is a required input; omitting it violates the payload
    schema (ERR_INVALID_REQUEST, PRD §5).

    Design: Corner/entities/application_create_missing_audit_committee_returns_invalid_request
    """
    reset_clock()
    issuer = create_issuer()
    payload = create_application_payload()
    del payload["audit_committee"]
    resp = api.create_listing_application(
        issuer["id"], payload, make_issuer_officer_headers(issuer["id"]))
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"
    assert err["error_id"] != "ERR_GOVERNANCE_COMPOSITION"
    rows = get_success_data(api.list_listing_applications(
        issuer["id"], ANALYST))
    assert isinstance(rows, list) and len(rows) == 0


def test_application_create_defaults_is_transfer_and_kind(api):
    """PRD §3.1: "The `is_transfer_from_exchange` flag defaults to false; the `application_kind` defaults to `INITIAL` but may be `TRANSFER`, `TIER_TRANSFER`, or `READMISSION`."
    PRD §3.1: "The application begins in `DRAFT` status."

    Design: Corner/entities/application_create_defaults_is_transfer_and_kind
    """
    reset_clock()
    issuer = create_issuer()
    resp = api.create_listing_application(
        issuer["id"], create_application_payload(),
        make_issuer_officer_headers(issuer["id"]))
    data = validate_success(resp, 201)
    assert data["is_transfer_from_exchange"] is False
    assert data["application_kind"] == "INITIAL"
    assert data["status"] == "DRAFT"
    assert data["version"] == 1


def test_application_create_extra_status_field_is_ignored_input(api):
    """PRD §3.1: "The application begins in `DRAFT` status." — status is system-set, never
    client-supplied; PRD §2.4: version is "an integer starting at 1, incremented on every
    mutation".

    Design: Corner/entities/application_create_extra_status_field_is_ignored_input
    """
    reset_clock()
    issuer = create_issuer()
    payload = create_application_payload()
    payload["status"] = "APPROVED"
    payload["version"] = 99
    resp = api.create_listing_application(
        issuer["id"], payload, make_issuer_officer_headers(issuer["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1


def test_application_create_out_of_enum_target_tier_returns_invalid_request(api):
    """PRD §3.1: the target_tier is "one of `GLOBAL_SELECT`, `GLOBAL`, or `CAPITAL`" — a
    value outside the closed enum violates the payload schema (ERR_INVALID_REQUEST,
    PRD §5).

    Design: Corner/entities/application_create_out_of_enum_target_tier_returns_invalid_request
    """
    reset_clock()
    issuer = create_issuer()
    payload = create_application_payload(target_tier="MAIN_MARKET")
    resp = api.create_listing_application(
        issuer["id"], payload, make_issuer_officer_headers(issuer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows = get_success_data(api.list_listing_applications(issuer["id"], ANALYST))
    assert isinstance(rows, list) and len(rows) == 0


def test_snapshot_create_with_denominator_one_split_returns_invalid_request(api):
    """PRD §3.9: "The `split_ratio_denominator` must be at least 2." A 1-for-1 'reverse
    split' violates the declared range (ERR_INVALID_REQUEST, PRD §5).

    Design: Corner/entities/snapshot_create_with_denominator_one_split_returns_invalid_request
    """
    reset_clock()
    issuer = create_issuer()
    resp = api.create_corporate_action(
        issuer["id"], {"action_type": "REVERSE_SPLIT", "split_ratio_denominator": 1},
        make_issuer_officer_headers(issuer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    rows = get_success_data(api.list_corporate_actions(issuer["id"], ANALYST))
    assert isinstance(rows, list) and len(rows) == 0


def test_market_data_snapshot_is_immutable_no_update_path(api):
    """PRD §2.4: "The MarketDataSnapshot and ComplianceRecord entities are immutable
    observation logs: they carry only id and created_at; both updated_at and version are
    absent from their representations."

    Design: Corner/entities/market_data_snapshot_is_immutable_no_update_path
    """
    reset_clock()
    issuer = create_issuer()
    resp = api.create_snapshot(
        issuer["id"],
        {"trade_date": "2026-09-01", "closing_bid_cents": 150,
         "market_value_publicly_held_cents": 500_000_000,
         "market_value_listed_securities_cents": 600_000_000_000,
         "round_lot_holders": 400, "total_shareholders": 400},
        ANALYST)
    snap = validate_success(resp, 201)
    rows = get_success_data(api.list_snapshots(issuer["id"], ANALYST))
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == snap["id"]
    assert row["closing_bid_cents"] == 150
    assert is_iso8601_timestamp(row["created_at"])
    assert "version" not in row
    assert "updated_at" not in row


def test_listing_tier_is_computed_from_approving_application(api):
    """PRD §3.3: "For INITIAL, TRANSFER, and READMISSION applications, the system creates
    a Listing with tier set to the application's target_tier, status ACTIVE, and
    application_id recording which application's approval created the listing; the
    issuer's status becomes LISTED".

    Design: Corner/entities/listing_tier_is_computed_from_approving_application
    """
    reset_clock()
    issuer = create_issuer()
    app = create_application(issuer["id"], target_tier="CAPITAL")
    submit_application(issuer["id"], app["id"])
    api.approve_application(issuer["id"], app["id"],
                            get_success_data(api.get_issuer(issuer["id"], ANALYST))["version"],
                            ANALYST)
    listings = get_success_data(api.list_listings(issuer["id"], ANALYST))
    assert len(listings) == 1
    listing = listings[0]
    assert listing["tier"] == "CAPITAL"
    assert listing["status"] == "ACTIVE"
    assert listing["application_id"] == app["id"]
    issuer_now = get_success_data(api.get_issuer(issuer["id"], ANALYST))
    assert issuer_now["status"] == "LISTED"
