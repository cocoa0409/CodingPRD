"""Routes: bus configurations."""
from flask import Blueprint, request
from db import DB, stamp_new, touch
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_stale_version,
    err_validation,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate

bp = Blueprint("configurations", __name__)

PROPULSION_TYPES = {"DIESEL", "CNG", "HEV", "BEV", "FCEV"}


def get_config_or_404(cid):
    c = DB.configurations.get(cid)
    if c is None:
        raise err_not_found("BusConfiguration not found")
    return c


def derive_seat_count(seating_layout):
    """Parse seat_count from a structured seating_layout object.

    Supported shapes (checked in order):
      - {"seat_count": N}
      - {"seats": [...]} -> len(seats)
      - {"rows": [{"seats": k}, ...]} -> sum of seats per row
      - {"rows": N, "seats_per_row": M} -> N*M
      - {"rows": N} -> N
    Returns an int, or 0 if it cannot be parsed.
    """
    if isinstance(seating_layout, dict):
        v = seating_layout.get("seat_count")
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        seats = seating_layout.get("seats")
        if isinstance(seats, list):
            return len(seats)
        rows = seating_layout.get("rows")
        if isinstance(rows, list):
            total = 0
            for r in rows:
                if isinstance(r, dict):
                    s = r.get("seats", 0)
                    if isinstance(s, list):
                        total += len(s)
                    elif isinstance(s, int) and not isinstance(s, bool):
                        total += s
            return total
        if isinstance(rows, int) and not isinstance(rows, bool):
            spr = seating_layout.get("seats_per_row")
            if isinstance(spr, int) and not isinstance(spr, bool):
                return rows * spr
            return rows
    return 0


@bp.post("/api/bus-configurations")
def create_config():
    require_roles("ConfigEngineer")
    body = get_body()
    contract_id = body.get("contract_id")
    if contract_id is None:
        raise err_invalid_request("Missing required field: contract_id")
    propulsion_type = body.get("propulsion_type")
    if propulsion_type is None:
        raise err_invalid_request("Missing required field: propulsion_type")
    if propulsion_type not in PROPULSION_TYPES:
        raise err_invalid_request("Unknown propulsion_type")
    for f in ("seating_layout", "fare_equipment", "accessibility_features", "component_ids"):
        if f not in body or body[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")
    contract = DB.contracts.get(contract_id)
    if contract is None:
        raise err_not_found("Contract not found")
    rec = {
        "contract_id": contract_id,
        "propulsion_type": propulsion_type,
        "seating_layout": body["seating_layout"],
        "fare_equipment": body["fare_equipment"],
        "accessibility_features": body["accessibility_features"],
        "component_ids": body["component_ids"],
        "seat_count": None,
        "freeze_version": 0,
        "status": "DRAFT",
    }
    stamp_new(rec)
    DB.configurations[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/bus-configurations/<busConfigurationId>")
def get_config(busConfigurationId):
    require_roles("PlatformAdmin", "ConfigEngineer", "ProcurementOfficer", "Auditor")
    c = get_config_or_404(busConfigurationId)
    return success_obj(public(c))


@bp.post("/api/bus-configurations/<busConfigurationId>/submit-review")
def submit_review(busConfigurationId):
    require_roles("ConfigEngineer")
    c = get_config_or_404(busConfigurationId)
    if c["status"] != "DRAFT":
        raise err_invalid_state("Configuration is not DRAFT")
    contract = DB.contracts.get(c["contract_id"])
    if contract is None:
        raise err_not_found("Contract not found")
    if contract["status"] not in ("DRAFT", "AWARDED"):
        raise err_invalid_state("Contract is not DRAFT or AWARDED")
    c["status"] = "ENGINEERING_REVIEW"
    touch(c)
    return success_obj(public(c))


@bp.post("/api/bus-configurations/<busConfigurationId>/freeze")
def freeze_config(busConfigurationId):
    require_roles("ConfigEngineer")
    c = get_config_or_404(busConfigurationId)
    if c["status"] != "ENGINEERING_REVIEW":
        raise err_invalid_state("Configuration is not ENGINEERING_REVIEW")
    contract = DB.contracts.get(c["contract_id"])
    if contract is None:
        raise err_not_found("Contract not found")
    body = get_body()
    expected = body.get("expected_contract_version")
    if expected is None:
        raise err_invalid_request("Missing required field: expected_contract_version")
    if expected != contract["version"]:
        raise err_stale_version()
    seat_count = derive_seat_count(c["seating_layout"])
    if seat_count < 10:
        raise err_validation("seating_layout parses to seat_count < 10")
    agency = DB.agencies.get(contract["agency_id"])
    if agency is not None and agency.get("federally_funded", True):
        if "WHEELCHAIR_LIFT" not in (c["accessibility_features"] or []):
            from errors import err_accessibility
            raise err_accessibility()
    c["status"] = "FROZEN"
    c["seat_count"] = seat_count
    c["freeze_version"] = c.get("freeze_version", 0) + 1
    touch(c)
    touch(contract)
    return success_obj(public(c))


@bp.post("/api/bus-configurations/<busConfigurationId>/return-to-draft")
def return_to_draft(busConfigurationId):
    require_roles("ConfigEngineer")
    c = get_config_or_404(busConfigurationId)
    if c["status"] == "ENGINEERING_REVIEW":
        c["status"] = "DRAFT"
        touch(c)
        return success_obj(public(c))
    if c["status"] == "FROZEN":
        for b in DB.buses.values():
            if b["bus_configuration_id"] == c["id"] and b["status"] != "ORDERED":
                raise err_invalid_state("BusUnit references this configuration beyond ORDERED")
        c["status"] = "DRAFT"
        c["seat_count"] = None
        touch(c)
        return success_obj(public(c))
    raise err_invalid_state("Configuration cannot return to draft from its current state")


@bp.post("/api/bus-configurations/<busConfigurationId>/obsolete")
def obsolete_config(busConfigurationId):
    require_roles("ConfigEngineer")
    c = get_config_or_404(busConfigurationId)
    if c["status"] != "FROZEN":
        raise err_invalid_state("Configuration is not FROZEN")
    terminal = {"ACCEPTED", "REJECTED"}
    for b in DB.buses.values():
        if b["bus_configuration_id"] == c["id"] and b["status"] not in terminal:
            raise err_invalid_state("BusUnit references this configuration in a non-terminal status")
    c["status"] = "OBSOLETE"
    touch(c)
    return success_obj(public(c))


@bp.get("/api/bus-configurations/<busConfigurationId>/bus-units")
def config_buses(busConfigurationId):
    require_roles("PlatformAdmin", "ConfigEngineer", "ProductionPlanner")
    get_config_or_404(busConfigurationId)
    limit, offset = parse_pagination(request.args)
    items = [b for b in DB.buses.values() if b["bus_configuration_id"] == busConfigurationId]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(b) for b in window], limit, offset, total)
