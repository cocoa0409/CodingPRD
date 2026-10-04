"""Corner coverage of the validation cascade: org_id and idempotency-key
uniqueness scopes, transfer semantics, sample membership, termination gates,
the appeal window and the review period."""
import pytest

from test_helpers import (
    ADMIN,
    add_finding,
    add_signer,
    api_client,
    create_active_member,
    create_member,
    create_qa_review_payload,
    create_transfer_payload,
    issue_review,
    list_sanctions,
    make_qa_auditor_headers,
    member_rep,
    open_review,
    read_loan,
    read_member,
    register_loan,
    set_clock,
    settle_review,
    setup_two_member_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

QA_CREATOR_HEADERS = make_qa_auditor_headers("qa-creator")


def test_duplicate_org_id_rejected_even_after_termination(api):
    """PRD §2.5: "A member's `org_id` is a string of exactly seven digits
    assigned by the operator at registration, classified by `org_id_type` as one
    of `TAX_ID`, `CHARTER_NUMBER`, or `LEI`, and is globally unique across every
    member ever registered — including members that later reach `TERMINATED`; a
    reuse attempt is refused with `ERR_DUPLICATE_ORG_ID`."

    Design: Corner/validations/duplicate_org_id_rejected_even_after_termination
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    # Zero loans, zero matches: immediate termination is permitted.
    current = read_member(a["id"])
    validate_success(
        api.terminate_member(
            a["id"],
            {"effective_date": "2026-01-05T00:00:00Z",
             "expected_member_version": current["version"]},
            ADMIN,
        )
    )
    assert read_member(a["id"])["status"] == "TERMINATED"

    resp = api.create_member(
        {"legal_name": "Alpha Reborn", "org_id": "1000000",
         "org_id_type": "LEI", "member_type": "INVESTOR"},
        ADMIN,
    )
    assert resp.status_code == 409, resp.text
    validate_error(resp, "ERR_DUPLICATE_ORG_ID")


def test_duplicate_idempotency_key_rejected_while_rejected_transfer_frees_key(api):
    """PRD §2.5: "A transfer carries a client-supplied `idempotency_key` whose
    uniqueness is enforced only among transfers that are not in `REJECTED`
    status; resubmitting a key already held by a live transfer fails with
    `ERR_DUPLICATE_IDEMPOTENCY_KEY`, while reusing the key of a rejected
    transfer is permitted."

    Design: Corner/validations/duplicate_idempotency_key_rejected_while_rejected_transfer_frees_key
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    loan1 = register_loan(a["id"], loan_amount_cents=50000000)
    loan2 = register_loan(a["id"], loan_amount_cents=50000000)

    t1 = validate_success(
        api.create_transfer(
            create_transfer_payload(loan1["id"], b["id"], loan1["version"],
                                    idempotency_key="K"),
            member_rep(a["id"]),
        ),
        expected_status=201,
    )

    # The key is held by a live (CONFIRMED) transfer: reuse is refused.
    dup = api.create_transfer(
        create_transfer_payload(loan2["id"], b["id"], loan2["version"],
                                idempotency_key="K"),
        member_rep(a["id"]),
    )
    assert dup.status_code == 409, dup.text
    validate_error(dup, "ERR_DUPLICATE_IDEMPOTENCY_KEY")

    # Once T1 is match-rejected the key is released and reuse succeeds.
    validate_success(api.reject_match(t1["id"], member_rep(a["id"])))
    t2 = validate_success(
        api.create_transfer(
            create_transfer_payload(loan2["id"], b["id"], loan2["version"],
                                    idempotency_key="K"),
            member_rep(a["id"]),
        ),
        expected_status=201,
    )
    assert t2["status"] == "CONFIRMED", t2


def test_self_transfer_rejected(api):
    """PRD §3.4: "The receiving member must exist and be `ACTIVE`
    (`ERR_MEMBER_NOT_ACTIVE`) and must differ from the current holder of the
    moved right or rights (`ERR_SELF_TRANSFER`)."

    Design: Corner/validations/self_transfer_rejected
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    loan = register_loan(a["id"], loan_amount_cents=50000000)

    resp = api.create_transfer(
        create_transfer_payload(loan["id"], a["id"], loan["version"],
                                idempotency_key="k-self-1"),
        member_rep(a["id"]),
    )
    assert resp.status_code == 422, resp.text
    validate_error(resp, "ERR_SELF_TRANSFER")

    rows, meta = validate_paginated(
        api.list_transfers(ADMIN, params={"loan_id": loan["id"]})
    )
    assert rows == [], rows


def test_not_rights_holder_rejected_on_transfer(api):
    """PRD §3.4: "The acting member must hold what it purports to move: a
    `BOTH` transfer requires the mover to hold both the beneficial and
    servicing rights on the loan, while a single-type transfer requires holding
    that one right; overreach is refused with `ERR_NOT_RIGHTS_HOLDER`."

    Design: Corner/validations/not_rights_holder_rejected_on_transfer
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    c = create_active_member(org_id="1000002", org_id_type="LEI",
                             member_type="INVESTOR")
    loan = register_loan(a["id"], loan_amount_cents=50000000)

    # B holds no right on the loan at all.
    resp = api.create_transfer(
        create_transfer_payload(loan["id"], c["id"], loan["version"],
                                idempotency_key="k-nrh-1"),
        member_rep(b["id"]),
    )
    assert resp.status_code == 409, resp.text
    validate_error(resp, "ERR_NOT_RIGHTS_HOLDER")
    assert read_loan(loan["id"])["current_servicer_id"] == a["id"]


def test_finding_on_loan_outside_sample_rejected(api):
    """PRD §3.5: "Each finding references a `loan_id` that must belong to the
    review's sample — defined as every loan ever registered by the reviewed
    member, in any status, ordered by registration serial ascending — and
    naming a loan outside that sample is refused with
    `ERR_LOAN_NOT_IN_SAMPLE`."

    Design: Corner/validations/finding_on_loan_outside_sample_rejected
    """
    from test_helpers import create_finding_payload
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    register_loan(a["id"], loan_amount_cents=50000000)
    b_loan = register_loan(b["id"], loan_amount_cents=50000000)
    review = open_review(a["id"])

    resp = api.create_finding(
        review["id"],
        create_finding_payload(b_loan["id"], field_name="MIN",
                               expected_value="x", actual_value="y",
                               severity="MAJOR"),
        QA_CREATOR_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    validate_error(resp, "ERR_LOAN_NOT_IN_SAMPLE")

    rows, _ = validate_paginated(api.list_findings(review["id"], ADMIN))
    assert rows == [], rows


def test_termination_blocked_while_member_holds_rights(api):
    """PRD §3.7: "First, the member must hold no rights anywhere on the
    registry: no loan in any status may name the member as
    `current_investor_id` or `current_servicer_id`, else
    `ERR_MEMBER_HOLDS_ACTIVE_RIGHTS`."

    Design: Corner/validations/termination_blocked_while_member_holds_rights
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    loan = register_loan(a["id"], loan_amount_cents=50000000)

    current = read_member(a["id"])
    resp = api.terminate_member(
        a["id"],
        {"effective_date": "2026-01-05T00:00:00Z",
         "expected_member_version": current["version"]},
        ADMIN,
    )
    assert resp.status_code == 409, resp.text
    validate_error(resp, "ERR_MEMBER_HOLDS_ACTIVE_RIGHTS")

    # Move both rights to B and confirm the match so A holds nothing.
    tr = validate_success(
        api.create_transfer(
            create_transfer_payload(loan["id"], b["id"], loan["version"],
                                    transfer_type="BOTH",
                                    idempotency_key="k-term-1"),
            member_rep(a["id"]),
        ),
        expected_status=201,
    )
    validate_success(api.match_confirm(tr["id"], member_rep(a["id"])))

    current2 = read_member(a["id"])
    terminated = validate_success(
        api.terminate_member(
            a["id"],
            {"effective_date": "2026-01-05T00:00:00Z",
             "expected_member_version": current2["version"]},
            ADMIN,
        )
    )
    assert terminated["status"] == "TERMINATED", terminated
    # The cascade keys on registering_member_id, not the current holder: the
    # loan A registered is still ACTIVE, so it flips even though B holds it.
    assert read_loan(loan["id"])["status"] == "INACTIVE_TERMINATED"


def test_appeal_window_expiry_is_thirty_days(api):
    """PRD §3.5: "Or it may appeal within the appeal window: an appeal filed no
    more than thirty days after the sanction's `created_at` moves the sanction
    to `APPEALED`; a later filing is refused with
    `ERR_APPEAL_WINDOW_EXPIRED`, and an appeal against a sanction no longer
    `ASSESSED` is refused with `ERR_SANCTION_NOT_APPEALABLE`."

    Design: Corner/validations/appeal_window_expiry_is_thirty_days
    """
    set_clock("2026-01-05T00:00:00Z")
    d = create_active_member(org_id="1000002", member_type="ORIGINATOR")
    loan = register_loan(d["id"], loan_amount_cents=40000000)
    review = open_review(d["id"], period_start="2026-01-01T00:00:00Z",
                         period_end="2026-03-31T00:00:00Z")
    add_finding(review["id"], loan["id"], severity="MINOR")
    issue_review(review["id"])
    settle_review(review["id"])
    sanction = list_sanctions(review_id=review["id"])[0]

    # Day 31 after the sanction's creation: outside the thirty-day window.
    set_clock("2026-02-05T00:00:00Z")
    resp = api.appeal_sanction(sanction["id"], member_rep(d["id"]))
    assert resp.status_code == 422, resp.text
    validate_error(resp, "ERR_APPEAL_WINDOW_EXPIRED")

    after = validate_success(api.get_sanction(sanction["id"], ADMIN))
    assert after["status"] == "ASSESSED", after


def test_qa_review_with_inverted_period_rejected(api):
    """PRD §3.5: "The period is inclusive at both ends, and `period_end` must
    not precede `period_start`; an inverted period is refused with
    `ERR_INVALID_PERIOD`."

    Design: Corner/validations/qa_review_with_inverted_period_rejected
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_member(org_id="1000000")

    resp = api.create_qa_review(
        create_qa_review_payload(a["id"], period_start="2026-06-30T00:00:00Z",
                                 period_end="2026-01-01T00:00:00Z"),
        QA_CREATOR_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    validate_error(resp, "ERR_INVALID_PERIOD")

    # Inclusive at both ends: an equal-bounds period is accepted.
    ok = validate_success(
        api.create_qa_review(
            create_qa_review_payload(a["id"], period_start="2026-03-01T00:00:00Z",
                                     period_end="2026-03-01T00:00:00Z"),
            QA_CREATOR_HEADERS,
        ),
        expected_status=201,
    )
    assert ok["period_start"] == "2026-03-01T00:00:00Z", ok
    assert ok["period_end"] == "2026-03-01T00:00:00Z", ok
