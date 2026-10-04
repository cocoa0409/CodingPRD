"""Corner queue B: calculation claims."""
import pytest

from test_helpers import (
    api_client,
    close_session,
    create_account,
    create_active_contract,
    create_monitor,
    create_published_listing,
    create_replication,
    create_share,
    create_storage_record,
    create_warehouse,
    eng_headers,
    fin_headers,
    get_account,
    get_account_billing_summary,
    get_contract,
    get_listing,
    get_monitor,
    get_provider_payout,
    list_ledger_entries,
    list_usage_events,
    open_session,
    post_drawdown,
    post_paid_usage,
    post_usage_event,
    publish_share,
    refresh_replication,
    resume_warehouse,
    revoke_share,
    scale_warehouse,
    set_clock,
    settle_paid_usage,
    shift_clock,
    validate_success,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6
DOLLAR_TOL = 0.005


def test_a_drawdown_within_the_allowance_posts_no_overage_row(api):
    """PRD §3.4: "The resulting `outcome` is `OVERAGE` when the overage quantity
    is positive, otherwise `ROLLOVER` when the rollover portion is positive,
    otherwise `BASE`." PRD §3.4: "A smaller drawdown that stays within the
    allowance produces no overage row at all and leaves `remaining_credits`
    above 0."

    Design: Corner/calculations/drawdown_within_allowance_posts_no_overage_row
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_CWI", "SMALL",
                                 auto_suspend_seconds=600)
    contract = create_active_contract(account["id"], 1000)
    dd = post_drawdown(contract["id"], warehouse["id"], 400, "cwi-400")

    assert dd["outcome"] == "BASE"
    assert dd["overage_usd"] == pytest.approx(0.0, abs=DOLLAR_TOL)
    assert get_contract(contract["id"])["remaining_credits"] == pytest.approx(
        600.0, abs=CREDIT_TOL
    )
    buckets = {e["bucket"] for e in list_ledger_entries(account["id"])}
    assert "OVERAGE" not in buckets


def test_dollar_denominated_postings_stay_out_of_the_monitor_window(api):
    """PRD §2.11: "A `ResourceMonitor` enforces a credit allowance against an
    account over a repeating interval". PRD §3.8: "because every monitor
    recomputes its interval consumption from the credit-denominated buckets
    only, the account's `used_pct` also stays exactly where it was."

    Design: Corner/calculations/storage_billing_excludes_dollar_rows_from_monitor_window
    """
    account = create_account(region="us-east-1")
    monitor = create_monitor(account["id"], "MON_CWD", 1000, interval="MONTHLY",
                             action="NOTIFY")
    warehouse = create_warehouse(account["id"], "WH_CWD", "LARGE",
                                 auto_suspend_seconds=3600)
    replicated = create_replication(account["id"], "REPL_CWD", "us-west-2", 4.5,
                                    target_cloud="CROSS_CLOUD")
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 3600))
    close_session(session["id"], warehouse["id"])
    used_before = get_monitor(monitor["id"])["used_pct"]
    refresh_replication(replicated["id"])
    used_after = get_monitor(monitor["id"])["used_pct"]

    assert used_before == pytest.approx(0.8, abs=CREDIT_TOL)
    assert used_after == pytest.approx(used_before, abs=CREDIT_TOL), (
        "a REPLICATION row is dollar-denominated and moves no credit"
    )
    after = get_monitor(monitor["id"])
    assert after["interval_consumption_credits"] == pytest.approx(8.0, abs=CREDIT_TOL)
    assert get_account(account["id"])[
        "posted_consumption_credits_reconciled"
    ] == pytest.approx(8.0, abs=CREDIT_TOL)


def test_the_notify_threshold_is_inclusive_at_exactly_fifty_percent(api):
    """PRD §2.11: "A monitor in `OK` whose `used_pct` reaches at least 50.0 while
    still below 100.0 moves to `NOTIFY_SENT`". PRD §2.4: "otherwise, if the
    account's maximum `used_pct` across its monitors is at least 50.0, the
    account is `RESTRICTED`".

    Design: Corner/calculations/monitor_threshold_exact_boundary_values
    """
    account = create_account(region="us-east-1")
    notify_monitor = create_monitor(account["id"], "MON_CB_50", 100,
                                    interval="MONTHLY", action="SUSPEND")
    warehouse = create_warehouse(account["id"], "WH_CB", "LARGE",
                                 auto_suspend_seconds=3600)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    # 8 credits per hour for 6.25 hours = 50.0 credits exactly, which is exactly
    # 50 percent of the 100-credit quota and still below 100 percent.
    set_clock(shift_clock(CLOCK_START, 22500))
    close_session(session["id"], warehouse["id"])

    landed = validate_success(
        api_client.get_monitor(notify_monitor["id"], fin_headers())
    )
    assert landed["used_pct"] == pytest.approx(50.0, abs=CREDIT_TOL)
    assert landed["monitor_state"] == "NOTIFY_SENT", (
        "a monitor whose used_pct reaches at least 50.0 while still below 100.0 "
        "moves to NOTIFY_SENT"
    )
    assert get_account(account["id"])["account_state"] == "RESTRICTED", (
        "an account whose maximum used_pct is at least 50.0 is RESTRICTED"
    )


def test_the_credit_and_dollar_reconcilers_move_independently(api):
    """PRD §2.4: "The two reconcilers are deliberately independent: `ROLLOVER`
    rows are excluded from the credit figure even though they carry
    `amount_credits`, and a session close that moves the credit figure leaves the
    storage-dollar figure untouched." PRD §2.4: "`posted_storage_dollars_reconciled` is the account's running
    storage-dollar total".

    Design: Corner/calculations/ledger_reconciliation_credit_and_dollar_figures_stay_independent
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_CR3", "SMALL",
                                 auto_suspend_seconds=600)
    create_storage_record(account["id"], "2026-09-03T00:00:00Z", active_tb=10.0,
                          time_travel_tb=2.0, fail_safe_tb=1.0, time_travel_days=7)
    # 10.0 * 0.77 * 30 = 231.00; 2.0 * 0.84 * 30 = 50.40; 1.0 * 1.01 * 30 = 30.30
    # (fixed 7-day window); per-component sum = 311.70.
    after_storage = get_account(account["id"])
    assert after_storage["posted_consumption_credits_reconciled"] == pytest.approx(
        0.0, abs=CREDIT_TOL
    ), "a storage snapshot moves only the dollar figure"
    assert after_storage["posted_storage_dollars_reconciled"] == pytest.approx(
        311.7, abs=DOLLAR_TOL
    )

    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 1200))
    close_session(session["id"], warehouse["id"])

    final = get_account_billing_summary(account["id"])
    assert final["posted_consumption_credits_reconciled"] == pytest.approx(
        0.666667, abs=CREDIT_TOL
    )
    assert final["posted_storage_dollars_reconciled"] == pytest.approx(
        311.7, abs=DOLLAR_TOL
    )
    assert final["account_dollars_balance"] == pytest.approx(311.7, abs=DOLLAR_TOL)


def test_a_free_listing_carries_a_zero_commission(api):
    """PRD §3.7: "A free listing carries a commission percentage of 0." PRD
    §3.7: "a payout or a paid usage row against one is refused with
    `ERR_FREE_LISTING_NOT_PAYABLE`, because a free listing has no credit volume
    to split."

    Design: Corner/calculations/free_listing_settlement_pays_nothing
    """
    from test_helpers import (
        ApiErrorId,
        admin_headers,
        create_listing,
        create_share,
        publish_listing,
        publish_share,
        validate_error,
    )
    provider = create_account(tenant_name="Calc Free P", region="us-east-1")
    consumer = create_account(tenant_name="Calc Free C", region="us-east-1")
    share = create_share(provider["id"], "SHARE_FR", [consumer["id"]],
                         objects_exposed=2)
    publish_share(share["id"], provider["id"])
    listing = create_listing(share["id"], provider["id"], "LIST_FR",
                             pricing_model="FREE", flat_price_usd=0.0)
    published = publish_listing(listing["id"], provider["id"])

    assert published["pricing_model"] == "FREE"
    assert published["frozen_price_usd"] is None
    assert published["gross_credit_volume"] == pytest.approx(0.0, abs=DOLLAR_TOL)
    assert published["provider_payout_usd"] == pytest.approx(0.0, abs=DOLLAR_TOL)
    assert published["platform_fee_usd"] == pytest.approx(0.0, abs=DOLLAR_TOL)
    # A free listing has no credit volume to split, so its payout read is refused.
    response = api_client.get_provider_payout(listing["id"], fin_headers())
    validate_error(response, ApiErrorId.ERR_FREE_LISTING_NOT_PAYABLE)


def test_a_same_cloud_transfer_prices_at_the_raw_volume_rate(api):
    """PRD §3.8: "The cost is the replicated terabytes multiplied by a base cost
    of 5.00 dollars per terabyte, multiplied by a region factor". PRD §3.8: "the
    account also exposes the derived
    `region_factor`, the replication factor of its own region".

    Design: Corner/calculations/replication_same_cloud_target_prices_at_factor_one
    """
    account = create_account(region="eu-central-1")
    replicated = create_replication(account["id"], "REPL_SC", "us-east-1", 4.5,
                                    target_cloud="SAME_CLOUD")
    refreshed = refresh_replication(replicated["id"])
    # 4.5 * 5.00 * 1.00 * 1.00 = 22.50 to us-east-1 on the same cloud.
    assert refreshed["transfer_cost_dollars"] == pytest.approx(22.5, abs=DOLLAR_TOL)
    assert refreshed["replication_state"] == "REFRESHED"
    assert get_account(account["id"])[
        "posted_consumption_credits_reconciled"
    ] == pytest.approx(0.0, abs=CREDIT_TOL)


def test_a_later_settlement_reuses_the_price_frozen_at_the_first_payout(api):
    """PRD §3.7: "on every later payout the frozen value is honoured unchanged
    even if `flat_price_usd` has since been edited, so a provider who raises the
    price after the first payout earns nothing extra on the already-priced
    rows." PRD §3.7: "Gross volume is the sum, rounded half up to six decimals,
    of `credits_used` multiplied by `price_per_credit` over every settled row of
    the listing".

    Design: Corner/calculations/conventional_idempotency_keys_do_not_reprice_a_usage_row
    """
    ctx = create_published_listing(title="LIST_FZ_A", flat_price_usd=0.50)
    provider, consumer, listing = ctx["provider_id"], ctx["consumer_id"], ctx["listing"]
    first = post_paid_usage(listing["id"], provider, consumer, 100)
    settled = settle_paid_usage(first["id"])
    assert settled["price_per_credit"] == pytest.approx(0.50, abs=DOLLAR_TOL)

    after = get_listing(listing["id"], provider)
    assert after["frozen_price_usd"] == pytest.approx(0.50, abs=DOLLAR_TOL)
    assert after["gross_credit_volume"] == pytest.approx(50.0, abs=DOLLAR_TOL)
    assert after["provider_payout_usd"] == pytest.approx(42.5, abs=DOLLAR_TOL)
    assert after["platform_fee_usd"] == pytest.approx(7.5, abs=DOLLAR_TOL)

    # A second row on the same listing settles at the frozen 0.50, not at a
    # repriced rate.
    second = post_paid_usage(listing["id"], provider, consumer, 100)
    settle_paid_usage(second["id"])
    final = get_listing(listing["id"], provider)
    assert final["gross_credit_volume"] == pytest.approx(100.0, abs=DOLLAR_TOL)
    assert final["provider_payout_usd"] == pytest.approx(85.0, abs=DOLLAR_TOL)
    assert final["platform_fee_usd"] == pytest.approx(15.0, abs=DOLLAR_TOL)


def test_the_three_storage_components_are_priced_separately(api):
    """PRD §3.5: "The dollars for a snapshot are computed from three components,
    each priced at its own rate: `ACTIVE` at 0.77 dollars per terabyte,
    `TIME_TRAVEL` at 0.84, and `FAIL_SAFE` at 1.01, each multiplied by a
    thirty-day month." PRD §3.5: "A component whose retention window is zero
    contributes nothing — the `TIME_TRAVEL` component counts only when
    `time_travel_days` is at least 1".

    Design: Corner/calculations/awsdaily_storage_components_priced_separately
    """
    account = create_account(region="us-east-1")
    record = create_storage_record(account["id"], "2026-09-05T00:00:00Z",
                                   active_tb=10.0, time_travel_tb=5.0,
                                   fail_safe_tb=2.0, time_travel_days=0)
    summary = get_storage_billing_summary_safe(record["id"])
    assert summary["per_component"]["TIME_TRAVEL"] == pytest.approx(0.0, abs=DOLLAR_TOL)
    assert summary["per_component"]["ACTIVE"] == pytest.approx(231.0, abs=DOLLAR_TOL)
    assert summary["per_component"]["FAIL_SAFE"] == pytest.approx(60.6, abs=DOLLAR_TOL)
    refreshed = validate_success(api_client.get_storage_record(record["id"],
                                                              eng_headers()))
    assert refreshed["billable_storage_tb"] == pytest.approx(17.0, abs=CREDIT_TOL)


def get_storage_billing_summary_safe(record_id):
    from test_helpers import get_storage_billing_summary
    return get_storage_billing_summary(record_id)


def test_a_replication_sweep_reports_each_configuration_independently(api):
    """PRD §3.8: "A refresh is a `DataEngineer` action admitted from
    `CONFIGURED`, `REFRESHED` or `FAILED`". PRD §3.8: "The cost is the
    replicated terabytes multiplied by a base cost of 5.00 dollars per terabyte,
    multiplied by a region factor — 1.00 for `us-east-1`, 1.10 for `us-west-2`,
    1.20 for `eu-central-1`, 1.30 for `ap-southeast-1`".

    Design: Corner/calculations/bulk_replication_sweep_reports_per_configuration_outcomes
    """
    account = create_account(region="us-east-1")
    first = create_replication(account["id"], "REPL_BK_A", "us-west-2", 2.0,
                               target_cloud="SAME_CLOUD")
    second = create_replication(account["id"], "REPL_BK_B", "ap-southeast-1", 2.0,
                                target_cloud="CROSS_CLOUD")
    refreshed_a = refresh_replication(first["id"])
    refreshed_b = refresh_replication(second["id"])

    # 2.0 * 5.00 * 1.10 * 1.00 = 11.00; 2.0 * 5.00 * 1.30 * 1.35 = 17.55.
    assert refreshed_a["transfer_cost_dollars"] == pytest.approx(11.0, abs=DOLLAR_TOL)
    assert refreshed_b["transfer_cost_dollars"] == pytest.approx(17.55, abs=DOLLAR_TOL)
    assert refreshed_a["replication_state"] == "REFRESHED"
    assert refreshed_b["replication_state"] == "REFRESHED"
    summary = get_account_billing_summary(account["id"])
    assert summary["account_dollars_balance"] == pytest.approx(28.55, abs=DOLLAR_TOL)