"""Routes: audit records."""
from flask import Blueprint, request
from db import DB, stamp_new, touch
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_sod,
    err_audit_precondition,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate

bp = Blueprint("audits", __name__)

AUDIT_TYPES = {"PRE_AWARD", "POST_DELIVERY"}


def get_audit_or_404(aid):
    a = DB.audits.get(aid)
    if a is None:
        raise err_not_found("AuditRecord not found")
    return a


def _buses_in_scope(contract_id):
    return [b for b in DB.buses.values() if b["contract_id"] == contract_id]


@bp.post("/api/audit-records")
def create_audit():
    require_roles("Auditor")
    body = get_body()
    contract_id = body.get("contract_id")
    audit_type = body.get("audit_type")
    auditor_id = body.get("auditor_id")
    if contract_id is None:
        raise err_invalid_request("Missing required field: contract_id")
    if audit_type is None:
        raise err_invalid_request("Missing required field: audit_type")
    if audit_type not in AUDIT_TYPES:
        raise err_invalid_request("Unknown audit_type")
    if auditor_id is None:
        raise err_invalid_request("Missing required field: auditor_id")
    contract = DB.contracts.get(contract_id)
    if contract is None:
        raise err_not_found("Contract not found")
    if audit_type == "POST_DELIVERY":
        # segregation of duties checked at open time per PRD 3.7
        for b in _buses_in_scope(contract_id):
            for c in DB.certificates.values():
                if c["bus_unit_id"] == b["id"] and c["status"] == "ISSUED":
                    if c["issued_by"] == auditor_id:
                        raise err_sod("POST_DELIVERY auditor collides with certificate issuer")
    rec = {
        "contract_id": contract_id,
        "audit_type": audit_type,
        "auditor_id": auditor_id,
        "scope_bus_count": 0,
        "findings_count": 0,
        "result": None,
        "status": "OPEN",
    }
    stamp_new(rec)
    DB.audits[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/audit-records/<auditRecordId>")
def get_audit(auditRecordId):
    require_roles("PlatformAdmin", "Auditor", "ProcurementOfficer")
    a = get_audit_or_404(auditRecordId)
    return success_obj(public(a))


@bp.post("/api/audit-records/<auditRecordId>/findings")
def record_finding(auditRecordId):
    require_roles("Auditor")
    a = get_audit_or_404(auditRecordId)
    if a["status"] != "OPEN":
        raise err_invalid_state("Audit is not OPEN")
    body = get_body()
    severity = body.get("severity")
    description_text = body.get("description_text")
    if severity is None:
        raise err_invalid_request("Missing required field: severity")
    if description_text is None:
        raise err_invalid_request("Missing required field: description_text")
    if severity == "FAILED":
        a["findings_count"] = a.get("findings_count", 0) + 1
    touch(a)
    return success_obj(public(a), 201)


@bp.post("/api/audit-records/<auditRecordId>/complete")
def complete_audit(auditRecordId):
    require_roles("Auditor")
    a = get_audit_or_404(auditRecordId)
    if a["status"] != "OPEN":
        raise err_invalid_state("Audit is not OPEN")
    contract = DB.contracts.get(a["contract_id"])
    buses = _buses_in_scope(a["contract_id"])
    if a["audit_type"] == "PRE_AWARD":
        if contract is None or contract["status"] != "AWARDED":
            raise err_audit_precondition("Contract is not AWARDED")
        ok = False
        for cfg in DB.configurations.values():
            if cfg["contract_id"] != a["contract_id"] or cfg["status"] != "FROZEN":
                continue
            propulsion_ids = [
                cid for cid in (cfg["component_ids"] or [])
                if cid in DB.components and DB.components[cid]["category"] == "PROPULSION"
            ]
            if all(DB.components[cid]["supplier_doc_status"] == "VERIFIED" for cid in propulsion_ids):
                ok = True
                break
        if not ok:
            raise err_audit_precondition("No FROZEN configuration with all PROPULSION components VERIFIED")
    else:  # POST_DELIVERY
        for b in buses:
            cert = None
            for c in DB.certificates.values():
                if c["bus_unit_id"] == b["id"] and c["status"] == "ISSUED":
                    cert = c
                    break
            if cert is None:
                raise err_audit_precondition("In-scope bus lacks an ISSUED certificate")
            if b["assembly_location"] not in ("US_MAIN", "US_ANNEX"):
                raise err_audit_precondition("In-scope bus not assembled at a domestic plant")
            if cert["issued_by"] == a["auditor_id"]:
                raise err_sod("POST_DELIVERY auditor collides with certificate issuer")
    a["scope_bus_count"] = len(buses)
    a["result"] = "PASS" if a.get("findings_count", 0) == 0 else "FAIL"
    a["status"] = "COMPLETED"
    touch(a)
    return success_obj(public(a))
