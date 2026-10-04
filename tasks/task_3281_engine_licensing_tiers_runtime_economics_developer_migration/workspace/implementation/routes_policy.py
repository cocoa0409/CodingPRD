"""Policy change and grandfather commitment routes."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_DUPLICATE_PERIOD, ERR_POLICY_WINDOW_TOO_SHORT,
)
from helpers import (
    ok, ok_list, body, new_common, touch, parse_date, iso_date_str, add_days,
)
from middleware import authenticate, authorize, ERR_FORBIDDEN_ORG
from services_calc import compute_standing

bp = Blueprint("policy", __name__)

READ_ROLES = {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"}


@bp.route("/policy-changes", methods=["POST"])
def create_policy():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    b = body()
    code = b.get("change_code")
    if not isinstance(code, str):
        raise_err(ERR_VALIDATION, "change_code is required")
    ann = parse_date(b.get("announcement_date"))
    eff = parse_date(b.get("effective_date"))
    if ann is None or eff is None:
        raise_err(ERR_VALIDATION, "announcement_date and effective_date must be ISO dates")
    retro = b.get("retroactive_flag")
    adverse = b.get("adverse_flag")
    if not isinstance(retro, bool) or not isinstance(adverse, bool):
        raise_err(ERR_VALIDATION, "retroactive_flag and adverse_flag must be booleans")
    window = b.get("grandfather_window_days")
    rate = b.get("new_per_install_cents")
    if not isinstance(window, int) or isinstance(window, bool) or window < 0:
        raise_err(ERR_VALIDATION, "grandfather_window_days must be a non-negative integer")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
        raise_err(ERR_VALIDATION, "new_per_install_cents must be a non-negative integer")
    for p in db.policy_changes.values():
        if p["change_code"] == code:
            raise_err(ERR_DUPLICATE_PERIOD, "change_code already exists")
    ent = new_common()
    ent.update({
        "change_code": code,
        "announcement_date": b["announcement_date"],
        "effective_date": b["effective_date"],
        "retroactive_flag": retro,
        "adverse_flag": adverse,
        "grandfather_window_days": window,
        "new_per_install_cents": rate,
        "change_status": "DRAFT",
    })
    db.policy_changes[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/policy-changes/<pid>", methods=["GET"])
def get_policy(pid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    p = db.policy_changes.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Policy change not found")
    return ok(p)


@bp.route("/policy-changes/<pid>/activate", methods=["POST"])
def activate_policy(pid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    p = db.policy_changes.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Policy change not found")
    if p["change_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only DRAFT changes may be activated")
    if not p.get("announcement_date") or not p.get("effective_date"):
        raise_err(ERR_VALIDATION, "Dates must be set")
    if p["retroactive_flag"] and p["grandfather_window_days"] < 30:
        raise_err(ERR_POLICY_WINDOW_TOO_SHORT, "grandfather_window_days must be >= 30 for retroactive changes")
    p["change_status"] = "ACTIVE"
    touch(p)
    # Cascade hop 1 + 2: commitments for shipped projects with shipped_on <= announcement_date
    ann = parse_date(p["announcement_date"])
    affected_orgs = set()
    for proj in db.projects.values():
        if proj["project_status"] != "SHIPPED":
            continue
        shipped = parse_date(proj.get("shipped_on"))
        if shipped is None or ann is None or shipped > ann:
            continue
        ent = new_common()
        ent.update({
            "policy_change_id": p["id"],
            "org_id": proj["org_id"],
            "project_id": proj["id"],
            "locked_schedule_label": "BASE",
            "commitment_status": "ACTIVE",
            "attestation_deadline": iso_date_str(add_days(ann, p["grandfather_window_days"])),
            "attested": False,
        })
        db.grandfather_commitments[ent["id"]] = ent
        proj["pinned_policy_change_id"] = p["id"]
        touch(proj)
        # PROVISIONAL invoices on those projects keep BASE label
        for inv in db.invoices.values():
            if inv["project_id"] == proj["id"] and inv["assessment_status"] == "PROVISIONAL":
                inv["fee_schedule_label"] = "BASE"
                touch(inv)
        affected_orgs.add(proj["org_id"])
    # Hop 3: retroactive AND adverse -> trust -= 10, standing recompute
    if p["retroactive_flag"] and p["adverse_flag"]:
        for oid in affected_orgs:
            org = db.orgs.get(oid)
            if org is None:
                continue
            org["trust_score"] = max(0, org["trust_score"] - 10)
            touch(org)
            compute_standing(org)
    return ok(p)


@bp.route("/policy-changes/<pid>/rescind", methods=["POST"])
def rescind_policy(pid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    p = db.policy_changes.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Policy change not found")
    if p["change_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only DRAFT changes may be rescinded")
    p["change_status"] = "RESCINDED"
    touch(p)
    return ok(p)


@bp.route("/grandfather-commitments", methods=["GET"])
def list_commitments():
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    items = sorted(db.grandfather_commitments.values(), key=lambda c: c["created_at"])
    pc = request.args.get("policy_change_id")
    og = request.args.get("org_id")
    pj = request.args.get("project_id")
    if pc:
        items = [c for c in items if c["policy_change_id"] == pc]
    if og:
        items = [c for c in items if c["org_id"] == og]
    if pj:
        items = [c for c in items if c["project_id"] == pj]
    if role == "OrgOwner":
        items = [c for c in items if c["org_id"] == uid]
    return ok_list(items)


@bp.route("/grandfather-commitments/<cid>", methods=["GET"])
def get_commitment(cid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    c = db.grandfather_commitments.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, "Commitment not found")
    if role == "OrgOwner" and uid != c["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your commitment")
    return ok(c)


@bp.route("/grandfather-commitments/<cid>/attest", methods=["POST"])
def attest_commitment(cid):
    from helpers import current_date
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    c = db.grandfather_commitments.get(cid)
    if c is None:
        raise_err(ERR_NOT_FOUND, "Commitment not found")
    if uid != c["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your commitment")
    if c["commitment_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Commitment not active")
    deadline = parse_date(c["attestation_deadline"])
    if deadline is not None and current_date() > deadline:
        c["commitment_status"] = "VOIDED"
        touch(c)
        proj = db.projects.get(c["project_id"])
        if proj and proj.get("pinned_policy_change_id") == c["policy_change_id"]:
            proj["pinned_policy_change_id"] = None
            touch(proj)
        raise_err(ERR_INVALID_STATE, "Attestation deadline has passed")
    c["attested"] = True
    touch(c)
    return ok(c)
