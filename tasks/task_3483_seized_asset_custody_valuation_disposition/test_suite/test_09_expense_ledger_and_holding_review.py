"""The append-only holding-cost ledger: the accumulator's arithmetic, its
zero floor, and the idempotent monthly accrual sweep."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_expense_entry,
    create_case,
    create_expense_entry_payload,
    create_valued_asset,
    get_asset,
    intake_asset,
    move_asset_to_storage,
    post_expense,
    run_holding_review,
    set_clock,
    validate_created,
    validate_error,
    validate_paginated,
)


def test_expense_cost_reversal_invariant(api):
    """PRD §3.4: "Each posting recomputes the asset's
    `accumulated_net_holding_cost_cents`, defined as the sum of the asset's
    `COST` entries minus the sum of its `REVENUE_OFFSET` entries minus the
    sum of its `REVERSAL` entries"
    PRD §3.4: "There is no update or delete for ledger rows — every entry is
    permanently `POSTED`, and a mistake is corrected by posting the
    compensating `REVERSAL`, never by editing history."

    Design: Difficulty/compensating_invariant/expense_cost_reversal_invariant
    """
    case = create_case(
        case_number="26-MJ-0017", judicial_district="E.D. Mich.",
        forfeiture_type="CIVIL", lead_agency_code="DEA",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="trailer",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    post_expense(
        asset["id"], 60_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )
    post_expense(
        asset["id"], 40_000, entry_kind="COST", expense_type="MAINTENANCE",
        incurred_on="2026-09-03T00:00:00Z",
    )
    post_expense(
        asset["id"], 20_000, entry_kind="REVENUE_OFFSET",
        expense_type="MANAGEMENT_FEE", incurred_on="2026-09-04T00:00:00Z",
    )
    base = get_asset(asset["id"])["accumulated_net_holding_cost_cents"]
    assert base == 80_000, "60000 + 40000 COST - 20000 REVENUE_OFFSET"

    post_expense(
        asset["id"], 30_000, entry_kind="COST", expense_type="SECURITY",
        incurred_on="2026-09-05T00:00:00Z",
    )
    post_expense(
        asset["id"], 30_000, entry_kind="REVERSAL", expense_type="SECURITY",
        incurred_on="2026-09-05T01:00:00Z",
    )
    after = get_asset(asset["id"])["accumulated_net_holding_cost_cents"]
    assert after == 80_000, "the COST/REVERSAL pair conserves the accumulator"

    rows, meta = validate_paginated(
        api.list_asset_expense_entries(
            asset["id"], TEST_USERS["asset_custodian_headers"]
        )
    )
    assert len(rows) == 5 and meta["total_count"] == 5, (
        "the REVERSAL persists as its own row — no mutation of history"
    )
    kinds = [r["entry_kind"] for r in rows]
    assert kinds.count("COST") == 3
    assert kinds.count("REVENUE_OFFSET") == 1
    assert kinds.count("REVERSAL") == 1


def test_reversal_below_zero_rejected(api):
    """PRD §3.4: "The accumulator may never be driven below zero: a reversal
    or revenue offset that would do so is rejected with
    `ERR_NEGATIVE_HOLDING_COST`."

    Design: Corner/errors/reversal_below_zero_rejected
    """
    case = create_case(
        case_number="26-MJ-1028", judicial_district="E.D. Va.",
        forfeiture_type="CIVIL", lead_agency_code="USMS",
    )
    asset = intake_asset(
        case["id"], asset_type="VEHICLE", description="flatbed",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="GOOD",
    )
    post_expense(
        asset["id"], 60_000, entry_kind="COST", expense_type="STORAGE",
        incurred_on="2026-09-02T00:00:00Z",
    )

    over = api.create_expense_entry(
        create_expense_entry_payload(
            asset["id"], entry_kind="REVERSAL", expense_type="STORAGE",
            amount_cents=60_001, incurred_on="2026-09-03T00:00:00Z",
        ),
        TEST_USERS["asset_custodian_headers"],
    )
    validate_error(over, ApiErrorId.ERR_NEGATIVE_HOLDING_COST)
    assert over.status_code == 422, "60001 against an accumulated 60000"

    exact = validate_created(
        api.create_expense_entry(
            create_expense_entry_payload(
                asset["id"], entry_kind="REVERSAL", expense_type="STORAGE",
                amount_cents=60_000, incurred_on="2026-09-03T01:00:00Z",
            ),
            TEST_USERS["asset_custodian_headers"],
        )
    )
    assert_expense_entry(exact)
    assert get_asset(asset["id"])["accumulated_net_holding_cost_cents"] == 0, (
        "the zero floor is reachable, not crossed"
    )


def test_holding_review_monthly_accrual_idempotent_and_filtered(api):
    """PRD §3.4: "A `FundAdministrator` runs the holding-review checkpoint,
    which scans every asset whose `legal_state` is `SEIZED`,
    `VALUATION_PENDING`, `VALUED`, or `DISPOSITION_REVIEW` and whose
    `custody_state` is `SECURED`, `IN_STORAGE`, or `IN_MAINTENANCE`."
    PRD §3.4: "The sweep is idempotent per asset per calendar month — a
    second run in the same month posts nothing — and its response carries the
    counts `assets_reviewed` and `accruals_posted`."
    PRD §3.3: the monthly carrying rates are "25,000 ($250) for `VEHICLE`".

    Design: Corner/calculations/holding_review_monthly_accrual_idempotent_and_filtered
    """
    case = create_case(
        case_number="26-MJ-1019", judicial_district="D. Kan.",
        forfeiture_type="CIVIL", lead_agency_code="ATF",
    )
    # In scope: legal VALUED, custody IN_STORAGE.
    in_scope, _ = create_valued_asset(
        case["id"], raw_value_cents=100_000, grade="EXCELLENT",
        method="BLUE_BOOK", description="stored car",
    )
    move_asset_to_storage(in_scope["id"], "EXCELLENT")
    # Out of scope: custody INTAKE is outside the sweep's custody filter.
    out_of_scope = intake_asset(
        case["id"], asset_type="VEHICLE", description="yard car",
        seized_on="2026-09-01T00:00:00Z", seizure_condition_grade="POOR",
    )

    set_clock("2026-09-15T00:00:00Z")
    run1 = run_holding_review()
    assert run1["accruals_posted"] == 1
    assert run1["assets_reviewed"] == 1, "only the IN_STORAGE asset is scanned"

    run2 = run_holding_review()
    assert run2["accruals_posted"] == 0, (
        "a second run inside the same calendar month is a no-op"
    )

    set_clock("2026-10-02T00:00:00Z")
    run3 = run_holding_review()
    assert run3["accruals_posted"] == 1, "October is a fresh asset-month"

    assert get_asset(in_scope["id"])["accumulated_net_holding_cost_cents"] == 50_000, (
        "two monthly accruals at the 25000 VEHICLE rate"
    )
    assert get_asset(out_of_scope["id"])["accumulated_net_holding_cost_cents"] == 0
