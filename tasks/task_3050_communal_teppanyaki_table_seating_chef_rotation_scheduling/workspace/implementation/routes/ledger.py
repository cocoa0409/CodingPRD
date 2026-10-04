"""VenueLedgerEntry endpoints."""
from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from errors import fail
from middleware import guard
from response import ok

bp = Blueprint("ledger", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/ledger-entries", methods=["GET"])
def list_entries():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("ledger_entries"), venue_id=h.q("venue_id"),
                         reservation_id=h.q("reservation_id"),
                         entry_kind=h.q("entry_kind"), status=h.q("status"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/ledger-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    guard(READ_ROLES)
    entry = svc.ledger_or_404(entry_id)
    return ok(db.public(entry), 200)


@bp.route("/service-floor/ledger-entries/<entry_id>/void", methods=["POST"])
def void_entry(entry_id):
    guard(["Host"])
    entry = svc.ledger_or_404(entry_id)
    if entry.get("status") != "POSTED":
        fail("ERR_INVALID_STATE")
    entry = svc.void_ledger_entry(entry, by_cascade=False)
    return ok(db.public(entry), 200)