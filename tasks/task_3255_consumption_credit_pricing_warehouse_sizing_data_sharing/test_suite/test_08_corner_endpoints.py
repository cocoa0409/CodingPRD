"""Corner queue B: endpoint-level claims."""
import pytest

from test_helpers import (
    admin_headers,
    api_client,
    create_account,
    create_active_contract,
    create_contract,
    create_listing,
    create_monitor,
    create_published_listing,
    create_published_share,
    create_replication,
    create_share,
    create_storage_record,
    create_usage_event_payload,
    create_warehouse,
    current_version,
    eng_headers,
    fin_headers,
    get_account_billing_summary,
    get_contract,
    get_listing,
    get_provider_payout,
    list_ledger_entries,
    list_usage_events,
    open_session,
    post_drawdown,
    post_paid_usage,
    post_usage_event,
    publish_listing,
    publish_share,
    refresh_replication,
    resume_warehouse,
    set_clock,
    settle_paid_usage,
    shift_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-09-01T00:00:00Z"
CREDIT_TOL = 1e-6
DOLLAR_TOL = 0.005


def close_session_h(session_id, warehouse_id):
    from test_helpers import close_session
    return close_session(session_id, warehouse_id)


def test_the_ledger_surface_filters_by_bucket_and_reports_an_empty_page(api):
    """PRD §3.9: "The account's ledger rows can be listed across every bucket,
    with filters on `bucket` and `source_entity`". PRD §2.5: "The triple of
    `source_entity`, `source_entity_id` and `bucket` is the posting's uniqueness
    key".

    Design: Corner/endpoints/ledger_entries_filter_by_bucket_and_source_entity
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_EL", "SMALL",
                                 auto_suspend_seconds=600)
    create_storage_record(account["id"], "2026-09-08T00:00:00Z", active_tb=1.0,
                          time_travel_tb=0.0, fail_safe_tb=0.0, time_travel_days=0)
    set_clock(CLOCK_START)
    resume_warehouse(warehouse["id"])
    session = open_session(warehouse["id"])
    set_clock(shift_clock(CLOCK_START, 60))
    close_session_h(session["id"], warehouse["id"])

    consumption, meta_c = validate_paginated(api_client.list_account_ledger_entries(
        account["id"], fin_headers(), {"bucket": "CONSUMPTION"}
    ))
    assert len(consumption) == 1
    assert consumption[0]["source_entity"] == "WarehouseSession"

    payout, meta_p = validate_paginated(api_client.list_account_ledger_entries(
        account["id"], fin_headers(), {"bucket": "PAYOUT"}
    ))
    assert payout == []
    assert meta_p["total_count"] == 0
    assert meta_p["has_more"] is False

    everything = list_ledger_entries(account["id"])
    assert len(everything) == 2


def test_the_cross_share_usage_list_filters_and_paginates(api):
    """PRD §3.6: "Usage events can be listed beneath a share, filtered by
    consumer, and can also be listed across all shares filtered by share,
    consumer account and attribution outcome." PRD §3.6: "The share's
    `consumer_query_count` and `consumer_credits` are recomputed across all its
    usage events, the credit total rounded half up to six decimals."

    Design: Corner/endpoints/share_usage_event_list_filters_and_pagination
    """
    provider = create_account(tenant_name="Ep Usage P", region="us-east-1")
    consumer_a = create_account(tenant_name="Ep Usage A", region="us-east-1")
    consumer_b = create_account(tenant_name="Ep Usage B", region="us-east-1")
    share = create_published_share(provider["id"],
                                   [consumer_a["id"], consumer_b["id"]],
                                   name="SHARE_EU", objects_exposed=3)
    post_usage_event(share["id"], provider["id"], consumer_a["id"],
                     credits_consumed=3.0, row_count=40)
    post_usage_event(share["id"], provider["id"], consumer_b["id"],
                     credits_consumed=7.0, row_count=10)

    page, meta = validate_paginated(api_client.list_usage_events(
        fin_headers(), {"share_id": share["id"], "limit": 1, "offset": 0}
    ))
    assert len(page) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    filtered = list_usage_events({"consumer_account_id": consumer_b["id"]})
    assert len(filtered) == 1
    assert filtered[0]["credits_consumed"] == pytest.approx(7.0, abs=CREDIT_TOL)

    from test_helpers import get_share
    after = get_share(share["id"], provider["id"])
    assert after["consumer_query_count"] == 2
    assert after["consumer_credits"] == pytest.approx(10.0, abs=CREDIT_TOL)


def test_the_provider_payout_read_reports_symmetric_split_figures(api):
    """PRD §3.7: "The provider share is deliberately derived by subtraction
    rather than rounded independently, so that `provider_payout_usd` and
    `platform_fee_usd` always sum back to `gross_credit_volume` exactly with no
    rounding remainder lost." PRD §3.7: "150 credits priced at 0.50 dollars each
    produce a gross of 75.00 dollars; with the 15 percent commission the
    platform fee is 11.25 dollars and the provider receives 63.75 dollars."

    Design: Corner/endpoints/provider_payout_read_reports_split_symmetry
    """
    ctx = create_published_listing(title="LIST_EP", flat_price_usd=0.50,
                                   credits_used=150)
    listing = ctx["listing"]
    payout = get_provider_payout(listing["id"])

    assert payout["gross_credit_volume"] == pytest.approx(75.0, abs=DOLLAR_TOL)
    assert payout["provider_payout_usd"] == pytest.approx(63.75, abs=DOLLAR_TOL)
    assert payout["platform_fee_usd"] == pytest.approx(11.25, abs=DOLLAR_TOL)
    assert payout["provider_payout_usd"] + payout["platform_fee_usd"] == pytest.approx(
        payout["gross_credit_volume"], abs=0.005
    )
    assert payout["frozen_price_usd"] == pytest.approx(0.50, abs=DOLLAR_TOL)


def test_the_scaling_action_requires_its_expected_version_field(api):
    """PRD §2.8: "Re-scaling a warehouse requires `expected_warehouse_version`,
    again compared against the warehouse's current `version`." PRD §2.8: "These
    fields are not optional and there is no unprotected variant of the five
    operations." PRD §2.10: "an absent required field or an unknown enumeration
    member raises the generic `ERR_INVALID_REQUEST` (400)."

    Design: Corner/endpoints/cluster_scaling_requires_expected_version_field
    """
    account = create_account(region="us-east-1")
    warehouse = create_warehouse(account["id"], "WH_EO", "LARGE",
                                 clusters_min=1, clusters_max=3)
    resume_warehouse(warehouse["id"])

    from test_helpers import ApiErrorId
    response = api_client.scale_warehouse(
        warehouse["id"], {"clusters": 2, "queued_queries": 16}, eng_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    from test_helpers import get_warehouse
    assert get_warehouse(warehouse["id"])["cluster_count"] == 1, (
        "the shape failure short-circuits the scaling rule"
    )