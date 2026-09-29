"""Two single calls whose effects propagate several hops beyond their target.

One nightly sweep ages three invoices and ends by denying a reimbursement claim
it never touched directly; one plan-year status change ends by denying elections
it never named.
"""
from test_helpers import assert_hra_ledger_conservation, assert_instant_equals
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ADMIN_1, make_benefits_admin_headers


def _three_unpaid_periods_and_an_open_claim(api):
    """R1 active on PRE65-CORE with three unpaid invoices, a funded HRA account
    holding a 40000-cent claim, and the clock past every past_due_at.

    Returns {"plan_option_id", "enrollment_id", "invoice_ids", "hra_account",
    "claim_id"}. The account is opened after the invoices are raised, so no
    premium offset was ever applied and funded_cents stays whole.
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    option_id = program["pre65_core"]["id"]

    certified = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())
    retiree_id = certified["retiree"]["id"]
    enrollment = fx.make_enrollment(
        api, retiree_id, plan_year_id, option_id
    )["enrollment"]

    periods = [
        ("2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z"),
        ("2027-02-01T00:00:00Z", "2027-02-28T00:00:00Z"),
        ("2027-03-01T00:00:00Z", "2027-03-31T00:00:00Z"),
    ]
    invoice_ids = []
    for start, end in periods:
        invoice = fx.make_invoice(api, enrollment["id"], start, end)
        assert invoice["net_due_cents"] == 15422
        assert invoice["hra_applied_cents"] == 0
        invoice_ids.append(invoice["id"])

    fx.set_clock(api, "2027-01-01T00:00:00Z")
    fx.run_daily(api)
    assert fx.reload_enrollment(api, enrollment["id"])["coverage_status"] == "ACTIVE"

    account = fx.make_hra_account(api, retiree_id, plan_year_id, 12)
    assert account["funded_cents"] == 184992
    claim = fx.make_claim(
        api,
        account,
        retiree_id,
        expense_category="QUALIFIED_MEDICAL",
        service_date="2027-02-10",
        submitted_cents=40000,
        documentation_reference="EOB-2027-0210-B",
    )
    held = fx.reload_hra_account(api, account["id"])
    assert held["pending_hold_cents"] == 40000
    assert held["available_balance_cents"] == 144992

    fx.set_clock(api, "2027-06-01T00:00:00Z")
    return {
        "plan_option_id": option_id,
        "enrollment_id": enrollment["id"],
        "invoice_ids": invoice_ids,
        "hra_account": held,
        "claim_id": claim["id"],
    }


def test_lapse_cascade_lapses_billing_terminates_coverage_and_writes_off(api):
    """Three arrears periods lapse the enrollment and write off every invoice.

    PRD 3.9: "Hop four fires only when `consecutive_unpaid_periods` has reached 3
    — three consecutive unpaid billing periods, roughly a quarter of arrears.
    Then `billing_status` moves from `DELINQUENT` to `LAPSED`, `lapse_date` is set
    to the logical clock, and `reinstatement_deadline` is set to the clock plus
    the plan year's `reinstatement_window_days`." and "In the same hop
    `coverage_status` becomes `TERMINATED` with `coverage_end_date` at the clock
    and `termination_reason` `PREMIUM_LAPSE`, the plan option's `enrolled_count`
    decrements by 1 and that option's `version` increments, and every `PAST_DUE`
    invoice on the enrollment moves to `WRITTEN_OFF` in `created_at` ascending
    order." The window is 60 days from the 2027-06-01 clock, so the reinstatement
    deadline lands on 2027-07-31.

    Design: Difficulty/transitive_cascade/daily_run_premium_lapse_cascade_depth_seven
    """
    state = _three_unpaid_periods_and_an_open_claim(api)

    counters = fx.run_daily(api, make_benefits_admin_headers(ADMIN_1))

    assert counters["processed_invoice_count"] == 3
    assert counters["activated_enrollment_count"] == 0
    assert counters["suspended_enrollment_count"] == 1
    assert counters["lapsed_enrollment_count"] == 1
    assert counters["applied_plan_change_count"] == 0
    assert counters["recomputed_msp_count"] == 0

    enrollment = fx.reload_enrollment(api, state["enrollment_id"])
    assert enrollment["consecutive_unpaid_periods"] == 3
    assert_instant_equals(
        enrollment["delinquency_first_unpaid_period_start"],
        "2027-01-01T00:00:00.000Z",
        "delinquency_first_unpaid_period_start",
    )
    assert enrollment["billing_status"] == "LAPSED"
    assert_instant_equals(
        enrollment["lapse_date"], "2027-06-01T00:00:00.000Z", "lapse_date"
    )
    assert_instant_equals(
        enrollment["reinstatement_deadline"],
        "2027-07-31T00:00:00.000Z",
        "reinstatement_deadline",
    )
    assert enrollment["coverage_status"] == "TERMINATED"
    assert_instant_equals(
        enrollment["coverage_end_date"], "2027-06-01T00:00:00.000Z", "coverage_end_date"
    )
    assert enrollment["termination_reason"] == "PREMIUM_LAPSE"

    for invoice_id in state["invoice_ids"]:
        assert fx.reload_invoice(api, invoice_id)["status"] == "WRITTEN_OFF"

    assert fx.reload_plan_option(api, state["plan_option_id"])["enrolled_count"] == 0


def test_lapse_cascade_freezes_the_account_and_denies_its_open_claim(api):
    """The last two hops reach an account and a claim no invoice named.

    PRD 3.9: "Hop five is caused by hop four rather than by the invoice ageing:
    the `OPEN` reimbursement account for that retiree and plan year moves to
    `FROZEN`, its `version` incrementing. Hop six is caused by hop five: for that
    now-frozen account, every claim whose `status` is `SUBMITTED`,
    `PENDING_SUBSTANTIATION` or `APPROVED` moves to `DENIED` with
    `denial_reason_code` `ACCOUNT_NOT_OPEN`, its held `eligible_cents` released
    from `pending_hold_cents` back into `available_balance_cents`, processed in
    `created_at` ascending order with each claim's `version` incrementing." The
    40000-cent hold therefore returns in full and the five buckets still sum to
    the unchanged funded_cents.

    Design: Difficulty/transitive_cascade/daily_run_premium_lapse_cascade_depth_seven
    """
    state = _three_unpaid_periods_and_an_open_claim(api)
    account_before = state["hra_account"]

    fx.run_daily(api)

    account = fx.reload_hra_account(api, account_before["id"])
    assert account["status"] == "FROZEN"
    assert account["version"] > account_before["version"]

    claim = fx.reload_claim(api, state["claim_id"])
    assert claim["status"] == "DENIED"
    assert claim["denial_reason_code"] == "ACCOUNT_NOT_OPEN"

    assert account["pending_hold_cents"] == 0
    assert account["available_balance_cents"] == 184992
    assert account["funded_cents"] == 184992
    assert account["substantiated_paid_cents"] == 0
    assert account["premium_offset_cents"] == 0
    assert account["forfeited_cents"] == 0
    assert_hra_ledger_conservation(account)


def _open_year_with_two_pending_elections(api):
    """An OPEN plan year carrying an ACTIVE PRE65-CORE, a DRAFT EXCH-HRA, one
    SUBMITTED election and one UNDER_REVIEW election, both on PRE65-CORE.

    Returns {"plan_year_id", "pre65_core_id", "exch_hra_id", "submitted_id",
    "under_review_id"}.
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    pre65_core_id = program["pre65_core"]["id"]
    exch_hra = fx.make_exch_hra(api, plan_year_id, activate=False)
    assert exch_hra["status"] == "DRAFT"

    r1 = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())
    r4 = fx.make_certified_retiree(api, plan_year_id, f.retiree_r4_payload())

    submitted = fx.make_election_event(
        api, r1["retiree"]["id"], plan_year_id, pre65_core_id
    )
    assert submitted["status"] == "SUBMITTED"
    under_review = fx.make_election_event(
        api, r4["retiree"]["id"], plan_year_id, pre65_core_id, review=True
    )
    assert under_review["status"] == "UNDER_REVIEW"

    return {
        "plan_year_id": plan_year_id,
        "pre65_core_id": pre65_core_id,
        "exch_hra_id": exch_hra["id"],
        "submitted_id": submitted["id"],
        "under_review_id": under_review["id"],
    }


def test_plan_year_close_closes_active_options_and_spares_the_draft_option(api):
    """Closing the year moves ACTIVE options to CLOSED_TO_NEW and nothing else.

    PRD 3.1: "The `OPEN → CLOSED` move is where a plan year sheds its in-flight
    work, and it does so in two chained hops. Hop one closes the catalogue: every
    plan option of that year whose `status` is `ACTIVE` moves to
    `CLOSED_TO_NEW`, in `created_at` ascending order, each such option's
    `version` incrementing." The EXCH-HRA option was never activated, so it is
    outside hop one and stays DRAFT.

    Design: Difficulty/transitive_cascade/plan_year_close_denies_open_elections_depth_three
    """
    state = _open_year_with_two_pending_elections(api)
    before = fx.reload_plan_option(api, state["pre65_core_id"])

    fx.advance_plan_year(api, state["plan_year_id"], "CLOSED")

    plan_year = fx.reload_plan_year(api, state["plan_year_id"])
    assert plan_year["status"] == "CLOSED"

    closed_option = fx.reload_plan_option(api, state["pre65_core_id"])
    assert closed_option["status"] == "CLOSED_TO_NEW"
    assert closed_option["version"] > before["version"]

    untouched = fx.reload_plan_option(api, state["exch_hra_id"])
    assert untouched["status"] == "DRAFT"


def test_plan_year_close_denies_the_elections_on_the_closed_option(api):
    """The third hop denies both in-flight elections with PLAN_CLOSED.

    PRD 3.1: "Hop two is caused by hop one rather than by the plan-year change
    itself: for each option hop one just moved to `CLOSED_TO_NEW`, every election
    event whose `requested_plan_option_id` names that option and whose `status`
    is `SUBMITTED` or `UNDER_REVIEW` moves to `DENIED` with `denial_reason_code`
    set to `PLAN_CLOSED`, again in `created_at` ascending order, each such
    event's `version` incrementing." Denial is not approval, so nothing
    materialises: no enrollment is created and enrolled_count stays 0.

    Design: Difficulty/transitive_cascade/plan_year_close_denies_open_elections_depth_three
    """
    state = _open_year_with_two_pending_elections(api)

    fx.advance_plan_year(api, state["plan_year_id"], "CLOSED")

    for election_id in (state["submitted_id"], state["under_review_id"]):
        election = fx.reload_election_event(api, election_id)
        assert election["status"] == "DENIED"
        assert election["denial_reason_code"] == "PLAN_CLOSED"
        assert election["resulting_enrollment_id"] is None

    assert fx.reload_plan_option(api, state["pre65_core_id"])["enrolled_count"] == 0
