"""Funding grants and the expense waterfall: allocation order,
all-or-nothing sufficiency, the exact-total boundary, optimistic
concurrency on expense posting, and grant expiry via run_ops."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    TEST_USERS,
    assert_expense_result,
    assert_funding_grant,
    create_center,
    create_funding_grant,
    get_center,
    run_ops,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

MGR = TEST_USERS["manager_headers"]


def _grants_by_id(api: ApiClient, center_id: str) -> dict:
    rows, _meta = validate_paginated(api.list_funding_grants(center_id, MGR))
    return {row["id"]: row for row in rows}


def test_waterfall_allocation_order(api: ApiClient):
    """PRD §3.8: "Posting runs an all-or-nothing waterfall across the center's `ACTIVE` grants, ordered by `spend_by_date` ascending with ties broken by `created_at` ascending — never by `id`."
    PRD §3.8: "Otherwise the waterfall walks the grants in order, debiting each the smaller of its own `remaining_cents` and the amount still unallocated; a grant drawn to exactly zero flips to `EXHAUSTED`. An expense exactly equal to the total remaining succeeds and exhausts every candidate."
    PRD §3.8: "The response returns `posted_cents` together with a `debits` list that preserves the allocation order, and the posting appends an entry carrying `posted_at`, `amount_cents`, and `description` to the center's append-only `expense_ledger`, incrementing the center's `version` by one."

    Design: Corner/calculations/waterfall_allocation_order
    """
    set_clock()
    center = create_center(
        name="Dalet Center",
        airport_code="OKC",
        occupancy_cap=25,
        required_daily_confirmed_assignments=1,
    )
    grant_a = create_funding_grant(
        center["id"], donor_name="Donor A", amount_cents=500,
        spend_by_date="2026-10-01",
    )
    grant_b = create_funding_grant(
        center["id"], donor_name="Donor B", amount_cents=700,
        spend_by_date="2026-11-01",
    )

    fresh = get_center(center["id"])
    resp = api.create_expense(
        center["id"],
        {
            "amount_cents": 600,
            "description": "coffee restock",
            "expected_center_version": fresh["version"],
        },
        MGR,
    )
    data = validate_success(resp, 201)
    assert_expense_result(data)
    assert data["posted_cents"] == 600
    assert len(data["debits"]) == 2, (
        "600 cents over grants of 500 and 700 allocates across exactly "
        f"two grants, got {len(data['debits'])} debits"
    )

    grants = _grants_by_id(api, center["id"])
    a = grants[grant_a["id"]]
    b = grants[grant_b["id"]]
    # The earlier spend_by_date (2026-10-01) is drained first: A takes the
    # full 500 (min(500, 600)) and flips EXHAUSTED; B takes the residual 100.
    assert a["spent_cents"] == 500 and a["remaining_cents"] == 0
    assert a["status"] == "EXHAUSTED"
    assert b["spent_cents"] == 100 and b["remaining_cents"] == 600
    assert b["status"] == "ACTIVE"
    assert_funding_grant(a)
    assert_funding_grant(b)


def test_waterfall_insufficient_all_or_nothing(api: ApiClient):
    """PRD §3.8: "If the expense exceeds the sum of `remaining_cents` across those grants, the posting is rejected with `ERR_BUDGET_EXCEEDED` and nothing is debited."

    Design: Corner/calculations/waterfall_insufficient_all_or_nothing
    """
    set_clock()
    center = create_center(
        name="He Center",
        airport_code="TUL",
        occupancy_cap=25,
        required_daily_confirmed_assignments=1,
    )
    grant = create_funding_grant(
        center["id"], donor_name="Donor C", amount_cents=500,
        spend_by_date="2026-12-31",
    )

    fresh = get_center(center["id"])
    resp = api.create_expense(
        center["id"],
        {
            "amount_cents": 501,
            "description": "over budget",
            "expected_center_version": fresh["version"],
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)

    grants = _grants_by_id(api, center["id"])
    assert grants[grant["id"]]["spent_cents"] == 0, (
        "all-or-nothing: the rejected posting debits nothing"
    )
    assert grants[grant["id"]]["remaining_cents"] == 500
    assert grants[grant["id"]]["status"] == "ACTIVE"


def test_waterfall_exact_total_boundary(api: ApiClient):
    """PRD §3.8: "Otherwise the waterfall walks the grants in order, debiting each the smaller of its own `remaining_cents` and the amount still unallocated; a grant drawn to exactly zero flips to `EXHAUSTED`. An expense exactly equal to the total remaining succeeds and exhausts every candidate."

    Design: Corner/calculations/waterfall_exact_total_boundary
    """
    set_clock()
    center = create_center(
        name="Vav Center",
        airport_code="LIT",
        occupancy_cap=25,
        required_daily_confirmed_assignments=1,
    )
    grant = create_funding_grant(
        center["id"], donor_name="Donor D", amount_cents=500,
        spend_by_date="2026-12-31",
    )

    fresh = get_center(center["id"])
    resp = api.create_expense(
        center["id"],
        {
            "amount_cents": 500,
            "description": "exact drain",
            "expected_center_version": fresh["version"],
        },
        MGR,
    )
    data = validate_success(resp, 201)
    assert data["posted_cents"] == 500, (
        "an expense exactly equal to the total remaining is accepted"
    )

    grants = _grants_by_id(api, center["id"])
    assert grants[grant["id"]]["remaining_cents"] == 0
    assert grants[grant["id"]]["status"] == "EXHAUSTED", (
        "a grant drawn to exactly zero flips to EXHAUSTED"
    )


def test_occ_expense_post_stale_version(api: ApiClient):
    """PRD §3.8: "Center expenses are posted by a `CenterManager` with an `amount_cents`, a `description`, and the obligatory `expected_center_version`; a stale center version rejects the posting with `ERR_STALE_VERSION`, because the allocation below depends on grant state the client may not have seen."
    PRD §2.5: "In all three cases, if the parent entity's `version` has advanced since the client last read it, the write is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is applied."

    Design: Corner/complexity_layers/occ_expense_post_stale_version
    """
    set_clock()
    center = create_center(
        name="Kaf2 Center",
        airport_code="MFE",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    grant = create_funding_grant(
        center["id"], donor_name="Donor E", amount_cents=10000,
        spend_by_date="2026-12-31",
    )

    fresh = get_center(center["id"])
    first = api.create_expense(
        center["id"],
        {
            "amount_cents": 100,
            "description": "first",
            "expected_center_version": fresh["version"],
        },
        MGR,
    )
    data = validate_success(first, 201)
    assert data["posted_cents"] == 100

    # The first posting bumped Center.version; replaying the same
    # expected_center_version is now stale and applies nothing.
    stale = api.create_expense(
        center["id"],
        {
            "amount_cents": 200,
            "description": "second",
            "expected_center_version": fresh["version"],
        },
        MGR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    grants = _grants_by_id(api, center["id"])
    assert grants[grant["id"]]["spent_cents"] == 100, (
        "the stale posting is rejected wholesale: only the first 100 cents "
        f"were debited, got {grants[grant['id']]['spent_cents']}"
    )


def test_grant_expiry_run_ops(api: ApiClient):
    """PRD §3.8: "When the operations checkpoint finds an `ACTIVE` grant whose `spend_by_date` has passed, the grant becomes `EXPIRED` and its remaining money is no longer spendable."
    PRD §3.8: "If the expense exceeds the sum of `remaining_cents` across those grants, the posting is rejected with `ERR_BUDGET_EXCEEDED` and nothing is debited."

    Design: Corner/complexity_layers/grant_expiry_run_ops
    """
    set_clock()
    center = create_center(
        name="Nun2 Center",
        airport_code="GRB",
        occupancy_cap=10,
        required_daily_confirmed_assignments=1,
    )
    grant = create_funding_grant(
        center["id"], donor_name="Donor F", amount_cents=800,
        spend_by_date="2026-09-05",
    )

    set_clock("2026-09-06T00:00:00Z")
    run_ops(center["id"])

    grants = _grants_by_id(api, center["id"])
    assert grants[grant["id"]]["status"] == "EXPIRED", (
        f"spend_by 2026-09-05 < current date 2026-09-06: the checkpoint "
        f"expires the grant, got {grants[grant['id']]['status']!r}"
    )

    # The expired grant has left the waterfall candidate set, so even 100
    # cents exceeds the total remaining (0).
    fresh = get_center(center["id"])
    resp = api.create_expense(
        center["id"],
        {
            "amount_cents": 100,
            "description": "too late",
            "expected_center_version": fresh["version"],
        },
        MGR,
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
