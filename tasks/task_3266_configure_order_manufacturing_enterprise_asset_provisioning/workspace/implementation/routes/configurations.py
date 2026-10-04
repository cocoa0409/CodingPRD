from flask import Blueprint, request
from db import STORE, new_entity, touch
from errors import (ApiError, err_invalid_request, err_invalid_state,
                    ERR_COMPATIBILITY_VIOLATION, ERR_COMPONENT_EOL,
                    ERR_PROGRAM_LOCK_VIOLATION, ERR_CONFIGURATION_IN_USE)
from middleware import require_roles, require_ownership
from helpers import (get_json_body, require_field, optional_field, get_pagination,
                     paginate, store_lookup, ser_configuration)
from response import success_object, success_list
from services.core import check_compatibility, lead_time_days

bp = Blueprint("configurations", __name__)


def _validate_selections(raw):
    if not isinstance(raw, list):
        raise err_invalid_request("component_selections must be an array")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise err_invalid_request("component_selections entries must be objects")
        cid = entry.get("component_id")
        qty = entry.get("qty")
        if not isinstance(cid, str):
            raise err_invalid_request("component_selections entries require component_id string")
        if not isinstance(qty, int) or isinstance(qty, bool):
            raise err_invalid_request("component_selections entries require integer qty")
        out.append({"component_id": cid, "qty": qty})
    return out


def _referenced_by_live_order(cfg_id, blocking_statuses):
    """True when any order line references cfg and its order's build_status is in blocking set."""
    for line in STORE.order_lines.values():
        if line["configuration_id"] != cfg_id:
            continue
        order = STORE.orders.get(line["order_id"])
        if order and order["build_status"] in blocking_statuses:
            return True
    return False


@bp.post("/api/configurations")
def create_configuration():
    uid, role = require_roles("CustomerUser", "AccountManager")
    body = get_json_body()
    account_id = require_field(body, "account_id", str)
    store_lookup("accounts", account_id)
    require_ownership(account_id, uid, role)
    chassis_id = require_field(body, "chassis_model_id", str)
    store_lookup("chassis_models", chassis_id)
    if "component_selections" not in body:
        raise err_invalid_request("Missing required field: component_selections")
    selections = _validate_selections(body["component_selections"])
    for s in selections:
        store_lookup("components", s["component_id"])
    template_id = optional_field(body, "template_id", str, default=None)
    if template_id is not None:
        store_lookup("templates", template_id)
    supersedes_id = optional_field(body, "supersedes_configuration_id", str, default=None)
    old = None
    if supersedes_id is not None:
        old = store_lookup("configurations", supersedes_id)
        # supersede blocked when old config referenced by order with build_status
        # outside {DRAFT, CANCELLED}
        if _referenced_by_live_order(supersedes_id, {"SUBMITTED", "ALLOCATED", "IN_PRODUCTION", "BUILT", "ON_HOLD"}):
            raise ApiError(ERR_CONFIGURATION_IN_USE,
                           "Configuration referenced by a live Order cannot be superseded", 409)
        if old["status"] != "DRAFT":
            raise err_invalid_state("Only a DRAFT configuration can be superseded")
    ent = new_entity()
    ent.update({
        "account_id": account_id,
        "template_id": template_id,
        "chassis_model_id": chassis_id,
        "component_selections": selections,
        "compatibility_ok": False,
        "lead_time_estimate_days": None,
        "committed_lead_time_days": None,
        "status": "DRAFT",
    })
    STORE.configurations[ent["id"]] = ent
    if old is not None:
        old["status"] = "SUPERSEDED"
        touch(old)
    return success_object(ser_configuration(ent), 201)


@bp.get("/api/configurations/<cid>")
def get_configuration(cid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    ent = store_lookup("configurations", cid)
    require_ownership(ent["account_id"], uid, role)
    return success_object(ser_configuration(ent))


@bp.get("/api/configurations")
def list_configurations():
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    limit, offset = get_pagination()
    items = list(STORE.configurations.values())
    if role == "CustomerUser":
        items = [c for c in items if c["account_id"] == uid]
    for f in ("account_id", "template_id", "chassis_model_id"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c[f] == v]
    items, total = paginate(items, limit, offset)
    return success_list([ser_configuration(c) for c in items], limit, offset, total)


@bp.post("/api/configurations/<cid>/validate")
def validate_configuration(cid):
    uid, role = require_roles("CustomerUser", "AccountManager")
    ent = store_lookup("configurations", cid)
    require_ownership(ent["account_id"], uid, role)
    if ent["status"] != "DRAFT":
        raise err_invalid_state("Configuration is not DRAFT")
    account = STORE.accounts.get(ent["account_id"])
    if account is None or account["status"] != "ACTIVE":
        raise err_invalid_state("Account is not ACTIVE")
    # priority 6: compatibility before EOL (priority 7)
    if not check_compatibility(ent["chassis_model_id"], ent["component_selections"]):
        raise ApiError(ERR_COMPATIBILITY_VIOLATION,
                       "Component selections violate compatibility rules", 422)
    chassis = STORE.chassis_models.get(ent["chassis_model_id"])
    if chassis is not None and chassis["status"] == "EOL":
        raise ApiError(ERR_COMPONENT_EOL, "Chassis model is end-of-life", 422)
    for s in ent["component_selections"]:
        comp = STORE.components.get(s["component_id"])
        if comp is not None and comp["status"] == "EOL":
            raise ApiError(ERR_COMPONENT_EOL, "Selected component is end-of-life", 422)
    ent["compatibility_ok"] = True
    ent["lead_time_estimate_days"] = lead_time_days(ent, "provisional")
    ent["status"] = "VALIDATED"
    touch(ent)
    return success_object(ser_configuration(ent))


@bp.post("/api/configurations/<cid>/lock")
def lock_configuration(cid):
    require_roles("AccountManager")
    ent = store_lookup("configurations", cid)
    if ent["status"] != "VALIDATED":
        raise err_invalid_state("Configuration is not VALIDATED")
    template_id = ent.get("template_id")
    if template_id is None:
        raise ApiError(ERR_PROGRAM_LOCK_VIOLATION, "Configuration has no template", 422)
    template = STORE.templates.get(template_id)
    if template is None:
        raise ApiError(ERR_PROGRAM_LOCK_VIOLATION, "Template not found", 422)
    program = STORE.programs.get(template["program_id"])
    if program is None or program["status"] != "LOCKED":
        raise ApiError(ERR_PROGRAM_LOCK_VIOLATION, "Program is not LOCKED", 422)
    comp_rev = {}
    sel_qty = {}
    for s in ent["component_selections"]:
        comp = STORE.components.get(s["component_id"])
        sel_qty[s["component_id"]] = sel_qty.get(s["component_id"], 0) + s["qty"]
        comp_rev[s["component_id"]] = comp["revision"] if comp else None
    for pin in template["pinned_components"]:
        cid = pin["component_id"]
        if cid not in sel_qty:
            raise ApiError(ERR_PROGRAM_LOCK_VIOLATION,
                           "Pinned component missing from selections", 422)
        if comp_rev.get(cid) != pin["revision"]:
            raise ApiError(ERR_PROGRAM_LOCK_VIOLATION,
                           "Pinned component revision mismatch", 422)
    ent["status"] = "LOCKED"
    touch(ent)
    return success_object(ser_configuration(ent))


@bp.post("/api/configurations/<cid>/unlock")
def unlock_configuration(cid):
    require_roles("AccountManager")
    ent = store_lookup("configurations", cid)
    if ent["status"] != "LOCKED":
        raise err_invalid_state("Configuration is not LOCKED")
    if _referenced_by_live_order(cid, {"SUBMITTED", "ALLOCATED", "IN_PRODUCTION"}):
        raise ApiError(ERR_CONFIGURATION_IN_USE,
                       "Configuration referenced by a live Order cannot be unlocked", 409)
    ent["status"] = "DRAFT"
    ent["compatibility_ok"] = False
    touch(ent)
    return success_object(ser_configuration(ent))
