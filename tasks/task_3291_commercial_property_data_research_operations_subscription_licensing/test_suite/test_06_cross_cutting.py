"""Cross-cutting reading surfaces: pagination, immutability, access control, cycles."""

from test_helpers import (
    ApiErrorId,
    assert_pagination_meta,
    NON_EXISTENT_UUID,
    add_distinct_user,
    create_lease_comparable,
    create_listing,
    create_property,
    ensure_researching,
    get_success_data,
    open_enforcement_case,
    set_logical_clock,
    setup_active_contract,
    setup_brokerage_org,
    setup_listing_licensed_brokerage,
    setup_provider_org,
    setup_subscriber_org,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_properties_list_paginates_and_filters_by_market(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to 10, its minimum is 1, and its maximum is 100."

    PRD §2.3: "Whatever query filters an endpoint accepts — a market, a status, an owning organization, a parent resource — narrow the result set without changing the sort."

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, and `total_count` counts the matching rows before pagination is applied."

    Design: Corner/entities/properties_list_paginates_and_filters_by_market
    """
    provider = setup_provider_org()
    for address in ("1400 Ross Ave", "5000 Maple Ave", "7500 N Central Expy"):
        create_property(provider["creator_headers"], market="TX-DALLAS", address_line=address)

    first_page, meta = validate_paginated(
        api.list_properties(provider["creator_headers"], {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert_pagination_meta(meta, total_count=3, limit=2, offset=0, has_more=True)

    second_page, meta2 = validate_paginated(
        api.list_properties(provider["creator_headers"], {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert_pagination_meta(meta2, total_count=3, limit=2, offset=2, has_more=False)

    filtered, meta3 = validate_paginated(
        api.list_properties(provider["creator_headers"], {"market": "TX-DALLAS"})
    )
    assert len(filtered) == 3
    assert meta3["total_count"] == 3

    default_page, meta4 = validate_paginated(
        api.list_properties(provider["creator_headers"])
    )
    assert len(default_page) == 3
    assert meta4["limit"] == 10
    assert meta4["offset"] == 0


def test_usage_event_get_returns_the_immutable_access_record(api):
    """PRD §2.6: "`UsageEvent` is the one exception. It is created with `common_fields: false`, and therefore carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because a usage record is an immutable ledger entry rather than a mutable resource."

    Design: Corner/entities/usage_event_get_returns_the_immutable_access_record
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(subscriber, annual_fee_cents=100_000)
    event = validate_success(
        api.create_usage_event(
            active["seat"]["id"],
            {"market": "TX-DALLAS", "event_type": "API_QUERY", "record_count": 4,
             "distinguishing_ip": "203.0.113.7", "occurred_at": "2026-09-02T09:00:00Z"},
            active["occupant_headers"],
        ),
        201,
    )
    fetched = get_success_data(
        api.get_usage_event(event["id"], active["admin_headers"])
    )
    assert fetched["record_count"] == 4
    assert fetched["event_type"] == "API_QUERY"
    assert "version" not in fetched
    assert "updated_at" not in fetched


def test_lease_comparable_window_is_accepted_when_chronological(api):
    """PRD §3.3: "The `lease_end` must be strictly after the `lease_start`, or the request is refused with `ERR_LEASE_WINDOW_INVALID` (HTTP 422)."

    PRD §3.3: "The server stamps `recorded_at` with the logical clock."

    Design: Corner/validations/lease_comparable_window_is_accepted_when_chronological
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(provider["creator_headers"])
    ensure_researching(prop["id"], provider["creator_headers"])

    accepted = create_lease_comparable(
        prop["id"], provider["creator_headers"], lease_start="2026-06-01T00:00:00Z",
        lease_end="2027-06-01T00:00:00Z",
    )
    assert accepted["tenant_name"] == "Harborline Logistics Inc"
    assert accepted["recorded_at"] == "2026-09-01T00:00:00Z"

    inverted = api.create_lease_comparable(
        prop["id"],
        {"tenant_name": "Harborline Logistics Inc", "lease_start": "2027-06-01T00:00:00Z",
         "lease_end": "2026-06-01T00:00:00Z", "escalated_rent_psf": 34.0,
         "effective_rent_psf": 32.0, "renewal_option": False},
        provider["creator_headers"],
    )
    validate_error(inverted, ApiErrorId.ERR_LEASE_WINDOW_INVALID)
    assert inverted.status_code == 422

    rows, meta = validate_paginated(
        api.list_lease_comparables(provider["creator_headers"], {"property_id": prop["id"]})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1


def test_listing_get_with_an_unknown_id_returns_listing_not_found(api):
    """PRD §2.12: "The not-found identifiers are specific to the entity being resolved: `ERR_ORGANIZATION_NOT_FOUND`, `ERR_USER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_ATTRIBUTE_NOT_FOUND`, `ERR_SOURCE_DOCUMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SEAT_NOT_FOUND` and `ERR_ENFORCEMENT_CASE_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/endpoints/listing_get_with_an_unknown_id_returns_listing_not_found
    """
    brokerage = setup_brokerage_org()
    resp = api.get_listing(NON_EXISTENT_UUID, brokerage["publisher_headers"])
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_FOUND)
    assert resp.status_code == 404


def test_withdrawal_of_a_draft_listing_returns_invalid_state(api):
    """PRD §3.8: "a `BrokerPublisher` moving a listing from `PUBLISHED` to `WITHDRAWN` requires only that the listing currently hold `PUBLISHED`, or the request is refused with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/endpoints/withdrawal_of_a_draft_listing_returns_invalid_state
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    brokerage = setup_brokerage_org()
    provider = setup_provider_org()
    prop = create_property(provider["creator_headers"])
    listing = create_listing(prop["id"], brokerage["org"]["id"],
                             brokerage["publisher_headers"])

    resp = api.withdraw_listing(listing["id"], brokerage["publisher_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    assert get_success_data(
        api.get_listing(listing["id"], brokerage["publisher_headers"])
    )["status"] == "DRAFT"


def test_anonymous_call_without_role_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request in which either header is absent, or in which either header is present but empty, is rejected with `ERR_UNAUTHENTICATED` and carries HTTP status 401."

    PRD §2.14: "Authentication and request shape come first: a missing or empty `X-User-ID` or `X-User-Role` header surfaces as `ERR_UNAUTHENTICATED` (401)

    Design: Corner/rbac/anonymous_call_without_role_headers_returns_unauthenticated
    """
    provider = setup_provider_org()
    prop = create_property(provider["creator_headers"])
    resp = api.start_research(prop["id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401

    # An authenticated call by an analyst assigned to a different market reaches
    # the scope check instead, so the 401 above came from the auth gate.
    nm_analyst, nm_headers = add_distinct_user(
        provider["org"]["id"], role="RESEARCH_ANALYST",
        full_name="Yusuf Adeyemi", assigned_market="NM-ALBUQUERQUE",
    )
    out_of_market = api.start_research(prop["id"], nm_headers)
    validate_error(out_of_market, ApiErrorId.ERR_PROPERTY_NOT_FOUND)
    assert out_of_market.status_code == 404


def test_run_research_cycle_expires_a_published_listing_past_its_ttl(api):
    """PRD §3.11: "Listing expiry comes next: every `PUBLISHED` listing whose `expires_at` the logical clock has reached is moved to `EXPIRED`."

    PRD §3.8: "A successful publication sets the status to `PUBLISHED`, stamps `published_at` with the logical clock, and sets `expires_at` to that instant plus the requested `duration_days` days."

    Design: Corner/cross_cutting_complexity_layers/run_research_cycle_expires_a_published_listing_past_its_ttl
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    brokerage = setup_listing_licensed_brokerage(markets=["TX-DALLAS"])
    provider = setup_provider_org()
    prop = create_property(provider["creator_headers"])
    listing = create_listing(
        prop["id"], brokerage["org"]["id"], brokerage["publisher_headers"],
        duration_days=90,
    )
    published = validate_success(
        api.publish_listing(listing["id"], brokerage["publisher_headers"]), 200
    )
    assert published["expires_at"] == "2026-11-30T00:00:00Z"

    set_logical_clock("2026-12-15T00:00:00Z")
    cycle = validate_success(
        api.run_research_cycle({"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}), 200
    )
    assert cycle["expired_listings"] >= 1
    assert get_success_data(
        api.get_listing(listing["id"], brokerage["publisher_headers"])
    )["status"] == "EXPIRED"


def test_settlement_reinstates_the_terminated_contract_and_conserves_the_market_count(api):
    """PRD §3.7: "The suspension's contract casualties are repaired rather than merely masked: every licensing contract of that organization which this escalation terminated is restored to `ACTIVE`, the `access_revoked` flag on the seats of those contracts is reset to false, and the organization's `authorized_market_count` is recomputed."

    Design: Difficulty/compensating_invariant/settlement_reinstatement_conserves_authorized_market_count
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    subscriber = setup_subscriber_org(
        org_name="Cedar Point Capital Partners", service_tier="MID_MARKET",
    )
    provider = setup_provider_org(
        org_name="Harborline Data Services", service_tier="ENTERPRISE", with_officer=True,
    )
    active = setup_active_contract(
        subscriber, annual_fee_cents=200_000, seat_count=3,
        licensed_markets=["TX-DALLAS", "TX-HOUSTON"],
        term_start="2026-05-01T00:00:00Z", term_end="2027-05-01T00:00:00Z",
        audit_intensity="ENHANCED",
    )
    contract_id = active["contract"]["id"]
    before = get_success_data(api.get_organization(
        subscriber["org"]["id"], {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}
    ))
    assert before["authorized_market_count"] == 2

    case = open_enforcement_case(
        subscriber["org"]["id"], contract_id, provider["officer_headers"],
        finding_cents=60_000_000, fee_rate_pct=1.25,
    )
    validate_success(api.escalate_case(case["id"], provider["officer_headers"]), 200)
    suspended = get_success_data(api.get_organization(
        subscriber["org"]["id"], {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}
    ))
    assert suspended["authorized_market_count"] == 0

    settled = validate_success(
        api.settle_case(case["id"], {"settlement_cents": 75_000_000}, provider["officer_headers"]),
        200,
    )
    assert settled["status"] == "SETTLED"
    after = get_success_data(api.get_organization(
        subscriber["org"]["id"], {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}
    ))
    assert after["status"] == "ACTIVE"
    assert after["authorized_market_count"] == before["authorized_market_count"]

    restored = get_success_data(api.get_contract(contract_id, active["admin_headers"]))
    assert restored["status"] == "ACTIVE"
    seat = get_success_data(api.get_seat(active["seat"]["id"], active["admin_headers"]))
    assert seat["access_revoked"] is False


def test_settlement_restores_the_terminated_contract_and_conserves_active_contracts(api):
    """PRD §2.8: "`active_contract_count` counts this organization's contracts whose status is `ACTIVE` or `GRACE`."

    PRD §3.7: "On success the case becomes `SETTLED` and the respondent organization returns to `ACTIVE`."

    Design: Difficulty/compensating_invariant/settlement_reinstatement_conserves_authorized_market_count
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    subscriber = setup_subscriber_org(
        org_name="Cedar Point Capital Partners", service_tier="MID_MARKET",
    )
    provider = setup_provider_org(
        org_name="Harborline Data Services", service_tier="ENTERPRISE", with_officer=True,
    )
    active = setup_active_contract(
        subscriber, annual_fee_cents=200_000, seat_count=3,
        licensed_markets=["TX-DALLAS", "TX-HOUSTON"],
        term_start="2026-05-01T00:00:00Z", term_end="2027-05-01T00:00:00Z",
        audit_intensity="ENHANCED",
    )
    platform = {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}
    started = get_success_data(api.get_organization(subscriber["org"]["id"], platform))
    assert started["active_contract_count"] == 1

    case = open_enforcement_case(
        subscriber["org"]["id"], active["contract"]["id"], provider["officer_headers"],
        finding_cents=60_000_000, fee_rate_pct=1.25,
    )
    validate_success(api.escalate_case(case["id"], provider["officer_headers"]), 200)
    suspended = get_success_data(api.get_organization(subscriber["org"]["id"], platform))
    assert suspended["active_contract_count"] == 0

    validate_success(
        api.settle_case(case["id"], {"settlement_cents": 75_000_000}, provider["officer_headers"]),
        200,
    )
    settled = get_success_data(api.get_organization(subscriber["org"]["id"], platform))
    assert settled["active_contract_count"] == 1
    assert settled["active_contract_count"] == started["active_contract_count"]


def test_contract_with_a_non_positive_fee_is_refused(api):
    """PRD §3.6: "The `seat_count` must be at least one, and the `annual_fee_cents` must be strictly positive — a non-positive fee is refused with `ERR_FEE_NOT_POSITIVE` (HTTP 409)."

    Design: Corner/validations/contract_with_a_non_positive_fee_is_refused
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    resp = api.create_contract(
        {
            "subscriber_organization_id": subscriber["org"]["id"],
            "product": "CORE_MARKET_DATA",
            "licensed_markets": ["TX-DALLAS"],
            "seat_count": 5,
            "annual_fee_cents": 0,
            "auto_renew": True,
            "renewal_notice_days": 30,
            "term_start": "2026-09-01T00:00:00Z",
            "term_end": "2027-09-01T00:00:00Z",
            "audit_intensity": "STANDARD",
        },
        subscriber["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FEE_NOT_POSITIVE)
    assert resp.status_code == 409

    accepted = validate_success(
        api.create_contract(
            {
                "subscriber_organization_id": subscriber["org"]["id"],
                "product": "CORE_MARKET_DATA",
                "licensed_markets": ["TX-DALLAS"],
                "seat_count": 5,
                "annual_fee_cents": 1,
                "auto_renew": True,
                "renewal_notice_days": 30,
                "term_start": "2026-09-01T00:00:00Z",
                "term_end": "2027-09-01T00:00:00Z",
                "audit_intensity": "STANDARD",
            },
            subscriber["admin_headers"],
        ),
        201,
    )
    assert accepted["status"] == "PENDING"