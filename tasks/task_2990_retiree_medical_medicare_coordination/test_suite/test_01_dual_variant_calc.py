"""Two calculations that each run under two variants and deliberately disagree.

The reimbursement claim is priced once at submission and again at approval, and
the plan-year liability is valued under two attribution methods over one
unchanged cohort.
"""
from test_helpers import (
    assert_hra_ledger_conservation,
    assert_instant_equals,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ACTUARY_1, HRA_ADMIN_2, make_actuary_headers


R2_OVERRIDES = {"other_group_coverage_employer_size": 25, "active_employment_flag": True}


def _medicare_account(api):
    """Clock 2026-10-20, OPEN plan year 2027, certified-eligible R2 and an OPEN
    HRA account funded for 7 covered months."""
    return fx.hra_funded_retiree(
        api,
        covered_months=7,
        clock="2026-10-20T00:00:00Z",
        retiree_payload=f.retiree_r2_payload(R2_OVERRIDES),
    )


def test_claim_submission_prices_under_the_provisional_variant(api):
    """Submitting a 30000-cent DENTAL_VISION_PREMIUM claim holds the full 30000.

    PRD 3.7: "The provisional variant caps only against the balance; it ignores
    the expense category's reimbursement percentage and the per-claim cap
    entirely." The account holds 122206 cents, so the lesser of submitted_cents
    and available_balance_cents is the submitted 30000, and both
    provisional_eligible_cents and eligible_cents open at that figure while
    pending_hold_cents rises to 30000 and available_balance_cents falls to 92206.

    Design: Difficulty/dual_variant_calc/hra_claim_provisional_versus_final_eligible_amount
    """
    state = _medicare_account(api)
    account = state["hra_account"]
    assert account["funded_cents"] == 122206
    assert account["available_balance_cents"] == 122206

    claim = fx.make_claim(
        api,
        account,
        state["retiree"]["id"],
        expense_category="DENTAL_VISION_PREMIUM",
        service_date="2027-03-10",
        submitted_cents=30000,
        documentation_reference="RCPT-2027-0310-A",
    )

    assert claim["status"] == "SUBMITTED"
    assert claim["provisional_eligible_cents"] == 30000
    assert claim["eligible_cents"] == 30000

    reloaded = fx.reload_hra_account(api, account["id"])
    assert reloaded["pending_hold_cents"] == 30000
    assert reloaded["available_balance_cents"] == 92206
    assert reloaded["funded_cents"] == 122206
    assert_hra_ledger_conservation(reloaded)


def test_claim_approval_reprices_under_the_final_variant(api):
    """Approval halves the same claim to 15000 and returns the surplus hold.

    PRD 3.7: "A `DENTAL_VISION_PREMIUM` expense is reimbursed at 5000 basis
    points, that is half of `submitted_cents`, truncated down to whole cents."
    The category rule runs first under the final variant, so the identical claim
    data yields eligible_cents 15000 while provisional_eligible_cents stays
    30000; the 15000-cent difference is unwound out of pending_hold_cents and
    back into available_balance_cents, which rises from 92206 to 107206.

    Design: Difficulty/dual_variant_calc/hra_claim_provisional_versus_final_eligible_amount
    """
    state = _medicare_account(api)
    account = state["hra_account"]
    claim = fx.make_claim(
        api,
        account,
        state["retiree"]["id"],
        expense_category="DENTAL_VISION_PREMIUM",
        service_date="2027-03-10",
        submitted_cents=30000,
        documentation_reference="RCPT-2027-0310-A",
    )

    reviewed = fx.review_claim(api, claim["id"], "APPROVE", reviewer_user_id=HRA_ADMIN_2)

    assert reviewed["status"] == "APPROVED"
    assert reviewed["eligible_cents"] == 15000
    assert reviewed["provisional_eligible_cents"] == 30000

    reloaded = fx.reload_hra_account(api, account["id"])
    assert reloaded["pending_hold_cents"] == 15000
    assert reloaded["available_balance_cents"] == 107206
    assert reloaded["funded_cents"] == 122206
    assert reloaded["substantiated_paid_cents"] == 0
    assert reloaded["premium_offset_cents"] == 0
    assert reloaded["forfeited_cents"] == 0
    assert_hra_ledger_conservation(reloaded)


def _single_certified_retiree_year(api):
    """Clock 2026-10-20, OPEN plan year 2027 and exactly one certified-eligible
    retiree, R1, so the valuation cohort has size 1."""
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    certified = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r1_payload())
    return plan_year, certified


def test_liability_valuation_projected_unit_credit_attributes_over_the_longer_horizon(api):
    """PROJECTED_UNIT_CREDIT writes apbo 2742856 against epbo 4571428.

    PRD 3.9: "Under `PROJECTED_UNIT_CREDIT` the retiree's accumulated obligation
    is the expected obligation multiplied by the lesser of the retiree's service
    years and the assumed-retirement horizon, divided by the assumed-retirement
    horizon, truncated down — the obligation is attributed over service to the
    assumed retirement date, so the denominator is the full-eligibility horizon
    plus 5." R1 is GRANDFATHERED_A with 12 service years, so the horizon is
    15 + 5 = 20, and liability_valued_at is the logical clock of the run.

    Design: Difficulty/dual_variant_calc/liability_valuation_projected_unit_credit_versus_full_eligibility
    """
    plan_year, _certified = _single_certified_retiree_year(api)

    valued = validate_success(
        api.run_liability_valuation(
            plan_year["id"],
            f.liability_valuation_payload("PROJECTED_UNIT_CREDIT"),
            make_actuary_headers(ACTUARY_1),
        )
    )

    assert valued["liability_method"] == "PROJECTED_UNIT_CREDIT"
    assert valued["measured_retiree_count"] == 1
    assert valued["epbo_total_cents"] == 4571428
    assert valued["apbo_total_cents"] == 2742856
    assert valued["service_cost_total_cents"] == 228571
    assert_instant_equals(
        valued["liability_valued_at"], "2026-10-20T00:00:00.000Z", "liability_valued_at"
    )


def test_liability_valuation_full_eligibility_attributes_over_the_shorter_horizon(api):
    """ATTRIBUTION_TO_FULL_ELIGIBILITY reports 3657142 from the same cohort.

    PRD 3.9: "Under `ATTRIBUTION_TO_FULL_ELIGIBILITY` it is the expected
    obligation multiplied by the lesser of the retiree's service years and the
    full-eligibility horizon, divided by the full-eligibility horizon, truncated
    down — the obligation is attributed to the full-eligibility date instead, so
    the denominator is smaller and the numerator saturates five years earlier."
    Re-running the valuation over the unchanged one-retiree cohort therefore
    raises apbo_total_cents from 2742856 to 3657142, a difference of 914286,
    while epbo_total_cents and service_cost_total_cents do not move.

    Design: Difficulty/dual_variant_calc/liability_valuation_projected_unit_credit_versus_full_eligibility
    """
    plan_year, _certified = _single_certified_retiree_year(api)
    actuary = make_actuary_headers(ACTUARY_1)

    first = validate_success(
        api.run_liability_valuation(
            plan_year["id"], f.liability_valuation_payload("PROJECTED_UNIT_CREDIT"), actuary
        )
    )
    assert first["apbo_total_cents"] == 2742856

    second = validate_success(
        api.run_liability_valuation(
            plan_year["id"],
            f.liability_valuation_payload("ATTRIBUTION_TO_FULL_ELIGIBILITY"),
            actuary,
        )
    )

    assert second["liability_method"] == "ATTRIBUTION_TO_FULL_ELIGIBILITY"
    assert second["apbo_total_cents"] == 3657142
    assert second["epbo_total_cents"] == 4571428
    assert second["service_cost_total_cents"] == 228571
    assert second["measured_retiree_count"] == 1
    assert second["apbo_total_cents"] - first["apbo_total_cents"] == 914286
    assert_instant_equals(
        second["liability_valued_at"], "2026-10-20T00:00:00.000Z", "liability_valued_at"
    )
