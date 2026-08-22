"""The allowance book: budget lines, selections, buy-out lock and reconciliation."""
from decimal import Decimal

from flask import Blueprint

from errors import AppError
from store import db, base_row, now, bump, ordered
from util import (
    authorize, check_staff_identity, parse_body, ok, ok_list, paginate, qfilter,
    req_str, req_enum, req_money, opt_money, req_dt, req_int, q2,
)
from routes.common import fetch, own_project
from services.constants import ALLOWANCE_CATEGORIES, LEDGER_COST_STATUSES
from services.calc import selection_total, material_ready_at
from services.ledger import recompute_project, project_allowance_items
from services.rows import new_change_order_row

bp = Blueprint("allowances", __name__)

ALLOWANCE_READ_ROLES = ["PlatformAdmin", "ProjectManager", "Estimator", "Controller",
                        "Client", "Lender"]
SELECTION_READ_ROLES = ["PlatformAdmin", "ProjectManager", "Estimator", "Controller",
                        "Client"]
SETTLE_ACTIONS = ("LOCK", "RECONCILE")
SELECTION_DECISIONS = ("APPROVE", "REJECT")


# ------------------------------------------------------------ allowance items
@bp.post("/allowance-items")
def create_allowance_item():
    user_id, role = authorize(["ProjectManager"])
    body = parse_body()
    project_id = req_str(body, "project_id")
    category = req_enum(body, "category", ALLOWANCE_CATEGORIES)
    allowance_amount = req_money(body, "allowance_amount", minimum=Decimal("0"),
                                 exclusive_min=True)
    selection_deadline = req_dt(body, "selection_deadline")

    project = db.projects.get(project_id)
    if project is None:
        raise AppError("ERR_PROJECT_NOT_FOUND")
    check_staff_identity(user_id, role)

    row = base_row()
    row.update({
        "project_id": project_id,
        "category": category,
        "allowance_amount": q2(allowance_amount),
        "selection_deadline": selection_deadline,
        "status": "OPEN",
        "selected_selection_id": None,
        "provisional_variance_amount": Decimal("0.00"),
        "final_variance_amount": None,
        "reconciled_amount": None,
        "material_lead_time_days": None,
        "locked_at": None,
        "frozen_at": None,
        "reconciled_at": None,
    })
    db.allowance_items[row["id"]] = row
    return ok(row, 201)


@bp.get("/allowance-items/<item_id>")
def get_allowance_item(item_id):
    user_id, role = authorize(ALLOWANCE_READ_ROLES)
    item = fetch("allowance_items", item_id)
    check_staff_identity(user_id, role)
    return ok(item, 200)


@bp.get("/allowance-items")
def list_allowance_items():
    user_id, role = authorize(ALLOWANCE_READ_ROLES)
    check_staff_identity(user_id, role)
    rows = ordered(db.allowance_items.values())
    project_id = qfilter("project_id")
    status = qfilter("status")
    selected_selection_id = qfilter("selected_selection_id")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if selected_selection_id:
        rows = [r for r in rows if r["selected_selection_id"] == selected_selection_id]
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/allowance-items/<item_id>/settle")
def settle_allowance_item(item_id):
    user_id, role = authorize(["Controller"])
    item = fetch("allowance_items", item_id)
    body = parse_body()
    action = req_enum(body, "action", SETTLE_ACTIONS)
    check_staff_identity(user_id, role)

    project = db.projects.get(item["project_id"])

    # ladder step 10 - target state admits the transition
    if action == "LOCK" and item["status"] != "SELECTED":
        raise AppError("ERR_ALLOWANCE_INVALID_STATE")
    if action == "RECONCILE" and item["status"] != "LOCKED":
        raise AppError("ERR_ALLOWANCE_INVALID_STATE")

    # ladder step 11 - parent project state
    if project is None or project["status"] != "UNDER_CONSTRUCTION":
        raise AppError("ERR_PROJECT_NOT_UNDER_CONSTRUCTION")

    if action == "LOCK":
        selection = db.selections.get(item.get("selected_selection_id"))
        lead_time_days = selection["lead_time_days"] if selection else 0

        item["status"] = "LOCKED"
        item["locked_at"] = now()
        item["material_lead_time_days"] = lead_time_days

        for task in ordered([t for t in db.schedule_tasks.values()
                             if t.get("driving_allowance_item_id") == item["id"]]):
            task["material_ready_at"] = material_ready_at(item["locked_at"], lead_time_days)
            bump(task)

        variance = item.get("provisional_variance_amount") or Decimal("0")
        if variance > 0:
            change_order = new_change_order_row(
                project_id=item["project_id"],
                origin="ALLOWANCE_OVERAGE",
                scope_description="Allowance overage on %s allowance line %s"
                                  % (item["category"], item["id"]),
                direct_cost=q2(variance),
                schedule_impact_days=0,
                source_allowance_item_id=item["id"],
            )
            db.change_orders[change_order["id"]] = change_order

        bump(item)
        recompute_project(project)
        return ok(item, 200)

    # RECONCILE - ladder step 25
    qualifying = [ce for ce in db.cost_entries.values()
                  if ce.get("source_allowance_item_id") == item["id"]
                  and ce["entry_type"] == "ALLOWANCE_ACTUAL"
                  and ce["status"] in LEDGER_COST_STATUSES]
    if not qualifying:
        raise AppError("ERR_ALLOWANCE_ACTUAL_MISSING")

    reconciled_amount = q2(sum((ce["amount"] for ce in qualifying), Decimal("0")))
    item["reconciled_amount"] = reconciled_amount
    item["final_variance_amount"] = q2(reconciled_amount - item["allowance_amount"])
    item["reconciled_at"] = now()
    item["status"] = "RECONCILED"
    bump(item)
    recompute_project(project)
    return ok(item, 200)


# ---------------------------------------------------------------- selections
@bp.post("/selections")
def create_selection():
    user_id, role = authorize(["Client"])
    body = parse_body()
    allowance_item_id = req_str(body, "allowance_item_id")
    vendor_name = req_str(body, "vendor_name")
    vendor_quote_amount = req_money(body, "vendor_quote_amount", minimum=Decimal("0"))
    freight_amount = opt_money(body, "freight_amount", Decimal("0"), minimum=Decimal("0"))
    install_amount = opt_money(body, "install_amount", Decimal("0"), minimum=Decimal("0"))
    lead_time_days = req_int(body, "lead_time_days", minimum=0)
    expected_version = req_int(body, "expected_allowance_item_version")

    # ladder step 6
    item = db.allowance_items.get(allowance_item_id)
    if item is None:
        raise AppError("ERR_ALLOWANCE_ITEM_NOT_FOUND")
    project = db.projects.get(item["project_id"])

    # ladder step 8
    own_project(project, user_id, role)

    # ladder step 11
    if project is None or project["status"] != "UNDER_CONSTRUCTION":
        raise AppError("ERR_PROJECT_NOT_UNDER_CONSTRUCTION")

    # ladder step 12
    if item["status"] != "OPEN" or project["budget_posture"] == "OVER_GMP":
        raise AppError("ERR_ALLOWANCE_FROZEN")

    # ladder step 13
    if expected_version != item["version"]:
        raise AppError("ERR_STALE_ALLOWANCE_VERSION")

    # ladder step 28
    if now() > item["selection_deadline"]:
        raise AppError("ERR_SELECTION_DEADLINE_PASSED")

    for existing in ordered([s for s in db.selections.values()
                             if s["allowance_item_id"] == item["id"]]):
        if existing["status"] == "PROPOSED":
            existing["status"] = "SUPERSEDED"
            existing["superseded_at"] = now()
            bump(existing)

    row = base_row()
    row.update({
        "allowance_item_id": item["id"],
        "vendor_name": vendor_name,
        "vendor_quote_amount": q2(vendor_quote_amount),
        "freight_amount": q2(freight_amount),
        "install_amount": q2(install_amount),
        "lead_time_days": lead_time_days,
        "selection_total": selection_total(vendor_quote_amount, freight_amount,
                                           install_amount),
        "status": "PROPOSED",
        "decided_at": None,
        "superseded_at": None,
    })
    db.selections[row["id"]] = row

    bump(item)
    return ok(row, 201)


@bp.get("/selections/<selection_id>")
def get_selection(selection_id):
    user_id, role = authorize(SELECTION_READ_ROLES)
    selection = fetch("selections", selection_id)
    check_staff_identity(user_id, role)
    return ok(selection, 200)


@bp.get("/allowance-items/<item_id>/selections")
def list_item_selections(item_id):
    user_id, role = authorize(SELECTION_READ_ROLES)
    item = fetch("allowance_items", item_id)
    check_staff_identity(user_id, role)
    rows = ordered([s for s in db.selections.values()
                    if s["allowance_item_id"] == item["id"]])
    rows.reverse()  # newest first (PRD 2.3)
    status = qfilter("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/selections/<selection_id>/decision")
def decide_selection(selection_id):
    user_id, role = authorize(["ProjectManager"])
    selection = fetch("selections", selection_id)
    body = parse_body()
    decision = req_enum(body, "decision", SELECTION_DECISIONS)
    check_staff_identity(user_id, role)

    item = db.allowance_items.get(selection["allowance_item_id"])
    project = db.projects.get(item["project_id"]) if item else None

    # ladder step 10
    if selection["status"] != "PROPOSED":
        raise AppError("ERR_SELECTION_NOT_PENDING")

    if decision == "REJECT":
        selection["status"] = "REJECTED"
        selection["decided_at"] = now()
        bump(selection)
        return ok(selection, 200)

    # APPROVE - the parent line must still be OPEN on a project that is not OVER_GMP
    if item is None or item["status"] != "OPEN" or (
            project is not None and project["budget_posture"] == "OVER_GMP"):
        raise AppError("ERR_ALLOWANCE_FROZEN")

    selection["status"] = "ACCEPTED"
    selection["decided_at"] = now()
    bump(selection)

    item["selected_selection_id"] = selection["id"]
    item["provisional_variance_amount"] = q2(
        selection["selection_total"] - item["allowance_amount"])
    item["status"] = "SELECTED"
    bump(item)

    if project is not None:
        recompute_project(project)
    return ok(selection, 200)
