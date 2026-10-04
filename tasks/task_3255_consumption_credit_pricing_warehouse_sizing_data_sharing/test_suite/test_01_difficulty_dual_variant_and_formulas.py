"""Difficulty queue A: dual-variant and combinatorial formulas."""
import pytest

from test_helpers import (
    assert_account_credit_figure,
    close_session,
    create_account,
    create_active_contract,
    create_replication,
    create_storage_record,
    create_warehouse,
    current_version,
    get_account,
    get_contract,
    get_storage_billing_summary,
    get_warehouse,
    open_session,
    post_drawdown,
    refresh_replication,
    resume_warehouse,
    scale_warehouse,
    set_clock,
    shift_clock,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6
DOLLAR_TOL = 0.005


# ---------------------------------------------------------------------------
# dual_variant_calc / session_billing_floor_diverges_on_short_session
# ---------------------------------------------------------------------------

def _setup_short_medium_session():
    """One MEDIUM warehouse with auto_suspend_seconds 60."""
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(
        account["id"], "WH_MS", "MEDIUM", auto_suspend_seconds=60,
        auto_resume=True, clusters_min=1, clusters_max=1, latency_slo_ms=1000,
    )
    return account, warehouse


def test_billed_floor_raises_a_short_session_above_its_metered_reading(api):
    """PRD §3.3: "A `MEDIUM` session of a single cluster that ran 47 seconds
    meters 0.052222 credits, because 4 times 1 times 47 divided by 3600 rounds
    to that; the same session bills 0.066667 credits, because its duration is
    raised to 600 seconds and 4 times 1 times 600 divided by 3600 is exactly
    two-thirds of a credit." PRD §2.7: "Session credits are rounded once per
    session at close and then frozen; they are never accumulated raw and
    rounded at the end."

    Design: Difficulty/dual_variant_calc/session_billing_floor_diverges_on_short_session
    """
    account, warehouse = _setup_short_medium_session()
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 47))
    closed = close_session(session["id"], warehouse["id"],
                           expected_warehouse_version=current_version(warehouse["id"]))

    assert closed["elapsed_seconds"] == 47
    assert closed["metered_credits"] == pytest.approx(0.052222, abs=CREDIT_TOL)
    assert closed["billed_seconds"] == 60
    assert closed["billed_credits"] == pytest.approx(0.066667, abs=CREDIT_TOL)


def test_short_session_billed_and_metered_readings_disagree(api):
    """PRD §3.3: "The two readings therefore diverge exactly when a session was
    shorter than its warehouse's floor." PRD §2.7: "The billed figure is never
    below the metered figure, which follows from the floor never lowering a
    duration."

    Design: Difficulty/dual_variant_calc/session_billing_floor_diverges_on_short_session
    """
    account, warehouse = _setup_short_medium_session()
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 47))
    closed = close_session(session["id"], warehouse["id"])

    assert closed["billed_credits"] != pytest.approx(closed["metered_credits"], abs=CREDIT_TOL), (
        "a session shorter than the floor must bill a different figure from the "
        "one it meters"
    )
    assert closed["billed_credits"] >= closed["metered_credits"]
    # 4 * 1 * 60 / 3600 = 0.066667 exactly; 4 * 1 * 47 / 3600 = 0.052222...
    assert closed["billed_credits"] == pytest.approx(4 * 1 * 60 / 3600, abs=CREDIT_TOL)
    assert closed["metered_credits"] == pytest.approx(round(4 * 1 * 47 / 3600, 6),
                                                      abs=CREDIT_TOL)


# ---------------------------------------------------------------------------
# dual_variant_calc / storage_cost_rounding_order_changes_the_cents
# ---------------------------------------------------------------------------

def test_storage_snapshot_stored_cost_rounds_per_component(api):
    """PRD §3.5: "Component by component, the active component is 12.47 times
    0.77 times 30, which is 288.057 and rounds to 288.06; the time-travel
    component is 3.33 times 0.84 times 30, which is 83.916 and rounds to 83.92;
    the fail-safe component is 1.0 times 1.01 times 30, which is 30.30 exactly.
    Summed and rounded, the snapshot's stored `storage_cost_dollars` is 288.06
    plus 83.92 plus 30.30, which is 402.28, and that is the figure carried by
    the ledger."

    Design: Difficulty/dual_variant_calc/storage_cost_rounding_order_changes_the_cents
    """
    account = create_account(region="us-east-1")
    record = create_storage_record(
        account["id"], CLOCK_START, active_tb=12.47, time_travel_tb=3.33,
        fail_safe_tb=1.0, time_travel_days=30,
    )
    assert record["storage_cost_dollars"] == pytest.approx(402.28, abs=DOLLAR_TOL)


def test_storage_billing_summary_reports_sum_then_round_variant(api):
    """PRD §3.5: "The snapshot billing-summary read surface returns four report
    fields: `storage_cost_dollars_reported`, which carries the sum-then-round
    variant as the documented reporting figure; `storage_cost_dollars_stored`,
    which carries the per-component value actually written on the snapshot".
    PRD §3.5: "Rounding once over the summed raw products of the same fixture
    gives 402.27 — a one-cent divergence that exists only because of rounding
    order."

    Design: Difficulty/dual_variant_calc/storage_cost_rounding_order_changes_the_cents
    """
    account = create_account(region="us-east-1")
    record = create_storage_record(
        account["id"], CLOCK_START, active_tb=12.47, time_travel_tb=3.33,
        fail_safe_tb=1.0, time_travel_days=30,
    )
    summary = get_storage_billing_summary(record["id"])

    assert summary["storage_cost_dollars_reported"] == pytest.approx(402.27, abs=DOLLAR_TOL)
    assert summary["storage_cost_dollars_stored"] == pytest.approx(402.28, abs=DOLLAR_TOL)
    assert summary["storage_cost_dollars_reported"] != pytest.approx(
        summary["storage_cost_dollars_stored"], abs=DOLLAR_TOL
    )
    assert summary["per_component"]["ACTIVE"] == pytest.approx(288.06, abs=DOLLAR_TOL)
    assert summary["per_component"]["TIME_TRAVEL"] == pytest.approx(83.92, abs=DOLLAR_TOL)
    assert summary["per_component"]["FAIL_SAFE"] == pytest.approx(30.30, abs=DOLLAR_TOL)


# ---------------------------------------------------------------------------
# combinatorial_formula / cluster_scaling_evaluation_order_min_floor_reapplied
# ---------------------------------------------------------------------------

def test_scaling_reapplies_the_minimum_floor_after_clamping(api):
    """PRD §3.2: "The candidate is the smaller of the requested cluster count
    and the clamped demand, and the minimum floor is re-applied to the
    candidate afterwards, so a client asking for fewer clusters than the
    warehouse's configured minimum gets the minimum." PRD §3.2: "19 queued
    queries against a warehouse whose `clusters_max` is 3 therefore yields 3
    clusters." The floor re-applied here is `clusters_min`, which is what the
    sentence names as the warehouse's configured minimum.

    Design: Difficulty/combinatorial_formula/cluster_scaling_evaluation_order_min_floor_reapplied
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(
        account["id"], "WH_SO", "LARGE", auto_suspend_seconds=600, auto_resume=True,
        clusters_min=2, clusters_max=3, latency_slo_ms=1000,
    )
    create_active_contract(account["id"], 1000)
    resume_warehouse(warehouse["id"])

    scaled = scale_warehouse(warehouse["id"], clusters=1, queued_queries=19)
    assert scaled["cluster_count"] == 2, (
        "the requested cluster count 1 is below the warehouse's configured "
        "minimum 2, so the floor re-applied to the candidate raises it to 2"
    )
    assert scaled["multi_cluster_queued_queries"] == 19
    assert scaled["status"] == "RUNNING"

    # The PRD's worked calibration: 19 queued queries at 8 per cluster clamp to
    # 3. With no active contract at all the budget steps are skipped and
    # cluster_count follows demand and clamping alone.
    bare = create_account(region="us-east-1")
    open_warehouse = create_warehouse(
        bare["id"], "WH_SO_2", "LARGE", auto_suspend_seconds=600,
        auto_resume=True, clusters_min=1, clusters_max=3, latency_slo_ms=1000,
    )
    resume_warehouse(open_warehouse["id"])
    clamped = scale_warehouse(open_warehouse["id"], clusters=3, queued_queries=19)
    assert clamped["cluster_count"] == 3, (
        "19 queued queries against a warehouse whose clusters_max is 3 yields "
        "3 clusters when no active contract can shrink the candidate"
    )


def test_scaling_leaves_the_contract_and_the_credit_figure_untouched(api):
    """PRD §3.2: "the account's reconciled credit figure is deliberately left
    untouched, because scaling changes the burn rate of future sessions only
    and never re-prices work already done."

    Design: Difficulty/combinatorial_formula/cluster_scaling_evaluation_order_min_floor_reapplied
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(
        account["id"], "WH_SO", "LARGE", auto_suspend_seconds=600, auto_resume=True,
        clusters_min=1, clusters_max=3, latency_slo_ms=1000,
    )
    contract = create_active_contract(account["id"], 1000)
    resume_warehouse(warehouse["id"])

    scaled = scale_warehouse(warehouse["id"], clusters=1, queued_queries=19)
    # 3 clusters project 8 * 3 * 900 / 3600 = 6.00 credits, far below 100.00.
    assert 8 * scaled["cluster_count"] * 900 / 3600 < 100.0
    refreshed = get_contract(contract["id"])
    assert refreshed["remaining_credits"] == pytest.approx(1000.0, abs=CREDIT_TOL)
    assert refreshed["drawn_credits"] == pytest.approx(0.0, abs=CREDIT_TOL)
    assert_account_credit_figure(get_account(account["id"]), 0.0)


# ---------------------------------------------------------------------------
# combinatorial_formula / contract_overage_waterfall_segment_order
# ---------------------------------------------------------------------------

def test_waterfall_labels_a_within_allowance_drawdown_as_base(api):
    """PRD §3.4: "The base portion is the smaller of this drawdown's
    `amount_credits` and the remaining unconsumed base, which is `base_credits`
    minus `base_consumed_credits`, itself never negative." PRD §3.4: "The
    resulting `outcome` is `OVERAGE` when the overage quantity is positive,
    otherwise `ROLLOVER` when the rollover portion is positive, otherwise
    `BASE`."

    Design: Difficulty/combinatorial_formula/contract_overage_waterfall_segment_order
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_WF", "SMALL",
                                 auto_suspend_seconds=600, auto_resume=True,
                                 clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    contract = create_active_contract(account["id"], 1000)
    dd = post_drawdown(contract["id"], warehouse["id"], 1000, "wf-1000-1")

    assert dd["outcome"] == "BASE"
    assert dd["overage_usd"] == pytest.approx(0.0, abs=DOLLAR_TOL)


def test_waterfall_prices_the_over_allowance_portion_as_overage(api):
    """PRD §3.4: "a contract with `base_credits` 1000 and no rollover receiving a
    single 1200-credit drawdown has a drawdownable quantity of 1000, so its
    overage quantity is 200 credits; priced at the contract's
    `overage_rate_per_credit` — say 3.00 dollars per credit — that posts 600.00
    dollars of overage, and the contract moves to `EXHAUSTED` with
    `remaining_credits` 0."

    Design: Difficulty/combinatorial_formula/contract_overage_waterfall_segment_order
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_WF", "SMALL",
                                 auto_suspend_seconds=600, auto_resume=True,
                                 clusters_min=1, clusters_max=1, latency_slo_ms=1000)
    contract = create_active_contract(account["id"], 1000,
                                      rollover_cap_credits=200,
                                      overage_rate_per_credit=3.00)
    post_drawdown(contract["id"], warehouse["id"], 1000, "wf-1000-1")
    dd = post_drawdown(contract["id"], warehouse["id"], 200, "wf-1000-2")

    assert dd["outcome"] == "OVERAGE"
    assert dd["overage_usd"] == pytest.approx(600.00, abs=DOLLAR_TOL)
    refreshed = get_contract(contract["id"])
    assert refreshed["status"] == "EXHAUSTED"
    assert refreshed["remaining_credits"] == pytest.approx(0.0, abs=CREDIT_TOL)


# ---------------------------------------------------------------------------
# combinatorial_formula / replication_transfer_cost_four_input_product
# ---------------------------------------------------------------------------

def test_replication_price_is_the_four_input_product(api):
    """PRD §3.8: "The cost is the replicated terabytes multiplied by a base cost
    of 5.00 dollars per terabyte, multiplied by a region factor — 1.00 for
    `us-east-1`, 1.10 for `us-west-2`, 1.20 for `eu-central-1`, 1.30 for
    `ap-southeast-1` — and by a cloud factor of 1.00 for `SAME_CLOUD` or 1.35
    for `CROSS_CLOUD`, rounded half up to two decimals once, at the end". PRD
    §3.8: "4.5 terabytes to `us-west-2` across clouds costs 4.5 times 5.00
    times 1.10 times 1.35, which is 33.41 dollars."

    Design: Difficulty/combinatorial_formula/replication_transfer_cost_four_input_product
    """
    account = create_account(region="us-east-1")
    repl = create_replication(account["id"], "REPL_RC", "us-west-2", 4.5,
                              target_cloud="CROSS_CLOUD")
    refreshed = refresh_replication(repl["id"])

    assert refreshed["replication_state"] == "REFRESHED"
    assert refreshed["refresh_count"] == 1
    assert refreshed["transfer_cost_dollars"] == pytest.approx(33.41, abs=DOLLAR_TOL)


def test_replication_is_not_priced_at_the_same_cloud_rate(api):
    """PRD §3.8: "and by a cloud factor of 1.00 for `SAME_CLOUD` or 1.35 for
    `CROSS_CLOUD`, rounded half up to two decimals once, at the end, over the
    product of all four inputs." PRD §3.8: "a failed transfer adds exactly 0
    dollars and leaves the prior transfer cost in place."

    Design: Difficulty/combinatorial_formula/replication_transfer_cost_four_input_product
    """
    account = create_account(region="us-east-1")
    repl = create_replication(account["id"], "REPL_RC", "us-west-2", 4.5,
                              target_cloud="CROSS_CLOUD")
    refreshed = refresh_replication(repl["id"])

    assert refreshed["transfer_cost_dollars"] != pytest.approx(27.00, abs=DOLLAR_TOL), (
        "the cross-cloud transfer must not be priced at the same-cloud rate"
    )
    assert refreshed["replication_state"] == "REFRESHED"