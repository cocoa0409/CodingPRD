"""FederalDefinition and DataElementMapping routes."""
from flask import Blueprint

from auth import actor, require_roles
from db import (LOCAL_SYSTEMS, READ_ROLES, SURVEY_DOMAINS, public, stamp_config,
                stamp_new, store, touch)
from errors import fail
from response import created, filter_eq, ok, paginate
from svc_common import get_cycle, get_definition, get_mapping
from svc_cycle import require_not_frozen
from validation import (get_body, opt_bool, opt_string, req_enum, req_str_array,
                        req_string, req_value_map)

bp = Blueprint("library", __name__)


def serialize_definition(row):
    return public(row)


def serialize_mapping(row):
    return public(row)


@bp.post("/federal-definitions")
def create_definition():
    require_roles("DataSteward")
    body = get_body()
    definition_code = req_string(body, "definition_code", 3, 64)
    survey_component = req_enum(body, "survey_component", SURVEY_DOMAINS)
    value_domain = req_str_array(body, "value_domain", 1, 40, 1, 32)
    required = opt_bool(body, "required", default=True)
    unit_of_measure = req_string(body, "unit_of_measure", 1, 32)
    effective_cycle_code = req_string(body, "effective_cycle_code", 1, 32)
    for peer in store.definitions.values():
        if (peer["definition_code"] == definition_code
                and peer["effective_cycle_code"] == effective_cycle_code):
            fail("ERR_DUPLICATE_DEFINITION",
                 "this definition code already exists for the effective cycle code")
    row = {
        "definition_code": definition_code,
        "survey_component": survey_component,
        "value_domain": value_domain,
        "required": required,
        "unit_of_measure": unit_of_measure,
        "effective_cycle_code": effective_cycle_code,
    }
    stamp_config(row)
    store.definitions[row["id"]] = row
    return created(serialize_definition(row))


@bp.get("/federal-definitions/<definition_id>")
def read_definition(definition_id):
    require_roles(*READ_ROLES)
    return ok(serialize_definition(get_definition(definition_id)))


@bp.get("/federal-definitions")
def list_definitions():
    require_roles(*READ_ROLES)
    rows = sorted(store.definitions.values(),
                  key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    rows = filter_eq(rows, {"survey_component": "survey_component",
                            "effective_cycle_code": "effective_cycle_code",
                            "required": "required"})
    return paginate(rows, serialize_definition)


# ---------------------------------------------------------------- DataElementMapping


def _value_domain_ok(definition, value_map):
    domain = definition["value_domain"]
    return all(value in domain for value in value_map.values())


@bp.post("/element-mappings")
def create_mapping():
    require_roles("IRAnalyst")
    body = get_body()
    cycle_id = req_string(body, "cycle_id", 1, None)
    definition_id = req_string(body, "definition_id", 1, None)
    local_system_code = req_enum(body, "local_system_code", LOCAL_SYSTEMS)
    local_field_path = req_string(body, "local_field_path", 3, 120)
    transform_expression = req_string(body, "transform_expression", 1, 500)
    value_map = req_value_map(body, "value_map", 1, 40)
    cycle = get_cycle(cycle_id)
    get_definition(definition_id)
    require_not_frozen(cycle)
    for peer in store.mappings.values():
        if (peer["cycle_id"] == cycle_id and peer["definition_id"] == definition_id
                and peer["local_system_code"] == local_system_code
                and peer["status"] != "REJECTED"):
            fail("ERR_DUPLICATE_MAPPING",
                 "a live mapping already exists for this cycle, definition and local system")
    row = {
        "cycle_id": cycle_id,
        "definition_id": definition_id,
        "local_system_code": local_system_code,
        "local_field_path": local_field_path,
        "transform_expression": transform_expression,
        "value_map": value_map,
        "status": "PROPOSED",
        "revision_round": 0,
        "validated_by_user_id": None,
        "rejection_reason": None,
    }
    stamp_new(row)
    store.mappings[row["id"]] = row
    return created(serialize_mapping(row))


@bp.get("/element-mappings/<mapping_id>")
def read_mapping(mapping_id):
    require_roles(*READ_ROLES)
    return ok(serialize_mapping(get_mapping(mapping_id)))


@bp.get("/element-mappings")
def list_mappings():
    require_roles(*READ_ROLES)
    rows = sorted(store.mappings.values(),
                  key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    rows = filter_eq(rows, {"cycle_id": "cycle_id", "definition_id": "definition_id",
                            "status": "status", "local_system_code": "local_system_code"})
    return paginate(rows, serialize_mapping)


@bp.post("/element-mappings/<mapping_id>/validate")
def validate_mapping(mapping_id):
    require_roles("DataSteward")
    body = get_body()
    decision = req_enum(body, "decision", ("APPROVE", "REJECT"))
    reason = opt_string(body, "rejection_reason", None, 500)
    mapping = get_mapping(mapping_id)
    cycle = get_cycle(mapping["cycle_id"])
    require_not_frozen(cycle)
    if mapping["status"] != "PROPOSED":
        fail("ERR_INVALID_MAPPING_STATE", "only a PROPOSED mapping can be adjudicated")
    if decision == "APPROVE":
        definition = get_definition(mapping["definition_id"])
        if not _value_domain_ok(definition, mapping["value_map"]):
            fail("ERR_VALUE_DOMAIN_VIOLATION",
                 "a mapped value falls outside the federal value domain")
        mapping["status"] = "VALIDATED"
        mapping["validated_by_user_id"] = actor()
        mapping["rejection_reason"] = None
    else:
        if reason is None or len(reason) < 10:
            fail("ERR_REJECTION_REASON_REQUIRED",
                 "a rejection requires a reason of 10 to 500 characters")
        mapping["status"] = "REJECTED"
        mapping["validated_by_user_id"] = actor()
        mapping["rejection_reason"] = reason
    touch(mapping)
    return ok(serialize_mapping(mapping))


@bp.post("/element-mappings/<mapping_id>/revise")
def revise_mapping(mapping_id):
    require_roles("IRAnalyst")
    body = get_body()
    transform_expression = req_string(body, "transform_expression", 1, 500)
    value_map = req_value_map(body, "value_map", 1, 40)
    mapping = get_mapping(mapping_id)
    cycle = get_cycle(mapping["cycle_id"])
    require_not_frozen(cycle)
    if mapping["status"] != "REJECTED":
        fail("ERR_INVALID_MAPPING_STATE", "only a REJECTED mapping can be revised")
    definition = get_definition(mapping["definition_id"])
    if not _value_domain_ok(definition, value_map):
        fail("ERR_VALUE_DOMAIN_VIOLATION",
             "a mapped value falls outside the federal value domain")
    mapping["transform_expression"] = transform_expression
    mapping["value_map"] = value_map
    mapping["status"] = "PROPOSED"
    mapping["rejection_reason"] = None
    mapping["revision_round"] = mapping["revision_round"] + 1
    touch(mapping)
    return ok(serialize_mapping(mapping))
