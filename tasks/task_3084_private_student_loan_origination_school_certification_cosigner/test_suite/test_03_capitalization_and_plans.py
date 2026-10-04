"""Capitalization at repayment entry and the repaid-plan payment formula."""
from test_helpers import (
    ERR_AMOUNT_OUT_OF_RANGE,
    TEST_USERS,
    assert_loan,
    assert_repayment_plan,
    book_accrual,
    enter_repayment,
    get_success_data,
    record_enrollment,
    setup_certified_loan,
    setup_loan_in_repayment,
    submit_standard_plan,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client


def _approved_grace_loan(disbursed_cents=800000):
    """IN_SCHOOL -> GRACE loan with the disbursed principal fully on the books."""
    orig = setup_certified_loan(
        certified_amount_cents=disbursed_cents,
        requested_amount_cents=disbursed_cents,
        cost_of_attendance_cents=disbursed_cents + 50000,
        other_aid_cents=50000,
        disburse=True,
        disbursement_amount_cents=disbursed_cents,
    )
    record_enrollment(orig, "GRADUATED")
    orig.loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    return orig


def test_capitalization_at_the_exact_cap_absorbs_the_whole_unpaid_balance(api):
    """PRD §3.5: "the loan's `unpaid_interest_cents` as of the transition is compared
    against a cap equal to ten percent of the loan's disbursed principal, rounded
    half up to the cent, and the amount actually capitalized is the lesser of the two.
    At the exact boundary, when the unpaid interest equals the cap, the whole unpaid
    amount is capitalized — the comparison is inclusive at the cap."

    Design: Difficulty/combinatorial_formula/capitalized_interest_gate_at_the_exact_cap_boundary
    """
    orig = _approved_grace_loan(800000)
    book_accrual(orig.loan["id"], window_months=32)
    pre = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert pre["unpaid_interest_cents"] == 80000, "32 months * 2500"
    assert pre["max_allowed_capitalization_cents"] == 80000, "10 percent of 800000"

    plan = submit_standard_plan(orig.loan["id"])
    get_success_data(client.approve_plan(plan["id"], TEST_USERS["servicer_headers"]))
    loan = enter_repayment(orig.loan["id"])

    assert loan["lifetime_capitalized_interest_cents"] == 80000
    assert loan["unpaid_interest_cents"] == 0
    assert loan["principal_cents"] == 880000
    assert loan["current_balance_cents"] == 880000
    assert loan["loan_status"] == "REPAYMENT"
    assert_loan(loan)


def test_capitalization_stamps_the_repayment_entry_date_and_books_the_ledger_row(api):
    """PRD §3.5: "The transition stamps `repayment_entered_date` from the logical clock
    and books a single capitalization"
    PRD §3.5: "The capitalization is booked as an `InterestAccrualEntry` with
    `entry_status` `CAPITALIZED` and `source_event` `CAPITALIZATION`"

    Design: Difficulty/combinatorial_formula/capitalized_interest_gate_at_the_exact_cap_boundary
    """
    orig = _approved_grace_loan(800000)
    book_accrual(orig.loan["id"], window_months=32)
    plan = submit_standard_plan(orig.loan["id"])
    get_success_data(client.approve_plan(plan["id"], TEST_USERS["servicer_headers"]))
    loan = enter_repayment(orig.loan["id"])

    assert loan["repayment_entered_date"] is not None
    assert loan["earned_capitalization_count"] == 1
    entries = validate_success(
        client.list_accrual_entries(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    capitalized = [e for e in entries if e["entry_status"] == "CAPITALIZED"]
    assert len(capitalized) == 1
    assert capitalized[0]["source_event"] == "CAPITALIZATION"
    assert capitalized[0]["accrued_amount_cents"] == 80000


def test_entering_repayment_requires_an_active_plan(api):
    """PRD §3.5: "The servicer moves a loan from `GRACE` into `REPAYMENT`, which
    requires that the loan is in `GRACE` and that at least one repayment plan child
    is `ACTIVE`"

    Design: Corner/validations/entering_repayment_without_an_active_plan_returns_plan_required
    """
    from test_helpers import ERR_PLAN_REQUIRED

    orig = _approved_grace_loan(800000)
    book_accrual(orig.loan["id"], window_months=1)
    response = client.enter_repayment(orig.loan["id"], TEST_USERS["servicer_headers"])
    validate_error(response, ERR_PLAN_REQUIRED)


def test_level_monthly_payment_is_the_annuity_on_the_pinned_snapshot(api):
    """PRD §3.6: "The level monthly payment is the standard annuity instalment that
    amortizes the pinned principal at the pinned monthly rate over the requested term.
    The pinned annual rate is divided by one hundred and then by twelve to obtain the
    monthly rate; the payment is the product of the pinned principal and the monthly
    rate, divided by one minus the quantity one plus the monthly rate raised to the
    negative of the term in months"

    Design: Difficulty/combinatorial_formula/capitalized_interest_gate_at_the_exact_cap_boundary
    """
    orig = setup_loan_in_repayment(plan_type="STANDARD", term_months=120)
    plans = validate_success(
        client.list_repayment_plans(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    plan = plans[0]
    assert plan["principal_snapshot_cents"] == 805000
    assert plan["rate_snapshot_pct"] == 3.75
    assert plan["term_months"] == 120
    assert plan["monthly_payment_cents"] == 8055
    assert plan["plan_status"] == "ACTIVE"
    assert_repayment_plan(plan)


def test_a_plan_whose_solved_payment_is_below_the_floor_cannot_be_activated(api):
    """PRD §3.6: "A plan whose solved `monthly_payment_cents` falls below the
    five-thousand-cent floor cannot be activated, and the attempt is refused with
    `ERR_AMOUNT_OUT_OF_RANGE`."

    Design: Corner/endpoints/amortising_a_plan_below_the_minimum_monthly_payment_is_rejected
    """
    orig = setup_loan_in_repayment(periods=30)
    version = validate_success(
        client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"])
    )["version"]
    long_plan = get_success_data(
        client.create_repayment_plan(
            orig.loan["id"],
            {"plan_type": "STANDARD", "term_months": 100000, "expected_loan_version": version},
            orig.applicant_headers,
        )
    )
    assert long_plan["monthly_payment_cents"] < 5000, "a 100000-month term solves below the floor"

    response = client.approve_plan(long_plan["id"], TEST_USERS["servicer_headers"])
    validate_error(response, ERR_AMOUNT_OUT_OF_RANGE)

    loan = validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))
    assert loan["active_plan_type"] == "STANDARD", "the pending plan never activated"
    stored = validate_success(
        client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert stored["version"] >= 1


def test_nested_child_existence_precedes_the_payment_floor_check(api):
    """PRD §2.9: "When the resource addressed is a loan child — a repayment plan, a
    payment, a disbursement or a cosigner release application — and it either does
    not exist or belongs to a different loan than the one named in the path, the
    failure is `ERR_LOAN_CHILD_NOT_FOUND`."
    PRD §2.12: "State preconditions then apply... Business-safety and compliance
    checks follow the state checks, and they run before all fiscal checks"

    Design: Difficulty/combinatorial_formula/capitalized_interest_gate_at_the_exact_cap_boundary
    """
    from test_helpers import ERR_LOAN_CHILD_NOT_FOUND, NON_EXISTENT_UUID

    orig = setup_loan_in_repayment(periods=30)
    response = client.approve_plan(NON_EXISTENT_UUID, TEST_USERS["servicer_headers"])
    validate_error(response, ERR_LOAN_CHILD_NOT_FOUND)