# Installation phases: creation under orders + phase action endpoints (PRD 3.6).
from datetime import timedelta

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

bp = Blueprint("phases", __name__)


def _load_phase(phase_id):
    phase = state.phases.get(phase_id)
    if phase is None:
        errors.not_found("ERR_PHASE_NOT_FOUND", "No installation phase with the given id")
    return phase


def cancel_phase_cascade(phase):
    """System-driven phase cancellation (PRD 3.6): both dimensions to CANCELLED,
    windows RESERVED -> CANCELLED, punches OPEN/RESOLVED -> VOID. Plant capacity
    release is implicit (only SCHEDULED/DELIVERED phases hold reservations).
    COMPLETE phases are untouched."""
    if phase["install_status"] == "COMPLETE":
        return
    if phase["logistics_status"] == "CANCELLED":
        return
    phase["logistics_status"] = "CANCELLED"
    phase["install_status"] = "CANCELLED"
    state.touch(phase)
    for window in state.windows.values():
        if (window["installation_phase_id"] == phase["id"]
                and window["status"] == "RESERVED"):
            window["status"] = "CANCELLED"
            state.touch(window)
    for ticket in state.punches.values():
        if (ticket["installation_phase_id"] == phase["id"]
                and ticket["status"] in ("OPEN", "RESOLVED")):
            ticket["status"] = "VOID"
            state.touch(ticket)


@bp.post("/project-orders/<orderId>/phases")
def create_phase(orderId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    order = state.orders.get(orderId)
    if order is None:
        errors.not_found("ERR_ORDER_NOT_FOUND", "No project order with the given id")
    authz.check_order_ownership(order, role, user_id)
    body = validate.body_json(request)
    # Step 5 shape precedes the step 8 state gate (PRD 2.9 global order).
    floor_number = validate.req_int(body, "floor_number", minimum=1)
    phase_sequence = validate.req_int(body, "phase_sequence", minimum=1)
    building_zone_id = validate.req_str(body, "building_zone_id")
    planned_units = validate.req_int(body, "planned_units", minimum=1)
    for other in state.phases.values():
        if (other["project_order_id"] == order["id"]
                and other["phase_sequence"] == phase_sequence):
            errors.validation("phase_sequence must be unique within an order")
    if order["status"] not in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED"):
        errors.invalid_state(
            "Phases may be added only while the order is DRAFT, SUBMITTED, or ACKNOWLEDGED")
    phase = _new_entity({
        "project_order_id": order["id"],
        "floor_number": floor_number,
        "phase_sequence": phase_sequence,
        "building_zone_id": building_zone_id,
        "planned_units": planned_units,
        "logistics_status": "PLANNED",
        "install_status": "NOT_STARTED",
        "plant_code": None,
        "production_date": None,
        "delivered_at": None,
        "install_started_at": None,
        "actual_install_complete_date": None,
    })
    state.phases[phase["id"]] = phase
    return envelope.success_object(serialize.phase(phase), status=201)


@bp.get("/project-orders/<orderId>/phases")
def list_phases(orderId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin", "EndUserRep"))
    order = state.orders.get(orderId)
    if order is None:
        errors.not_found("ERR_ORDER_NOT_FOUND", "No project order with the given id")
    authz.check_order_ownership(order, role, user_id)
    items = [p for p in state.phases.values() if p["project_order_id"] == order["id"]]
    page, total, limit, offset = envelope.paginate(items, request.args)
    return envelope.success_list(
        [serialize.phase(p) for p in page], total, limit, offset)


@bp.post("/phases/<phaseId>/reserve-slot")
def reserve_slot(phaseId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    phase = _load_phase(phaseId)
    authz.check_phase_ownership(phase, role, user_id)
    body = validate.body_json(request)
    plant_code = validate.req_enum(body, "plant_code", constants.PLANT_CODES)
    production_date = validate.req_date(body, "production_date")
    # Gate order pinned by PRD 3.6: state, order acknowledged, lifecycle,
    # production notice, transit window, plant capacity.
    if phase["logistics_status"] != "PLANNED" or phase["install_status"] != "NOT_STARTED":
        errors.invalid_state("Only a PLANNED / NOT_STARTED phase can reserve a slot")
    order = state.orders.get(phase["project_order_id"])
    if order["status"] != "ACKNOWLEDGED":
        errors.err("ERR_ORDER_NOT_ACKNOWLEDGED", 409,
                   "The phase's order is not ACKNOWLEDGED")
    spec = state.configurations.get(order["configuration_id"])
    for entry in spec["modules"]:
        category = constants.MODULE_FAMILY_CATEGORY[entry["module_type"]]
        fam = calc.family_for_category(category)
        if fam is not None and fam["lifecycle_status"] == "DISCONTINUED":
            errors.err("ERR_PRODUCT_LINE_DISCONTINUED", 422,
                       f"Product family {fam['family_code']} is DISCONTINUED")
    today = clock.today()
    if production_date < today + timedelta(days=constants.PRODUCTION_NOTICE_DAYS):
        errors.err("ERR_PRODUCTION_NOTICE_VIOLATION", 422,
                   "production_date must be at least 2 days after the clock date")
    latest = (calc._parse_date(order["requested_install_date"])
              - timedelta(days=constants.TRANSIT_DAYS[plant_code]))
    if production_date > latest:
        errors.err("ERR_TRANSIT_WINDOW_VIOLATION", 422,
                   "production_date is later than requested_install_date - transit days")
    production_iso = production_date.isoformat()
    if calc.plant_capacity_available(plant_code, production_iso) < phase["planned_units"]:
        errors.err("ERR_PLANT_CAPACITY_EXCEEDED", 422,
                   "Plant daily capacity exceeded for that production_date")
    phase["plant_code"] = plant_code
    phase["production_date"] = production_iso
    phase["logistics_status"] = "SCHEDULED"
    state.touch(phase)
    return envelope.success_object(serialize.phase(phase))


@bp.post("/phases/<phaseId>/start-install")
def start_install(phaseId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    phase = _load_phase(phaseId)
    authz.check_phase_ownership(phase, role, user_id)
    validate.body_json(request)
    # One dealer action drives both dimensions (PRD 3.6).
    if phase["logistics_status"] != "SCHEDULED" or phase["install_status"] != "NOT_STARTED":
        errors.invalid_state("Only a SCHEDULED / NOT_STARTED phase can start install")
    if clock.today() < calc._parse_date(phase["production_date"]):
        errors.invalid_state("Goods cannot ship before their production_date")
    phase["logistics_status"] = "DELIVERED"
    phase["install_status"] = "IN_PROGRESS"
    phase["delivered_at"] = clock.now_iso()
    phase["install_started_at"] = clock.now_iso()
    state.touch(phase)
    return envelope.success_object(serialize.phase(phase))


@bp.post("/phases/<phaseId>/complete")
def complete_phase(phaseId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    phase = _load_phase(phaseId)
    authz.check_phase_ownership(phase, role, user_id)
    validate.body_json(request)
    if phase["install_status"] != "IN_PROGRESS":
        errors.invalid_state("Only an IN_PROGRESS phase can complete")
    # Gate 24: floor/phase sequencing (PRD 3.6).
    for other in state.phases.values():
        if other["project_order_id"] != phase["project_order_id"] or other["id"] == phase["id"]:
            continue
        earlier = ((other["floor_number"] < phase["floor_number"])
                   or (other["floor_number"] == phase["floor_number"]
                       and other["phase_sequence"] < phase["phase_sequence"]))
        if earlier and other["install_status"] != "COMPLETE":
            errors.err("ERR_FLOOR_SEQUENCE_VIOLATION", 422,
                       "An earlier (floor_number, phase_sequence) phase is not COMPLETE")
    # Gate 25: punch gate (PRD 3.6).
    for ticket in state.punches.values():
        if ticket["installation_phase_id"] != phase["id"]:
            continue
        if ticket["severity"] == "CRITICAL" and ticket["status"] in ("OPEN", "RESOLVED"):
            errors.err("ERR_OPEN_CRITICAL_PUNCH", 422,
                       "A CRITICAL punch is still OPEN or RESOLVED")
        if ticket["severity"] == "MAJOR" and ticket["status"] == "OPEN":
            errors.err("ERR_OPEN_CRITICAL_PUNCH", 422, "A MAJOR punch is still OPEN")
    phase["install_status"] = "COMPLETE"
    phase["actual_install_complete_date"] = clock.today().isoformat()
    state.touch(phase)
    # Bubble-up (PRD 3.6): order CLOSED when ACKNOWLEDGED and all phases COMPLETE.
    order = state.orders.get(phase["project_order_id"])
    siblings = [p for p in state.phases.values()
                if p["project_order_id"] == order["id"]]
    if (order["status"] == "ACKNOWLEDGED" and len(siblings) >= 1
            and all(p["install_status"] == "COMPLETE" for p in siblings)):
        order["status"] = "CLOSED"
        state.touch(order)
    return envelope.success_object(serialize.phase(phase))
