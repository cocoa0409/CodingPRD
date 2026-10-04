"""Game project routes."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_VERSION_UNSUPPORTED, ERR_ORG_SUSPENDED,
)
from helpers import (
    ok, ok_list, body, new_common, touch, current_date, iso_date_str,
)
from middleware import (
    authenticate, authorize, get_org_or_404, check_org_ownership,
    ERR_FORBIDDEN_ORG,
)
from services_calc import compute_risk_score, compute_standing
from routes_orgs import _is_migrated

bp = Blueprint("projects", __name__)


def _check_project_owner(role, uid, project):
    if role == "OrgOwner" and uid != project["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your project")


@bp.route("/orgs/<oid>/projects", methods=["POST"])
def create_project(oid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner", "PlatformAdmin"})
    check_org_ownership(role, uid, oid)
    org = get_org_or_404(oid)
    if _is_migrated(oid) or org["org_standing"] == "SUSPENDED":
        raise_err(ERR_ORG_SUSPENDED, "Org suspended or migrated")
    b = body()
    title = b.get("title")
    evid = b.get("editor_version_id")
    if not isinstance(title, str) or not isinstance(evid, str):
        raise_err(ERR_VALIDATION, "title and editor_version_id are required strings")
    charity = b.get("charity_flag", False)
    if not isinstance(charity, bool):
        raise_err(ERR_VALIDATION, "charity_flag must be a boolean")
    ev = db.editor_versions.get(evid)
    if ev is None or ev["support_status"] == "SUNSET":
        raise_err(ERR_VERSION_UNSUPPORTED, "Editor version missing or SUNSET")
    ent = new_common()
    ent.update({
        "org_id": oid,
        "title": title,
        "editor_version_id": evid,
        "charity_flag": charity,
        "project_status": "DEVELOPMENT",
        "shipped_on": None,
        "lifetime_installs": 0,
        "upgrade_risk_score": 0,
        "pinned_policy_change_id": None,
    })
    db.projects[ent["id"]] = ent
    ent["upgrade_risk_score"] = compute_risk_score(ent)
    return ok(ent, 201)


@bp.route("/orgs/<oid>/projects", methods=["GET"])
def list_org_projects(oid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"})
    check_org_ownership(role, uid, oid)
    get_org_or_404(oid)
    items = [p for p in db.projects.values() if p["org_id"] == oid]
    items.sort(key=lambda p: p["created_at"])
    ps = request.args.get("project_status")
    if ps:
        items = [p for p in items if p["project_status"] == ps]
    return ok_list(items)


@bp.route("/projects", methods=["GET"])
def list_projects():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "FinanceOps", "Auditor"})
    items = sorted(db.projects.values(), key=lambda p: p["created_at"])
    ev = request.args.get("editor_version_id")
    og = request.args.get("org_id")
    pc = request.args.get("pinned_policy_change_id")
    if ev:
        items = [p for p in items if p["editor_version_id"] == ev]
    if og:
        items = [p for p in items if p["org_id"] == og]
    if pc:
        items = [p for p in items if p.get("pinned_policy_change_id") == pc]
    return ok_list(items)


@bp.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor", "ReviewBoard"})
    p = db.projects.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Project not found")
    _check_project_owner(role, uid, p)
    return ok(p)


@bp.route("/projects/<pid>/ship", methods=["POST"])
def ship_project(pid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    p = db.projects.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Project not found")
    _check_project_owner(role, uid, p)
    if p["project_status"] != "DEVELOPMENT":
        raise_err(ERR_INVALID_STATE, "Project must be DEVELOPMENT to ship")
    org = get_org_or_404(p["org_id"])
    compute_standing(org)
    if org["org_standing"] == "SUSPENDED":
        raise_err(ERR_ORG_SUSPENDED, "Org is suspended")
    ev = db.editor_versions.get(p["editor_version_id"])
    if ev is None or ev["support_status"] == "SUNSET":
        raise_err(ERR_VERSION_UNSUPPORTED, "Pinned editor version is SUNSET")
    today = current_date()
    p["project_status"] = "SHIPPED"
    p["shipped_on"] = iso_date_str(today)
    p["lifetime_installs"] = 0
    p["upgrade_risk_score"] = compute_risk_score(p)
    touch(p)
    # Grandfathering evaluation: ACTIVE adverse retroactive change with open window,
    # project shipped on or before announcement_date
    from helpers import parse_date, add_days
    from helpers import new_common as nc
    for pc in db.policy_changes.values():
        if pc["change_status"] != "ACTIVE":
            continue
        if not (pc.get("retroactive_flag") and pc.get("adverse_flag")):
            continue
        ann = parse_date(pc["announcement_date"])
        if ann is None:
            continue
        deadline = add_days(ann, pc["grandfather_window_days"])
        shipped = parse_date(p["shipped_on"])
        if shipped is not None and shipped <= ann and today <= deadline:
            # Avoid duplicate commitment
            exists = any(
                c["project_id"] == p["id"] and c["policy_change_id"] == pc["id"]
                and c["commitment_status"] == "ACTIVE"
                for c in db.grandfather_commitments.values()
            )
            if not exists:
                ent = nc()
                ent.update({
                    "policy_change_id": pc["id"],
                    "org_id": p["org_id"],
                    "project_id": p["id"],
                    "locked_schedule_label": "BASE",
                    "commitment_status": "ACTIVE",
                    "attestation_deadline": iso_date_str(deadline),
                    "attested": False,
                })
                db.grandfather_commitments[ent["id"]] = ent
                p["pinned_policy_change_id"] = pc["id"]
                touch(p)
    return ok(p)
