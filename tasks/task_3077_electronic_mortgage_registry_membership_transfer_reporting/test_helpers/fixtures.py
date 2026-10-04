"""Composite setup helpers.

The registry gates nearly every interesting operation behind several layers of
preamble: an ACTIVE member needs an ACTIVE signer, loan registration needs an
ACTIVE member, transfers need a loan and a second member, sanctions need a
settled review, and settlement needs two distinct auditors. These helpers
compress those chains so tests can read as assertions rather than plumbing.

Every helper uses the lenient success reader so a broken preamble surfaces as
a setup failure instead of a confusing assertion failure downstream.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_loan_payload,
    create_member_payload,
    create_qa_review_payload,
    create_finding_payload,
    create_signer_payload,
    create_transfer_payload,
)
from .test_users import (
    QA_CREATOR,
    QA_SETTLER,
    TEST_USERS,
    make_member_rep_headers,
    make_qa_auditor_headers,
)

ADMIN = TEST_USERS["registry_admin_headers"]

_org_counter = itertools.count(1000000)


def _fresh_org_id() -> str:
    return str(next(_org_counter))


# --------------------------------------------------------------------------
# Tier 0: the logical clock
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the registry's logical clock; evaluates due timed transitions."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Tier 1: member lifecycle
# --------------------------------------------------------------------------

def create_member(org_id=None, activate=False, **overrides) -> dict:
    """Register a member (PENDING_ACTIVATION). Optionally activate it."""
    payload = create_member_payload(org_id=org_id or _fresh_org_id(), **overrides)
    member = get_success_data(api_client.create_member(payload, ADMIN))
    if activate:
        add_signer(member["id"])
        member = get_success_data(api_client.activate_member(member["id"], ADMIN))
    return member


def add_signer(member_id, **overrides) -> dict:
    """Designate an ACTIVE signer for a member."""
    return get_success_data(
        api_client.create_signer(member_id, create_signer_payload(**overrides), ADMIN)
    )


def create_active_member(org_id=None, signer=True, **overrides) -> dict:
    """Register a member, give it an ALL-scope signer, and activate it."""
    member = get_success_data(
        api_client.create_member(
            create_member_payload(org_id=org_id or _fresh_org_id(), **overrides), ADMIN
        )
    )
    if signer:
        add_signer(member["id"])
    return get_success_data(api_client.activate_member(member["id"], ADMIN))


def read_member(member_id) -> dict:
    return get_success_data(api_client.get_member(member_id, ADMIN))


def member_rep(member_id) -> dict:
    """Headers for the MemberRep acting as the given member."""
    return make_member_rep_headers(member_id)


# --------------------------------------------------------------------------
# Tier 2: loans
# --------------------------------------------------------------------------

def register_loan(member_id, **overrides) -> dict:
    """Register a loan under the given ACTIVE member. Returns the loan."""
    return get_success_data(
        api_client.create_loan(create_loan_payload(**overrides), member_rep(member_id))
    )


def read_loan(loan_id) -> dict:
    return get_success_data(api_client.get_loan(loan_id, ADMIN))


# --------------------------------------------------------------------------
# Tier 3: transfers and matches
# --------------------------------------------------------------------------

def transfer(from_member_id, loan, to_member_id, **overrides) -> dict:
    """Report a CONFIRMED transfer from the loan's current holder."""
    loan = read_loan(loan["id"])
    payload = create_transfer_payload(
        loan["id"], to_member_id, loan["version"], **overrides
    )
    return get_success_data(api_client.create_transfer(payload, member_rep(from_member_id)))


def get_match_for_transfer(transfer_id) -> dict:
    """Fetch the single TransferMatch row belonging to a transfer."""
    rows, meta = validate_paginated(
        api_client.list_transfer_matches(ADMIN, params={"transfer_id": transfer_id})
    )
    assert len(rows) == 1, f"expected exactly one match for transfer {transfer_id}"
    return rows[0]


def list_findings(review_id) -> list:
    rows, _meta = validate_paginated(api_client.list_findings(review_id, ADMIN))
    return rows


def list_sanctions(**params) -> list:
    rows, _meta = validate_paginated(api_client.list_sanctions(ADMIN, params=params))
    return rows


def list_sor_exceptions(**params) -> list:
    rows, _meta = validate_paginated(api_client.list_sor_exceptions(ADMIN, params=params))
    return rows


# --------------------------------------------------------------------------
# Tier 4: QA reviews, findings, sanctions
# --------------------------------------------------------------------------

def open_review(member_id, creator=QA_CREATOR, **overrides) -> dict:
    """Open a DRAFT QA review for a member as the given auditor."""
    return get_success_data(
        api_client.create_qa_review(
            create_qa_review_payload(member_id, **overrides),
            make_qa_auditor_headers(creator),
        )
    )


def add_finding(review_id, loan_id, creator=QA_CREATOR, **overrides) -> dict:
    return get_success_data(
        api_client.create_finding(
            review_id,
            create_finding_payload(loan_id, **overrides),
            make_qa_auditor_headers(creator),
        )
    )


def issue_review(review_id, creator=QA_CREATOR) -> dict:
    return get_success_data(
        api_client.issue_review(review_id, make_qa_auditor_headers(creator))
    )


def settle_review(review_id, settler=QA_SETTLER, payload=None) -> dict:
    return get_success_data(
        api_client.settle_review(
            review_id, {} if payload is None else payload, make_qa_auditor_headers(settler)
        )
    )


def setup_settled_review(member_id, loan_id, severity="MINOR", settler=QA_SETTLER,
                         settle_payload=None, creator=QA_CREATOR):
    """Open a review, add one finding on the given loan, issue and settle it.

    Returns (review, sanction).
    """
    review = open_review(member_id, creator=creator)
    add_finding(review["id"], loan_id, creator=creator, severity=severity)
    review = issue_review(review["id"], creator=creator)
    review = settle_review(review["id"], settler=settler, payload=settle_payload)
    sanctions = list_sanctions(review_id=review["id"])
    assert len(sanctions) == 1, "settling a review creates exactly one sanction"
    return review, sanctions[0]


def setup_two_member_pair(org_a=None, org_b=None):
    """Two ACTIVE members, each with an ALL-scope signer. Returns (a, b)."""
    a = create_active_member(org_id=org_a)
    b = create_active_member(org_id=org_b)
    return a, b
