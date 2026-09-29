"""Processor programs (PRD 3.1)."""
from flask import Blueprint

from apierrors import fail
from auth import authorize
from envelope import apply_filters, list_response, object_response
from serial import program as ser_program
from shapes import as_enum, as_int, as_str, body, present
from store import db, new_id, ordered, stamp_new, touch

bp = Blueprint("programs", __name__)

NORMALIZATION_MODES = ("NET_REVENUE_SPLIT", "GROSS_SPLIT")
MINIMUM_BILLING_MODES = ("SHORTFALL_BILLED", "NO_MINIMUM")


def _lookup(program_id):
    row = db.programs.get(program_id)
    if row is None:
        fail("ERR_PROGRAM_NOT_FOUND", "no processor program with id %s" % program_id)
    return row


@bp.route("/processor-programs", methods=["POST"])
def create_program():
    authorize("IsoAdmin")
    payload = body()
    name = as_str(payload, "name", min_len=1, max_len=120)
    buy_rate_bps = as_int(payload, "buy_rate_bps", minimum=0, maximum=500)
    buy_rate_per_item_cents = as_int(payload, "buy_rate_per_item_cents", minimum=0)
    assessment_bps = as_int(payload, "assessment_bps", minimum=0, maximum=100)
    normalization_mode = as_enum(payload, "normalization_mode", NORMALIZATION_MODES)
    minimum_billing_mode = as_enum(
        payload, "minimum_billing_mode", MINIMUM_BILLING_MODES,
        required=False, default="SHORTFALL_BILLED")
    row = {
        "id": new_id(),
        "name": name,
        "buy_rate_bps": buy_rate_bps,
        "buy_rate_per_item_cents": buy_rate_per_item_cents,
        "assessment_bps": assessment_bps,
        "normalization_mode": normalization_mode,
        "minimum_billing_mode": minimum_billing_mode,
        "status": "ACTIVE",
    }
    stamp_new(row)
    db.programs[row["id"]] = row
    return object_response(ser_program(row), 201)


@bp.route("/processor-programs", methods=["GET"])
def list_programs():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    rows = apply_filters(list(db.programs.values()), [("status", "status")])
    return list_response(ordered(rows), ser_program)


@bp.route("/processor-programs/<program_id>", methods=["GET"])
def get_program(program_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    return object_response(ser_program(_lookup(program_id)))


@bp.route("/processor-programs/<program_id>", methods=["PATCH"])
def patch_program(program_id):
    authorize("IsoAdmin")
    payload = body()
    name = as_str(payload, "name", required=False, min_len=1, max_len=120)
    buy_rate_bps = as_int(payload, "buy_rate_bps", required=False, minimum=0, maximum=500)
    per_item = as_int(payload, "buy_rate_per_item_cents", required=False, minimum=0)
    assessment_bps = as_int(payload, "assessment_bps", required=False, minimum=0, maximum=100)
    minimum_billing_mode = as_enum(
        payload, "minimum_billing_mode", MINIMUM_BILLING_MODES, required=False)
    row = _lookup(program_id)
    if present(payload, "name"):
        row["name"] = name
    if present(payload, "buy_rate_bps"):
        row["buy_rate_bps"] = buy_rate_bps
    if present(payload, "buy_rate_per_item_cents"):
        row["buy_rate_per_item_cents"] = per_item
    if present(payload, "assessment_bps"):
        row["assessment_bps"] = assessment_bps
    if present(payload, "minimum_billing_mode"):
        row["minimum_billing_mode"] = minimum_billing_mode
    touch(row)
    return object_response(ser_program(row))


@bp.route("/processor-programs/<program_id>/suspend", methods=["POST"])
def suspend_program(program_id):
    authorize("IsoAdmin")
    row = _lookup(program_id)
    row["status"] = "SUSPENDED"
    touch(row)
    return object_response(ser_program(row))


@bp.route("/processor-programs/<program_id>/reinstate", methods=["POST"])
def reinstate_program(program_id):
    authorize("IsoAdmin")
    row = _lookup(program_id)
    row["status"] = "ACTIVE"
    touch(row)
    return object_response(ser_program(row))
