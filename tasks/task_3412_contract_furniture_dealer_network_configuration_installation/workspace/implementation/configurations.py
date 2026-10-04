# Configuration specs routes (PRD 3.4; scaffold Tables 2/5).
from flask import Blueprint, request

import authz
import calc
import clock
import constants
import envelope
import errors
import serialize
import state
import validate
from dealers import _new_entity

bp = Blueprint("configurations", __name__)


def _load_spec(spec_id):
    spec = state.configurations.get(spec_id)
    if spec is None:
        errors.not_found("ERR_CONFIGURATION_NOT_FOUND", "No configuration with the given id")
    return spec


def _validate_modules_shape(modules):
    """Create-time shape (PRD 2.9 step 5): non-empty list of entries carrying
    module_type and integer qty >= 1. Module-type knowledge and fabric rules are
    lock-time checks (PRD 3.4), not create-time."""
    if not isinstance(modules, list) or len(modules) < 1:
        errors.validation("modules must be a non-empty array")
    normalized = []
    for entry in modules:
        if not isinstance(entry, dict):
            errors.validation("each module entry must be an object")
        module_type = entry.get("module_type")
        if not validate.is_str(module_type) or module_type == "":
            errors.validation("module_type must be a non-empty string")
        qty = entry.get("qty")
        if not validate.is_int(qty) or qty < 1:
            errors.validation("module qty must be an integer >= 1")
        fabric_grade = entry.get("fabric_grade")
        if fabric_grade is not None and not validate.is_str(fabric_grade):
            errors.validation("fabric_grade must be a string or null")
        normalized.append({
            "module_type": module_type,
            "fabric_grade": fabric_grade,
            "qty": qty,
        })
    return normalized


def _validate_modules_at_lock(spec):
    """Lock-time module rules (PRD 3.4): known module types, category family row
    resolvable, fabric present for SYSTEMS/SEATING and null for STORAGE."""
    for entry in spec["modules"]:
        module_type = entry["module_type"]
        if module_type not in constants.MODULE_BOM_RULES:
            errors.err("ERR_INVALID_MODULE", 422, f"Unknown module_type {module_type}")
        category = constants.MODULE_FAMILY_CATEGORY[module_type]
        if calc.family_for_category(category) is None:
            errors.err("ERR_INVALID_MODULE", 422,
                       f"No product family row for category {category}")
        fabric = entry.get("fabric_grade")
        if category == "STORAGE":
            if fabric is not None:
                errors.err("ERR_INVALID_MODULE", 422,
                           "fabric_grade must be null for STORAGE modules")
        else:
            if fabric is None or fabric not in constants.FABRIC_GRADES:
                errors.err("ERR_INVALID_MODULE", 422,
                           "fabric_grade is required (A, B, C, or COM) for "
                           "SYSTEMS/SEATING modules")


def _check_family_lifecycle_at_lock(spec):
    today = clock.today()
    seen = set()
    for entry in spec["modules"]:
        category = constants.MODULE_FAMILY_CATEGORY[entry["module_type"]]
        if category in seen:
            continue
        seen.add(category)
        fam = calc.family_for_category(category)
        if fam["lifecycle_status"] == "DISCONTINUED":
            errors.err("ERR_PRODUCT_LINE_DISCONTINUED", 422,
                       f"Product family {fam['family_code']} is DISCONTINUED")
        if fam["lifecycle_status"] == "SUNSETTING":
            if today > calc._parse_date(fam["last_order_date"]):
                errors.err("ERR_LAST_ORDER_DATE_PASSED", 422,
                           "Clock date is past the family's last_order_date")


@bp.post("/configurations")
def create_configuration():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    body = validate.body_json(request)
    name = validate.req_str(body, "name")
    modules = _validate_modules_shape(validate.require(body, "modules"))
    spec = _new_entity({
        "dealer_id": user_id,
        "name": name,
        "modules": modules,
        "status": "DRAFT",
        "revision_number": 1,
        "total_units": None,
        "list_total_cents": None,
        "max_lead_time_days": None,
        "locked_at": None,
    })
    state.configurations[spec["id"]] = spec
    return envelope.success_object(serialize.configuration(spec), status=201)


@bp.get("/configurations/<configurationId>")
def get_configuration(configurationId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin"))
    spec = _load_spec(configurationId)
    authz.check_dealer_ownership(spec["dealer_id"], role, user_id)
    return envelope.success_object(serialize.configuration(spec))


@bp.get("/configurations")
def list_configurations():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin"))
    items = list(state.configurations.values())
    if role == "DealerRep":
        items = [c for c in items if c["dealer_id"] == user_id]
    dealer_filter = request.args.get("dealer_id")
    if dealer_filter is not None:
        items = [c for c in items if c["dealer_id"] == dealer_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    page, total, limit, offset = envelope.paginate(items, request.args)
    return envelope.success_list(
        [serialize.configuration(c) for c in page], total, limit, offset)


@bp.post("/configurations/<configurationId>/lock")
def lock_configuration(configurationId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    spec = _load_spec(configurationId)
    authz.check_dealer_ownership(spec["dealer_id"], role, user_id)
    body = validate.body_json(request)
    expected = validate.req_int(body, "expected_configuration_version")
    # Step 7 OCC precedes step 8 state (PRD 2.9; PRD 3.4 prose order).
    if expected != spec["version"]:
        errors.stale_version()
    if spec["status"] != "DRAFT":
        errors.invalid_state("Only a DRAFT configuration can be locked")
    _validate_modules_at_lock(spec)
    _check_family_lifecycle_at_lock(spec)
    lines, parts_total, total_units = calc.bom_expand(spec["modules"])
    spec["total_units"] = total_units
    spec["list_total_cents"] = parts_total
    spec["max_lead_time_days"] = calc.config_lead_time(spec["modules"])
    spec["status"] = "LOCKED"
    spec["locked_at"] = clock.now_iso()
    state.touch(spec)
    return envelope.success_object(serialize.configuration(spec))


@bp.post("/configurations/<configurationId>/revise")
def revise_configuration(configurationId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    spec = _load_spec(configurationId)
    authz.check_dealer_ownership(spec["dealer_id"], role, user_id)
    validate.body_json(request)
    if spec["status"] != "LOCKED":
        errors.invalid_state("Only a LOCKED configuration can be revised")
    spec["status"] = "DRAFT"
    spec["revision_number"] += 1
    state.touch(spec)
    return envelope.success_object(serialize.configuration(spec))


@bp.get("/configurations/<configurationId>/bom")
def configuration_bom(configurationId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin"))
    spec = _load_spec(configurationId)
    authz.check_dealer_ownership(spec["dealer_id"], role, user_id)
    lines, parts_total, total_units = calc.bom_expand(spec["modules"])
    return envelope.success_object({
        "lines": lines,
        "parts_total_cents": parts_total,
        "total_units": total_units,
    })
