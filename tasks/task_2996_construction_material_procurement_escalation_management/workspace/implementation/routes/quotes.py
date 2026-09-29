"""Quote endpoints (PRD 3.3)."""

from flask import Blueprint, request

import calc
import domain
import serial
from auth import authorize, current_role, current_user_id
from envelope import created, ok, paginated
from errors import ApiError
from shapes import Field, validate
from store import ordered, store
from util import add_days

bp = Blueprint("quotes", __name__)

QUOTE_FIELDS = [
    Field("material_package_id", "string", required=True),
    Field("supplier_id", "string", required=True),
    Field("base_price", "number", required=True, exclusive_minimum=0, max_dp=2),
    Field("received_at", "datetime", required=True),
    Field("price_hold_days", "int", required=True, minimum=1, maximum=120),
]

REVISE_FIELDS = [
    Field("base_price", "number", required=True, exclusive_minimum=0, max_dp=2),
    Field("received_at", "datetime", required=True),
    Field("price_hold_days", "int", required=True, minimum=1, maximum=120),
]


def _check_overlap(package_id, supplier_id, start, end, exempt_quote_id=None):
    """Half-open [received_at, expires_at) overlap against OPEN/CONVERTED quotes."""
    for row in ordered(list(store.quotes.values())):
        if row["material_package_id"] != package_id:
            continue
        if row["supplier_id"] != supplier_id:
            continue
        if row["status"] not in ("OPEN", "CONVERTED"):
            continue
        if exempt_quote_id is not None and row["id"] == exempt_quote_id:
            continue
        if start < row["expires_at"] and row["received_at"] < end:
            raise ApiError("ERR_PRICE_HOLD_OVERLAP")


def _revive_package(pkg):
    if pkg["status"] == "IDENTIFIED":
        pkg["status"] = "SOURCING"
        store.touch(pkg)
    elif pkg["status"] == "SOURCING_STALLED":
        pkg["status"] = "SOURCING"
        store.touch(pkg)


@bp.post("/procurement/quotes")
@authorize("SupplierRep")
def create_quote():
    body = validate(QUOTE_FIELDS)
    pkg = domain.get_package(body["material_package_id"])
    supplier = domain.get_supplier(body["supplier_id"])
    if current_role() == "SupplierRep" and current_user_id() != supplier["id"]:
        raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
    if body["received_at"] > store.clock:
        raise ApiError("ERR_INVALID_REQUEST", "received_at may not be later than the clock")
    expires_at = add_days(body["received_at"], body["price_hold_days"])
    _check_overlap(pkg["id"], supplier["id"], body["received_at"], expires_at)
    row = store.new_row()
    row.update(body)
    row["supersedes_quote_id"] = None
    row["expires_at"] = expires_at
    row["status"] = "OPEN"
    store.quotes[row["id"]] = row
    _revive_package(pkg)
    return created(serial.quote(row))


@bp.get("/procurement/quotes/<quote_id>")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def read_quote(quote_id):
    row = domain.get_quote(quote_id)
    return ok(serial.quote(row))


@bp.get("/procurement/quotes")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_quotes():
    args = request.args
    package_id = domain.string_filter(args, "material_package_id")
    supplier_id = domain.string_filter(args, "supplier_id")
    supersedes = domain.string_filter(args, "supersedes_quote_id")
    status = domain.string_filter(args, "status")
    rows = []
    for row in ordered(list(store.quotes.values())):
        if package_id is not None and row["material_package_id"] != package_id:
            continue
        if supplier_id is not None and row["supplier_id"] != supplier_id:
            continue
        if supersedes is not None and row["supersedes_quote_id"] != supersedes:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paginated(rows, serial.quote)


@bp.post("/procurement/quotes/<quote_id>/revise")
@authorize("SupplierRep")
def revise_quote(quote_id):
    body = validate(REVISE_FIELDS)
    old = domain.get_quote(quote_id)
    if current_role() == "SupplierRep" and current_user_id() != old["supplier_id"]:
        raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
    if old["status"] != "OPEN":
        raise ApiError("ERR_QUOTE_NOT_OPEN")
    if body["received_at"] > store.clock:
        raise ApiError("ERR_INVALID_REQUEST", "received_at may not be later than the clock")
    expires_at = add_days(body["received_at"], body["price_hold_days"])
    _check_overlap(
        old["material_package_id"], old["supplier_id"], body["received_at"], expires_at,
        exempt_quote_id=old["id"],
    )
    old["status"] = "SUPERSEDED"
    store.touch(old)
    row = store.new_row()
    row["material_package_id"] = old["material_package_id"]
    row["supplier_id"] = old["supplier_id"]
    row["supersedes_quote_id"] = old["id"]
    row["base_price"] = body["base_price"]
    row["received_at"] = body["received_at"]
    row["price_hold_days"] = body["price_hold_days"]
    row["expires_at"] = expires_at
    row["status"] = "OPEN"
    store.quotes[row["id"]] = row
    _revive_package(store.packages[row["material_package_id"]])
    return created(serial.quote(row))
