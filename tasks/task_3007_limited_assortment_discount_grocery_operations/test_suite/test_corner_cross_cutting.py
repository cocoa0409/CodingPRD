"""Cross-cutting layers: optimistic concurrency, derived ledgers, filtered pagination."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    CUSTOMER_SERVICE_HEADERS,
    fixtures,
    make_store_manager_headers,
)
from test_helpers.factories import cart_coin_event_payload


def test_occ_stale_finds_buy_version_rejected(api):
    """A second re-plan against the stale captured version fails ERR_STALE_VERSION.

    PRD §2.6: "Re-planning a Finds buy's allocations requires the request to carry `expected_finds_buy_version` holding the client's last observed `version` of the buy. If the buy's current `version` has advanced since that read, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "While the buy is `ALLOCATED`, planning may run again: every existing allocation row — all still `RESERVED` — is deleted and the waterfall recreates the plan from scratch. Because a re-plan legitimately replaces the prior draft, it is OCC-guarded per §2.6: the request must carry `expected_finds_buy_version`, and a stale value is rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_layers/occ_stale_finds_buy_version_rejected
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)
    fixtures.create_store(api)
    buy = fixtures.create_finds_buy(
        api, product["id"], total_quantity=5,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    planned = fixtures.plan_allocations(api, buy)
    assert planned["status"] == "ALLOCATED"
    captured_version = planned["version"]

    # First superseding re-plan against the fresh version succeeds.
    replanned = validate_success(
        api.plan_allocations(
            buy["id"], {"expected_finds_buy_version": captured_version}, CATEGORY_MANAGER_HEADERS
        )
    )
    assert replanned["status"] == "ALLOCATED"
    assert replanned["version"] == captured_version + 1

    # Replaying the same stale version is rejected.
    stale = api.plan_allocations(
        buy["id"], {"expected_finds_buy_version": captured_version}, CATEGORY_MANAGER_HEADERS
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)


def test_occ_stale_category_version_rejected(api):
    """PATCH with a stale expected_category_version fails; the fresh one succeeds.

    PRD §2.6: "Updating a category's SKU cap requires the request to carry `expected_category_version` holding the client's last observed `version` of the category. If the category's current `version` has advanced since that read — for example because a product activation or discontinuation moved the assortment count — the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_category_version_rejected
    """
    category = fixtures.create_category(api, sku_cap=2)
    captured_version = category["version"]

    updated = validate_success(
        api.update_category(
            category["id"],
            {"sku_cap": 3, "expected_category_version": captured_version},
            CATEGORY_MANAGER_HEADERS,
        )
    )
    assert updated["sku_cap"] == 3
    assert updated["version"] == captured_version + 1

    stale = api.update_category(
        category["id"],
        {"sku_cap": 4, "expected_category_version": captured_version},
        CATEGORY_MANAGER_HEADERS,
    )
    validate_error(stale, "ERR_STALE_VERSION", 412)

    read = validate_success(api.get_category(category["id"], CATEGORY_MANAGER_HEADERS))
    assert read["sku_cap"] == 3, "the rejected PATCH must not change the cap"


def test_store_refund_ledgers_stay_reconciled(api):
    """Approve 698 + approve 349 + pay the first: liability 349, paid 698.

    PRD §3.9: "Approval immediately increases the store's `refund_liability_cents` by the computed amount."
    PRD §3.9: "Payout moves it `APPROVED → PAID`: the store's `refund_liability_cents` decreases by `refund_amount_cents` and its `refund_paid_cents` increases by the same amount — the cumulative record of refunds actually disbursed."

    Design: Corner/cross_cutting_layers/derived_field_store_ledgers_reconciled
    """
    world = fixtures.claims_world(api)
    store, product = world["store"], world["product"]

    claim_a = fixtures.claim_under_review(
        api, product["id"], store["id"],
        quantity=1, unit_price_cents=349, reason="QUALITY_DEFECT",
    )
    claim_b = fixtures.claim_under_review(
        api, product["id"], store["id"],
        quantity=1, unit_price_cents=349, reason="DAMAGED",
    )
    validate_success(api.approve_claim(claim_a["id"], CUSTOMER_SERVICE_HEADERS))
    validate_success(api.approve_claim(claim_b["id"], CUSTOMER_SERVICE_HEADERS))
    validate_success(api.pay_claim(claim_a["id"], CUSTOMER_SERVICE_HEADERS))

    read = validate_success(api.get_store(store["id"], CUSTOMER_SERVICE_HEADERS))
    assert read["refund_liability_cents"] == 349, (
        f"only claim B (349) is still APPROVED, got {read['refund_liability_cents']}"
    )
    assert read["refund_paid_cents"] == 698, (
        f"claim A paid out 349 doubled = 698, got {read['refund_paid_cents']}"
    )


def test_pagination_with_kind_filter(api):
    """kind=FINDS pages only FINDS products; total_count reflects the filtered set.

    PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD §3.2: "Products may be listed with `category_id`, `kind`, and `status` filters."

    Design: Corner/cross_cutting_layers/pagination_filter_sort_interaction
    """
    category = fixtures.create_category(api, sku_cap=5)
    fixtures.create_product(api, category["id"], sku_code="SKU-C1", kind="CORE")
    fixtures.create_product(
        api, category["id"], sku_code="SKU-F1", kind="FINDS", barcode_count=3
    )
    fixtures.create_product(
        api, category["id"], sku_code="SKU-F2", kind="FINDS", barcode_count=3
    )

    data, meta = validate_paginated(
        api.list_products(CATEGORY_MANAGER_HEADERS, params={"kind": "FINDS", "limit": 1, "offset": 0})
    )
    assert len(data) == 1
    assert data[0]["kind"] == "FINDS"
    assert meta["total_count"] == 2, "total_count reflects the filtered set, not all three"
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(
        api.list_products(CATEGORY_MANAGER_HEADERS, params={"kind": "FINDS", "limit": 1, "offset": 1})
    )
    assert len(data2) == 1
    assert data2[0]["kind"] == "FINDS"
    assert data2[0]["id"] != data[0]["id"]
    assert meta2["has_more"] is False


def test_immediate_consistency_post_mutation_reads(api):
    """A GET right after a coin event shows the new balance — no lag.

    PRD §3.6: "The store's `coins_outstanding` — coins currently held by customers in carts — is derived by replaying the store's events in `created_at` ascending order (timestamps carry three fractional digits, and `id` is never used for ordering): an `INSERT` adds its `coin_count`, a `RETURN` and a `CORRAL_COLLECT` each subtract theirs, and an `AUDIT_ADJUST` adds its signed `coin_count`. The balance is checked against the running prefix: any `RETURN`, `CORRAL_COLLECT`, or `AUDIT_ADJUST` that would drive it negative is rejected with `ERR_COIN_BALANCE_NEGATIVE`. The store's `coin_liability_cents` is the outstanding count multiplied by 25 — the quarter deposit per cart."

    Design: Corner/consistency_model/immediate_consistency_post_mutation_reads
    """
    store = fixtures.create_store(api)
    manager = make_store_manager_headers(store["id"])

    validate_success(
        api.create_cart_coin_event(store["id"], cart_coin_event_payload("INSERT", 7), manager),
        201,
    )
    read = validate_success(api.get_store(store["id"], manager))
    assert read["coins_outstanding"] == 7
    assert read["coin_liability_cents"] == 175, "7 coins at 25 cents each"
