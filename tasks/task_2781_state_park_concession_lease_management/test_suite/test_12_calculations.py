"""Computed-figure coverage: the bond requirement, the marginal annual ladder,
the sufficiency floor and straight-line amortization."""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
    assert_status,
)

LEASE_YEAR_ONE = {"lease_year_start": "2027-03-01", "lease_year_end": "2028-02-29"}
APRIL = {"period_start": "2027-04-01", "period_end": "2027-05-01"}
MAY = {"period_start": "2027-05-01", "period_end": "2027-06-01"}


def _receipts(lodging, food, retail, activity):
    return {
        "lodging_receipts_cents": lodging,
        "food_beverage_receipts_cents": food,
        "retail_receipts_cents": retail,
        "activity_receipts_cents": activity,
    }


def _reconcile(api, lease_id, **overrides):
    payload = F.reconciliation_payload(
        lease_id, X.lease_version(api, lease_id), **dict(LEASE_YEAR_ONE, **overrides)
    )
    return api.create_reconciliation(payload, X.exec_officer_headers())


def test_required_bond_amount_applies_the_long_term_multiplier_above_ten_years(api):
    """PRD §3.5: "Take one quarter of the lease's `minimum_annual_guarantee_cents`, rounded half up to whole cents; take one tenth of the lease's `capital_investment_obligation_cents`, also rounded half up to whole cents; then take whichever is greatest of those two rounded components and a hard floor of twenty-five thousand dollars."
    PRD §3.5: "For a term strictly longer than ten years the requirement is that value multiplied by one and a half, rounded half up to whole cents a second time."
    PRD §3.5: "What it must eventually be worth is decided at award and stored twice: as `required_bond_amount_cents` on the lease and, copied from it, as `required_amount_cents` on the bond."
    PRD §3.4: "`term_end` is obtained by adding the whole number of `term_years` to `term_start` and then subtracting one day — a ten-year term starting 2027-03-01 therefore ends 2037-02-28."

    Design: Corner/calculations/required_bond_amount_applies_the_long_term_multiplier_above_ten_years
    """
    ctx = X.setup_scored_proposal(api, prospectus={"term_years": 15})
    X.set_clock(api, X.POST_DEADLINE_CLOCK)
    X.close_prospectus(api, ctx["prospectus_id"])

    response = api.award_prospectus(
        ctx["prospectus_id"], F.award_payload("2027-03-01"), X.award_officer_headers()
    )
    validate_success(response, 201)
    lease = get_success_data(response)
    assert_fields(lease, {"term_years": 15, "term_start": "2027-03-01", "term_end": "2042-02-28"})
    assert_cents_equals(
        lease["required_bond_amount_cents"], 4500000, "required_bond_amount_cents"
    )

    bond = get_success_data(
        api.get_bond(lease["performance_bond_id"], X.award_officer_headers())
    )
    assert_cents_equals(bond["required_amount_cents"], 4500000, "required_amount_cents")
    assert_status(bond, "PENDING")


def test_a_rejected_report_is_excluded_from_the_lease_year_input_set(api):
    """PRD §3.8: "The period set is every gross receipts report on this lease whose status is `ACCEPTED` or `RESTATED` and whose period lies inside the year — `period_start` at or after `lease_year_start`, and `period_end` no later than the day after `lease_year_end` — taken in order of `period_start` ascending and, for ties, `created_at` ascending."
    PRD §3.8: "Reports still `SUBMITTED`, and reports that were `REJECTED`, contribute nothing at all — so a month the agency rejected and the concessionaire never amended silently lowers the year's receipts."
    PRD §3.8: "Concretely: the first slice is the lesser of the annual total and five hundred thousand dollars; the second slice is the lesser of the annual total and one and a half million dollars, minus five hundred thousand dollars, floored at zero; the third slice is the annual total minus one and a half million dollars, floored at zero."
    PRD §3.8: "`annual_fee_due_cents` is whichever is greater, the tiered fee or `mag_applied_cents`."
    PRD §3.8: "`base_delta_cents` is `annual_fee_due_cents` less `remitted_total_cents`, and a negative value means the concessionaire overpaid across the year."
    PRD §3.8: "On a reconciliation the officer creates directly, `penalty_cents` and `interest_cents` are both zero; `additional_fee_due_cents` is `base_delta_cents` plus `penalty_cents` plus `interest_cents`."
    PRD §3.8: "`due_date` is thirty days after `lease_year_end`."
    PRD §3.8: "`lease_year_number` is recorded as the one-based index of that year within the term, derived from `lease_year_start` and the lease's `term_start`."

    Design: Corner/calculations/rejected_report_is_excluded_from_the_annual_reconciliation_input_set
    """
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    accepted = X.file_report(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        **dict(APRIL, **_receipts(30000000, 60000000, 24000000, 6000000)),
    )
    assert_cents_equals(accepted["assessed_fee_cents"], 6450000, "assessed_fee_cents")
    X.accept_report(api, accepted["id"], 6450000)

    rejected = X.file_report(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        **dict(MAY, **_receipts(7500000, 15000000, 6000000, 1500000)),
    )
    assert_cents_equals(rejected["total_receipts_cents"], 30000000, "total_receipts_cents")
    rejected = get_success_data(
        api.reject_report(rejected["id"], F.reject_report_payload(), X.exec_officer_headers())
    )
    assert_status(rejected, "REJECTED")

    X.set_clock(api, "2028-03-05T00:00:00Z")
    response = _reconcile(api, ctx["lease_id"])
    validate_success(response, 201)
    recon = get_success_data(response)
    assert recon["lease_year_number"] == 1, recon["lease_year_number"]
    assert_cents_equals(
        recon["annual_gross_receipts_cents"], 120000000, "annual_gross_receipts_cents"
    )
    assert_cents_equals(recon["annual_fee_due_cents"], 7750000, "annual_fee_due_cents")
    assert_cents_equals(recon["mag_applied_cents"], 6000000, "mag_applied_cents")
    assert_cents_equals(recon["remitted_total_cents"], 6450000, "remitted_total_cents")
    assert_cents_equals(recon["base_delta_cents"], 1300000, "base_delta_cents")
    assert_cents_equals(recon["penalty_cents"], 0, "penalty_cents")
    assert_cents_equals(recon["interest_cents"], 0, "interest_cents")
    assert_cents_equals(
        recon["additional_fee_due_cents"], 1300000, "additional_fee_due_cents"
    )
    assert recon["due_date"] == "2028-03-30", recon["due_date"]
    assert_status(recon, "PENDING_PAYMENT")

    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 1300000, "outstanding_fee_balance_cents"
    )


def test_a_draw_landing_exactly_on_the_sufficiency_floor_leaves_the_bond_partially_drawn(api):
    """PRD §3.9: "**Hop two** moves the money on the bond: `available_balance_cents` falls by the drawn amount and `drawn_total_cents` rises by the same amount, while `penal_sum_cents` never changes — the penal sum is the face value of the instrument, not a running balance."
    PRD §3.9: "Where the bond lands depends on a sufficiency floor: half of `required_amount_cents`, rounded half up to whole cents."
    PRD §3.9: "If the remaining `available_balance_cents` is at or above that floor the bond lands in `PARTIALLY_DRAWN`, and the agency's security is still adequate; if it falls strictly below the floor the bond lands in `INSUFFICIENT`."
    PRD §3.9: "**Hop three** fires only on `INSUFFICIENT`: the lease's `compliance_status` moves `DEFICIENT → DEFAULT` and, at the same time, its `contract_status` moves from `ACTIVE` or `HOLDOVER` to `TERMINATED_DEFAULT`."

    Design: Corner/calculations/bond_sufficiency_floor_is_fifty_percent_of_the_required_amount
    """
    ctx = X.setup_active_lease(api)
    action = X.issue_compliance_action(
        api,
        ctx["lease_id"],
        action_type="OPERATING_STANDARD",
        deficiency_note="Housekeeping standard not met on the spring inspection.",
        cure_deadline="2027-03-04T00:00:00Z",
    )
    X.set_clock(api, "2027-03-05T00:00:00Z")

    response = api.order_bond_draw(
        action["id"], F.order_bond_draw_payload(1500000), X.exec_officer_headers()
    )
    validate_success(response, 200)
    ordered = get_success_data(response)
    assert_status(ordered, "BOND_DRAW_ORDERED")
    assert_cents_equals(ordered["draw_amount_cents"], 1500000, "draw_amount_cents")

    bond = get_success_data(api.get_bond(ctx["bond_id"], X.award_officer_headers()))
    assert_status(bond, "PARTIALLY_DRAWN")
    assert_cents_equals(bond["available_balance_cents"], 1500000, "available_balance_cents")
    assert_cents_equals(bond["drawn_total_cents"], 1500000, "drawn_total_cents")
    assert_cents_equals(bond["penal_sum_cents"], 3000000, "penal_sum_cents")

    assert_lease_state(
        X.read_lease(api, ctx["lease_id"]),
        contract_status="ACTIVE",
        compliance_status="DEFICIENT",
    )


def test_the_annual_ladder_prices_all_three_marginal_slices(api):
    """PRD §3.8: "The first five hundred thousand dollars of annual receipts pay the lease's `base_fee_pct`."
    PRD §3.8: "Receipts above five hundred thousand dollars and up to one and a half million dollars pay `base_fee_pct` plus two and a half percentage points."
    PRD §3.8: "Receipts above one and a half million dollars pay `base_fee_pct` plus five percentage points."
    PRD §3.8: "Concretely: the first slice is the lesser of the annual total and five hundred thousand dollars; the second slice is the lesser of the annual total and one and a half million dollars, minus five hundred thousand dollars, floored at zero; the third slice is the annual total minus one and a half million dollars, floored at zero."
    PRD §3.8: "Each slice is multiplied by its own rate, divided by one hundred and rounded half up to whole cents *independently*, and the tiered fee is the sum of the three rounded slice fees."
    PRD §3.8: "`mag_applied_cents` is the lease's full `minimum_annual_guarantee_cents` when the requested window is exactly the lease year window that the term arithmetic of §3.4 produces; when a shorter window is reconciled, the guarantee is prorated — the full guarantee multiplied by the inclusive number of days from `lease_year_start` through `lease_year_end` and divided by three hundred and sixty-five, rounded half up to whole cents."

    Design: Corner/calculations/annual_ladder_prices_all_three_marginal_slices_in_one_lease_year
    """
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    report = X.file_report(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        **dict(APRIL, **_receipts(50000000, 100000000, 40000000, 10000000)),
    )
    assert_cents_equals(report["total_receipts_cents"], 200000000, "total_receipts_cents")
    assert_cents_equals(report["assessed_fee_cents"], 10750000, "assessed_fee_cents")
    X.accept_report(api, report["id"], 10750000)

    X.set_clock(api, "2028-03-05T00:00:00Z")
    response = _reconcile(api, ctx["lease_id"])
    validate_success(response, 201)
    recon = get_success_data(response)
    assert_cents_equals(
        recon["annual_gross_receipts_cents"], 200000000, "annual_gross_receipts_cents"
    )
    assert_cents_equals(recon["mag_applied_cents"], 6000000, "mag_applied_cents")
    assert_cents_equals(recon["annual_fee_due_cents"], 15000000, "annual_fee_due_cents")
    assert_cents_equals(recon["remitted_total_cents"], 10750000, "remitted_total_cents")
    assert_cents_equals(recon["base_delta_cents"], 4250000, "base_delta_cents")
    assert_cents_equals(
        recon["additional_fee_due_cents"], 4250000, "additional_fee_due_cents"
    )
    assert_status(recon, "PENDING_PAYMENT")


def test_reports_filed_out_of_period_order_reconcile_to_the_same_annual_total(api):
    """PRD §3.8: "The period set is every gross receipts report on this lease whose status is `ACCEPTED` or `RESTATED` and whose period lies inside the year — `period_start` at or after `lease_year_start`, and `period_end` no later than the day after `lease_year_end` — taken in order of `period_start` ascending and, for ties, `created_at` ascending."
    PRD §3.8: "Each report contributes its `restated_receipts_cents` if it is `RESTATED` and its `total_receipts_cents` otherwise, and the sum is `annual_gross_receipts_cents`."
    PRD §3.8: "What was actually paid is `remitted_total_cents`, the sum of `remittance_received_cents` over that same period set."
    PRD §3.8: "`due_date` is thirty days after `lease_year_end`."
    PRD §3.8: "And the period must not intersect another report on the same lease whose status is `SUBMITTED`, `ACCEPTED` or `RESTATED`, else `ERR_REPORT_PERIOD_OVERLAP`; because reporting periods are half-open, a period ending 2027-07-01 and a period starting 2027-07-01 are adjacent rather than overlapping and both may stand."

    Design: Corner/calculations/reports_filed_out_of_period_order_reconcile_to_the_same_annual_total
    """
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    half_year_receipts = _receipts(15000000, 30000000, 12000000, 3000000)
    later = X.file_report(api, ctx["lease_id"], ctx["offeror_id"], **dict(MAY, **half_year_receipts))
    assert_cents_equals(later["assessed_fee_cents"], 3225000, "assessed_fee_cents")
    X.accept_report(api, later["id"], 3225000)
    earlier = X.file_report(
        api, ctx["lease_id"], ctx["offeror_id"], **dict(APRIL, **half_year_receipts)
    )
    X.accept_report(api, earlier["id"], 3225000)

    X.set_clock(api, "2028-03-05T00:00:00Z")
    response = _reconcile(api, ctx["lease_id"])
    validate_success(response, 201)
    recon = get_success_data(response)
    assert recon["lease_year_number"] == 1, recon["lease_year_number"]
    assert_cents_equals(
        recon["annual_gross_receipts_cents"], 120000000, "annual_gross_receipts_cents"
    )
    assert_cents_equals(recon["annual_fee_due_cents"], 7750000, "annual_fee_due_cents")
    assert_cents_equals(recon["remitted_total_cents"], 6450000, "remitted_total_cents")
    assert_cents_equals(recon["base_delta_cents"], 1300000, "base_delta_cents")
    assert_cents_equals(
        recon["additional_fee_due_cents"], 1300000, "additional_fee_due_cents"
    )
    assert recon["due_date"] == "2028-03-30", recon["due_date"]


def test_amortization_counts_the_in_service_month_as_a_whole_elapsed_month(api):
    """PRD §3.9: "The useful life in months is `useful_life_years` multiplied by twelve."
    PRD §3.9: "The months elapsed are counted from the improvement's `in_service_date` to the lease's `term_end`: twelve times the difference in calendar years, plus the difference in calendar months, plus one — the plus one makes the in-service month itself count as elapsed, so a partial month at either end counts as a whole month."
    PRD §3.9: "The amortized amount is `approved_cost_cents` multiplied by the clamped month count, divided by the useful life in months, rounded half up to whole cents; `unamortized_value_cents` is `approved_cost_cents` less that amortized amount, floored at zero."
    PRD §3.9: "The base is always `approved_cost_cents` — the figure the agency authorized — and never `actual_cost_cents`, even when the concessionaire spent more."
    PRD §3.9: "Each capital improvement in `COMPLETED` has its `unamortized_value_cents` computed and then moves to `VESTED_IN_AGENCY` if its `ownership_at_expiration` is `AGENCY` or to `COMPENSABLE` if it is `CONCESSIONAIRE`."
    PRD §3.9: "Finally the lease's `possessory_interest_value_cents` is frozen as the sum of `unamortized_value_cents` over its `COMPENSABLE` improvements only, and the lease's `version` advances by one along with every row the cascade touched."
    PRD §3.7: "On success both fields are persisted, the park's `open_closure_window_count` falls by one because the site has reopened, and the lease's `capital_investment_completed_cents` rises by the lesser of `actual_cost_cents` and `approved_cost_cents`."

    Design: Corner/calculations/amortization_counts_the_in_service_month_as_a_whole_elapsed_month
    """
    ctx = X.setup_active_lease(api)
    improvement = X.propose_improvement(
        api,
        ctx["lease_id"],
        ctx["offeror_id"],
        description="Cabin cluster rebuild",
        funding_source="CONCESSIONAIRE_CAPITAL",
        proposed_cost_cents=6000000,
        useful_life_years=20,
        construction_window_start="2027-04-01",
        construction_window_end="2027-06-01",
        ownership_at_expiration="CONCESSIONAIRE",
    )
    X.approve_improvement(api, improvement["id"], 6000000)
    X.place_improvement_in_service(
        api,
        improvement["id"],
        ctx["offeror_id"],
        actual_cost_cents=6500000,
        in_service_date="2027-06-01",
    )
    X.set_clock(api, "2037-03-01T00:00:00Z")

    response = api.expire_lease(ctx["lease_id"], X.exec_officer_headers())
    validate_success(response, 200)
    lease = get_success_data(response)
    assert_status(lease, "EXPIRED", "contract_status")
    assert_cents_equals(
        lease["capital_investment_completed_cents"], 6000000, "capital_investment_completed_cents"
    )
    assert_cents_equals(
        lease["possessory_interest_value_cents"], 3075000, "possessory_interest_value_cents"
    )

    stored = get_success_data(
        api.get_improvement(improvement["id"], X.award_officer_headers())
    )
    assert_status(stored, "COMPENSABLE")
    assert_cents_equals(stored["unamortized_value_cents"], 3075000, "unamortized_value_cents")

    park = get_success_data(api.get_park(ctx["park_id"], X.award_officer_headers()))
    assert park["open_closure_window_count"] == 0, park["open_closure_window_count"]
