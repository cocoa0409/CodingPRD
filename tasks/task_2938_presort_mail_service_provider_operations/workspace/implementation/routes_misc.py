"""Containers, service-level records, invoice settlement and the logical clock."""

from flask import Blueprint

import domain
import serialize
import shape
from envelope import listed, single
from errors import ApiError
from store import db, touch
from util import fmt_instant, parse_instant

bp = Blueprint("misc", __name__)

ALL_OPS = ("BureauAdmin", "PostageManager", "PresortOperator", "AcceptanceClerk")


# ------------------------------------------------------------- containers ---

@bp.get("/sort-containers/<container_id>")
def read_container(container_id):
    shape.authenticate(ALL_OPS)
    return single(serialize.sort_container(domain.get_container(container_id)))


@bp.get("/sort-containers/<container_id>/service-level-records")
def list_container_records(container_id):
    shape.authenticate(("BureauAdmin", "PostageManager", "AcceptanceClerk"))
    domain.get_container(container_id)
    return listed(
        domain.container_records(container_id), serialize.service_level_record
    )


# --------------------------------------------------- service-level records ---

@bp.get("/service-level-records/<record_id>")
def read_service_level_record(record_id):
    shape.authenticate(
        ("BureauAdmin", "PostageManager", "AcceptanceClerk", "ClientContact")
    )
    return single(serialize.service_level_record(domain.get_slr(record_id)))


@bp.post("/service-level-records/<record_id>/delivery-scan")
def delivery_scan(record_id):
    shape.authenticate(("AcceptanceClerk",))
    body = shape.validate_body(
        {
            "actual_delivery_days": {"type": "integer", "check": shape.int_min(0)},
            "scanned_at_utc": {"type": "datetime"},
        }
    )
    record = domain.get_slr(record_id)
    # rung 36
    if record["actual_delivery_days"] is not None:
        raise ApiError("ERR_DELIVERY_ALREADY_SCANNED")
    record["actual_delivery_days"] = body["actual_delivery_days"]
    record["scanned_at_utc"] = parse_instant(body["scanned_at_utc"])
    record["on_time"] = body["actual_delivery_days"] <= record["committed_days"]
    touch(record)
    return single(serialize.service_level_record(record))


# ------------------------------------------------------ invoice settlement ---

@bp.get("/client-invoices/<invoice_id>")
def read_invoice(invoice_id):
    shape.authenticate(("BureauAdmin", "PostageManager", "ClientContact"))
    return single(serialize.client_invoice(domain.get_invoice(invoice_id)))


@bp.post("/client-invoices/<invoice_id>/payment")
def pay_invoice(invoice_id):
    shape.authenticate(("PostageManager",))
    body = shape.validate_body({"amount_cents": {"type": "integer"}})
    invoice = domain.get_invoice(invoice_id)
    # rung 15
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_INVOICE_STATE")
    # rung 44
    if body["amount_cents"] != invoice["total_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")
    invoice["status"] = "PAID"
    invoice["paid_amount_cents"] = body["amount_cents"]
    touch(invoice)
    return single(serialize.client_invoice(invoice))


# ---------------------------------------------------------- logical clock ---

@bp.post("/_clock/set_current_utc")
def set_clock():
    shape.authenticate(("BureauAdmin",))
    body = shape.validate_body({"to_iso8601": {"type": "datetime"}})
    db.clock = parse_instant(body["to_iso8601"])

    no_shows = []
    for shipment in db.ordered("drop_shipments"):
        if shipment["status"] != "SCHEDULED":
            continue
        if shipment["window_end_utc"] < db.clock:
            shipment["status"] = "NO_SHOW"
            touch(shipment)
            no_shows.append(shipment["id"])
    return single(
        {
            "current_utc": fmt_instant(db.clock),
            "no_show_shipment_ids": no_shows,
        }
    )
