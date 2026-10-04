"""BeefSupplier and Audit routes."""

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_AUDIT_ALREADY_RECORDED,
    ERR_SUPPLIER_INVALID_STATE,
    conflict,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    logical_iso,
    paginate,
    parse_datetime,
    req_field,
    req_int,
    req_string,
    touch,
)

bp = Blueprint("suppliers", __name__)

SPEC_PROFILE_KEYS_NUMERIC = ("lean_point_pct", "max_fat_pct", "max_bacterial_count_cfu_g")


def _validate_spec_profile(spec):
    if not isinstance(spec, dict):
        raise invalid_request("spec_profile must be an object")
    for k in SPEC_PROFILE_KEYS_NUMERIC:
        if k not in spec or isinstance(spec[k], bool) or not isinstance(spec[k], (int, float)):
            raise invalid_request("spec_profile.%s must be numeric" % k)
    if "chilled_never_frozen" not in spec or not isinstance(spec["chilled_never_frozen"], bool):
        raise invalid_request("spec_profile.chilled_never_frozen must be a boolean")


@bp.route("/suppliers", methods=["POST"])
def create_supplier():
    require_roles("SupplyChainDirector")
    body = get_json_body()
    supplier_code = req_string(body, "supplier_code")
    spec_profile = req_field(body, "spec_profile")
    audit_frequency_days = req_int(body, "audit_frequency_days")
    _validate_spec_profile(spec_profile)
    s = base_entity()
    s.update({
        "supplier_code": supplier_code,
        "spec_profile": spec_profile,
        "audit_frequency_days": audit_frequency_days,
        "status": "PROBATION",
    })
    db.suppliers[s["id"]] = s
    return success_object(domain.ser_supplier(s), 201)


@bp.route("/suppliers", methods=["GET"])
def list_suppliers():
    require_roles("SupplyChainDirector", "QualityAuditor", "CommissaryPlanner")
    items = list(db.suppliers.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_supplier(s) for s in page], limit, offset, total)


@bp.route("/suppliers/<sid>", methods=["GET"])
def get_supplier(sid):
    require_roles("SupplyChainDirector", "QualityAuditor", "CommissaryPlanner")
    return success_object(domain.ser_supplier(domain.get_supplier(sid)))


@bp.route("/suppliers/<sid>/retire", methods=["POST"])
def retire_supplier(sid):
    require_roles("SupplyChainDirector")
    supplier = domain.get_supplier(sid)
    if supplier["status"] != "APPROVED":
        raise conflict(ERR_SUPPLIER_INVALID_STATE, "Supplier must be APPROVED to retire")
    domain.supplier_retire_cascade(supplier)
    supplier["status"] = "RETIRED"
    touch(supplier)
    return success_object(domain.ser_supplier(supplier))


# ---------------- audits ----------------

@bp.route("/suppliers/<sid>/audits", methods=["POST"])
def schedule_audit(sid):
    require_roles("QualityAuditor")
    supplier = domain.get_supplier(sid)
    body = get_json_body()
    scheduled_date = parse_datetime(req_field(body, "scheduled_date"), "scheduled_date")
    a = base_entity()
    a.update({
        "supplier_id": supplier["id"],
        "scheduled_date": scheduled_date,
        "completed_at": None,
        "result": None,
        "findings": "",
        "recorded_by_id": None,
        "status": "SCHEDULED",
    })
    db.audits[a["id"]] = a
    return success_object(domain.ser_audit(a), 201)


@bp.route("/suppliers/<sid>/audits", methods=["GET"])
def list_audits(sid):
    require_roles("QualityAuditor", "SupplyChainDirector")
    supplier = domain.get_supplier(sid)
    items = [a for a in db.audits.values() if a["supplier_id"] == supplier["id"]]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_audit(a) for a in page], limit, offset, total)


@bp.route("/audits/<aid>", methods=["GET"])
def get_audit(aid):
    require_roles("QualityAuditor", "SupplyChainDirector")
    return success_object(domain.ser_audit(domain.get_audit(aid)))


@bp.route("/suppliers/<sid>/audits/<aid>/record-audit", methods=["POST"])
def record_audit(sid, aid):
    user_id, _ = require_roles("QualityAuditor")
    # Path existence left-to-right: supplier first, then audit.
    supplier = domain.get_supplier(sid)
    audit = domain.get_audit(aid)
    body = get_json_body()
    result = req_string(body, "result")
    if result not in ("PASS", "FAIL"):
        raise invalid_request("result must be PASS or FAIL")
    findings = body.get("findings", "")
    if findings is None:
        findings = ""
    if not isinstance(findings, str):
        raise invalid_request("findings must be a string")
    # State preconditions (tier 8): supplier status, then audit status.
    # FAIL is only recordable on PROBATION or APPROVED; PASS additionally on
    # SUSPENDED. Any other combination has no declared transition.
    if supplier["status"] == "RETIRED":
        raise conflict(ERR_SUPPLIER_INVALID_STATE, "Supplier is RETIRED")
    if supplier["status"] == "SUSPENDED" and result != "PASS":
        raise conflict(ERR_SUPPLIER_INVALID_STATE, "SUSPENDED supplier only accepts a PASS audit")
    if audit["status"] != "SCHEDULED":
        raise conflict(ERR_AUDIT_ALREADY_RECORDED, "Audit is not SCHEDULED")

    # Record the audit.
    audit["status"] = "RECORDED"
    audit["result"] = result
    audit["completed_at"] = db.clock_now()
    audit["recorded_by_id"] = user_id
    audit["findings"] = findings
    touch(audit)

    # Fire supplier transition.
    if result == "PASS":
        supplier["status"] = "APPROVED"
        touch(supplier)
    else:  # FAIL on PROBATION or APPROVED -> SUSPENDED + cascade
        domain.supplier_fail_suspension(supplier)
    return success_object(domain.ser_audit(audit))


@bp.route("/suppliers/<sid>/audits/<aid>/cancel", methods=["POST"])
def cancel_audit(sid, aid):
    require_roles("QualityAuditor")
    domain.get_supplier(sid)
    audit = domain.get_audit(aid)
    if audit["status"] != "SCHEDULED":
        raise conflict(ERR_AUDIT_ALREADY_RECORDED, "Audit is not SCHEDULED")
    audit["status"] = "CANCELLED"
    touch(audit)
    return success_object(domain.ser_audit(audit))
