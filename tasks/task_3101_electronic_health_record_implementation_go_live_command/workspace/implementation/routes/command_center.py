"""Command-center tickets, staffing shifts and optimization backlog (PRD §4.8)."""

from datetime import timedelta, timezone

from flask import Blueprint

from db import (
    DB,
    EPOCH_CAPACITY_POINTS,
    HANDOFF_BUFFER_MINUTES,
    add_minutes,
    parse_iso,
)
from errors import (
    ERR_DEFECT_NOT_FOUND,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PRIMARY_FACILITY_MISMATCH,
    ERR_RELEASE_CAPACITY_EXCEEDED,
    ERR_SHIFT_OVERLAP,
    ERR_STAFF_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_TICKET_NOT_FOUND,
    fail,
)
from request_utils import (
    actor,
    body_fields,
    collection,
    enum_member,
    filter_args,
    pagination,
    payload,
    require_role,
)
from response import ok
from services import calculations as C
from services import lookups as L
from services import recompute as R
from services.core import serialize, stamp_created

bp = Blueprint("command_center", __name__)

TICKET_READ_ROLES = ["CommandCenterLead", "TriageCommander", "ImplementationAnalyst"]
SHIFT_MANAGE_ROLES = ["CommandCenterLead"]
SHIFT_READ_ROLES = ["CommandCenterLead", "ImplementationAnalyst"]
OPTIMIZATION_ROLES = ["OptimizationLead"]
OPTIMIZATION_READ = ["OptimizationLead", "ImplementationAnalyst"]

SEVERITIES = {"SEV1", "SEV2", "SEV3", "SEV4"}
SUPPORT_ROLES = {
    "AT_THE_ELBOW",
    "TRIAGE_COMMANDER",
    "APPLICATION_ANALYST",
    "CHARGE_CAPTURE_SPECIALIST",
}


def ticket_view(ticket):
    return serialize("CommandCenterTicket", ticket)


def shift_view(shift):
    return serialize("StaffingShift", shift)


def item_view(item):
    return serialize("OptimizationBacklogItem", item)


# --------------------------------------------------------------------------
# CommandCenterTicket
# --------------------------------------------------------------------------
@bp.route("/command-center-tickets", methods=["POST"])
def create_ticket():
    uid, role = actor()
    require_role(role, ["CommandCenterLead", "TriageCommander"])
    data = body_fields(
        [
            ("facility_id", "string", True),
            ("department_id", "string", False),
            ("target_ref", "string", True),
            ("severity", "enum", True),
            ("at_the_elbow_zone", "string", True),
            ("linked_test_defect_id", "string", False),
        ],
        payload(),
    )
    enum_member("severity", data["severity"], SEVERITIES)
    facility = DB.facilities.get(data["facility_id"])
    if facility is None:
        fail(ERR_FACILITY_NOT_FOUND, "No facility matches the facility_id.")
    if data["department_id"]:
        department = DB.departments.get(data["department_id"])
        if department is None:
            fail(ERR_DEPARTMENT_NOT_FOUND, "No department matches the department_id.")
    if DB.resolve_ref(data["target_ref"]) is None:
        fail(
            ERR_DEPARTMENT_NOT_FOUND,
            "The polymorphic target_ref does not resolve to a Department, Facility or InterfaceChannel.",
        )
    if data["linked_test_defect_id"]:
        if data["linked_test_defect_id"] not in DB.test_defects:
            fail(ERR_DEFECT_NOT_FOUND, "No test defect matches the linked_test_defect_id.")
    coverage = _coverage_count(facility["id"])
    sla = C.command_center_sla(data["severity"], data["at_the_elbow_zone"], coverage)
    ticket = {
        "id": DB.new_id(),
        "ehr_implementation_id": facility["ehr_implementation_id"],
        "facility_id": facility["id"],
        "department_id": data["department_id"],
        "target_ref": data["target_ref"],
        "severity": data["severity"],
        "at_the_elbow_zone": data["at_the_elbow_zone"],
        "linked_test_defect_id": data["linked_test_defect_id"],
        "reported_utc": DB.clock.get(),
        "resolution_sla_minutes": int(sla),
        "triage_state": "REPORTED",
    }
    stamp_created(ticket)
    DB.command_center_tickets[ticket["id"]] = ticket
    DB.register_created(ticket)
    return ok(ticket_view(ticket), status=201)


def _coverage_count(facility_id):
    clock = DB.clock.get()
    count = 0
    for shift in DB.staffing_shifts.values():
        if shift["facility_id"] != facility_id:
            continue
        if shift["support_role"] != "AT_THE_ELBOW":
            continue
        if shift["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if shift["end_utc"] > clock:
            count += 1
    return count


@bp.route("/command-center-tickets", methods=["GET"])
def list_tickets():
    uid, role = actor()
    require_role(role, TICKET_READ_ROLES)
    rows = list(DB.command_center_tickets.values())
    filters = filter_args(
        [
            "ehr_implementation_id",
            "facility_id",
            "department_id",
            "linked_test_defect_id",
            "severity",
            "triage_state",
        ]
    )
    for key, value in filters.items():
        rows = [t for t in rows if t.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([ticket_view(t) for t in window], pagination=page)


@bp.route("/command-center-tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    uid, role = actor()
    require_role(role, TICKET_READ_ROLES)
    ticket = DB.command_center_tickets.get(ticket_id)
    if ticket is None:
        fail(ERR_TICKET_NOT_FOUND, "No command-center ticket matches the id.")
    return ok(ticket_view(ticket))


def _ticket_transition(ticket_id, allowed_from, mutate):
    uid, role = actor()
    require_role(role, ["TriageCommander"])
    ticket = DB.command_center_tickets.get(ticket_id)
    if ticket is None:
        fail(ERR_TICKET_NOT_FOUND, "No command-center ticket matches the id.")
    R.recompute_program_tree(ticket["ehr_implementation_id"])
    if ticket["triage_state"] not in allowed_from:
        fail(
            ERR_INVALID_STATE,
            "The ticket is in triage state %s; this operation requires %s."
            % (ticket["triage_state"], " or ".join(allowed_from)),
        )
    mutate(uid, ticket)
    DB.touch(ticket, common=True)
    R.recompute_program_tree(ticket["ehr_implementation_id"])
    return ok(ticket_view(ticket))


@bp.route("/command-center-tickets/<ticket_id>/triage", methods=["POST"])
def triage_ticket(ticket_id):
    def mutate(uid, ticket):
        ticket["triage_state"] = "TRIAGED"
        linked = ticket.get("linked_test_defect_id")
        if linked and linked in DB.test_defects:
            defect = DB.test_defects[linked]
            if defect["blocks_go_live"]:
                defect["status"] = "REOPENED"
                DB.touch(defect, common=True)

    return _ticket_transition(ticket_id, ["REPORTED"], mutate)


@bp.route("/command-center-tickets/<ticket_id>/begin-resolution", methods=["POST"])
def begin_ticket_resolution(ticket_id):
    def mutate(uid, ticket):
        ticket["triage_state"] = "IN_RESOLUTION"

    return _ticket_transition(ticket_id, ["TRIAGED"], mutate)


@bp.route("/command-center-tickets/<ticket_id>/resolve", methods=["POST"])
def resolve_ticket(ticket_id):
    def mutate(uid, ticket):
        ticket["triage_state"] = "RESOLVED"

    return _ticket_transition(ticket_id, ["IN_RESOLUTION", "ESCALATED"], mutate)


# --------------------------------------------------------------------------
# StaffingShift
# --------------------------------------------------------------------------
@bp.route("/staffing-shifts", methods=["POST"])
def create_shift():
    uid, role = actor()
    require_role(role, SHIFT_MANAGE_ROLES)
    data = body_fields(
        [
            ("staff_id", "string", True),
            ("facility_id", "string", True),
            ("support_role", "enum", True),
            ("start_utc", "datetime", True),
            ("end_utc", "datetime", True),
        ],
        payload(),
    )
    enum_member("support_role", data["support_role"], SUPPORT_ROLES)
    staff = DB.staffs.get(data["staff_id"])
    if staff is None:
        fail(ERR_STAFF_NOT_FOUND, "No staff member matches the staff_id.")
    facility = DB.facilities.get(data["facility_id"])
    if facility is None:
        fail(ERR_FACILITY_NOT_FOUND, "No facility matches the facility_id.")
    start = parse_iso(data["start_utc"])
    end = parse_iso(data["end_utc"])
    if end <= start:
        fail(ERR_INVALID_REQUEST, "end_utc must be later than start_utc.")
    if staff["primary_facility_id"] != facility["id"]:
        fail(
            ERR_PRIMARY_FACILITY_MISMATCH,
            "The staff member's primary facility does not match the shift facility.",
        )
    for existing in DB.staffing_shifts.values():
        if existing["status"] in ("COMPLETED", "NO_SHOW", "REASSIGNED"):
            continue
        if existing["staff_id"] == staff["id"] and _overlaps(
            start, end, existing["start_utc"], existing["end_utc"]
        ):
            fail(ERR_SHIFT_OVERLAP, "The shift overlaps another shift of the same staff member.")
        if (
            existing["facility_id"] == facility["id"]
            and existing["support_role"] == "AT_THE_ELBOW"
            and data["support_role"] == "AT_THE_ELBOW"
            and _overlaps(start, end, existing["start_utc"], existing["end_utc"])
        ):
            fail(
                ERR_SHIFT_OVERLAP,
                "The shift overlaps another AT_THE_ELBOW shift at the same facility.",
            )
    shift = {
        "id": DB.new_id(),
        "ehr_implementation_id": facility["ehr_implementation_id"],
        "staff_id": staff["id"],
        "facility_id": facility["id"],
        "support_role": data["support_role"],
        "start_utc": start,
        "end_utc": end,
        "handoff_buffer_minutes": HANDOFF_BUFFER_MINUTES,
        "status": "SCHEDULED",
    }
    stamp_created(shift)
    DB.staffing_shifts[shift["id"]] = shift
    DB.register_created(shift)
    return ok(shift_view(shift), status=201)


def _overlaps(start, end, other_start, other_end):
    return start < other_end and other_start < end


@bp.route("/staffing-shifts", methods=["GET"])
def list_shifts():
    uid, role = actor()
    require_role(role, SHIFT_READ_ROLES)
    rows = list(DB.staffing_shifts.values())
    filters = filter_args(
        ["ehr_implementation_id", "staff_id", "facility_id", "support_role", "status"]
    )
    for key, value in filters.items():
        rows = [s for s in rows if s.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([shift_view(s) for s in window], pagination=page)


@bp.route("/staffing-shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    uid, role = actor()
    require_role(role, SHIFT_READ_ROLES)
    shift = DB.staffing_shifts.get(shift_id)
    if shift is None:
        fail(ERR_INVALID_REQUEST, "No staffing shift matches the id.")
    return ok(shift_view(shift))


def _shift_transition(shift_id, allowed_from, mutate):
    uid, role = actor()
    require_role(role, SHIFT_MANAGE_ROLES)
    shift = DB.staffing_shifts.get(shift_id)
    if shift is None:
        fail(ERR_INVALID_REQUEST, "No staffing shift matches the id.")
    R.recompute_program_tree(shift["ehr_implementation_id"])
    if shift["status"] not in allowed_from:
        fail(
            ERR_INVALID_STATE,
            "The shift is in status %s; this operation requires %s."
            % (shift["status"], " or ".join(allowed_from)),
        )
    mutate(uid, shift)
    DB.touch(shift, common=True)
    R.recompute_program_tree(shift["ehr_implementation_id"])
    return ok(shift_view(shift))


@bp.route("/staffing-shifts/<shift_id>/activate", methods=["POST"])
def activate_shift(shift_id):
    def mutate(uid, shift):
        if DB.clock.get() < shift["start_utc"]:
            fail(ERR_INVALID_STATE, "The shift may not activate before its start instant.")
        staff = DB.staffs.get(shift["staff_id"])
        if staff is None or staff["status"] != "CREDENTIALED":
            fail(
                ERR_INVALID_STATE,
                "The assigned staff member must hold CREDENTIALED status.",
            )
        shift["status"] = "ACTIVE"

    return _shift_transition(shift_id, ["SCHEDULED"], mutate)


@bp.route("/staffing-shifts/<shift_id>/complete", methods=["POST"])
def complete_shift(shift_id):
    def mutate(uid, shift):
        shift["status"] = "COMPLETED"

    return _shift_transition(shift_id, ["ACTIVE"], mutate)


@bp.route("/staffing-shifts/<shift_id>/reassign", methods=["POST"])
def reassign_shift(shift_id):
    def mutate(uid, shift):
        if DB.clock.get() >= shift["start_utc"]:
            fail(ERR_INVALID_STATE, "A shift may only be reassigned before it starts.")
        shift["status"] = "REASSIGNED"

    return _shift_transition(shift_id, ["SCHEDULED"], mutate)


# --------------------------------------------------------------------------
# OptimizationBacklogItem
# --------------------------------------------------------------------------
@bp.route("/optimization-backlog-items", methods=["POST"])
def create_optimization_item():
    uid, role = actor()
    require_role(role, OPTIMIZATION_ROLES)
    data = body_fields(
        [
            ("department_id", "string", True),
            ("title", "string", True),
            ("effort_points", "int", True),
            ("expected_ehr_implementation_version", "int", True),
        ],
        payload(),
    )
    department = DB.departments.get(data["department_id"])
    if department is None:
        fail(ERR_DEPARTMENT_NOT_FOUND, "No department matches the department_id.")
    program = DB.ehr_implementations[department["ehr_implementation_id"]]
    if data["expected_ehr_implementation_version"] != int(program["version"]):
        fail(
            ERR_STALE_VERSION,
            "expected_ehr_implementation_version does not match the program's current version.",
        )
    if data["effort_points"] <= 0:
        fail(ERR_INVALID_REQUEST, "effort_points must be a positive integer.")
    item = {
        "id": DB.new_id(),
        "department_id": department["id"],
        "ehr_implementation_id": program["id"],
        "title": data["title"],
        "effort_points": data["effort_points"],
        "requested_epoch": program["current_epoch_index"],
        "scheduled_epoch": None,
        "status": "NEW",
    }
    stamp_created(item)
    DB.optimization_backlog_items[item["id"]] = item
    DB.register_created(item)
    program["version"] = int(program["version"]) + 1
    program["updated_at"] = item["created_at"]
    return ok(item_view(item), status=201)


@bp.route("/optimization-backlog-items", methods=["GET"])
def list_optimization_items():
    uid, role = actor()
    require_role(role, OPTIMIZATION_READ)
    rows = list(DB.optimization_backlog_items.values())
    filters = filter_args(["department_id", "ehr_implementation_id", "status"])
    for key, value in filters.items():
        rows = [i for i in rows if i.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([item_view(i) for i in window], pagination=page)


@bp.route("/optimization-backlog-items/<item_id>", methods=["GET"])
def get_optimization_item(item_id):
    uid, role = actor()
    require_role(role, OPTIMIZATION_READ)
    item = DB.optimization_backlog_items.get(item_id)
    if item is None:
        fail(ERR_INVALID_REQUEST, "No optimization backlog item matches the id.")
    return ok(item_view(item))


def _optimization_transition(item_id, allowed_from, mutate):
    uid, role = actor()
    require_role(role, OPTIMIZATION_ROLES)
    item = DB.optimization_backlog_items.get(item_id)
    if item is None:
        fail(ERR_INVALID_REQUEST, "No optimization backlog item matches the id.")
    if item["status"] not in allowed_from:
        fail(
            ERR_INVALID_STATE,
            "The optimization item is in status %s; this operation requires %s."
            % (item["status"], " or ".join(allowed_from)),
        )
    mutate(uid, item)
    DB.touch(item, common=True)
    return ok(item_view(item))


@bp.route("/optimization-backlog-items/<item_id>/triage", methods=["POST"])
def triage_optimization_item(item_id):
    def mutate(uid, item):
        item["status"] = "TRIAGED"

    return _optimization_transition(item_id, ["NEW"], mutate)


@bp.route("/optimization-backlog-items/<item_id>/schedule", methods=["POST"])
def schedule_optimization_item(item_id):
    uid, role = actor()
    require_role(role, OPTIMIZATION_ROLES)
    item = DB.optimization_backlog_items.get(item_id)
    if item is None:
        fail(ERR_INVALID_REQUEST, "No optimization backlog item matches the id.")
    data = body_fields([("target_epoch", "int", True)], payload())
    if item["status"] != "TRIAGED":
        fail(ERR_INVALID_STATE, "Scheduling requires the item to be TRIAGED.")
    if int(item["effort_points"]) > EPOCH_CAPACITY_POINTS:
        fail(
            ERR_RELEASE_CAPACITY_EXCEEDED,
            "The item exceeds a whole epoch's release capacity and can never be scheduled.",
        )
    siblings = [
        i
        for i in DB.optimization_backlog_items.values()
        if i["ehr_implementation_id"] == item["ehr_implementation_id"]
    ]
    item["scheduled_epoch"] = C.allocate_scheduled_epoch(
        item, data["target_epoch"], siblings
    )
    item["status"] = "SCHEDULED"
    DB.touch(item, common=True)
    return ok(item_view(item))


@bp.route("/optimization-backlog-items/<item_id>/start", methods=["POST"])
def start_optimization_item(item_id):
    def mutate(uid, item):
        item["status"] = "IN_PROGRESS"

    return _optimization_transition(item_id, ["SCHEDULED"], mutate)


@bp.route("/optimization-backlog-items/<item_id>/release", methods=["POST"])
def release_optimization_item(item_id):
    def mutate(uid, item):
        program = DB.ehr_implementations[item["ehr_implementation_id"]]
        if program["current_epoch_index"] < int(item["scheduled_epoch"] or 0):
            fail(
                ERR_INVALID_STATE,
                "The program epoch has not yet reached the item's scheduled epoch.",
            )
        item["status"] = "RELEASED"

    return _optimization_transition(item_id, ["IN_PROGRESS"], mutate)


@bp.route("/optimization-backlog-items/<item_id>/reject", methods=["POST"])
def reject_optimization_item(item_id):
    def mutate(uid, item):
        item["status"] = "REJECTED"

    return _optimization_transition(item_id, ["TRIAGED"], mutate)