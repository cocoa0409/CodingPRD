"""Settlement certification and invoicing (PRD 3.9)."""
from flask import Blueprint

import serializers as ser
from calc import refresh_exposure
from core import (acting_role, acting_user, apply_filters, authenticate, db, fail,
                  field_string, get_body, lookup_path, paginate, respond_object, touch)

bp = Blueprint("settlements", __name__)

READERS = ("PipelineScheduler", "TariffAdministrator", "Shipper")
STAFF = ("PipelineScheduler", "TariffAdministrator")


def get_settlement(row_id):
    return lookup_path(db.settlements, row_id, "ERR_SETTLEMENT_NOT_FOUND")


@bp.route("/pipeline/settlements/<row_id>/certify", methods=["POST"])
def certify(row_id):
    authenticate(("PipelineScheduler",))
    settlement = get_settlement(row_id)
    get_body()
    if settlement["status"] != "DRAFT":
        fail("ERR_SETTLEMENT_INVALID_STATE",
             "Only a DRAFT settlement can be certified, not {}.".format(settlement["status"]))
    cycle = db.cycles.get(settlement["cycle_id"])
    publisher = cycle["schedule_published_by_user_id"] if cycle else None
    if publisher is not None and publisher == acting_user():
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The operator who published the schedule may not certify this settlement.")
    settlement["status"] = "CERTIFIED"
    settlement["certified_by_user_id"] = acting_user()
    touch(settlement)
    return respond_object(ser.settlement_json(settlement))


@bp.route("/pipeline/settlements/<row_id>/invoice", methods=["POST"])
def invoice(row_id):
    authenticate(("TariffAdministrator",))
    settlement = get_settlement(row_id)
    body = get_body()
    number = field_string(body, "invoice_number")
    if settlement["status"] != "CERTIFIED":
        fail("ERR_SETTLEMENT_INVALID_STATE",
             "Only a CERTIFIED settlement can be invoiced, not {}.".format(settlement["status"]))
    if settlement["certified_by_user_id"] is not None \
            and settlement["certified_by_user_id"] == acting_user():
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The certifying operator may not invoice this settlement.")
    settlement["status"] = "INVOICED"
    settlement["invoice_number"] = number
    touch(settlement)
    shipper = db.shippers.get(settlement["shipper_id"])
    if shipper is not None:
        refresh_exposure(shipper)
    return respond_object(ser.settlement_json(settlement))


@bp.route("/pipeline/settlements/<row_id>", methods=["GET"])
def read_settlement(row_id):
    authenticate(READERS)
    settlement = get_settlement(row_id)
    if acting_role() == "Shipper" and settlement["shipper_id"] != acting_user():
        fail("ERR_NOT_RESOURCE_OWNER", "This settlement belongs to another shipper.")
    return respond_object(ser.settlement_json(settlement))


def _shipper_key(row):
    shipper = db.shippers.get(row["shipper_id"])
    if shipper is None:
        return (row["created_at"], row["_seq"], row["created_at"], row["_seq"])
    return (shipper["created_at"], shipper["_seq"], row["created_at"], row["_seq"])


@bp.route("/pipeline/settlements", methods=["GET"])
def list_settlements():
    authenticate(STAFF)
    rows = apply_filters(list(db.settlements.values()), [
        ("cycle_id", "cycle_id", "str"),
        ("shipper_id", "shipper_id", "str"),
        ("status", "status", "str"),
    ])
    rows.sort(key=_shipper_key)
    return paginate(rows, ser.settlement_json)
