"""Small helpers shared by the route modules."""
import secrets

from flask import request

import db
import response
import validate
from errors import ApiError

NOT_FOUND = {
    "merchants": "ERR_MERCHANT_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "employers": "ERR_EMPLOYER_NOT_FOUND",
    "eligibility_files": "ERR_ELIGIBILITY_FILE_NOT_FOUND",
    "memberships": "ERR_MEMBERSHIP_NOT_FOUND",
    "offers": "ERR_OFFER_NOT_FOUND",
    "placement_slots": "ERR_PLACEMENT_SLOT_NOT_FOUND",
    "redemptions": "ERR_REDEMPTION_NOT_FOUND",
    "disputes": "ERR_DISPUTE_NOT_FOUND",
    "statements": "ERR_STATEMENT_NOT_FOUND",
    "ledger_entries": "ERR_LEDGER_ENTRY_NOT_FOUND",
}


def fetch(store_name, row_id):
    """Band 2 of PRD 2.9: resolve an identifier or fail with its own code."""
    store = getattr(db, store_name)
    row = store.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[store_name], "No such %s." % store_name[:-1].replace("_", " "))
    return row


def occ(row, body, field):
    """PRD 2.7: the echo field is required and must equal the parent version."""
    raw = body.get(field, None)
    if raw is None:
        raise ApiError("ERR_VALIDATION", "Field '%s' is required." % field)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ApiError("ERR_VALIDATION", "Field '%s' must be an integer." % field)
    if raw != row["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "The echoed %s does not match the current version." % field,
        )


def page(rows, serializer):
    """PRD 2.3: created_at ASC unless the caller already ordered the rows."""
    limit, offset = validate.pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return response.listing([serializer(r) for r in window], limit, offset, total)


def paged_sorted(rows, serializer):
    return page(db.sorted_rows(rows), serializer)


def arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def matches(row, key, value):
    return value is None or row.get(key) == value


def token():
    return secrets.token_urlsafe(24)


def resolve_fk(body, key, store_name):
    """Band 2 before band 3: a supplied FK is resolved before schema checks.

    A missing or non-string FK cannot name a row, so it falls through to the
    schema band, which reports it as a missing required field.
    """
    raw = body.get(key)
    if isinstance(raw, str) and raw.strip() != "":
        return fetch(store_name, raw)
    return None
