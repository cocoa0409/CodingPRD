from flask import Blueprint, request
from db import STORE, new_entity, touch
from errors import (ApiError, err_invalid_request, err_not_found, err_invalid_state,
                    ERR_STALE_COMPONENT_VERSION, ERR_INVALID_STATE)
from middleware import require_roles, require_ownership
from helpers import (get_json_body, require_field, optional_field, get_pagination,
                     paginate, store_lookup, ser_account, ser_program, ser_chassis,
                     ser_component, ser_rule, ser_template)
from response import success_object, success_list

bp = Blueprint("catalog", __name__)

ACCOUNT_TIERS = {"STANDARD", "PREMIER", "FEDERAL"}
CHASSIS_CATEGORIES = {"LAPTOP", "DESKTOP", "SERVER", "WORKSTATION"}
COMPONENT_KINDS = {"CPU", "MEMORY", "STORAGE", "GPU", "NIC", "PSU", "WIFI", "DISPLAY", "OS_IMAGE"}
RULE_TYPES = {"ALLOWED", "REQUIRES", "EXCLUDES", "MIN_QTY"}


# ---------------- accounts ----------------

@bp.post("/api/accounts")
def create_account():
    require_roles("PlatformAdmin")
    body = get_json_body()
    company = require_field(body, "company_name", str)
    tier = require_field(body, "account_tier", str, enum=ACCOUNT_TIERS)
    credit = require_field(body, "credit_limit_cents", int)
    ent = new_entity()
    ent.update({
        "company_name": company,
        "account_tier": tier,
        "credit_limit_cents": credit,
        "outstanding_cents": 0,
        "recovery_credit_cents": 0,
        "status": "ACTIVE",
    })
    STORE.accounts[ent["id"]] = ent
    return success_object(ser_account(ent), 201)


@bp.get("/api/accounts/<aid>")
def get_account(aid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    ent = store_lookup("accounts", aid)
    require_ownership(aid, uid, role)
    return success_object(ser_account(ent))


@bp.get("/api/accounts")
def list_accounts():
    require_roles("PlatformAdmin", "AccountManager")
    limit, offset = get_pagination()
    items, total = paginate(list(STORE.accounts.values()), limit, offset)
    return success_list([ser_account(a) for a in items], limit, offset, total)


# ---------------- programs ----------------

@bp.post("/api/accounts/<aid>/programs")
def create_program(aid):
    require_roles("AccountManager")
    store_lookup("accounts", aid)
    body = get_json_body()
    name = require_field(body, "name", str)
    prefix = require_field(body, "asset_tag_prefix", str)
    image = require_field(body, "custom_image_ref", str)
    ent = new_entity()
    ent.update({
        "account_id": aid,
        "name": name,
        "locked": False,
        "asset_tag_prefix": prefix,
        "custom_image_ref": image,
        "status": "OPEN",
    })
    STORE.programs[ent["id"]] = ent
    return success_object(ser_program(ent), 201)


@bp.get("/api/programs/<pid>")
def get_program(pid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    ent = store_lookup("programs", pid)
    require_ownership(ent["account_id"], uid, role)
    return success_object(ser_program(ent))


@bp.get("/api/programs")
def list_programs():
    require_roles("PlatformAdmin", "AccountManager")
    limit, offset = get_pagination()
    items = list(STORE.programs.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    items, total = paginate(items, limit, offset)
    return success_list([ser_program(p) for p in items], limit, offset, total)


@bp.post("/api/programs/<pid>/lock")
def lock_program(pid):
    require_roles("AccountManager")
    ent = store_lookup("programs", pid)
    if ent["status"] != "OPEN":
        raise err_invalid_state("Program is not OPEN")
    ent["locked"] = True
    ent["status"] = "LOCKED"
    touch(ent)
    for t in STORE.templates.values():
        if t["program_id"] == pid:
            t["status"] = "LOCKED"
            touch(t)
    return success_object(ser_program(ent))


@bp.get("/api/accounts/<aid>/programs")
def list_account_programs(aid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    store_lookup("accounts", aid)
    require_ownership(aid, uid, role)
    limit, offset = get_pagination()
    items = [p for p in STORE.programs.values() if p["account_id"] == aid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_program(p) for p in items], limit, offset, total)


# ---------------- templates ----------------

def _validate_pinned_components(raw):
    if not isinstance(raw, list):
        raise err_invalid_request("pinned_components must be an array")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise err_invalid_request("pinned_components entries must be objects")
        cid = entry.get("component_id")
        rev = entry.get("revision")
        qty = entry.get("qty")
        if not isinstance(cid, str) or not isinstance(rev, str):
            raise err_invalid_request("pinned_components entries require component_id and revision strings")
        if not isinstance(qty, int) or isinstance(qty, bool):
            raise err_invalid_request("pinned_components entries require integer qty")
        out.append({"component_id": cid, "revision": rev, "qty": qty})
    return out


@bp.post("/api/programs/<pid>/templates")
def create_template(pid):
    require_roles("AccountManager")
    store_lookup("programs", pid)
    body = get_json_body()
    name = require_field(body, "name", str)
    chassis_id = require_field(body, "chassis_model_id", str)
    store_lookup("chassis_models", chassis_id)
    if "pinned_components" not in body:
        raise err_invalid_request("Missing required field: pinned_components")
    pinned = _validate_pinned_components(body["pinned_components"])
    image = optional_field(body, "pinned_image_ref", str, default=None)
    ent = new_entity()
    ent.update({
        "program_id": pid,
        "name": name,
        "chassis_model_id": chassis_id,
        "pinned_components": pinned,
        "pinned_image_ref": image,
        "status": "DRAFT",
    })
    STORE.templates[ent["id"]] = ent
    return success_object(ser_template(ent), 201)


@bp.post("/api/templates/<tid>/publish")
def publish_template(tid):
    require_roles("AccountManager")
    ent = store_lookup("templates", tid)
    if ent["status"] != "DRAFT":
        raise err_invalid_state("Template is not DRAFT")
    ent["status"] = "PUBLISHED"
    touch(ent)
    return success_object(ser_template(ent))


@bp.get("/api/programs/<pid>/templates")
def list_program_templates(pid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    prog = store_lookup("programs", pid)
    require_ownership(prog["account_id"], uid, role)
    limit, offset = get_pagination()
    items = [t for t in STORE.templates.values() if t["program_id"] == pid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_template(t) for t in items], limit, offset, total)


@bp.get("/api/templates/<tid>")
def get_template(tid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    ent = store_lookup("templates", tid)
    prog = STORE.programs.get(ent["program_id"])
    if prog:
        require_ownership(prog["account_id"], uid, role)
    return success_object(ser_template(ent))


@bp.get("/api/templates")
def list_templates():
    require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    limit, offset = get_pagination()
    items = list(STORE.templates.values())
    program_id = request.args.get("program_id")
    chassis_model_id = request.args.get("chassis_model_id")
    if program_id is not None:
        items = [t for t in items if t["program_id"] == program_id]
    if chassis_model_id is not None:
        items = [t for t in items if t["chassis_model_id"] == chassis_model_id]
    items, total = paginate(items, limit, offset)
    return success_list([ser_template(t) for t in items], limit, offset, total)


# ---------------- chassis models ----------------

@bp.post("/api/chassis-models")
def create_chassis():
    require_roles("PlatformAdmin")
    body = get_json_body()
    code = require_field(body, "model_code", str)
    category = require_field(body, "category", str, enum=CHASSIS_CATEGORIES)
    price = require_field(body, "base_price_cents", int)
    hours = require_field(body, "build_duration_hours", int)
    ent = new_entity()
    ent.update({
        "model_code": code,
        "category": category,
        "base_price_cents": price,
        "build_duration_hours": hours,
        "status": "CATALOG",
    })
    STORE.chassis_models[ent["id"]] = ent
    return success_object(ser_chassis(ent), 201)


@bp.post("/api/chassis-models/<cid>/discontinue")
def discontinue_chassis(cid):
    require_roles("PlatformAdmin")
    ent = store_lookup("chassis_models", cid)
    if ent["status"] != "CATALOG":
        raise err_invalid_state("Chassis model is not CATALOG")
    ent["status"] = "EOL"
    touch(ent)
    return success_object(ser_chassis(ent))


@bp.get("/api/chassis-models/<cid>")
def get_chassis(cid):
    require_roles("PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps")
    ent = store_lookup("chassis_models", cid)
    return success_object(ser_chassis(ent))


# ---------------- components ----------------

@bp.post("/api/components")
def create_component():
    require_roles("PlatformAdmin")
    body = get_json_body()
    sku = require_field(body, "sku", str)
    kind = require_field(body, "kind", str, enum=COMPONENT_KINDS)
    price = require_field(body, "price_cents", int)
    lead = require_field(body, "lead_time_days", int)
    stock = optional_field(body, "stock_on_hand", int, default=0)
    revision = require_field(body, "revision", str)
    ent = new_entity()
    ent.update({
        "sku": sku,
        "kind": kind,
        "price_cents": price,
        "lead_time_days": lead,
        "stock_on_hand": stock,
        "reserved_units": 0,
        "revision": revision,
        "status": "ACTIVE",
    })
    STORE.components[ent["id"]] = ent
    return success_object(ser_component(ent), 201)


@bp.get("/api/components/<cid>")
def get_component(cid):
    require_roles("PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps")
    ent = store_lookup("components", cid)
    return success_object(ser_component(ent))


@bp.post("/api/components/<cid>/restock")
def restock_component(cid):
    require_roles("PlatformAdmin", "FactoryOps")
    ent = store_lookup("components", cid)
    body = get_json_body()
    add = require_field(body, "add_units", int)
    expected = require_field(body, "expected_component_version", int)
    if expected != ent["version"]:
        raise ApiError(ERR_STALE_COMPONENT_VERSION,
                       "expected_component_version does not match component's current version", 412)
    ent["stock_on_hand"] += add
    touch(ent)
    return success_object(ser_component(ent))


@bp.get("/api/components")
def list_components():
    require_roles("PlatformAdmin", "AccountManager", "CustomerUser", "FactoryOps")
    limit, offset = get_pagination()
    items = list(STORE.components.values())
    status = request.args.get("status")
    kind = request.args.get("kind")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if kind is not None:
        items = [c for c in items if c["kind"] == kind]
    items, total = paginate(items, limit, offset)
    return success_list([ser_component(c) for c in items], limit, offset, total)


@bp.post("/api/components/<cid>/discontinue")
def discontinue_component(cid):
    require_roles("PlatformAdmin")
    ent = store_lookup("components", cid)
    if ent["status"] != "ACTIVE":
        raise err_invalid_state("Component is not ACTIVE")
    ent["status"] = "EOL"
    touch(ent)
    return success_object(ser_component(ent))


# ---------------- compatibility rules ----------------

@bp.post("/api/compatibility-rules")
def create_rule():
    require_roles("PlatformAdmin")
    body = get_json_body()
    chassis_id = require_field(body, "chassis_model_id", str)
    store_lookup("chassis_models", chassis_id)
    component_id = require_field(body, "component_id", str)
    store_lookup("components", component_id)
    rule_type = require_field(body, "rule_type", str, enum=RULE_TYPES)
    other = body.get("other_component_id")
    min_qty = body.get("min_qty")
    if rule_type in ("REQUIRES", "EXCLUDES"):
        if not isinstance(other, str):
            raise err_invalid_request("other_component_id required for REQUIRES/EXCLUDES")
        store_lookup("components", other)
        min_qty = None
    elif rule_type == "MIN_QTY":
        if not isinstance(min_qty, int) or isinstance(min_qty, bool):
            raise err_invalid_request("min_qty required for MIN_QTY")
        other = None
    else:  # ALLOWED
        other = None
        min_qty = None
    ts = new_entity()
    ent = {
        "id": ts["id"],
        "created_at": ts["created_at"],
        "chassis_model_id": chassis_id,
        "component_id": component_id,
        "rule_type": rule_type,
        "other_component_id": other,
        "min_qty": min_qty,
    }
    STORE.compat_rules[ent["id"]] = ent
    return success_object(ser_rule(ent), 201)


@bp.get("/api/chassis-models/<cid>/compatibility-rules")
def list_chassis_rules(cid):
    require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    store_lookup("chassis_models", cid)
    limit, offset = get_pagination()
    items = [r for r in STORE.compat_rules.values() if r["chassis_model_id"] == cid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_rule(r) for r in items], limit, offset, total)


@bp.get("/api/compatibility-rules")
def list_rules():
    require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    limit, offset = get_pagination()
    items = list(STORE.compat_rules.values())
    for f in ("chassis_model_id", "component_id", "other_component_id"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r[f] == v]
    items, total = paginate(items, limit, offset)
    return success_list([ser_rule(r) for r in items], limit, offset, total)


@bp.get("/api/components/<cid>/compatibility-rules")
def list_component_rules(cid):
    require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    store_lookup("components", cid)
    limit, offset = get_pagination()
    items = [r for r in STORE.compat_rules.values() if r["component_id"] == cid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_rule(r) for r in items], limit, offset, total)
