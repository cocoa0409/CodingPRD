"""Two multi-step formulas whose pinned step order changes the cents.

Reimbursement funding floors the monthly credit before multiplying by covered
months, and premium assembly charges a fee-exclusive administrative fee before
applying a service-weighted employer subsidy.
"""
from test_helpers import assert_hra_ledger_conservation, assert_instant_equals
from test_helpers import factories as f
from test_helpers import fixtures as fx


R2_OVERRIDES = {"other_group_coverage_employer_size": 25, "active_employment_flag": True}


def _year_with_two_certified_retirees(api):
    """Clock 2026-10-20, OPEN plan year 2027, and both R2 (MEDICARE_ENROLLED) and
    R1 (PRE_MEDICARE) certified eligible with no HRA account yet."""
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    r2 = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r2_payload(R2_OVERRIDES))
    r1 = fx.make_certified_retiree(api, plan_year["id"], f.retiree_r1_payload())
    return plan_year, r2, r1


def test_hra_funding_floors_the_monthly_credit_before_multiplying(api):
    """209500 cents over 7 covered months funds 122206, not 122208.

    PRD 3.7: "Flooring per month before multiplying is the rule; dividing the
    year's credit by 12 after multiplying by the covered months is not, and the
    two differ — a full-year credit of 209500 cents over 7 covered months yields
    122206 cents under the pinned order and 122208 cents under the rejected one."
    R2 is MEDICARE_ENROLLED, so the account draws hra_credit_medicare_cents.

    Design: Difficulty/combinatorial_formula/hra_funding_monthly_floor_before_multiply
    """
    plan_year, r2, _r1 = _year_with_two_certified_retirees(api)

    account = fx.make_hra_account(api, r2["retiree"]["id"], plan_year["id"], 7)

    assert account["annual_credit_cents"] == 122206
    assert account["annual_credit_cents"] != 122208
    assert account["carryover_in_cents"] == 0
    assert account["funded_cents"] == 122206
    assert account["available_balance_cents"] == 122206
    assert account["pending_hold_cents"] == 0
    assert account["substantiated_paid_cents"] == 0
    assert account["premium_offset_cents"] == 0
    assert account["forfeited_cents"] == 0
    assert account["status"] == "OPEN"
    assert_hra_ledger_conservation(account)


def test_hra_funding_loses_cents_to_the_monthly_floor_over_a_full_year(api):
    """185000 cents over all 12 covered months funds 184992, not 185000.

    PRD 3.7: "That full-year figure is then divided by 12 and truncated down to
    whole cents to give a monthly credit, and only then multiplied by
    `covered_months` to give `annual_credit_cents`." R1's posture is not
    MEDICARE_ENROLLED, so the account draws hra_credit_pre_medicare_cents, and
    because 185000 is not divisible by 12 the per-month floor still costs the
    account 8 cents even when every month of the year is covered.

    Design: Difficulty/combinatorial_formula/hra_funding_monthly_floor_before_multiply
    """
    plan_year, _r2, r1 = _year_with_two_certified_retirees(api)

    account = fx.make_hra_account(api, r1["retiree"]["id"], plan_year["id"], 12)

    assert account["annual_credit_cents"] == 184992
    assert account["annual_credit_cents"] != 185000
    assert account["funded_cents"] == 184992
    assert account["available_balance_cents"] == 184992
    assert_hra_ledger_conservation(account)


def _two_enrolled_retirees(api):
    """Clock 2026-10-20, OPEN plan year 2027, ACTIVE PRE65-CORE, and approved
    enrollments for R1 (12 service years) and R4 (33 service years)."""
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    option_id = program["pre65_core"]["id"]

    r1 = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())
    enr1 = fx.make_enrollment(api, r1["retiree"]["id"], plan_year_id, option_id)
    r4 = fx.make_certified_retiree(api, plan_year_id, f.retiree_r4_payload())
    enr4 = fx.make_enrollment(api, r4["retiree"]["id"], plan_year_id, option_id)
    return program, enr1["enrollment"], enr4["enrollment"]


def test_invoice_admin_fee_is_fee_exclusive_on_the_base_premium(api):
    """74500 cents of base premium carries a 2607-cent fee and grosses 77107.

    PRD 3.8: "The circular fixed-point reading is not used, and the two differ
    visibly: a `base_premium_cents` of 74500 yields an `admin_fee_cents` of 2607
    under the pinned rule, where the rejected fixed point would yield 2702." R1
    is GRANDFATHERED_A with 12 service years, so no long-service bump applies and
    the subsidy stays at 8000 basis points; with no reimbursement account the
    whole retiree share is due.

    Design: Difficulty/combinatorial_formula/premium_invoice_fee_exclusive_and_service_tiered_subsidy
    """
    _program, enr1, _enr4 = _two_enrolled_retirees(api)

    invoice = fx.make_invoice(
        api, enr1["id"], "2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z"
    )

    assert invoice["base_premium_cents"] == 74500
    assert invoice["admin_fee_cents"] == 2607
    assert invoice["admin_fee_cents"] != 2702
    assert invoice["gross_premium_cents"] == 77107
    assert invoice["gross_premium_cents"] != 77202
    assert invoice["employer_subsidy_bps"] == 8000
    assert invoice["employer_subsidy_cents"] == 61685
    assert invoice["retiree_share_cents"] == 15422
    assert invoice["hra_applied_cents"] == 0
    assert invoice["net_due_cents"] == 15422
    assert invoice["status"] == "ISSUED"
    assert_instant_equals(invoice["due_date"], "2027-01-31T00:00:00.000Z", "due_date")
    assert_instant_equals(
        invoice["past_due_at"], "2027-03-03T00:00:00.000Z", "past_due_at"
    )
    assert enr1["monthly_retiree_premium_cents"] == 15422


def test_invoice_long_service_bump_raises_the_subsidy_on_the_same_gross(api):
    """33 service years lift the same 77107 gross to a 9000-bps subsidy.

    PRD 3.8: "A long-service bump then applies: when the retiree's service years
    — `credited_service_months` divided by 12 and truncated down — is at least
    25, the rate rises by 1000 basis points, capped so that it never exceeds
    10000 basis points." R4 is GRANDFATHERED_A with 402 credited months, so 33
    service years take the rate from 8000 to 9000 basis points and the retiree
    share falls from 15422 to 7711 on the identical plan option and period.

    Design: Difficulty/combinatorial_formula/premium_invoice_fee_exclusive_and_service_tiered_subsidy
    """
    _program, _enr1, enr4 = _two_enrolled_retirees(api)

    invoice = fx.make_invoice(
        api, enr4["id"], "2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z"
    )

    assert invoice["base_premium_cents"] == 74500
    assert invoice["admin_fee_cents"] == 2607
    assert invoice["gross_premium_cents"] == 77107
    assert invoice["employer_subsidy_bps"] == 9000
    assert invoice["employer_subsidy_cents"] == 69396
    assert invoice["retiree_share_cents"] == 7711
    assert invoice["hra_applied_cents"] == 0
    assert invoice["net_due_cents"] == 7711
    assert enr4["monthly_retiree_premium_cents"] == 7711
