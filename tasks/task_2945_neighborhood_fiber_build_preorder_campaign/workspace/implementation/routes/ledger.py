"""The append-only ledger (PRD 2.8)."""

from flask import Blueprint

import auth
import calc
import envelope
import listing
import serialize
from store import must_find, ordered, rows

bp = Blueprint("ledger", __name__)

READ_ROLES = ("ProgramManager", "ClaimsApprover", "Subscriber")


@bp.get("/ledger-entries/<entry_id>")
def read_entry(entry_id):
    auth.gate(READ_ROLES)
    row = must_find("ledger_entries", entry_id)
    return envelope.ok(serialize.ledger_entry(row))


@bp.get("/ledger-entries")
def list_entries():
    auth.gate(READ_ROLES)
    items = listing.apply_filters(
        ordered(rows("ledger_entries")),
        (
            listing.fk("account_id", "account_id", "accounts"),
            listing.fk("preorder_id", "preorder_id", "preorders"),
            listing.fk("damage_claim_id", "damage_claim_id", "damage_claims"),
            listing.enum("entry_type", "entry_type", calc.ENTRY_TYPES),
        ),
    )
    return envelope.list_response(items, serialize.ledger_entry)
