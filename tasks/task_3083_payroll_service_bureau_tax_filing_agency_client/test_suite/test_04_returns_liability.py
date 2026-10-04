"""Tax return lifecycle, dual liability views, and shortfall penalties (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_confirmed_deposit,
    create_deposit,
    create_return_for,
    create_run,
    create_settled_run,
    get_client,
    get_success_data,
    set_clock,
    setup_active_client,
    submit_run,
    impound_run,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import create_client, create_jurisdiction, create_registration_payload


def _q3_jurisdiction():
    return create_jurisdiction(
        code="CA-DE9",
        name="CA EDD DE9",
        deposit_frequency="QUARTERLY",
        underpayment_threshold_cents=250000,
    )


def test_return_liability_bureau_books_vs_agency_confirmed():
    """PRD §3.7: "At filing time the system computes `expected_liability_cents`
    under the **bureau-books view**: the sum of `total_tax_cents` across the
    client's PayrollRuns whose `period_end` falls inside the return period and
    whose status is `SUBMITTED`, `IMPOUNDED`, or `SETTLED` — deliberately
    including money the bureau has drafted but not yet settled."
    PRD §3.7: "Reconciliation moves an `ACCEPTED` return to `RECONCILED`, stamps
    `reconciled_at`, and freezes the final liability comparison on the return under
    the **agency-confirmed view**: the sum of `amount_cents` across the client's
    `CONFIRMED` TaxDeposits for the return's jurisdiction whose `quarter` falls
    inside the return period — only money the agency has acknowledged."

    Design: Difficulty/dual_variant_calc/return_liability_bureau_books_vs_agency_confirmed
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    # Run 1: SETTLED with CONFIRMED deposit of 400000.
    r1 = create_settled_run(
        client,
        pay_date="2026-09-04T00:00:00Z",
        period_start="2026-08-16T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
        gross_pay_cents=2000000,
        total_tax_cents=400000,
    )
    create_confirmed_deposit(r1["run"], jurisdiction["id"], 400000)
    # Run 2: IMPOUNDED (not settled) with a SCHEDULED-only deposit of 350000.
    run2 = create_run(
        client,
        pay_date="2026-09-18T00:00:00Z",
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-15T00:00:00Z",
        gross_pay_cents=1800000,
        total_tax_cents=350000,
    )
    submit_run(client, run2)
    impound_run(client, run2)
    run2 = get_success_data(
        api_client.get_payroll_run(run2["id"], TEST_USERS["filer_alpha_headers"])
    )
    create_deposit(run2, jurisdiction["id"], 350000)

    # Q3 must be closed before the return can be filed (PRD §3.7 temporal gate).
    set_clock("2026-10-05T00:00:00Z")
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    filed = validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    # Bureau books: 400000 SETTLED + 350000 IMPOUNDED = 750000.
    assert filed["expected_liability_cents"] == 750000

    accepted = validate_success(
        api_client.accept_return(ret["id"], TEST_USERS["filer_beta_headers"])
    )
    assert accepted["status"] == "ACCEPTED"
    reconciled = validate_success(
        api_client.reconcile_return(ret["id"], TEST_USERS["filer_beta_headers"])
    )
    assert reconciled["status"] == "RECONCILED"
    # Agency-confirmed: only the CONFIRMED deposit D1 (400000) counts.
    assert reconciled["expected_liability_cents"] == 400000
    assert filed["expected_liability_cents"] != reconciled["expected_liability_cents"]


def test_bureau_books_includes_drafted_but_unsettled_runs():
    """PRD §3.7: "the sum of `total_tax_cents` across the client's PayrollRuns
    whose `period_end` falls inside the return period and whose status is
    `SUBMITTED`, `IMPOUNDED`, or `SETTLED` — deliberately including money the
    bureau has drafted but not yet settled, and excluding `REVERSED` and
    `CANCELLED` runs."

    Design: Difficulty/dual_variant_calc/return_liability_bureau_books_vs_agency_confirmed
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    # A merely-SUBMITTED run (never impounded) still counts toward bureau books.
    create_settled_run(
        client,
        pay_date="2026-08-17T00:00:00Z",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        gross_pay_cents=1000000,
        total_tax_cents=200000,
    )
    run_sub = create_run(
        client,
        pay_date="2026-09-04T00:00:00Z",
        period_start="2026-08-22T00:00:00Z",
        period_end="2026-09-04T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    submit_run(client, run_sub)

    set_clock("2026-10-05T00:00:00Z")
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    filed = validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert filed["expected_liability_cents"] == 500000  # 200000 SETTLED + 300000 SUBMITTED
    assert filed["status"] == "FILED"


def test_bureau_books_excludes_reversed_and_cancelled_runs():
    """PRD §3.7: "the sum of `total_tax_cents` across the client's PayrollRuns
    whose `period_end` falls inside the return period and whose status is
    `SUBMITTED`, `IMPOUNDED`, or `SETTLED` — deliberately including money the
    bureau has drafted but not yet settled, and excluding `REVERSED` and
    `CANCELLED` runs."

    Design: Corner/calculations/c_bureau_books_excludes_reversed_and_cancelled_runs
    """
    from test_helpers import fail_impound

    jurisdiction = _q3_jurisdiction()
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    # Run A: SETTLED, tax 300000 (counts).
    create_settled_run(
        client,
        pay_date="2026-08-17T00:00:00Z",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    # Run B: REVERSED via NSF fail, tax 999999 (excluded).
    run_b = create_run(
        client,
        pay_date="2026-08-31T00:00:00Z",
        period_start="2026-08-16T00:00:00Z",
        period_end="2026-08-31T00:00:00Z",
        gross_pay_cents=4999995,
        total_tax_cents=999999,
    )
    submit_run(client, run_b)
    fail_impound(impound_run(client, run_b))
    # Run C: CANCELLED while SUBMITTED, tax 888888 (excluded).
    run_c = create_run(
        client,
        pay_date="2026-09-15T00:00:00Z",
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-14T00:00:00Z",
        gross_pay_cents=4444440,
        total_tax_cents=888888,
    )
    submit_run(client, run_c)
    from test_helpers import make_client_admin_headers

    validate_success(
        api_client.cancel_run(run_c["id"], make_client_admin_headers(client["id"]))
    )

    set_clock("2026-10-05T00:00:00Z")  # Q3 closed
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    filed = validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert filed["expected_liability_cents"] == 300000


def test_shortfall_penalty_safe_harbor_zeroes_penalty():
    """PRD §3.7: "The safe harbor excuses the balance-due penalty whenever the
    client's `CONFIRMED` deposits for that jurisdiction and quarter total at least
    the jurisdiction's `underpayment_threshold_cents` — a comparison with the
    threshold inclusive, so a total exactly at the threshold is safe."
    PRD §3.7: "the evaluation order is pinned: the liability is computed first
    under the bureau-books view, then the safe-harbor comparison runs, then the
    shortfall."

    Design: Difficulty/combinatorial_formula/shortfall_penalty_pinned_evaluation_order
    """
    jurisdiction = _q3_jurisdiction()
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    # Three SETTLED runs of 300000 tax each in Q3 (liability 900000).
    pay_dates = [
        ("2026-07-15T00:00:00Z", "2026-07-01T00:00:00Z", "2026-07-14T00:00:00Z"),
        ("2026-08-17T00:00:00Z", "2026-08-01T00:00:00Z", "2026-08-15T00:00:00Z"),
        ("2026-09-15T00:00:00Z", "2026-09-01T00:00:00Z", "2026-09-14T00:00:00Z"),
    ]
    runs = []
    for pay, start, end in pay_dates:
        runs.append(
            create_settled_run(
                client,
                pay_date=pay,
                period_start=start,
                period_end=end,
                gross_pay_cents=1500000,
                total_tax_cents=300000,
            )
        )
    # Only ONE deposit of 300000 CONFIRMED; 300000 >= threshold 250000.
    create_confirmed_deposit(runs[0]["run"], jurisdiction["id"], 300000)

    set_clock("2026-10-05T00:00:00Z")  # Q3 closed; filing window reached
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    filed = validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert filed["expected_liability_cents"] == 900000
    assert filed["shortfall_penalty_exposure_cents"] == 0, (
        "safe harbor: confirmed deposits 300000 >= threshold 250000 zeroes the penalty"
    )


def test_shortfall_penalty_applies_below_threshold():
    """PRD §3.7: "Below the threshold, the shortfall is the liability minus the
    confirmed-deposit total; if that difference is zero or negative the exposure is
    zero. Otherwise the exposure is the shortfall multiplied by a tier rate chosen
    by how many calendar days elapsed from the quarter's end to the filing date —
    `penalty_tier1_rate` when at most 5 days, `penalty_tier2_rate` when 6 to 15
    days, `penalty_tier3_rate` when 16 or more — rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/shortfall_penalty_pinned_evaluation_order
    """
    jurisdiction = _q3_jurisdiction()
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    create_settled_run(
        client,
        pay_date="2026-08-17T00:00:00Z",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    # No confirmed deposits: below the threshold.
    # File 5 days after quarter end (2026-09-30 -> 2026-10-05): tier 1 (0.02).
    set_clock("2026-10-05T00:00:00Z")
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    filed = validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert filed["expected_liability_cents"] == 300000
    # shortfall 300000 * 0.02 = 6000.
    assert filed["shortfall_penalty_exposure_cents"] == 6000


def test_safe_harbor_threshold_boundary_exactly_at():
    """PRD §3.7: "The safe harbor excuses the balance-due penalty whenever the
    client's `CONFIRMED` deposits for that jurisdiction and quarter total at least
    the jurisdiction's `underpayment_threshold_cents` — a comparison with the
    threshold inclusive, so a total exactly at the threshold is safe."

    Design: Corner/calculations/c_safe_harbor_threshold_boundary_exactly_at
    """
    jurisdiction = _q3_jurisdiction()
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    r1 = create_settled_run(
        client,
        pay_date="2026-07-15T00:00:00Z",
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-07-14T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    # Confirmed total exactly 250000 == underpayment_threshold_cents.
    create_confirmed_deposit(r1["run"], jurisdiction["id"], 250000)
    create_settled_run(
        client,
        pay_date="2026-08-17T00:00:00Z",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    create_settled_run(
        client,
        pay_date="2026-09-15T00:00:00Z",
        period_start="2026-09-01T00:00:00Z",
        period_end="2026-09-14T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    set_clock("2026-10-05T00:00:00Z")
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    filed = validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert filed["expected_liability_cents"] == 900000
    assert filed["shortfall_penalty_exposure_cents"] == 0, (
        "exactly-at-threshold is safe (inclusive >=)"
    )


def test_safe_harbor_one_cent_below_threshold_penalizes():
    """PRD §3.7: "The safe harbor excuses the balance-due penalty whenever the
    client's `CONFIRMED` deposits for that jurisdiction and quarter total at least
    the jurisdiction's `underpayment_threshold_cents` — a comparison with the
    threshold inclusive, so a total exactly at the threshold is safe."
    PRD §3.7: "Below the threshold, the shortfall is the liability minus the
    confirmed-deposit total; if that difference is zero or negative the exposure
    is zero. Otherwise the exposure is the shortfall multiplied by a tier rate."

    Design: Corner/calculations/c_safe_harbor_threshold_boundary_exactly_at
    """
    jurisdiction = _q3_jurisdiction()
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    r1 = create_settled_run(
        client,
        pay_date="2026-08-17T00:00:00Z",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    # Confirmed total 249999 — one cent below the threshold.
    create_confirmed_deposit(r1["run"], jurisdiction["id"], 249999)
    set_clock("2026-10-05T00:00:00Z")  # 5 days after Q3 end -> tier 1
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    filed = validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert filed["expected_liability_cents"] == 300000
    # shortfall = 300000 - 249999 = 50001; 50001 * 0.02 = 1000.02 -> 1000 half-up.
    assert filed["shortfall_penalty_exposure_cents"] == 1000


def test_file_before_period_close_returns_period_not_closed():
    """PRD §3.7: "Filing also enforces a temporal gate: the return's period must
    be closed — filing before the period end plus the jurisdiction's filing
    window, as read on the logical clock, is rejected with `ERR_PERIOD_NOT_CLOSED`
    (HTTP 409)."

    Design: Corner/validations/v_file_before_period_close_returns_period_not_closed
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    # Q3 ends 2026-09-30; filing on 2026-09-29 is before period close.
    set_clock("2026-09-29T00:00:00Z")
    resp = api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED, 409)
    set_clock("2026-10-01T00:00:00Z")
    filed = validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert filed["status"] == "FILED"


def test_file_on_last_day_of_period_rejected_next_day_ok():
    """PRD §3.7: "Filing also enforces a temporal gate: the return's period must
    be closed — filing before the period end plus the jurisdiction's filing
    window, as read on the logical clock, is rejected with `ERR_PERIOD_NOT_CLOSED`
    (HTTP 409)."

    Design: Corner/validations/v_file_before_period_close_returns_period_not_closed
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    set_clock("2026-09-30T12:00:00Z")  # still inside Q3
    resp = api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED, 409)
    set_clock("2026-10-01T00:00:00Z")
    filed = validate_success(
        api_client.file_return(ret["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert filed["status"] == "FILED"
    assert filed.get("filed_at"), "filed_at must be stamped at filing"


def test_reconcile_blocked_by_open_notice_then_succeeds():
    """PRD §3.7: "Reconciliation is blocked while any AgencyNotice for the return
    is `OPEN` or `IN_REVIEW`, surfacing `ERR_OPEN_NOTICE_BLOCKS_RECONCILIATION`
    (HTTP 409)."
    PRD §3.9: "once the last such notice is resolved the reconcile gate re-opens."

    Design: Corner/state_machines/sm_return_reconcile_blocked_by_open_notice_bubble_up
    """
    from test_helpers import create_accepted_return, create_notice_payload

    jurisdiction = _q3_jurisdiction()
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    r1 = create_settled_run(
        client,
        pay_date="2026-08-17T00:00:00Z",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    create_confirmed_deposit(r1["run"], jurisdiction["id"], 300000)
    set_clock("2026-10-20T00:00:00Z")
    ret = create_accepted_return(client, jurisdiction["id"], "2026-Q3")
    notice = get_success_data(
        api_client.create_notice(
            create_notice_payload(
                client_id=client["id"],
                jurisdiction_id=jurisdiction["id"],
                return_id=ret["id"],
                notice_type="DATA_MISMATCH",
                claimed_amount_cents=75000,
                received_at="2026-10-21T00:00:00Z",
                response_due_at="2026-11-21T00:00:00Z",
            ),
            TEST_USERS["filer_alpha_headers"],
        )
    )
    resp = api_client.reconcile_return(ret["id"], TEST_USERS["filer_beta_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_NOTICE_BLOCKS_RECONCILIATION, 409)

    validate_success(
        api_client.start_notice_review(notice["id"], TEST_USERS["filer_alpha_headers"])
    )
    validate_success(
        api_client.resolve_notice(
            notice["id"],
            {"resolution": "NO_CHANGE", "resolution_note": "Confirmed correct"},
            TEST_USERS["filer_alpha_headers"],
        )
    )
    validate_success(
        api_client.close_notice(notice["id"], TEST_USERS["filer_alpha_headers"])
    )
    reconciled = validate_success(
        api_client.reconcile_return(ret["id"], TEST_USERS["filer_beta_headers"])
    )
    assert reconciled["status"] == "RECONCILED"


def test_reconcile_blocked_by_in_review_notice():
    """PRD §3.7: "Reconciliation is blocked while any AgencyNotice for the return
    is `OPEN` or `IN_REVIEW`, surfacing `ERR_OPEN_NOTICE_BLOCKS_RECONCILIATION`
    (HTTP 409)."

    Design: Corner/state_machines/sm_return_reconcile_blocked_by_open_notice_bubble_up
    """
    from test_helpers import create_accepted_return, create_notice_payload

    jurisdiction = _q3_jurisdiction()
    setup = setup_active_client(jurisdiction=jurisdiction)
    client = setup["client"]
    r1 = create_settled_run(
        client,
        pay_date="2026-08-17T00:00:00Z",
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
        gross_pay_cents=1500000,
        total_tax_cents=300000,
    )
    create_confirmed_deposit(r1["run"], jurisdiction["id"], 300000)
    set_clock("2026-10-20T00:00:00Z")
    ret = create_accepted_return(client, jurisdiction["id"], "2026-Q3")
    notice = get_success_data(
        api_client.create_notice(
            create_notice_payload(
                client_id=client["id"],
                jurisdiction_id=jurisdiction["id"],
                return_id=ret["id"],
                notice_type="BALANCE_DUE",
            ),
            TEST_USERS["filer_alpha_headers"],
        )
    )
    validate_success(
        api_client.start_notice_review(notice["id"], TEST_USERS["filer_alpha_headers"])
    )
    resp = api_client.reconcile_return(ret["id"], TEST_USERS["filer_beta_headers"])
    validate_error(resp, ApiErrorId.ERR_OPEN_NOTICE_BLOCKS_RECONCILIATION, 409)


def test_electronic_filing_gated_on_registration_verification():
    """PRD §3.7: "The return starts in `DRAFT` status, and its `filing_method` is
    computed from the registration gate: `ELECTRONIC` when the
    JurisdictionRegistration for the (client, jurisdiction) pair is `VERIFIED`,
    `MANUAL_INTERIM` when the registration is still `PENDING`."
    PRD §3.3: "A registration that flips from `PENDING` to `VERIFIED` does not
    rewrite anything that was filed earlier — it only changes what is computed for
    filings created after the flip."

    Design: Difficulty/cross_entity_state_dependency/electronic_return_filing_gated_on_registration_verification
    """
    from test_helpers import create_return_for as _mk

    j_fed = create_jurisdiction()
    j_ca = _q3_jurisdiction()
    setup = setup_active_client(jurisdiction=j_fed)
    client = setup["client"]
    # CA registration created but left PENDING (multi-jurisdiction delay).
    reg_ca = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=j_ca["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    set_clock("2026-10-05T00:00:00Z")
    ret_man = _mk(client, j_ca["id"], "2026-Q3")
    assert ret_man["filing_method"] == "MANUAL_INTERIM"
    # Manual interim filing succeeds while the registration is PENDING.
    filed_man = validate_success(
        api_client.file_return(ret_man["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert filed_man["status"] == "FILED"
    assert filed_man["filing_method"] == "MANUAL_INTERIM"

    # Verify the CA registration: no retroactive rewrite of the filed return.
    validate_success(
        api_client.verify_registration(reg_ca["id"], TEST_USERS["onboarder_headers"])
    )
    fetched_man = validate_success(
        api_client.get_return(ret_man["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert fetched_man["filing_method"] == "MANUAL_INTERIM"
    assert fetched_man["status"] == "FILED"

    # Returns created after verification come out ELECTRONIC.
    ret_elec = _mk(client, j_ca["id"], "2026-Q4")
    assert ret_elec["filing_method"] == "ELECTRONIC"


def test_pending_registration_blocks_electronic_create_but_allows_manual_filing():
    """PRD §3.7: "`ELECTRONIC` when the JurisdictionRegistration for the (client,
    jurisdiction) pair is `VERIFIED`, `MANUAL_INTERIM` when the registration is
    still `PENDING` — the bureau files on paper in the interim rather than leaving
    the client non-compliant — and if the registration is `REJECTED` the return
    cannot be created at all, failing with `ERR_REGISTRATION_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/electronic_return_filing_gated_on_registration_verification
    """
    j_fed = create_jurisdiction()
    j_ca = _q3_jurisdiction()
    setup = setup_active_client(jurisdiction=j_fed)
    client = setup["client"]
    reg_ca = get_success_data(
        api_client.create_registration(
            client["id"],
            create_registration_payload(jurisdiction_id=j_ca["id"]),
            TEST_USERS["onboarder_headers"],
        )
    )
    # Reject the CA registration: return creation must fail.
    validate_success(
        api_client.reject_registration(
            reg_ca["id"], "POA not on file", TEST_USERS["onboarder_headers"]
        )
    )
    from test_helpers import client_version

    resp = api_client.create_return(
        {
            "client_id": client["id"],
            "jurisdiction_id": j_ca["id"],
            "period": "2026-Q3",
            "expected_client_version": client_version(client["id"]),
        },
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_VERIFIED, 422)


def test_deposit_submission_gated_on_payroll_run_settlement():
    """PRD §3.6: "the backing PayrollRun must be `SETTLED` — funds actually in the
    bureau account — else `ERR_FUNDS_NOT_SETTLED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/deposit_submission_gated_on_payroll_run_settlement
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    run = create_run(client, gross_pay_cents=750000, total_tax_cents=150000)
    submit_run(client, run)
    imp = impound_run(client, run)
    run = get_success_data(
        api_client.get_payroll_run(run["id"], TEST_USERS["filer_alpha_headers"])
    )
    dep = create_deposit(run, jurisdiction["id"], 150000)

    # Run still IMPOUNDED (impound PENDING): submission fails.
    resp = api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_FUNDS_NOT_SETTLED, 409)

    validate_success(api_client.settle_impound(imp["id"], TEST_USERS["treasury_headers"]))
    assert get_success_data(
        api_client.get_payroll_run(run["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "SETTLED"

    submitted = validate_success(
        api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )
    assert submitted["status"] == "SUBMITTED"


def test_deposit_submission_blocked_for_draft_run():
    """PRD §3.6: "the backing PayrollRun must be `SETTLED` — funds actually in the
    bureau account — else `ERR_FUNDS_NOT_SETTLED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/deposit_submission_gated_on_payroll_run_settlement
    """
    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    run = create_run(client, gross_pay_cents=750000, total_tax_cents=150000)
    submit_run(client, run)
    impound_run(client, run)
    run = get_success_data(
        api_client.get_payroll_run(run["id"], TEST_USERS["filer_alpha_headers"])
    )
    dep = create_deposit(run, jurisdiction["id"], 150000)
    resp = api_client.submit_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    validate_error(resp, ApiErrorId.ERR_FUNDS_NOT_SETTLED, 409)
    assert get_success_data(
        api_client.get_deposit(dep["id"], TEST_USERS["filer_alpha_headers"])
    )["status"] == "SCHEDULED"


def test_return_create_occ_stale_client_version():
    """PRD §2.7: "Creating a tax return requires `expected_client_version` to
    equal the owning Client's current `version`. A new filing supersedes the
    caller's snapshot of the client's filing landscape, so a stale view is refused
    rather than silently serialized."
    PRD §2.7: "a mismatch is always rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/l_occ_stale_client_version_on_deposit_create
    """
    from test_helpers import client_version

    setup = setup_active_client()
    client, jurisdiction = setup["client"], setup["jurisdiction"]
    stale = client["version"]
    # First create succeeds and bumps the client's version.
    ret = create_return_for(client, jurisdiction["id"], "2026-Q3")
    assert ret["status"] == "DRAFT"
    assert client_version(client["id"]) == stale + 1
    # Second create with the pre-bump version is refused.
    resp = api_client.create_return(
        {
            "client_id": client["id"],
            "jurisdiction_id": jurisdiction["id"],
            "period": "2026-Q4",
            "expected_client_version": stale,
        },
        TEST_USERS["filer_alpha_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_initiate_impound_occ_stale_client_version():
    """PRD §2.7: "Initiating an impound requires `expected_client_version` to
    equal the owning Client's current `version`. Risk-posture changes, credit-hold
    changes, and prior impound initiations all advance the client's `version`, so
    a stale read of the client's funding posture cannot be used to justify a new
    draft."
    PRD §2.7: "a mismatch is always rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/l_occ_stale_client_version_on_deposit_create
    """
    from test_helpers import make_client_admin_headers

    setup = setup_active_client()
    client = setup["client"]
    run = create_run(client)
    submit_run(client, run)
    stale = client["version"]
    resp = api_client.initiate_impound(
        run["id"], stale + 99, make_client_admin_headers(client["id"])
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
