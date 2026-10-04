"""Difficulty queue A: cyclic / parallel state machines and transitive cascades."""
import pytest

from test_helpers import (
    create_account,
    create_active_contract,
    create_listing,
    create_monitor,
    create_published_listing,
    create_share,
    create_warehouse,
    current_version,
    eng_headers,
    get_account,
    get_contract,
    get_listing,
    get_monitor,
    get_warehouse,
    open_session,
    close_session,
    post_drawdown,
    post_paid_usage,
    publish_listing,
    publish_share,
    renew_contract,
    resume_warehouse,
    revoke_share,
    scale_warehouse,
    set_clock,
    settle_paid_usage,
    shift_clock,
    suspend_warehouse,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6
DOLLAR_TOL = 0.005


# ---------------------------------------------------------------------------
# non_linear_state_machine / warehouse_parallel_status_and_cluster_dimensions
# ---------------------------------------------------------------------------

def test_cluster_count_moves_while_status_stays_running(api):
    """PRD §2.6: "The two axes are not derivable from one another:
    `cluster_count` moves freely between `clusters_min` and `clusters_max`
    while `status` remains `RUNNING`." PRD §2.6: "A warehouse therefore reports
    both fields separately, and the parallel dimensions are never collapsed
    into one."

    Design: Difficulty/non_linear_state_machine/warehouse_parallel_status_and_cluster_dimensions
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(
        account["id"], "WH_PA", "LARGE", auto_suspend_seconds=3600, auto_resume=True,
        clusters_min=1, clusters_max=3, latency_slo_ms=1000,
    )
    resumed = resume_warehouse(warehouse["id"])
    assert resumed["status"] == "RUNNING"

    up = scale_warehouse(warehouse["id"], clusters=3, queued_queries=24)
    assert up["cluster_count"] == 3
    assert up["status"] == "RUNNING"

    down = scale_warehouse(warehouse["id"], clusters=1, queued_queries=0)
    assert down["cluster_count"] == 1
    assert down["status"] == "RUNNING", (
        "scaling moves the parallel cluster dimension without touching the "
        "lifecycle dimension"
    )


def test_reaching_running_resets_the_cluster_dimension_to_its_lower_bound(api):
    """PRD §2.6: "A new warehouse is created in `SUSPENDED` with a
    `cluster_count` of 0. Reaching `RUNNING` always resets `cluster_count` to
    `clusters_min`, both on a deliberate resume and on the auto-resume path that
    a query takes against a suspended warehouse. Going to `SUSPENDED`, whether
    deliberately or by idle timeout, always sets `cluster_count` to 0."

    Design: Difficulty/non_linear_state_machine/warehouse_parallel_status_and_cluster_dimensions
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(
        account["id"], "WH_PA", "LARGE", auto_suspend_seconds=3600, auto_resume=True,
        clusters_min=2, clusters_max=3, latency_slo_ms=1000,
    )
    assert warehouse["status"] == "SUSPENDED"
    assert warehouse["cluster_count"] == 0

    resumed = resume_warehouse(warehouse["id"])
    assert resumed["cluster_count"] == 2, "reaching RUNNING resets to clusters_min"

    scaled = scale_warehouse(warehouse["id"], clusters=3, queued_queries=24)
    assert scaled["cluster_count"] == 3

    idle = scale_warehouse(warehouse["id"], clusters=1, queued_queries=0)
    assert idle["cluster_count"] == 2, "the min floor re-applies on the way down"

    suspended = suspend_warehouse(warehouse["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["cluster_count"] == 0


# ---------------------------------------------------------------------------
# non_linear_state_machine / contract_term_cycle_renewal_rounds
# ---------------------------------------------------------------------------

def _published_usage_based_listing():
    provider = create_account(tenant_name="Provider CW", region="us-east-1")
    consumer = create_account(tenant_name="Consumer CW", region="us-east-1")
    share = create_share(provider["id"], "SHARE_CW", [consumer["id"]],
                         objects_exposed=5)
    publish_share(share["id"], provider["id"])
    listing = create_listing(share["id"], provider["id"], "LIST_CW",
                             pricing_model="USAGE_BASED", flat_price_usd=0.50)
    publish_listing(listing["id"], provider["id"])
    return provider, consumer, share, listing


def test_settling_paid_usage_freezes_the_price_on_the_first_payout(api):
    """PRD §3.7: "For a usage-based listing on its first payout, the price is
    taken from the listing's `flat_price_usd` and frozen as `frozen_price_usd`".
    PRD §3.7: "150 credits priced at 0.50 dollars each produce a gross of 75.00
    dollars; with the 15 percent commission the platform fee is 11.25 dollars
    and the provider receives 63.75 dollars."

    Design: Difficulty/transitive_cascade/commit_contract_cascade_withdraw_freezes_frozen_price
    """
    provider, consumer, share, listing = _published_usage_based_listing()
    usage = post_paid_usage(listing["id"], provider["id"], consumer["id"], 150)
    settled = settle_paid_usage(usage["id"])

    assert settled["usage_state"] == "SETTLED"
    refreshed = get_listing(listing["id"], provider["id"])
    assert refreshed["frozen_price_usd"] == pytest.approx(0.50, abs=DOLLAR_TOL)
    assert refreshed["gross_credit_volume"] == pytest.approx(75.00, abs=DOLLAR_TOL)
    assert refreshed["provider_payout_usd"] == pytest.approx(63.75, abs=DOLLAR_TOL)
    assert refreshed["platform_fee_usd"] == pytest.approx(11.25, abs=DOLLAR_TOL)


def test_share_revocation_cascades_into_listing_withdrawal_keeping_the_freeze(api):
    """PRD §3.6: "It returns the share to `DRAFT`, resets `consumer_query_count`
    and `consumer_credits` both to 0, and cascades: every `Listing` bound to this
    share that is still `PUBLISHED` moves to `WITHDRAWN`, and that listing
    transition is what freezes `provider_payout_usd` and `platform_fee_usd`."

    Design: Difficulty/transitive_cascade/commit_contract_cascade_withdraw_freezes_frozen_price
    """
    provider, consumer, share, listing = _published_usage_based_listing()
    usage = post_paid_usage(listing["id"], provider["id"], consumer["id"], 150)
    settle_paid_usage(usage["id"])

    revoked = revoke_share(share["id"], provider["id"])
    assert revoked["status"] == "DRAFT"

    after = get_listing(listing["id"], provider["id"])
    assert after["listing_state"] == "WITHDRAWN"
    assert after["frozen_price_usd"] == pytest.approx(0.50, abs=DOLLAR_TOL)
    assert after["provider_payout_usd"] == pytest.approx(63.75, abs=DOLLAR_TOL), (
        "the withdrawal freezes the earnings rather than reversing them"
    )
    assert after["platform_fee_usd"] == pytest.approx(11.25, abs=DOLLAR_TOL)