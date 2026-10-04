"""Disbursement and the two-stage repayment schedule (PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    assert_installment,
    assert_loan,
    create_trustee,
    finalize_schedule,
    get_application,
    get_loan,
    installments_by_number,
    list_installments,
    make_payment,
    set_clock,
    validate_error,
    validate_paginated,
)
from test_helpers import api_client as client
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APPLICATION_NOT_FUNDED,
    ERR_SCHEDULE_ALREADY_FINAL,
)

ADMIN = TEST_USERS["admin_headers"]


def _disbursed_500k_over_5():
    """Trustee-vouched 500000 / 5-month loan: 4 x 50000 endorsements + 100000
    trustee endorsement (private 300000) + 100000 + 100000 public
    contributions, the second of which lands exactly on the request."""
    trustee = create_trustee(endorsement_limit_cents=3_000_000)
    return fx.create_disbursed_loan(
        principal_cents=500_000,
        term_months=5,
        trustee=trustee,
        endorsement_amounts=[50_000, 50_000, 50_000, 50_000],
        trustee_endorsement_amount=100_000,
        contribution_amounts=[100_000, 100_000],
    )


def test_provisional_schedule_splits_evenly_with_remainder_last(api):
    """PRD §3.6: "Under the provisional schedule the split is even: the
    `provisional_base_cents` is the principal floor-divided by the term,
    installments 1 through *N*−1 carry that base as their `amount_due_cents`,
    and the final installment absorbs the entire rounding remainder."
    PRD §3.6: "the loan starts in `REPAYING` with `schedule_status` of
    `PROVISIONAL`."

    Design: Difficulty/combinatorial_formula/provisional_vs_final_schedule_rounding_order
    """
    set_clock()
    ns = _disbursed_500k_over_5()
    loan = ns.loan
    assert loan["status"] == "REPAYING"
    assert loan["schedule_status"] == "PROVISIONAL"
    assert loan["provisional_base_cents"] == 100_000
    assert_loan(loan)

    installments = list_installments(loan["id"])
    assert len(installments) == 5, "one installment per term month"
    by_number = {i["installment_number"]: i for i in installments}
    for n in range(1, 6):
        inst = by_number[n]
        assert_installment(inst)
        assert inst["amount_due_cents"] == 100_000, f"installment {n}"
        assert inst["amount_paid_cents"] == 0
        assert inst["remaining_cents"] == 100_000
        assert inst["status"] == "PENDING"


def test_finalize_rewrites_schedule_with_remainder_first(api):
    """PRD §3.6: "The final schedule deliberately front-loads the first
    installment by 100 cents plus the remainder: the `final_base_cents` is
    `principal_cents` minus 100, floor-divided by the term; installments 2
    through *N* carry that base; and installment 1 carries the
    `final_first_cents` — whatever remains of the principal after the other
    *N*−1 installments take the reduced base."
    PRD §3.6: "Finalization rewrites every installment's `amount_due_cents`,
    stores both computed bases on the loan, flips `schedule_status` to
    `FINAL`, and bumps the loan's `version`."

    Design: Difficulty/combinatorial_formula/provisional_vs_final_schedule_rounding_order
    """
    set_clock()
    ns = _disbursed_500k_over_5()
    loan = ns.loan

    finalized = finalize_schedule(loan)
    assert finalized["schedule_status"] == "FINAL"
    # floor((500000 - 100) / 5) = 99980
    assert finalized["final_base_cents"] == 99_980
    # 500000 - 4*99980 = 100080
    assert finalized["final_first_cents"] == 100_080
    assert finalized["version"] > loan["version"]

    by_number = installments_by_number(loan["id"])
    assert by_number[1]["amount_due_cents"] == 100_080
    for n in range(2, 6):
        assert by_number[n]["amount_due_cents"] == 99_980
    total = sum(i["amount_due_cents"] for i in by_number.values())
    assert total == 500_000, "the final schedule preserves the principal"


def test_finalize_schedule_twice_rejected(api):
    """PRD §3.6: "A `PlatformAdmin` may replace the provisional schedule with
    the final schedule exactly once, guarded by `expected_loan_version`, and
    only while the loan is `REPAYING`, the `schedule_status` is still
    `PROVISIONAL`, and no payment has touched any installment (every
    `amount_paid_cents` still 0) — otherwise the request fails with
    `ERR_SCHEDULE_ALREADY_FINAL` (HTTP 409)."

    Design: Corner/validations/finalize_schedule_twice_rejected
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)
    finalized = finalize_schedule(ns.loan)

    resp = client.finalize_schedule(
        ns.loan["id"], {"expected_loan_version": finalized["version"]}, ADMIN
    )
    validate_error(resp, ERR_SCHEDULE_ALREADY_FINAL, expected_status=409)
    assert get_loan(ns.loan["id"])["schedule_status"] == "FINAL"


def test_finalize_after_payment_is_rejected(api):
    """PRD §3.6: "A `PlatformAdmin` may replace the provisional schedule with
    the final schedule exactly once, guarded by `expected_loan_version`, and
    only while the loan is `REPAYING`, the `schedule_status` is still
    `PROVISIONAL`, and no payment has touched any installment (every
    `amount_paid_cents` still 0) — otherwise the request fails with
    `ERR_SCHEDULE_ALREADY_FINAL` (HTTP 409)."

    Design: Corner/validations/finalize_schedule_twice_rejected
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)
    make_payment(ns.loan, ns.borrower, 1_000)
    loan = get_loan(ns.loan["id"])

    resp = client.finalize_schedule(
        loan["id"], {"expected_loan_version": loan["version"]}, ADMIN
    )
    validate_error(resp, ERR_SCHEDULE_ALREADY_FINAL, expected_status=409)


def test_disburse_before_funded_returns_application_not_funded(api):
    """PRD §3.6: "Disbursement is a `PlatformAdmin` act on a `FUNDED`
    application — attempting it in any other state is rejected with
    `ERR_APPLICATION_NOT_FUNDED` (HTTP 409)"

    Design: Corner/state_machines/disburse_before_funded_returns_invalid_state
    """
    set_clock()
    ns = fx.create_funded_application(
        principal_cents=300_000,
        term_months=3,
        trustee=create_trustee(endorsement_limit_cents=1_000_000),
        endorsement_amounts=[25_000, 25_000, 25_000, 25_000],
        trustee_endorsement_amount=50_000,
        contribution_amounts=[50_000],
    )
    # Funded total is 200000 of 300000: still PUBLIC_FUNDRAISING.
    application = ns.application
    assert application["status"] == "PUBLIC_FUNDRAISING"
    assert application["funded_total_cents"] == 200_000

    resp = client.disburse_application(
        application["id"],
        {"expected_application_version": application["version"]},
        ADMIN,
    )
    validate_error(resp, ERR_APPLICATION_NOT_FUNDED, expected_status=409)


def test_disburse_converts_endorsements_and_creates_one_loan(api):
    """PRD §3.6: "Disbursement creates the `Loan`: at most one loan ever
    exists per application, its `borrower_id`, `principal_cents` (equal to
    the application's `requested_amount_cents`), and `term_months` are copied
    from the application, `disbursed_at` is stamped, and the loan starts in
    `REPAYING` with `schedule_status` of `PROVISIONAL`."
    PRD §3.6: "In the same act, every `ACTIVE` endorsement and contribution
    on the application becomes `CONVERTED` with `resolved_at` set to the
    disbursement timestamp"

    Design: Corner/state_machines/disburse_before_funded_returns_invalid_state
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)
    loan = ns.loan
    assert loan["principal_cents"] == 100_000
    assert loan["term_months"] == 3
    assert loan["borrower_id"] == ns.borrower["id"]
    assert loan["loan_application_id"] == ns.application["id"]
    assert loan["disbursed_at"], "disbursed_at is stamped"

    endorsements, _ = validate_paginated(
        client.list_application_endorsements(ns.application["id"], ADMIN)
    )
    assert endorsements, "the pipeline created endorsements"
    for endorsement in endorsements:
        assert endorsement["status"] == "CONVERTED"
        assert endorsement["resolved_at"] is not None

    # A second disbursement attempt finds no FUNDED application to act on.
    resp = client.disburse_application(
        ns.application["id"],
        {"expected_application_version": ns.application["version"]},
        ADMIN,
    )
    assert resp.status_code == 409, "at most one loan per application"


def test_contribution_response_reflects_funded_flip_immediately(api):
    """PRD §3.5: "The moment a contribution brings `funded_total_cents` to
    exactly the requested amount, the application transitions automatically
    to `FUNDED` and stamps `funded_at`."

    Design: Corner/consistency_model/contribution_response_reflects_funded_flip_immediately
    """
    set_clock()
    ns = fx.create_private_fundraising_application(
        trustee=create_trustee(endorsement_limit_cents=500_000),
        requested_amount_cents=150_000,
        term_months=3,
    )
    application, _ = fx.meet_quorum_with_endorsements(
        ns, [12_500, 12_500, 12_500, 12_500], trustee_amount=50_000
    )
    application = fx.open_public(application, ns.borrower)
    lender = fx.create_lender(deposit_cents=500_000)

    fx.contribute(application, lender, 50_000)
    application = get_application(application["id"])
    assert application["status"] == "FUNDED"
    assert application["funded_at"] is not None
    assert application["funded_total_cents"] == 150_000
