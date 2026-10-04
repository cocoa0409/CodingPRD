"""Formulation changes and rematch tasks."""
from flask import Blueprint, request

import db
import services
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_stale_version,
    err_effective_date_invalid, err_equipment_not_calibrated,
)
from response import (
    body, get_auth, require_roles, require_dealer_principal, success_obj,
    paginate, req_string, req_ts,
)

bp = Blueprint("formulation", __name__)

READ = ["PlatformAdmin", "RegionManager", "ChannelDirector", "ColorLabAdmin", "DealerPrincipal"]


def _serialize_change(c):
    return dict(c)


def _serialize_task(t):
    return dict(t)


# ---------------- formulation changes ----------------

@bp.post("/formulation-changes")
def create_change():
    _, role = get_auth()
    require_roles(role, ["ColorLabAdmin"])
    data = body()
    pl_id = req_string(data, "product_line_id")
    title = req_string(data, "title")
    reason = req_string(data, "reason")
    effective_date = req_ts(data, "effective_date")
    if pl_id not in db.product_lines:
        raise err_not_found("product_line_id not found")
    rec = db.new_common()
    rec.update({
        "product_line_id": pl_id,
        "title": title,
        "reason": reason,
        "effective_date": db.fmt_ts(effective_date),
        "status": "DRAFT",
    })
    db.formulation_changes[rec["id"]] = rec
    return success_obj(_serialize_change(rec), 201)


@bp.get("/formulation-changes")
def list_changes():
    _, role = get_auth()
    require_roles(role, READ)
    items = list(db.formulation_changes.values())
    pl_id = request.args.get("product_line_id")
    if pl_id is not None:
        items = [c for c in items if c["product_line_id"] == pl_id]
    return paginate([_serialize_change(c) for c in items])


@bp.get("/formulation-changes/<cid>")
def get_change(cid):
    _, role = get_auth()
    require_roles(role, READ)
    c = db.formulation_changes.get(cid)
    if c is None:
        raise err_not_found("formulation change not found")
    return success_obj(_serialize_change(c))


def _get_change_or_404(cid):
    c = db.formulation_changes.get(cid)
    if c is None:
        raise err_not_found("formulation change not found")
    return c


@bp.post("/formulation-changes/<cid>/announce")
def announce_change(cid):
    _, role = get_auth()
    require_roles(role, ["ColorLabAdmin"])
    c = _get_change_or_404(cid)
    data = body()
    # OCC before state preconditions
    if "expected_change_version" in data and data["expected_change_version"] is not None:
        expected = data["expected_change_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err_invalid_request("expected_change_version must be an integer")
        if expected != c["version"]:
            raise err_stale_version()
    if c["status"] != "DRAFT":
        raise err_invalid_state("formulation change is not DRAFT")
    eff = db.parse_ts(c["effective_date"])
    if eff is None or eff <= db.now():
        raise err_effective_date_invalid("effective_date must be strictly after now at announce")
    c["status"] = "ANNOUNCED"
    db.touch(c)
    return success_obj(_serialize_change(c))


@bp.post("/formulation-changes/<cid>/make-effective")
def make_effective(cid):
    _, role = get_auth()
    require_roles(role, ["ColorLabAdmin"])
    c = _get_change_or_404(cid)
    if c["status"] != "ANNOUNCED":
        raise err_invalid_state("formulation change is not ANNOUNCED")
    eff = db.parse_ts(c["effective_date"])
    if eff is None or eff > db.now():
        raise err_effective_date_invalid("effective_date must be at or before now at make-effective")
    c["status"] = "EFFECTIVE"
    db.touch(c)
    # fan out the rematch wave
    pl = db.product_lines.get(c["product_line_id"])
    cs_id = pl["colorant_system_id"] if pl else None
    affected = [
        f for f in db.formulas.values()
        if f["product_line_id"] == c["product_line_id"] and f["status"] == "ACTIVE"
    ]
    eligible_dealers = []
    if cs_id is not None:
        for lic in db.licenses.values():
            services._sweep_license(lic)
            if lic["colorant_system_id"] == cs_id and lic["status"] in ("ACTIVE", "SUSPENDED"):
                if lic["dealer_id"] not in eligible_dealers:
                    eligible_dealers.append(lic["dealer_id"])
    for f in affected:
        old_version = f["formulation_version"]
        for dealer_id in eligible_dealers:
            task = {
                "id": db.new_id(),
                "created_at": db.fmt_ts(db.now()),
                "formulation_change_id": c["id"],
                "dealer_id": dealer_id,
                "color_formula_id": f["id"],
                "old_formulation_version": old_version,
                "new_formulation_version": old_version + 1,
                "status": "PENDING",
            }
            db.rematch_tasks[task["id"]] = task
        f["formulation_version"] = old_version + 1
        f["rematch_pending"] = len(eligible_dealers) > 0
        db.touch(f)
    return success_obj(_serialize_change(c))


@bp.post("/formulation-changes/<cid>/cancel")
def cancel_change(cid):
    _, role = get_auth()
    require_roles(role, ["ColorLabAdmin"])
    c = _get_change_or_404(cid)
    if c["status"] not in ("DRAFT", "ANNOUNCED"):
        raise err_invalid_state("formulation change is not DRAFT or ANNOUNCED")
    c["status"] = "CANCELLED"
    db.touch(c)
    return success_obj(_serialize_change(c))


# ---------------- rematch tasks ----------------

@bp.get("/rematch-tasks")
def list_rematch_tasks():
    _, role = get_auth()
    require_roles(role, READ)
    items = list(db.rematch_tasks.values())
    dealer_id = request.args.get("dealer_id")
    change_id = request.args.get("formulation_change_id")
    formula_id = request.args.get("color_formula_id")
    if dealer_id is not None:
        items = [t for t in items if t["dealer_id"] == dealer_id]
    if change_id is not None:
        items = [t for t in items if t["formulation_change_id"] == change_id]
    if formula_id is not None:
        items = [t for t in items if t["color_formula_id"] == formula_id]
    return paginate([_serialize_task(t) for t in items])


@bp.get("/formulation-changes/<cid>/rematch-tasks")
def list_change_tasks(cid):
    _, role = get_auth()
    require_roles(role, READ)
    if cid not in db.formulation_changes:
        raise err_not_found("formulation change not found")
    items = [t for t in db.rematch_tasks.values() if t["formulation_change_id"] == cid]
    return paginate([_serialize_task(t) for t in items])


@bp.get("/dealers/<did>/rematch-tasks")
def list_dealer_tasks(did):
    _, role = get_auth()
    require_roles(role, READ)
    if did not in db.dealers:
        raise err_not_found("dealer not found")
    items = [t for t in db.rematch_tasks.values() if t["dealer_id"] == did]
    return paginate([_serialize_task(t) for t in items])


@bp.get("/formulas/<fid>/rematch-tasks")
def list_formula_tasks(fid):
    _, role = get_auth()
    require_roles(role, READ)
    if fid not in db.formulas:
        raise err_not_found("formula not found")
    items = [t for t in db.rematch_tasks.values() if t["color_formula_id"] == fid]
    return paginate([_serialize_task(t) for t in items])


@bp.post("/rematch-tasks/<tid>/complete")
def complete_task(tid):
    user_id, role = get_auth()
    require_roles(role, ["DealerPrincipal"])
    t = db.rematch_tasks.get(tid)
    if t is None:
        raise err_not_found("rematch task not found")
    require_dealer_principal(user_id, role, t["dealer_id"])
    if t["status"] != "PENDING":
        raise err_invalid_state("rematch task is not PENDING")
    formula = db.formulas.get(t["color_formula_id"])
    pl = db.product_lines.get(formula["product_line_id"]) if formula else None
    cs_id = pl["colorant_system_id"] if pl else None
    services.sweep_equipment([u for u in db.equipment.values() if u["dealer_id"] == t["dealer_id"]])
    has_calibrated = any(
        u["dealer_id"] == t["dealer_id"]
        and u["colorant_system_id"] == cs_id
        and u["status"] == "CALIBRATED"
        for u in db.equipment.values()
    )
    if not has_calibrated:
        raise err_equipment_not_calibrated()
    t["status"] = "DONE"
    services.complete_task_bubble_up(t)
    return success_obj(_serialize_task(t))
