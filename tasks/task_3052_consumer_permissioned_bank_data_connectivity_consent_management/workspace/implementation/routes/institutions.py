"""Institution routes: create/list/get/recover/migration, agreements, breakage."""

from flask import Blueprint, request

import db
from middleware import require_role, parse_limit_offset
from response import success_object, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_MIGRATION_WINDOW_CLOSED, ERR_MIGRATION_INCOMPLETE,
    ERR_DUPLICATE_ACTIVE,
)
from services import core
from services.serializers import institution_out, agreement_out, breakage_out

bp = Blueprint("institutions", __name__)

ALL_READ_ROLES = ("PlatformAdmin", "ComplianceReviewer", "Consumer", "Recipient")


def _get_institution(institution_id):
    inst = db.institutions.get(institution_id)
    if inst is None:
        raise err(ERR_NOT_FOUND, "Institution not found")
    return inst


@bp.route("/institutions", methods=["POST"])
def create_institution():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}

    name = body.get("name")
    supported_methods = body.get("supported_methods")
    target_method = body.get("target_method")
    mw_start = body.get("migration_window_start")
    mw_end = body.get("migration_window_end")

    # uniqueness of name (priority 17 before field validity per PRD §2.9 ordering
    # — but ERR_INVALID_REQUEST for malformed fields is last, priority 20;
    # PRD §3.1 says malformed submissions rejected with ERR_INVALID_REQUEST)
    # Required-field presence first (field-level), then semantic checks.
    if not isinstance(name, str) or not name.strip():
        raise err(ERR_INVALID_REQUEST, "name must be a non-empty string")
    if not isinstance(supported_methods, list) or not supported_methods:
        raise err(ERR_INVALID_REQUEST, "supported_methods must be a non-empty array")
    for m in supported_methods:
        if m not in core.METHODS:
            raise err(ERR_INVALID_REQUEST, f"supported_methods contains invalid method {m}")
    if target_method not in core.TARGET_METHODS:
        raise err(ERR_INVALID_REQUEST, "target_method must be BANK_API or OAUTH_TOKEN")
    if target_method not in supported_methods:
        raise err(ERR_INVALID_REQUEST, "target_method must be a member of supported_methods")
    start_dt = core.parse_dt(mw_start, "migration_window_start") if mw_start is not None else None
    end_dt = core.parse_dt(mw_end, "migration_window_end") if mw_end is not None else None
    if start_dt is None or end_dt is None:
        raise err(ERR_INVALID_REQUEST, "migration_window_start and migration_window_end are required")
    if not (end_dt > start_dt):
        raise err(ERR_INVALID_REQUEST, "migration_window_end must be strictly after migration_window_start")

    # name uniqueness (ERR_DUPLICATE_ACTIVE)
    for other in db.institutions.values():
        if other["name"] == name:
            raise err(ERR_DUPLICATE_ACTIVE, "institution name must be unique")

    inst = {
        "name": name,
        "supported_methods": list(supported_methods),
        "target_method": target_method,
        "migration_window_start": core.iso(start_dt),
        "migration_window_end": core.iso(end_dt),
        "migration_state": "NOT_STARTED",
        "status": "ACTIVE",
        "_mw_start_dt": start_dt,
        "_mw_end_dt": end_dt,
        "_last_recovered_dt": None,
    }
    core.stamp_new(inst)
    db.institutions[inst["id"]] = inst
    return success_object(institution_out(inst), 201)


@bp.route("/institutions", methods=["GET"])
def list_institutions():
    require_role(*ALL_READ_ROLES)
    limit, offset = parse_limit_offset(request.args)
    status_filter = request.args.get("status")
    items = []
    for inst in db.institutions.values():
        core.recompute_institution_health(inst)
        if status_filter and inst["status"] != status_filter:
            continue
        items.append(inst)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([institution_out(i) for i in page], limit, offset, total)


@bp.route("/institutions/<institutionId>", methods=["GET"])
def get_institution(institutionId):
    require_role(*ALL_READ_ROLES)
    inst = _get_institution(institutionId)
    core.recompute_institution_health(inst)
    return success_object(institution_out(inst))


@bp.route("/institutions/<institutionId>/recover", methods=["POST"])
def recover_institution(institutionId):
    require_role("PlatformAdmin")
    inst = _get_institution(institutionId)
    core.recompute_institution_health(inst)
    if inst["status"] != "BROKEN":
        raise err(ERR_INVALID_STATE, "Institution is not BROKEN")
    inst["status"] = "ACTIVE"
    inst["_last_recovered_dt"] = db.get_clock()
    core.touch(inst)
    return success_object(institution_out(inst))


@bp.route("/institutions/<institutionId>/migration/start", methods=["POST"])
def migration_start(institutionId):
    require_role("PlatformAdmin")
    inst = _get_institution(institutionId)
    clock = db.get_clock()
    # state check (priority 5) — migration_state must be NOT_STARTED
    if inst["migration_state"] != "NOT_STARTED":
        raise err(ERR_INVALID_STATE, "Migration already started or complete")
    # window check (priority 12)
    if not (inst["_mw_start_dt"] <= clock <= inst["_mw_end_dt"]):
        raise err(ERR_MIGRATION_WINDOW_CLOSED, "Clock is outside the migration window")
    if inst["target_method"] not in inst["supported_methods"]:
        raise err(ERR_INVALID_REQUEST, "target_method must be a member of supported_methods")
    inst["migration_state"] = "IN_PROGRESS"
    core.touch(inst)
    return success_object(institution_out(inst))


@bp.route("/institutions/<institutionId>/migration/complete", methods=["POST"])
def migration_complete(institutionId):
    require_role("PlatformAdmin")
    inst = _get_institution(institutionId)
    if inst["migration_state"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE, "Migration is not IN_PROGRESS")
    # completion gate (priority 18)
    for conn in db.connections.values():
        if conn["institution_id"] == inst["id"] and conn["status"] != "DISCONNECTED":
            if conn["method"] != inst["target_method"]:
                raise err(ERR_MIGRATION_INCOMPLETE,
                          "Non-DISCONNECTED connections still on non-target method")
    inst["migration_state"] = "COMPLETE"
    core.touch(inst)
    return success_object(institution_out(inst))


# ------------------------------------------------------------- agreements

@bp.route("/institutions/<institutionId>/agreements", methods=["POST"])
def create_agreement(institutionId):
    require_role("PlatformAdmin")
    inst = _get_institution(institutionId)
    body = request.get_json(silent=True) or {}

    # OCC check (priority 6)
    expected = body.get("expected_institution_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise err(ERR_INVALID_REQUEST, "expected_institution_version must be an integer")
        if expected != inst["version"]:
            raise err(ERR_STALE_VERSION, "expected_institution_version does not match")

    rate_limit = body.get("rate_limit_per_hour")
    pfbs = body.get("permitted_fields_by_scope")
    if not isinstance(rate_limit, int) or isinstance(rate_limit, bool) or rate_limit < 1:
        raise err(ERR_INVALID_REQUEST, "rate_limit_per_hour must be an integer >= 1")
    if not isinstance(pfbs, dict) or not pfbs:
        raise err(ERR_INVALID_REQUEST, "permitted_fields_by_scope must be a non-empty object")
    for scope, fields in pfbs.items():
        if scope not in core.DATA_SCOPES:
            raise err(ERR_INVALID_REQUEST, f"permitted_fields_by_scope key {scope} is not a declared DataScope")
        if not isinstance(fields, list) or not fields:
            raise err(ERR_INVALID_REQUEST, f"permitted_fields_by_scope[{scope}] must be a non-empty array")

    # supersede prior ACTIVE agreement
    for ag in db.agreements.values():
        if ag["institution_id"] == inst["id"] and ag.get("active"):
            ag["active"] = False
            core.touch(ag)

    ag = {
        "institution_id": inst["id"],
        "rate_limit_per_hour": rate_limit,
        "permitted_fields_by_scope": pfbs,
        "active": True,
    }
    core.stamp_new(ag)
    db.agreements[ag["id"]] = ag
    core.touch(inst)  # institution version increments
    return success_object(agreement_out(ag), 201)


@bp.route("/institutions/<institutionId>/agreements", methods=["GET"])
def list_agreements(institutionId):
    require_role("PlatformAdmin", "ComplianceReviewer")
    inst = _get_institution(institutionId)
    limit, offset = parse_limit_offset(request.args)
    active_filter = request.args.get("active")
    items = [a for a in db.agreements.values() if a["institution_id"] == inst["id"]]
    if active_filter is not None:
        want = active_filter.lower() == "true"
        items = [a for a in items if bool(a.get("active")) == want]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([agreement_out(a) for a in page], limit, offset, total)


@bp.route("/institutions/<institutionId>/breakage_events", methods=["GET"])
def list_institution_breakage(institutionId):
    require_role("PlatformAdmin", "ComplianceReviewer")
    inst = _get_institution(institutionId)
    limit, offset = parse_limit_offset(request.args)
    items = [b for b in db.breakage_events.values() if b["institution_id"] == inst["id"]]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([breakage_out(b) for b in page], limit, offset, total)
