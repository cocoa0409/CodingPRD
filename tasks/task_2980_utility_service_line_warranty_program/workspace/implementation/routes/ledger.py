"""The immutable money ledger: append-only, no version, no mutation endpoint."""

from flask import Blueprint

import config
import serializers
from errors import ApiError
from response import object_response, paginate
from store import ordered, store
from validation import current_user_id, filter_enum, filter_value, require_path_uuid, require_role

bp = Blueprint("ledger", __name__)

READ_ROLES = (
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_CUSTOMER_SERVICE_REP,
    config.ROLE_BILLING_OPS,
    config.ROLE_REGULATORY_AFFAIRS,
    config.ROLE_OPERATIONS_ADMIN,
)


def lookup_ledger_entry(entry_id):
    entry = store.ledger_entries.get(entry_id)
    if entry is None:
        raise ApiError("ERR_LEDGER_ENTRY_NOT_FOUND", "No ledger entry with id %s" % entry_id)
    return entry


@bp.get("/ledger-entries")
def list_ledger_entries():
    current_user_id()
    require_role(*READ_ROLES)
    enrollment_id = filter_value("enrollment_id")
    claim_id = filter_value("claim_id")
    ledger_kind = filter_enum("ledger_kind", config.LEDGER_KINDS)
    entry_type = filter_enum("entry_type", config.LEDGER_ENTRY_TYPES)

    def matches(row):
        if enrollment_id is not None and row["enrollment_id"] != enrollment_id:
            return False
        if claim_id is not None and row["claim_id"] != claim_id:
            return False
        if ledger_kind is not None and row["ledger_kind"] != ledger_kind:
            return False
        if entry_type is not None and row["entry_type"] != entry_type:
            return False
        return True

    return paginate(ordered(store.ledger_entries, matches), serializers.ledger_entry)


@bp.get("/ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    current_user_id()
    require_role(*READ_ROLES)
    require_path_uuid(entry_id)
    return object_response(serializers.ledger_entry(lookup_ledger_entry(entry_id)))
