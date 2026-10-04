"""Routes: procurement contracts and implementation phases."""
from flask import Blueprint, request

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_DUPLICATE_KEY,
    ERR_CONTRACT_NOT_SETTLED, ERR_PHASE_SEQUENCE_GAP,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services_common import strip_internal, append_audit
from util import (
    new_id, now_ts, touch, require_fields, require_int, optional_str, parse_date,
)

bp = Blueprint("contracts", __name__)

CONTRACT_STATUSES = [
    "DRAFT", "POSTED", "Q&A_OPEN", "Q&A_CLOSED", "EVALUATION", "AWARD_PENDING",
    "AWARDED", "IMPLEMENTATION", "CLOSED", "PROTESTED", "CANCELLED",
]

_TRANSITIONS = {
    ("DRAFT", "POSTED"),
    ("POSTED", "Q&A_OPEN"),
    ("Q&A_OPEN", "Q&A_CLOSED"),
    ("Q&A_CLOSED", "EVALUATION"),
    ("EVALUATION", "AWARD_PENDING"),
    ("EVALUATION", "PROTESTED"),
    ("PROTESTED", "EVALUATION"),
}

_AUDIT_TRANSITIONS = {"POSTED", "PROTESTED"}  # PROTESTED->EVALUATION handled separately


def get_contract_or_404(contract_id):
    c = db.get("contracts", contract_id)
    if c is None:
        raise_error(ERR_NOT_FOUND, "contract not found")
    return c


@bp.route("/programs/contracts", methods=["POST"])
def create_contract():
    user_id, role = require_roles("ProcurementOfficer")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["agency_id", "solicitation_number", "vendor_name", "contract_value_cents"])
    agency = db.get("agencies", payload["agency_id"])
    if agency is None:
        raise_error(ERR_REFERENCE_NOT_FOUND, "agency_id does not exist")
    if agency.get("status") == "ARCHIVED":
        raise_error(ERR_INVALID_STATE, "agency is archived")
    value = require_int(payload, "contract_value_cents")
    for c in db.all_items("contracts"):
        if c["solicitation_number"] == payload["solicitation_number"]:
            raise_error(ERR_DUPLICATE_KEY, "solicitation_number already exists")
    if value <= 0:
        raise_error(ERR_INVALID_REQUEST, "contract_value_cents must be greater than zero")
    now = now_ts()
    contract = {
        "id": new_id(),
        "agency_id": agency["id"],
        "solicitation_number": payload["solicitation_number"],
        "vendor_name": payload["vendor_name"],
        "contract_value_cents": value,
        "status": "DRAFT",
        "awarded_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("contracts", contract)
    append_audit(contract["id"], role, user_id, "POST /programs/contracts", "ProcurementContract",
                 contract["id"], "contract created in DRAFT")
    return success_object(strip_internal(contract), 201)


@bp.route("/programs/contracts", methods=["GET"])
def list_contracts():
    require_roles("ProcurementOfficer", "ImplementationManager", "AgencyProjectManager",
                  "VendorProjectManager", "FinanceOfficer", "PlatformAdmin")
    limit, offset = parse_pagination(request.args)
    items = db.all_items("contracts")
    agency_id = request.args.get("agency_id")
    if agency_id is not None:
        items = [c for c in items if c["agency_id"] == agency_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(c) for c in page], limit, offset, total)


@bp.route("/programs/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    require_roles("ProcurementOfficer", "ImplementationManager", "AgencyProjectManager",
                  "VendorProjectManager", "FinanceOfficer", "BusinessAnalyst",
                  "DataMigrationLead", "InterfaceEngineer", "SupportManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    return success_object(strip_internal(c), 200)


@bp.route("/programs/contracts/<contract_id>/transition", methods=["POST"])
def transition_contract(contract_id):
    user_id, role = require_roles("ProcurementOfficer")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["target"])
    target = payload["target"]
    if target not in CONTRACT_STATUSES or target in ("AWARDED", "IMPLEMENTATION", "CLOSED", "CANCELLED"):
        raise_error(ERR_INVALID_REQUEST, "invalid transition target")
    if (c["status"], target) not in _TRANSITIONS:
        raise_error(ERR_INVALID_STATE, f"cannot transition {c['status']} -> {target}")
    if target == "POSTED" and not c["contract_value_cents"] > 0:
        raise_error(ERR_INVALID_REQUEST, "contract_value_cents must be > 0 to post")
    if target == "PROTESTED" or (c["status"] == "PROTESTED" and target == "EVALUATION"):
        note = payload.get("note")
        if not isinstance(note, str) or not note.strip():
            raise_error(ERR_INVALID_REQUEST, "note is required for protest/resolution")
    before = c["status"]
    c["status"] = target
    touch(c)
    if target in _AUDIT_TRANSITIONS or before == "PROTESTED":
        append_audit(c["id"], role, user_id, "POST /programs/contracts/{id}/transition",
                     "ProcurementContract", c["id"], f"{before} -> {target}")
    return success_object(strip_internal(c), 200)


@bp.route("/programs/contracts/<contract_id>/award", methods=["POST"])
def award_contract(contract_id):
    user_id, role = require_roles("ProcurementOfficer")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["expected_contract_version"])
    expected = require_int(payload, "expected_contract_version")
    if c["status"] != "AWARD_PENDING":
        raise_error(ERR_INVALID_STATE, "contract not in AWARD_PENDING")
    if not isinstance(c.get("vendor_name"), str) or not c["vendor_name"].strip():
        raise_error(ERR_INVALID_REQUEST, "vendor_name must be non-empty")
    if expected != c["version"]:
        raise_error(ERR_STALE_VERSION, "stale contract version")
    c["status"] = "AWARDED"
    c["awarded_at"] = now_ts()
    touch(c)
    append_audit(c["id"], role, user_id, "POST /programs/contracts/{id}/award",
                 "ProcurementContract", c["id"], "AWARD_PENDING -> AWARDED")
    return success_object(strip_internal(c), 200)


@bp.route("/programs/contracts/<contract_id>/start-implementation", methods=["POST"])
def start_implementation(contract_id):
    user_id, role = require_roles("ImplementationManager")
    c = get_contract_or_404(contract_id)
    if c["status"] != "AWARDED":
        raise_error(ERR_INVALID_STATE, "contract not in AWARDED")
    phases = [p for p in db.filter_items("phases", contract_id=c["id"]) if p["status"] == "PLANNED"]
    if not phases:
        raise_error(ERR_INVALID_STATE, "no PLANNED phase exists")
    c["status"] = "IMPLEMENTATION"
    touch(c)
    for p in db.filter_items("phases", contract_id=c["id"]):
        if p["sequence_no"] == 1 and p["status"] == "PLANNED":
            p["status"] = "ACTIVE"
            touch(p)
    return success_object(strip_internal(c), 200)


@bp.route("/programs/contracts/<contract_id>/close", methods=["POST"])
def close_contract(contract_id):
    user_id, role = require_roles("ImplementationManager")
    c = get_contract_or_404(contract_id)
    if c["status"] != "IMPLEMENTATION":
        raise_error(ERR_INVALID_STATE, "contract not in IMPLEMENTATION")
    milestones = db.filter_items("milestones", contract_id=c["id"])
    if any(m["status"] != "PAID" for m in milestones):
        raise_error(ERR_CONTRACT_NOT_SETTLED, "all milestones must be PAID")
    transitions = db.filter_items("support_transitions", contract_id=c["id"])
    if not transitions or transitions[0]["status"] != "STEADY_STATE":
        raise_error(ERR_CONTRACT_NOT_SETTLED, "support transition must be STEADY_STATE")
    agreements = db.filter_items("maintenance_agreements", contract_id=c["id"])
    if not any(a["status"] == "ACTIVE" for a in agreements):
        raise_error(ERR_CONTRACT_NOT_SETTLED, "maintenance agreement must be ACTIVE")
    c["status"] = "CLOSED"
    touch(c)
    append_audit(c["id"], role, user_id, "POST /programs/contracts/{id}/close",
                 "ProcurementContract", c["id"], "IMPLEMENTATION -> CLOSED")
    return success_object(strip_internal(c), 200)


@bp.route("/programs/contracts/<contract_id>/cancel", methods=["POST"])
def cancel_contract(contract_id):
    user_id, role = require_roles("ProcurementOfficer")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["cancel_reason"])
    if c["status"] in ("CLOSED", "CANCELLED"):
        raise_error(ERR_INVALID_STATE, "contract already terminal")
    for m in db.filter_items("milestones", contract_id=c["id"]):
        if m["status"] in ("INVOICED", "PAID"):
            raise_error(ERR_INVALID_STATE, "contract has invoiced/paid milestones")
    # cascade
    for m in db.filter_items("milestones", contract_id=c["id"]):
        if m["status"] not in ("PAID", "REJECTED"):
            m["status"] = "REJECTED"
            touch(m)
    for p in db.filter_items("phases", contract_id=c["id"]):
        if p["status"] not in ("COMPLETED", "CANCELLED"):
            p["status"] = "CANCELLED"
            touch(p)
    c["status"] = "CANCELLED"
    touch(c)
    return success_object(strip_internal(c), 200)


# ---------------- phases ----------------

def get_phase_or_404(phase_id):
    p = db.get("phases", phase_id)
    if p is None:
        raise_error(ERR_NOT_FOUND, "phase not found")
    return p


@bp.route("/programs/contracts/<contract_id>/phases", methods=["POST"])
def create_phase(contract_id):
    require_roles("ImplementationManager")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["sequence_no", "name", "planned_start_on", "planned_end_on"])
    seq = require_int(payload, "sequence_no")
    start = parse_date(payload["planned_start_on"], "planned_start_on")
    end = parse_date(payload["planned_end_on"], "planned_end_on")
    if end < start:
        raise_error("ERR_INVALID_DATE_RANGE", "planned_end_on before planned_start_on")
    existing = db.filter_items("phases", contract_id=c["id"])
    expected_seq = max([p["sequence_no"] for p in existing], default=0) + 1
    if seq != expected_seq:
        raise_error(ERR_PHASE_SEQUENCE_GAP, "sequence_no not contiguous from 1")
    now = now_ts()
    phase = {
        "id": new_id(),
        "contract_id": c["id"],
        "sequence_no": seq,
        "name": payload["name"],
        "planned_start_on": payload["planned_start_on"],
        "planned_end_on": payload["planned_end_on"],
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("phases", phase)
    return success_object(strip_internal(phase), 201)


@bp.route("/programs/contracts/<contract_id>/phases", methods=["GET"])
def list_phases(contract_id):
    require_roles("ImplementationManager", "AgencyProjectManager", "VendorProjectManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("phases", contract_id=c["id"])
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(p) for p in page], limit, offset, total)


@bp.route("/programs/phases/<phase_id>", methods=["GET"])
def get_phase(phase_id):
    require_roles("ImplementationManager", "AgencyProjectManager", "VendorProjectManager", "PlatformAdmin")
    return success_object(strip_internal(get_phase_or_404(phase_id)), 200)


# ---------------- audit log ----------------

@bp.route("/programs/contracts/<contract_id>/audit-log", methods=["GET"])
def list_audit_log(contract_id):
    require_roles("PlatformAdmin", "AgencyProjectManager", "ProcurementOfficer",
                  "ImplementationManager", "FinanceOfficer")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("audit_log", contract_id=c["id"])
    kind = request.args.get("entity_kind")
    if kind is not None:
        items = [e for e in items if e["entity_kind"] == kind]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(e) for e in page], limit, offset, total)
