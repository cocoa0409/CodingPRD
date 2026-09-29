"""Derived quantities checked to the cent, the branch and the calendar day.

The coordination branch table, the actuarial cohort filter, the two-year
reimbursement carryover chain, the premium waterfall's subsidy rate and the two
date computations that no stored field can stand in for.
"""
from test_helpers import (
    assert_hra_ledger_conservation,
    assert_instant_equals,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ACTUARY_1,
    ADMIN_1,
    ANALYST_1,
    BILLING_1,
    COUNSELOR_1,
    HRA_ADMIN_1,
    make_actuary_headers,
    make_benefits_admin_headers,
    make_billing_clerk_headers,
    make_eligibility_analyst_headers,
    make_enrollment_counselor_headers,
    make_hra_administrator_headers,
)


BRANCH_WALK = (
    (
        {"active_employment_flag": True, "other_group_coverage_employer_size": 20},
        "GROUP_PRIMARY_WORKING_AGED",
        "WORKING_AGED_LARGE_EMPLOYER",
    ),
    (
        {"other_group_coverage_employer_size": 19},
        "MEDICARE_PRIMARY",
        "WORKING_AGED_SMALL_EMPLOYER",
    ),
    (
        {
            "active_employment_flag": False,
            "disability_entitlement_flag": True,
            "other_group_coverage_employer_size": 100,
        },
        "GROUP_PRIMARY",
        "DISABILITY_LARGE_EMPLOYER",
    ),
    (
        {"other_group_coverage_employer_size": 99},
        "MEDICARE_PRIMARY",
        "DISABILITY_SMALL_EMPLOYER",
    ),
    (
        {"esrd_flag": True, "esrd_entitlement_date": "2025-05-01"},
        "GROUP_PRIMARY",
        "ESRD_WITHIN_COORDINATION",
    ),
    (
        {"esrd_entitlement_date": "2024-01-01"},
        "MEDICARE_PRIMARY",
        "ESRD_AFTER_COORDINATION",
    ),
)


def _medicare_retiree_on_a_pending_exchange_enrollment(api):
    """R2, Medicare-enrolled, holding one PENDING enrollment on EXCH-HRA with the
    clock at 2026-10-20.

    Returns {"retiree_id", "enrollment"}. EXCH-HRA carries no prescription
    subsidy vehicle, so nothing about the option can move the payer order.
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    option = fx.make_exch_hra(api, plan_year_id, activate=True)

    certified = fx.make_certified_retiree(api, plan_year_id, f.retiree_r2_payload())
    retiree = certified["retiree"]
    assert retiree["medicare_status"] == "MEDICARE_ENROLLED"
    assert retiree["esrd_flag"] is False
    assert retiree["active_employment_flag"] is False
    assert retiree["disability_entitlement_flag"] is False
    assert retiree["other_group_coverage_employer_size"] == 0

    enrollment = fx.make_enrollment(
        api, retiree["id"], plan_year_id, option["id"]
    )["enrollment"]
    assert enrollment["coverage_status"] == "PENDING"
    return {"retiree_id": retiree["id"], "enrollment": enrollment}


def test_six_coordination_patches_walk_the_payer_order_branch_table(api):
    """Both employer-size boundaries, and renal disease outranking disability.

    PRD 3.6: "Eight branches are evaluated strictly top to bottom against the
    enrollment's retiree, and the first branch that matches wins; the order is
    pinned and no later branch is consulted once an earlier one matches." and
    "Both employer-size thresholds are inclusive, so exactly 20 employees selects
    the working-aged large-employer branch and exactly 100 employees selects the
    disability large-employer branch." The last two patches leave
    `disability_entitlement_flag` true underneath, and the renal-disease branches
    still win because they sit above: "The elapsed-months arithmetic used by the
    renal-disease branches is exact and integer: multiply the difference in years
    between the two dates by 12, add the difference in their month numbers, and
    then subtract one when the day-of-month of the later date is strictly less
    than the day-of-month of the earlier date." — 17 whole months from 2025-05-01
    and 33 from 2024-01-01 against a 2026-10-20 clock, either side of the 30-month
    coordination period. Each patch reaches the enrollment because the answer is
    "re-derived whenever a retiree's Medicare or other-coverage attributes are
    updated", and PRD 2.4 makes that reach visible: `version` "increases by
    exactly 1 on every mutation of that row, including mutations reached through a
    cascade rather than through a direct request against the row itself."

    Design: Corner/calculations/msp_payer_order_branch_table_propagates_through_six_branches
    """
    state = _medicare_retiree_on_a_pending_exchange_enrollment(api)
    enrollment_id = state["enrollment"]["id"]
    admin = make_benefits_admin_headers(ADMIN_1)

    assert state["enrollment"]["payer_order"] == "MEDICARE_PRIMARY"
    assert state["enrollment"]["msp_basis_code"] == "MEDICARE_PRIMARY_RETIREE_COVERAGE"
    assert state["enrollment"]["version"] == 1

    for step, (patch, payer_order, basis_code) in enumerate(BRANCH_WALK, start=1):
        validate_success(
            api.patch_retiree(state["retiree_id"], f.retiree_patch_payload(patch), admin)
        )
        enrollment = fx.reload_enrollment(api, enrollment_id)
        assert enrollment["payer_order"] == payer_order, step
        assert enrollment["msp_basis_code"] == basis_code, step
        assert enrollment["coverage_status"] == "PENDING", step
        assert enrollment["version"] == step + 1, step

    assert fx.reload_enrollment(api, enrollment_id)["version"] == 7


def test_the_valuation_cohort_counts_only_the_certified_eligible_retiree(api):
    """Three retirees hold a determination for the year and one is measured.

    PRD 3.9: "The valuation cohort is every retiree who holds an eligibility
    determination for that plan year whose `status` is `CERTIFIED` and whose
    `outcome` is `ELIGIBLE`, iterated in the retirees' `created_at` ascending
    order. `DRAFT`, `UNDER_APPEAL` and `SUPERSEDED` determinations are excluded,
    and so are `CERTIFIED` determinations whose `outcome` is `INELIGIBLE`." R1 is
    a `GRANDFATHERED_A`, so PRD 3.9 gives a full-eligibility horizon of "15 years
    for a `GRANDFATHERED_A`" and an assumed-retirement horizon of "that
    full-eligibility horizon plus 5 further years", the 20 that
    `PROJECTED_UNIT_CREDIT` divides by, and the service cost is "the expected
    obligation divided by the assumed-retirement horizon and truncated down when
    the retiree's service years are strictly below that horizon".

    Design: Corner/calculations/liability_valuation_cohort_excludes_ineligible_and_draft_determinations
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    r1 = fx.make_retiree_r1(api)
    r3 = fx.make_retiree_r3(api)
    r5 = fx.make_retiree(api, f.retiree_r5_payload())

    determination_1 = fx.make_determination(api, r1, plan_year["id"])
    determination_3 = fx.make_determination(api, r3, plan_year["id"])
    determination_5 = fx.make_determination(api, r5, plan_year["id"], certify=False)

    assert determination_1["status"] == "CERTIFIED"
    assert determination_1["outcome"] == "ELIGIBLE"
    assert determination_3["status"] == "CERTIFIED"
    assert determination_3["outcome"] == "INELIGIBLE"
    assert determination_3["points"] == 74
    assert determination_5["status"] == "DRAFT"
    assert determination_5["outcome"] == "ELIGIBLE"

    valued = validate_success(
        api.run_liability_valuation(
            plan_year["id"],
            f.liability_valuation_payload("PROJECTED_UNIT_CREDIT"),
            make_actuary_headers(ACTUARY_1),
        )
    )

    assert valued["measured_retiree_count"] == 1
    assert valued["epbo_total_cents"] == 4571428
    assert valued["apbo_total_cents"] == 2742856
    assert valued["service_cost_total_cents"] == 228571
    assert valued["liability_method"] == "PROJECTED_UNIT_CREDIT"
    assert_instant_equals(
        valued["liability_valued_at"], "2026-10-20T00:00:00.000Z", "liability_valued_at"
    )


def _closed_2026_account_and_a_certified_2027_year(api):
    """R1's 2026 account funded at 184992, closed at 2026-12-31 with 92496 left,
    beside an OPEN 2027 plan year the same retiree is certified eligible for.

    Returns {"retiree_id", "plan_year_2026_id", "plan_year_2027_id",
    "determination_2026", "account_2026"} where account_2026 is the closed row.
    """
    fx.set_clock(api, "2025-10-20T00:00:00Z")
    plan_year_2026 = fx.make_open_plan_year(
        api,
        year=2026,
        overrides={
            "open_enrollment_start": "2025-10-15T00:00:00Z",
            "open_enrollment_end": "2025-11-15T00:00:00Z",
            "coverage_start": "2026-01-01T00:00:00Z",
        },
    )
    retiree = fx.make_retiree_r1(api)
    determination_2026 = fx.make_determination(api, retiree, plan_year_2026["id"])
    assert determination_2026["status"] == "CERTIFIED"

    account_2026 = fx.make_hra_account(
        api, retiree["id"], plan_year_2026["id"], covered_months=12
    )
    assert account_2026["annual_credit_cents"] == 184992
    assert account_2026["carryover_in_cents"] == 0
    assert account_2026["funded_cents"] == 184992

    fx.set_clock(api, "2026-12-31T00:00:00Z")
    closed = fx.close_hra_year(api, account_2026["id"])
    assert closed["status"] == "CLOSED"
    assert closed["forfeited_cents"] == 92496
    assert closed["available_balance_cents"] == 92496

    plan_year_2027 = fx.make_open_plan_year(api, year=2027)
    fx.make_determination(
        api, fx.reload_retiree(api, retiree["id"]), plan_year_2027["id"]
    )
    return {
        "retiree_id": retiree["id"],
        "plan_year_2026_id": plan_year_2026["id"],
        "plan_year_2027_id": plan_year_2027["id"],
        "determination_2026": determination_2026,
        "account_2026": closed,
    }


def test_the_new_year_account_inherits_the_closed_accounts_surviving_balance(api):
    """92496 arrives as carryover, and the annual credit is not inflated by it.

    PRD 3.7: "`carryover_in_cents` is the `available_balance_cents` of the account
    named by `prior_year_account_id`, or 0 when no prior account was supplied.
    `funded_cents` is `annual_credit_cents` plus `carryover_in_cents`, and it is
    this figure that the ledger invariant conserves forever after." The annual
    credit itself is computed from the plan year alone — "That full-year figure is
    then divided by 12 and truncated down to whole cents to give a monthly credit,
    and only then multiplied by `covered_months` to give `annual_credit_cents`" —
    so it lands on the same 184992 the 2026 account started with. The prior
    determination survives the second one, because PRD 3.4 supersedes only "the
    retiree's earlier determinations for that same retiree-and-plan-year pair".

    Design: Corner/calculations/hra_carryover_chain_inherits_closed_prior_year_balance
    """
    state = _closed_2026_account_and_a_certified_2027_year(api)

    account_2027 = validate_success(
        api.create_hra_account(
            f.hra_account_payload(
                state["retiree_id"],
                state["plan_year_2027_id"],
                12,
                state["account_2026"]["id"],
            ),
            make_hra_administrator_headers(HRA_ADMIN_1),
        ),
        expected_status=201,
    )

    assert account_2027["annual_credit_cents"] == 184992
    assert account_2027["carryover_in_cents"] == 92496
    assert account_2027["funded_cents"] == 277488
    assert account_2027["available_balance_cents"] == 277488
    assert account_2027["pending_hold_cents"] == 0
    assert account_2027["substantiated_paid_cents"] == 0
    assert account_2027["premium_offset_cents"] == 0
    assert account_2027["forfeited_cents"] == 0
    assert account_2027["status"] == "OPEN"
    assert account_2027["closed_at"] is None
    assert_hra_ledger_conservation(account_2027)

    assert fx.reload_determination(api, state["determination_2026"]["id"])["status"] == (
        "CERTIFIED"
    )

    children, meta = validate_paginated(
        api.list_hra_accounts(
            make_hra_administrator_headers(HRA_ADMIN_1),
            {"prior_year_account_id": state["account_2026"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert fx.list_ids(children) == [account_2027["id"]]


def test_the_forfeiture_cap_is_a_fraction_of_the_annual_credit_alone(api):
    """277488 funded, a 92496 cap, and 184992 forfeited rather than 138744.

    PRD 3.7: "the carryover cap is `annual_credit_cents` multiplied by the plan
    year's `carryover_cap_pct`, truncated down to whole cents; `forfeited_cents`
    is the excess of `available_balance_cents` over that cap, or 0 when the balance
    does not exceed the cap; and `available_balance_cents` is reduced by exactly
    `forfeited_cents`." The PRD names the trap directly: "Note carefully that the
    cap is a fraction of **this** plan year's `annual_credit_cents` alone —
    inherited `carryover_in_cents` does not raise it, so a retiree carrying a large
    balance forward will forfeit most of it a second time." A cap taken off
    `funded_cents` would be 138744 and forfeit only 138744. PRD 2.10 requires the
    five buckets to keep summing to `funded_cents` afterwards.

    Design: Corner/calculations/hra_forfeiture_cap_ignores_inherited_carryover_bucket
    """
    state = _closed_2026_account_and_a_certified_2027_year(api)
    account_2027 = fx.make_hra_account(
        api,
        state["retiree_id"],
        state["plan_year_2027_id"],
        covered_months=12,
        prior_year_account_id=state["account_2026"]["id"],
    )
    assert account_2027["funded_cents"] == 277488
    assert account_2027["annual_credit_cents"] == 184992
    assert account_2027["carryover_in_cents"] == 92496

    fx.set_clock(api, "2027-12-31T00:00:00Z")
    closed = validate_success(
        api.close_hra_year(
            account_2027["id"], make_hra_administrator_headers(HRA_ADMIN_1)
        )
    )

    assert closed["forfeited_cents"] == 184992
    assert closed["forfeited_cents"] != 138744
    assert closed["available_balance_cents"] == 92496
    assert closed["pending_hold_cents"] == 0
    assert closed["substantiated_paid_cents"] == 0
    assert closed["premium_offset_cents"] == 0
    assert closed["status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], "2027-12-31T00:00:00.000Z", "closed_at")
    assert closed["funded_cents"] == 277488
    assert_hra_ledger_conservation(closed)


def test_a_one_month_reimbursement_balance_leaves_six_cents_to_remit(api):
    """15416 of reimbursement money against a 15422 share, so 6 cents remain.

    PRD 3.8 pins the waterfall: "`admin_fee_cents` is 350 basis points — three and
    a half percent — of `base_premium_cents`, truncated down to whole cents" giving
    2607 on 74500, then "`gross_premium_cents` is `base_premium_cents` plus
    `admin_fee_cents`", then "`employer_subsidy_cents` is `gross_premium_cents`
    multiplied by `employer_subsidy_bps`, divided by 10000, and truncated down to
    whole cents" and "`retiree_share_cents` is `gross_premium_cents` minus
    `employer_subsidy_cents`". Step seven brings in the account: "`hra_applied_cents`
    is the lesser of that available balance and `retiree_share_cents`", step eight
    that "`net_due_cents` is `retiree_share_cents` minus `hra_applied_cents`", and
    step ten that "The invoice's `status` is `PAID` when `net_due_cents` is 0 — a
    fully subsidised and fully offset period requires no remittance — and `ISSUED`
    otherwise." PRD 3.8 also fixes the ageing dates — "`due_date` is
    `billing_period_start` plus 30 days. `past_due_at` is `due_date` plus the plan
    year's `premium_grace_period_days`" — and the account-side transfer:
    "`available_balance_cents` decreases by `hra_applied_cents`,
    `premium_offset_cents` increases by the same amount, and the account's
    `version` increments."

    Design: Corner/calculations/premium_invoice_partial_hra_offset_leaves_six_cents_due
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    certified = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())
    retiree_id = certified["retiree"]["id"]

    enrollment = fx.make_enrollment(
        api, retiree_id, plan_year_id, program["pre65_core"]["id"]
    )["enrollment"]
    assert enrollment["monthly_retiree_premium_cents"] == 15422

    account = fx.make_hra_account(api, retiree_id, plan_year_id, covered_months=1)
    assert account["annual_credit_cents"] == 15416
    assert account["available_balance_cents"] == 15416
    assert account["premium_offset_cents"] == 0

    fx.set_clock(api, "2027-01-05T00:00:00Z")
    counters = fx.run_daily(api)
    assert counters["activated_enrollment_count"] == 1
    assert fx.reload_enrollment(api, enrollment["id"])["coverage_status"] == "ACTIVE"

    invoice = validate_success(
        api.create_invoice(
            f.invoice_payload(enrollment["id"]),
            make_billing_clerk_headers(BILLING_1),
        ),
        expected_status=201,
    )

    assert invoice["base_premium_cents"] == 74500
    assert invoice["admin_fee_cents"] == 2607
    assert invoice["gross_premium_cents"] == 77107
    assert invoice["employer_subsidy_bps"] == 8000
    assert invoice["employer_subsidy_cents"] == 61685
    assert invoice["retiree_share_cents"] == 15422
    assert invoice["hra_applied_cents"] == 15416
    assert invoice["net_due_cents"] == 6
    assert invoice["paid_cents"] == 0
    assert invoice["status"] == "ISSUED"
    assert_instant_equals(invoice["due_date"], "2027-01-31T00:00:00.000Z", "due_date")
    assert_instant_equals(
        invoice["past_due_at"], "2027-03-03T00:00:00.000Z", "past_due_at"
    )

    debited = fx.reload_hra_account(api, account["id"])
    assert debited["available_balance_cents"] == 0
    assert debited["premium_offset_cents"] == 15416
    assert debited["substantiated_paid_cents"] == 0
    assert debited["pending_hold_cents"] == 0
    assert debited["forfeited_cents"] == 0
    assert debited["funded_cents"] == 15416
    assert debited["version"] == 2
    assert_hra_ledger_conservation(debited)


def test_exactly_twenty_five_service_years_earns_the_long_service_bonus(api):
    """300 credited months buys 1000 extra basis points; 299 buys nothing.

    PRD 3.8 step four: "`employer_subsidy_bps` starts from the retiree's grandfather
    cohort: 8000 basis points, that is eighty percent, for a `GRANDFATHERED_A`
    retiree" and then "A long-service bump then applies: when the retiree's service
    years — `credited_service_months` divided by 12 and truncated down — is at least
    25, the rate rises by 1000 basis points, capped so that it never exceeds 10000
    basis points. A `GRANDFATHERED_A` retiree with 25 or more service years therefore
    lands on 9000 basis points, and the cap only ever binds if a cohort rate were
    already at or above 9000." Both retirees sit in the
    same cohort on the same option, so PRD 3.8's earlier steps produce an identical
    77107 gross for each and the bonus is the only moving part. Neither retiree has
    a reimbursement account, and PRD 3.8 says that balance "is treated as 0 when no
    such account exists".

    Design: Corner/calculations/long_service_bonus_bps_applied_at_exactly_twenty_five_service_years
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    option_id = program["pre65_core"]["id"]

    at_threshold = fx.make_certified_retiree(
        api,
        plan_year_id,
        f.retiree_payload(full_name="Delphine Marchetti", credited_service_months=300),
    )
    below_threshold = fx.make_certified_retiree(
        api,
        plan_year_id,
        f.retiree_payload(full_name="Anton Bielawski", credited_service_months=299),
    )
    assert at_threshold["retiree"]["grandfathered_group"] == "GRANDFATHERED_A"
    assert below_threshold["retiree"]["grandfathered_group"] == "GRANDFATHERED_A"

    enrollment_at = fx.make_enrollment(
        api, at_threshold["retiree"]["id"], plan_year_id, option_id
    )["enrollment"]
    enrollment_below = fx.make_enrollment(
        api, below_threshold["retiree"]["id"], plan_year_id, option_id
    )["enrollment"]
    assert enrollment_at["monthly_retiree_premium_cents"] == 7711
    assert enrollment_below["monthly_retiree_premium_cents"] == 15422

    fx.set_clock(api, "2027-01-05T00:00:00Z")
    billing = make_billing_clerk_headers(BILLING_1)

    invoice_at = validate_success(
        api.create_invoice(f.invoice_payload(enrollment_at["id"]), billing),
        expected_status=201,
    )
    invoice_below = validate_success(
        api.create_invoice(f.invoice_payload(enrollment_below["id"]), billing),
        expected_status=201,
    )

    assert invoice_at["employer_subsidy_bps"] == 9000
    assert invoice_at["employer_subsidy_cents"] == 69396
    assert invoice_at["retiree_share_cents"] == 7711
    assert invoice_at["net_due_cents"] == 7711

    assert invoice_below["employer_subsidy_bps"] == 8000
    assert invoice_below["employer_subsidy_cents"] == 61685
    assert invoice_below["retiree_share_cents"] == 15422

    for invoice in (invoice_at, invoice_below):
        assert invoice["base_premium_cents"] == 74500
        assert invoice["admin_fee_cents"] == 2607
        assert invoice["gross_premium_cents"] == 77107
        assert invoice["hra_applied_cents"] == 0
        assert invoice["status"] == "ISSUED"

    assert (
        invoice_below["retiree_share_cents"] - invoice_at["retiree_share_cents"] == 7711
    )


GRANDFATHER_PROBES = (
    ("Cutoff A Minus One", "1992-12-31", 400, "GRANDFATHERED_A", 99),
    ("Cutoff A Exact", "1993-01-01", 400, "TRANSITION_B", 99),
    ("Cutoff B Minus One", "2004-12-31", 260, "TRANSITION_B", 87),
    ("Cutoff B Exact", "2005-01-01", 260, "STANDARD_C", 87),
)


def test_both_grandfather_cutoffs_are_half_open_on_the_low_side(api):
    """Four hire dates a day either side of the two cohort boundaries.

    PRD 3.3: "A retiree hired strictly before 1 January 1993 is a
    `GRANDFATHERED_A`. Otherwise, a retiree hired strictly before 1 January 2005 is
    a `TRANSITION_B`. Everyone else is a `STANDARD_C`. Both boundaries are
    half-open on the low side, so a `hire_date` of exactly 1993-01-01 lands in
    `TRANSITION_B` and a `hire_date` of exactly 2005-01-01 lands in `STANDARD_C`.
    The comparison is a calendar-date comparison, not an instant comparison." No
    plan year is involved, because PRD 3.3 also says grandfathering "is decided
    once, at creation, from `hire_date` alone". The points each row opens with
    follow from the same section: `eligibility_points` "is the sum of completed age
    at retirement and service years; it is computed when the retiree record is
    created", so 66 completed years plus 33 or 21 service years.

    Design: Corner/calculations/grandfather_group_assigned_at_both_hire_date_cutoffs
    """
    admin = make_benefits_admin_headers(ADMIN_1)

    for full_name, hire_date, months, group, points in GRANDFATHER_PROBES:
        retiree = validate_success(
            api.create_retiree(
                f.retiree_payload(
                    full_name=full_name,
                    birth_date="1960-01-01",
                    hire_date=hire_date,
                    retirement_date="2026-12-31",
                    credited_service_months=months,
                ),
                admin,
            ),
            expected_status=201,
        )
        assert retiree["hire_date"] == hire_date, full_name
        assert retiree["grandfathered_group"] == group, full_name
        assert retiree["eligibility_status"] == "UNDETERMINED", full_name
        assert retiree["determination_sequence"] == 0, full_name
        assert retiree["eligibility_points"] == points, full_name

    _rows, meta = validate_paginated(api.list_retirees(admin))
    assert meta["total_count"] == 4


def test_the_rule_set_follows_the_cohort_and_not_the_numbers(api):
    """R6 has 82 points and is INELIGIBLE because its cohort tests age 65.

    PRD 3.3: "Which eligibility rule set a retiree faces is a direct function of
    the cohort. A `GRANDFATHERED_A` retiree is measured under
    `RULE_OF_75_GRANDFATHERED`, a `TRANSITION_B` retiree under `AGE_60_SERVICE_15`,
    and a `STANDARD_C` retiree under `AGE_65_SERVICE_10`." Neither of the two
    cohort rules looks at points at all: "Under `AGE_60_SERVICE_15`, the retiree is
    `ELIGIBLE` when completed age at retirement is at least 60 years and service
    years is at least 15; otherwise `INELIGIBLE`." and "Under `AGE_65_SERVICE_10`,
    the retiree is `ELIGIBLE` when completed age at retirement is at least 65 years
    and service years is at least 10; otherwise `INELIGIBLE`." Both determinations
    stay in `DRAFT`, so PRD 3.4 leaves the retirees' own `eligibility_status`
    alone — that dimension moves only when "the subject retiree's
    `eligibility_status` is set to the determination's `outcome`" at certification —
    while `determination_sequence` and `eligibility_points` do advance, because
    "`determination_sequence` — the running count of determinations ever created for
    that retiree — increments, `eligibility_points` is rewritten".

    Design: Corner/calculations/rule_set_code_selected_by_group_for_transition_b_and_standard_c
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    r5 = fx.make_retiree(api, f.retiree_r5_payload())
    r6 = fx.make_retiree(api, f.retiree_r6_payload())
    assert r5["grandfathered_group"] == "TRANSITION_B"
    assert r6["grandfathered_group"] == "STANDARD_C"

    analyst = make_eligibility_analyst_headers(ANALYST_1)
    determination_5 = validate_success(
        api.create_determination(
            f.determination_payload(r5["id"], plan_year["id"], r5["version"]), analyst
        ),
        expected_status=201,
    )
    determination_6 = validate_success(
        api.create_determination(
            f.determination_payload(r6["id"], plan_year["id"], r6["version"]), analyst
        ),
        expected_status=201,
    )

    assert determination_5["grandfathered_group"] == "TRANSITION_B"
    assert determination_5["rule_set_code"] == "AGE_60_SERVICE_15"
    assert determination_5["age_years_at_retirement"] == 64
    assert determination_5["service_years"] == 28
    assert determination_5["points"] == 92
    assert determination_5["outcome"] == "ELIGIBLE"
    assert determination_5["status"] == "DRAFT"

    assert determination_6["grandfathered_group"] == "STANDARD_C"
    assert determination_6["rule_set_code"] == "AGE_65_SERVICE_10"
    assert determination_6["age_years_at_retirement"] == 64
    assert determination_6["service_years"] == 18
    assert determination_6["points"] == 82
    assert determination_6["outcome"] == "INELIGIBLE"
    assert determination_6["status"] == "DRAFT"

    reloaded_5 = fx.reload_retiree(api, r5["id"])
    reloaded_6 = fx.reload_retiree(api, r6["id"])
    assert reloaded_5["determination_sequence"] == 1
    assert reloaded_6["determination_sequence"] == 1
    assert reloaded_5["eligibility_points"] == 92
    assert reloaded_6["eligibility_points"] == 82
    assert reloaded_5["eligibility_status"] == "UNDETERMINED"
    assert reloaded_6["eligibility_status"] == "UNDETERMINED"


def test_a_life_event_covers_from_the_first_of_the_following_month(api):
    """An election admitted in February takes effect on 1 March, not 1 January.

    PRD 3.5: "For any of the four qualifying life events, `window_deadline` is the
    `event_date` taken at midnight UTC plus 31 days, and the election is admitted
    only while the logical clock is at or after the `event_date` at midnight UTC and
    at or before that `window_deadline` — closed at both ends — a clock outside it
    being refused with `ERR_LIFE_EVENT_WINDOW_EXPIRED`. Its
    `coverage_effective_date` is the first day of the calendar month **after** the
    month containing `event_date`, at midnight UTC." That is a different rule from
    the annual one, where "`coverage_effective_date` is the plan year's
    `coverage_start`", so the plan year's 2027-01-01 must not appear. The admitted
    row opens where PRD 3.5 says it does: "An admitted election is created with
    `status` `SUBMITTED`, `submitted_at` set to the logical clock,
    `created_by_user_id` set to the submitting user's `X-User-ID`,
    `denial_reason_code` null and `resulting_enrollment_id` null."

    Design: Corner/calculations/life_event_coverage_effective_date_is_first_of_following_month
    """
    program = fx.standard_program(api)
    plan_year = program["plan_year"]
    certified = fx.make_certified_retiree(
        api, plan_year["id"], f.retiree_r1_payload()
    )
    assert_instant_equals(
        plan_year["open_enrollment_end"], "2026-11-15T00:00:00.000Z", "open_enrollment_end"
    )

    fx.set_clock(api, "2027-02-10T00:00:00Z")
    counselor = make_enrollment_counselor_headers(COUNSELOR_1)

    election = validate_success(
        api.create_election_event(
            f.election_event_payload(
                certified["retiree"]["id"],
                plan_year["id"],
                program["pre65_core"]["id"],
                "LOSS_OF_OTHER_COVERAGE",
                "2027-02-05",
            ),
            counselor,
        ),
        expected_status=201,
    )

    assert election["event_type"] == "LOSS_OF_OTHER_COVERAGE"
    assert election["status"] == "SUBMITTED"
    assert election["created_by_user_id"] == COUNSELOR_1
    assert_instant_equals(
        election["window_deadline"], "2027-03-08T00:00:00.000Z", "window_deadline"
    )
    assert_instant_equals(
        election["coverage_effective_date"],
        "2027-03-01T00:00:00.000Z",
        "coverage_effective_date",
    )
    assert not election["coverage_effective_date"].startswith("2027-01-01")
    assert_instant_equals(
        election["submitted_at"], "2027-02-10T00:00:00.000Z", "submitted_at"
    )
    assert election["resulting_enrollment_id"] is None
    assert election["denial_reason_code"] is None
