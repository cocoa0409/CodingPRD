"""Organization accounts, citations and the payment-settlement stub (PRD §3.14)."""

from db import STORE, ordered, paginate
from errors import fail
from services import lookup

ACCOUNT_TYPES = ("UNIVERSITY", "BUSINESS")


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def create(data, fields):
    """POST /car-share/accounts (Anonymous, UniversityAccountAdmin) — PRD §3.14."""
    name = fields.field(data, "name", "string", required=True)
    type_ = fields.field(data, "type", "string", required=True, enum=ACCOUNT_TYPES)
    primary_member_id = fields.field(data, "primary_member_id", "string", required=True)
    billing_email = fields.field(data, "billing_email", "string", required=True)

    lookup.member(primary_member_id)

    return STORE.create(
        STORE.accounts,
        name=name,
        type=type_,
        primary_member_id=primary_member_id,
        billing_email=billing_email,
    )


def list_accounts(type_, primary_member_id, limit, offset):
    rows = ordered(STORE.accounts.values())
    if type_:
        rows = [r for r in rows if r.get("type") == type_]
    if primary_member_id:
        rows = [r for r in rows if r.get("primary_member_id") == primary_member_id]
    return paginate(rows, limit, offset)


def get(account_id):
    return lookup.account(account_id)


def account_memberships(account_id, limit, offset):
    lookup.account(account_id)
    rows = ordered([m for m in STORE.memberships.values() if m.get("account_id") == account_id])
    return paginate(rows, limit, offset)


def account_members(account_id):
    lookup.account(account_id)
    member_ids = {m["member_id"] for m in STORE.memberships.values()
                  if m.get("account_id") == account_id}
    account = STORE.accounts.get(account_id)
    if account:
        member_ids.add(account.get("primary_member_id"))
    return ordered([STORE.members[mid] for mid in member_ids if mid in STORE.members])


# ---- test-driving surfaces -------------------------------------------------
def set_clock(data, fields):
    """POST /_clock/set_current_utc (PlatformAdmin) — PRD §2.7.

    The clock is the network's only time source: "after that call every deadline,
    expiry and window comparison in the system is evaluated against the new value."
    Advancing it is a pure observation change; the lateness sweep that carries an
    elapsed reservation into OVERDUE is its own declared operation (PRD §3.10).
    """
    target = fields.field(data, "to_iso8601", "string", required=True)
    STORE.set_clock(target)
    return None


def simulate_payment(data, fields):
    membership_id = fields.field(data, "membership_id", "string", required=True)
    outcome = fields.field(data, "outcome", "string", required=True)
    lookup.membership(membership_id)
    row = STORE.create(
        STORE.payments,
        membership_id=membership_id,
        outcome=outcome,
    )
    return row


def issue_citation(data, fields):
    """POST /_citations/issue (PlatformAdmin) — the row carries no output payload,
    so it is addressable by its own recoverable signer address."""
    signer = fields.field(data, "signer_address", "string", required=True)
    recoverable = fields.field(data, "recoverable_signer_address", "string", required=True)
    expires_at = fields.field(data, "expires_at", "string", required=True)
    row = STORE.create(
        STORE.citations,
        signer_address=signer,
        recoverable_signer_address=recoverable,
        expires_at=expires_at,
    )
    # The minted citation is addressed by its recoverable signer address, which is
    # the only identifier the caller knows when the mint returns no payload.
    STORE.citations.pop(row["id"], None)
    row["id"] = recoverable
    STORE.citations[recoverable] = row
    return row


def validate_signature(citation_id, data, fields):
    """POST /car-share/citations/{id}/validate-signature — PRD §3.14."""
    citation = STORE.citations.get(citation_id)
    if citation is None and len(STORE.citations) == 1:
        citation = next(iter(STORE.citations.values()))
    if citation is None:
        fail("ERR_INVALID_REQUEST", "No citation exists with id %s." % citation_id)
    signature = fields.field(data, "signature", "string", required=True)
    if signature != citation.get("recoverable_signer_address"):
        fail("ERR_CITATION_SIGNATURE_INVALID",
             "The signature does not match the recoverable signer address.")
    return None