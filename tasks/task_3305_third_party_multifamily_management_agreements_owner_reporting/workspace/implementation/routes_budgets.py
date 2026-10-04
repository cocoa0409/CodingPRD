"""Routes: Budgets."""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import (
    invalid_request,
    invalid_state_transition,
    not_found,
    reforecast_requires_base,
    sod_violation,
    stale_version,
)
from middleware import (
    get_or_404,
    opt_enum,
    opt_int,
    req_enum,
    req_int,
    req_str,
    require_roles,
)
from response import body, ok_object, paginate

bp = Blueprint("budgets", __name__)

GET_ROLES = ("PortfolioManager", "PropertyAccountant", "OwnerRep")


def budget_out(b):
    return dict(b)


def _arg(name):
    return request.args.get(name)


def _validate_reforecast_base(prop_id, fiscal_year, supersedes_id, expected_version):
    """Common validation for REFORECAST budgets. Returns the base budget."""
    base = db.budgets.get(supersedes_id) if supersedes_id else None
    if (
        base is None
        or base["property_id"] != prop_id
        or base["fiscal_year"] != fiscal_year
        or base["status"] != "APPROVED"
    ):
        raise reforecast_requires_base()
    if expected_version is not None and expected_version != base["version"]:
        raise stale_version()
    return base


@bp.post("/mgmt/budgets")
def create_budget():
    user_id, _ = require_roles("PropertyAccountant")
    data = body()
    property_id = req_str(data, "property_id")
    get_or_404(db.properties, property_id)
    fiscal_year = req_int(data, "fiscal_year")
    kind = opt_enum(data, "kind", ("ANNUAL", "REFORECAST"), "ANNUAL")
    operating_revenue_cents = req_int(data, "operating_revenue_cents")
    operating_expense_cents = req_int(data, "operating_expense_cents")
    capex_total_cents = req_int(data, "capex_total_cents")
    supersedes_budget_id = data.get("supersedes_budget_id")
    expected_base_budget_version = data.get("expected_base_budget_version")

    if kind == "REFORECAST":
        if not supersedes_budget_id:
            raise reforecast_requires_base()
        _validate_reforecast_base(
            property_id, fiscal_year, supersedes_budget_id, expected_base_budget_version
        )

    now = now_iso()
    b = {
        "id": new_id(),
        "property_id": property_id,
        "fiscal_year": fiscal_year,
        "kind": kind,
        "operating_revenue_cents": operating_revenue_cents,
        "operating_expense_cents": operating_expense_cents,
        "capex_total_cents": capex_total_cents,
        "supersedes_budget_id": supersedes_budget_id,
        "status": "DRAFT",
        "decided_by": None,
        "_submitted_by": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.budgets[b["id"]] = b
    return ok_object(budget_out(b), status=201)


@bp.get("/mgmt/budgets/<budgetId>")
def get_budget(budgetId):
    require_roles(*GET_ROLES)
    b = get_or_404(db.budgets, budgetId)
    return ok_object(budget_out(b))


@bp.get("/mgmt/budgets")
def list_budgets():
    require_roles(*GET_ROLES)
    property_id = _arg("property_id")
    fiscal_year = _arg("fiscal_year")
    kind = _arg("kind")
    status = _arg("status")
    supersedes = _arg("supersedes_budget_id")
    items = sorted(db.budgets.values(), key=lambda x: (x["created_at"], x["id"]))
    if property_id is not None:
        items = [b for b in items if b["property_id"] == property_id]
    if fiscal_year is not None:
        try:
            fy = int(fiscal_year)
        except ValueError:
            raise invalid_request("fiscal_year must be an integer")
        items = [b for b in items if b["fiscal_year"] == fy]
    if kind is not None:
        items = [b for b in items if b["kind"] == kind]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if supersedes is not None:
        items = [b for b in items if b.get("supersedes_budget_id") == supersedes]
    return paginate([budget_out(b) for b in items])


@bp.post("/mgmt/budgets/<budgetId>/submit")
def submit_budget(budgetId):
    user_id, _ = require_roles("PropertyAccountant")
    b = get_or_404(db.budgets, budgetId)
    if b["status"] != "DRAFT":
        raise invalid_state_transition("Budget must be DRAFT to submit")
    prop = db.properties.get(b["property_id"])
    if prop is None or prop["management_posture"] != "MANAGED":
        raise invalid_state_transition("Property must be MANAGED to submit a budget")
    if b["kind"] == "REFORECAST":
        base = db.budgets.get(b.get("supersedes_budget_id") or "")
        if (
            base is None
            or base["property_id"] != b["property_id"]
            or base["fiscal_year"] != b["fiscal_year"]
            or base["status"] != "APPROVED"
        ):
            raise reforecast_requires_base()
    b["status"] = "SUBMITTED"
    b["_submitted_by"] = user_id
    b["updated_at"] = now_iso()
    b["version"] += 1
    return ok_object(budget_out(b))


@bp.post("/mgmt/budgets/<budgetId>/approve")
def approve_budget(budgetId):
    user_id, _ = require_roles("OwnerRep")
    b = get_or_404(db.budgets, budgetId)
    if b["status"] != "SUBMITTED":
        raise invalid_state_transition("Budget must be SUBMITTED to approve")
    if b.get("_submitted_by") is not None and b["_submitted_by"] == user_id:
        raise sod_violation()
    now = now_iso()
    b["status"] = "APPROVED"
    b["decided_by"] = user_id
    b["updated_at"] = now
    b["version"] += 1
    if b["kind"] == "REFORECAST" and b.get("supersedes_budget_id"):
        base = db.budgets.get(b["supersedes_budget_id"])
        if base is not None and base["status"] == "APPROVED":
            base["status"] = "SUPERSEDED"
            base["updated_at"] = now
            base["version"] += 1
    return ok_object(budget_out(b))


@bp.post("/mgmt/budgets/<budgetId>/reject")
def reject_budget(budgetId):
    user_id, _ = require_roles("OwnerRep")
    b = get_or_404(db.budgets, budgetId)
    if b["status"] != "SUBMITTED":
        raise invalid_state_transition("Budget must be SUBMITTED to reject")
    if b.get("_submitted_by") is not None and b["_submitted_by"] == user_id:
        raise sod_violation()
    b["status"] = "REJECTED"
    b["decided_by"] = user_id
    b["updated_at"] = now_iso()
    b["version"] += 1
    return ok_object(budget_out(b))
