# ProductionLine domain (PRD 3.3): registration (OWNED starts CERTIFIED, CO_MAN
# starts PENDING with contract fields), the operational cycle, and co-man
# quality-equivalence audits driving the certification dimension.
from decimal import Decimal

from flask import Blueprint, request

import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from store import db, flush_dirty, make_entity, mark, public
from validation import Shape, body_json, get_enum, get_int, get_list, get_num, get_str

bp = Blueprint("lines", __name__, url_prefix="/protein-ops/production-lines")

ANY_ROLE = constants.ROLES
OPERATIONAL_STATES = ["IDLE", "SETUP", "RUNNING", "CLEANING", "DOWN"]
# IDLE -> SETUP -> RUNNING -> CLEANING -> IDLE; DOWN reachable from the four
# cycle states and returning only to IDLE.
OPERATIONAL_TRANSITIONS = {
    ("IDLE", "SETUP"),
    ("SETUP", "RUNNING"),
    ("RUNNING", "CLEANING"),
    ("CLEANING", "IDLE"),
    ("IDLE", "DOWN"),
    ("SETUP", "DOWN"),
    ("RUNNING", "DOWN"),
    ("CLEANING", "DOWN"),
    ("DOWN", "IDLE"),
}


@bp.route("", methods=["POST"])
def create_line():
    _user_id, role = authenticate()
    authorize(role, ["PlantManager"])

    body = body_json()
    shape = Shape()
    line_code = get_str(body, "line_code", shape, non_empty=True)
    site_type = get_enum(body, "site_type", constants.SITE_TYPES, shape)
    hourly_capacity_kg = get_int(body, "hourly_capacity_kg", shape, minv=1)
    supported = get_list(body, "supported_isolate_types", shape, item_choices=constants.ISOLATE_TYPES, non_empty=True)
    coman_partner_name = get_str(body, "coman_partner_name", shape, required=False)
    monthly_cap = get_int(body, "monthly_reserved_capacity_kg", shape, required=False)

    # Tier 8: uniqueness of line_code.
    if line_code is not None:
        for existing in db["lines"].values():
            if existing["line_code"] == line_code:
                raise err("ERR_UNIQUE_CONSTRAINT", "line_code already exists")

    # Tier 11: type-conditional contract fields — required exactly when CO_MAN,
    # forbidden on OWNED.
    if site_type == "CO_MAN":
        if coman_partner_name is None:
            shape.add("coman_partner_name", "is required for CO_MAN lines")
        if monthly_cap is None:
            shape.add("monthly_reserved_capacity_kg", "is required for CO_MAN lines")
    elif site_type == "OWNED":
        if coman_partner_name is not None:
            shape.add("coman_partner_name", "must be null for OWNED lines")
        if monthly_cap is not None:
            shape.add("monthly_reserved_capacity_kg", "must be null for OWNED lines")
    shape.raise_if_any()

    line = make_entity(
        "lines",
        {
            "line_code": line_code,
            "site_type": site_type,
            "coman_partner_name": coman_partner_name,
            "monthly_reserved_capacity_kg": monthly_cap,
            "hourly_capacity_kg": hourly_capacity_kg,
            "supported_isolate_types": supported,
            "certification_status": "CERTIFIED" if site_type == "OWNED" else "PENDING",
            "operational_status": "IDLE",
            "reserved_capacity_kg": 0,
            "last_audit_texture_score": None,
            "last_audit_moisture_variance_pct": None,
        },
    )
    return success(public(line), "object", 201)


@bp.route("", methods=["GET"])
def list_lines():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["lines"].values())
    for param in ("site_type", "certification_status", "operational_status"):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l.get(param) == value]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, meta = paginate([public(l) for l in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/<lid>/operational-transitions", methods=["POST"])
def operational_transition(lid):
    _user_id, role = authenticate()
    authorize(role, ["PlantManager"])

    line = db["lines"].get(lid)
    if line is None:
        raise err("ERR_NOT_FOUND", "production line not found")

    body = body_json()
    shape = Shape()
    target = get_enum(body, "target_status", OPERATIONAL_STATES, shape)
    if target is not None:
        if (line["operational_status"], target) not in OPERATIONAL_TRANSITIONS:
            raise err(
                "ERR_INVALID_STATE",
                "no operational transition %s -> %s" % (line["operational_status"], target),
            )
    shape.raise_if_any()

    line["operational_status"] = target
    mark(line)
    flush_dirty()
    return success(public(line), "object", 200)


@bp.route("/<lid>/certification-audits", methods=["POST"])
def certification_audit(lid):
    _user_id, role = authenticate()
    authorize(role, ["QualityManager"])

    line = db["lines"].get(lid)
    if line is None:
        raise err("ERR_NOT_FOUND", "production line not found")

    body = body_json()
    shape = Shape()
    texture_score = get_int(body, "texture_score", shape)
    moisture_variance_pct = get_num(body, "moisture_variance_pct", shape)

    # Tier 6 compliance: audits apply only to co-manufactured lines.
    if line["site_type"] != "CO_MAN":
        raise err("ERR_AUDIT_NOT_APPLICABLE", "certification audits apply only to CO_MAN lines")
    shape.raise_if_any()

    # equivalence_audit_result: inclusive thresholds — boundaries pass.
    passed = (
        texture_score >= constants.TEXTURE_EQUIVALENCE_MIN_SCORE
        and Decimal(str(moisture_variance_pct)) <= constants.MOISTURE_VARIANCE_MAX_PCT
    )
    line["last_audit_texture_score"] = texture_score
    line["last_audit_moisture_variance_pct"] = moisture_variance_pct
    if passed:
        line["certification_status"] = "CERTIFIED"
    elif line["certification_status"] == "CERTIFIED":
        line["certification_status"] = "SUSPENDED"
    # FAILED from PENDING (or SUSPENDED) leaves the status unchanged.
    mark(line)
    flush_dirty()
    return success(public(line), "object", 201)
