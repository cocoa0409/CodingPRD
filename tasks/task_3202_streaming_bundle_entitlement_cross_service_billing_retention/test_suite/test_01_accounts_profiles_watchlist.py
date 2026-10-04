"""Account, profile, and watchlist coverage."""
from test_helpers import (
    TEST_USERS,
    add_watchlist_item_payload,
    assert_service_profile,
    assert_subscriber_account,
    create_service_profile_payload,
    create_subscriber_account_payload,
    get_profile,
    is_valid_uuid,
    make_subscriber_headers,
    register_account,
    setup_account_with_billing,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SUPPORT = TEST_USERS["support_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_register_account_missing_email_returns_invalid_request(api, anonymous_headers):
    """PRD §4: "Request bodies must be well-formed — a missing required field, a
    malformed type, a bad enum value, or a malformed ISO 8601 datetime is
    rejected with ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/register_account_missing_email_returns_invalid_request
    """
    resp = api.create_subscriber_account({"full_name": "No Email"}, anonymous_headers)
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_register_account_duplicate_email_rejected(api, anonymous_headers):
    """PRD §3.2: "The email is globally unique across all accounts — a duplicate
    registration fails with ERR_DUPLICATE_EMAIL (HTTP 409)."

    Design: Corner/entities/register_account_duplicate_email_rejected
    """
    first = api.create_subscriber_account(
        create_subscriber_account_payload(email="dup@x.com", full_name="First"), ANON
    )
    validate_success(first, 201)
    resp = api.create_subscriber_account(
        create_subscriber_account_payload(email="dup@x.com", full_name="Second"), ANON
    )
    validate_error(resp, "ERR_DUPLICATE_EMAIL", 409)


def test_system_fields_id_and_version_server_generated(api, anonymous_headers):
    """PRD §2.4: "Every resource carries an id that is a server-minted UUID with
    no type prefix."
    PRD §2.4: "Resources with full bookkeeping — SubscriberAccount, ServiceProfile,
    BillingAccount, Subscription, Entitlement, Migration, RetentionRedemption,
    and Invoice — additionally carry created_at and updated_at, both ISO 8601 UTC
    timestamps with three fractional digits, and an integer version that starts
    at 1 and increments by 1 on every mutation of the resource."
    PRD §2.5: "Instead it consults a logical clock whose startup default is
    exactly 2026-09-01T00:00:00Z; before any explicit advance, every
    time-sensitive rule evaluates against that default."

    Design: Corner/entities/system_fields_id_and_version_server_generated
    """
    resp = api.create_subscriber_account(
        create_subscriber_account_payload(email="sys@x.com", full_name="Sys Fields"), ANON
    )
    data = validate_success(resp, 201)
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert data["created_at"].startswith("2026-09-01T00:00:00"), (
        f"created_at must reflect the logical clock default, got {data['created_at']}"
    )
    assert data["version"] == 1


def test_account_defaults_credit_and_counts_zero(api, anonymous_headers):
    """PRD §3.2: "The account also carries three ledger fields that start empty:
    grandfathered_price_cents and grandfathered_plan_code are null until the
    first subscription activates, and account_credit_cents and
    retention_redemption_count start at 0."
    PRD §3.2: "an Anonymous caller supplies an email and full_name and receives
    a SubscriberAccount whose account_status starts ACTIVE."

    Design: Corner/entities/account_defaults_credit_and_counts_zero
    """
    resp = api.create_subscriber_account(
        create_subscriber_account_payload(email="def@x.com", full_name="Defaults"), ANON
    )
    data = validate_success(resp, 201)
    assert_subscriber_account(data)
    assert data["account_credit_cents"] == 0
    assert data["retention_redemption_count"] == 0
    assert data["grandfathered_price_cents"] is None
    assert data["grandfathered_plan_code"] is None
    assert data["account_status"] == "ACTIVE"


def test_profile_kids_mode_forces_cap_computed(api):
    """PRD §3.3: "Setting kids_mode to true forces the cap to TV_PG regardless
    of any supplied value — this applies both at creation and on later
    parental-control updates, which may set maturity_rating_cap, kids_mode,
    or both."

    Design: Corner/entities/profile_kids_mode_forces_cap_computed
    """
    account = register_account(email="kids@x.com")
    hdrs = make_subscriber_headers(account["id"])
    resp = api.create_service_profile(
        account["id"],
        create_service_profile_payload(
            service="DPLUS", kids_mode=True, maturity_rating_cap="TV_MA"
        ),
        hdrs,
    )
    data = validate_success(resp, 201)
    assert_service_profile(data)
    assert data["maturity_rating_cap"] == "TV_PG"
    assert data["kids_mode"] is True


def test_watchlist_count_derived_field_reconciliation(api):
    """PRD §3.3: "Each successful add increments the profile's watchlist_count
    by 1 and each removal decrements it by 1; the watchlist may be listed with
    an optional title_maturity filter."

    Design: Corner/entities/watchlist_count_derived_field_reconciliation
    """
    account = register_account(email="wl@x.com")
    hdrs = make_subscriber_headers(account["id"])
    profile = validate_success(
        api.create_service_profile(
            account["id"], create_service_profile_payload(service="DPLUS"), hdrs
        ),
        201,
    )
    r1 = api.add_watchlist_item(
        profile["id"], add_watchlist_item_payload("t1", "TV_G"), hdrs
    )
    validate_success(r1, 201)
    r2 = api.add_watchlist_item(
        profile["id"], add_watchlist_item_payload("t2", "TV_MA"), hdrs
    )
    item2 = validate_success(r2, 201)
    del_resp = api.delete_watchlist_item(profile["id"], item2["id"], hdrs)
    assert del_resp.status_code == 204, f"delete must return 204, got {del_resp.status_code}"
    profile_after = get_profile(profile["id"], hdrs)
    assert profile_after["watchlist_count"] == 1, (
        f"after two adds and one removal watchlist_count must be 1, got {profile_after['watchlist_count']}"
    )


def test_get_account_not_found(api, platform_admin_headers):
    """PRD §2.8: "The first unresolved segment fails the request with
    ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_account_not_found
    """
    resp = api.get_subscriber_account(
        "00000000-0000-0000-0000-000000000000", platform_admin_headers
    )
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_maturity_gate_rank_equality_allowed(api):
    """PRD §3.3: "the system computes the effective cap — TV_PG whenever
    kids_mode is true (ignoring whatever is stored in maturity_rating_cap),
    otherwise the stored maturity_rating_cap — and allows the add if and only
    if the title's rank is at most the effective cap's rank. A title exactly at
    the cap is allowed; one rank above it is rejected with
    ERR_MATURITY_RATING_EXCEEDED (HTTP 422)."

    Design: Difficulty/boundary_precision_check/maturity_gate_rank_equality_allowed
    """
    account = register_account(email="bp2@x.com")
    hdrs = make_subscriber_headers(account["id"])
    profile = validate_success(
        api.create_service_profile(
            account["id"],
            create_service_profile_payload(service="DPLUS", kids_mode=True),
            hdrs,
        ),
        201,
    )
    bad = api.add_watchlist_item(
        profile["id"], add_watchlist_item_payload("teen-drama-1", "TV_14"), hdrs
    )
    validate_error(bad, "ERR_MATURITY_RATING_EXCEEDED", 422)
    good = api.add_watchlist_item(
        profile["id"], add_watchlist_item_payload("pg-cartoon-1", "TV_PG"), hdrs
    )
    validate_success(good, 201)
    assert get_profile(profile["id"], hdrs)["watchlist_count"] == 1


def test_maturity_gate_kids_mode_cap_is_forced_tv_pg(api):
    """PRD §3.3: "Setting kids_mode to true forces the cap to TV_PG regardless
    of any supplied value — this applies both at creation and on later
    parental-control updates, which may set maturity_rating_cap, kids_mode,
    or both."
    PRD §3.3: "allows the add if and only if the title's rank is at most the
    effective cap's rank. A title exactly at the cap is allowed; one rank above
    it is rejected with ERR_MATURITY_RATING_EXCEEDED (HTTP 422)."

    Design: Difficulty/boundary_precision_check/maturity_gate_rank_equality_allowed
    """
    account = register_account(email="bp2b@x.com")
    hdrs = make_subscriber_headers(account["id"])
    profile = validate_success(
        api.create_service_profile(
            account["id"],
            create_service_profile_payload(
                service="DPLUS", kids_mode=True, maturity_rating_cap="TV_MA"
            ),
            hdrs,
        ),
        201,
    )
    # Stored cap would allow TV_MA, but kids_mode forces the effective cap to
    # TV_PG, so a TV_14 title (one rank above TV_PG) must be rejected.
    rejected = api.add_watchlist_item(
        profile["id"], add_watchlist_item_payload("mature-1", "TV_14"), hdrs
    )
    validate_error(rejected, "ERR_MATURITY_RATING_EXCEEDED", 422)
    # A title one rank below the forced cap is inside it.
    accepted = api.add_watchlist_item(
        profile["id"], add_watchlist_item_payload("kids-1", "TV_G"), hdrs
    )
    validate_success(accepted, 201)


def test_maturity_gate_precision_at_every_rank(api):
    """PRD §3.3: "The watchlist gate ranks maturity on a five-step ladder: TV_Y
    is rank 0, TV_G is rank 1, TV_PG is rank 2, TV_14 is rank 3, and TV_MA is
    rank 4."
    PRD §3.3: "allows the add if and only if the title's rank is at most the
    effective cap's rank. A title exactly at the cap is allowed; one rank above
    it is rejected with ERR_MATURITY_RATING_EXCEEDED (HTTP 422)."

    Design: Corner/calculations/maturity_gate_precision_at_every_rank
    """
    account = register_account(email="calc4@x.com")
    hdrs = make_subscriber_headers(account["id"])
    profile = validate_success(
        api.create_service_profile(
            account["id"],
            create_service_profile_payload(service="DPLUS", maturity_rating_cap="TV_14"),
            hdrs,
        ),
        201,
    )
    rejected = api.add_watchlist_item(
        profile["id"], add_watchlist_item_payload("ma-title", "TV_MA"), hdrs
    )
    validate_error(rejected, "ERR_MATURITY_RATING_EXCEEDED", 422)
    accepted = api.add_watchlist_item(
        profile["id"], add_watchlist_item_payload("tv14-title", "TV_14"), hdrs
    )
    validate_success(accepted, 201)
    assert get_profile(profile["id"], hdrs)["watchlist_count"] == 1


def test_duplicate_watchlist_item_rejected(api):
    """PRD §3.3: "The same title_id may appear only once per profile — a repeat
    add fails with ERR_DUPLICATE_WATCHLIST_ITEM (HTTP 409)."

    Design: Corner/validations/duplicate_watchlist_item_rejected
    """
    account = register_account(email="val5@x.com")
    hdrs = make_subscriber_headers(account["id"])
    profile = validate_success(
        api.create_service_profile(
            account["id"], create_service_profile_payload(service="DPLUS"), hdrs
        ),
        201,
    )
    validate_success(
        api.add_watchlist_item(
            profile["id"], add_watchlist_item_payload("t1", "TV_G"), hdrs
        ),
        201,
    )
    resp = api.add_watchlist_item(
        profile["id"], add_watchlist_item_payload("t1", "TV_G"), hdrs
    )
    validate_error(resp, "ERR_DUPLICATE_WATCHLIST_ITEM", 409)


def test_duplicate_profile_per_service_rejected(api):
    """PRD §3.3: "at most one profile per (account, service) pair may exist in
    any status other than UNLINKED, and a second attempt fails with
    ERR_DUPLICATE_PROFILE (HTTP 409)."

    Design: Corner/validations/duplicate_profile_per_service_rejected
    """
    account = register_account(email="val6@x.com")
    hdrs = make_subscriber_headers(account["id"])
    validate_success(
        api.create_service_profile(
            account["id"], create_service_profile_payload(service="DPLUS"), hdrs
        ),
        201,
    )
    dup = api.create_service_profile(
        account["id"], create_service_profile_payload(service="DPLUS"), hdrs
    )
    validate_error(dup, "ERR_DUPLICATE_PROFILE", 409)
    hulu = api.create_service_profile(
        account["id"], create_service_profile_payload(service="HULU"), hdrs
    )
    validate_success(hulu, 201)
