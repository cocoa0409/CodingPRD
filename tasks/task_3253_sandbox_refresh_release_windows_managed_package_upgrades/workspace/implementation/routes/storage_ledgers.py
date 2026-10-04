"""Storage-ledger route (PRD §4)."""

from flask import Blueprint

import middleware
import response
from services import common, storage

bp = Blueprint("storage_ledgers", __name__)


@bp.post("/platform/storage-ledgers/<ledger_id>/restore")
def restore(ledger_id):
    actor = middleware.require("StorageArchivist")
    ledger = common.get_storage_ledger(ledger_id)
    env = storage.restore_ledger(actor, ledger)
    from serializers import environment

    return response.ok(environment(env))