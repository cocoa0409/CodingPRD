"""The append-only ledger: read-only endpoints (PRD 3.9)."""
from flask import Blueprint

import auth
import db
import derive
import response
import support

bp = Blueprint("ledger", __name__)


@bp.get("/perks/ledger-entries/<row_id>")
def get_entry(row_id):
    auth.require(auth.PLATFORM_ADMIN)
    row = support.fetch("ledger_entries", row_id)
    return response.ok(derive.ledger_json(row))


@bp.get("/perks/ledger-entries")
def list_entries():
    auth.require(auth.PLATFORM_ADMIN, auth.PARTNER_MANAGER)
    filters = {
        "redemption_id": support.arg("redemption_id"),
        "placement_slot_id": support.arg("placement_slot_id"),
        "statement_id": support.arg("statement_id"),
        "employer_id": support.arg("employer_id"),
        "merchant_id": support.arg("merchant_id"),
        "entry_type": support.arg("entry_type"),
    }
    rows = []
    for row in db.ledger_entries.values():
        if any(not support.matches(row, key, value) for key, value in filters.items()):
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.ledger_json)
