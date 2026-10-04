"""Concurrency (OCC), RBAC, and the logical clock (PRD §2.7, §2.1, §2.4)."""
from test_helpers import (
    TEST_USERS,
    create_application,
    create_borrower,
    create_lender,
    create_submittable_borrower,
    get_application,
    get_loan,
    make_borrower_headers,
    make_lender_headers,
    make_payment,
    run_sweeps,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_FORBIDDEN,
    ERR_INVITE_NOT_PENDING,
    ERR_SCHEDULE_ALREADY_FINAL,
    ERR_STALE_VERSION,
)

ADMIN = TEST_USERS["admin_headers"]


def test_stale_version_on_submit_rejected(api):
    """PRD §2.7: "Submitting a loan application requires
    `expected_application_version`, carrying the version of the
    `LoanApplication` the client last observed. If the application's current
    `version` has advanced since that observation — for example because the
    draft was edited, and each edit bumps the version — the submission is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_version_on_submit_rejected
    """
    set_clock()
    borrower = create_submittable_borrower()
    application = create_application(borrower)
    stale_version = application["version"]

    edited = validate_success(
        client.update_application(
            application["id"],
            {"business_purpose": "x v2"},
            make_borrower_headers(borrower["id"]),
        )
    )
    assert edited["version"] > stale_version

    resp = client.submit_application(
        application["id"],
        {"expected_application_version": stale_version},
        make_borrower_headers(borrower["id"]),
    )
    validate_error(resp, ERR_STALE_VERSION, expected_status=412)
    assert get_application(application["id"])["status"] == "DRAFT"


def test_submit_with_current_version_succeeds_after_stale_rejection(api):
    """PRD §2.7: "Submitting a loan application requires
    `expected_application_version`, carrying the version of the
    `LoanApplication` the client last observed."
    PRD §3.3: "A successful submission moves the application `DRAFT` →
    `IN_REVIEW`, recomputes the borrower's score and variant as in §3.2, and
    bumps the application's `version`."

    Design: Corner/validations/stale_version_on_submit_rejected
    """
    set_clock()
    borrower = create_submittable_borrower()
    application = create_application(borrower)
    edited = validate_success(
        client.update_application(
            application["id"],
            {"business_purpose": "x v2"},
            make_borrower_headers(borrower["id"]),
        )
    )
    resp = client.submit_application(
        application["id"],
        {"expected_application_version": application["version"]},
        make_borrower_headers(borrower["id"]),
    )
    validate_error(resp, ERR_STALE_VERSION, expected_status=412)

    submitted = validate_success(
        client.submit_application(
            application["id"],
            {"expected_application_version": edited["version"]},
            make_borrower_headers(borrower["id"]),
        )
    )
    assert submitted["status"] == "IN_REVIEW"
    assert submitted["version"] > edited["version"]


def test_occ_stale_loan_version_on_finalize(api):
    """PRD §2.7: "Finalizing a loan's repayment schedule requires
    `expected_loan_version`, matched against the `Loan`'s current `version`.
    Any mutation of the loan — a payment, a status flip — advances the
    version, and a finalize request carrying an earlier-observed version is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.9: "Last of all, the optimistic-concurrency check
    (`ERR_STALE_VERSION`) — a stale request that also violates a business
    rule reports the business rule."
    PRD §3.6: "...and no payment has touched any installment (every
    `amount_paid_cents` still 0) — otherwise the request fails with
    `ERR_SCHEDULE_ALREADY_FINAL` (HTTP 409)."

    Design: Corner/cross_cutting_layers/occ_stale_loan_version_on_finalize
    """
    set_clock()
    ns = fx.create_trustee_funded_loan(
        principal_cents=200_000,
        term_months=3,
        endorsement_amounts=[25_000, 25_000, 25_000, 25_000],
        trustee_endorsement_amount=50_000,
        contribution_amounts=[50_000],
    )
    stale_loan_version = ns.loan["version"]

    # A payment mutates the loan and advances its version.
    make_payment(ns.loan, ns.borrower, 1_000)
    assert get_loan(ns.loan["id"])["version"] > stale_loan_version

    # The request is stale AND a payment has touched an installment; per the
    # global ordering the business rule is reported before the OCC check.
    resp = client.finalize_schedule(
        ns.loan["id"], {"expected_loan_version": stale_loan_version}, ADMIN
    )
    validate_error(resp, ERR_SCHEDULE_ALREADY_FINAL, expected_status=409)
    assert get_loan(ns.loan["id"])["schedule_status"] == "PROVISIONAL"


def test_disburse_with_stale_application_version_rejected(api):
    """PRD §2.7: "Disbursing a funded application likewise requires
    `expected_application_version`. Because every endorsement and every
    contribution bumps the application's `version`, a version read before
    the final contribution arrived is stale by the time disbursement is
    requested, and the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_loan_version_on_finalize
    """
    set_clock()
    ns = fx.create_private_fundraising_application(requested_amount_cents=500_000)
    application = get_application(ns.application["id"])
    stale_version = application["version"]

    application, _ = fx.meet_quorum_with_endorsements(ns, [25_000] * 15)
    assert application["version"] > stale_version
    application = fx.open_public(application, ns.borrower)
    whale = fx.create_lender(deposit_cents=1_000_000)
    fx.contribute(application, whale, 125_000)
    application = get_application(application["id"])
    assert application["status"] == "FUNDED"

    resp = client.disburse_application(
        application["id"], {"expected_application_version": stale_version}, ADMIN
    )
    validate_error(resp, ERR_STALE_VERSION, expected_status=412)

    loan = fx.disburse(application)
    assert loan["status"] == "REPAYING"


def test_lender_cannot_approve_application(api):
    """PRD §2.1: "A caller whose role is not permitted for the operation, or
    whose `X-User-ID` fails an entity-backed ownership check, is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.3: "Review belongs to the `PlatformAdmin`, with three outcomes."

    Design: Corner/roles/lender_cannot_approve_application
    """
    set_clock()
    ns = fx.create_submitted_application()
    lender = create_lender()
    resp = client.approve_application(
        ns.application["id"], make_lender_headers(lender["id"])
    )
    validate_error(resp, ERR_FORBIDDEN, expected_status=403)


def test_borrower_cannot_endorse_own_application(api):
    """PRD §2.1: "A caller whose role is not permitted for the operation, or
    whose `X-User-ID` fails an entity-backed ownership check, is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.4: "During the private period, lenders lend through
    endorsements."

    Design: Corner/roles/borrower_cannot_endorse_own_application
    """
    set_clock()
    ns = fx.create_private_fundraising_application()
    resp = client.create_endorsement(
        ns.application["id"],
        {"lender_id": ns.borrower["id"], "amount_cents": 25_000},
        make_borrower_headers(ns.borrower["id"]),
    )
    validate_error(resp, ERR_FORBIDDEN, expected_status=403)


def test_borrower_cannot_touch_anothers_application(api):
    """PRD §2.1: "A borrower acts with `X-User-Role` set to `Borrower`, and
    `X-User-ID` must be the `id` of the acting `Borrower` record; ownership
    checks on any resource that references a borrower compare the resource's
    `borrower_id` to `X-User-ID`."
    PRD §2.1: "A caller whose role is not permitted for the operation, or
    whose `X-User-ID` fails an entity-backed ownership check, is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/roles/ownership_check_borrower_cannot_touch_others_application
    """
    set_clock()
    owner = create_submittable_borrower()
    intruder = create_submittable_borrower()
    application = create_application(owner)

    resp = client.submit_application(
        application["id"],
        {"expected_application_version": application["version"]},
        make_borrower_headers(intruder["id"]),
    )
    validate_error(resp, ERR_FORBIDDEN, expected_status=403)
    assert get_application(application["id"])["status"] == "DRAFT"


def test_invite_accept_twice_returns_invite_not_pending(api):
    """PRD §3.2: "Both actions require the invite to still be `SENT`; an
    invite already resolved is rejected with `ERR_INVITE_NOT_PENDING`
    (HTTP 409)."

    Design: Corner/state_machines/invite_accept_twice_returns_invite_not_pending
    """
    set_clock()
    borrower = create_borrower()
    invite = validate_success(
        client.create_invite(
            borrower["id"],
            {"invitee_email": "double-accept@example.com"},
            make_borrower_headers(borrower["id"]),
        ),
        expected_status=201,
    )
    accepted = validate_success(client.accept_invite(invite["invite_token"]))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["responded_at"] is not None

    resp = client.accept_invite(invite["invite_token"])
    validate_error(resp, ERR_INVITE_NOT_PENDING, expected_status=409)


def test_clock_default_is_fixed_startup_time(api):
    """PRD §2.4: "Before the clock is ever set, the logical clock reads
    exactly `2026-09-01T00:00:00Z` and never falls back to wall-clock time."
    PRD §3.2: "Invites are perishable: the maintenance sweep moves any
    invite still `SENT` 30 days after its creation to `EXPIRED`, stamping
    `responded_at` with the sweep time."

    Design: Corner/cross_cutting_layers/clock_default_is_fixed_startup_time
    """
    # No set_clock call at all: the invite is stamped at the fixed default.
    borrower = create_borrower()
    invite = validate_success(
        client.create_invite(
            borrower["id"],
            {"invitee_email": "default-clock@example.com"},
            make_borrower_headers(borrower["id"]),
        ),
        expected_status=201,
    )
    assert invite["created_at"].startswith(
        "2026-09-01T00:00:00"
    ), f"default logical clock, got {invite['created_at']}"

    set_clock("2026-10-01T00:01:00Z")
    sweep = run_sweeps()
    assert sweep["invites_expired"] == 1

    resp = client.accept_invite(invite["invite_token"])
    validate_error(resp, ERR_INVITE_NOT_PENDING, expected_status=409)
