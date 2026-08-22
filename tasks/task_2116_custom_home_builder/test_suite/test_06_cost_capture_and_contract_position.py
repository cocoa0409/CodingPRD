"""Capturing cost and reading the contract position on both accounting bases."""

from test_helpers import (
    ApiErrorId,
    assert_cost_entry,
    assert_money_equals,
    assert_project_ledger_invariants,
    post_cost_entry,
    read_contract_position,
    read_cost_entry,
    read_project,
    setup_identical_ledger_pair,
    setup_job,
    setup_submitted_draw,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_fixed_price_position_bills_the_contract_sum(api):
    """PRD §3.5: "Under a `FIXED_PRICE` contract, `variant_applied` reads `FIXED_PRICE`,
    `owner_billable_amount` is simply `contract_sum_current` — the owner owes the contract sum
    regardless of what the build actually cost — and `builder_margin_amount` is
    `contract_sum_current` minus `cost_to_date`, rounded half up to two decimals."
    PRD §3.5: "It also reports `gmp_headroom`, which is the `gmp_cap` minus
    `contract_sum_current` rounded half up to two decimals when a cap exists, and null when the
    project carries no cap."

    Design: Difficulty/dual_variant_calc/contract_position_fixed_price_vs_cost_plus_diverge
    """
    ctx = setup_identical_ledger_pair()

    position = validate_success(
        api.get_contract_position(ctx["fixed_price_project"]["id"], ADMIN), 200
    )

    assert position["variant_applied"] == "FIXED_PRICE"
    assert position["contract_type"] == "FIXED_PRICE"
    assert_money_equals(position["owner_billable_amount"], 900000.00, "owner_billable_amount")
    assert_money_equals(position["builder_margin_amount"], 854999.70, "builder_margin_amount")
    assert_money_equals(position["cost_to_date"], 45000.30, "cost_to_date")
    assert_money_equals(position["contract_sum_current"], 900000.00, "contract_sum_current")
    assert_money_equals(position["gmp_headroom"], 100000.00, "gmp_headroom")


def test_cost_plus_position_bills_actual_cost_plus_the_builder_fee(api):
    """PRD §3.5: "Under a `COST_PLUS` contract, `variant_applied` reads `COST_PLUS`, and the
    billable figure is built from actual cost instead: the server first computes `cost_to_date`
    multiplied by one plus the project's `builder_fee_pct`, rounded half up to two decimals;
    `owner_billable_amount` is then that figure, except that when the project carries a
    `gmp_cap` the billable figure is the lesser of the two — the guaranteed maximum price is a
    genuine ceiling on a cost-plus job."
    PRD §3.5: "`builder_margin_amount` is then `owner_billable_amount` minus `cost_to_date`,
    rounded half up to two decimals."

    Design: Difficulty/dual_variant_calc/contract_position_fixed_price_vs_cost_plus_diverge
    """
    ctx = setup_identical_ledger_pair()

    position = validate_success(
        api.get_contract_position(ctx["cost_plus_project"]["id"], ADMIN), 200
    )

    assert position["variant_applied"] == "COST_PLUS"
    assert position["contract_type"] == "COST_PLUS"
    assert_money_equals(position["owner_billable_amount"], 53100.35, "owner_billable_amount")
    assert_money_equals(position["builder_margin_amount"], 8100.05, "builder_margin_amount")
    assert_money_equals(position["cost_to_date"], 45000.30, "cost_to_date")
    assert_money_equals(position["contract_sum_current"], 900000.00, "contract_sum_current")
    assert_money_equals(position["gmp_headroom"], 100000.00, "gmp_headroom")


def test_cost_approval_lands_in_the_project_ledger_immediately(api):
    """PRD §3.5: "Approving advances the entry `PENDING → APPROVED`, stamps
    `approved_by_staff_id` with the acting controller's identifier and `approved_at` with the
    logical clock now, and recomputes the project's `cost_to_date` and `eligible_cost_pool`
    followed by `budget_posture`."
    PRD §2.6: "`eligible_cost_pool` is the narrower sum over cost entries whose status is
    `APPROVED` or `INCLUDED_IN_DRAW` only — it is the pool of money not yet paid out, and it is
    the quantity the draw machinery conserves."

    Design: Corner/consistency_model/cost_entry_approval_is_reflected_in_the_project_ledger_immediately
    """
    ctx = setup_job(
        with_lender=False, contract_type="COST_PLUS", builder_fee_pct=0.18
    )
    entry = post_cost_entry(ctx, amount=10000.10, incurred_at="2026-08-10T00:00:00.000Z")
    assert_cost_entry(entry)
    assert entry["status"] == "PENDING"

    approved = validate_success(
        api.review_cost_entry(
            entry["id"], {"decision": "APPROVE"}, ctx["controller_a_headers"]
        ),
        200,
    )

    assert approved["status"] == "APPROVED"
    assert approved["approved_by_staff_id"] == ctx["controller_a"]["id"]

    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["cost_to_date"], 10000.10, "cost_to_date")
    assert_money_equals(project["eligible_cost_pool"], 10000.10, "eligible_cost_pool")
    assert_project_ledger_invariants(project)

    position = read_contract_position(ctx["project"]["id"])
    assert position["variant_applied"] == "COST_PLUS"
    assert_money_equals(position["cost_to_date"], 10000.10, "cost_to_date")
    assert_money_equals(position["owner_billable_amount"], 11800.12, "owner_billable_amount")


def test_second_review_of_an_approved_cost_entry_is_refused(api):
    """PRD §3.5: "A review aimed at an entry whose status is not `PENDING` is refused with
    `ERR_COST_ENTRY_INVALID_STATE`."
    PRD §2.6: "`cost_to_date` is the sum of `amount` across the project's cost entries whose
    status is `APPROVED`, `INCLUDED_IN_DRAW`, or `PAID`, rounded half up to two decimal places;
    `PENDING` and `REJECTED` entries never contribute."

    Design: Corner/errors/second_review_of_an_approved_cost_entry_returns_invalid_state
    """
    ctx = setup_job(with_lender=False)
    entry = post_cost_entry(ctx, amount=10000.10, incurred_at="2026-08-10T00:00:00.000Z")
    validate_success(
        api.review_cost_entry(
            entry["id"], {"decision": "APPROVE"}, ctx["controller_a_headers"]
        ),
        200,
    )

    response = api.review_cost_entry(
        entry["id"], {"decision": "APPROVE"}, ctx["controller_a_headers"]
    )
    validate_error(response, ApiErrorId.ERR_COST_ENTRY_INVALID_STATE, 409)

    assert read_cost_entry(entry["id"])["status"] == "APPROVED"
    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["cost_to_date"], 10000.10, "cost_to_date")
    assert_money_equals(project["eligible_cost_pool"], 10000.10, "eligible_cost_pool")


def test_cost_entries_can_be_filtered_by_the_draw_that_holds_them(api):
    """PRD §3.5: "Cost entries can be read individually and listed with filters on
    `project_id`, `subcontractor_id`, `source_allowance_item_id`, `draw_request_id`,
    `approved_by_staff_id`, and `status`."
    PRD §3.5: "When a draw is submitted, each eligible entry advances `APPROVED →
    INCLUDED_IN_DRAW` and has its `draw_request_id` pointed at that draw; `eligible_cost_pool`
    does not move, because both statuses count toward it."

    Design: Corner/endpoints/cost_entries_filtered_by_draw_request_id_returns_only_that_draw
    """
    ctx = setup_submitted_draw(
        lines=[
            {"amount": 10000.10, "incurred_at": "2026-08-10T00:00:00.000Z"},
            {"amount": 20000.10, "incurred_at": "2026-08-31T00:00:00.000Z"},
            {"amount": 15000.10, "incurred_at": "2026-09-05T00:00:00.000Z"},
        ],
        frame_waiver_required=False,
    )
    inside_one, inside_two, outside = ctx["cost_entries"]

    rows, meta = validate_paginated(
        api.list_cost_entries(
            ctx["controller_b_headers"],
            params={"draw_request_id": ctx["draw"]["id"], "limit": 100},
        )
    )

    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert {row["id"] for row in rows} == {inside_one["id"], inside_two["id"]}
    assert read_cost_entry(outside["id"])["draw_request_id"] is None
