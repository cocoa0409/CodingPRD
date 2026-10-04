"""DataSupplier endpoints and supplier-scoped agreement creation/listing."""

from flask import Blueprint, request

from db import db
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_agreement_window_overlap,
)
from middleware import require_role, get_pagination, ALL_ROLES
from response import success_object, success_array
from services.cascades import suspend_agreement_cascade, resume_agreement_cascade
from services.common import (
    body_json, require_fields, check_str, check_int, check_enum, check_date, mint, touch,
)

bp = Blueprint("suppliers", __name__)

SUPPLIER_TYPES = {"PHARMACY", "DISTRIBUTOR", "CLAIM_PROCESSOR"}
DATA_DOMAINS = {"RETAIL_SCRIPTS", "DISTRIBUTION_SHIPMENTS", "CLAIMS_ADJUDICATION"}
NON_TERMINAL_AGREEMENT_STATUSES = {"DRAFT", "ACTIVE", "SUSPENDED"}


def _sorted(values):
    return sorted(values, key=lambda e: e["created_at"])


def check_window_overlap(supplier_id, data_domain, start, end, exclude_id=None):
    """Half-open [start, end) overlap vs non-TERMINATED same-supplier same-domain agreements."""
    for ag in db.agreements.values():
        if exclude_id is not None and ag["id"] == exclude_id:
            continue
        if ag["supplier_id"] != supplier_id or ag["data_domain"] != data_domain:
            continue
        if ag["status"] not in NON_TERMINAL_AGREEMENT_STATUSES:
            continue
        if start < ag["exclusivity_end_date"] and ag["exclusivity_start_date"] < end:
            raise err_agreement_window_overlap()


@bp.route("/suppliers", methods=["POST"])
def create_supplier():
    require_role(["DataAcquisitionManager"])
    data = body_json()
    require_fields(data, ["name", "supplier_type", "state_code"])
    name = check_str(data, "name")
    supplier_type = check_enum(data, "supplier_type", SUPPLIER_TYPES)
    state_code = check_str(data, "state_code")
    supplier = mint(db.suppliers, {
        "name": name,
        "supplier_type": supplier_type,
        "state_code": state_code,
        "status": "ACTIVE",
    })
    return success_object(supplier, status=201)


@bp.route("/suppliers", methods=["GET"])
def list_suppliers():
    require_role(ALL_ROLES)
    limit, offset = get_pagination()
    supplier_type = request.args.get("supplier_type")
    status = request.args.get("status")
    if supplier_type is not None and supplier_type not in SUPPLIER_TYPES:
        raise err_invalid_request("Invalid supplier_type filter")
    if status is not None and status not in ("ACTIVE", "SUSPENDED"):
        raise err_invalid_request("Invalid status filter")
    items = _sorted(db.suppliers.values())
    if supplier_type is not None:
        items = [s for s in items if s["supplier_type"] == supplier_type]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)


@bp.route("/suppliers/<sid>", methods=["GET"])
def get_supplier(sid):
    require_role(ALL_ROLES)
    supplier = db.suppliers.get(sid)
    if supplier is None:
        raise err_not_found("Supplier not found")
    return success_object(supplier)


@bp.route("/suppliers/<sid>/suspend", methods=["POST"])
def suspend_supplier(sid):
    require_role(["DataAcquisitionManager"])
    supplier = db.suppliers.get(sid)
    if supplier is None:
        raise err_not_found("Supplier not found")
    if supplier["status"] != "ACTIVE":
        raise err_invalid_state("Supplier must be ACTIVE to suspend")
    supplier["status"] = "SUSPENDED"
    touch(supplier)
    for ag in sorted(
        (a for a in db.agreements.values()
         if a["supplier_id"] == sid and a["status"] == "ACTIVE"),
        key=lambda a: a["created_at"],
    ):
        ag["status"] = "SUSPENDED"
        touch(ag)
        suspend_agreement_cascade(ag)
    return success_object(supplier)


@bp.route("/suppliers/<sid>/resume", methods=["POST"])
def resume_supplier(sid):
    require_role(["DataAcquisitionManager"])
    supplier = db.suppliers.get(sid)
    if supplier is None:
        raise err_not_found("Supplier not found")
    if supplier["status"] != "SUSPENDED":
        raise err_invalid_state("Supplier must be SUSPENDED to resume")
    supplier["status"] = "ACTIVE"
    touch(supplier)
    for ag in sorted(
        (a for a in db.agreements.values()
         if a["supplier_id"] == sid and a["status"] == "SUSPENDED"),
        key=lambda a: a["created_at"],
    ):
        ag["status"] = "ACTIVE"
        touch(ag)
        resume_agreement_cascade(ag)
    return success_object(supplier)


@bp.route("/suppliers/<sid>/agreements", methods=["POST"])
def create_agreement(sid):
    require_role(["DataAcquisitionManager"])
    supplier = db.suppliers.get(sid)
    if supplier is None:
        raise err_not_found("Supplier not found")
    data = body_json()
    require_fields(data, ["data_domain", "exclusivity_start_date", "exclusivity_end_date", "royalty_budget_cents"])
    data_domain = check_enum(data, "data_domain", DATA_DOMAINS)
    start = check_date(data, "exclusivity_start_date")
    end = check_date(data, "exclusivity_end_date")
    budget = check_int(data, "royalty_budget_cents", min_v=0)
    check_window_overlap(sid, data_domain, start, end)
    agreement = mint(db.agreements, {
        "supplier_id": sid,
        "data_domain": data_domain,
        "exclusivity_start_date": start,
        "exclusivity_end_date": end,
        "royalty_budget_cents": budget,
        "royalty_spent_cents": 0,
        "amendment_count": 0,
        "status": "DRAFT",
    })
    return success_object(agreement, status=201)


@bp.route("/suppliers/<sid>/agreements", methods=["GET"])
def list_supplier_agreements(sid):
    require_role(ALL_ROLES)
    supplier = db.suppliers.get(sid)
    if supplier is None:
        raise err_not_found("Supplier not found")
    limit, offset = get_pagination()
    items = _sorted([a for a in db.agreements.values() if a["supplier_id"] == sid])
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)
