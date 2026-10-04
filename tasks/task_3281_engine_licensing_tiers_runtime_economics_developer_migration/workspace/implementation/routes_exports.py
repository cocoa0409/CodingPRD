"""Export agreement and export build routes."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_INVALID_INTERVAL, ERR_AGREEMENT_OVERLAP, ERR_AGREEMENT_INACTIVE,
    ERR_TIER_FEATURE_NOT_ALLOWED, ERR_ORG_SUSPENDED, ERR_PROJECT_FROZEN,
)
from helpers import (
    ok, ok_list, body, new_common, new_id, now_iso, touch, parse_date,
    iso_date_str, current_date,
)
from middleware import (
    authenticate, authorize, get_org_or_404, check_org_ownership,
    ERR_FORBIDDEN_ORG,
)
from services_calc import active_tier_config
from routes_orgs import _is_migrated

bp = Blueprint("exports", __name__)

READ_ROLES = {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"}
PLATFORMS = {"CONSOLE_A", "CONSOLE_B", "CONSOLE_C"}


def _overlaps_existing(oid, platform, start, end, exclude_id=None):
    for a in db.export_agreements.values():
        if a["org_id"] != oid or a["platform_code"] != platform:
            continue
        if exclude_id and a["id"] == exclude_id:
            continue
        if a["agreement_status"] not in ("ACTIVE", "PENDING"):
            continue
        s2 = parse_date(a["term_start"]); e2 = parse_date(a["term_end"])
        if s2 is None or e2 is None:
            continue
        # Closed interval: touching counts as conflict
        if start <= e2 and s2 <= end:
            return True
    return False


@bp.route("/orgs/<oid>/export-agreements", methods=["POST"])
def create_agreement(oid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    check_org_ownership(role, uid, oid)
    org = get_org_or_404(oid)
    if _is_migrated(oid) or org["org_standing"] == "SUSPENDED":
        raise_err(ERR_ORG_SUSPENDED, "Org suspended or migrated")
    b = body()
    platform = b.get("platform_code")
    if platform not in PLATFORMS:
        raise_err(ERR_VALIDATION, "platform_code invalid")
    start = parse_date(b.get("term_start"))
    end = parse_date(b.get("term_end"))
    if start is None or end is None or start > end:
        raise_err(ERR_INVALID_INTERVAL, "term_start must be <= term_end")
    if _overlaps_existing(oid, platform, start, end):
        raise_err(ERR_AGREEMENT_OVERLAP, "Overlapping agreement for same platform")
    ent = new_common()
    ent.update({
        "org_id": oid,
        "platform_code": platform,
        "term_start": b["term_start"],
        "term_end": b["term_end"],
        "agreement_status": "PENDING",
    })
    db.export_agreements[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/orgs/<oid>/export-agreements", methods=["GET"])
def list_agreements(oid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    check_org_ownership(role, uid, oid)
    get_org_or_404(oid)
    items = [a for a in db.export_agreements.values() if a["org_id"] == oid]
    items.sort(key=lambda a: a["created_at"])
    pc = request.args.get("platform_code")
    st = request.args.get("agreement_status")
    if pc:
        items = [a for a in items if a["platform_code"] == pc]
    if st:
        items = [a for a in items if a["agreement_status"] == st]
    return ok_list(items)


@bp.route("/export-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    a = db.export_agreements.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    if role == "OrgOwner" and uid != a["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your agreement")
    return ok(a)


@bp.route("/export-agreements/<aid>/activate", methods=["POST"])
def activate_agreement(aid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    a = db.export_agreements.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    if a["agreement_status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only PENDING agreements may be activated")
    org = get_org_or_404(a["org_id"])
    cfg = active_tier_config(org["effective_tier_code"])
    start = parse_date(a["term_start"]); end = parse_date(a["term_end"])
    if _overlaps_existing(a["org_id"], a["platform_code"], start, end, exclude_id=a["id"]):
        raise_err(ERR_AGREEMENT_OVERLAP, "Overlapping agreement for same platform")
    if cfg is None or not cfg.get("export_module_allowed"):
        raise_err(ERR_TIER_FEATURE_NOT_ALLOWED, "Tier does not allow console export")
    a["agreement_status"] = "ACTIVE"
    touch(a)
    return ok(a)


@bp.route("/export-agreements/<aid>/revoke", methods=["POST"])
def revoke_agreement(aid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    a = db.export_agreements.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, "Agreement not found")
    if a["agreement_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only ACTIVE agreements may be revoked")
    a["agreement_status"] = "REVOKED"
    touch(a)
    return ok(a)


@bp.route("/projects/<pid>/export-builds", methods=["POST"])
def create_build(pid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    p = db.projects.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Project not found")
    if uid != p["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your project")
    if p["project_status"] in ("FROZEN", "ARCHIVED"):
        raise_err(ERR_PROJECT_FROZEN, "Project frozen or archived")
    b = body()
    agreement_id = b.get("agreement_id")
    platform = b.get("platform_code")
    label = b.get("build_label")
    if not isinstance(label, str):
        raise_err(ERR_VALIDATION, "build_label is required")
    if platform not in PLATFORMS:
        raise_err(ERR_VALIDATION, "platform_code invalid")
    a = db.export_agreements.get(agreement_id) if isinstance(agreement_id, str) else None
    if (a is None or a["org_id"] != p["org_id"] or a["platform_code"] != platform
            or a["agreement_status"] != "ACTIVE"):
        raise_err(ERR_AGREEMENT_INACTIVE, "Agreement missing, wrong org/platform, or not ACTIVE")
    ent = {
        "id": new_id(),
        "created_at": now_iso(),
        "project_id": pid,
        "agreement_id": agreement_id,
        "platform_code": platform,
        "build_label": label,
        "created_on": iso_date_str(current_date()),
    }
    db.export_builds[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/projects/<pid>/export-builds", methods=["GET"])
def list_project_builds(pid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    p = db.projects.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Project not found")
    if role == "OrgOwner" and uid != p["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your project")
    items = [x for x in db.export_builds.values() if x["project_id"] == pid]
    items.sort(key=lambda x: x["created_at"])
    pc = request.args.get("platform_code")
    if pc:
        items = [x for x in items if x["platform_code"] == pc]
    return ok_list(items)


@bp.route("/export-builds", methods=["GET"])
def list_builds():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "FinanceOps", "Auditor"})
    items = sorted(db.export_builds.values(), key=lambda x: x["created_at"])
    ag = request.args.get("agreement_id")
    pj = request.args.get("project_id")
    if ag:
        items = [x for x in items if x["agreement_id"] == ag]
    if pj:
        items = [x for x in items if x["project_id"] == pj]
    return ok_list(items)


@bp.route("/export-builds/<bid>", methods=["GET"])
def get_build(bid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    x = db.export_builds.get(bid)
    if x is None:
        raise_err(ERR_NOT_FOUND, "Export build not found")
    if role == "OrgOwner":
        p = db.projects.get(x["project_id"])
        if p is None or uid != p["org_id"]:
            raise_err(ERR_FORBIDDEN_ORG, "Not your build")
    return ok(x)
