"""Profit pool probes: share variants, eligibility gate, period overlap."""
from test_helpers import (
    ADMIN,
    FINANCE as FINANCE_H,
    ApiErrorId,
    calculate_pool,
    create_active_store,
    create_book,
    create_delivered_order,
    create_pool,
    create_publisher,
    create_store,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _three_august_stores():
    """Stores A/B/C created in order and activated 2026-08-01; thresholds 20000."""
    set_clock("2026-08-01T00:00:00Z")
    a = create_active_store(
        shop_name="Alpha Books",
        slug="alpha-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    b = create_active_store(
        shop_name="Beta Books",
        slug="beta-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    c = create_active_store(
        shop_name="Gamma Books",
        slug="gamma-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    return a, b, c


def _august_sales(book_a_id, book_b_id, store_a_id, store_b_id):
    """Store A gets a DELIVERED 100000 order; store B a DELIVERED 50000 order."""
    create_delivered_order(
        "cust-2",
        lines=[{"book_id": book_a_id, "quantity": 1}],
        attributed_store_id=store_a_id,
    )
    create_delivered_order(
        "cust-2",
        lines=[{"book_id": book_b_id, "quantity": 1}],
        attributed_store_id=store_b_id,
    )


def _share_map(dist_body):
    return {line["store_id"]: line for line in dist_body["share_lines"]}


def _setup_two_book_catalog():
    pub = create_publisher(
        name="Riverbend Press",
        discount_pct=0.46,
        returns_allowed=True,
        return_window_days=30,
        return_credit_pct=0.80,
    )
    book_a = create_book(
        pub["id"], isbn="9780000000002", title="Hardcover A", list_price_cents=100000
    )
    book_b = create_book(
        pub["id"], isbn="9780000000003", title="Hardcover B", list_price_cents=50000
    )
    return book_a, book_b


def test_pool_share_equal_split_vs_sales_weighted_diverge(api):
    """PRD §3.6: "Under `EQUAL_SPLIT`, each eligible store receives `pool_cents`
    divided by `eligible_store_count`, floored — a store with zero direct sales
    earns exactly what the top seller earns. Under `SALES_WEIGHTED`, each
    eligible store's weight is the sum of `gross_cents` over orders attributed
    to it that reached `DELIVERED` with `delivered_at` inside the period, and
    its share is `pool_cents` multiplied by its weight over the total weight,
    floored"
    PRD §3.6: "the unallocated `remainder_cents` — the pool minus the sum of
    floored shares — is credited to exactly one store, the eligible store with
    the earliest `created_at` under equal split, or the eligible store with the
    largest weight (ties broken by earliest `created_at`) under sales weighting."

    Design: Difficulty/dual_variant_calc/pool_share_equal_split_vs_sales_weighted_diverge
    """
    store_a, store_b, store_c = _three_august_stores()
    book_a, book_b = _setup_two_book_catalog()
    _august_sales(book_a["id"], book_b["id"], store_a["id"], store_b["id"])

    set_clock("2026-09-02T00:00:00Z")
    weighted = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        pool_cents=90001,
        share_mode="SALES_WEIGHTED",
    )
    weighted = calculate_pool(weighted["id"])
    w = _share_map(weighted)
    # weights: A=100000, B=50000, C=0; total 150000.
    assert w[store_a["id"]]["share_cents"] == 60001  # 60000 + remainder 1
    assert w[store_b["id"]]["share_cents"] == 30000
    assert w[store_c["id"]]["share_cents"] == 0

    # Free the period, then run the identical data under EQUAL_SPLIT.
    get_success_data(
        api.pool_action(weighted["id"], {"action": "recalculate"}, FINANCE_H)
    )
    get_success_data(api.pool_action(weighted["id"], {"action": "void"}, FINANCE_H))

    equal = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        pool_cents=90001,
        share_mode="EQUAL_SPLIT",
    )
    equal = calculate_pool(equal["id"])
    e = _share_map(equal)
    assert e[store_a["id"]]["share_cents"] == 30001  # 30000 + remainder 1
    assert e[store_b["id"]]["share_cents"] == 30000
    assert e[store_c["id"]]["share_cents"] == 30000


def test_pool_share_circular_weight_then_floor_then_remainder(api):
    """PRD §3.6: "Under `SALES_WEIGHTED`, each eligible store's weight is the sum
    of `gross_cents` over orders attributed to it that reached `DELIVERED` with
    `delivered_at` inside the period, and its share is `pool_cents` multiplied
    by its weight over the total weight, floored"
    PRD §3.6: "the unallocated `remainder_cents` — the pool minus the sum of
    floored shares — is credited to exactly one store, the eligible store with
    the earliest `created_at` under equal split, or the eligible store with the
    largest weight (ties broken by earliest `created_at`) under sales weighting."

    Design: Difficulty/combinatorial_formula/pool_share_circular_weight_then_floor_then_remainder
    """
    set_clock("2026-08-01T00:00:00Z")
    pub = create_publisher(
        name="Riverbend Press",
        discount_pct=0.46,
        returns_allowed=True,
        return_window_days=30,
        return_credit_pct=0.80,
    )
    book_a = create_book(
        pub["id"], isbn="9780000000011", title="Big Book", list_price_cents=100000
    )
    book_b = create_book(
        pub["id"], isbn="9780000000012", title="Mid Book", list_price_cents=50000
    )
    store_a = create_active_store(
        shop_name="AAA Books", slug="aaa-books", commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    store_b = create_active_store(
        shop_name="BBB Books", slug="bbb-books", commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    store_c = create_active_store(
        shop_name="CCC Books", slug="ccc-books", commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    _august_sales(book_a["id"], book_b["id"], store_a["id"], store_b["id"])

    set_clock("2026-09-02T00:00:00Z")
    dist = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        pool_cents=100001,
        share_mode="SALES_WEIGHTED",
    )
    dist = calculate_pool(dist["id"])
    shares = _share_map(dist)
    # floors: A floor(100001*100000/150000)=66667, B=33333, C=0; remainder 1 -> A.
    assert shares[store_a["id"]]["share_cents"] == 66668
    assert shares[store_b["id"]]["share_cents"] == 33333
    assert shares[store_c["id"]]["share_cents"] == 0
    assert dist["remainder_cents"] == 1
    assert dist["eligible_store_count"] == 3
    assert sum(line["share_cents"] for line in dist["share_lines"]) == 100001


def test_pool_eligibility_exactly_fourteen_active_days(api):
    """PRD §3.6: "A store is eligible when it was active for at least 14 such
    days; a store active exactly 14 days is eligible. The count of eligible
    stores becomes `eligible_store_count`."
    PRD §3.6: "Ineligible stores still appear in `share_lines`, marked
    `eligible` false with `share_cents` zero."

    Design: Difficulty/boundary_precision_check/pool_eligibility_exactly_fourteen_active_days
    """
    set_clock("2026-08-01T00:00:00Z")
    early = create_active_store(
        shop_name="Early Books", slug="early-books", commission_pct=0.30
    )
    edge = create_store(shop_name="Edge Books", slug="edge-books", commission_pct=0.30)
    late = create_store(shop_name="Late Books", slug="late-books", commission_pct=0.30)
    set_clock("2026-08-18T00:00:00Z")
    get_success_data(api.store_action(edge["id"], {"action": "activate"}, ADMIN))
    set_clock("2026-08-19T00:00:00Z")
    get_success_data(api.store_action(late["id"], {"action": "activate"}, ADMIN))

    set_clock("2026-09-02T00:00:00Z")
    dist = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        pool_cents=30000,
        share_mode="EQUAL_SPLIT",
    )
    dist = calculate_pool(dist["id"])
    assert dist["eligible_store_count"] == 2
    assert dist["remainder_cents"] == 0
    shares = _share_map(dist)
    assert shares[early["id"]]["eligible"] is True
    assert shares[early["id"]]["share_cents"] == 15000
    assert shares[edge["id"]]["eligible"] is True
    assert shares[edge["id"]]["share_cents"] == 15000  # exactly 14 days: eligible
    assert shares[late["id"]]["eligible"] is False
    assert shares[late["id"]]["share_cents"] == 0  # 13 days: ineligible


def test_pool_weighted_zero_total_weight_falls_back_to_equal_split(api):
    """PRD §3.6: "if no eligible store has any delivered sales in the period,
    the allocation falls back to the equal-split arithmetic."
    PRD §3.6: "the unallocated `remainder_cents` — the pool minus the sum of
    floored shares — is credited to exactly one store, the eligible store with
    the earliest `created_at` under equal split, or the eligible store with the
    largest weight (ties broken by earliest `created_at`) under sales weighting."

    Design: Corner/calculations/pool_weighted_zero_total_weight_falls_back_to_equal_split
    """
    set_clock("2026-09-01T00:00:00Z")
    first = create_active_store(
        shop_name="State Books", slug="state-books", commission_pct=0.30
    )
    second = create_active_store(
        shop_name="Second Books", slug="second-books", commission_pct=0.20
    )
    set_clock("2026-09-16T00:00:00Z")
    dist = create_pool(
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-15T00:00:00Z",
        pool_cents=40001,
        share_mode="SALES_WEIGHTED",
    )
    dist = calculate_pool(dist["id"])
    shares = _share_map(dist)
    # total_weight == 0 -> equal-split fallback: floor(40001/2) = 20000 each,
    # remainder 1 to the earliest-created store.
    assert shares[first["id"]]["share_cents"] == 20001
    assert shares[second["id"]]["share_cents"] == 20000
    assert dist["remainder_cents"] == 1


def test_pool_excludes_opted_out_and_deactivated_stores_from_candidate_set(api):
    """PRD §3.6: "for every store with `pool_opt_in` true that is not
    `DEACTIVATED`, the server counts the whole calendar days within the period
    on which the store held `ACTIVE` status for the entire day, derived from
    its `activated_at` and `suspended_at` epochs"
    PRD §3.2: "A `DEACTIVATED` store is excluded from all future pool
    distributions."

    Design: Corner/calculations/pool_excludes_opted_out_and_deactivated_stores_from_candidate_set
    """
    set_clock("2026-09-01T00:00:00Z")
    in_store = create_active_store(
        shop_name="State Books", slug="state-books", commission_pct=0.30
    )
    out_store = create_active_store(
        shop_name="Out Books",
        slug="out-books",
        commission_pct=0.20,
        pool_opt_in=False,
    )
    gone = create_active_store(
        shop_name="Gone Books", slug="gone-books", commission_pct=0.20
    )
    get_success_data(api.store_action(gone["id"], {"action": "deactivate"}, ADMIN))

    set_clock("2026-09-16T00:00:00Z")
    dist = create_pool(
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-15T00:00:00Z",
        pool_cents=28000,
        share_mode="EQUAL_SPLIT",
    )
    dist = calculate_pool(dist["id"])
    assert dist["eligible_store_count"] == 1
    assert len(dist["share_lines"]) == 1
    line = dist["share_lines"][0]
    assert line["store_id"] == in_store["id"]
    assert line["eligible"] is True
    assert line["share_cents"] == 28000
    ids = {l["store_id"] for l in dist["share_lines"]}
    assert out_store["id"] not in ids
    assert gone["id"] not in ids


def test_suspended_days_do_not_count_toward_pool_eligibility(api):
    """PRD §3.6: "for every store with `pool_opt_in` true that is not
    `DEACTIVATED`, the server counts the whole calendar days within the period
    on which the store held `ACTIVE` status for the entire day, derived from
    its `activated_at` and `suspended_at` epochs — a store suspended mid-period
    forfeits the days from suspension until reactivation."
    PRD §3.6: "If no store is eligible at all, every share is zero, the
    remainder is zero, and the pool stays unallocated — which the approval
    sum-check will refuse to lock."

    Design: Corner/calculations/suspended_days_do_not_count_toward_pool_eligibility
    """
    set_clock("2026-09-01T00:00:00Z")
    store = create_active_store(
        shop_name="State Books", slug="state-books", commission_pct=0.30
    )
    set_clock("2026-09-08T00:00:00Z")
    get_success_data(api.store_action(store["id"], {"action": "suspend"}, ADMIN))
    set_clock("2026-09-15T00:00:00Z")
    get_success_data(api.store_action(store["id"], {"action": "reactivate"}, ADMIN))
    set_clock("2026-09-16T00:00:00Z")
    dist = create_pool(
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-15T00:00:00Z",
        pool_cents=10000,
        share_mode="EQUAL_SPLIT",
    )
    dist = calculate_pool(dist["id"])
    # Only Sep 1..7 were whole ACTIVE days: 7 < 14.
    assert dist["eligible_store_count"] == 0
    assert dist["remainder_cents"] == 0
    line = _share_map(dist)[store["id"]]
    assert line["eligible"] is False
    assert line["share_cents"] == 0


def test_pool_period_half_open_overlap_vs_back_to_back(api):
    """PRD §3.6: "Periods are half-open intervals, and a new period must not
    intersect any existing non-`VOID` distribution's period under that half-open
    test; back-to-back periods, where one ends exactly as the next begins, are
    allowed. Overlaps are rejected with `ERR_POOL_PERIOD_OVERLAP` (HTTP 409)."
    PRD §3.6: "A distribution may instead be voided from `DRAFT`, which is
    terminal."

    Design: Difficulty/resource_temporal_overlap/pool_period_half_open_overlap_vs_back_to_back
    """
    set_clock("2026-09-01T00:00:00Z")
    dist = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        pool_cents=10000,
        share_mode="EQUAL_SPLIT",
    )
    # Aug 15..Sep 15 intersects [Aug 1, Sep 1) -> rejected.
    resp = api.create_pool_distribution(
        {
            "period_start": "2026-08-15T00:00:00Z",
            "period_end": "2026-09-15T00:00:00Z",
            "pool_cents": 10000,
            "share_mode": "EQUAL_SPLIT",
        },
        FINANCE_H,
    )
    validate_error(resp, ApiErrorId.ERR_POOL_PERIOD_OVERLAP, expected_status=409)

    # Back-to-back: starts exactly at the existing period's exclusive end.
    resp = api.create_pool_distribution(
        {
            "period_start": "2026-09-01T00:00:00Z",
            "period_end": "2026-10-01T00:00:00Z",
            "pool_cents": 10000,
            "share_mode": "EQUAL_SPLIT",
        },
        FINANCE_H,
    )
    validate_success(resp, expected_status=201)

    # Voiding the first distribution frees its period.
    get_success_data(api.pool_action(dist["id"], {"action": "void"}, FINANCE_H))
    # [Aug15, Sep1) overlapped with the now-void pool 1 but is back-to-back
    # with pool 3 [Sep1, Oct1), so it must now be accepted.
    resp = api.create_pool_distribution(
        {
            "period_start": "2026-08-15T00:00:00Z",
            "period_end": "2026-09-01T00:00:00Z",
            "pool_cents": 10000,
            "share_mode": "EQUAL_SPLIT",
        },
        FINANCE_H,
    )
    validate_success(resp, expected_status=201)


def test_pool_calculate_before_period_end_rejected(api):
    """PRD §3.6: "Calculation turns the `DRAFT` distribution into `CALCULATED`,
    and only once the period has fully elapsed — `period_end` must be at or
    before the logical clock, failing which the request is rejected with
    `ERR_WINDOW_NOT_SATISFIED`."

    Design: Corner/validations/pool_calculate_before_period_end_rejected
    """
    set_clock("2026-08-14T00:00:00Z")
    dist = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        pool_cents=10000,
        share_mode="EQUAL_SPLIT",
    )
    resp = api.pool_action(dist["id"], {"action": "calculate"}, FINANCE_H)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_SATISFIED, expected_status=422)

    set_clock("2026-08-15T00:00:00Z")  # clock == period_end exactly
    resp = api.pool_action(dist["id"], {"action": "calculate"}, FINANCE_H)
    body = validate_success(resp, expected_status=200)
    assert body["status"] == "CALCULATED"


def test_occ_stale_version_on_pool_approve(api):
    """PRD §2.10: "That request must carry `expected_distribution_version`, the
    distribution `version` the client last observed. Because every calculate,
    recalculate, approve, and distribute advances the distribution's `version`,
    a client acting on an earlier view holds a stale number; if the supplied
    value does not match the distribution's current `version`, the request is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/occ_stale_version_on_pool_approve
    """
    set_clock("2026-08-01T00:00:00Z")
    create_active_store(shop_name="OCC Books", slug="occ-books", commission_pct=0.20)
    set_clock("2026-09-01T00:00:00Z")
    dist = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        pool_cents=10000,
        share_mode="EQUAL_SPLIT",
    )
    stale_version = dist["version"]
    calc = calculate_pool(dist["id"])
    assert calc["version"] != stale_version

    resp = api.pool_action(
        dist["id"],
        {"action": "approve", "expected_distribution_version": stale_version},
        FINANCE_H,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    resp = api.pool_action(
        dist["id"],
        {"action": "approve", "expected_distribution_version": calc["version"]},
        FINANCE_H,
    )
    body = validate_success(resp, expected_status=200)
    assert body["status"] == "APPROVED"


def test_pool_void_terminal_and_double_distribute_fails(api):
    """PRD §3.6: "the distribution lifecycle runs `DRAFT` → `CALCULATED` →
    `APPROVED` → `DISTRIBUTED`, with recalculate returning `CALCULATED` to
    `DRAFT` and `VOID` as the terminal alternative out of `DRAFT`"
    PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/pool_void_terminal_and_double_distribute_fails
    """
    set_clock("2026-08-01T00:00:00Z")
    create_active_store(
        shop_name="State Books", slug="state-books", commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    set_clock("2026-09-01T00:00:00Z")
    dist_v = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        pool_cents=10000,
        share_mode="EQUAL_SPLIT",
    )
    dist_d = create_pool(
        period_start="2026-08-15T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
        pool_cents=10000,
        share_mode="EQUAL_SPLIT",
    )
    get_success_data(api.pool_action(dist_v["id"], {"action": "void"}, FINANCE_H))
    calc = calculate_pool(dist_d["id"])
    get_success_data(
        api.pool_action(
            dist_d["id"],
            {"action": "approve", "expected_distribution_version": calc["version"]},
            FINANCE_H,
        )
    )
    done = get_success_data(
        api.pool_action(dist_d["id"], {"action": "distribute"}, FINANCE_H)
    )
    assert done["status"] == "DISTRIBUTED"

    resp = api.pool_action(dist_v["id"], {"action": "calculate"}, FINANCE_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    resp = api.pool_action(dist_d["id"], {"action": "distribute"}, FINANCE_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    resp = api.list_ledger_entries(FINANCE_H, {"pool_distribution_id": dist_v["id"]})
    entries, _meta = validate_paginated(resp)
    assert entries == []


def test_pool_distribute_cascades_share_lines_ledger_payout(api):
    """PRD §3.6: "Distribution itself moves each eligible share line with a
    positive amount — processed in order of store `created_at` ascending — into
    a `POOL_DISTRIBUTION` ledger entry naming the distribution via
    `pool_distribution_id`; each write reconciles that store's
    `accrued_balance_cents`, and after the final write the payout release sweep
    runs, opening payouts for every affiliate whose balance now meets its
    threshold."
    PRD §2.7: "if the balance is greater than or equal to the affiliate's
    `payout_threshold_cents`, and no payout for that affiliate currently sits in
    `PENDING` or `PROCESSING`, and the affiliate's own status is `ACTIVE`, a new
    payout is opened for exactly the current balance as a frozen snapshot."

    Design: Difficulty/transitive_cascade/pool_distribute_cascades_share_lines_ledger_payout
    """
    set_clock("2026-08-01T00:00:00Z")
    store_a = create_active_store(
        shop_name="Pool A", slug="pool-a", commission_pct=0.30,
        payout_threshold_cents=2500,
    )
    store_b = create_active_store(
        shop_name="Pool B", slug="pool-b", commission_pct=0.30,
        payout_threshold_cents=60000,
    )
    set_clock("2026-09-02T00:00:00Z")
    dist = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        pool_cents=60000,
        share_mode="EQUAL_SPLIT",
    )
    calc = calculate_pool(dist["id"])
    get_success_data(
        api.pool_action(
            dist["id"],
            {"action": "approve", "expected_distribution_version": calc["version"]},
            FINANCE_H,
        )
    )
    done = get_success_data(
        api.pool_action(dist["id"], {"action": "distribute"}, FINANCE_H)
    )
    assert done["status"] == "DISTRIBUTED"

    resp = api.list_ledger_entries(
        FINANCE_H, {"pool_distribution_id": dist["id"], "kind": "POOL_DISTRIBUTION"}
    )
    entries, _ = validate_paginated(resp)
    amounts = {e["affiliate_store_id"]: e["amount_cents"] for e in entries}
    assert amounts[store_a["id"]] == 30000
    assert amounts[store_b["id"]] == 30000

    a = get_success_data(api.get_store(store_a["id"], FINANCE_H))
    b = get_success_data(api.get_store(store_b["id"], FINANCE_H))
    assert a["accrued_balance_cents"] == 30000
    assert b["accrued_balance_cents"] == 30000

    payouts_a, _ = validate_paginated(
        api.list_payouts(FINANCE_H, {"affiliate_store_id": store_a["id"]})
    )
    assert len(payouts_a) == 1
    assert payouts_a[0]["amount_cents"] == 30000
    assert payouts_a[0]["status"] == "PENDING"

    payouts_b, _ = validate_paginated(
        api.list_payouts(FINANCE_H, {"affiliate_store_id": store_b["id"]})
    )
    assert payouts_b == []


def test_err_pool_sum_mismatch_when_no_eligible_stores(api):
    """PRD §3.6: "If no store is eligible at all, every share is zero, the
    remainder is zero, and the pool stays unallocated — which the approval
    sum-check will refuse to lock."
    PRD §3.6: "the `share_cents` across `share_lines` must total exactly
    `pool_cents`, else `ERR_POOL_SUM_MISMATCH` (HTTP 422)."

    Design: Corner/errors/err_pool_sum_mismatch_when_no_eligible_stores
    """
    set_clock("2026-09-01T00:00:00Z")
    create_active_store(
        shop_name="Opted Out",
        slug="opted-out",
        commission_pct=0.20,
        pool_opt_in=False,
    )
    dist = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        pool_cents=10000,
        share_mode="EQUAL_SPLIT",
    )
    calc = calculate_pool(dist["id"])
    assert calc["status"] == "CALCULATED"
    resp = api.pool_action(
        dist["id"],
        {"action": "approve", "expected_distribution_version": calc["version"]},
        FINANCE_H,
    )
    validate_error(resp, ApiErrorId.ERR_POOL_SUM_MISMATCH, expected_status=422)


def test_pool_share_modes_disagree_on_two_store_data(api):
    """PRD §3.6: "Under `EQUAL_SPLIT`, each eligible store receives `pool_cents`
    divided by `eligible_store_count`, floored — a store with zero direct sales
    earns exactly what the top seller earns. Under `SALES_WEIGHTED`, each
    eligible store's weight is the sum of `gross_cents` over orders attributed
    to it that reached `DELIVERED` with `delivered_at` inside the period, and
    its share is `pool_cents` multiplied by its weight over the total weight,
    floored"

    Design: Difficulty/dual_variant_calc/pool_share_equal_split_vs_sales_weighted_diverge
    """
    set_clock("2026-08-01T00:00:00Z")
    pub = create_publisher(
        name="Riverbend Press",
        discount_pct=0.46,
        returns_allowed=True,
        return_window_days=30,
        return_credit_pct=0.80,
    )
    book = create_book(
        pub["id"], isbn="9780000000002", title="Hardcover A", list_price_cents=100000
    )
    seller = create_active_store(
        shop_name="Seller Books", slug="seller-books", commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    quiet = create_active_store(
        shop_name="Quiet Books", slug="quiet-books", commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    create_delivered_order(
        "cust-2",
        lines=[{"book_id": book["id"], "quantity": 1}],
        attributed_store_id=seller["id"],
    )
    set_clock("2026-09-02T00:00:00Z")

    weighted = calculate_pool(
        create_pool(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
            pool_cents=50000,
            share_mode="SALES_WEIGHTED",
        )["id"]
    )
    w = _share_map(weighted)
    # Seller holds all the weight and takes the entire pool.
    assert w[seller["id"]]["share_cents"] == 50000
    assert w[quiet["id"]]["share_cents"] == 0

    get_success_data(api.pool_action(weighted["id"], {"action": "recalculate"}, FINANCE_H))
    get_success_data(api.pool_action(weighted["id"], {"action": "void"}, FINANCE_H))

    equal = calculate_pool(
        create_pool(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
            pool_cents=50000,
            share_mode="EQUAL_SPLIT",
        )["id"]
    )
    e = _share_map(equal)
    # Same data, equal split: the zero-sales store earns what the seller earns.
    assert e[seller["id"]]["share_cents"] == 25000
    assert e[quiet["id"]]["share_cents"] == 25000


def test_pool_weighted_exact_division_leaves_zero_remainder(api):
    """PRD §3.6: "the unallocated `remainder_cents` — the pool minus the sum of
    floored shares — is credited to exactly one store, the eligible store with
    the earliest `created_at` under equal split, or the eligible store with the
    largest weight (ties broken by earliest `created_at`) under sales weighting."
    PRD §3.6: "Under `SALES_WEIGHTED`, each eligible store's weight is the sum
    of `gross_cents` over orders attributed to it that reached `DELIVERED` with
    `delivered_at` inside the period, and its share is `pool_cents` multiplied
    by its weight over the total weight, floored"

    Design: Difficulty/combinatorial_formula/pool_share_circular_weight_then_floor_then_remainder
    """
    set_clock("2026-08-01T00:00:00Z")
    pub = create_publisher(
        name="Riverbend Press",
        discount_pct=0.46,
        returns_allowed=True,
        return_window_days=30,
        return_credit_pct=0.80,
    )
    book = create_book(
        pub["id"], isbn="9780000000002", title="Hardcover A", list_price_cents=100000
    )
    seller = create_active_store(
        shop_name="Seller Books", slug="seller-books", commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    create_active_store(
        shop_name="Quiet Books", slug="quiet-books", commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    create_delivered_order(
        "cust-2",
        lines=[{"book_id": book["id"], "quantity": 1}],
        attributed_store_id=seller["id"],
    )
    set_clock("2026-09-02T00:00:00Z")
    dist = calculate_pool(
        create_pool(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
            pool_cents=40000,
            share_mode="SALES_WEIGHTED",
        )["id"]
    )
    # floor(40000 * 100000/100000) = 40000 exactly: nothing left over.
    assert dist["remainder_cents"] == 0
    shares = _share_map(dist)
    assert shares[seller["id"]]["share_cents"] == 40000
    assert sum(line["share_cents"] for line in dist["share_lines"]) == 40000


def test_store_active_thirteen_days_is_ineligible(api):
    """PRD §3.6: "A store is eligible when it was active for at least 14 such
    days; a store active exactly 14 days is eligible. The count of eligible
    stores becomes `eligible_store_count`."
    PRD §3.6: "Ineligible stores still appear in `share_lines`, marked
    `eligible` false with `share_cents` zero."

    Design: Difficulty/boundary_precision_check/pool_eligibility_exactly_fourteen_active_days
    """
    set_clock("2026-08-01T00:00:00Z")
    late = create_store(shop_name="Late Books", slug="late-books", commission_pct=0.30)
    set_clock("2026-08-19T00:00:00Z")
    get_success_data(api.store_action(late["id"], {"action": "activate"}, ADMIN))
    set_clock("2026-09-02T00:00:00Z")
    dist = calculate_pool(
        create_pool(
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
            pool_cents=30000,
            share_mode="EQUAL_SPLIT",
        )["id"]
    )
    assert dist["eligible_store_count"] == 0
    line = _share_map(dist)[late["id"]]
    assert line["eligible"] is False  # 13 whole ACTIVE days < 14
    assert line["share_cents"] == 0


def test_pool_period_partial_overlap_at_start_rejected(api):
    """PRD §3.6: "Periods are half-open intervals, and a new period must not
    intersect any existing non-`VOID` distribution's period under that half-open
    test; back-to-back periods, where one ends exactly as the next begins, are
    allowed. Overlaps are rejected with `ERR_POOL_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/pool_period_half_open_overlap_vs_back_to_back
    """
    set_clock("2026-09-01T00:00:00Z")
    create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        pool_cents=10000,
        share_mode="EQUAL_SPLIT",
    )
    # A period ending exactly at the existing start is back-to-back: allowed.
    resp = api.create_pool_distribution(
        {
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-08-01T00:00:00Z",
            "pool_cents": 10000,
            "share_mode": "EQUAL_SPLIT",
        },
        FINANCE_H,
    )
    validate_success(resp, expected_status=201)
    # A period starting before and ending inside the existing one: overlap.
    resp = api.create_pool_distribution(
        {
            "period_start": "2026-07-15T00:00:00Z",
            "period_end": "2026-08-15T00:00:00Z",
            "pool_cents": 10000,
            "share_mode": "EQUAL_SPLIT",
        },
        FINANCE_H,
    )
    validate_error(resp, ApiErrorId.ERR_POOL_PERIOD_OVERLAP, expected_status=409)


def test_pool_distribute_releases_payout_at_exact_threshold(api):
    """PRD §3.6: "Distribution itself moves each eligible share line with a
    positive amount — processed in order of store `created_at` ascending — into
    a `POOL_DISTRIBUTION` ledger entry naming the distribution via
    `pool_distribution_id`; each write reconciles that store's
    `accrued_balance_cents`, and after the final write the payout release sweep
    runs, opening payouts for every affiliate whose balance now meets its
    threshold."
    PRD §2.7: "A balance exactly equal to the threshold does release."

    Design: Difficulty/transitive_cascade/pool_distribute_cascades_share_lines_ledger_payout
    """
    set_clock("2026-08-01T00:00:00Z")
    store_a = create_active_store(
        shop_name="Pool A", slug="pool-a", commission_pct=0.30,
        payout_threshold_cents=2500,
    )
    store_b = create_active_store(
        shop_name="Pool B", slug="pool-b", commission_pct=0.30,
        payout_threshold_cents=2500,
    )
    set_clock("2026-09-02T00:00:00Z")
    dist = create_pool(
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
        pool_cents=5000,
        share_mode="EQUAL_SPLIT",
    )
    calc = calculate_pool(dist["id"])
    get_success_data(
        api.pool_action(
            dist["id"],
            {"action": "approve", "expected_distribution_version": calc["version"]},
            FINANCE_H,
        )
    )
    done = get_success_data(
        api.pool_action(dist["id"], {"action": "distribute"}, FINANCE_H)
    )
    assert done["status"] == "DISTRIBUTED"

    entries, _ = validate_paginated(
        api.list_ledger_entries(
            FINANCE_H, {"pool_distribution_id": dist["id"], "kind": "POOL_DISTRIBUTION"}
        )
    )
    amounts = {e["affiliate_store_id"]: e["amount_cents"] for e in entries}
    assert amounts[store_a["id"]] == 2500
    assert amounts[store_b["id"]] == 2500

    for store in (store_a, store_b):
        payouts, _ = validate_paginated(
            api.list_payouts(FINANCE_H, {"affiliate_store_id": store["id"]})
        )
        assert len(payouts) == 1  # 2500 == threshold: releases
        assert payouts[0]["amount_cents"] == 2500
