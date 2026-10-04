"""Directive issuance (PlatformAdmin): immutable airworthiness artifacts whose
mandatory entries cascade into open workscopes of INDUCTED visits."""
from flask import Blueprint

from authz import require_roles
from cascade import directive_issuance_cascade
from envelope import success
from errors import api_err
from serialize import directive_json
from storage import DB, new_id, next_seq, now
from validate import as_bool, as_datetime, as_enum, as_int, as_number, as_str, body, req_field

bp = Blueprint("directives", __name__)

DIRECTIVE_TYPES = {"AD", "SB", "ED"}


@bp.route("/api/directives", methods=["POST"])
def create_directive():
    require_roles("PlatformAdmin")
    data = body()
    ref = as_str(req_field(data, "directive_ref"), "directive_ref")
    dtype = as_enum(req_field(data, "directive_type"), "directive_type", DIRECTIVE_TYPES)
    model = as_str(req_field(data, "applicability_model"), "applicability_model")
    mandatory = as_bool(req_field(data, "mandatory"), "mandatory")
    cost = as_number(req_field(data, "estimated_cost_usd"), "estimated_cost_usd")
    if cost <= 0:
        raise api_err("ERR_INVALID_REQUEST", "estimated_cost_usd must be > 0")
    compliance_cycles = data.get("compliance_cycles")
    if compliance_cycles is not None:
        compliance_cycles = as_int(compliance_cycles, "compliance_cycles")
        if compliance_cycles <= 0:
            raise api_err("ERR_INVALID_REQUEST", "compliance_cycles must be a positive integer")
    compliance_date = data.get("compliance_date")
    if compliance_date is not None:
        compliance_date = as_datetime(compliance_date, "compliance_date")
    if compliance_cycles is None and compliance_date is None:
        raise api_err("ERR_INVALID_REQUEST",
                      "at least one of compliance_cycles / compliance_date is required")
    if any(d["directive_ref"] == ref for d in DB["directives"].values()):
        raise api_err("ERR_DUPLICATE_RESOURCE", "directive_ref already issued")
    directive = {
        "id": new_id(), "directive_ref": ref, "directive_type": dtype,
        "applicability_model": model, "mandatory": mandatory,
        "compliance_cycles": compliance_cycles, "compliance_date": compliance_date,
        "estimated_cost_usd": cost,
        "created_at": now(), "_seq": next_seq(),
    }
    DB["directives"][directive["id"]] = directive
    directive_issuance_cascade(directive)
    return success(directive_json(directive), 201)
