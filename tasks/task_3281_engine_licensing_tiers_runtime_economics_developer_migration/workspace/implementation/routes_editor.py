"""Editor version routes with lifecycle transitions."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_INVALID_INTERVAL, ERR_LTS_WINDOW_OVERLAP, ERR_DUPLICATE_PERIOD,
)
from helpers import (
    ok, ok_list, body, new_common, parse_date, touch, current_date,
    months_between,
)
from middleware import authenticate, authorize
from services_calc import compute_risk_score

bp = Blueprint("editor_versions", __name__)

READ_ROLES = {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor", "ReviewBoard"}


@bp.route("/editor-versions", methods=["POST"])
def create_version():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    b = body()
    vs = b.get("version_string")
    ml = b.get("major_line")
    rel = b.get("released_on")
    if not isinstance(vs, str) or not isinstance(ml, str):
        raise_err(ERR_VALIDATION, "version_string and major_line are required strings")
    if parse_date(rel) is None:
        raise_err(ERR_VALIDATION, "released_on must be an ISO date")
    dac = b.get("deprecated_api_count", 0)
    if not isinstance(dac, int) or isinstance(dac, bool) or dac < 0:
        raise_err(ERR_VALIDATION, "deprecated_api_count must be a non-negative integer")
    for v in db.editor_versions.values():
        if v["version_string"] == vs:
            raise_err(ERR_DUPLICATE_PERIOD, "version_string already exists")
    ent = new_common()
    ent.update({
        "version_string": vs,
        "major_line": ml,
        "released_on": rel,
        "support_status": "SUPPORTED",
        "lts_window_start": None,
        "lts_window_end": None,
        "deprecated_api_count": dac,
    })
    db.editor_versions[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/editor-versions", methods=["GET"])
def list_versions():
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    items = sorted(db.editor_versions.values(), key=lambda v: v["created_at"])
    ml = request.args.get("major_line")
    ss = request.args.get("support_status")
    if ml:
        items = [v for v in items if v["major_line"] == ml]
    if ss:
        items = [v for v in items if v["support_status"] == ss]
    return ok_list(items)


@bp.route("/editor-versions/<vid>", methods=["GET"])
def get_version(vid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    v = db.editor_versions.get(vid)
    if v is None:
        raise_err(ERR_NOT_FOUND, "Editor version not found")
    return ok(v)


def _recompute_pinned_projects(version):
    for p in db.projects.values():
        if p["editor_version_id"] == version["id"] and p["project_status"] == "SHIPPED":
            p["upgrade_risk_score"] = compute_risk_score(p)
            touch(p)


@bp.route("/editor-versions/<vid>/transition", methods=["POST"])
def transition_version(vid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    v = db.editor_versions.get(vid)
    if v is None:
        raise_err(ERR_NOT_FOUND, "Editor version not found")
    b = body()
    target = b.get("target_status")
    if target not in ("LTS", "DEPRECATED", "SUNSET"):
        raise_err(ERR_VALIDATION, "target_status must be LTS, DEPRECATED or SUNSET")
    current = v["support_status"]
    today = current_date()

    allowed = {
        ("SUPPORTED", "LTS"),
        ("LTS", "DEPRECATED"),
        ("DEPRECATED", "SUNSET"),
        ("SUPPORTED", "DEPRECATED"),
    }
    if (current, target) not in allowed:
        raise_err(ERR_INVALID_STATE, "Transition %s -> %s not allowed" % (current, target))

    if target == "LTS":
        ws = parse_date(b.get("lts_window_start"))
        we = parse_date(b.get("lts_window_end"))
        if ws is None or we is None or ws > we:
            raise_err(ERR_INVALID_INTERVAL, "Invalid LTS window")
        # Closed-interval overlap vs same major_line other versions
        for other in db.editor_versions.values():
            if other["id"] == v["id"] or other["major_line"] != v["major_line"]:
                continue
            ows = parse_date(other.get("lts_window_start"))
            owe = parse_date(other.get("lts_window_end"))
            if ows and owe and other["support_status"] in ("LTS", "DEPRECATED"):
                if ws <= owe and ows <= we:
                    raise_err(ERR_LTS_WINDOW_OVERLAP, "LTS window overlaps another version on the same line")
        v["lts_window_start"] = b["lts_window_start"]
        v["lts_window_end"] = b["lts_window_end"]
        v["support_status"] = "LTS"
        touch(v)
        _recompute_pinned_projects(v)
        return ok(v)

    if target == "DEPRECATED":
        if current == "LTS":
            we = parse_date(v.get("lts_window_end"))
            if we is None or not (today > we):
                raise_err(ERR_INVALID_STATE, "LTS window has not ended")
        else:  # SUPPORTED -> DEPRECATED
            rel = parse_date(v["released_on"])
            if months_between(rel, today) < 24:
                raise_err(ERR_INVALID_STATE, "released_on must be at least 24 months in the past")
        v["support_status"] = "DEPRECATED"
        touch(v)
        _recompute_pinned_projects(v)
        return ok(v)

    # SUNSET from DEPRECATED
    we = parse_date(v.get("lts_window_end"))
    if we is None or months_between(we, today) < 12:
        raise_err(ERR_INVALID_STATE, "lts_window_end must be at least 12 months in the past")
    v["support_status"] = "SUNSET"
    touch(v)
    # Cascade: SHIPPED projects pinned to this version freeze
    for p in db.projects.values():
        if p["editor_version_id"] == v["id"] and p["project_status"] == "SHIPPED":
            p["project_status"] = "FROZEN"
            p["upgrade_risk_score"] = compute_risk_score(p)
            touch(p)
    return ok(v)
