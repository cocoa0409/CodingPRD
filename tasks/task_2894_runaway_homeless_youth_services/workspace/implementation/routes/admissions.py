"""Emergency shelter admission, extension, discharge and notification listing."""

from flask import Blueprint, request

import authz
import calc
import cascade
import envelope
import find
import serial
import shape
import store
from errors import fail

bp = Blueprint("admissions", __name__)

ADMISSION_STATUSES = (
    "PENDING_SCREENING",
    "WAITLISTED",
    "ACTIVE",
    "EXTENDED",
    "DISCHARGE_SCHEDULED",
    "DISCHARGED",
    "DENIED",
)
EXIT_DESTINATIONS = (
    "FAMILY_REUNIFIED",
    "TRANSITIONAL_LIVING",
    "INDEPENDENT_HOUSING",
    "OTHER_SHELTER",
    "UNKNOWN",
)
NOTIFICATION_STATUSES = (
    "PENDING",
    "ATTEMPTED",
    "CONTACTED",
    "WAIVED",
    "OVERDUE",
    "LAW_ENFORCEMENT_REPORTED",
)


def _occupancy_interval(admission):
    """PRD 3.3: the existing admission's interval runs from admitted_at - falling back
    to requested_at - up to but not including discharged_at, falling back to
    planned_discharge_at."""
    start = admission["admitted_at"] or admission["requested_at"]
    end = admission["discharged_at"] or admission["planned_discharge_at"]
    return start, end


@bp.post("/ryhs/admissions")
def request_admission():
    user_id, _role = authz.require(authz.SHELTER_CASE_MANAGER)
    body = shape.body()
    # Ladder 5: body foreign keys resolve in declaration order - youth_id then program_id.
    youth = shape.fk_lookup(body, "youth_id", store.youths, "ERR_YOUTH_NOT_FOUND")
    program = shape.fk_lookup(body, "program_id", store.programs, "ERR_PROGRAM_NOT_FOUND")
    # Ladder 6.
    shape.need_str(body, "youth_id", 1, 200)
    shape.need_str(body, "program_id", 1, 200)
    planned_discharge_at = shape.need_instant(body, "planned_discharge_at")
    # PRD 3.3: waitlist_opt_out "when omitted it behaves as false".
    opt_out = shape.opt_bool(body, "waitlist_opt_out", False)
    clock = store.now()

    # Ladder 11: no other admission of this youth at the same program holds a bed.
    for other in store.admissions.values():
        if (
            other["youth_id"] == youth["id"]
            and other["program_id"] == program["id"]
            and other["status"] in calc.BED_HOLDING_ADMISSION_STATUSES
        ):
            fail("ERR_YOUTH_ALREADY_SHELTERED")

    # Ladder 19: the youth's most recent screening is not ESCALATED.
    latest = calc.latest_screening(youth["id"])
    if latest is not None and latest["status"] == "ESCALATED":
        fail("ERR_SCREENING_ESCALATED_BLOCKS_ACTION")

    # Ladder 25: the youth's age lies inside the licensed band, both bounds inclusive.
    age = calc.age_years(youth, clock)
    if age < program["min_age_years"] or age > program["max_age_years"]:
        fail("ERR_AGE_OUTSIDE_PROGRAM_BAND")

    # Ladder 26.
    if program["program_type"] != "EMERGENCY_SHELTER":
        fail("ERR_PROGRAM_TYPE_MISMATCH")

    # Ladder 27: half-open intervals with a zero buffer, so exact adjacency is legal.
    for other in store.admissions.values():
        if other["youth_id"] != youth["id"]:
            continue
        if other["status"] not in calc.NON_TERMINAL_ADMISSION_STATUSES:
            continue
        other_start, other_end = _occupancy_interval(other)
        if other_start is None or other_end is None:
            continue
        if clock < other_end and other_start < planned_discharge_at:
            fail("ERR_ADMISSION_OVERLAP")

    # Ladder 32.
    if not planned_discharge_at > clock:
        fail("ERR_INVALID_INTERVAL", "planned_discharge_at must be later than the current clock")

    # The priority score is frozen from the youth as it stands at request time.
    priority_score = calc.priority_score(youth, clock)

    # Ladder 42.
    if program["posture"] == "RESTRICTED" and priority_score < calc.RESTRICTED_PRIORITY_FLOOR:
        fail("ERR_PROGRAM_RESTRICTED_PRIORITY")

    # Ladder 43: waitlisting was opted out of against a FROZEN program.
    if program["posture"] == "FROZEN" and opt_out:
        fail("ERR_BED_CAPACITY_EXCEEDED")

    record = {
        "youth_id": youth["id"],
        "program_id": program["id"],
        "status": "PENDING_SCREENING",
        "requested_at": clock,
        "admitted_at": None,
        "planned_discharge_at": planned_discharge_at,
        "discharged_at": None,
        "priority_score": priority_score,
        "projected_billable_nights": None,
        "final_billable_nights": None,
        "extension_count": 0,
        "capacity_blocked": False,
        "exit_destination": None,
        "outcome_positive": None,
        "admitting_user_id": user_id,
    }
    store.stamp_new(record)
    store.admissions[record["id"]] = record

    if program["posture"] == "FROZEN":
        # The capacity branch is evaluated before the screening branch.
        record["status"] = "WAITLISTED"
        record["capacity_blocked"] = True
        cascade.refresh_program(program)
    elif latest is not None and latest["status"] == "CLEARED":
        # The five-record ACTIVE cascade. The admission row is brand new, so it stays
        # at version 1.
        cascade.activate_admission(record, clock)
    return envelope.created(serial.admission(record))


@bp.get("/ryhs/admissions")
def list_admissions():
    authz.require(
        authz.PROGRAM_ADMIN,
        authz.SHELTER_CASE_MANAGER,
        authz.REUNIFICATION_SPECIALIST,
        authz.TLP_COORDINATOR,
    )
    youth_id = request.args.get("youth_id")
    program_id = request.args.get("program_id")
    status = envelope.enum_filter("status", ADMISSION_STATUSES)
    rows = list(store.admissions.values())
    if youth_id is not None:
        rows = [r for r in rows if r["youth_id"] == youth_id]
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.listing(store.ordered(rows), serial.admission)


@bp.get("/ryhs/admissions/<admission_id>")
def read_admission(admission_id):
    authz.require(
        authz.PROGRAM_ADMIN,
        authz.SHELTER_CASE_MANAGER,
        authz.REUNIFICATION_SPECIALIST,
        authz.TLP_COORDINATOR,
    )
    return envelope.ok(serial.admission(find.admission(admission_id)))


def _operable(admission, allowed):
    """Ladder 9 then 10 - the two codes never shadow one another because rule 9 is
    scoped to the five non-terminal statuses only."""
    if admission["status"] in calc.NON_TERMINAL_ADMISSION_STATUSES:
        if admission["status"] not in allowed:
            fail("ERR_ADMISSION_NOT_ACTIVE")
        return
    fail("ERR_ADMISSION_ALREADY_TERMINAL")


@bp.post("/ryhs/admissions/<admission_id>/extend")
def extend(admission_id):
    authz.require(authz.SHELTER_CASE_MANAGER)
    admission = find.admission(admission_id)
    body = shape.body()
    new_planned = shape.need_instant(body, "new_planned_discharge_at")
    _operable(admission, ("ACTIVE", "EXTENDED"))

    # PRD 3.5: "on the first extension, the youth must have no guardian notification
    # standing OVERDUE"; the runaway report is what discharges that obligation.
    if admission["extension_count"] == 0:
        for notification in calc.youth_notifications(admission["youth_id"]):
            if notification["status"] == "OVERDUE":
                fail("ERR_RUNAWAY_REPORT_REQUIRED")

    # Ladder 32: strictly later than the current planned discharge instant.
    if not new_planned > admission["planned_discharge_at"]:
        fail(
            "ERR_INVALID_INTERVAL",
            "new_planned_discharge_at must be later than the current planned_discharge_at",
        )

    program = store.programs[admission["program_id"]]
    projected = calc.projected_billable_nights(admission["admitted_at"], new_planned)
    # Ladder 34: a figure exactly equal to the ceiling is allowed.
    if projected > program["max_stay_nights"]:
        fail("ERR_MAX_STAY_EXCEEDED")
    # Ladder 35.
    if admission["extension_count"] >= calc.MAX_EXTENSIONS:
        fail("ERR_MAX_EXTENSIONS_REACHED")

    admission["planned_discharge_at"] = new_planned
    admission["extension_count"] += 1
    admission["projected_billable_nights"] = projected
    admission["status"] = "EXTENDED"
    store.touch(admission)
    return envelope.ok(serial.admission(admission))


@bp.post("/ryhs/admissions/<admission_id>/discharge")
def discharge(admission_id):
    authz.require(authz.SHELTER_CASE_MANAGER)
    admission = find.admission(admission_id)
    body = shape.body()
    exit_destination = shape.need_enum(body, "exit_destination", EXIT_DESTINATIONS)
    _operable(admission, ("ACTIVE", "EXTENDED", "DISCHARGE_SCHEDULED"))

    # Ladder 21: an OVERDUE obligation with no runaway report on file blocks discharge.
    for notification in cascade.admission_notifications(admission["id"]):
        if (
            notification["status"] == "OVERDUE"
            and notification["runaway_report_filed_at"] is None
        ):
            fail("ERR_RUNAWAY_REPORT_REQUIRED")

    cascade.discharge_admission(admission, exit_destination)
    return envelope.ok(serial.admission(admission))


@bp.get("/ryhs/admissions/<admission_id>/guardian-notifications")
def list_notifications(admission_id):
    authz.require(
        authz.PROGRAM_ADMIN, authz.SHELTER_CASE_MANAGER, authz.REUNIFICATION_SPECIALIST
    )
    admission = find.admission(admission_id)
    status = envelope.enum_filter("status", NOTIFICATION_STATUSES)
    rows = cascade.admission_notifications(admission["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.listing(rows, serial.notification)
