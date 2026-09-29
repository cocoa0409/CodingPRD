"""Bottled inventory: lot reads and QA release.

Endpoints (4): GET /milk-lots, GET /milk-lots/{id},
GET /milk-lots/{id}/dispenses, POST /milk-lots/{id}/release.
"""

from flask import Blueprint

import serializers
from auth import (ADMIN, DISPENSING_PHARMACIST, MEDICAL_DIRECTOR,
                  PROCESSING_TECHNICIAN, QA_OFFICER, actor_id, guard)
from envelope import ok, page, pagination
from errors import fail, not_found
from listing import apply_filters, sort_by
from store import db, find, set_field
from validate import json_body  # noqa: F401  (release takes no body)

bp = Blueprint("lots", __name__)

LOT_READERS = (QA_OFFICER, DISPENSING_PHARMACIST, PROCESSING_TECHNICIAN, ADMIN)
LOT_DETAIL_READERS = (QA_OFFICER, DISPENSING_PHARMACIST, PROCESSING_TECHNICIAN,
                      MEDICAL_DIRECTOR, ADMIN)
DISPENSE_READERS = (DISPENSING_PHARMACIST, QA_OFFICER, MEDICAL_DIRECTOR, ADMIN)


def lot_or_404(lot_id):
    lot = find("lots", lot_id)
    if lot is None:
        not_found("Milk lot '%s' does not exist." % lot_id)
    return lot


# --- GET /milk-lots --------------------------------------------------------
@bp.route("/milk-lots", methods=["GET"])
@guard(*LOT_READERS)
def list_lots():
    limit, offset = pagination()
    rows = apply_filters(db.rows("lots"),
                         [("run_id", "run_id", "str"),
                          ("release_status", "release_status", "str"),
                          ("milk_class", "milk_class", "str")])
    sort_by(rows, [(lambda r: r["expiration_date"], False),
                   (lambda r: r["lot_code"], False)])
    return page(rows, limit, offset, serializers.lot_out)


# --- GET /milk-lots/{id} ---------------------------------------------------
@bp.route("/milk-lots/<lot_id>", methods=["GET"])
@guard(*LOT_DETAIL_READERS)
def get_lot(lot_id):
    return ok(serializers.lot_out(lot_or_404(lot_id)))


# --- GET /milk-lots/{id}/dispenses ----------------------------------------
@bp.route("/milk-lots/<lot_id>/dispenses", methods=["GET"])
@guard(*DISPENSE_READERS)
def list_lot_dispenses(lot_id):
    lot = lot_or_404(lot_id)
    limit, offset = pagination()
    rows = [d for d in db.rows("dispenses") if d["lot_id"] == lot["id"]]
    rows = apply_filters(rows, [("status", "status", "str")])
    sort_by(rows, [(lambda r: r["created_at"], False),
                   (lambda r: r["_seq"], False)])
    return page(rows, limit, offset, serializers.dispense_out)


# --- POST /milk-lots/{id}/release -----------------------------------------
@bp.route("/milk-lots/<lot_id>/release", methods=["POST"])
@guard(QA_OFFICER)
def release_lot(lot_id):
    lot = lot_or_404(lot_id)
    if lot["release_status"] != "HOLD":
        fail("ERR_LOT_STATE_INVALID",
             "A lot in %s may not be released." % lot["release_status"])
    run = find("runs", lot["run_id"])
    if run is None or run["release_eligibility"] != "ELIGIBLE":
        fail("ERR_RUN_NOT_RELEASE_ELIGIBLE",
             "The lot's run is not release-eligible on both dimensions.")
    actor = actor_id()
    if actor == run["completed_by_user_id"] \
            or actor == run["culture_recorded_by_user_id"]:
        fail("ERR_SOD_RELEASE_CONFLICT",
             "The releasing officer may not have completed or cultured the run.")

    set_field(lot, "released_at", db.clock_instant())
    set_field(lot, "released_by_user_id", actor)
    set_field(lot, "release_status", "RELEASED")
    return ok(serializers.lot_out(lot))
