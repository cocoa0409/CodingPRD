"""Corner queue B: error-catalog claims."""
import pytest

from test_helpers import (
    get_success_data,
    ApiErrorId,
    admin_headers,
    api_client,
    create_account,
    create_active_contract,
    create_listing,
    create_published_share,
    create_share,
    create_usage_event_payload,
    create_warehouse,
    eng_headers,
    fin_headers,
    get_account,
    get_contract,
    get_listing,
    get_monitor,
    list_drawdowns,
    post_paid_usage,
    publish_listing,
    publish_share,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6


def test_a_drawdown_above_the_single_drawdown_ceiling_is_a_range_error(api):
    """PRD §3.4: "`amount_credits` is strictly positive and at most 1000 credits
    for a single drawdown, and a value outside that band is refused with
    `ERR_DRAWDOWN_AMOUNT_RANGE`". PRD §2.10: "the single-drawdown amount bounds
    raise `ERR_DRAWDOWN_AMOUNT_RANGE` (400)".

    Design: Corner/errors/error_drawdown_amount_range_above_single_drawdown_ceiling
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_EA", "SMALL")
    contract = create_active_contract(account["id"], 1000,
                                      overage_rate_per_credit=3.00,
                                      rollover_cap_credits=200)
    response = api_client.create_drawdown(
        {"contract_id": contract["id"], "warehouse_id": warehouse["id"],
         "amount_credits": 1001, "source_kind": "SESSION",
         "idempotency_key": "ea-big",
         "expected_contract_version": get_contract(contract["id"])["version"]},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_DRAWDOWN_AMOUNT_RANGE)
    assert get_contract(contract["id"])["drawn_credits"] == pytest.approx(
        0.0, abs=CREDIT_TOL
    )


def test_a_cluster_bound_violation_on_a_patch_is_a_400_range_error(api):
    """PRD §2.10: "The thirteenth layer is field shape and range, and it is where
    the specific range codes live: the cluster-bound guards and the
    cluster-intent floor raise `ERR_CLUSTER_RANGE` (400)". PRD §3.2:
    "`clusters_max` defaults to 1, must be at least `clusters_min`, and must not
    exceed 10 — a violated cluster bound is refused with `ERR_CLUSTER_RANGE`."

    Design: Corner/errors/error_cluster_range_is_a_400_not_a_state_error
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_EC", "LARGE",
                                 clusters_min=1, clusters_max=3)
    from test_helpers import resume_warehouse, get_warehouse
    resume_warehouse(warehouse["id"])

    response = api_client.patch_warehouse(
        warehouse["id"], {"clusters_min": 5, "clusters_max": 2}, eng_headers()
    )
    validate_error(response, ApiErrorId.ERR_CLUSTER_RANGE)
    after = get_warehouse(warehouse["id"])
    assert after["clusters_min"] == 1
    assert after["clusters_max"] == 3


def test_an_auto_suspend_below_the_floor_is_its_own_range_error(api):
    """PRD §3.2: "it must be at least 60 and at most 3600 seconds, defaults to
    600, and a value outside that band is refused with
    `ERR_AUTO_SUSPEND_RANGE`."

    Design: Corner/errors/error_auto_suspend_range_below_floor
    """
    account = create_account(region="us-east-1")
    response = api_client.create_warehouse(
        {"account_id": account["id"], "name": "WH_ES2", "size": "SMALL",
         "auto_suspend_seconds": 30},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_AUTO_SUSPEND_RANGE)


def test_the_auto_suspend_band_is_inclusive_at_both_boundaries(api):
    """PRD §3.2: "it must be at least 60 and at most 3600 seconds". PRD §2.6:
    "`auto_suspend_seconds` is the idle window before the warehouse suspends
    itself and also the billed floor applied to each session".

    Design: Corner/errors/error_auto_suspend_range_below_floor
    """
    account = create_account(region="us-east-1")
    floor = create_warehouse(account["id"], "WH_LO", "SMALL",
                             auto_suspend_seconds=60)
    ceiling = create_warehouse(account["id"], "WH_HI", "SMALL",
                               auto_suspend_seconds=3600)
    assert floor["auto_suspend_seconds"] == 60
    assert ceiling["auto_suspend_seconds"] == 3600

    above = api_client.create_warehouse(
        {"account_id": account["id"], "name": "WH_XHI", "size": "SMALL",
         "auto_suspend_seconds": 3601},
        eng_headers(),
    )
    validate_error(above, ApiErrorId.ERR_AUTO_SUSPEND_RANGE)


def test_a_time_travel_window_past_ninety_days_is_a_range_error(api):
    """PRD §3.5: "`time_travel_days` must be at least 0 and at most 90, and a
    value outside that band is refused with `ERR_STORAGE_DAYS_RANGE`."

    Design: Corner/errors/error_storage_days_range_on_time_travel_window
    """
    account = create_account(region="us-east-1")
    response = api_client.create_storage_record(
        {"account_id": account["id"], "usage_date": "2026-09-09T00:00:00Z",
         "active_tb": 1.0, "time_travel_tb": 1.0, "fail_safe_tb": 1.0,
         "time_travel_days": 91},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_STORAGE_DAYS_RANGE)


def test_a_ninety_day_window_is_accepted_and_the_fail_safe_window_is_fixed(api):
    """PRD §3.5: "`fail_safe_tb` component is governed by `fail_safe_days`, which
    is fixed at 7 days and is not settable by any client — it is a system field,
    not an input."

    Design: Corner/errors/error_storage_days_range_on_time_travel_window
    """
    account = create_account(region="us-east-1")
    from test_helpers import create_storage_record
    record = create_storage_record(account["id"], "2026-09-09T00:00:00Z",
                                   active_tb=1.0, time_travel_tb=1.0,
                                   fail_safe_tb=1.0, time_travel_days=90)
    assert record["time_travel_days"] == 90
    assert record["fail_safe_days"] == 7


def test_paid_usage_against_a_draft_listing_is_refused_on_the_listing_state(api):
    """PRD §2.10: "The nineteenth layer is listing publication state on the
    paid-usage path, refused with `ERR_LISTING_NOT_PUBLISHED` (409)". PRD §3.7:
    "The listing must be `PUBLISHED` or the request is refused with
    `ERR_LISTING_NOT_PUBLISHED`".

    Design: Corner/errors/error_listing_not_published_before_withdraw
    """
    provider = create_account(tenant_name="Err Listing P", region="us-east-1")
    consumer = create_account(tenant_name="Err Listing C", region="us-east-1")
    share = create_published_share(provider["id"], [consumer["id"]],
                                   name="SHARE_EL", objects_exposed=2)
    listing = create_listing(share["id"], provider["id"], "LIST_EL",
                             pricing_model="USAGE_BASED", flat_price_usd=0.50)
    assert listing["listing_state"] == "DRAFT"

    response = api_client.create_paid_usage(
        {"listing_id": listing["id"], "buyer_account_id": consumer["id"],
         "credits_used": 10,
         "expected_listing_version": get_listing(listing["id"],
                                                 provider["id"])["version"]},
        admin_headers(provider["id"]),
    )
    validate_error(response, ApiErrorId.ERR_LISTING_NOT_PUBLISHED)
    assert get_listing(listing["id"], provider["id"])["listing_state"] == "DRAFT"


def test_publishing_the_listing_makes_the_identical_paid_usage_request_succeed(api):
    """PRD §3.7: "It moves the listing to `PUBLISHED` and leaves
    `frozen_price_usd` null until the first provider payout."

    Design: Corner/errors/error_listing_not_published_before_withdraw
    """
    provider = create_account(tenant_name="Err Listing P", region="us-east-1")
    consumer = create_account(tenant_name="Err Listing C", region="us-east-1")
    share = create_published_share(provider["id"], [consumer["id"]],
                                   name="SHARE_EL", objects_exposed=2)
    listing = create_listing(share["id"], provider["id"], "LIST_EL",
                             pricing_model="USAGE_BASED", flat_price_usd=0.50)
    published = publish_listing(listing["id"], provider["id"])
    assert published["listing_state"] == "PUBLISHED"
    assert published["frozen_price_usd"] is None

    usage = post_paid_usage(listing["id"], provider["id"], consumer["id"], 10)
    assert usage["usage_state"] == "PENDING"


def test_a_share_naming_its_own_provider_as_consumer_is_refused(api):
    """PRD §3.6: "none of them may equal `provider_account_id`: a share that
    lists its own provider as a consumer is refused with
    `ERR_SHARE_SELF_CONSUMPTION`, because self-consumption would have to be
    billed to someone and there is no correct someone."

    Design: Corner/errors/error_share_self_consumption_on_consumer_list
    """
    provider = create_account(tenant_name="Err Self", region="us-east-1")
    response = api_client.create_share(
        {"provider_account_id": provider["id"], "name": "SHARE_SS",
         "objects_exposed": 1, "consumer_account_ids": [provider["id"]]},
        admin_headers(provider["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SHARE_SELF_CONSUMPTION)
    _, meta = validate_paginated(api_client.list_shares(
        admin_headers(provider["id"]), {"provider_account_id": provider["id"]}
    ))
    assert meta["total_count"] == 0


def test_a_consumer_list_that_excludes_the_provider_is_accepted(api):
    """PRD §3.6: "Every member of `consumer_account_ids` must be the id of an
    existing account, and none of them may equal `provider_account_id`".

    Design: Corner/errors/error_share_self_consumption_on_consumer_list
    """
    provider = create_account(tenant_name="Err Self", region="us-east-1")
    consumer = create_account(tenant_name="Err Self C", region="us-east-1")
    share = validate_success(api_client.create_share(
        {"provider_account_id": provider["id"], "name": "SHARE_SS",
         "objects_exposed": 1, "consumer_account_ids": [consumer["id"]]},
        admin_headers(provider["id"]),
    ), 201)
    assert share["consumer_account_ids"] == [consumer["id"]]


def test_a_consumer_inclusive_account_without_a_published_share_cannot_resume(api):
    """PRD §3.2: "A resume on an account marking `INCLUDE_CONSUMERS` scope that
    has no monitor to drive a sweep is refused with `ERR_MONITOR_MISSING`." PRD
    §2.11: "A consumer-inclusive scope is only meaningful when the account
    actually has something to include, so a monitor reset or a warehouse resume
    on such an account is refused when the account has no monitor bound to it or
    has no published share exposing consumers."

    Design: Corner/errors/error_monitor_missing_on_include_consumers_scope
    """
    account = create_account(region="us-east-1", monitor_scope="INCLUDE_CONSUMERS")
    # A monitor is bound, but the account exposes no consumer through any
    # published share, so a consumer-scoped sweep has nothing to drive.
    create_monitor_h(account["id"], "MON_EM", 100)
    warehouse = create_warehouse(account["id"], "WH_EM", "SMALL",
                                 auto_suspend_seconds=600, auto_resume=True,
                                 clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    assert get_account(account["id"])["account_state"] == "OPEN"

    response = api_client.resume_warehouse(warehouse["id"], {}, eng_headers())
    validate_error(response, ApiErrorId.ERR_MONITOR_MISSING)


def create_monitor_h(account_id, name, quota):
    from test_helpers import create_monitor
    return create_monitor(account_id, name, quota, interval="MONTHLY",
                          action="SUSPEND")


def test_the_same_resume_on_a_bound_account_succeeds(api):
    """PRD §2.11: "Resetting a monitor is a `FinanceController` action and is the
    only way a monitor returns to `OK`. The monitor's own edge into `OK` is taken
    from `SUSPENDED`". PRD §3.2: "A resume is attempted by a `DataEngineer` or a
    `PlatformOperator` and requires the warehouse to be `SUSPENDED`".

    Design: Corner/errors/error_monitor_missing_on_include_consumers_scope
    """
    from test_helpers import create_monitor
    account = create_account(region="us-east-1", monitor_scope="ACCOUNT_ONLY")
    create_monitor(account["id"], "MON_EM", 100, interval="MONTHLY",
                   action="SUSPEND")
    warehouse = create_warehouse(account["id"], "WH_EM", "SMALL",
                                 auto_suspend_seconds=600, auto_resume=True,
                                 clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    resumed = api_client.resume_warehouse(warehouse["id"], {}, eng_headers())
    data = validate_success(resumed)
    assert data["status"] == "RUNNING"


def test_a_replayed_idempotency_key_returns_the_original_drawdown(api):
    """PRD §3.4: "The `idempotency_key` is unique within the contract — a second
    posting with a key already used on that contract returns the first drawdown
    unchanged rather than drawing again". PRD §2.10: "The twelfth layer is
    per-account uniqueness, refused with `ERR_DUPLICATE_RESOURCE` (409)."

    Design: Corner/errors/error_consumer_drawdown_ceiling_on_inactive_accounts
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_ED", "SMALL")
    contract = create_active_contract(account["id"], 1000)
    first = get_success_data(api_client.create_drawdown(
        {"contract_id": contract["id"], "warehouse_id": warehouse["id"],
         "amount_credits": 100, "source_kind": "SESSION",
         "idempotency_key": "ed-k1",
         "expected_contract_version": get_contract(contract["id"])["version"]},
        eng_headers(),
    ), 201)

    replay = api_client.create_drawdown(
        {"contract_id": contract["id"], "warehouse_id": warehouse["id"],
         "amount_credits": 100, "source_kind": "SESSION",
         "idempotency_key": "ed-k1",
         "expected_contract_version": get_contract(contract["id"])["version"]},
        eng_headers(),
    )
    assert replay.status_code in (200, 201), (
        f"a replayed key returns the first drawdown, got {replay.status_code}: "
        f"{replay.text}"
    )
    data = validate_success(replay, replay.status_code)
    assert data["id"] == first["id"]
    after = get_contract(contract["id"])
    assert after["drawn_credits"] == pytest.approx(100.0, abs=CREDIT_TOL)
    assert after["drawdown_count"] == 1
    assert len(list_drawdowns(contract["id"])) == 1