"""Rights-request depth: provisional embargo vs hard withdrawal, branching
fork, hold-to-revocation cascade, and the work-availability checkout gate."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS, make_patron_headers, make_legal_reviewer_headers,
    create_loan_payload,
    set_clock, make_patron, make_library, make_work, make_batch_with_items,
    setup_work_with_lendable_items, checkout, join_waitlist,
    get_work, get_item, get_loan, get_patron, get_entry,
    file_work_rights_request, begin_review, escalate_hold, decide_request,
)

ADMIN = TEST_USERS["admin_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]
SCANOP = TEST_USERS["scan_operator_headers"]


def test_provisional_embargo_preserves_active_loans():
    """PRD 3.8: "For a `WORK` subject, beginning review immediately embargoes
    the work — `availability` becomes `EMBARGOED`, the `lendable` flag of the
    work's `LENDABLE` items flips false, and waitlist promotion skips
    embargoed works — but loans already `ACTIVE` are untouched, and the
    catalog record remains visible."

    Design: Difficulty/dual_variant_calc/work_availability_provisional_embargo_vs_hard_withdrawal
    """
    set_clock("2026-09-10T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "At-Risk Almanac", "author": "A. Writer",
                        "publication_year": 1998},
    )
    patron = make_patron(email="p1@example.org")
    loan = checkout(items[0]["id"], patron["id"])
    request = file_work_rights_request(work["id"], claimant_name="Estate of Writer")

    begin_review(request["id"], reviewer="legal-b")
    assert get_work(work["id"])["availability"] == "EMBARGOED"
    assert get_loan(loan["id"])["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api_client.list_patron_loans(patron["id"], ADMIN, params={"status": "ACTIVE"})
    )
    assert len(rows) == 1


def test_hard_withdrawal_revokes_active_loans():
    """PRD 3.8: "For a `WORK` subject, `availability` becomes `WITHDRAWN` and
    every `ACTIVE` loan on the work's items is revoked: each such loan moves
    from `ACTIVE` to `REVOKED`, its item returns from `ON_LOAN` to `LENDABLE`,
    the borrower's `active_loan_count` decreases by 1, and waitlist promotion
    runs per affected work."

    Design: Difficulty/dual_variant_calc/work_availability_provisional_embargo_vs_hard_withdrawal
    """
    set_clock("2026-09-10T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "At-Risk Almanac", "author": "A. Writer",
                        "publication_year": 1998},
    )
    patron = make_patron(email="p1@example.org")
    loan = checkout(items[0]["id"], patron["id"])
    request = file_work_rights_request(work["id"], claimant_name="Estate of Writer")
    begin_review(request["id"], reviewer="legal-b")

    escalate_hold(request["id"], reviewer="legal-b")
    assert get_work(work["id"])["availability"] == "WITHDRAWN"
    assert get_loan(loan["id"])["status"] == "REVOKED"
    assert get_item(items[0]["id"])["status"] == "LENDABLE"
    assert get_patron(patron["id"])["active_loan_count"] == 0


def test_branching_review_hold_dismiss_fork_cascade_not_undone():
    """PRD 3.8: "Escalation triggers the hard-withdrawal cascade. For a `WORK`
    subject, `availability` becomes `WITHDRAWN` and every `ACTIVE` loan on the
    work's items is revoked: each such loan moves from `ACTIVE` to `REVOKED`,
    its item returns from `ON_LOAN` to `LENDABLE`, the borrower's
    `active_loan_count` decreases by 1, and waitlist promotion runs per
    affected work."

    Design: Difficulty/non_linear_state_machine/rights_request_branching_review_hold_dismiss_fork
    """
    set_clock("2026-09-10T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Contested Memoirs", "author": "B. Author",
                        "publication_year": 2005},
    )
    patron = make_patron(email="p2@example.org")
    loan = checkout(items[0]["id"], patron["id"])
    request = file_work_rights_request(work["id"], claimant_name="Heirs of Author")
    begin_review(request["id"], reviewer="legal-b")

    escalate_hold(request["id"], reviewer="legal-b")
    # the LEGAL_HOLD branch fired the revocation cascade
    assert get_loan(loan["id"])["status"] == "REVOKED"

    decide_request(request["id"], "DISMISS", decider="legal-c")
    # the revoked loan stays REVOKED: branch side effects are not undone
    assert get_loan(loan["id"])["status"] == "REVOKED"
    assert get_patron(patron["id"])["active_loan_count"] == 0


def test_branching_review_hold_dismiss_fork_dismissal_recovers_availability():
    """PRD 3.8: "A decision of `DISMISS` moves the request to `DISMISSED` and
    triggers availability recovery: the subject work's `availability` is
    recomputed from scratch, and if it recovers to `AVAILABLE`, the platform
    re-evaluates `DEPOSITED` items in sealed batches for promotion to
    `LENDABLE`, each such promotion running waitlist promotion for the work in
    the usual way."
    PRD 3.8: "the decider's `X-User-ID` must differ from `reviewed_by`, and the
    decider is recorded as `decided_by`."

    Design: Difficulty/non_linear_state_machine/rights_request_branching_review_hold_dismiss_fork
    """
    set_clock("2026-09-10T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Contested Memoirs", "author": "B. Author",
                        "publication_year": 2005},
    )
    patron = make_patron(email="p2@example.org")
    loan = checkout(items[0]["id"], patron["id"])
    request = file_work_rights_request(work["id"], claimant_name="Heirs of Author")
    begin_review(request["id"], reviewer="legal-b")
    escalate_hold(request["id"], reviewer="legal-b")
    decide_request(request["id"], "DISMISS", decider="legal-c")

    # no remaining blocking request: availability recovers
    assert get_work(work["id"])["availability"] == "AVAILABLE"
    fresh = validate_success(api_client.get_rights_request(request["id"], LEGAL))
    assert fresh["decided_by"] == "legal-c"
    assert fresh["reviewed_by"] == "legal-b"


def test_rights_hold_to_loan_revocation_cascade_revokes_and_restores_item():
    """PRD 3.8: "Escalation triggers the hard-withdrawal cascade. For a `WORK`
    subject, `availability` becomes `WITHDRAWN` and every `ACTIVE` loan on the
    work's items is revoked: each such loan moves from `ACTIVE` to `REVOKED`,
    its item returns from `ON_LOAN` to `LENDABLE`, the borrower's
    `active_loan_count` decreases by 1, and waitlist promotion runs per
    affected work."

    Design: Difficulty/transitive_cascade/rights_hold_to_loan_revocation_cascade
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Disputed Field Guide", "author": "D. Scribe",
                        "publication_year": 1988},
    )
    borrower = make_patron(email="p5@example.org")
    waiter = make_patron(email="p6@example.org")
    loan = checkout(items[0]["id"], borrower["id"])
    entry = join_waitlist(work["id"], waiter["id"])
    request = file_work_rights_request(work["id"], claimant_name="Publisher Q")
    begin_review(request["id"], reviewer="legal-b")

    escalate_hold(request["id"], reviewer="legal-b")
    assert get_work(work["id"])["availability"] == "WITHDRAWN"
    assert get_loan(loan["id"])["status"] == "REVOKED"
    assert get_item(items[0]["id"])["status"] == "LENDABLE"
    assert get_patron(borrower["id"])["active_loan_count"] == 0


def test_rights_hold_to_loan_revocation_cascade_offers_waitlist():
    """PRD 3.8: "Escalation triggers the hard-withdrawal cascade. For a `WORK`
    subject, `availability` becomes `WITHDRAWN` and every `ACTIVE` loan on the
    work's items is revoked: each such loan moves from `ACTIVE` to `REVOKED`,
    its item returns from `ON_LOAN` to `LENDABLE`, the borrower's
    `active_loan_count` decreases by 1, and waitlist promotion runs per
    affected work."
    PRD 3.5: "The first eligible patron wins: the entry moves from `OPEN` to
    `OFFERED`, `offered_at` is stamped with the current logical clock, and
    `offer_expires_at` is set exactly 48 hours after `offered_at`."

    Design: Difficulty/transitive_cascade/rights_hold_to_loan_revocation_cascade
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Disputed Field Guide", "author": "D. Scribe",
                        "publication_year": 1988},
    )
    borrower = make_patron(email="p5@example.org")
    waiter = make_patron(email="p6@example.org")
    loan = checkout(items[0]["id"], borrower["id"])
    entry = join_waitlist(work["id"], waiter["id"])
    request = file_work_rights_request(work["id"], claimant_name="Publisher Q")
    begin_review(request["id"], reviewer="legal-b")
    escalate_hold(request["id"], reviewer="legal-b")

    offered = get_entry(entry["id"])
    # The revocation cascade returned the item to LENDABLE and ran promotion
    # (PRD 3.8), but the work's availability is now WITHDRAWN, and PRD 3.3's
    # `lendable` projection ("it is true exactly when the item's own `status`
    # is `LENDABLE`, its work's `availability` is `AVAILABLE`, and its owning
    # library's `status` is `ACTIVE`") makes the supply check fail — so the
    # promotion run ends with no offer and the entry stays OPEN.
    assert offered["status"] == "OPEN"
    assert offered["offered_at"] is None


def test_loan_checkout_gated_by_work_availability_succeeds_before_review():
    """PRD 3.8: "A `FILED` request has no effect on availability or playback —
    only `UNDER_REVIEW`, `LEGAL_HOLD`, and `UPHELD_REMOVED` requests do."

    Design: Difficulty/cross_entity_state_dependency/loan_checkout_gated_by_work_availability
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=2,
        work_overrides={"title": "Embargo Studies", "author": "G. Gate",
                        "publication_year": 2015},
    )
    patron1 = make_patron(email="p9@example.org")
    make_patron(email="p10@example.org")
    request = file_work_rights_request(work["id"], claimant_name="Rights Holder R")
    assert get_work(work["id"])["availability"] == "AVAILABLE"

    loan = checkout(items[0]["id"], patron1["id"])
    assert loan["status"] == "ACTIVE"


def test_loan_checkout_gated_by_work_availability_blocked_after_review():
    """PRD 3.4: "the item's work must be `AVAILABLE` (else
    `ERR_WORK_UNAVAILABLE`)"

    Design: Difficulty/cross_entity_state_dependency/loan_checkout_gated_by_work_availability
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=2,
        work_overrides={"title": "Embargo Studies", "author": "G. Gate",
                        "publication_year": 2015},
    )
    patron1 = make_patron(email="p9@example.org")
    patron2 = make_patron(email="p10@example.org")
    request = file_work_rights_request(work["id"], claimant_name="Rights Holder R")
    checkout(items[0]["id"], patron1["id"])

    begin_review(request["id"], reviewer="legal-b")
    assert get_work(work["id"])["availability"] == "EMBARGOED"

    resp = api_client.create_loan(
        create_loan_payload(items[1]["id"], patron2["id"]),
        make_patron_headers(patron2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_WORK_UNAVAILABLE)
    assert get_item(items[1]["id"])["status"] == "LENDABLE"
