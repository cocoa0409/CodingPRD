"""Delinquency, default, trustee program health, and the sweep
(PRD §3.7, §3.8, §2.4)."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    TEST_USERS,
    create_trustee,
    get_borrower,
    get_loan,
    get_trustee,
    installments_by_number,
    make_payment,
    run_sweeps,
    set_clock,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]


def _parse_ts(ts):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _due_date(loan_id, number=1):
    return _parse_ts(installments_by_number(loan_id)[number]["due_date"])


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_repaying_delinquent_cycle_clears_delinquent_since(api):
    """PRD §3.7: "A `REPAYING` loan whose earliest non-`PAID` installment is
    more than 14 days past due moves to `DELINQUENT`, stamps
    `delinquent_since`, and records a delinquency coaching message for the
    borrower — coaching, never collections."
    PRD §3.7: "if the loan was `DELINQUENT` and the payment leaves no
    non-`PAID` installment more than 14 days past its `due_date`, the loan
    cures back to `REPAYING` and `delinquent_since` clears to null."

    Design: Difficulty/non_linear_state_machine/loan_repaying_delinquent_cycle
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)
    due = _due_date(ns.loan["id"])

    # 15 days past due -> DELINQUENT.
    set_clock(_iso(due + timedelta(days=15)))
    sweep = run_sweeps()
    assert sweep["loans_delinquent"] == 1
    loan = get_loan(ns.loan["id"])
    assert loan["status"] == "DELINQUENT"
    assert loan["delinquent_since"] is not None

    # Paying the installment in full cures the loan back to REPAYING.
    make_payment(loan, ns.borrower, 100_000)
    loan = get_loan(ns.loan["id"])
    assert loan["status"] == "PAID_OFF", "single-installment loan pays off"
    assert loan["delinquent_since"] is None


def test_delinquency_cycle_returns_to_repaying_on_cure(api):
    """PRD §3.7: "if the loan was `DELINQUENT` and the payment leaves no
    non-`PAID` installment more than 14 days past its `due_date`, the loan
    cures back to `REPAYING` and `delinquent_since` clears to null."

    Design: Difficulty/non_linear_state_machine/loan_repaying_delinquent_cycle
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(
        principal_cents=200_000,
        term_months=3,
        endorsement_amounts=[25_000, 25_000, 25_000, 25_000],
        trustee_endorsement_amount=50_000,
        contribution_amounts=[50_000],
    )
    due1 = _due_date(ns.loan["id"], 1)

    # 15 days past installment 1 -> DELINQUENT.
    set_clock(_iso(due1 + timedelta(days=15)))
    run_sweeps()
    loan = get_loan(ns.loan["id"])
    assert loan["status"] == "DELINQUENT"
    delinquent_since = loan["delinquent_since"]
    assert delinquent_since is not None

    # Pay installment 1 in full (66666); the waterfall spills the rest onto
    # installment 2, which is not yet past due, so the loan cures.
    make_payment(loan, ns.borrower, 100_000)
    loan = get_loan(ns.loan["id"])
    assert loan["status"] == "REPAYING"
    assert loan["delinquent_since"] is None


def test_delinquency_and_default_grace_boundaries(api):
    """PRD §3.7: "A `REPAYING` loan whose earliest non-`PAID` installment is
    more than 14 days past due moves to `DELINQUENT`"
    PRD §3.7: "A `DELINQUENT` loan whose earliest non-`PAID` installment is
    more than 74 days past due — the 14-day delinquency window plus a 60-day
    default horizon — moves to `DEFAULTED`, stamps `defaulted_at`"

    Design: Difficulty/resource_temporal_overlap/delinquency_grace_window_boundary
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)
    due = _due_date(ns.loan["id"])

    # 13 days past due: inside the grace window.
    set_clock(_iso(due + timedelta(days=13)))
    sweep = run_sweeps()
    assert sweep["loans_delinquent"] == 0
    assert get_loan(ns.loan["id"])["status"] == "REPAYING"

    # 15 days past due: flips to DELINQUENT.
    set_clock(_iso(due + timedelta(days=15)))
    sweep = run_sweeps()
    assert sweep["loans_delinquent"] == 1
    assert get_loan(ns.loan["id"])["status"] == "DELINQUENT"

    # Exactly 74 days past due: "more than 74" is strict — still DELINQUENT.
    set_clock(_iso(due + timedelta(days=74)))
    sweep = run_sweeps()
    assert sweep["loans_defaulted"] == 0
    assert get_loan(ns.loan["id"])["status"] == "DELINQUENT"


def test_default_at_75_days_restricts_the_borrower(api):
    """PRD §3.7: "A `DELINQUENT` loan whose earliest non-`PAID` installment
    is more than 74 days past due — the 14-day delinquency window plus a
    60-day default horizon — moves to `DEFAULTED`, stamps `defaulted_at`, and
    cascades hard: the borrower's `status` becomes `RESTRICTED` with
    `restricted_since` set to the sweep time and `defaulted_loan_count`
    incremented"

    Design: Difficulty/resource_temporal_overlap/delinquency_grace_window_boundary
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(principal_cents=100_000, term_months=3)
    due = _due_date(ns.loan["id"])

    set_clock(_iso(due + timedelta(days=75)))
    sweep = run_sweeps()
    assert sweep["loans_defaulted"] == 1

    loan = get_loan(ns.loan["id"])
    assert loan["status"] == "DEFAULTED"
    assert loan["defaulted_at"] is not None

    borrower = get_borrower(ns.borrower["id"])
    assert borrower["status"] == "RESTRICTED"
    assert borrower["restricted_since"] is not None
    assert borrower["defaulted_loan_count"] == 1


def _three_trustee_loans(trustee):
    """Three trustee-vouched 100000/3-month loans from three borrowers,
    funded by a 25000 trustee endorsement plus four lender endorsements
    (57500) and a closing 17500 contribution. Returns the namespaces.
    """
    namespaces = []
    for _ in range(3):
        ns = fx.create_trustee_funded_loan(
            principal_cents=100_000,
            term_months=3,
            trustee=trustee,
            trustee_endorsement_amount=25_000,
            endorsement_amounts=[50_000, 2_500, 2_500, 2_500],
            contribution_amounts=[17_500],
        )
        namespaces.append(ns)
    return namespaces

def test_trustee_default_rate_auto_suspension(api):
    """PRD §3.8: "The sweep suspends a trustee automatically when its
    `default_rate_bps` exceeds 2,000 basis points (20%) across at least 3
    terminally resolved endorsed loans, setting `suspension_reason` to
    `DEFAULT_RATE`."
    PRD §3.8: "The `default_rate_bps` is 0 while the trustee has no
    terminally resolved endorsed loans, and otherwise ten thousand times
    `endorsed_defaulted_count` divided by `endorsed_terminal_count`, rounded
    half-up to integer basis points"

    Design: Corner/calculations/trustee_default_rate_auto_suspension
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=1_000_000)
    namespaces = _three_trustee_loans(trustee)

    # Two loans repaid in full -> PAID_OFF; the third left to default.
    for ns in namespaces[:2]:
        make_payment(ns.loan, ns.borrower, 100_000)

    trustee_mid = get_trustee(trustee["id"])
    assert trustee_mid["endorsed_terminal_count"] == 2
    assert trustee_mid["status"] == "ACTIVE", "below the 3-terminal minimum"

    # Default the third loan: due date + 75 days.
    due = _due_date(namespaces[2].loan["id"])
    set_clock(_iso(due + timedelta(days=75)))
    sweep = run_sweeps()
    assert sweep["loans_defaulted"] == 1

    loan3 = get_loan(namespaces[2].loan["id"])
    assert loan3["status"] == "DEFAULTED"
    borrower3 = get_borrower(namespaces[2].borrower["id"])
    assert borrower3["status"] == "RESTRICTED"

    trustee_after = get_trustee(trustee["id"])
    assert trustee_after["endorsed_terminal_count"] == 3
    assert trustee_after["endorsed_defaulted_count"] == 1
    # round_half_up(10000 * 1/3) = 3333 > 2000 with >= 3 terminal loans.
    assert trustee_after["default_rate_bps"] == 3333
    assert trustee_after["status"] == "SUSPENDED"
    assert trustee_after["suspension_reason"] == "DEFAULT_RATE"


def test_trustee_below_minimum_terminal_count_not_suspended(api):
    """PRD §3.8: "The sweep suspends a trustee automatically when its
    `default_rate_bps` exceeds 2,000 basis points (20%) across at least 3
    terminally resolved endorsed loans"

    Design: Corner/calculations/trustee_default_rate_auto_suspension
    """
    set_clock()
    trustee = create_trustee(endorsement_limit_cents=1_000_000)
    ns = fx.create_trustee_funded_loan(
        principal_cents=100_000,
        term_months=3,
        trustee=trustee,
        trustee_endorsement_amount=25_000,
        endorsement_amounts=[50_000, 2_500, 2_500, 2_500],
        contribution_amounts=[17_500],
    )
    # One defaulting loan: rate would be 10000 bps but the terminal count is
    # 1 < 3, so no auto-suspension.
    due = _due_date(ns.loan["id"])
    set_clock(_iso(due + timedelta(days=75)))
    sweep = run_sweeps()
    assert sweep["loans_defaulted"] == 1

    trustee_after = get_trustee(trustee["id"])
    assert trustee_after["endorsed_terminal_count"] == 1
    assert trustee_after["endorsed_defaulted_count"] == 1
    assert trustee_after["default_rate_bps"] == 10_000
    assert trustee_after["status"] == "ACTIVE", "minimum-count gate blocks suspension"


def test_manual_suspend_and_reinstate_cycle(api):
    """PRD §3.8: "A `PlatformAdmin` may suspend an `ACTIVE` trustee manually,
    setting `suspension_reason` to `MANUAL`."
    PRD §3.8: "Reinstatement is manual only — a `PlatformAdmin` returns a
    `SUSPENDED` trustee to `ACTIVE` and resets `suspension_reason` to `NONE`."
    PRD §3.8: "Requesting either transition from the wrong state is
    `ERR_INVALID_STATE`."

    Design: Corner/calculations/trustee_default_rate_auto_suspension
    """
    from test_helpers import validate_error
    from test_helpers.api_errors import ERR_INVALID_STATE

    set_clock()
    trustee = create_trustee()

    suspended = validate_success(client.suspend_trustee(trustee["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "MANUAL"

    resp = client.suspend_trustee(trustee["id"], ADMIN)
    validate_error(resp, ERR_INVALID_STATE, expected_status=409)

    reinstated = validate_success(client.reinstate_trustee(trustee["id"], ADMIN))
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["suspension_reason"] == "NONE"

    resp = client.reinstate_trustee(trustee["id"], ADMIN)
    validate_error(resp, ERR_INVALID_STATE, expected_status=409)
