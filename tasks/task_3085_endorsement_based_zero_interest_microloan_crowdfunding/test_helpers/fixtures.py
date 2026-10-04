"""Composite setup helpers built purely from PRD-declared endpoints.

Every helper drives the real API; nothing is seeded behind the scenes. The
helpers raise ``AssertionError`` with a "Setup failed" prefix when any setup
call does not succeed, so a broken precondition surfaces as a clear fixture
error rather than as a puzzling assertion failure in the test body.

The test harness restarts the server (empty database) before every test, so
each fixture builds its preconditions from scratch.
"""
from types import SimpleNamespace

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .test_users import (
    TEST_USERS,
    make_borrower_headers,
    make_lender_headers,
    make_trustee_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# low-level helpers
# ---------------------------------------------------------------------------

def _data(response, what):
    if not (200 <= response.status_code < 300):
        raise AssertionError(
            f"Setup failed: {what} returned HTTP {response.status_code}: "
            f"{response.text[:400]}"
        )
    body = response.json()
    if "data" not in body:
        raise AssertionError(f"Setup failed: {what} returned no data envelope: {body}")
    return body["data"]


def set_clock(iso8601=DEFAULT_CLOCK_ISO):
    return _data(api_client.set_clock(iso8601, ADMIN), f"clock set to {iso8601}")


def run_sweeps():
    return _data(api_client.run_sweeps(ADMIN), "POST /_sweeps/run")


# ---------------------------------------------------------------------------
# Tier 1 — participants
# ---------------------------------------------------------------------------

def create_borrower(**overrides):
    return _data(
        api_client.create_borrower(f.create_borrower_payload(**overrides), TEST_USERS["anonymous_headers"]),
        "POST /borrowers",
    )


def create_lender(deposit_cents=None, **overrides):
    lender = _data(
        api_client.create_lender(f.create_lender_payload(**overrides), TEST_USERS["anonymous_headers"]),
        "POST /lenders",
    )
    if deposit_cents:
        deposit(lender["id"], deposit_cents)
        lender = get_lender(lender["id"])
    return lender


def get_lender(lender_id):
    return _data(
        api_client.get_lender(lender_id, make_lender_headers(lender_id)),
        "GET /lenders/{id}",
    )


def deposit(lender_id, amount_cents):
    return _data(
        api_client.deposit(
            lender_id, {"amount_cents": amount_cents}, make_lender_headers(lender_id)
        ),
        "POST /lenders/{id}/deposits",
    )


def create_trustee(**overrides):
    return _data(
        api_client.create_trustee(f.create_trustee_payload(**overrides), ADMIN),
        "POST /trustees",
    )


def get_trustee(trustee_id):
    return _data(api_client.get_trustee(trustee_id, ADMIN), "GET /trustees/{id}")


def get_borrower(borrower_id):
    return _data(api_client.get_borrower(borrower_id, ADMIN), "GET /borrowers/{id}")


def get_application(application_id):
    return _data(
        api_client.get_application(application_id, ADMIN), "GET /loan-applications/{id}"
    )


def get_loan(loan_id):
    return _data(api_client.get_loan(loan_id, ADMIN), "GET /loans/{id}")


# ---------------------------------------------------------------------------
# Tier 2 — social underwriting
# ---------------------------------------------------------------------------

def create_accepted_invites(borrower, count, email_prefix="invitee"):
    """Create `count` invites for the borrower and accept every one of them.

    Returns the list of invite payloads (ACCEPTED).
    """
    headers = make_borrower_headers(borrower["id"])
    invites = []
    for i in range(count):
        invite = _data(
            api_client.create_invite(
                borrower["id"],
                f.create_invite_payload(invitee_email=f"{email_prefix}-{i}-{borrower['id'][:8]}@x.com"),
                headers,
            ),
            "POST /borrowers/{id}/underwriting-invites",
        )
        invites.append(
            _data(api_client.accept_invite(invite["invite_token"]), "accept invite")
        )
    return invites


def create_submittable_borrower(accepts=3, **borrower_overrides):
    """Borrower with `accepts` ACCEPTED underwriting invites.

    The borrower profile defaults to tenure 24 / prior 1 so the score clears
    the 60-point approval threshold once enough accepts are supplied (10
    accepts suffice in every endorsement mode).
    """
    borrower = create_borrower(**borrower_overrides)
    create_accepted_invites(borrower, accepts)
    return borrower


# ---------------------------------------------------------------------------
# Tier 3 — application pipeline
# ---------------------------------------------------------------------------

def create_application(borrower, **overrides):
    return _data(
        api_client.create_application(
            f.create_application_payload(borrower["id"], **overrides),
            make_borrower_headers(borrower["id"]),
        ),
        "POST /loan-applications",
    )


def submit_application(application, borrower, trustee_id=None):
    payload = {"expected_application_version": application["version"]}
    if trustee_id is not None:
        payload["trustee_id"] = trustee_id
    return _data(
        api_client.submit_application(
            application["id"], payload, make_borrower_headers(borrower["id"])
        ),
        "POST /loan-applications/{id}/submit",
    )


def approve_application(application, notes=None):
    return _data(
        api_client.approve_application(
            application["id"], ADMIN, {"notes": notes} if notes else {}
        ),
        "POST /loan-applications/{id}/approve",
    )


def open_private(application, borrower):
    return _data(
        api_client.open_private(application["id"], make_borrower_headers(borrower["id"])),
        "POST /loan-applications/{id}/open-private",
    )


def open_public(application, borrower):
    return _data(
        api_client.open_public(application["id"], make_borrower_headers(borrower["id"])),
        "POST /loan-applications/{id}/open-public",
    )


def endorse(application, lender, amount_cents):
    return _data(
        api_client.create_endorsement(
            application["id"],
            f.create_endorsement_payload(lender["id"], amount_cents=amount_cents),
            make_lender_headers(lender["id"]),
        ),
        "POST /loan-applications/{id}/endorsements",
    )


def trustee_endorse(application, trustee, amount_cents):
    return _data(
        api_client.create_trustee_endorsement(
            trustee["id"],
            f.create_trustee_endorsement_payload(
                application["id"], amount_cents=amount_cents
            ),
            make_trustee_headers(trustee["id"]),
        ),
        "POST /trustees/{id}/endorsements",
    )


def contribute(application, lender, amount_cents):
    return _data(
        api_client.create_contribution(
            application["id"],
            f.create_contribution_payload(lender["id"], amount_cents=amount_cents),
            make_lender_headers(lender["id"]),
        ),
        "POST /loan-applications/{id}/contributions",
    )


def disburse(application):
    return _data(
        api_client.disburse_application(
            application["id"],
            {"expected_application_version": application["version"]},
            ADMIN,
        ),
        "POST /loan-applications/{id}/disburse",
    )


# ---------------------------------------------------------------------------
# Tier 4 — composite pipeline stages
# ---------------------------------------------------------------------------

def create_draft_application(borrower=None, accepts=3, **app_overrides):
    """Borrower (with the floor acceptance quota met) + a DRAFT application."""
    if borrower is None:
        borrower = create_submittable_borrower(accepts=accepts)
    application = create_application(borrower, **app_overrides)
    return SimpleNamespace(borrower=borrower, application=application)


def create_submitted_application(
    borrower=None, trustee=None, accepts=3, **app_overrides
):
    """Application advanced DRAFT -> IN_REVIEW."""
    if borrower is None:
        borrower = create_submittable_borrower(accepts=accepts)
    application = create_application(borrower, **app_overrides)
    application = submit_application(
        application, borrower, trustee_id=trustee["id"] if trustee else None
    )
    return SimpleNamespace(
        borrower=borrower, application=application, trustee=trustee
    )


def create_private_fundraising_application(
    borrower=None, trustee=None, accepts=10, **app_overrides
):
    """Application advanced to PRIVATE_FUNDRAISING.

    Trustee-vouched when `trustee` is given, self-endorsed otherwise. The
    default borrower profile (tenure 24, 10 accepts, prior 1) scores 63
    self-endorsed or 75 trustee-vouched — both clear the 60-point approval
    threshold.
    """
    submitted = create_submitted_application(
        borrower=borrower, trustee=trustee, accepts=accepts, **app_overrides
    )
    application = approve_application(submitted.application)
    application = open_private(application, submitted.borrower)
    return SimpleNamespace(
        borrower=submitted.borrower, application=application, trustee=trustee
    )


def meet_quorum_with_endorsements(ns, lender_amounts, trustee_amount=None):
    """Add endorsements to a PRIVATE_FUNDRAISING application.

    `lender_amounts` is a list of (fresh lender, amount) pairs — one new
    lender is created and funded per entry so every endorsement is distinct.
    Optionally adds one trustee endorsement when `trustee_amount` is given.
    Returns (application, lenders).
    """
    lenders = []
    for amount in lender_amounts:
        lender = create_lender(deposit_cents=max(amount * 4, 100_000))
        endorse(ns.application, lender, amount)
        lenders.append(lender)
    if trustee_amount is not None:
        assert ns.trustee is not None, "trustee_amount requires a trustee"
        trustee_endorse(ns.application, ns.trustee, trustee_amount)
    application = get_application(ns.application["id"])
    return application, lenders


def create_funded_application(
    principal_cents=100_000,
    term_months=3,
    trustee=None,
    endorsement_amounts=None,
    trustee_endorsement_amount=None,
    contribution_amounts=None,
    borrower=None,
    accepts=10,
):
    """Walk an application to FUNDED and return the namespace.

    Defaults: self-endorsed borrower, 15 endorsements of 2500 (37500 private),
    one contribution of 62500 to reach 100000 exactly. The default borrower
    profile (tenure 24, 10 accepts, prior 1) scores 63 self-endorsed or 75
    trustee-vouched — both clear the 60-point approval threshold.
    """
    if endorsement_amounts is None:
        endorsement_amounts = [2500] * 15
    ns = create_private_fundraising_application(
        borrower=borrower,
        trustee=trustee,
        accepts=accepts,
        requested_amount_cents=principal_cents,
        term_months=term_months,
    )
    application, lenders = meet_quorum_with_endorsements(
        ns, endorsement_amounts, trustee_amount=trustee_endorsement_amount
    )
    application = open_public(application, ns.borrower)
    contributors = []
    for amount in contribution_amounts or []:
        lender = create_lender(deposit_cents=max(amount * 4, 100_000))
        contribute(application, lender, amount)
        contributors.append(lender)
    application = get_application(application["id"])
    return SimpleNamespace(
        borrower=ns.borrower,
        application=application,
        trustee=trustee,
        endorsers=lenders,
        contributors=contributors,
    )


def create_disbursed_loan(
    principal_cents=100_000,
    term_months=3,
    trustee=None,
    endorsement_amounts=None,
    trustee_endorsement_amount=None,
    contribution_amounts=None,
    borrower=None,
    accepts=10,
):
    """Full pipeline through disbursement. Returns namespace with the Loan.

    The endorsements/contributions must sum exactly to principal_cents or the
    application never reaches FUNDED.
    """
    ns = create_funded_application(
        principal_cents=principal_cents,
        term_months=term_months,
        trustee=trustee,
        endorsement_amounts=endorsement_amounts,
        trustee_endorsement_amount=trustee_endorsement_amount,
        contribution_amounts=contribution_amounts,
        borrower=borrower,
        accepts=accepts,
    )
    loan = disburse(ns.application)
    return SimpleNamespace(
        borrower=ns.borrower,
        application=get_application(ns.application["id"]),
        trustee=ns.trustee,
        endorsers=ns.endorsers,
        contributors=ns.contributors,
        loan=loan,
    )


def create_trustee_funded_loan(
    principal_cents=100_000,
    term_months=3,
    trustee=None,
    trustee_endorsement_amount=25_000,
    endorsement_amounts=(12_500, 12_500, 12_500, 12_500),
    contribution_amounts=(25_000,),
    borrower=None,
):
    """Trustee-vouched pipeline: 1 trustee endorsement + 4 lender endorsements
    (quorum 5), then contributions to reach the target, then disbursement.

    Defaults fund 100000 as 25000 trustee + 4 x 12500 endorsements (private
    75000) plus one 25000 contribution that flips the application FUNDED. The
    pieces must sum exactly to principal_cents.
    """
    if trustee is None:
        trustee = create_trustee()
    return create_disbursed_loan(
        principal_cents=principal_cents,
        term_months=term_months,
        trustee=trustee,
        endorsement_amounts=list(endorsement_amounts),
        trustee_endorsement_amount=trustee_endorsement_amount,
        contribution_amounts=list(contribution_amounts),
        borrower=borrower,
    )


# ---------------------------------------------------------------------------
# Tier 5 — loan lifecycle
# ---------------------------------------------------------------------------

def make_payment(loan, borrower, amount_cents):
    return _data(
        api_client.make_payment(
            loan["id"],
            {"amount_cents": amount_cents},
            make_borrower_headers(borrower["id"]),
        ),
        "POST /loans/{id}/payments",
    )


def finalize_schedule(loan):
    return _data(
        api_client.finalize_schedule(
            loan["id"], {"expected_loan_version": loan["version"]}, ADMIN
        ),
        "POST /loans/{id}/finalize-schedule",
    )


def list_installments(loan_id):
    return _data(api_client.list_installments(loan_id, ADMIN), "GET /loans/{id}/installments")


def installments_by_number(loan_id):
    return {i["installment_number"]: i for i in list_installments(loan_id)}


def create_paid_off_loan(**kwargs):
    """Disbursed loan fully repaid with a single payment (borrower pays the
    whole principal). Returns the loan namespace."""
    ns = create_trustee_funded_loan(**kwargs)
    make_payment(ns.loan, ns.borrower, ns.loan["principal_cents"])
    ns.loan = get_loan(ns.loan["id"])
    return ns


def _parse_ts(ts):
    from datetime import datetime, timezone

    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Fall back to fromisoformat for offset-suffixed stamps.
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_delinquent_loan(past_due_days=15, **kwargs):
    """Disbursed 3-month loan swept to DELINQUENT.

    The earliest installment's due_date is read back from the server; the
    clock is advanced `past_due_days` past it and the sweep runs.
    """
    from datetime import timedelta

    ns = create_trustee_funded_loan(term_months=3, **kwargs)
    due = _parse_ts(installments_by_number(ns.loan["id"])[1]["due_date"])
    set_clock(_fmt_ts(due + timedelta(days=past_due_days)))
    run_sweeps()
    ns.loan = get_loan(ns.loan["id"])
    return ns
