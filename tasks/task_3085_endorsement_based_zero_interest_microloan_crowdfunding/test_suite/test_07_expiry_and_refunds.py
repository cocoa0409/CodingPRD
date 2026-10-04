"""Campaign expiry, withdrawal, cancellation, and refund cascades
(PRD §3.5, §2.4)."""
from test_helpers import (
    TEST_USERS,
    create_lender,
    create_private_fundraising_application,
    get_application,
    get_lender,
    make_borrower_headers,
    make_lender_headers,
    run_sweeps,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_INVALID_STATE

ADMIN = TEST_USERS["admin_headers"]


def test_expiry_cascade_refunds_endorsements_and_contribution(api):
    """PRD §3.5: "A public campaign past its `public_deadline` whose
    `funded_total_cents` is still short of the requested amount is moved to
    `EXPIRED_PUBLIC`; every `ACTIVE` endorsement and every `ACTIVE`
    contribution becomes `REFUNDED`, each non-trustee endorsement and each
    contribution credits its lender back in full, and `private_total_cents`,
    `public_total_cents`, and `distinct_endorser_count` all recompute to 0.
    Both transitions stamp `terminal_at`."

    Design: Difficulty/transitive_cascade/expiry_cascade_application_endorsement_lender
    """
    set_clock()
    ns = create_private_fundraising_application(
        requested_amount_cents=400_000, term_months=6
    )
    endorsers = [create_lender(deposit_cents=100_000) for _ in range(15)]
    for lender in endorsers:
        fx.endorse(ns.application, lender, 25_000)
    application = get_application(ns.application["id"])

    set_clock("2026-09-10T00:00:00Z")
    application = fx.open_public(application, ns.borrower)
    bulk = create_lender(deposit_cents=2_000_000)
    fx.contribute(application, bulk, 20_000)

    set_clock("2026-10-11T00:00:00Z")
    sweep = run_sweeps()
    assert sweep["applications_expired"] == 1

    application = get_application(application["id"])
    assert application["status"] == "EXPIRED_PUBLIC"
    assert application["terminal_at"] is not None
    assert application["private_total_cents"] == 0
    assert application["public_total_cents"] == 0
    assert application["distinct_endorser_count"] == 0

    endorsements, _ = validate_paginated(
        client.list_application_endorsements(
            application["id"], ADMIN, params={"limit": 100}
        )
    )
    assert len(endorsements) == 15
    for endorsement in endorsements:
        assert endorsement["status"] == "REFUNDED"
        assert endorsement["resolved_at"] is not None

    for lender in endorsers:
        assert (
            get_lender(lender["id"])["lending_balance_cents"] == 100_000
        ), "the 25000 endorsement refund returns to the lending account"
    assert get_lender(bulk["id"])["lending_balance_cents"] == 2_000_000


def test_expired_public_is_terminal(api):
    """PRD §3.5: "A public campaign past its `public_deadline` whose
    `funded_total_cents` is still short of the requested amount is moved to
    `EXPIRED_PUBLIC`"
    PRD §3.5: "Attempting either action from any other state is
    `ERR_INVALID_STATE`."

    Design: Difficulty/transitive_cascade/expiry_cascade_application_endorsement_lender
    """
    set_clock()
    ns = create_private_fundraising_application(
        requested_amount_cents=400_000, term_months=6
    )
    application, _ = fx.meet_quorum_with_endorsements(ns, [25_000] * 15)
    application = fx.open_public(application, ns.borrower)

    set_clock("2026-10-11T00:00:00Z")
    sweep = run_sweeps()
    assert sweep["applications_expired"] == 1
    assert get_application(application["id"])["status"] == "EXPIRED_PUBLIC"

    resp = client.withdraw_application(
        application["id"], make_borrower_headers(ns.borrower["id"])
    )
    validate_error(resp, ERR_INVALID_STATE, expected_status=409)


def test_private_expiry_restores_the_lender_balance_exactly(api):
    """PRD §3.5: "A private period still running past its `private_deadline`
    is moved to `EXPIRED_PRIVATE`; every `ACTIVE` endorsement on it becomes
    `REFUNDED` with `resolved_at` stamped at sweep time, each non-trustee
    endorsement credits its `amount_cents` back to the lender's
    `lending_balance_cents`, and the application's `private_total_cents` and
    `distinct_endorser_count` recompute to 0."
    PRD §3.1: "The `lifetime_lent_cents` counter tracks capital the lender
    has deployed, and `lifetime_repaid_cents` accumulates principal credited
    back through repayment distribution."

    Design: Difficulty/compensating_invariant/lender_balance_conserved_across_lend_and_refund
    """
    set_clock()
    ns = create_private_fundraising_application(
        requested_amount_cents=500_000, term_months=6
    )
    lender = create_lender()
    fx.deposit(lender["id"], 100_000)
    fx.endorse(ns.application, lender, 40_000)
    assert get_lender(lender["id"])["lending_balance_cents"] == 60_000

    set_clock("2026-09-17T00:00:00Z")
    run_sweeps()

    assert get_application(ns.application["id"])["status"] == "EXPIRED_PRIVATE"
    after = get_lender(lender["id"])
    assert (
        after["lending_balance_cents"] == 100_000
    ), "deposit 100000 - endorsement 40000 + refund 40000 conserves the balance"
    assert after["lifetime_lent_cents"] == 0, "refunded endorsements are not lent"
    assert after["lifetime_repaid_cents"] == 0


def test_endorsement_debit_and_refund_conserve_multiple_lenders(api):
    """PRD §3.4: "debits the lender's `lending_balance_cents` by that amount"
    PRD §3.5: "A private period still running past its `private_deadline` is
    moved to `EXPIRED_PRIVATE`; every `ACTIVE` endorsement on it becomes
    `REFUNDED` with `resolved_at` stamped at sweep time, each non-trustee
    endorsement credits its `amount_cents` back to the lender's
    `lending_balance_cents`"

    Design: Difficulty/compensating_invariant/lender_balance_conserved_across_lend_and_refund
    """
    set_clock()
    ns = create_private_fundraising_application(
        requested_amount_cents=500_000, term_months=6
    )
    deposits = [120_000, 80_000]
    amounts = [30_000, 25_000]
    lenders = []
    for deposit_amount, amount in zip(deposits, amounts):
        lender = create_lender(deposit_cents=deposit_amount)
        fx.endorse(ns.application, lender, amount)
        after_debit = get_lender(lender["id"])
        assert after_debit["lending_balance_cents"] == deposit_amount - amount
        lenders.append((lender, deposit_amount))

    set_clock("2026-09-17T00:00:00Z")
    sweep = run_sweeps()
    assert sweep["applications_expired"] == 1

    for lender, deposit_amount in lenders:
        after = get_lender(lender["id"])
        assert (
            after["lending_balance_cents"] == deposit_amount
        ), "debit + refund restores the pre-lend balance exactly"
        assert after["lifetime_lent_cents"] == 0
        assert after["lifetime_repaid_cents"] == 0


def test_private_window_boundary_is_inclusive_then_expires(api):
    """PRD §3.4: "moving the application `APPROVED_PENDING_FUNDRAISE` →
    `PRIVATE_FUNDRAISING` and stamping `private_started_at`; the
    `private_deadline` is set to exactly 15 days later."
    PRD §3.5: "A private period still running past its `private_deadline` is
    moved to `EXPIRED_PRIVATE`"
    PRD §2.4: "Every deadline, grace window, and status flip described in §3
    is evaluated only when the sweep runs — nothing in this system
    transitions merely because time passed."

    Design: Difficulty/resource_temporal_overlap/private_window_expiry_boundary
    """
    set_clock()
    ns = create_private_fundraising_application(
        requested_amount_cents=300_000, term_months=4
    )
    lender = create_lender(deposit_cents=500_000)

    # At exactly the deadline (2026-09-16T00:00:00Z) the window is still
    # open: the endorsement succeeds.
    set_clock("2026-09-16T00:00:00Z")
    fx.endorse(ns.application, lender, 25_000)

    # One second past the deadline the sweep expires the application.
    set_clock("2026-09-16T00:00:01Z")
    sweep = run_sweeps()
    assert sweep["applications_expired"] == 1
    assert (
        get_application(ns.application["id"])["status"] == "EXPIRED_PRIVATE"
    )

    # A post-expiry endorsement is a state violation; the refunded balance
    # is back to the full deposit.
    resp = client.create_endorsement(
        ns.application["id"],
        {"lender_id": lender["id"], "amount_cents": 25_000},
        make_lender_headers(lender["id"]),
    )
    validate_error(resp, ERR_INVALID_STATE, expected_status=409)
    assert get_lender(lender["id"])["lending_balance_cents"] == 500_000


def test_no_sweep_no_expiry_even_past_deadline(api):
    """PRD §2.4: "Every deadline, grace window, and status flip described in
    §3 is evaluated only when the sweep runs — nothing in this system
    transitions merely because time passed."

    Design: Difficulty/resource_temporal_overlap/private_window_expiry_boundary
    """
    set_clock()
    ns = create_private_fundraising_application(
        requested_amount_cents=300_000, term_months=4
    )
    set_clock("2026-09-20T00:00:00Z")  # past the 15-day private window
    application = get_application(ns.application["id"])
    assert (
        application["status"] == "PRIVATE_FUNDRAISING"
    ), "the deadline alone does nothing until the sweep runs"


def test_cancel_funded_application_refunds_everything(api):
    """PRD §3.5: "Cancellation is the post-funding exit: a `FUNDED`
    application for which no `Loan` has yet been created may be cancelled
    into `CANCELLED`, refunding every `ACTIVE` endorsement and contribution
    exactly as an expiry would."

    Design: Corner/state_machines/cancel_funded_application_refunds_everything
    """
    set_clock()
    trustee = fx.create_trustee(endorsement_limit_cents=1_000_000)
    ns = fx.create_funded_application(
        principal_cents=150_000,
        term_months=3,
        trustee=trustee,
        endorsement_amounts=[25_000, 25_000, 25_000, 25_000],
        trustee_endorsement_amount=25_000,
        contribution_amounts=[25_000],
    )
    assert ns.application["status"] == "FUNDED"

    cancelled = validate_success(
        client.cancel_application(
            ns.application["id"], make_borrower_headers(ns.borrower["id"])
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["terminal_at"] is not None
    assert cancelled["private_total_cents"] == 0
    assert cancelled["funded_total_cents"] == 0

    endorsements, _ = validate_paginated(
        client.list_application_endorsements(ns.application["id"], ADMIN)
    )
    assert endorsements
    for endorsement in endorsements:
        assert endorsement["status"] == "REFUNDED"

    # Each endorser deposited 100000 and endorsed 25000: fully restored.
    for lender in ns.endorsers:
        assert get_lender(lender["id"])["lending_balance_cents"] == 100_000


def test_withdraw_from_private_cancels_endorsements_and_credits_lenders(api):
    """PRD §3.5: "Withdrawal is available from `DRAFT`, `IN_REVIEW`,
    `APPROVED_PENDING_FUNDRAISE`, and `PRIVATE_FUNDRAISING`, moving the
    application to `WITHDRAWN` with `terminal_at` stamped; withdrawing from
    `PRIVATE_FUNDRAISING` additionally moves every `ACTIVE` endorsement to
    `CANCELLED` (stamping each `resolved_at`) and credits each non-trustee
    endorsement's amount back to its lender."

    Design: Corner/state_machines/cancel_funded_application_refunds_everything
    """
    set_clock()
    ns = create_private_fundraising_application(
        requested_amount_cents=300_000, term_months=4
    )
    lender = create_lender(deposit_cents=100_000)
    fx.endorse(ns.application, lender, 25_000)
    assert get_lender(lender["id"])["lending_balance_cents"] == 75_000

    withdrawn = validate_success(
        client.withdraw_application(
            ns.application["id"], make_borrower_headers(ns.borrower["id"])
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["terminal_at"] is not None

    endorsements, _ = validate_paginated(
        client.list_application_endorsements(ns.application["id"], ADMIN)
    )
    assert len(endorsements) == 1
    assert endorsements[0]["status"] == "CANCELLED"
    assert endorsements[0]["resolved_at"] is not None
    assert get_lender(lender["id"])["lending_balance_cents"] == 100_000
