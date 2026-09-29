"""Signing lines and handing a reserved line back (PRD 3.5)."""
from flask import Blueprint

import db
import response
import serialize
import services
from errors import fail
from middleware import BROKER_PLACEMENT_LEAD, require
from routes._common import REINSURER_READ, ordered_filtered, paged, q

bp = Blueprint("lines", __name__)


@bp.route("/signing-lines", methods=["GET"])
def list_signing_lines():
    require(REINSURER_READ)
    rows = ordered_filtered(db.signing_lines, [
        ("layer_id", q("layer_id")),
        ("quote_id", q("quote_id")),
        ("reinsurer_id", q("reinsurer_id")),
        ("status", q("status")),
    ])
    return paged(rows, serialize.signing_line)


@bp.route("/signing-lines/<signing_line_id>", methods=["GET"])
def read_signing_line(signing_line_id):
    require(REINSURER_READ)
    row = services.get_signing_line(signing_line_id)
    return response.object_response(serialize.signing_line(row), 200)


@bp.route("/signing-lines/<signing_line_id>/release", methods=["POST"])
def release_signing_line(signing_line_id):
    require((BROKER_PLACEMENT_LEAD,))
    line = services.get_signing_line(signing_line_id)
    if line["status"] not in ("PROVISIONAL", "SIGNED"):
        fail("ERR_SIGNING_LINE_STATE_INVALID",
             "a %s line cannot be released" % line["status"])
    layer = services.layer_of_line(line)
    if layer["status"] == "BOUND":
        fail("ERR_LAYER_STATE_INVALID", "a bound layer's lines cannot be released")
    program = services.program_of_line(line)
    if program["placement_status"] != "FIRM_ORDER":
        fail("ERR_PROGRAM_STATE_INVALID", "the owning program must be in FIRM_ORDER")

    services.release_line_cascade(line, "WITHDRAWN_BY_BROKER")
    services.revert_layer_after_release(layer)
    services.revert_program_from_firm_order(program)
    services.recompute_reinsurer_capacity(line["reinsurer_id"])
    return response.object_response(serialize.signing_line(line), 200)
