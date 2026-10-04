"""Corner queue B: cross-cutting complexity layers and the consistency model."""
import pytest

from test_helpers import (
    ApiErrorId,
    admin_headers,
    api_client,
    create_account,
    create_active_contract,
    create_listing,
    create_monitor,
    create_published_listing,
    create_published_share,
    create_replication,
    create_share,
    create_storage_record,
    create_warehouse,
    current_version,
    eng_headers,
    fin_headers,
    get_account,
    get_contract,
    get_listing,
    get_monitor,
    get_warehouse,
    list_ledger_entries,
    open_session,
    patch_warehouse,
    post_drawdown,
    post_paid_usage,
    publish_listing,
    publish_share,
    refresh_replication,
    resume_warehouse,
    scale_warehouse,
    set_clock,
    settle_paid_usage,
    shift_clock,
    validate_error,
    validate_paginated,
    validate_success,
    NON_EXISTENT_UUID,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6
DOLLAR_TOL = 0.005


def test_a_stale_warehouse_version_is_refused_on_session_close(api):
    """PRD §2.8: "Closing a metered session requires
    `expected_warehouse_version`, compared against the current `version` of the
    `VirtualWarehouse` that served the session." PRD §2.8: "When the value does
    not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) before
    the write is applied."

    Design: Corner/cross_cutting_complexity_layers/stale_warehouse_version_on_session_close
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_OCR", "SMALL",
                                 auto_suspend_seconds=600)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    stale_version = current_version(warehouse["id"])
    patch_warehouse(warehouse["id"], {"size": "MEDIUM"})

    response = api_client.close_session(
        session["id"], {"expected_warehouse_version": stale_version}, eng_headers()
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)


def test_re_reading_the_version_after_the_resize_closes_the_session(api):
    """PRD §2.8: "a warehouse's version advances legitimately through a resize, a
    cluster-scaling call, a suspend sweep, or a sibling session closing against
    it, and a contract's version advances through a drawdown, a rollover booking
    or a renewal".

    Design: Corner/cross_cutting_complexity_layers/stale_warehouse_version_on_session_close
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_OCR", "SMALL",
                                 auto_suspend_seconds=600)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    patch_warehouse(warehouse["id"], {"size": "MEDIUM"})

    from test_helpers import close_session
    closed = close_session(session["id"], warehouse["id"],
                           expected_warehouse_version=current_version(warehouse["id"]))
    assert closed["state"] == "CLOSED"


def test_a_stale_contract_version_is_refused_on_a_second_drawdown(api):
    """PRD §2.8: "Posting a credit drawdown requires `expected_contract_version`,
    compared against the current `version` of the `CapacityContract` being drawn
    down." PRD §3.4: "`expected_contract_version` must equal the contract's
    current `version` or the posting is refused as stale."

    Design: Corner/cross_cutting_complexity_layers/stale_contract_version_on_drawdown
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_OCC", "SMALL")
    contract = create_active_contract(account["id"], 1000)
    stale_version = contract["version"]
    post_drawdown(contract["id"], warehouse["id"], 100, "occ-100",
                  expected_contract_version=stale_version)

    response = api_client.create_drawdown(
        {"contract_id": contract["id"], "warehouse_id": warehouse["id"],
         "amount_credits": 100, "source_kind": "SESSION",
         "idempotency_key": "occ-200",
         "expected_contract_version": stale_version},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    after = get_contract(contract["id"])
    assert after["drawn_credits"] == pytest.approx(100.0, abs=CREDIT_TOL)
    assert after["drawdown_count"] == 1


def test_a_stale_listing_version_is_refused_on_paid_usage(api):
    """PRD §2.8: "Recording paid share usage requires `expected_listing_version`,
    compared against the current `version` of the `Listing` being queried."

    Design: Corner/cross_cutting_complexity_layers/stale_listing_version_on_paid_usage
    """
    ctx = create_published_listing(title="LIST_OL", flat_price_usd=0.50)
    provider, consumer, listing = ctx["provider_id"], ctx["consumer_id"], ctx["listing"]
    stale_version = get_listing(listing["id"], provider)["version"]
    usage = post_paid_usage(listing["id"], provider, consumer, 50,
                            expected_listing_version=stale_version)
    settle_paid_usage(usage["id"])

    response = api_client.create_paid_usage(
        {"listing_id": listing["id"], "buyer_account_id": consumer,
         "credits_used": 50, "expected_listing_version": stale_version},
        admin_headers(provider),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    assert get_listing(listing["id"], provider)["frozen_price_usd"] == pytest.approx(
        0.50, abs=DOLLAR_TOL
    )


def test_a_stale_storage_snapshot_version_is_refused_on_revise(api):
    """PRD §2.8: "Revising a storage snapshot requires
    `expected_storage_usage_record_version`, compared against the current
    `version` of the `StorageUsageRecord` being revised."

    Design: Corner/cross_cutting_complexity_layers/stale_storage_snapshot_version_on_revise
    """
    account = create_account(region="us-east-1")
    record = create_storage_record(account["id"], "2026-09-10T00:00:00Z",
                                   active_tb=5.0, time_travel_tb=1.0,
                                   fail_safe_tb=1.0, time_travel_days=7)
    stale_version = record["version"]
    api_client.revise_storage_record(
        record["id"],
        {"active_tb": 6.0, "time_travel_tb": 1.0, "fail_safe_tb": 1.0,
         "time_travel_days": 7,
         "expected_storage_usage_record_version": stale_version},
        eng_headers(),
    )
    # PRD §3.5: revision is "admitted only from `FINALIZED`". Re-finalizing a
    # REVISED snapshot returns it to FINALIZED, so the version can advance
    # ahead of the one the client still holds.
    from test_helpers import finalize_storage_record
    finalize_storage_record(record["id"])

    response = api_client.revise_storage_record(
        record["id"],
        {"active_tb": 7.0, "time_travel_tb": 1.0, "fail_safe_tb": 1.0,
         "time_travel_days": 7,
         "expected_storage_usage_record_version": stale_version},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    from test_helpers import get_storage_record
    assert get_storage_record(record["id"])["active_tb"] == pytest.approx(6.0)


def test_replaying_an_idempotency_key_returns_the_first_drawdown(api):
    """PRD §3.4: "The `idempotency_key` is unique within the contract — a second
    posting with a key already used on that contract returns the first drawdown
    unchanged rather than drawing again, and a repeated key is reported as a
    duplicate resource."

    Design: Corner/cross_cutting_complexity_layers/idempotent_drawdown_replay_returns_the_first_row
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_IDM", "SMALL")
    contract = create_active_contract(account["id"], 1000)
    first = post_drawdown(contract["id"], warehouse["id"], 250, "idem-k1")

    replay = api_client.create_drawdown(
        {"contract_id": contract["id"], "warehouse_id": warehouse["id"],
         "amount_credits": 250, "source_kind": "SESSION",
         "idempotency_key": "idem-k1",
         "expected_contract_version": get_contract(contract["id"])["version"]},
        eng_headers(),
    )
    # PRD §3.4: "a second posting with a key already used on that contract
    # returns the first drawdown unchanged rather than drawing again". The
    # replay creates no new row, so it is served from the first one.
    assert replay.status_code in (200, 201), (
        f"a replayed key returns the first drawdown, got {replay.status_code}: "
        f"{replay.text}"
    )
    data = validate_success(replay, replay.status_code)
    assert data["id"] == first["id"]
    after = get_contract(contract["id"])
    assert after["drawn_credits"] == pytest.approx(250.0, abs=CREDIT_TOL)
    assert after["drawdown_count"] == 1


def test_a_different_key_with_the_same_amount_draws_again(api):
    """PRD §3.4: "`amount_credits` is strictly positive and at most 1000 credits
    for a single drawdown".

    Design: Corner/cross_cutting_complexity_layers/idempotent_drawdown_replay_returns_the_first_row
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_IDM", "SMALL")
    contract = create_active_contract(account["id"], 1000)
    post_drawdown(contract["id"], warehouse["id"], 250, "idem-k1")
    post_drawdown(contract["id"], warehouse["id"], 250, "idem-k2")
    after = get_contract(contract["id"])
    assert after["drawn_credits"] == pytest.approx(500.0, abs=CREDIT_TOL)
    assert after["drawdown_count"] == 2


def test_a_sweep_of_scaling_calls_is_best_effort_per_resource(api):
    """PRD §3.2: "it lands on a warehouse whose `status` is `RUNNING` or
    `RESIZING`; any other lifecycle state rejects the request with
    `ERR_INVALID_STATE`." PRD §2.10: "an earlier layer always wins."

    Design: Corner/cross_cutting_complexity_layers/partial_failure_in_scaling_sweep_is_per_resource
    """
    account = create_account(region="us-east-1")
    running = create_warehouse(account["id"], "WH_BS_RUN", "LARGE",
                               clusters_min=1, clusters_max=4)
    suspended = create_warehouse(account["id"], "WH_BS_OFF", "LARGE",
                                 clusters_min=1, clusters_max=4)
    resume_warehouse(running["id"])

    scaled = scale_warehouse(running["id"], clusters=4, queued_queries=32)
    assert scaled["cluster_count"] == 4

    response = api_client.scale_warehouse(
        suspended["id"],
        {"clusters": 4, "queued_queries": 32,
         "expected_warehouse_version": current_version(suspended["id"])},
        eng_headers(),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_warehouse(running["id"])["cluster_count"] == 4, (
        "the failure on the second warehouse did not revert the first"
    )
    from test_helpers import list_warehouses
    _, meta = validate_paginated(api_client.list_warehouses(
        eng_headers(), {"account_id": account["id"]}
    ))
    assert meta["total_count"] == 2


def test_a_replication_cost_reads_zero_before_its_first_refresh(api):
    """PRD §3.8: "A new configuration is `CONFIGURED` with a transfer cost of
    0." PRD §3.8: "Completion recomputes the transfer cost, stamps
    `last_refresh_at` from the logical clock, and posts it to the account's
    `REPLICATION` bucket with an `amount_credits` of 0."

    Design: Corner/cross_cutting_complexity_layers/replication_cost_reported_before_and_after_refresh
    """
    account = create_account(region="us-east-1")
    replicated = create_replication(account["id"], "REPL_RR", "eu-central-1", 3.0,
                                    target_cloud="SAME_CLOUD")
    assert replicated["transfer_cost_dollars"] == pytest.approx(0.0, abs=DOLLAR_TOL)
    assert replicated["refresh_count"] == 0

    refreshed = refresh_replication(replicated["id"])
    # 3.0 * 5.00 * 1.20 * 1.00 = 18.00.
    assert refreshed["transfer_cost_dollars"] == pytest.approx(18.0, abs=DOLLAR_TOL)
    assert refreshed["refresh_count"] == 1
    assert get_account(account["id"])["posted_storage_dollars_reconciled"] == \
        pytest.approx(0.0, abs=DOLLAR_TOL)


def test_the_reconciled_credit_figure_is_visible_in_the_same_request(api):
    """PRD §2.5: "`updated_at` is an ISO 8601 UTC timestamp with three fractional
    digits recording the last modification". PRD §2.4:
    "`posted_consumption_credits_reconciled` is the account's running credit
    total."

    Design: Corner/consistency_model/immediate_consistency_of_reconciled_credit_figure
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_IM", "SMALL",
                                 auto_suspend_seconds=600)
    create_active_contract(account["id"], 1000)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 1200))
    from test_helpers import close_session
    closed = close_session(session["id"], warehouse["id"])

    assert closed["billed_credits"] == pytest.approx(0.666667, abs=CREDIT_TOL)
    assert get_account(account["id"])[
        "posted_consumption_credits_reconciled"
    ] == pytest.approx(0.666667, abs=CREDIT_TOL), (
        "the read agrees with the close with no waiting"
    )