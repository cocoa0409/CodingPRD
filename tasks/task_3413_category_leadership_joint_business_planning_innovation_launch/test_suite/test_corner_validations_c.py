"""Corner queue — validation probes on the fund ledger, the OCC-guarded
shelf-recommendation write, plan uniqueness, and the ordered shelf-rec
verification checks (state, implementation SLA, store count).

Each test translates one non-stub corner-design `validations` instance and
cites the PRD sentence that pins the asserted rule.
"""
from test_helpers import (
    ApiErrorId,
    assert_plan,
    assert_shelf_recommendation,
    create_accepted_analysis,
    create_accrual_payload,
    create_implementing_shelf_rec,
    create_plan,
    create_plan_decide_payload,
    create_plan_payload,
    create_shelf_rec_payload,
    create_verify_payload,
    get_fund,
    get_plan_version,
    post_accrual,
    set_clock,
    setup_activated_plan,
    setup_proposed_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_duplicate_accrual_period_rejected_without_double_count(
    api, finance_analyst_headers
):
    """PRD §3.6: "A `FinanceAnalyst` posts one accrual per period against a fund, supplying the `period` as a `YYYY-MM` string and the period's `invoiced_sales_cents`; each period may be posted to a fund only once, and a repeat is rejected with `ERR_DUPLICATE_ACCRUAL_PERIOD` (HTTP 409)."
    PRD §3.6: "The period's accrual-basis shares accumulate into `edlp_accrued_cents` and `event_accrued_cents`, the cash shares into `edlp_cash_cents` and `event_cash_cents`, the raw invoiced amount into `total_invoiced_cents`, and the fund's `version` increments."

    Reposting period 2027-01 to the same fund is rejected, and the rejected
    repeat accumulates nothing: `total_invoiced_cents` still reads the first
    posting's 1000000.

    Design: Corner/validations/duplicate_accrual_period_returns_409
    """
    scenario = setup_activated_plan()
    fund_id = scenario["fund"]["id"]

    post_accrual(fund_id, "2027-01", 1000000)

    validate_error(
        api.post_fund_accrual(
            fund_id, create_accrual_payload("2027-01", 500000), finance_analyst_headers
        ),
        ApiErrorId.ERR_DUPLICATE_ACCRUAL_PERIOD,
    )

    fund = get_fund(fund_id)
    assert fund["total_invoiced_cents"] == 1000000, (
        f"a rejected repeat must not double-count, got {fund['total_invoiced_cents']}"
    )


def test_space_change_beyond_absolute_cap_rejected(api, category_advisor_headers):
    """PRD §3.4: "The recommendation names a `title`, a `space_change_pct` — the recommended total shelf-space change for the manufacturer's portfolio, whose absolute value may not exceed 30 percent in either direction — and a `target_store_count`, an integer from 1 to 10000, recording how many stores must implement the change for it to count as verified."
    PRD §2.9: "Body shape: required fields present, no undeclared fields, types valid, enum members valid, and the numeric, string, and array constraints of the resource honored — including the pagination `limit` range, the promotional discount-depth cap, the shelf space-change cap, the store-count range, the rule that `sku_adds` and `sku_drops` must not overlap, positive committed volumes, a positive sales target, review and event windows whose end is strictly after their start, the `YYYY-MM` accrual period format, and the requirement that a price-pack's `channel` belongs to the plan retailer's channel set. Any breach is `ERR_VALIDATION` (HTTP 400)."

    `space_change_pct` 31 breaches the 30-percent absolute cap — a body-shape
    violation (400) even with a fresh `expected_plan_version` and an accepted
    analysis in place.

    Design: Corner/validations/shelf_space_change_out_of_range_returns_400
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    create_accepted_analysis(plan_id, scenario["retailer"]["id"])
    plan_version = get_plan_version(plan_id)

    validate_error(
        api.create_shelf_recommendation(
            plan_id,
            create_shelf_rec_payload(plan_version, title="Too far", space_change_pct=31),
            category_advisor_headers,
        ),
        ApiErrorId.ERR_VALIDATION,
    )


def test_sku_in_both_adds_and_drops_rejected(api, category_advisor_headers):
    """PRD §3.4: "Two optional assortment arrays accompany it: `sku_adds`, the SKU codes to add, and `sku_drops`, the SKU codes to remove."
    PRD §3.4: "Either may be empty and both default to empty, but they must never intersect — a SKU listed in both is a body-shape violation under `ERR_VALIDATION`."

    SKU-2 appears in both `sku_adds` and `sku_drops`: a body-shape violation
    (400).

    Design: Corner/validations/sku_lists_overlap_returns_400
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    create_accepted_analysis(plan_id, scenario["retailer"]["id"])
    plan_version = get_plan_version(plan_id)

    validate_error(
        api.create_shelf_recommendation(
            plan_id,
            create_shelf_rec_payload(
                plan_version,
                title="Contradictory",
                sku_adds=["SKU-1", "SKU-2"],
                sku_drops=["SKU-2"],
            ),
            category_advisor_headers,
        ),
        ApiErrorId.ERR_VALIDATION,
    )


def test_second_live_plan_for_same_triple_rejected(api, manufacturer_planner_headers):
    """PRD §3.1: "Uniqueness is enforced across the joint calendar: at most one plan per combination of retailer, category, and fiscal year may exist in a non-terminal status — a duplicate attempt while a live sibling exists fails with `ERR_PLAN_ALREADY_EXISTS` (HTTP 409), though a plan whose predecessor ended `REJECTED` or `EXPIRED` is free to be re-created."

    The first plan for (retailer, category, 2027) is live (PROPOSED), so the
    second create over the same triple fails.

    Design: Corner/validations/plan_create_duplicate_active_triple_returns_409
    """
    scenario = setup_proposed_plan()

    validate_error(
        api.create_plan(
            create_plan_payload(
                scenario["retailer"]["id"],
                scenario["category"]["id"],
                growth_target_pct=10,
                weekly_baseline_cases=200,
                avg_unit_net_price_cents=500,
            ),
            manufacturer_planner_headers,
        ),
        ApiErrorId.ERR_PLAN_ALREADY_EXISTS,
    )


def test_plan_triple_vacated_by_terminal_rejection(api, manufacturer_planner_headers):
    """PRD §3.1: "Uniqueness is enforced across the joint calendar: at most one plan per combination of retailer, category, and fiscal year may exist in a non-terminal status — a duplicate attempt while a live sibling exists fails with `ERR_PLAN_ALREADY_EXISTS` (HTTP 409), though a plan whose predecessor ended `REJECTED` or `EXPIRED` is free to be re-created."
    PRD §3.1: "From `PROPOSED`, only the plan's own `RetailerBuyer` may decide: a `decision` of `ACCEPT` moves the plan `PROPOSED → ACCEPTED`, while `REJECT` moves it to the terminal `REJECTED`."

    Once the retailer rejects the first plan into the terminal REJECTED state,
    the (retailer, category, 2027) triple is free and the re-create succeeds
    (201), born PROPOSED.

    Design: Corner/validations/plan_create_duplicate_triple_allowed_after_rejection
    """
    scenario = setup_proposed_plan()

    rejected = validate_success(
        api.decide_plan(
            scenario["plan"]["id"],
            create_plan_decide_payload("REJECT"),
            scenario["buyer_headers"],
        ),
        200,
    )
    assert rejected["status"] == "REJECTED"

    created = validate_success(
        api.create_plan(
            create_plan_payload(
                scenario["retailer"]["id"],
                scenario["category"]["id"],
                growth_target_pct=10,
                weekly_baseline_cases=200,
                avg_unit_net_price_cents=500,
            ),
            manufacturer_planner_headers,
        ),
        201,
    )
    assert_plan(created)
    assert created["status"] == "PROPOSED", (
        f"a plan is born directly into PROPOSED, got {created['status']}"
    )


def test_verify_after_implementation_sla_stalls_recommendation(
    api, category_advisor_headers
):
    """PRD §3.4: "Second, the elapsed logical time since `accepted_at` must not exceed the 90-day SLA — a verification attempted later is rejected with `ERR_IMPLEMENTATION_STALLED` (HTTP 409), and in the same failed request the recommendation auto-transitions to `STALLED`, terminal, with its `version` incremented; the error and the stall are inseparable."
    PRD §2.10: "A shelf-recommendation verification attempted after its implementation deadline is rejected with `ERR_IMPLEMENTATION_STALLED` — and the recommendation still transitions to `STALLED`, version incremented, inside that same failed request."

    Accepted at logical 2027-01-01 and verified at 2027-04-02 (accepted_at +
    91 days): the SLA check fires before the store-count check, so the error
    surfaces even though 150 stores meets the 100-store target — and the
    failed request still leaves the recommendation STALLED.

    Design: Corner/validations/verify_after_sla_stalls_recommendation
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    rec = create_implementing_shelf_rec(
        plan_id, scenario["retailer"]["id"], accepted_clock="2027-01-01T00:00:00Z"
    )

    set_clock("2027-04-02T00:00:00Z")  # accepted_at + 91 days
    validate_error(
        api.verify_shelf_recommendation(
            rec["id"], create_verify_payload(150), category_advisor_headers
        ),
        ApiErrorId.ERR_IMPLEMENTATION_STALLED,
    )

    recs, _ = validate_paginated(
        api.list_shelf_recommendations(plan_id, category_advisor_headers)
    )
    reloaded = {r["id"]: r for r in recs}[rec["id"]]
    assert reloaded["status"] == "STALLED", (
        f"the stall is inseparable from the error, got {reloaded['status']}"
    )


def test_verify_below_target_store_count_changes_nothing(api, category_advisor_headers):
    """PRD §3.4: "Third, the payload's `implemented_store_count` must be at least the recommendation's `target_store_count` — a within-SLA audit that falls short fails with `ERR_IMPLEMENTATION_INCOMPLETE` (HTTP 422) and changes nothing: the recommendation stays `IMPLEMENTING` for another attempt."

    Verified on the acceptance day itself (well within the 90-day SLA) with 99
    stores against a 100-store target: the audit fails (422) and the
    recommendation stays IMPLEMENTING at the same version.

    Design: Corner/validations/verify_with_insufficient_stores_returns_incomplete
    """
    scenario = setup_activated_plan()
    plan_id = scenario["plan"]["id"]
    rec = create_implementing_shelf_rec(
        plan_id, scenario["retailer"]["id"], accepted_clock="2027-01-01T00:00:00Z"
    )
    # The logical clock still reads the acceptance instant — within the SLA.

    validate_error(
        api.verify_shelf_recommendation(
            rec["id"], create_verify_payload(99), category_advisor_headers
        ),
        ApiErrorId.ERR_IMPLEMENTATION_INCOMPLETE,
    )

    recs, _ = validate_paginated(
        api.list_shelf_recommendations(plan_id, category_advisor_headers)
    )
    reloaded = {r["id"]: r for r in recs}[rec["id"]]
    assert reloaded["status"] == "IMPLEMENTING", (
        f"an incomplete audit changes nothing, got {reloaded['status']}"
    )
    assert reloaded["version"] == rec["version"], (
        f"no mutation means no version bump: {rec['version']} -> {reloaded['version']}"
    )


def test_verify_at_sla_boundary_with_exact_target_succeeds(api, category_advisor_headers):
    """PRD §3.4: "Second, the elapsed logical time since `accepted_at` must not exceed the 90-day SLA — a verification attempted later is rejected with `ERR_IMPLEMENTATION_STALLED` (HTTP 409), and in the same failed request the recommendation auto-transitions to `STALLED`, terminal, with its `version` incremented; the error and the stall are inseparable."
    PRD §3.4: "Third, the payload's `implemented_store_count` must be at least the recommendation's `target_store_count` — a within-SLA audit that falls short fails with `ERR_IMPLEMENTATION_INCOMPLETE` (HTTP 422) and changes nothing: the recommendation stays `IMPLEMENTING` for another attempt."
    PRD §3.4: "A verification that passes all three moves the recommendation to the terminal `VERIFIED`, records the audited count into `verified_store_count`, and increments its `version`."

    Both boundaries are inclusive: at exactly accepted_at + 90 days
    (2027-04-01, which does not exceed the SLA) with exactly the 100-store
    target met, the verify succeeds and lands VERIFIED with
    `verified_store_count` recorded.

    Design: Corner/validations/verify_success_boundary_at_target
    """
    scenario = setup_activated_plan()
    rec = create_implementing_shelf_rec(
        scenario["plan"]["id"],
        scenario["retailer"]["id"],
        accepted_clock="2027-01-01T00:00:00Z",
    )

    set_clock("2027-04-01T00:00:00Z")  # exactly accepted_at + 90 days
    verified = validate_success(
        api.verify_shelf_recommendation(
            rec["id"], create_verify_payload(100), category_advisor_headers
        ),
        200,
    )
    assert_shelf_recommendation(verified)
    assert verified["status"] == "VERIFIED", (
        f"both boundaries inclusive means the audit passes, got {verified['status']}"
    )
    assert verified["verified_store_count"] == 100, (
        f"the audited count is recorded, got {verified['verified_store_count']}"
    )
