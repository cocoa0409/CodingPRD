"""Routes: OwnerReportPackages."""

from flask import Blueprint, request

import calc
from db import db, new_id, now_iso, get_clock
from errors import (
    distribution_window_missed,
    invalid_state_transition,
)
from middleware import (
    get_or_404,
    req_enum,
    req_month,
    require_roles,
)
from response import body, ok_object, paginate

bp = Blueprint("reports", __name__)

GET_ROLES = ("PortfolioManager", "PropertyAccountant", "OwnerRep")


def report_out(r):
    return dict(r)


def _arg(name):
    return request.args.get(name)


@bp.post("/mgmt/properties/<propertyId>/reports")
def create_report(propertyId):
    require_roles("PropertyAccountant")
    get_or_404(db.properties, propertyId)
    data = body()
    period_month = req_month(data, "period_month")
    package_type = req_enum(data, "package_type", ("MONTHLY_OWNER", "LENDER"))
    now = now_iso()
    r = {
        "id": new_id(),
        "property_id": propertyId,
        "period_month": period_month,
        "package_type": package_type,
        "distribution_amount_cents": 0,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.reports[r["id"]] = r
    return ok_object(report_out(r), status=201)


@bp.get("/mgmt/reports/<reportId>")
def get_report(reportId):
    require_roles(*GET_ROLES)
    r = get_or_404(db.reports, reportId)
    return ok_object(report_out(r))


@bp.get("/mgmt/properties/<propertyId>/reports")
def list_reports_for_property(propertyId):
    require_roles(*GET_ROLES)
    get_or_404(db.properties, propertyId)
    period_month = _arg("period_month")
    package_type = _arg("package_type")
    status = _arg("status")
    items = sorted(
        (r for r in db.reports.values() if r["property_id"] == propertyId),
        key=lambda x: (x["created_at"], x["id"]),
    )
    if period_month is not None:
        items = [r for r in items if r["period_month"] == period_month]
    if package_type is not None:
        items = [r for r in items if r["package_type"] == package_type]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([report_out(r) for r in items])


@bp.get("/mgmt/reports")
def list_reports():
    require_roles(*GET_ROLES)
    property_id = _arg("property_id")
    period_month = _arg("period_month")
    package_type = _arg("package_type")
    status = _arg("status")
    items = sorted(db.reports.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [r for r in items if r["property_id"] == property_id]
    if period_month is not None:
        items = [r for r in items if r["period_month"] == period_month]
    if package_type is not None:
        items = [r for r in items if r["package_type"] == package_type]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([report_out(r) for r in items])


def _closed_statement_for(property_id, period_month):
    for s in db.statements.values():
        if (
            s["property_id"] == property_id
            and s["period_month"] == period_month
            and s["status"] == "CLOSED"
        ):
            return s
    return None


@bp.post("/mgmt/reports/<reportId>/generate")
def generate_report(reportId):
    require_roles("PropertyAccountant")
    r = get_or_404(db.reports, reportId)
    if r["status"] != "DRAFT":
        raise invalid_state_transition("Report must be DRAFT to generate")
    stmt = _closed_statement_for(r["property_id"], r["period_month"])
    if stmt is None:
        raise invalid_state_transition("No CLOSED statement exists for this property+period")
    prop = db.properties[r["property_id"]]
    r["status"] = "GENERATED"
    if r["package_type"] == "MONTHLY_OWNER":
        r["distribution_amount_cents"] = calc.owner_distribution_cents(prop, r["period_month"])
    else:
        r["distribution_amount_cents"] = 0
    r["updated_at"] = now_iso()
    r["version"] += 1
    return ok_object(report_out(r))


@bp.post("/mgmt/reports/<reportId>/deliver")
def deliver_report(reportId):
    require_roles("PropertyAccountant")
    r = get_or_404(db.reports, reportId)
    if r["status"] != "GENERATED":
        raise invalid_state_transition("Report must be GENERATED to deliver")
    prop = db.properties[r["property_id"]]
    now = now_iso()
    if r["package_type"] == "MONTHLY_OWNER":
        owner = db.owners.get(prop["owner_id"])
        dom = owner["distribution_day_of_month"] if owner else 10
        clock = get_clock()
        if clock.day > dom + 5:
            raise distribution_window_missed()
        # Post the distribution
        if r["distribution_amount_cents"] > 0:
            prop["cash_available_cents"] = prop.get("cash_available_cents", 0) - r[
                "distribution_amount_cents"
            ]
            prop["updated_at"] = now
            prop["version"] += 1
            e = {
                "id": new_id(),
                "property_id": r["property_id"],
                "resident_id": None,
                "kind": "EXPENSE",
                "amount_cents": r["distribution_amount_cents"],
                "accrual_month": r["period_month"],
                "collected_month": r["period_month"],
                "status": "POSTED",
                "created_at": now,
                "updated_at": now,
                "version": 1,
            }
            db.ledger[e["id"]] = e
    r["status"] = "DELIVERED"
    r["updated_at"] = now
    r["version"] += 1
    return ok_object(report_out(r))
