"""Corner coverage of endpoint behaviors: the OCC-guarded transfer and
termination writes, and the borrower inquiry's current-rights view."""
import pytest

from test_helpers import (
    ADMIN,
    TEST_USERS,
    api_client,
    create_active_member,
    create_transfer_payload,
    get_match_for_transfer,
    member_rep,
    read_loan,
    read_member,
    register_loan,
    set_clock,
    setup_two_member_pair,
    validate_error,
    validate_success,
)

BORROWER = TEST_USERS["borrower_inquirer_headers"]


def test_transfer_success_moves_rights_and_bumps_loan_version(api):
    """PRD §3.4: "On acceptance the transfer is born in `CONFIRMED` status
    (there is no pending state for the transfer itself), the rights move
    immediately — `current_investor_id` takes the receiving member for
    `BENEFICIAL` or `BOTH`, `current_servicer_id` for `SERVICING` or `BOTH` —
    and the loan's `version` advances by one with `updated_at` refreshed."
    PRD §2.8: "If the loan's current `version` differs — because, for example,
    another writer has since confirmed a transfer on the same loan, moving its
    rights and advancing its version — the request is rejected with
    `ERR_STALE_LOAN_VERSION` (HTTP 412)."
    PRD §3.4: "Confirmation of the transfer simultaneously opens the **match
    protocol** on the sending side: the registry creates one TransferMatch,
    addressed to the from-side member as `reported_by_member_id`, stamped with
    the clock as `reported_at`, and set to `PENDING`."

    Design: Corner/endpoints/transfer_success_moves_rights_and_bumps_loan_version
    """
    set_clock("2026-01-05T00:00:00Z")
    a, b = setup_two_member_pair(org_a="1000000", org_b="1000001")
    loan = register_loan(a["id"], loan_amount_cents=50000000)
    observed_version = loan["version"]

    tr = validate_success(
        api.create_transfer(
            create_transfer_payload(loan["id"], b["id"], observed_version,
                                    transfer_type="BOTH",
                                    idempotency_key="k-occ-1"),
            member_rep(a["id"]),
        ),
        expected_status=201,
    )
    assert tr["status"] == "CONFIRMED", tr
    assert tr["from_member_id"] == a["id"], tr
    assert tr["to_member_id"] == b["id"], tr

    loan_after = read_loan(loan["id"])
    assert loan_after["current_investor_id"] == b["id"], loan_after
    assert loan_after["current_servicer_id"] == b["id"], loan_after
    assert loan_after["version"] == observed_version + 1, loan_after

    # A second writer holding the pre-transfer version is rejected (OCC).
    # Per §2.9 tier 16, stale-version rejection is a guarantee about
    # otherwise-valid requests, so the stale attempt must itself be valid
    # apart from the version: B (now rights holder) moves BOTH rights to C.
    c = create_active_member(org_id="1000002", member_type="INVESTOR")
    stale = api.create_transfer(
        create_transfer_payload(loan["id"], c["id"], observed_version,
                                transfer_type="BOTH",
                                idempotency_key="k-occ-2"),
        member_rep(b["id"]),
    )
    assert stale.status_code == 412, stale.text
    validate_error(stale, "ERR_STALE_LOAN_VERSION")

    # The match protocol opened on the from side.
    match = get_match_for_transfer(tr["id"])
    assert match["status"] == "PENDING", match
    assert match["reported_by_member_id"] == a["id"], match


def test_terminate_occ_stale_member_version_rejected(api):
    """PRD §2.8: "Filing a membership termination requires the request to carry
    `expected_member_version`, matched against the target member's current
    `version`. A mismatch — for instance because a suspend or reinstate has
    advanced the member's version since the operator last read it — is rejected
    with `ERR_STALE_MEMBER_VERSION` (HTTP 412)."

    Design: Corner/endpoints/terminate_occ_stale_member_version_rejected
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    observed_version = read_member(a["id"])["version"]

    # Suspend and reinstate advance the member's version twice.
    validate_success(api.suspend_member(a["id"], ADMIN))
    validate_success(api.reinstate_member(a["id"], ADMIN))

    stale = api.terminate_member(
        a["id"],
        {"effective_date": "2026-01-05T00:00:00Z",
         "expected_member_version": observed_version},
        ADMIN,
    )
    assert stale.status_code == 412, stale.text
    validate_error(stale, "ERR_STALE_MEMBER_VERSION")

    fresh_version = read_member(a["id"])["version"]
    terminated = validate_success(
        api.terminate_member(
            a["id"],
            {"effective_date": "2026-01-05T00:00:00Z",
             "expected_member_version": fresh_version},
            ADMIN,
        )
    )
    assert terminated["status"] == "TERMINATED", terminated


def test_borrower_inquiry_reflects_current_rights_after_two_hop_transfer(api):
    """PRD §3.9: "A `BorrowerInquirer` presents a Mortgage Identification Number
    and receives, for that `min`, the loan's `loan_id`, its `loan_status`, and
    the identities of the current holders of record: `current_investor_id` with
    `current_investor_org_id`, and `current_servicer_id` with
    `current_servicer_org_id`."

    Design: Corner/endpoints/borrower_inquiry_reflects_current_rights_after_two_hop_transfer
    """
    set_clock("2026-01-05T00:00:00Z")
    a = create_active_member(org_id="1000000")
    b = create_active_member(org_id="1000001", org_id_type="LEI")
    c = create_active_member(org_id="1000002", org_id_type="LEI")
    loan = register_loan(a["id"], loan_amount_cents=50000000)
    assert loan["min"] == "100000000000000016", loan

    # A -> B servicing, then B -> C servicing; A never moves the investor right.
    validate_success(
        api.create_transfer(
            create_transfer_payload(loan["id"], b["id"], loan["version"],
                                    idempotency_key="k-bi-1"),
            member_rep(a["id"]),
        ),
        expected_status=201,
    )
    loan_now = read_loan(loan["id"])
    validate_success(
        api.create_transfer(
            create_transfer_payload(loan["id"], c["id"], loan_now["version"],
                                    idempotency_key="k-bi-2"),
            member_rep(b["id"]),
        ),
        expected_status=201,
    )

    data = validate_success(api.borrower_inquiry("100000000000000016", BORROWER))
    assert data["min"] == "100000000000000016", data
    assert data["loan_id"] == loan["id"], data
    assert data["loan_status"] == "ACTIVE", data
    assert data["current_servicer_org_id"] == "1000002", data
    assert data["current_servicer_id"] == c["id"], data
    assert data["current_investor_org_id"] == "1000000", data
    assert data["current_investor_id"] == a["id"], data
