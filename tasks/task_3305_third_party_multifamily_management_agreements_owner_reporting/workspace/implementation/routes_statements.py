"""Routes: MonthlyStatements."""

from datetime import datetime, timezone

from flask import Blueprint, request

import calc
from db import db, new_id, now_iso, get_clock
from errors import (
    books_locked,
    invalid_request,
    invalid_state_transition,
    statement_period_open,
)
from middleware import (
    get_or_404,
    month_add,
    req_enum,
    req_month,
    require_roles,
)
from response import body, ok_object, paginate

bp = Blueprint("statements", __name__)

GET_ROLES = ("PortfolioManager", "PropertyAccountant", "OwnerRep")


def stmt_out(s, preview=False):
    out = dict(s)
    out.pop("_frozen", None)
    return out


def _arg(name):
    return request.args.get(name)


def _refresh_computed(s):
    """Recompute statement computed fields from current ledger/staff state."""
    fields = calc.compute_statement_fields(s)
    s.update(fields)


@bp.post("/mgmt/properties/<propertyId>/statements")
def create_statement(propertyId):
    require_roles("PropertyAccountant")
    prop = get_or_404(db.properties, propertyId)
    if prop["management_posture"] not in ("MANAGED", "TRANSITIONING_OUT"):
        raise invalid_state_transition("Property must be managed to open a statement")
    data = body()
    period_month = req_month(data, "period_month")
    basis = req_enum(data, "basis", ("CASH", "ACCRUAL"))
    now = now_iso()
    s = {
        "id": new_id(),
        "property_id": propertyId,
        "period_month": period_month,
        "basis": basis,
        "collected_revenue_cents": 0,
        "base_fee_cents": 0,
        "incentive_fee_cents": 0,
        "payroll_charge_cents": 0,
        "management_fee_total_cents": 0,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.statements[s["id"]] = s
    return ok_object(stmt_out(s), status=201)


@bp.get("/mgmt/statements/<statementId>")
def get_statement(statementId):
    require_roles(*GET_ROLES)
    s = get_or_404(db.statements, statementId)
    if s["status"] == "OPEN":
        _refresh_computed(s)  # preview computations while OPEN
    return ok_object(stmt_out(s))


@bp.get("/mgmt/properties/<propertyId>/statements")
def list_statements_for_property(propertyId):
    require_roles(*GET_ROLES)
    get_or_404(db.properties, propertyId)
    period_month = _arg("period_month")
    status = _arg("status")
    items = sorted(
        (s for s in db.statements.values() if s["property_id"] == propertyId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    if period_month is not None:
        items = [s for s in items if s["period_month"] == period_month]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate([stmt_out(s) for s in items])


@bp.get("/mgmt/statements")
def list_statements():
    require_roles(*GET_ROLES)
    property_id = _arg("property_id")
    period_month = _arg("period_month")
    status = _arg("status")
    items = sorted(db.statements.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [s for s in items if s["property_id"] == property_id]
    if period_month is not None:
        items = [s for s in items if s["period_month"] == period_month]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate([stmt_out(s) for s in items])


def _first_day_after_period(period_month):
    """First day of the month following period_month, as a datetime (UTC)."""
    nxt = month_add(period_month, 1)
    y = int(nxt[:4])
    m = int(nxt[5:7])
    return datetime(y, m, 1, tzinfo=timezone.utc)


@bp.post("/mgmt/statements/<statementId>/close")
def close_statement(statementId):
    require_roles("PropertyAccountant")
    s = get_or_404(db.statements, statementId)
    if s["status"] != "OPEN":
        raise invalid_state_transition("Statement must be OPEN to close")
    prop = db.properties[s["property_id"]]
    if prop["management_posture"] not in ("MANAGED", "TRANSITIONING_OUT"):
        raise invalid_state_transition("Property posture does not permit statement close")
    if get_clock() < _first_day_after_period(s["period_month"]):
        raise statement_period_open()
    # Run computations and freeze
    _refresh_computed(s)
    now = now_iso()
    s["status"] = "CLOSED"
    s["updated_at"] = now
    s["version"] += 1
    # Cascade: cash reduced by management_fee_total + payroll_charge (manager paid)
    total_paid = s["management_fee_total_cents"] + s["payroll_charge_cents"]
    prop["cash_available_cents"] = prop.get("cash_available_cents", 0) - total_paid
    prop["updated_at"] = now
    prop["version"] += 1
    # Cascade: DRAFT OwnerReportPackage for same property+period -> GENERATED
    for r in db.reports.values():
        if (
            r["property_id"] == s["property_id"]
            and r["period_month"] == s["period_month"]
            and r["status"] == "DRAFT"
        ):
            r["status"] = "GENERATED"
            if r["package_type"] == "MONTHLY_OWNER":
                r["distribution_amount_cents"] = calc.owner_distribution_cents(
                    prop, r["period_month"]
                )
            else:
                r["distribution_amount_cents"] = 0
            r["updated_at"] = now
            r["version"] += 1
    return ok_object(stmt_out(s))


@bp.post("/mgmt/statements/<statementId>/restate")
def restate_statement(statementId):
    require_roles("PropertyAccountant")
    s = get_or_404(db.statements, statementId)
    if s["status"] != "CLOSED":
        raise invalid_state_transition("Only CLOSED statements can be restated")
    locked = any(
        r for r in db.reports.values()
        if r["property_id"] == s["property_id"]
        and r["period_month"] == s["period_month"]
        and r["status"] == "DELIVERED"
    )
    if locked:
        raise books_locked()
    _refresh_computed(s)
    s["updated_at"] = now_iso()
    s["version"] += 1
    return ok_object(stmt_out(s))
