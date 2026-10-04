"""Routes: StaffPositions and LedgerEntries."""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import invalid_request
from middleware import (
    get_or_404,
    opt_enum,
    opt_int,
    req_enum,
    req_int,
    req_month,
    req_str,
    require_roles,
    valid_month,
)
from response import body, ok_object, paginate

bp = Blueprint("staff_ledger", __name__)

STAFF_GET_ROLES = ("PortfolioManager", "PropertyAccountant", "OwnerRep")
LEDGER_GET_ROLES = ("PortfolioManager", "PropertyAccountant", "OwnerRep", "RiskOfficer")
LEDGER_KINDS = ("RENT", "FEE", "RECOVERY", "CONCESSION", "EXPENSE", "PAYROLL")


def staff_out(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def ledger_out(e):
    return dict(e)


def _arg(name):
    return request.args.get(name)


# ---------- Staff ----------

@bp.post("/mgmt/properties/<propertyId>/staff")
def create_staff(propertyId):
    require_roles("PortfolioManager")
    get_or_404(db.properties, propertyId)
    data = body()
    role_title = req_str(data, "role_title")
    hourly_cost_cents = req_int(data, "hourly_cost_cents")
    scheduled_hours_per_week = req_int(data, "scheduled_hours_per_week")
    shared_region_code = req_str(data, "shared_region_code")
    if hourly_cost_cents < 0 or scheduled_hours_per_week < 0:
        raise invalid_request("hourly cost and hours must be non-negative")
    now = now_iso()
    s = {
        "id": new_id(),
        "property_id": propertyId,
        "role_title": role_title,
        "hourly_cost_cents": hourly_cost_cents,
        "scheduled_hours_per_week": scheduled_hours_per_week,
        "shared_region_code": shared_region_code,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.staff[s["id"]] = s
    return ok_object(staff_out(s), status=201)


@bp.get("/mgmt/staff/<staffPositionId>")
def get_staff(staffPositionId):
    require_roles(*STAFF_GET_ROLES)
    s = get_or_404(db.staff, staffPositionId)
    return ok_object(staff_out(s))


@bp.get("/mgmt/properties/<propertyId>/staff")
def list_staff_for_property(propertyId):
    require_roles(*STAFF_GET_ROLES)
    get_or_404(db.properties, propertyId)
    status = _arg("status")
    items = sorted(
        (s for s in db.staff.values() if s["property_id"] == propertyId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate([staff_out(s) for s in items])


@bp.get("/mgmt/staff")
def list_staff():
    require_roles(*STAFF_GET_ROLES)
    property_id = _arg("property_id")
    status = _arg("status")
    items = sorted(db.staff.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [s for s in items if s["property_id"] == property_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate([staff_out(s) for s in items])


# ---------- Ledger entries ----------

@bp.post("/mgmt/properties/<propertyId>/ledger-entries")
def create_ledger_entry(propertyId):
    require_roles("PropertyAccountant")
    prop = get_or_404(db.properties, propertyId)
    data = body()
    kind = req_enum(data, "kind", LEDGER_KINDS)
    amount = req_int(data, "amount_cents")
    accrual_month = req_month(data, "accrual_month")
    collected_month = data.get("collected_month")
    if collected_month is not None and not valid_month(collected_month):
        raise invalid_request("collected_month must be YYYY-MM")
    resident_id = data.get("resident_id")
    if resident_id is not None:
        res = db.residents.get(resident_id)
        if res is None or res["property_id"] != propertyId:
            raise invalid_request("resident_id does not reference a resident of this property")
    # Charges positive, credits negative: reject negative amounts on charge kinds
    if kind in ("RENT", "FEE", "RECOVERY", "EXPENSE", "PAYROLL") and amount < 0:
        raise invalid_request("Charge-kind amounts must be non-negative")
    now = now_iso()
    e = {
        "id": new_id(),
        "property_id": propertyId,
        "resident_id": resident_id,
        "kind": kind,
        "amount_cents": amount,
        "accrual_month": accrual_month,
        "collected_month": collected_month,
        "status": "POSTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.ledger[e["id"]] = e
    # Cash effect: when collected_month set, revenue credits increase cash;
    # charges with collected_month also collected (rent collected = cash in).
    # PRD §2.9: cash = credits minus charges minus fees/payroll minus reserves.
    # Revenue kinds (RENT/FEE/RECOVERY) with collected_month bring cash in by
    # amount; CONCESSION (credit) reduces; EXPENSE/PAYROLL pay cash out.
    if kind in ("RENT", "FEE", "RECOVERY") and collected_month is not None:
        prop["cash_available_cents"] = prop.get("cash_available_cents", 0) + amount
        prop["updated_at"] = now
    elif kind == "CONCESSION" and collected_month is not None:
        prop["cash_available_cents"] = prop.get("cash_available_cents", 0) + amount
        prop["updated_at"] = now
    elif kind in ("EXPENSE", "PAYROLL"):
        prop["cash_available_cents"] = prop.get("cash_available_cents", 0) - amount
        prop["updated_at"] = now
    return ok_object(ledger_out(e), status=201)


@bp.get("/mgmt/ledger-entries/<ledgerEntryId>")
def get_ledger_entry(ledgerEntryId):
    require_roles(*LEDGER_GET_ROLES)
    e = get_or_404(db.ledger, ledgerEntryId)
    return ok_object(ledger_out(e))


def _filter_ledger(items):
    resident_id = _arg("resident_id")
    kind = _arg("kind")
    status = _arg("status")
    accrual_month = _arg("accrual_month")
    collected_month = _arg("collected_month")
    if resident_id is not None:
        items = [e for e in items if e.get("resident_id") == resident_id]
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if accrual_month is not None:
        items = [e for e in items if e.get("accrual_month") == accrual_month]
    if collected_month is not None:
        items = [e for e in items if e.get("collected_month") == collected_month]
    return items


@bp.get("/mgmt/properties/<propertyId>/ledger-entries")
def list_ledger_for_property(propertyId):
    require_roles(*LEDGER_GET_ROLES)
    get_or_404(db.properties, propertyId)
    items = sorted(
        (e for e in db.ledger.values() if e["property_id"] == propertyId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    return paginate([ledger_out(e) for e in _filter_ledger(items)])


@bp.get("/mgmt/ledger-entries")
def list_ledger():
    require_roles(*LEDGER_GET_ROLES)
    property_id = _arg("property_id")
    items = sorted(db.ledger.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [e for e in items if e["property_id"] == property_id]
    return paginate([ledger_out(e) for e in _filter_ledger(items)])
