"""Two-variant calculations: the annual tier ladder against the period
remittance sum, and the two composite-score rounding disciplines."""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
    assert_pct_equals,
    assert_status,
)
from test_helpers.test_users import (
    PANELIST_ONE_USER_ID,
    PANELIST_TWO_USER_ID,
    concessionaire_headers,
    specialist_headers,
)

QUARTER_PERIODS = [
    {"period_start": "2027-04-01", "period_end": "2027-05-01"},
    {"period_start": "2027-05-01", "period_end": "2027-06-01"},
    {"period_start": "2027-06-01", "period_end": "2027-07-01"},
]
MONTHLY_RECEIPTS = {
    "lodging_receipts_cents": 10000000,
    "food_beverage_receipts_cents": 20000000,
    "retail_receipts_cents": 8000000,
    "activity_receipts_cents": 2000000,
}
PANEL_SCORES_ONE = X.PANEL_SCORES_ONE
PANEL_SCORES_TWO = X.PANEL_SCORES_TWO


def _lease_year_with_three_accepted_months(api):
    """ACTIVE lease, approved season, three accepted monthly reports of
    40,000,000 each remitted at their own assessed fee of 2,150,000."""
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    reports = []
    for period in QUARTER_PERIODS:
        report = X.file_report(
            api, ctx["lease_id"], ctx["offeror_id"], **dict(period, **MONTHLY_RECEIPTS)
        )
        X.accept_report(api, report["id"], 2150000)
        reports.append(report)
    ctx["reports"] = reports
    X.set_clock(api, "2028-03-05T00:00:00Z")
    return ctx


def test_annual_reconciliation_prices_the_year_on_the_marginal_tier_ladder(api):
    """PRD §3.8: "That annual total is then priced on a marginal tier ladder that ignores the per-category differentials entirely."
    PRD §3.8: "The first five hundred thousand dollars of annual receipts pay the lease's `base_fee_pct`."
    PRD §3.8: "Receipts above five hundred thousand dollars and up to one and a half million dollars pay `base_fee_pct` plus two and a half percentage points."
    PRD §3.8: "`annual_fee_due_cents` is whichever is greater, the tiered fee or `mag_applied_cents`."

    Design: Difficulty/dual_variant_calc/annual_tiered_ladder_diverges_from_period_remittance_sum
    """
    ctx = _lease_year_with_three_accepted_months(api)

    response = api.create_reconciliation(
        F.reconciliation_payload(
            ctx["lease_id"],
            X.lease_version(api, ctx["lease_id"]),
            lease_year_start="2027-03-01",
            lease_year_end="2028-02-29",
        ),
        X.award_officer_headers(),
    )
    validate_success(response, 201)
    recon = get_success_data(response)

    assert recon["lease_year_number"] == 1
    assert_cents_equals(
        recon["annual_gross_receipts_cents"], 120000000, "annual_gross_receipts_cents"
    )
    # 50,000,000 at 5.00 = 2,500,000 plus 70,000,000 at 7.50 = 5,250,000.
    assert_cents_equals(recon["annual_fee_due_cents"], 7750000, "annual_fee_due_cents")
    assert_cents_equals(recon["mag_applied_cents"], 6000000, "mag_applied_cents")
    assert_cents_equals(recon["penalty_cents"], 0, "penalty_cents")
    assert_cents_equals(recon["interest_cents"], 0, "interest_cents")


def test_annual_reconciliation_invoices_the_gap_against_period_remittances(api):
    """PRD §3.8: "What was actually paid is `remitted_total_cents`, the sum of `remittance_received_cents` over that same period set."
    PRD §3.8: "`base_delta_cents` is `annual_fee_due_cents` less `remitted_total_cents`, and a negative value means the concessionaire overpaid across the year."
    PRD §3.8: "On a reconciliation the officer creates directly, `penalty_cents` and `interest_cents` are both zero; `additional_fee_due_cents` is `base_delta_cents` plus `penalty_cents` plus `interest_cents`."
    PRD §3.8: "`due_date` is thirty days after `lease_year_end`."
    PRD §3.8: "The row is created in `PENDING_PAYMENT` when `additional_fee_due_cents` is strictly positive and directly in `CREDIT_ISSUED` otherwise — the agency does not invoice a credit, it records one."

    Design: Difficulty/dual_variant_calc/annual_tiered_ladder_diverges_from_period_remittance_sum
    """
    ctx = _lease_year_with_three_accepted_months(api)
    assert_cents_equals(
        ctx["reports"][0]["assessed_fee_cents"], 2150000, "period assessed_fee_cents"
    )

    recon = X.create_reconciliation(
        api,
        ctx["lease_id"],
        lease_year_start="2027-03-01",
        lease_year_end="2028-02-29",
    )

    # The period basis totals 3 x 2,150,000; the annual ladder wants 7,750,000.
    assert_cents_equals(recon["remitted_total_cents"], 6450000, "remitted_total_cents")
    assert_cents_equals(recon["base_delta_cents"], 1300000, "base_delta_cents")
    assert_cents_equals(
        recon["additional_fee_due_cents"], 1300000, "additional_fee_due_cents"
    )
    assert recon["due_date"] == "2028-03-30", recon["due_date"]
    assert_status(recon, "PENDING_PAYMENT")

    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 1300000, "outstanding_fee_balance_cents"
    )
    assert_lease_state(lease, contract_status="ACTIVE")


def _twin_prospectus_proposals(api):
    """One park carrying two solicitations that differ only in `scoring_mode`,
    each with one proposal holding one identical score sheet."""
    X.set_clock(api, X.BOOTSTRAP_CLOCK)
    park = X.register_park(api)
    offeror = X.register_offeror(api)
    holder = concessionaire_headers(offeror["id"])

    def solicitation(scoring_mode, service_category, title_suffix):
        opportunity = X.approved_opportunity(
            api,
            park["id"],
            title=f"Cedar Hollow {title_suffix} Concession",
            service_category=service_category,
        )
        prospectus = X.draft_prospectus(
            api, opportunity["id"], scoring_mode=scoring_mode
        )
        return X.issue_prospectus(api, prospectus["id"])

    pros_a = solicitation("PER_CRITERION_ROUNDING", "LODGING", "Lodge")
    pros_b = solicitation("FINAL_ROUNDING", "MARINA", "Marina")

    prop_a = X.submit_proposal(api, pros_a["id"], offeror["id"])
    prop_b = X.submit_proposal(api, pros_b["id"], offeror["id"])
    for proposal_id in (prop_a["id"], prop_b["id"]):
        X.begin_review(api, proposal_id)
        X.file_evaluation(api, proposal_id, PANELIST_ONE_USER_ID, **PANEL_SCORES_ONE)
    return {
        "offeror_id": offeror["id"],
        "holder": holder,
        "prop_a_id": prop_a["id"],
        "prop_b_id": prop_b["id"],
    }


def test_per_criterion_rounding_composite_rounds_each_contribution(api):
    """PRD §3.4: "Under `PER_CRITERION_ROUNDING`, each criterion's raw mean is first rounded half up to two decimal places, then multiplied by that criterion's weight and divided by one hundred, and that product is itself rounded half up to two decimal places; `composite_score` is the exact sum of the five resulting two-decimal contributions."
    PRD §3.4: "The panel is complete at two sheets, and the second sheet is the one that scores the proposal: `composite_score` is computed and the proposal moves `UNDER_REVIEW → SCORED` in the same request."

    Design: Difficulty/dual_variant_calc/composite_score_rounding_location_shifts_evaluation_result
    """
    ctx = _twin_prospectus_proposals(api)

    response = api.file_evaluation(
        ctx["prop_a_id"],
        F.evaluation_payload(**PANEL_SCORES_TWO),
        X.panelist_headers(PANELIST_TWO_USER_ID),
    )
    validate_success(response, 201)

    proposal = get_success_data(api.get_proposal(ctx["prop_a_id"], specialist_headers()))
    assert proposal["evaluation_count"] == 2
    assert_status(proposal, "SCORED")
    # 16.30 + 21.38 + 18.10 + 11.33 + 14.10
    assert_pct_equals(proposal["composite_score"], "81.21", "composite_score")


def test_final_rounding_composite_rounds_only_the_total(api):
    """PRD §3.4: "Identical score sheets on two prospectuses that differ only in `scoring_mode` can therefore produce composites one hundredth of a point apart, and that is intended, not a defect."
    PRD §3.2: "`scoring_mode` selects which of the two composite-score variants will be applied to every proposal on this solicitation and is either `PER_CRITERION_ROUNDING` or `FINAL_ROUNDING`; the choice is made once, at drafting time, and cannot be revisited."

    Design: Difficulty/dual_variant_calc/composite_score_rounding_location_shifts_evaluation_result
    """
    ctx = _twin_prospectus_proposals(api)

    for proposal_id in (ctx["prop_a_id"], ctx["prop_b_id"]):
        response = api.file_evaluation(
            proposal_id,
            F.evaluation_payload(**PANEL_SCORES_TWO),
            X.panelist_headers(PANELIST_TWO_USER_ID),
        )
        validate_success(response, 201)

    per_criterion = get_success_data(
        api.get_proposal(ctx["prop_a_id"], specialist_headers())
    )
    final_rounding = get_success_data(
        api.get_proposal(ctx["prop_b_id"], specialist_headers())
    )

    assert_fields(final_rounding, {"evaluation_count": 2})
    assert_status(final_rounding, "SCORED")
    # 16.30 + 21.375 + 18.10 + 11.325 + 14.10 = 81.20 exactly, rounded once.
    assert_pct_equals(final_rounding["composite_score"], "81.20", "composite_score")
    assert_pct_equals(per_criterion["composite_score"], "81.21", "composite_score")
