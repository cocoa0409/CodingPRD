"""Composite setup helpers that build the preconditions tests need.

Every helper builds its state from scratch through PRD-declared endpoints,
because the harness restarts the server (and therefore empties the database)
before every individual test.
"""
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_UTC, TEST_DEFAULTS, ANNUAL_PAYOUT_CAP_CENTS,
)
from .factories import (
    create_branch_payload, create_advisor_payload, create_supervisor_enrollment_payload,
    create_advisor_link_payload, create_account_payload, create_revenue_entry_payload,
    create_payout_period_payload, create_payout_line_payload, create_payout_loan_payload,
    create_expense_pass_through_payload, create_transition_payload,
    create_retention_contest_payload,
)
from .test_users import TEST_USERS, make_advisor_ops_headers

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
BRANCH_MANAGER = TEST_USERS["branch_manager_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── Tier 0: Logical clock ────────────────────────────

def set_clock(current_utc=DEFAULT_CLOCK_UTC):
    """Set the logical clock. Every window-sensitive scenario needs this."""
    return get_success_data(api_client.set_clock(current_utc, PLATFORM_ADMIN))


# ─── Tier 1: Branch and supervision escalation ────────

def create_branch(branch_code=TEST_DEFAULTS["BRANCH_CODE"],
                  name=TEST_DEFAULTS["BRANCH_NAME"],
                  transmittal_account=TEST_DEFAULTS["TRANSMITTAL_ACCOUNT"],
                  osj_name=TEST_DEFAULTS["OSJ_NAME"], **overrides):
    return get_success_data(api_client.create_branch(
        create_branch_payload(branch_code=branch_code, name=name,
                              transmittal_account=transmittal_account,
                              osj_name=osj_name, **overrides),
        PLATFORM_ADMIN))


def refresh_branch(branch_id):
    return get_success_data(api_client.get_branch(branch_id, PLATFORM_ADMIN))


def create_advisor(advisor_code, crd_number, full_name, **overrides):
    return get_success_data(api_client.create_advisor(
        create_advisor_payload(advisor_code, crd_number, full_name, **overrides),
        PLATFORM_ADMIN))


def refresh_advisor(advisor_id):
    return get_success_data(api_client.get_advisor(advisor_id, PLATFORM_ADMIN))


def open_supervisor_enrollment(branch_code, advisor_code, effective_date="2026-09-01"):
    return get_success_data(api_client.create_supervisor_enrollment(
        create_supervisor_enrollment_payload(branch_code, advisor_code, effective_date),
        PLATFORM_ADMIN))


def enroll_supervisor(branch_code, advisor_code, effective_date="2026-09-01"):
    """Open a supervisory enrollment and advance it to ENROLLED, escalating the branch."""
    enrollment = open_supervisor_enrollment(branch_code, advisor_code, effective_date)
    return get_success_data(api_client.set_supervisor_enrollment_state(
        enrollment["id"],
        {"to_status": "ENROLLED", "expected_branch_version": _branch_version(branch_code)},
        PLATFORM_ADMIN))


def revoke_supervisor_enrollment(enrollment_id, branch_code):
    """Revoke an ENROLLED supervisor enrollment, demoting the branch."""
    return api_client.set_supervisor_enrollment_state(
        enrollment_id,
        {"to_status": "REVOKED", "expected_branch_version": _branch_version(branch_code)},
        PLATFORM_ADMIN)


def _branch_version(branch_code):
    """Read the branch's current version by its business key."""
    data, _meta = _list_page(api_client.list_branches(PLATFORM_ADMIN))
    for row in data:
        if row["branch_code"] == branch_code:
            return row["version"]
    raise AssertionError(f"Setup failed: branch {branch_code} not found")


def _branch_id(branch_code):
    data, _meta = _list_page(api_client.list_branches(PLATFORM_ADMIN))
    for row in data:
        if row["branch_code"] == branch_code:
            return row["id"]
    raise AssertionError(f"Setup failed: branch {branch_code} not found")


def _list_page(response):
    """Return (rows, meta) for a list response without asserting pagination shape."""
    data = get_success_data(response)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data, {}


def _list_rows(response):
    """The rows of a list response.

    A list endpoint's 2xx envelope carries `response_type: "array"`, so the
    `data` field is the array itself.  `get_success_data` performs the envelope
    validation and hands the array back; this helper is the read-through used by
    every fixture that consumes a list.
    """
    data = get_success_data(response)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data


def create_advisor_link(advisor, branch_code, is_supervisor=False,
                        assignment_type="PRIMARY"):
    return get_success_data(api_client.create_advisor_link(
        create_advisor_link_payload(advisor["advisor_code"], branch_code,
                                    is_supervisor=is_supervisor,
                                    assignment_type=assignment_type),
        PLATFORM_ADMIN))


def set_advisor_link_state(link_id, to_status, branch_code):
    return api_client.set_advisor_link_state(
        link_id,
        {"to_status": to_status, "expected_branch_version": _branch_version(branch_code)},
        PLATFORM_ADMIN)


# ─── Tier 1: Advisor lifecycle ────────────────────────

def create_loan(advisor, principal_cents=500_000, amortization_rate_bps=2000,
                forgiveness_milestone_pct=100):
    return get_success_data(api_client.create_payout_loan(
        create_payout_loan_payload(advisor["advisor_code"],
                                   principal_cents=principal_cents,
                                   amortization_rate_bps=amortization_rate_bps,
                                   forgiveness_milestone_pct=forgiveness_milestone_pct),
        PLATFORM_ADMIN))


def enroll_advisor(advisor):
    """PROSPECT -> ONBOARDING. Requires a REQUESTED/ACTIVE loan on file."""
    current = refresh_advisor(advisor["id"])
    return get_success_data(api_client.enroll_advisor(
        advisor["id"], {"expected_advisor_version": current["version"]},
        make_advisor_ops_headers(advisor["id"])))


def affiliate_advisor(advisor, affiliation_model="IC"):
    """ONBOARDING -> ACTIVE. Requires an ACTIVE branch and a portable book."""
    current = refresh_advisor(advisor["id"])
    return get_success_data(api_client.affiliate_advisor(
        advisor["id"],
        {"affiliation_model": affiliation_model,
         "expected_advisor_version": current["version"]},
        make_advisor_ops_headers(advisor["id"])))


def activate_advisor(advisor, affiliation_model="IC"):
    enroll_advisor(advisor)
    return affiliate_advisor(advisor, affiliation_model)


def setup_supervised_branch(branch_code=TEST_DEFAULTS["BRANCH_CODE"],
                            supervisor_advisor_code=None, crd_number="9000001",
                            full_name="Branch Supervisor"):
    set_clock()
    """Create a branch and escalate it to SUPERVISED with one enrolled supervisor."""
    branch = create_branch(branch_code=branch_code)
    supervisor = create_advisor(supervisor_advisor_code or f"{branch_code}-SUP",
                                crd_number, full_name,
                                primary_branch_code=branch_code,
                                ingested_book_total_cents=500_000_000,
                                book_transferred_cents=400_000_000)
    enroll_supervisor(branch_code, supervisor["advisor_code"])
    link = create_advisor_link(supervisor, branch_code, is_supervisor=True)
    return refresh_branch(branch["id"]), supervisor, link


def setup_active_advisor(advisor_code="A-1001", crd_number="1234567",
                         full_name="Iris Calloway", affiliation_model="IC",
                         branch_code=TEST_DEFAULTS["BRANCH_CODE"],
                         ingested_book_total_cents=500_000_000,
                         book_transferred_cents=400_000_000,
                         protocol_eligible=True, eo_coverage_level="STANDARD",
                         principal_cents=500_000, amortization_rate_bps=2000,
                         forgiveness_milestone_pct=100,
                         own_supervisor=True, extra_links=None):
    """An ACTIVE advisor on a supervised branch, with a REQUESTED->ACTIVE loan.

    By default the advisor is its own branch supervisor, which is what escalates
    the branch to ACTIVE so the affiliation can succeed.
    """
    set_clock()
    branch = create_branch(branch_code=branch_code)
    advisor = create_advisor(advisor_code, crd_number, full_name,
                             primary_branch_code=branch_code,
                             affiliation_model=affiliation_model,
                             ingested_book_total_cents=ingested_book_total_cents,
                             book_transferred_cents=book_transferred_cents,
                             protocol_eligible=protocol_eligible,
                             eo_coverage_level=eo_coverage_level)
    enrollment = None
    supervisor_link = None
    if own_supervisor:
        enrollment = enroll_supervisor(branch_code, advisor_code)
        supervisor_link = create_advisor_link(advisor, branch_code, is_supervisor=True)
    for link in (extra_links or []):
        create_advisor_link(advisor, link["branch_code"],
                            is_supervisor=link.get("is_supervisor", False),
                            assignment_type=link.get("assignment_type", "SECONDARY"))
    loan = create_loan(advisor, principal_cents=principal_cents,
                       amortization_rate_bps=amortization_rate_bps,
                       forgiveness_milestone_pct=forgiveness_milestone_pct)
    activate_advisor(advisor, affiliation_model)
    return {
        "branch": refresh_branch(branch["id"]),
        "advisor": refresh_advisor(advisor["id"]),
        "loan": get_success_data(api_client.get_payout_loan(loan["id"], PLATFORM_ADMIN)),
        "supervisor_enrollment": enrollment,
        "supervisor_link": supervisor_link,
    }


def demote_branch(branch_code, enrollment_id=None, link_id=None):
    """Return a branch to UNSUPERVISED by revoking its last supervisor.

    Revoking the enrolled supervisor enrollment takes the branch down once no
    enrolled enrollment and no assigned supervisor link remains.
    """
    if link_id is not None:
        get_success_data(set_advisor_link_state(link_id, "INACTIVE", branch_code))
    if enrollment_id is not None:
        get_success_data(revoke_supervisor_enrollment(enrollment_id, branch_code))
    return refresh_branch(_branch_id(branch_code))


def setup_advisor_on_branch(advisor_code, branch_code, **advisor_overrides):
    """An ACTIVE advisor on a branch that is already supervised by someone else.

    Used when a test needs several advisors sharing one branch, so the branch is
    created once and the advisors are added on top of it.
    """
    advisor = create_advisor(advisor_code,
                             advisor_overrides.pop("crd_number", f"5{advisor_code[-5:]}"),
                             advisor_overrides.pop("full_name", "Branch Colleague"),
                             primary_branch_code=branch_code, **advisor_overrides)
    loan = create_loan(advisor,
                       principal_cents=advisor_overrides.get("principal_cents", 500_000))
    activate_advisor(advisor, advisor["affiliation_model"])
    return {"advisor": refresh_advisor(advisor["id"]), "loan": loan}


def setup_supervised_branch_with_advisor(supervisor_code="A-9001",
                                         advisor_code="A-1001", **advisor_overrides):
    """A supervised branch whose supervisor is a *different* advisor than the subject."""
    branch = create_branch()
    supervisor = create_advisor(supervisor_code, "9000001", "Branch Supervisor",
                                primary_branch_code=TEST_DEFAULTS["BRANCH_CODE"],
                                ingested_book_total_cents=800_000_000,
                                book_transferred_cents=640_000_000)
    enroll_supervisor(TEST_DEFAULTS["BRANCH_CODE"], supervisor_code)
    create_advisor_link(supervisor, TEST_DEFAULTS["BRANCH_CODE"], is_supervisor=True)

    advisor = create_advisor(advisor_code, advisor_overrides.pop("crd_number", "1234567"),
                             advisor_overrides.pop("full_name", "Subject Advisor"),
                             primary_branch_code=TEST_DEFAULTS["BRANCH_CODE"],
                             **advisor_overrides)
    loan = create_loan(advisor)
    activate_advisor(advisor, advisor["affiliation_model"])
    return {
        "branch": refresh_branch(branch["id"]),
        "supervisor": supervisor,
        "advisor": refresh_advisor(advisor["id"]),
        "loan": loan,
    }


def open_account(advisor, account_number, account_type="BROKERAGE",
                 balance_cents=10_000_000, annual_fee_cents=0, held_away=False):
    return get_success_data(api_client.create_account(
        create_account_payload(advisor["advisor_code"], account_number,
                               account_type=account_type,
                               balance_cents=balance_cents,
                               annual_fee_cents=annual_fee_cents,
                               held_away=held_away),
        make_advisor_ops_headers(advisor["id"])))


def open_period(branch_code=TEST_DEFAULTS["BRANCH_CODE"], year=2026, month=9,
                period_index=1):
    return get_success_data(api_client.create_payout_period(
        create_payout_period_payload(branch_code, year, month, period_index),
        BRANCH_MANAGER))


RETIREMENT_MONTH = 7
SEPTEMBER_MONTH = 9


def open_payout_line(advisor, period_id, projected_annual_production_cents):
    return get_success_data(api_client.open_payout_line(
        advisor["id"],
        create_payout_line_payload(period_id, projected_annual_production_cents),
        make_advisor_ops_headers(advisor["id"])))


def book_entry(advisor, account_id, gross_commission_cents,
               production_date="2026-09-03", product_type="EQUITY"):
    return get_success_data(api_client.create_revenue_entry(
        create_revenue_entry_payload(advisor["advisor_code"], account_id,
                                     gross_commission_cents,
                                     production_date=production_date,
                                     product_type=product_type),
        make_advisor_ops_headers(advisor["id"])))


def release_entry(entry, advisor):
    return get_success_data(api_client.release_revenue_entry(
        entry["id"], make_advisor_ops_headers(advisor["id"])))


def create_pass_through(advisor, period_id, category, billing_model="FLAT_MONTHLY"):
    return get_success_data(api_client.create_expense_pass_through(
        create_expense_pass_through_payload(advisor["advisor_code"], period_id,
                                            category, billing_model),
        BRANCH_MANAGER))


def advance_period(period_id, to_state, branch_code=TEST_DEFAULTS["BRANCH_CODE"],
                   role_headers=None):
    return get_success_data(api_client.set_payout_period_state(
        period_id,
        {"to_state": to_state, "expected_branch_version": _branch_version(branch_code)},
        role_headers or BRANCH_MANAGER))


def advance_period_raw(period_id, to_state, branch_code=TEST_DEFAULTS["BRANCH_CODE"],
                       role_headers=None):
    """Advance a period without validating — for negative tests."""
    return api_client.set_payout_period_state(
        period_id,
        {"to_state": to_state, "expected_branch_version": _branch_version(branch_code)},
        role_headers or BRANCH_MANAGER)


def true_up_period(period_id, branch_code=TEST_DEFAULTS["BRANCH_CODE"]):
    return get_success_data(api_client.true_up_period(
        period_id, {"expected_branch_version": _branch_version(branch_code)},
        BRANCH_MANAGER))


def net_settlement(period_id, advisor_code):
    return get_success_data(api_client.net_settlement(
        period_id, {"advisor_code": advisor_code}, BRANCH_MANAGER))


def start_departure(advisor):
    current = refresh_advisor(advisor["id"])
    return get_success_data(api_client.start_departure(
        advisor["id"], {"expected_advisor_version": current["version"]},
        make_advisor_ops_headers(advisor["id"])))


def start_book_transfer(advisor):
    current = refresh_advisor(advisor["id"])
    return get_success_data(api_client.start_book_transfer(
        advisor["id"], {"expected_advisor_version": current["version"]},
        make_advisor_ops_headers(advisor["id"])))


def open_transition(advisor, period_id):
    current = refresh_advisor(advisor["id"])
    return get_success_data(api_client.create_transition(
        create_transition_payload(advisor["advisor_code"], period_id,
                                  current["version"]),
        BRANCH_MANAGER))


def contest_account(transition_id, account_id, retention_rate_bps=500):
    return api_client.contest_retention(
        transition_id,
        create_retention_contest_payload(account_id, retention_rate_bps),
        BRANCH_MANAGER)


def open_period_raw(branch_code=TEST_DEFAULTS["BRANCH_CODE"], year=2026, month=9,
                    period_index=1):
    """Open a period without validating — for negative assertions."""
    return api_client.create_payout_period(
        create_payout_period_payload(branch_code, year, month, period_index),
        BRANCH_MANAGER)


def settle_retention(transition_id, account_ids_retained, advisor):
    current = refresh_advisor(advisor["id"])
    return api_client.settle_retention(
        transition_id,
        {"account_ids_retained": account_ids_retained,
         "expected_advisor_version": current["version"]},
        BRANCH_MANAGER)


def lose_retention(transition_id, account_ids_lost, advisor):
    current = refresh_advisor(advisor["id"])
    return api_client.lose_retention(
        transition_id,
        {"account_ids_lost": account_ids_lost,
         "expected_advisor_version": current["version"]},
        BRANCH_MANAGER)


def retire_loan(advisor, account, mileage_cents=None,
                production_date="2026-07-10", period=None):
    """Drive a loan to a zero balance, then post the period that carries it.

    A draw may only be posted while the loan is still live, and the forgiveness
    milestone only books on released production, so the sequence is: release the
    milestone production, take the draw, forgive the residual, then post the
    period so the release and its draw are actually settled.

    `account` is whichever account the milestone production is booked against —
    an account object, or a bare account id.
    """
    account_id = account["id"] if isinstance(account, dict) else account
    set_clock("2026-07-28T00:00:00Z")
    period = period or open_period(month=RETIREMENT_MONTH)
    loan = get_success_data(api_client.list_payout_loans(
        PLATFORM_ADMIN, {"advisor_code": advisor["advisor_code"]}))[0]
    entry = book_entry(advisor, account_id,
                       mileage_cents if mileage_cents is not None
                       else loan["principal_cents"],
                       production_date=production_date)
    release_entry(entry, advisor)
    get_success_data(api_client.amortize_loan(
        loan["id"], {"payout_period_id": period["id"]},
        make_advisor_ops_headers(advisor["id"])))
    get_success_data(api_client.forgive_loan(
        loan["id"],
        {"expected_advisor_version": refresh_advisor(advisor["id"])["version"]},
        make_advisor_ops_headers(advisor["id"])))
    advance_period(period["id"], "CLOSED", advisor["primary_branch_code"])
    advance_period(period["id"], "PAID", advisor["primary_branch_code"])
    set_clock(DEFAULT_CLOCK_UTC)
    return get_success_data(api_client.get_payout_loan(loan["id"], PLATFORM_ADMIN))


def setup_departing_advisor(advisor_code="A-1105", account_numbers=("A-1105-1",),
                            account_balances=(4_000_000,), period_index=1,
                            loan_principal=500_000, crd_number="2234571",
                            milestone_account_index=0, open_caller_period=True):
    """An ACTIVE advisor with a fully discharged loan, then moved to DEPARTING.

    Each account is opened already FROZEN, which is the book state a departing
    advisor's accounts sit in: the account is created while the advisor is still
    ACTIVE and the departure's freeze cascade then leaves it frozen. The loan is
    retired against one of those accounts (the mileage production is back-dated
    so it never lands in the month the caller's period covers).

    The retirement is booked while the clock rests at the startup default
    2026-09-01T00:00:00Z, so a book transfer that follows stamps its
    pending_transfer_at at that instant and the twenty-four-hour hold is measured
    from there. The caller's period is opened only after the departure, because a
    period tagged to the branch may not be OPEN when the departure runs.
    """
    ctx = setup_active_advisor(advisor_code=advisor_code, crd_number=crd_number,
                               full_name="Departing Advisor",
                               ingested_book_total_cents=200_000_000,
                               book_transferred_cents=160_000_000,
                               principal_cents=loan_principal,
                               forgiveness_milestone_pct=100)
    advisor = ctx["advisor"]
    # The book is retired against an account that is in place before the
    # departure, so the departure's freeze cascade leaves it FROZEN and the
    # advisor's outstanding balance reads zero.
    milestone_account = open_account(advisor, f"{advisor_code}-RP",
                                     balance_cents=1_000_000)
    retirement_period = open_period(month=RETIREMENT_MONTH, period_index=1)
    retire_loan(advisor, milestone_account, period=retirement_period)
    departed = start_departure(advisor)
    # The named accounts are opened only now, after the freeze cascade has run,
    # so they start OPEN and the book transfer can release them into the transfer
    # window that the supervisory hold is measured against.
    accounts = [open_account(refresh_advisor(departed["id"]), number,
                             balance_cents=balance)
                for number, balance in zip(account_numbers, account_balances)]
    book_transfer = start_book_transfer(refresh_advisor(departed["id"]))
    period = None
    if open_caller_period:
        period = open_period(period_index=period_index, month=SEPTEMBER_MONTH)
    ctx.update({"accounts": accounts, "advisor": refresh_advisor(departed["id"]),
                "period": period,
                "retirement_period": retirement_period,
                "book_transfer": book_transfer,
                "milestone_account": milestone_account,
                "account_numbers": list(account_numbers)})
    return ctx


def setup_retention_scenario(advisor_code="A-1307",
                             account_numbers=("A-1307-1", "A-1307-2", "A-1307-3"),
                             account_balances=(10_000_000, 10_000_000, 10_000_000),
                             loan_principal=500_000,
                             book_transferred_cents=160_000_000,
                             ingested_book_total_cents=None,
                             with_transition=True):
    """A DEPARTING advisor whose named accounts are addressable for a contest.

    The named accounts are opened after the departure, so the freeze cascade has
    already run; the accounts are then moved into the transfer window through a
    book transfer — the status a retention contest requires, and the status the
    contest row is keyed on — leaving the milestone account FROZEN so it remains
    in the frozen book the transition counts.  Every period the sweep touches is
    closed before the next one is opened, so the branch is never left holding an
    OPEN period that would block the later departure.
    """
    ingested = ingested_book_total_cents or max(book_transferred_cents * 10000 // 8000, 1)
    ctx = setup_active_advisor(advisor_code=advisor_code, crd_number="2234571",
                               full_name="Retention Advisor",
                               ingested_book_total_cents=ingested,
                               book_transferred_cents=book_transferred_cents,
                               principal_cents=loan_principal,
                               forgiveness_milestone_pct=100)
    advisor = ctx["advisor"]
    milestone = open_account(advisor, f"{advisor_code}-RP",
                             balance_cents=1_000_000)
    retirement_period = open_period(month=RETIREMENT_MONTH, period_index=1)
    retire_loan(advisor, milestone, period=retirement_period)

    departed = start_departure(refresh_advisor(advisor["id"]))
    # The named accounts are opened only now, after the departure's freeze
    # cascade has run, so they start OPEN and the book transfer can release them
    # into the transfer window the contest requires.
    accounts = [open_account(refresh_advisor(departed["id"]), number,
                             balance_cents=balance)
                for number, balance in zip(account_numbers, account_balances)]
    book_transfer = start_book_transfer(refresh_advisor(departed["id"]))
    set_clock("2026-09-02T13:00:00Z")

    contest_period = None
    transition = None
    if with_transition:
        # The contest is booked in a period that is neither PAID nor VOID.
        contest_period = open_period(period_index=2, month=SEPTEMBER_MONTH)
        transition = open_transition(refresh_advisor(departed["id"]),
                                     contest_period["id"])
    ctx.update({"advisor": refresh_advisor(departed["id"]), "accounts": accounts,
                "period": contest_period, "retirement_period": retirement_period,
                "book_transfer": book_transfer, "transition": transition,
                "milestone_account": milestone,
                "account_numbers": list(account_numbers)})
    return ctx


def confirm_transfer(account_id, role_headers=None):
    """Confirm a book transfer for an account that finished its hold window."""
    return get_success_data(api_client.confirm_transfer(
        account_id, role_headers or COMPLIANCE_OFFICER))


def setup_funded_period(advisor_code="A-1001", affiliation_model="IC",
                        projected_annual_production_cents=120_000_000,
                        entries=((800_000, "2026-09-03", "EQUITY"),),
                        account_balance_cents=10_000_000,
                        principal_cents=500_000, forgiveness_milestone_pct=100,
                        amortization_rate_bps=2000, period_index=1,
                        period_month=9, release=False):
    """An ACTIVE advisor with a period, a payout line and booked revenue entries."""
    ctx = setup_active_advisor(advisor_code=advisor_code,
                               affiliation_model=affiliation_model,
                               principal_cents=principal_cents,
                               forgiveness_milestone_pct=forgiveness_milestone_pct,
                               amortization_rate_bps=amortization_rate_bps)
    # The trailing-twelve-month window reads the logical clock, so the clock is
    # advanced past the months the fixture books production in; every window
    # arithmetic rule then sees that production.
    set_clock("2026-10-01T00:00:00Z")
    advisor = ctx["advisor"]
    account = open_account(advisor, f"{advisor_code}-EQ",
                           balance_cents=account_balance_cents)
    period = open_period(month=period_month, period_index=period_index)
    line = open_payout_line(advisor, period["id"], projected_annual_production_cents)
    created = [book_entry(advisor, account["id"], gross, date, product)
               for gross, date, product in entries]
    if release:
        for entry in created:
            release_entry(entry, advisor)
    ctx.update({"account": account, "period": period, "line": line, "entries": created})
    return ctx


def setup_advisor_on_unsupervised_branch(branch_code="SOLO-1",
                                         advisor_code="A-1304",
                                         supervisor_code="A-1305",
                                         account_numbers=(),
                                         account_balances=()):
    """An ACTIVE advisor whose branch has been demoted back to UNSUPERVISED.

    The advisor is activated while the branch is supervised, then the branch's
    last supervisor is removed so the branch reads UNSUPERVISED / DRAFT again
    while the advisor keeps its ACTIVE lifecycle.
    """
    branch = create_branch(branch_code=branch_code, name="Solo Practice",
                           transmittal_account="TA-9001", osj_name="Solo OSJ")
    supervisor = create_advisor(supervisor_code, "5234568", "Lars Petrossian",
                                primary_branch_code=branch_code,
                                ingested_book_total_cents=100_000_000,
                                book_transferred_cents=80_000_000)
    enrollment = enroll_supervisor(branch_code, supervisor_code)
    link = create_advisor_link(supervisor, branch_code, is_supervisor=True)

    advisor = create_advisor(advisor_code, "5234567", "Verity Okonjo",
                             primary_branch_code=branch_code,
                             ingested_book_total_cents=500_000_000,
                             book_transferred_cents=400_000_000)
    loan = create_loan(advisor, principal_cents=500_000, forgiveness_milestone_pct=90)
    activate_advisor(advisor)

    accounts = [open_account(advisor, number, balance_cents=balance)
                for number, balance in zip(account_numbers, account_balances)]

    # Remove the branch's only supervisor, taking it back to UNSUPERVISED.
    get_success_data(set_advisor_link_state(link["id"], "INACTIVE", branch_code))
    get_success_data(api_client.set_supervisor_enrollment_state(
        enrollment["id"],
        {"to_status": "REVOKED", "expected_branch_version": _branch_version(branch_code)},
        PLATFORM_ADMIN))

    return {
        "branch": refresh_branch(branch["id"]),
        "supervisor": supervisor,
        "advisor": refresh_advisor(advisor["id"]),
        "loan": loan,
        "accounts": accounts,
    }


def make_instance_headers(user_id, role):
    """Headers for an arbitrary acting principal — used by ownership-gated tests."""
    return build_user_headers(user_id, role)


def setup_suspended_advisor(advisor_code="A-1101", account_numbers=("A-1101-1", "A-1101-2"),
                            account_balances=(10_000_000, 20_000_000)):
    """An ACTIVE advisor on a supervised branch holding OPEN accounts."""
    ctx = setup_active_advisor(advisor_code=advisor_code, crd_number="2234567",
                               full_name="Suspended Advisor")
    advisor = ctx["advisor"]
    accounts = [open_account(advisor, number, balance_cents=balance)
                for number, balance in zip(account_numbers, account_balances)]
    ctx["accounts"] = accounts
    ctx["account_numbers"] = list(account_numbers)
    return ctx


def suspend_advisor(advisor_id):
    current = refresh_advisor(advisor_id)
    return api_client.set_advisor_state(
        advisor_id, {"to_status": "SUSPENDED",
                     "expected_advisor_version": current["version"]},
        COMPLIANCE_OFFICER)


def reinstate_advisor(advisor_id):
    current = refresh_advisor(advisor_id)
    return api_client.set_advisor_state(
        advisor_id, {"to_status": "ACTIVE",
                     "expected_advisor_version": current["version"]},
        COMPLIANCE_OFFICER)


def list_retention_rows(transition_id):
    """Return the raw list response for a transition's retention rows.

    Callers wrap this in `get_success_data(...)`, which validates the envelope
    and unwraps `data` (an array for this list endpoint).  Returning the rows
    here would double-unwrap and break the caller's envelope check.
    """
    return api_client.list_transition_retention_rows(transition_id, BRANCH_MANAGER)


def annual_payout_cap_cents():
    return ANNUAL_PAYOUT_CAP_CENTS