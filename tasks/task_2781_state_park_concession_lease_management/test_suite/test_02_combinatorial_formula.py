"""Multi-term formulas whose rounding and step order are pinned: the period
franchise fee and the close-out settlement waterfall."""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_lease_state,
    assert_null,
    assert_status,
)

PINNED_RECEIPTS = {
    "lodging_receipts_cents": 12345760,
    "food_beverage_receipts_cents": 3333328,
    "retail_receipts_cents": 2222120,
    "activity_receipts_cents": 1111120,
}


def _lease_ready_to_report(api):
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-05-02T00:00:00Z")
    return ctx


def test_period_fee_rounds_each_category_before_summing(api):
    """PRD §3.8: "**The evaluation order is pinned**: for each of the four categories, multiply that category's receipts by that category's rate, divide by one hundred, and round half up to whole cents; then add the four rounded category fees together in the order lodging, food and beverage, retail, activities."
    PRD §3.8: "Summing the four raw products and rounding once at the end is wrong and can differ from the correct answer by a cent or two."
    PRD §3.8: "`total_receipts_cents` is simply the four category amounts added together."

    Design: Difficulty/combinatorial_formula/period_fee_rounds_each_category_before_summing
    """
    ctx = _lease_ready_to_report(api)

    response = api.create_report(
        F.report_payload(
            ctx["lease_id"],
            period_start="2027-04-01",
            period_end="2027-05-01",
            **PINNED_RECEIPTS,
        ),
        ctx["offeror_headers"],
    )
    validate_success(response, 201)
    report = get_success_data(response)

    assert_cents_equals(report["total_receipts_cents"], 19012328, "total_receipts_cents")
    # 802474 + 166666 + 99995 + 77778, each rounded before the sum.
    assert_cents_equals(report["assessed_fee_cents"], 1146913, "assessed_fee_cents")
    assert report["assessed_fee_cents"] != 1146915, (
        "assessed_fee_cents was computed by rounding the summed raw products once"
    )


def test_period_report_accrues_reserve_and_leaves_the_lease_ledger_alone(api):
    """PRD §3.8: "`maintenance_reserve_due_cents` is one half of one percent of `total_receipts_cents`, rounded half up to whole cents."
    PRD §3.8: "Exactly one `APPROVED` operating plan on the same lease must have a closed season window `season_start` through `season_end` that covers every calendar day of the half-open reporting period; that plan's identifier is written onto the report as `operating_plan_id`, and if no approved season covers the period the filing is refused with `ERR_NO_APPROVED_OPERATING_PLAN`."
    PRD §3.8: "On success the remittance is persisted and three lease ledger fields move at once — `reported_receipts_ytd_cents` rises by the report's `total_receipts_cents`, `remitted_fee_ytd_cents` rises by the logged remittance, and `maintenance_reserve_balance_cents` rises by `maintenance_reserve_due_cents` — with the report and the lease each advancing their `version` by one."

    Design: Difficulty/combinatorial_formula/period_fee_rounds_each_category_before_summing
    """
    ctx = _lease_ready_to_report(api)

    report = X.file_report(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        period_start="2027-04-01",
        period_end="2027-05-01",
        **PINNED_RECEIPTS,
    )

    # 19,012,328 x 0.50 / 100 = 95,061.64 -> 95,062.
    assert_cents_equals(
        report["maintenance_reserve_due_cents"], 95062, "maintenance_reserve_due_cents"
    )
    assert report["operating_plan_id"] == ctx["plan_id"]
    assert_status(report, "SUBMITTED")
    assert_null(report, "remittance_received_cents")

    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(lease["remitted_fee_ytd_cents"], 0, "remitted_fee_ytd_cents")
    assert_cents_equals(
        lease["maintenance_reserve_balance_cents"], 0, "maintenance_reserve_balance_cents"
    )


def _expired_lease_with_compensable_improvement(api):
    """An expired lease carrying one COMPENSABLE improvement worth 15,375,000
    and an unpaid reconciliation of 1,300,000."""
    ctx = X.setup_lease_with_season(api)

    X.set_clock(api, "2027-03-02T00:00:00Z")
    improvement = X.propose_improvement(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        description="Lodge guest-wing rebuild",
        funding_source="CONCESSIONAIRE_CAPITAL",
        proposed_cost_cents=30000000,
        useful_life_years=20,
        construction_window_start="2027-04-01",
        construction_window_end="2027-06-16",
        ownership_at_expiration="CONCESSIONAIRE",
    )
    X.approve_improvement(api, improvement["id"], 30000000)
    X.set_clock(api, "2027-06-20T00:00:00Z")
    X.place_improvement_in_service(
        api,
        improvement["id"],
        ctx["offeror_id"],
        actual_cost_cents=30000000,
        in_service_date="2027-06-15",
    )

    X.set_clock(api, "2027-07-02T00:00:00Z")
    for period in (
        {"period_start": "2027-04-01", "period_end": "2027-05-01"},
        {"period_start": "2027-05-01", "period_end": "2027-06-01"},
        {"period_start": "2027-06-01", "period_end": "2027-07-01"},
    ):
        report = X.file_report(
            api,
            ctx["lease_id"],
            ctx["offeror_id"],
            lodging_receipts_cents=10000000,
            food_beverage_receipts_cents=20000000,
            retail_receipts_cents=8000000,
            activity_receipts_cents=2000000,
            **period,
        )
        X.accept_report(api, report["id"], 2150000)

    X.set_clock(api, "2028-03-05T00:00:00Z")
    recon = X.create_reconciliation(
        api, ctx["lease_id"], lease_year_start="2027-03-01", lease_year_end="2028-02-29"
    )

    X.set_clock(api, "2037-03-01T00:00:00Z")
    lease = get_success_data(
        api.expire_lease(ctx["lease_id"], X.exec_officer_headers())
    )
    ctx.update({"improvement_id": improvement["id"], "recon_id": recon["id"], "lease": lease})
    return ctx


def test_close_out_charges_the_admin_fee_on_the_gross_possessory_interest(api):
    """PRD §3.9: "Step two: the administrative fee is three percent of that gross figure, rounded half up to whole cents."
    PRD §3.9: "Step three: the raw net is the gross figure less the administrative fee less the lease's `outstanding_fee_balance_cents`."
    PRD §3.9: "Step four: `transfer_settlement_net_cents` is the raw net when it is positive and zero otherwise, while `transfer_settlement_deficiency_cents` is the raw net negated when the raw net is negative and zero otherwise."

    Design: Difficulty/combinatorial_formula/transfer_settlement_charges_admin_fee_on_gross_before_offsets
    """
    ctx = _expired_lease_with_compensable_improvement(api)

    response = api.close_out_lease(ctx["lease_id"], X.exec_officer_headers())
    validate_success(response, 200)
    lease = get_success_data(response)

    assert_cents_equals(
        lease["possessory_interest_value_cents"], 15375000, "possessory_interest_value_cents"
    )
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 1300000, "outstanding_fee_balance_cents"
    )
    # 15,375,000 - 461,250 - 1,300,000; the fee is 3% of the gross, not of the net.
    assert_cents_equals(
        lease["transfer_settlement_net_cents"], 13613750, "transfer_settlement_net_cents"
    )
    assert lease["transfer_settlement_net_cents"] != 13652750, (
        "the administrative fee was charged on the net rather than the gross figure"
    )
    assert_cents_equals(
        lease["transfer_settlement_deficiency_cents"],
        0,
        "transfer_settlement_deficiency_cents",
    )


def test_close_out_leaves_the_bond_and_the_unpaid_invoice_where_they_are(api):
    """PRD §3.9: "The lease then moves `EXPIRED → CLOSED_OUT`, which along with `TERMINATED_DEFAULT` is a terminal `contract_status`: nothing further can be filed, reconciled or audited against it."
    PRD §3.9: "The bond moves `ACTIVE → RELEASED` only when the lease's `outstanding_fee_balance_cents` is zero; when money is still owed the bond keeps whatever status it has, and the close-out proceeds regardless."
    PRD §3.9: "Each operating plan in `SUBMITTED`, `RETURNED` or `APPROVED` moves to `SUPERSEDED`."

    Design: Difficulty/combinatorial_formula/transfer_settlement_charges_admin_fee_on_gross_before_offsets
    """
    ctx = _expired_lease_with_compensable_improvement(api)

    lease = get_success_data(
        api.close_out_lease(ctx["lease_id"], X.exec_officer_headers())
    )
    assert_lease_state(lease, contract_status="CLOSED_OUT")
    assert_null(lease, "predecessor_lease_id")

    improvement = get_success_data(
        api.get_improvement(ctx["improvement_id"], X.award_officer_headers())
    )
    assert_status(improvement, "COMPENSABLE")
    assert_cents_equals(
        improvement["unamortized_value_cents"], 15375000, "unamortized_value_cents"
    )

    bond = get_success_data(api.get_bond(ctx["bond_id"], X.award_officer_headers()))
    assert_status(bond, "ACTIVE")

    recon = get_success_data(
        api.get_reconciliation(ctx["recon_id"], X.award_officer_headers())
    )
    assert_status(recon, "PENDING_PAYMENT")

    plan = get_success_data(
        api.get_operating_plan(ctx["plan_id"], X.award_officer_headers())
    )
    assert_status(plan, "SUPERSEDED")
