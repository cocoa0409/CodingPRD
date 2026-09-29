"""The append-only fleet cost ledger: read and list only (PRD 2.10)."""

from flask import Blueprint

import serialize
import validate
from auth import ALL_ROLES, authorize
from envelope import ok
from filters import collect
from store import store

bp = Blueprint("ledger", __name__)


@bp.route("/fleet/ledger-entries/<ledger_entry_id>", methods=["GET"])
def read_ledger_entry(ledger_entry_id):
    authorize(ALL_ROLES)
    return ok(serialize.ledger_entry(validate.load("ledger_entry", ledger_entry_id)))


@bp.route("/fleet/ledger-entries", methods=["GET"])
def list_ledger_entries():
    authorize(ALL_ROLES)
    return collect(
        store.ledger.values(),
        [
            ("vehicle_id", "vehicle_id", "str"),
            ("entry_type", "entry_type", "str"),
            ("source_entity_type", "source_entity_type", "str"),
            ("source_entity_id", "source_entity_id", "str"),
        ],
        serialize.ledger_entry,
        sort_keys=("posted_at", "created_at"),
    )
