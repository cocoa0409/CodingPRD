"""Supplier and DisruptionEvent endpoints (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import serial
from auth import authorize
from domain import EVENT_TYPES
from envelope import created, ok, paginated
from shapes import Field, validate
from store import ordered, store

bp = Blueprint("suppliers", __name__)

SUPPLIER_FIELDS = [
    Field("legal_name", "string", required=True, min_len=1, max_len=200),
    Field("country_of_origin", "string", required=True, pattern=r"^[A-Z]{2}$"),
    Field("declared_tariff_rate_pct", "number", minimum=0, maximum=100,
          default=Decimal("0")),
]

SUSPEND_FIELDS = [
    Field("reason", "string", required=True),
]

DISRUPTION_FIELDS = [
    Field("event_type", "enum", required=True, choices=EVENT_TYPES),
    Field("effective_date", "datetime", required=True),
    Field("description", "string", required=True, min_len=1, max_len=500),
    Field("tariff_rate_pct", "number", minimum=0, maximum=100, default=Decimal("0")),
]


@bp.post("/procurement/suppliers")
@authorize("BuyoutManager")
def create_supplier():
    body = validate(SUPPLIER_FIELDS)
    row = store.new_row()
    row.update(body)
    row["status"] = "ACTIVE"
    row["suspension_reason"] = None
    store.suppliers[row["id"]] = row
    return created(serial.supplier(row))


@bp.get("/procurement/suppliers/<supplier_id>")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def read_supplier(supplier_id):
    row = domain.get_supplier(supplier_id)
    return ok(serial.supplier(row))


@bp.get("/procurement/suppliers")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_suppliers():
    args = request.args
    status = domain.string_filter(args, "status")
    country = domain.string_filter(args, "country_of_origin")
    band = domain.string_filter(args, "exposure_band_snapshot")
    rows = []
    for row in ordered(list(store.suppliers.values())):
        if status is not None and row["status"] != status:
            continue
        if country is not None and row["country_of_origin"] != country:
            continue
        if band is not None:
            if calc.supplier_exposure(row, forward=False)[1] != band:
                continue
        rows.append(row)
    return paginated(rows, serial.supplier)


@bp.post("/procurement/suppliers/<supplier_id>/suspend")
@authorize("ProjectExecutive")
def suspend_supplier(supplier_id):
    body = validate(SUSPEND_FIELDS)
    row = domain.get_supplier(supplier_id)
    row["status"] = "SUSPENDED"
    row["suspension_reason"] = body["reason"]
    store.touch(row)
    return ok(serial.supplier(row))


@bp.post("/procurement/suppliers/<supplier_id>/disruption-events")
@authorize("BuyoutManager")
def create_disruption(supplier_id):
    body = validate(DISRUPTION_FIELDS)
    supplier = domain.get_supplier(supplier_id)
    row = store.new_row()
    row.update(body)
    row["supplier_id"] = supplier["id"]
    row["status"] = "OPEN"
    row["mitigated_at"] = None
    store.disruptions[row["id"]] = row
    return created(serial.disruption(row))


@bp.get("/procurement/suppliers/<supplier_id>/disruption-events")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_disruptions(supplier_id):
    supplier = domain.get_supplier(supplier_id)
    args = request.args
    status = domain.string_filter(args, "status")
    event_type = domain.string_filter(args, "event_type")
    rows = []
    for row in ordered(list(store.disruptions.values())):
        if row["supplier_id"] != supplier["id"]:
            continue
        if status is not None and row["status"] != status:
            continue
        if event_type is not None and row["event_type"] != event_type:
            continue
        rows.append(row)
    return paginated(rows, serial.disruption)
