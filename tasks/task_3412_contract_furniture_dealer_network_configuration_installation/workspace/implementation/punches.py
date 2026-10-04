# Punch tickets routes (PRD 3.8; scaffold Tables 2/5).
from flask import Blueprint, request

import authz
import clock
import constants
import envelope
import errors
import serialize
import state
import validate
from dealers import _new_entity

bp = Blueprint("punches", __name__)


def _load_ticket(ticket_id):
    ticket = state.punches.get(ticket_id)
    if ticket is None:
        errors.not_found("ERR_PUNCH_NOT_FOUND", "No punch ticket with the given id")
    return ticket


def _ticket_visible_to(ticket, role, user_id):
    if role == "ManufacturerAdmin":
        return True
    phase = state.phases.get(ticket["installation_phase_id"])
    if phase is None:
        return False
    order = state.orders.get(phase["project_order_id"])
    if order is None:
        return False
    return authz.order_visible_to(order, role, user_id)


@bp.post("/punch-tickets")
def create_punch():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("EndUserRep", "DealerRep"))
    body = validate.body_json(request)
    # Step 3: body FK resolves.
    phase_id = body.get("installation_phase_id")
    if isinstance(phase_id, str) and phase_id not in state.phases:
        errors.not_found("ERR_PHASE_NOT_FOUND", "No installation phase with the given id")
    phase = state.phases.get(phase_id) if isinstance(phase_id, str) else None
    # Step 4: ownership of the phase's order (dealer scope or end-user scope).
    if phase is not None:
        authz.check_phase_ownership(phase, role, user_id)
    # Step 5: body shape, including the conditional part_number requirement.
    phase_id = validate.req_str(body, "installation_phase_id")
    severity = validate.req_enum(body, "severity", constants.PUNCH_SEVERITIES)
    description = validate.req_str(body, "description")
    requires_part = validate.opt_bool(body, "requires_part", False)
    if requires_part is None:
        requires_part = False
    part_number = None
    if requires_part:
        part_number = validate.req_str(body, "part_number")
        if part_number not in constants.CATALOG_PART_NUMBERS:
            errors.validation("part_number must be a catalog part number")
    phase = state.phases[phase_id]
    # Step 8: filing requires install IN_PROGRESS (PRD 3.8).
    if phase["install_status"] != "IN_PROGRESS":
        errors.invalid_state("Punch items may be filed only while install is IN_PROGRESS")
    ticket = _new_entity({
        "installation_phase_id": phase_id,
        "severity": severity,
        "description": description,
        "requires_part": requires_part,
        "part_number": part_number,
        "status": "OPEN",
        "resolution_note": None,
    })
    state.punches[ticket["id"]] = ticket
    return envelope.success_object(serialize.punch(ticket), status=201)


@bp.get("/punch-tickets")
def list_punches():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin", "EndUserRep"))
    items = [t for t in state.punches.values()
             if _ticket_visible_to(t, role, user_id)]
    phase_filter = request.args.get("installation_phase_id")
    if phase_filter is not None:
        items = [t for t in items if t["installation_phase_id"] == phase_filter]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [t for t in items if t["status"] == status_filter]
    page, total, limit, offset = envelope.paginate(items, request.args)
    return envelope.success_list(
        [serialize.punch(t) for t in page], total, limit, offset)


@bp.get("/punch-tickets/<ticketId>")
def get_punch(ticketId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin", "EndUserRep"))
    ticket = _load_ticket(ticketId)
    if not _ticket_visible_to(ticket, role, user_id):
        errors.forbidden_ownership()
    return envelope.success_object(serialize.punch(ticket))


@bp.post("/punch-tickets/<ticketId>/resolve")
def resolve_punch(ticketId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    ticket = _load_ticket(ticketId)
    authz.check_punch_ownership(ticket, role, user_id)
    body = validate.body_json(request)
    resolution_note = validate.req_str(body, "resolution_note")
    if ticket["status"] != "OPEN":
        errors.invalid_state("Only an OPEN ticket can be resolved")
    ticket["status"] = "RESOLVED"
    ticket["resolution_note"] = resolution_note
    state.touch(ticket)
    if ticket["requires_part"]:
        # CASCADE link 1 (PRD 3.8): auto-create a SUBMITTED PARTS WarrantyClaim.
        phase = state.phases.get(ticket["installation_phase_id"])
        claim = _new_entity({
            "project_order_id": phase["project_order_id"],
            "installation_phase_id": phase["id"],
            "punch_ticket_id": ticket["id"],
            "claim_type": "PARTS",
            "part_number": ticket["part_number"],
            "description": ticket["description"],
            "status": "SUBMITTED",
            "filed_date": clock.today().isoformat(),
            "review_note": None,
            "reviewed_at": None,
        })
        state.claims[claim["id"]] = claim
    return envelope.success_object(serialize.punch(ticket))


@bp.post("/punch-tickets/<ticketId>/verify")
def verify_punch(ticketId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("EndUserRep",))
    ticket = _load_ticket(ticketId)
    authz.check_punch_ownership(ticket, role, user_id)
    body = validate.body_json(request)
    outcome = validate.req_enum(body, "outcome", constants.VERIFY_OUTCOMES)
    if ticket["status"] != "RESOLVED":
        errors.invalid_state("Only a RESOLVED ticket can be verified")
    ticket["status"] = "VERIFIED" if outcome == "CONFIRMED" else "OPEN"
    state.touch(ticket)
    return envelope.success_object(serialize.punch(ticket))
