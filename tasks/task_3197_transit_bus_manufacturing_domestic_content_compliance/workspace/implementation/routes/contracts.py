"""Routes: contracts, option orders."""
from datetime import timedelta
from flask import Blueprint, request
from db import DB, stamp_new, touch, _fmt_logical
from errors import (
    err_not_found, err_invalid_request, err_fiscal, err_agency_suspended,
    err_invalid_state, err_audit_incomplete, err_stale_version, err_deadline,
    err_referential,
)
from middleware import require_roles, get_body, opt_enum
from response import success_obj, success_list, public, parse_pagination, paginate
from services.core import (
    option_escalation, recompute_zev, lazy_option_check, lazy_bus_check,
)

bp = Blueprint("contracts", __name__)

ESCALATION_INDICES = {"PPI_1413", "CPI_U"}
PROPULSION_TYPES = {"DIESEL", "CNG", "HEV", "BEV", "FCEV"}


def get_contract_or_404(cid):
    c = DB.contracts.get(cid)
    if c is None:
        raise err_not_found("Contract not found")
    return c


def _lazy_contract_reads(contract):
    """Lazily expire options and auto-accept buses when contract is read."""
    for o in DB.option_orders.values():
        if o["contract_id"] == contract["id"]:
            lazy_option_check(o)


@bp.post("/api/contracts")
def create_contract():
    uid, role = require_roles("ProcurementOfficer")
    body = get_body()
    agency_id = body.get("agency_id")
    if agency_id is None:
        raise err_invalid_request("Missing required field: agency_id")
    agency = DB.agencies.get(agency_id)
    if agency is None:
        raise err_not_found("Agency not found")
    if agency["status"] == "SUSPENDED":
        raise err_agency_suspended()
    base_quantity = body.get("base_quantity")
    base_price = body.get("base_unit_price_cents")
    base_year = body.get("base_contract_year")
    escalation_index = body.get("escalation_index")
    if base_quantity is None:
        raise err_invalid_request("Missing required field: base_quantity")
    if base_price is None:
        raise err_invalid_request("Missing required field: base_unit_price_cents")
    if base_year is None:
        raise err_invalid_request("Missing required field: base_contract_year")
    if escalation_index is None:
        raise err_invalid_request("Missing required field: escalation_index")
    if escalation_index not in ESCALATION_INDICES:
        raise err_invalid_request("Unknown escalation_index")
    if not isinstance(base_quantity, int) or isinstance(base_quantity, bool):
        raise err_invalid_request("base_quantity must be an integer")
    if not isinstance(base_price, int) or isinstance(base_price, bool):
        raise err_invalid_request("base_unit_price_cents must be an integer")
    option_years = body.get("option_years", 0)
    if not isinstance(option_years, int) or isinstance(option_years, bool) or option_years < 0 or option_years > 5:
        raise err_invalid_request("option_years must be an integer 0-5")
    option_specs = body.get("option_specs", [])
    if option_specs is None:
        option_specs = []
    if not isinstance(option_specs, list):
        raise err_invalid_request("option_specs must be an array")
    if option_years == 0:
        option_specs = []
    for spec in option_specs:
        if not isinstance(spec, dict):
            raise err_invalid_request("option_specs entries must be objects")
        if "quantity" not in spec or "propulsion_type" not in spec:
            raise err_invalid_request("option_specs entries require quantity and propulsion_type")
        if spec["propulsion_type"] not in PROPULSION_TYPES:
            raise err_invalid_request("Unknown propulsion_type in option_specs")
    if base_quantity < 1:
        raise err_fiscal("base_quantity must be at least 1")
    if base_price <= 0:
        raise err_fiscal("base_unit_price_cents must be positive")
    for spec in option_specs:
        q = spec["quantity"]
        if not isinstance(q, int) or isinstance(q, bool) or q <= 0:
            raise err_fiscal("option spec quantity must be positive")
    rec = {
        "agency_id": agency_id,
        "base_quantity": base_quantity,
        "base_unit_price_cents": base_price,
        "base_contract_year": base_year,
        "escalation_index": escalation_index,
        "option_years": option_years,
        "option_specs": option_specs,
        "awarded_at": None,
        "status": "DRAFT",
    }
    stamp_new(rec)
    DB.contracts[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/contracts")
def list_contracts():
    require_roles("PlatformAdmin", "ProcurementOfficer", "AgencyAdmin", "Auditor", "ProductionPlanner")
    limit, offset = parse_pagination(request.args)
    agency_id = request.args.get("agency_id")
    status = request.args.get("status")
    items = list(DB.contracts.values())
    if agency_id is not None:
        items = [c for c in items if c["agency_id"] == agency_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(c) for c in window], limit, offset, total)


@bp.get("/api/contracts/<contractId>")
def get_contract(contractId):
    require_roles("PlatformAdmin", "ProcurementOfficer", "AgencyAdmin", "Auditor", "ProductionPlanner")
    c = get_contract_or_404(contractId)
    _lazy_contract_reads(c)
    return success_obj(public(c))


@bp.post("/api/contracts/<contractId>/award")
def award_contract(contractId):
    require_roles("ProcurementOfficer")
    c = get_contract_or_404(contractId)
    if c["status"] != "DRAFT":
        raise err_invalid_state("Contract is not DRAFT")
    agency = DB.agencies.get(c["agency_id"])
    if agency is None or agency["status"] != "ACTIVE":
        raise err_invalid_state("Agency is not ACTIVE")
    if c["base_quantity"] < 1:
        raise err_fiscal("base_quantity must be at least 1")
    frozen_exists = any(
        cfg["contract_id"] == c["id"] and cfg["status"] == "FROZEN"
        for cfg in DB.configurations.values()
    )
    if not frozen_exists:
        raise err_invalid_state("No FROZEN BusConfiguration for this contract")
    now = DB.clock.now()
    c["status"] = "AWARDED"
    c["awarded_at"] = _fmt_logical(now)
    touch(c)
    for i, spec in enumerate(c["option_specs"]):
        oy = i + 1
        deadline = now + timedelta(days=365 * oy)
        oo = {
            "contract_id": c["id"],
            "option_year": oy,
            "quantity": spec["quantity"],
            "propulsion_type": spec["propulsion_type"],
            "exercised_unit_price_cents": None,
            "status": "AVAILABLE",
            "exercise_deadline": _fmt_logical(deadline),
        }
        stamp_new(oo)
        DB.option_orders[oo["id"]] = oo
    return success_obj(public(c))


@bp.post("/api/contracts/<contractId>/activate")
def activate_contract(contractId):
    require_roles("ProcurementOfficer")
    c = get_contract_or_404(contractId)
    if c["status"] != "AWARDED":
        raise err_invalid_state("Contract is not AWARDED")
    passing = any(
        a["contract_id"] == c["id"]
        and a["audit_type"] == "PRE_AWARD"
        and a["status"] == "COMPLETED"
        and a.get("result") == "PASS"
        for a in DB.audits.values()
    )
    if not passing:
        raise err_audit_incomplete()
    c["status"] = "ACTIVE"
    touch(c)
    return success_obj(public(c))


@bp.post("/api/contracts/<contractId>/complete")
def complete_contract(contractId):
    require_roles("ProcurementOfficer")
    c = get_contract_or_404(contractId)
    if c["status"] != "ACTIVE":
        raise err_invalid_state("Contract is not ACTIVE")
    for b in DB.buses.values():
        if b["contract_id"] == c["id"] and b["status"] not in ("ACCEPTED", "REJECTED"):
            raise err_invalid_state("BusUnits not all terminal")
    for o in DB.option_orders.values():
        if o["contract_id"] == c["id"] and o["status"] not in ("EXERCISED", "EXPIRED"):
            raise err_invalid_state("OptionOrders not all terminal")
    c["status"] = "COMPLETED"
    touch(c)
    return success_obj(public(c))


@bp.post("/api/contracts/<contractId>/terminate")
def terminate_contract(contractId):
    require_roles("ProcurementOfficer")
    c = get_contract_or_404(contractId)
    if c["status"] not in ("DRAFT", "ACTIVE"):
        raise err_invalid_state("Contract cannot be terminated from its current state")
    if c["status"] == "ACTIVE":
        for b in DB.buses.values():
            if b["contract_id"] == c["id"] and b["status"] in (
                "IN_PRODUCTION", "PLANT_INSPECTION", "IN_TRANSIT",
            ):
                raise err_invalid_state("Buses in production/inspection/transit")
        # Cascade
        affected_bus_ids = set()
        for o in DB.option_orders.values():
            if o["contract_id"] == c["id"] and o["status"] == "AVAILABLE":
                o["status"] = "EXPIRED"
                touch(o)
        for b in DB.buses.values():
            if b["contract_id"] == c["id"] and b["status"] in ("ORDERED", "ENGINEERED"):
                b["status"] = "REJECTED"
                touch(b)
                affected_bus_ids.add(b["id"])
        for slot in DB.slots.values():
            if slot.get("bus_unit_id") in affected_bus_ids and slot["status"] in ("OPEN", "ASSIGNED"):
                slot["status"] = "CANCELLED"
                slot["kit_status"] = "NOT_KITTED"
                touch(slot)
        for kit in DB.kits.values():
            if kit["bus_unit_id"] in affected_bus_ids and kit["status"] in ("STAGING", "COMPLETE"):
                kit["status"] = "CONSUMED"
                touch(kit)
        recompute_zev(c["agency_id"])
    c["status"] = "TERMINATED"
    touch(c)
    return success_obj(public(c))


@bp.get("/api/contracts/<contractId>/option-orders")
def contract_options(contractId):
    require_roles("PlatformAdmin", "ProcurementOfficer", "AgencyAdmin")
    c = get_contract_or_404(contractId)
    _lazy_contract_reads(c)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [o for o in DB.option_orders.values() if o["contract_id"] == contractId]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(o) for o in window], limit, offset, total)


@bp.get("/api/contracts/<contractId>/bus-configurations")
def contract_configs(contractId):
    require_roles("PlatformAdmin", "ProcurementOfficer", "ConfigEngineer", "Auditor")
    get_contract_or_404(contractId)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [c for c in DB.configurations.values() if c["contract_id"] == contractId]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(c) for c in window], limit, offset, total)


@bp.get("/api/contracts/<contractId>/bus-units")
def contract_buses(contractId):
    require_roles("PlatformAdmin", "ProcurementOfficer", "ProductionPlanner", "AgencyInspector", "Auditor", "WarrantyAdmin")
    get_contract_or_404(contractId)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [b for b in DB.buses.values() if b["contract_id"] == contractId]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(b) for b in window], limit, offset, total)


@bp.get("/api/contracts/<contractId>/audit-records")
def contract_audits(contractId):
    require_roles("PlatformAdmin", "ProcurementOfficer", "Auditor")
    get_contract_or_404(contractId)
    limit, offset = parse_pagination(request.args)
    audit_type = request.args.get("audit_type")
    items = [a for a in DB.audits.values() if a["contract_id"] == contractId]
    if audit_type is not None:
        items = [a for a in items if a["audit_type"] == audit_type]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(a) for a in window], limit, offset, total)


@bp.post("/api/option-orders/<optionOrderId>/exercise")
def exercise_option(optionOrderId):
    require_roles("ProcurementOfficer")
    o = DB.option_orders.get(optionOrderId)
    if o is None:
        raise err_not_found("OptionOrder not found")
    lazy_option_check(o)
    if o["status"] != "AVAILABLE":
        raise err_invalid_state("OptionOrder is not AVAILABLE")
    contract = DB.contracts.get(o["contract_id"])
    if contract is None:
        raise err_not_found("Contract not found")
    if contract["status"] != "ACTIVE":
        raise err_invalid_state("Contract is not ACTIVE")
    body = get_body()
    # deadline check (priority 9, before OCC priority 12)
    from db import _parse_iso
    now = DB.clock.now()
    if now > _parse_iso(o["exercise_deadline"]):
        raise err_deadline("Option exercise deadline passed")
    # FROZEN config with matching propulsion
    frozen_match = any(
        cfg["contract_id"] == contract["id"]
        and cfg["status"] == "FROZEN"
        and cfg["propulsion_type"] == o["propulsion_type"]
        for cfg in DB.configurations.values()
    )
    if not frozen_match:
        raise err_referential("No FROZEN BusConfiguration matching propulsion_type")
    expected = body.get("expected_contract_version")
    if expected is None:
        raise err_invalid_request("Missing required field: expected_contract_version")
    if expected != contract["version"]:
        raise err_stale_version()
    o["status"] = "EXERCISED"
    o["exercised_unit_price_cents"] = option_escalation(contract, o)
    touch(o)
    touch(contract)
    recompute_zev(contract["agency_id"])
    return success_obj(public(o))


@bp.get("/api/option-orders/<optionOrderId>")
def get_option(optionOrderId):
    require_roles("PlatformAdmin", "ProcurementOfficer", "AgencyAdmin")
    o = DB.option_orders.get(optionOrderId)
    if o is None:
        raise err_not_found("OptionOrder not found")
    lazy_option_check(o)
    return success_obj(public(o))
