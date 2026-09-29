"""Cross-cutting layers: the two version guards, and the delinquency counter.

The first two tests take the same shape on the two parents that carry optimistic
concurrency — a write that invalidates the very version the client just read, a
replay that must be refused before any business arithmetic runs, and a re-read that
makes the retry succeed. The third walks the delinquency counter to its inclusive
threshold and back down again, so that the run which finally lapses the enrollment
is counting from a reset rather than from the beginning of time.
"""
from test_helpers import (
    ApiErrorId,
    assert_hra_buckets,
    assert_hra_ledger_conservation,
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_1,
    ANALYST_1,
    ANALYST_2,
    HRA_ADMIN_1,
    make_benefits_admin_headers,
    make_eligibility_analyst_headers,
    make_hra_administrator_headers,
    make_retiree_headers,
)


def test_the_version_a_determination_create_invalidates_is_its_own(api):
    """The create bumps the retiree, so replaying the same version is stale.

    PRD 2.5 makes the field mandatory and the comparison exact: a determination
    create "must carry `expected_retiree_version` as a required, non-optional body
    field holding the client's last observed `version` of the target `Retiree`. If
    that value does not equal the retiree's current `version`, the create is
    rejected with `ERR_STALE_RETIREE_VERSION` (HTTP 412)." What makes the replay
    stale is the first create's own side effect, PRD 3.4: "`determination_sequence`
    — the running count of determinations ever created for that retiree —
    increments, `eligibility_points` is rewritten, and the retiree's `version`
    therefore increments." A 412 is the only possible answer because PRD 2.8 rung
    14 is "`expected_retiree_version` equals the retiree's current `version` →
    `ERR_STALE_RETIREE_VERSION` (412), on eligibility-determination creation." and
    the refused call may write nothing. Supersession does not reach across plan
    years either, PRD 3.4 retiring only "the retiree's earlier determinations for
    that same retiree-and-plan-year pair".

    Design: Corner/cross_cutting_complexity_layers/stale_expected_retiree_version_returns_412_then_fresh_read_succeeds
    """
    analyst = make_eligibility_analyst_headers(ANALYST_1)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    year_2027 = fx.make_open_plan_year(api)
    year_2028 = fx.make_open_plan_year(
        api,
        2028,
        overrides={
            "open_enrollment_start": "2027-10-15T00:00:00Z",
            "open_enrollment_end": "2027-11-15T00:00:00Z",
            "coverage_start": "2028-01-01T00:00:00Z",
        },
    )

    retiree = fx.make_retiree(api, f.retiree_r1_payload())
    remembered_version = retiree["version"]
    assert remembered_version == 1

    first = validate_success(
        api.create_determination(
            f.determination_payload(
                retiree["id"], year_2027["id"], remembered_version
            ),
            analyst,
        ),
        expected_status=201,
    )
    after_first = fx.reload_retiree(api, retiree["id"])
    assert after_first["version"] == 2
    assert after_first["determination_sequence"] == 1
    assert after_first["eligibility_points"] == 75

    validate_error(
        api.create_determination(
            f.determination_payload(
                retiree["id"], year_2028["id"], remembered_version
            ),
            analyst,
        ),
        ApiErrorId.ERR_STALE_RETIREE_VERSION.value,
        expected_status=412,
    )

    _rows, rejected_meta = validate_paginated(
        api.list_determinations(analyst, {"plan_year_id": year_2028["id"]})
    )
    assert rejected_meta["total_count"] == 0
    unmoved = fx.reload_retiree(api, retiree["id"])
    assert unmoved["version"] == 2
    assert unmoved["determination_sequence"] == 1

    second = validate_success(
        api.create_determination(
            f.determination_payload(retiree["id"], year_2028["id"], unmoved["version"]),
            analyst,
        ),
        expected_status=201,
    )
    assert second["plan_year_id"] == year_2028["id"]

    after_second = fx.reload_retiree(api, retiree["id"])
    assert after_second["version"] == 3
    assert after_second["determination_sequence"] == 2

    assert fx.reload_determination(api, first["id"])["status"] == "DRAFT"


def test_the_version_a_claim_invalidates_is_checked_before_the_balance(api):
    """Two claims from one read: the second is refused on the version, not the money.

    PRD 2.5 guards the account the same way it guards the retiree: a claim create
    "must carry `expected_hra_account_version` as a required, non-optional body
    field holding the client's last observed `version` of the target `HraAccount`.
    If that value does not equal the account's current `version`, the create is
    rejected with `ERR_STALE_HRA_ACCOUNT_VERSION` (HTTP 412)." The first claim is
    what makes the second one stale, PRD 3.7: "`pending_hold_cents` increases by
    the provisional amount and `available_balance_cents` decreases by it, so the
    account's `version` increments", the held figure itself being "the lesser of
    `submitted_cents` and the account's `available_balance_cents`". The refusal
    cannot be about affordability, because PRD 2.8 orders the two rungs — 15 is
    "`expected_hra_account_version` equals the account's current `version` →
    `ERR_STALE_HRA_ACCOUNT_VERSION` (412), on reimbursement-claim creation." and
    46 is "The account's `available_balance_cents` is strictly greater than zero,
    so the account can fund at least part of the submitted claim →
    `ERR_HRA_BALANCE_INSUFFICIENT` (422), on claim creation." — and states that
    "the rule that appears earliest in the following ladder produces the response,
    and no later rule is evaluated or reported." Through all of it PRD 2.10 holds:
    "`funded_cents` equals the sum of five buckets: `available_balance_cents`,
    `pending_hold_cents`, `substantiated_paid_cents`, `premium_offset_cents` and
    `forfeited_cents`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_hra_account_version_returns_412_on_claim_create
    """
    hra_admin = make_hra_administrator_headers(HRA_ADMIN_1)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    certified = fx.make_certified_retiree(
        api,
        plan_year["id"],
        f.retiree_r1_payload(),
        creator_user_id=ANALYST_1,
        certifier_user_id=ANALYST_2,
    )
    retiree_id = certified["retiree"]["id"]
    account = fx.make_hra_account(api, retiree_id, plan_year["id"], covered_months=12)
    remembered_version = account["version"]
    assert remembered_version == 1
    assert_hra_buckets(
        account,
        annual_credit_cents=184992,
        funded_cents=184992,
        available_balance_cents=184992,
        pending_hold_cents=0,
        substantiated_paid_cents=0,
        premium_offset_cents=0,
        forfeited_cents=0,
    )

    fx.set_clock(api, "2027-06-01T00:00:00Z")
    retiree_headers = make_retiree_headers(retiree_id)

    first_claim = validate_success(
        api.create_claim(
            f.claim_payload(
                account["id"],
                remembered_version,
                expense_category="MEDICARE_PART_B_PREMIUM",
                service_date="2027-05-15",
                submitted_cents=20000,
                documentation_reference="EOB-A",
            ),
            retiree_headers,
        ),
        expected_status=201,
    )
    assert first_claim["provisional_eligible_cents"] == 20000

    after_first = fx.reload_hra_account(api, account["id"])
    assert_hra_buckets(
        after_first,
        available_balance_cents=164992,
        pending_hold_cents=20000,
        substantiated_paid_cents=0,
        premium_offset_cents=0,
        forfeited_cents=0,
    )
    assert after_first["version"] == 2

    stale_body = f.claim_payload(
        account["id"],
        remembered_version,
        expense_category="MEDIGAP_PREMIUM",
        service_date="2027-05-16",
        submitted_cents=30000,
        documentation_reference="EOB-B",
    )
    stale = validate_error(
        api.create_claim(stale_body, retiree_headers),
        ApiErrorId.ERR_STALE_HRA_ACCOUNT_VERSION.value,
        expected_status=412,
    )
    assert stale["error_id"] != ApiErrorId.ERR_HRA_BALANCE_INSUFFICIENT.value

    untouched = fx.reload_hra_account(api, account["id"])
    assert_hra_buckets(
        untouched,
        available_balance_cents=164992,
        pending_hold_cents=20000,
    )
    assert untouched["version"] == 2
    _claims, claims_meta = validate_paginated(
        api.list_claims(hra_admin, {"hra_account_id": account["id"]})
    )
    assert claims_meta["total_count"] == 1

    fresh_body = dict(stale_body, expected_hra_account_version=untouched["version"])
    second_claim = validate_success(
        api.create_claim(fresh_body, retiree_headers), expected_status=201
    )
    assert second_claim["provisional_eligible_cents"] == 30000

    after_second = fx.reload_hra_account(api, account["id"])
    assert_hra_buckets(
        after_second,
        funded_cents=184992,
        available_balance_cents=134992,
        pending_hold_cents=50000,
        substantiated_paid_cents=0,
        premium_offset_cents=0,
        forfeited_cents=0,
    )
    assert after_second["version"] == 3
    assert_hra_ledger_conservation(after_second)


def test_two_unpaid_periods_suspend_and_the_third_lapses_after_a_reset(api):
    """One, then back to zero, then one, two — the boundary — and three.

    PRD 3.9 phase 2 ages one invoice per run: "Every invoice whose `status` is
    `ISSUED` or `PARTIALLY_PAID` and whose `past_due_at` is at or before the clock
    is processed in `created_at` ascending order, and each is counted in
    `processed_invoice_count`." Hop two then "touches the owning enrollment:
    `consecutive_unpaid_periods` increments by 1,
    `delinquency_first_unpaid_period_start` is set to that invoice's
    `billing_period_start` if it was previously null and left alone otherwise, and
    `billing_status` moves from `CURRENT` or `REINSTATED` to `DELINQUENT`.", and
    "Hop three, caused by hop two, moves `coverage_status` from `ACTIVE` to
    `SUSPENDED`, and each such enrollment is counted in
    `suspended_enrollment_count`." — an enrollment already suspended has no such
    move to make and is therefore not counted again. The threshold is inclusive and
    cumulative: "Hop four fires only when `consecutive_unpaid_periods` has reached
    3 — three consecutive unpaid billing periods, roughly a quarter of arrears.
    Then `billing_status` moves from `DELINQUENT` to `LAPSED`, `lapse_date` is set
    to the logical clock, and `reinstatement_deadline` is set to the clock plus the
    plan year's `reinstatement_window_days`." — 60 days after 2027-06-01 is
    2027-07-31 — and "In the same hop `coverage_status` becomes `TERMINATED` with
    `coverage_end_date` at the clock and `termination_reason` `PREMIUM_LAPSE`, the
    plan option's `enrolled_count` decrements by 1 and that option's `version`
    increments, and every `PAST_DUE` invoice on the enrollment moves to
    `WRITTEN_OFF` in `created_at` ascending order."

    The counter is resettable, which is what makes the count cumulative from the
    reset rather than from the beginning. PRD 3.8: "Full payment of an invoice that
    had aged into `PAST_DUE` unwinds delinquency. The owning enrollment's
    `consecutive_unpaid_periods` decrements by 1, and when it reaches 0 —
    equivalently, when no invoice on that enrollment is left in `PAST_DUE` —
    `billing_status` moves from `DELINQUENT` back to `CURRENT`,
    `delinquency_first_unpaid_period_start` is cleared to null, `coverage_status`
    moves from `SUSPENDED` back to `ACTIVE`, and the enrollment's `version`
    increments." The ageing calendar comes from PRD 3.8 step 9, "`due_date` is
    `billing_period_start` plus 30 days. `past_due_at` is `due_date` plus the plan
    year's `premium_grace_period_days`", and each period costs the same 15422
    because the waterfall charges "8000 basis points, that is eighty percent, for a
    `GRANDFATHERED_A` retiree" against a gross built from a base of 74500 and the
    pinned fee, "a `base_premium_cents` of 74500 yields an `admin_fee_cents` of
    2607", with no reimbursement account in existence to offset it.

    Design: Corner/cross_cutting_complexity_layers/unpaid_period_threshold_lapses_at_three_and_resets_on_full_payment
    """
    admin = make_benefits_admin_headers(ADMIN_1)
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    option = fx.make_pre65_core(api, plan_year["id"])
    certified = fx.make_certified_retiree(
        api,
        plan_year["id"],
        f.retiree_r1_payload(),
        creator_user_id=ANALYST_1,
        certifier_user_id=ANALYST_2,
    )
    retiree_id = certified["retiree"]["id"]
    pair = fx.make_enrollment(api, retiree_id, plan_year["id"], option["id"])
    enrollment_id = pair["enrollment"]["id"]

    fx.set_clock(api, "2027-01-01T00:00:00Z")
    activation = fx.run_daily(api)
    assert activation["activated_enrollment_count"] == 1
    assert fx.reload_enrollment(api, enrollment_id)["coverage_status"] == "ACTIVE"

    periods = (
        ("2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z"),
        ("2027-02-01T00:00:00Z", "2027-02-28T00:00:00Z"),
        ("2027-03-01T00:00:00Z", "2027-03-31T00:00:00Z"),
        ("2027-04-01T00:00:00Z", "2027-04-30T00:00:00Z"),
    )
    invoices = [
        fx.make_invoice(api, enrollment_id, start, end) for start, end in periods
    ]
    for invoice in invoices:
        assert invoice["gross_premium_cents"] == 77107
        assert invoice["employer_subsidy_cents"] == 61685
        assert invoice["hra_applied_cents"] == 0
        assert invoice["net_due_cents"] == 15422
    assert_instant_equals(invoices[0]["past_due_at"], "2027-03-03T00:00:00.000Z")
    assert_instant_equals(invoices[3]["past_due_at"], "2027-06-01T00:00:00.000Z")

    fx.set_clock(api, "2027-03-03T00:00:00Z", admin)
    first_run = fx.run_daily(api, admin)
    assert first_run["processed_invoice_count"] == 1
    assert first_run["suspended_enrollment_count"] == 1
    assert first_run["lapsed_enrollment_count"] == 0
    assert fx.reload_invoice(api, invoices[0]["id"])["status"] == "PAST_DUE"

    delinquent = fx.reload_enrollment(api, enrollment_id)
    assert delinquent["consecutive_unpaid_periods"] == 1
    assert delinquent["billing_status"] == "DELINQUENT"
    assert delinquent["coverage_status"] == "SUSPENDED"
    assert_instant_equals(
        delinquent["delinquency_first_unpaid_period_start"], "2027-01-01T00:00:00.000Z"
    )

    paid = fx.pay_invoice(api, invoices[0]["id"], 15422, make_retiree_headers(retiree_id))
    assert paid["status"] == "PAID"
    assert paid["paid_cents"] == 15422

    reset = fx.reload_enrollment(api, enrollment_id)
    assert reset["consecutive_unpaid_periods"] == 0
    assert reset["billing_status"] == "CURRENT"
    assert reset["coverage_status"] == "ACTIVE"
    assert reset["delinquency_first_unpaid_period_start"] is None

    fx.set_clock(api, "2027-04-03T00:00:00Z", admin)
    second_run = fx.run_daily(api, admin)
    assert second_run["processed_invoice_count"] == 1
    assert second_run["suspended_enrollment_count"] == 1
    assert second_run["lapsed_enrollment_count"] == 0
    after_second = fx.reload_enrollment(api, enrollment_id)
    assert after_second["consecutive_unpaid_periods"] == 1
    assert after_second["billing_status"] == "DELINQUENT"
    assert after_second["coverage_status"] == "SUSPENDED"

    fx.set_clock(api, "2027-05-01T00:00:00Z", admin)
    third_run = fx.run_daily(api, admin)
    assert third_run["processed_invoice_count"] == 1
    assert third_run["suspended_enrollment_count"] == 0
    assert third_run["lapsed_enrollment_count"] == 0
    boundary = fx.reload_enrollment(api, enrollment_id)
    assert boundary["consecutive_unpaid_periods"] == 2
    assert boundary["billing_status"] == "DELINQUENT"
    assert boundary["coverage_status"] == "SUSPENDED"
    assert boundary["lapse_date"] is None
    assert boundary["reinstatement_deadline"] is None

    fx.set_clock(api, "2027-06-01T00:00:00Z", admin)
    fourth_run = fx.run_daily(api, admin)
    assert fourth_run["processed_invoice_count"] == 1
    assert fourth_run["lapsed_enrollment_count"] == 1

    lapsed = fx.reload_enrollment(api, enrollment_id)
    assert lapsed["consecutive_unpaid_periods"] == 3
    assert lapsed["billing_status"] == "LAPSED"
    assert_instant_equals(lapsed["lapse_date"], "2027-06-01T00:00:00.000Z")
    assert_instant_equals(
        lapsed["reinstatement_deadline"], "2027-07-31T00:00:00.000Z"
    )
    assert lapsed["coverage_status"] == "TERMINATED"
    assert lapsed["termination_reason"] == "PREMIUM_LAPSE"
    assert fx.reload_plan_option(api, option["id"])["enrolled_count"] == 0

    assert fx.reload_invoice(api, invoices[0]["id"])["status"] == "PAID"
    for invoice in invoices[1:]:
        assert fx.reload_invoice(api, invoice["id"])["status"] == "WRITTEN_OFF"
