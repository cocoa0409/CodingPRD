"""PRD 3.8 — moves-adds-changes ticketing, the MAC budget and Cascade C."""

from flask import Blueprint, request

import calc
import identifiers
import lookup
import rollups
import serial
import store
from auth import (CERTIFIER, CLIENT, DESIGN_ENGINEER, INSTALLER, PROJECT_MANAGER,
                  require)
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import D, base_record, db, touch
from validation import Field, body, no_body, require_window

mac_bp = Blueprint("mac", __name__)

TICKET_TYPES = ("MOVE", "ADD", "CHANGE")
TICKET_STATES = ("SUBMITTED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "REJECTED")
ROOM_OCCUPYING_STATES = ("SCHEDULED", "IN_PROGRESS")
READ_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, INSTALLER, CERTIFIER, CLIENT)


def _room_window_conflict(ticket, start, end):
    """PRD 3.8: widen the candidate by 30 minutes at BOTH ends, compare against the
    unwidened windows of the other SCHEDULED / IN_PROGRESS tickets of the same room.
    The intersection is half-open, so an exact half-hour gap is admitted, and two
    overlaps are legal while the third is refused."""
    buffer = store.minutes(calc.MAC_CHANGEOVER_MINUTES)
    widened_start = start - buffer
    widened_end = end + buffer
    overlaps = 0
    for other in db.tickets.values():
        if other["id"] == ticket["id"]:
            continue
        if other["telecom_room_id"] != ticket["telecom_room_id"]:
            continue
        if other["ticket_state"] not in ROOM_OCCUPYING_STATES:
            continue
        other_start = other["scheduled_window_start"]
        other_end = other["scheduled_window_end"]
        if other_start is None or other_end is None:
            continue
        if other_start < widened_end and other_end > widened_start:
            overlaps += 1
    return overlaps >= calc.MAC_ROOM_CREW_CAPACITY


@mac_bp.route("/cabling/mac-tickets", methods=["POST"])
@require(CLIENT)
def raise_ticket():
    values = body([
        Field("project_id", "string"),
        Field("link_id", "string"),
        Field("telecom_room_id", "string"),
        Field("ticket_type", "enum", enum=TICKET_TYPES),
        Field("requested_window_start", "datetime"),
        Field("requested_window_end", "datetime"),
        Field("labor_hours_estimate", "number", exclusive_min=0),
        Field("expedite_requested", "bool", required=False, default=False),
        Field("new_identifier", "string", required=False, default=None, nullable=True),
    ])
    require_window(values, "requested_window_start", "requested_window_end")
    if values["new_identifier"] is not None and values["ticket_type"] != "CHANGE":
        raise ApiError("ERR_INVALID_REQUEST",
                       "new_identifier is null on every ticket type but CHANGE.")
    project = lookup.project(values["project_id"])
    link = lookup.link(values["link_id"])
    room = lookup.room(values["telecom_room_id"])
    if link["project_id"] != project["id"]:
        raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                       "link_id belongs to a different project.")
    if room["project_id"] != project["id"]:
        raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                       "telecom_room_id belongs to a different project.")
    if project["occupancy_status"] != "OCCUPIED":
        raise ApiError("ERR_PROJECT_NOT_OCCUPIED",
                       "Moves-adds-changes ticketing opens only once the space is "
                       "occupied.")
    ticket = base_record()
    ticket.update({
        "project_id": project["id"],
        "link_id": link["id"],
        "telecom_room_id": room["id"],
        "ticket_type": values["ticket_type"],
        "requested_window_start": values["requested_window_start"],
        "requested_window_end": values["requested_window_end"],
        "scheduled_window_start": None,
        "scheduled_window_end": None,
        "labor_hours_estimate": values["labor_hours_estimate"],
        "actual_labor_hours": None,
        "expedite_requested": values["expedite_requested"],
        "estimated_billed_cents": None,
        "final_billed_cents": None,
        "new_identifier": values["new_identifier"],
        "ticket_state": "SUBMITTED",
        "rework_count": 0,
    })
    db.tickets[ticket["id"]] = ticket
    return created(serial.public(ticket))


@mac_bp.route("/cabling/mac-tickets/<ticket_id>", methods=["GET"])
@require(*READ_ROLES)
def read_ticket(ticket_id):
    return ok(serial.public(lookup.ticket(ticket_id)))


@mac_bp.route("/cabling/mac-tickets", methods=["GET"])
@require(*READ_ROLES)
def list_tickets():
    project_id = request.args.get("project_id")
    link_id = request.args.get("link_id")
    telecom_room_id = request.args.get("telecom_room_id")
    ticket_state = enum_filter(request.args, "ticket_state", TICKET_STATES)
    ticket_type = enum_filter(request.args, "ticket_type", TICKET_TYPES)
    rows = []
    for ticket in db.tickets.values():
        if project_id is not None and ticket["project_id"] != project_id:
            continue
        if link_id is not None and ticket["link_id"] != link_id:
            continue
        if (telecom_room_id is not None
                and ticket["telecom_room_id"] != telecom_room_id):
            continue
        if ticket_state is not None and ticket["ticket_state"] != ticket_state:
            continue
        if ticket_type is not None and ticket["ticket_type"] != ticket_type:
            continue
        rows.append(ticket)
    return paginate(rows, request.args, serial.public)


@mac_bp.route("/cabling/mac-tickets/<ticket_id>/schedule", methods=["POST"])
@require(PROJECT_MANAGER)
def schedule_ticket(ticket_id):
    values = body([
        Field("scheduled_window_start", "datetime"),
        Field("scheduled_window_end", "datetime"),
    ])
    require_window(values, "scheduled_window_start", "scheduled_window_end")
    ticket = lookup.ticket(ticket_id)
    if ticket["ticket_state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_TICKET_STATE",
                       "Only a SUBMITTED ticket can be scheduled.")
    start = values["scheduled_window_start"]
    end = values["scheduled_window_end"]
    if _room_window_conflict(ticket, start, end):
        raise ApiError("ERR_ROOM_WINDOW_CONFLICT",
                       "The room already hosts two crews across that window.")
    project = db.projects[ticket["project_id"]]
    estimate = calc.mac_billing(ticket["labor_hours_estimate"],
                                ticket["expedite_requested"])
    if project["consumed_mac_cents"] + estimate > project["mac_budget_cents"]:
        raise ApiError("ERR_MAC_BUDGET_EXCEEDED",
                       "The moves-adds-changes budget cannot absorb this estimate.")
    ticket["ticket_state"] = "SCHEDULED"
    ticket["scheduled_window_start"] = start
    ticket["scheduled_window_end"] = end
    ticket["estimated_billed_cents"] = estimate
    touch(ticket)
    rollups.recompute_consumed_mac_cents(project)
    touch(project)
    return ok(serial.public(ticket))


@mac_bp.route("/cabling/mac-tickets/<ticket_id>/reject", methods=["POST"])
@require(PROJECT_MANAGER)
def reject_ticket(ticket_id):
    no_body()
    ticket = lookup.ticket(ticket_id)
    if ticket["ticket_state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_TICKET_STATE",
                       "Only a SUBMITTED ticket can be rejected.")
    ticket["ticket_state"] = "REJECTED"
    touch(ticket)
    return ok(serial.public(ticket))


@mac_bp.route("/cabling/mac-tickets/<ticket_id>/start", methods=["POST"])
@require(INSTALLER)
def start_ticket(ticket_id):
    no_body()
    ticket = lookup.ticket(ticket_id)
    if ticket["ticket_state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TICKET_STATE",
                       "Only a SCHEDULED ticket can be started.")
    clock = store.now()
    if not (clock >= ticket["scheduled_window_start"]
            and clock < ticket["scheduled_window_end"]):
        raise ApiError("ERR_TICKET_WINDOW_NOT_OPEN",
                       "The site clock is outside the ticket's scheduled window.")
    ticket["ticket_state"] = "IN_PROGRESS"
    touch(ticket)
    return ok(serial.public(ticket))


@mac_bp.route("/cabling/mac-tickets/<ticket_id>/rework", methods=["POST"])
@require(PROJECT_MANAGER)
def rework_ticket(ticket_id):
    no_body()
    ticket = lookup.ticket(ticket_id)
    if ticket["ticket_state"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_TICKET_STATE",
                       "Only an IN_PROGRESS ticket can be sent back for rework.")
    ticket["ticket_state"] = "SUBMITTED"
    ticket["scheduled_window_start"] = None
    ticket["scheduled_window_end"] = None
    ticket["estimated_billed_cents"] = None
    ticket["rework_count"] += 1
    touch(ticket)
    project = db.projects[ticket["project_id"]]
    rollups.recompute_consumed_mac_cents(project)
    touch(project)
    return ok(serial.public(ticket))


@mac_bp.route("/cabling/mac-tickets/<ticket_id>/complete", methods=["POST"])
@require(INSTALLER)
def complete_ticket(ticket_id):
    values = body([
        Field("actual_labor_hours", "number", exclusive_min=0),
        Field("new_identifier", "string", required=False, default=None, nullable=True),
    ])
    ticket = lookup.ticket(ticket_id)
    if ticket["ticket_state"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_TICKET_STATE",
                       "Only an IN_PROGRESS ticket can be completed.")
    project = db.projects[ticket["project_id"]]
    link = db.links.get(ticket["link_id"])
    supplied = values["new_identifier"] if "new_identifier" in values["_present"] \
        else None
    new_identifier = supplied if supplied is not None else ticket["new_identifier"]
    renames = ticket["ticket_type"] == "CHANGE" and new_identifier is not None
    if renames:
        identifiers.screen_identifier(project, new_identifier,
                                     exclude_link_id=ticket["link_id"])

    # ---- Cascade C hop 1: the ticket closes and the money is reconciled.
    ticket["ticket_state"] = "COMPLETED"
    ticket["actual_labor_hours"] = values["actual_labor_hours"]
    if supplied is not None:
        ticket["new_identifier"] = supplied
    ticket["final_billed_cents"] = calc.mac_billing(values["actual_labor_hours"],
                                                    ticket["expedite_requested"])
    touch(ticket)
    rollups.recompute_consumed_mac_cents(project)
    touch(project)

    if renames and link is not None:
        # ---- Hop 2, caused by hop 1: the rename voids label, record and sign-off.
        link["identifier"] = new_identifier
        link["applied_identifier"] = None
        link["record_state"] = "UNLABELED"
        if link["install_state"] == "CERTIFIED":
            link["install_state"] = "TERMINATED"
            link["certifier_user_id"] = None
        touch(link)
        # ---- Hop 3, caused by hop 2: the project roll-ups are recomputed.
        rollups.recompute_project_rollups(project)
        # ---- Hop 4, caused by hop 3: the warranty consequence, revocation included.
        rollups.apply_warranty_consequence(project, allow_revoke=True)
    return ok(serial.public(ticket))
