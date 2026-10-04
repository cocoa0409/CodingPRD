"""Breadth coverage for endpoint behaviours (OCC, adjustments, pagination)."""
from test_helpers import (
    api_client,
    buy_title,
    create_active_developer,
    create_buyer,
    create_released_title,
    get_success_data,
    make_developer_headers,
    read_title,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
)

OPS = TEST_USERS["platform_ops_headers"]


def test_occ_stale_version_rejected_on_adjustment():
    """PRD §2.6: "Recording a manual revenue adjustment requires the
    non-optional field `expected_title_version` carrying the caller's last
    observed `version` of the title; if the title's current `version` has
    advanced — because a refund cascade, a purchase, or an earlier adjustment
    moved its recognized revenue — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/occ_stale_version_rejected_on_adjustment
    """
    developer, title = create_released_title(base_price_usd_cents=500)
    dev_headers = make_developer_headers(developer["id"])
    observed_version = read_title(title["id"], developer)["version"]

    # An intervening purchase advances the title's version and its ledger.
    buyer = create_buyer()
    buy_title(buyer, title)

    res = api_client.adjust_title_revenue(
        title["id"],
        {"delta_usd_cents": 100, "reason": "stale write",
         "expected_title_version": observed_version},
        OPS,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    fresh_version = read_title(title["id"], developer)["version"]
    assert fresh_version != observed_version

    get_success_data(
        api_client.adjust_title_revenue(
            title["id"],
            {"delta_usd_cents": 100, "reason": "fresh write",
             "expected_title_version": fresh_version},
            OPS,
        )
    )
    final = read_title(title["id"], developer)
    assert final["lifetime_recognized_revenue_usd_cents"] == 500 + 100


def test_negative_adjustment_floor():
    """PRD §3.2: "The delta is added to the title's recognized revenue, but the
    adjustment is rejected with `ERR_NEGATIVE_REVENUE` (HTTP 422) whenever it
    would drive the title's recognized revenue below zero, and the title's tier
    is re-evaluated after the adjustment lands."

    Design: Corner/endpoints/negative_adjustment_floor
    """
    developer, title = create_released_title(base_price_usd_cents=500)
    buyer = create_buyer()
    buy_title(buyer, title)  # recognized revenue 500

    version = read_title(title["id"], developer)["version"]
    res = api_client.adjust_title_revenue(
        title["id"],
        {"delta_usd_cents": -501, "reason": "overdraw",
         "expected_title_version": version},
        OPS,
    )
    validate_error(res, ApiErrorId.ERR_NEGATIVE_REVENUE)

    unchanged = read_title(title["id"], developer)
    assert unchanged["lifetime_recognized_revenue_usd_cents"] == 500


def test_list_pagination_defaults():
    """PRD §2.3: "All list endpoints accept two optional query parameters:
    `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0).
    Results are always sorted by `created_at` ascending. The `meta` block of a
    list response carries `limit`, `offset`, `total_count`, and `has_more`,
    where `has_more` indicates whether further results exist beyond the
    returned window."

    Design: Corner/endpoints/list_pagination_defaults
    """
    developer = create_active_developer()

    data, meta = validate_paginated(
        api_client.list_titles(OPS, params={"developer_account_id": developer["id"]})
    )
    assert data == []
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
