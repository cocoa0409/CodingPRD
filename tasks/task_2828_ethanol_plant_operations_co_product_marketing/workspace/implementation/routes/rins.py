"""Renewable credit batches: read, list and retirement."""
import guards
import serialize
from envelope import ok, ok_list
from errors import fail
from routes import bp
from shape import enum_param, int_param, page, pagination, require_auth, str_param, take
from store import db, touch

RETIRE_SPEC = {"retirement_reference": {"type": "string", "required": True}}
RIN_STATUSES = ("GENERATED", "SEPARATED", "RETIRED")


@bp.route("/rin-batches/<rin_id>", methods=["GET"])
def get_rin(rin_id):
    require_auth(["PlantManager", "ComplianceOfficer", "RiskManager"])
    rin = guards.get_rin(rin_id)
    return ok(serialize.rin_out(rin))


@bp.route("/rin-batches", methods=["GET"])
def list_rins():
    require_auth(["PlantManager", "ComplianceOfficer", "RiskManager"])
    batch_id = str_param("fermentation_batch_id")
    shipment_id = str_param("separated_shipment_id")
    status = enum_param("status", RIN_STATUSES)
    rin_year = int_param("rin_year")
    limit, offset = pagination()
    if batch_id is not None:
        guards.get_batch(batch_id)
    if shipment_id is not None:
        guards.get_shipment(shipment_id)
    rows = list(db.rins.values())
    if batch_id is not None:
        rows = [r for r in rows if r["fermentation_batch_id"] == batch_id]
    if shipment_id is not None:
        rows = [r for r in rows if r["separated_shipment_id"] == shipment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if rin_year is not None:
        rows = [r for r in rows if int(r["rin_year"]) == rin_year]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.rin_out(r) for r in window], limit, offset, len(rows))


@bp.route("/rin-batches/<rin_id>/retire", methods=["POST"])
def retire_rin(rin_id):
    require_auth(["ComplianceOfficer"])
    body = take(RETIRE_SPEC)
    rin = guards.get_rin(rin_id)
    if rin["status"] != "SEPARATED":
        fail("ERR_INVALID_RIN_STATE",
             "Credit batch is %s and may not be retired" % rin["status"])
    shipment = db.shipments.get(rin["separated_shipment_id"])
    if shipment is None or shipment["billing_status"] != "INVOICED":
        fail("ERR_SHIPMENT_NOT_INVOICED",
             "The separating shipment has not been invoiced")
    rin["status"] = "RETIRED"
    rin["retirement_reference"] = body["retirement_reference"]
    rin["retired_at"] = db.clock
    touch(rin)
    return ok(serialize.rin_out(rin))
