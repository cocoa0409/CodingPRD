"""Shifts, staffing, escalation, EVV, assignments and timesheets."""
from flask import Blueprint

import auth as authmod
import cascade
import derive
import envelope
import lookup
import serialize
import store
import validate
from errors import fail
from store import db, new_row
from timeutil import add_minutes, week_window, whole_minutes

bp = Blueprint("shifts", __name__)

STAFFING_STATUSES = (
    "OPEN", "ASSIGNED", "ESCALATED", "PARENT_BACKUP", "COMPLETED", "CANCELLED",
)
EVV_STATUSES = ("NOT_STARTED", "CLOCKED_IN", "VERIFIED", "EXCEPTION")
ASSIGNMENT_STATUSES = ("ACTIVE", "CANCELLED", "COMPLETED")
EVV_METHODS = ("GPS", "IVR", "MANUAL")
TIMESHEET_STATUSES = (
    "CAPTURED", "EDITED", "SUBMITTED", "BILL_ACCEPTED", "BILL_REJECTED", "VOIDED",
)
BILLING_DECISIONS = ("ACCEPT", "REJECT")
ASSIGNABLE_STAFFING = ("OPEN", "ESCALATED", "ASSIGNED")


def _case_of_shift(shift):
    return db.cases.get(shift["case_id"])


def _guard_case_open(case):
    """PRD 2.8 check 10 -- the governing case is neither ON_HOLD nor CLOSED."""
    if case is not None and case["status"] in ("ON_HOLD", "CLOSED"):
        fail("ERR_CASE_ON_HOLD", "The governing case is not open for staffing activity.")


def _guard_auth_staffable(case):
    """PRD 2.8 check 11."""
    auth = db.authorizations.get(case["authorization_id"]) if case is not None else None
    if auth is None or auth["status"] not in derive.STAFFABLE_AUTH_STATUS:
        fail("ERR_AUTHORIZATION_NOT_ACTIVE", "The authorization is not open for staffing.")
    return auth


# --------------------------------------------------------------------------- #
# 47-49. publishing and reading shifts
# --------------------------------------------------------------------------- #
@bp.route("/shifts", methods=["POST"])
def create_shift():
    authmod.require("Scheduler")
    data = validate.body()
    case = lookup.get_case(validate.req_fk(data, "case_id"))
    start_at = validate.req_instant(data, "start_at")
    end_at = validate.req_instant(data, "end_at")
    required_skills = validate.req_skills(data, "required_skills")
    if not end_at > start_at:
        validate.bad("Field 'end_at' must be strictly after 'start_at'.")
    _guard_case_open(case)
    authorization = _guard_auth_staffable(case)
    patient = db.patients.get(case["patient_id"])
    if patient is not None and patient["status"] == "HOSPITALIZED":
        fail("ERR_PATIENT_HOSPITALIZED", "The patient is hospitalized.")
    if start_at < authorization["effective_start"] or end_at > authorization["effective_end"]:
        fail("ERR_SHIFT_OUTSIDE_AUTH_WINDOW",
             "The shift does not sit inside the authorization's effective window.")
    row = new_row(
        case_id=case["id"],
        start_at=start_at,
        end_at=end_at,
        required_skills=required_skills,
        scheduled_minutes=whole_minutes(start_at, end_at),
        staffing_status="OPEN",
        evv_status="NOT_STARTED",
        escalation_tier="NONE",
        escalated_at=None,
        cancel_reason="NONE",
    )
    db.shifts[row["id"]] = row
    return cascade.respond(serialize.shift, row, 201)


@bp.route("/shifts/<shift_id>", methods=["GET"])
def read_shift(shift_id):
    authmod.require("Scheduler", "ClinicalSupervisor", "CaseManager", "Nurse")
    return envelope.ok(serialize.shift(lookup.get_shift(shift_id)))


@bp.route("/shifts", methods=["GET"])
def list_shifts():
    authmod.require("Scheduler", "ClinicalSupervisor", "CaseManager")
    limit, offset = validate.pagination()
    case_id = validate.query_value("case_id")
    staffing_status = validate.query_enum("staffing_status", STAFFING_STATUSES)
    evv_status = validate.query_enum("evv_status", EVV_STATUSES)
    start_after = validate.query_instant("start_after")
    rows = store.ordered(db.shifts)
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if staffing_status is not None:
        rows = [r for r in rows if r["staffing_status"] == staffing_status]
    if evv_status is not None:
        rows = [r for r in rows if r["evv_status"] == evv_status]
    if start_after is not None:
        rows = [r for r in rows if r["start_at"] > start_after]
    total = len(rows)
    body = [serialize.shift(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


# --------------------------------------------------------------------------- #
# 50-51. the selector: candidates and automatic staffing
# --------------------------------------------------------------------------- #
@bp.route("/shifts/<shift_id>/staffing-candidates", methods=["GET"])
def staffing_candidates(shift_id):
    authmod.require("Scheduler")
    shift = lookup.get_shift(shift_id)
    case = _case_of_shift(shift)
    pool = derive.candidate_pool(shift, case) if case is not None else []
    ranked = [nurse["id"] for nurse in pool]
    top = derive.match_score(pool[0], shift, case) if pool else 0
    return envelope.ok({
        "shift_id": shift["id"],
        "candidate_count": len(pool),
        "ranked_nurse_ids": ranked,
        "selected_nurse_id": ranked[0] if ranked else None,
        "top_match_score": int(top),
    })


def _assign(shift, case, nurse):
    """Create the assignment row -- shared by manual and automatic staffing."""
    score = derive.match_score(nurse, shift, case)
    incumbent = derive.active_assignment_of_shift(shift["id"])
    if incumbent is not None:
        cascade.cancel_assignment(incumbent, "REPLACED")
    row = new_row(
        shift_id=shift["id"],
        nurse_id=nurse["id"],
        status="ACTIVE",
        continuity_match=(case is not None and case["continuity_nurse_id"] == nurse["id"]),
        match_score_at_assignment=int(score),
        cancel_reason="NONE",
    )
    db.assignments[row["id"]] = row
    shift["staffing_status"] = "ASSIGNED"
    shift["escalation_tier"] = "NONE"
    shift["escalated_at"] = None
    cascade.touch(shift)
    return row


def _guard_assignable(shift, case):
    """The shared state gauntlet of a manual assignment and of auto-staffing."""
    if shift["staffing_status"] not in ASSIGNABLE_STAFFING:
        fail("ERR_INVALID_STATE", "The shift is not open to a staffing decision.")
    if shift["start_at"] < db.clock:
        fail("ERR_INVALID_STATE", "The shift has already started.")
    _guard_case_open(case)
    if case is None or case["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The governing case is not ACTIVE.")
    return _guard_auth_staffable(case)


def _guard_weekly_cap(shift, authorization):
    """PRD 2.8 check 36 -- the payer's authorized weekly hour cap."""
    window = week_window(shift["start_at"])
    committed = derive.committed_minutes(
        authorization["id"], window, exclude_shift_id=shift["id"])
    ceiling = int(derive.dec(authorization["approved_hours_per_week"]) * derive.dec(60))
    if committed + shift["scheduled_minutes"] > ceiling:
        fail("ERR_WEEKLY_HOURS_EXCEEDED",
             "The assignment would push the week past the authorized hours.")


@bp.route("/shifts/<shift_id>/auto-staff", methods=["POST"])
def auto_staff(shift_id):
    authmod.require("Scheduler")
    shift = lookup.get_shift(shift_id)
    data = validate.body()
    expected = validate.req_int(data, "expected_shift_version")
    if expected != int(shift["version"]):
        fail("ERR_STALE_SHIFT_VERSION", "The shift has been modified since it was last read.")
    case = _case_of_shift(shift)
    authorization = _guard_assignable(shift, case)
    if derive.supervisory_status(case) != "CURRENT":
        fail("ERR_SUPERVISORY_VISIT_OVERDUE", "The case's supervisory visit is overdue.")
    pool = derive.candidate_pool(shift, case)
    if not pool:
        fail("ERR_NO_ELIGIBLE_NURSE", "No eligible nurse is available for this shift.")
    _guard_weekly_cap(shift, authorization)
    row = _assign(shift, case, pool[0])
    return cascade.respond(serialize.assignment, row, 201)


# --------------------------------------------------------------------------- #
# 52-53. escalation ladder and parent backup
# --------------------------------------------------------------------------- #
@bp.route("/shifts/<shift_id>/escalate", methods=["POST"])
def escalate_shift(shift_id):
    authmod.require("Scheduler")
    shift = lookup.get_shift(shift_id)
    data = validate.body()
    validate.req_str(data, "escalation_reason")
    if shift["staffing_status"] not in ("OPEN", "ESCALATED"):
        fail("ERR_INVALID_STATE", "Only an unfilled shift may be escalated.")
    if shift["start_at"] < db.clock:
        fail("ERR_INVALID_STATE", "The shift has already started.")
    case = _case_of_shift(shift)
    _guard_case_open(case)
    if case is None or case["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The governing case is not ACTIVE.")
    patient = db.patients.get(case["patient_id"])
    if shift["staffing_status"] == "OPEN":
        shift["staffing_status"] = "ESCALATED"
        shift["escalation_tier"] = "TIER1_AGENCY_POOL"
        shift["escalated_at"] = db.clock
    else:
        if patient is not None and bool(patient["parent_backup_available"]):
            fail("ERR_INVALID_STATE",
                 "Tier two is reachable only by arranging the parent backup.")
        shift["escalation_tier"] = "TIER3_PAYER_NOTIFICATION"
    cascade.touch(shift)
    return cascade.respond(serialize.shift, shift)


@bp.route("/shifts/<shift_id>/parent-backup", methods=["POST"])
def parent_backup(shift_id):
    authmod.require("Scheduler")
    shift = lookup.get_shift(shift_id)
    data = validate.body()
    validate.req_str(data, "arrangement_note")
    if shift["staffing_status"] != "ESCALATED":
        fail("ERR_INVALID_STATE", "Only an ESCALATED shift may be covered by parent backup.")
    if shift["start_at"] < db.clock:
        fail("ERR_INVALID_STATE", "The shift has already started.")
    case = _case_of_shift(shift)
    _guard_case_open(case)
    patient = db.patients.get(case["patient_id"]) if case is not None else None
    if patient is None or not bool(patient["parent_backup_available"]):
        fail("ERR_NO_PARENT_BACKUP", "The family has no parent backup available.")
    shift["staffing_status"] = "PARENT_BACKUP"
    shift["escalation_tier"] = "TIER2_PARENT_BACKUP"
    cascade.touch(shift)
    return cascade.respond(serialize.shift, shift)


# --------------------------------------------------------------------------- #
# 54-55. electronic visit verification
# --------------------------------------------------------------------------- #
@bp.route("/shifts/<shift_id>/clock-in", methods=["POST"])
def clock_in(shift_id):
    uid, role = authmod.require("Nurse")
    shift = lookup.get_shift(shift_id)
    authmod.nurse_owns_shift(role, uid, shift)
    data = validate.body()
    evv_method = validate.req_enum(data, "evv_method", EVV_METHODS)
    geo_verified = validate.opt_bool(data, "geo_verified", default=False)
    if shift["evv_status"] != "NOT_STARTED":
        fail("ERR_INVALID_STATE", "Verification has already started on this shift.")
    if shift["staffing_status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE", "The shift is not staffed with a nurse.")
    case = _case_of_shift(shift)
    _guard_case_open(case)
    if db.clock < add_minutes(shift["start_at"], -derive.EVV_EARLY_WINDOW_MINUTES):
        fail("ERR_CLOCK_IN_TOO_EARLY", "Clock-in is not permitted this far before the shift.")
    assignment = derive.active_assignment_of_shift(shift["id"])
    row = new_row(
        shift_assignment_id=assignment["id"],
        clock_in_at=db.clock,
        clock_out_at=None,
        evv_method=evv_method,
        geo_verified=geo_verified,
        gross_billable_units=0,
        edit_deduction_units=0,
        net_billable_units=0,
        edit_codes=[],
        status="CAPTURED",
        rejection_reason=None,
        edit_reason=None,
        submitted_by_user_id=None,
        _edited=False,
    )
    db.timesheets[row["id"]] = row
    shift["evv_status"] = "CLOCKED_IN"
    cascade.touch(shift)
    derive.recompute_billing(row)
    return cascade.respond(serialize.timesheet, row, 201)


def _open_timesheet_of_assignment(assignment_id):
    rows = derive.timesheets_of_assignment(assignment_id)
    for row in rows:
        if row["clock_out_at"] is None:
            return row
    return rows[-1] if rows else None


@bp.route("/shifts/<shift_id>/clock-out", methods=["POST"])
def clock_out(shift_id):
    uid, role = authmod.require("Nurse")
    shift = lookup.get_shift(shift_id)
    authmod.nurse_owns_shift(role, uid, shift)
    if shift["staffing_status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE", "The shift is not in progress on its staffing axis.")
    if shift["evv_status"] != "CLOCKED_IN":
        fail("ERR_INVALID_STATE", "The nurse has not clocked in on this shift.")
    assignment = derive.active_assignment_of_shift(shift["id"])
    timesheet = _open_timesheet_of_assignment(assignment["id"]) if assignment else None
    if timesheet is None:
        fail("ERR_INVALID_STATE", "No open timesheet exists for this shift.")
    timesheet["clock_out_at"] = db.clock
    # the verification axis is settled before the money is computed: the deduction
    # rule reads the shift's evv_status.
    shift["evv_status"] = "VERIFIED" if derive.evv_verified(timesheet, shift) else "EXCEPTION"
    shift["staffing_status"] = "COMPLETED"
    cascade.touch(shift)
    assignment["status"] = "COMPLETED"
    cascade.touch(assignment)
    derive.recompute_billing(timesheet)
    cascade.touch(timesheet)
    return cascade.respond(serialize.timesheet, timesheet)


# --------------------------------------------------------------------------- #
# 56-60. shift assignments
# --------------------------------------------------------------------------- #
def _guard_nurse_gauntlet(shift, case, nurse):
    """PRD 2.8 checks 15-19, in that exact order."""
    if nurse["id"] in (case.get("excluded_nurse_ids") or []):
        fail("ERR_NURSE_EXCLUDED_FROM_CASE", "The nurse is barred from this case.")
    if nurse["status"] != "ACTIVE":
        fail("ERR_NURSE_NOT_ACTIVE", "The nurse is not ACTIVE.")
    if not nurse["license_expires_on"] > shift["end_at"].date():
        fail("ERR_NURSE_LICENSE_EXPIRED", "The nurse's licence lapses before the shift ends.")
    rows_by_skill = {}
    for skill in shift["required_skills"]:
        matched = [
            c for c in db.competencies.values()
            if c["nurse_id"] == nurse["id"] and c["skill"] == skill
        ]
        if not matched:
            fail("ERR_NURSE_SKILL_MISMATCH",
                 "The nurse holds no competency row for a required skill.")
        rows_by_skill[skill] = matched
    shift_date = shift["start_at"].date()
    for skill, matched in rows_by_skill.items():
        usable = [
            c for c in matched
            if c["status"] == "VALID" and c["expires_on"] > shift_date
        ]
        if not usable:
            fail("ERR_COMPETENCY_EXPIRED",
                 "A required competency is expired, revoked or lapses on the shift's start date.")


@bp.route("/shift-assignments", methods=["POST"])
def create_assignment():
    authmod.require("Scheduler")
    data = validate.body()
    shift = lookup.get_shift(validate.req_fk(data, "shift_id"))
    nurse = lookup.get_nurse(validate.req_fk(data, "nurse_id"))
    expected = validate.req_int(data, "expected_shift_version")
    if expected != int(shift["version"]):
        fail("ERR_STALE_SHIFT_VERSION", "The shift has been modified since it was last read.")
    case = _case_of_shift(shift)
    authorization = _guard_assignable(shift, case)
    _guard_nurse_gauntlet(shift, case, nurse)
    if derive.supervisory_status(case) != "CURRENT":
        fail("ERR_SUPERVISORY_VISIT_OVERDUE", "The case's supervisory visit is overdue.")
    if derive.nurse_rest_buffer_conflict(nurse["id"], shift):
        fail("ERR_NURSE_SHIFT_OVERLAP",
             "The nurse holds a conflicting assignment inside the sixty-minute rest buffer.")
    if derive.patient_overlap_count(case, shift) >= int(case["concurrent_nurse_limit"]):
        fail("ERR_PATIENT_CONCURRENCY_EXCEEDED",
             "The patient's concurrent nurse limit would be exceeded.")
    window = week_window(shift["start_at"])
    nurse_minutes = derive.nurse_week_minutes(
        nurse["id"], window, exclude_shift_id=shift["id"])
    if nurse_minutes + shift["scheduled_minutes"] > int(nurse["max_weekly_hours"]) * 60:
        fail("ERR_NURSE_WEEKLY_LIMIT_EXCEEDED", "The nurse's weekly ceiling would be exceeded.")
    _guard_weekly_cap(shift, authorization)
    row = _assign(shift, case, nurse)
    return cascade.respond(serialize.assignment, row, 201)


@bp.route("/shift-assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    authmod.require("Scheduler", "ClinicalSupervisor", "Nurse")
    return envelope.ok(serialize.assignment(lookup.get_assignment(assignment_id)))


@bp.route("/shift-assignments", methods=["GET"])
def list_assignments():
    authmod.require("Scheduler", "ClinicalSupervisor", "Nurse")
    limit, offset = validate.pagination()
    shift_id = validate.query_value("shift_id")
    nurse_id = validate.query_value("nurse_id")
    status = validate.query_enum("status", ASSIGNMENT_STATUSES)
    rows = store.ordered(db.assignments)
    if shift_id is not None:
        rows = [r for r in rows if r["shift_id"] == shift_id]
    if nurse_id is not None:
        rows = [r for r in rows if r["nurse_id"] == nurse_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    body = [serialize.assignment(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


@bp.route("/shift-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    authmod.require("Scheduler")
    row = lookup.get_assignment(assignment_id)
    data = validate.body()
    validate.req_str(data, "cancel_note")
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE assignment may be cancelled.")
    shift = db.shifts.get(row["shift_id"])
    if shift is None or shift["staffing_status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE", "The shift is not in the ASSIGNED state.")
    if shift["evv_status"] != "NOT_STARTED":
        fail("ERR_INVALID_STATE", "The nurse has already clocked in on this shift.")
    cascade.cancel_assignment(row, "SCHEDULER")
    shift["staffing_status"] = "OPEN"
    cascade.touch(shift)
    return cascade.respond(serialize.assignment, row)


@bp.route("/shift-assignments/<assignment_id>/timesheets", methods=["GET"])
def list_assignment_timesheets(assignment_id):
    authmod.require("Scheduler", "PayerReviewer", "Nurse")
    assignment = lookup.get_assignment(assignment_id)
    limit, offset = validate.pagination()
    rows = derive.timesheets_of_assignment(assignment["id"])
    total = len(rows)
    body = [serialize.timesheet(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


# --------------------------------------------------------------------------- #
# 61-65. timesheets
# --------------------------------------------------------------------------- #
BILLED_TERMINAL = ("BILL_ACCEPTED", "VOIDED")


def _guard_not_billed(timesheet):
    """PRD 2.8 check 39."""
    if timesheet["status"] in BILLED_TERMINAL:
        fail("ERR_TIMESHEET_ALREADY_BILLED", "The timesheet has already been billed or voided.")


@bp.route("/timesheets/<timesheet_id>", methods=["GET"])
def read_timesheet(timesheet_id):
    authmod.require("Scheduler", "PayerReviewer", "Nurse")
    return envelope.ok(serialize.timesheet(lookup.get_timesheet(timesheet_id)))


@bp.route("/timesheets/<timesheet_id>", methods=["PATCH"])
def patch_timesheet(timesheet_id):
    uid, role = authmod.require("Nurse")
    row = lookup.get_timesheet(timesheet_id)
    authmod.nurse_owns_timesheet(role, uid, row)
    data = validate.body()
    edit_reason = validate.req_str(data, "edit_reason")
    clock_in_at = validate.opt_instant(data, "clock_in_at")
    clock_out_at = validate.opt_instant(data, "clock_out_at")
    resulting_out = clock_out_at if clock_out_at is not None else row["clock_out_at"]
    if resulting_out is None:
        validate.bad("A correction must leave 'clock_out_at' non-null.")
    _guard_not_billed(row)
    if row["status"] not in ("CAPTURED", "BILL_REJECTED"):
        fail("ERR_INVALID_STATE", "The timesheet is not open to correction.")
    if clock_in_at is not None:
        row["clock_in_at"] = clock_in_at
    row["clock_out_at"] = resulting_out
    row["edit_reason"] = edit_reason
    row["_edited"] = True
    row["status"] = "EDITED"
    derive.recompute_billing(row)
    cascade.touch(row)
    return cascade.respond(serialize.timesheet, row)


@bp.route("/timesheets/<timesheet_id>/submit", methods=["POST"])
def submit_timesheet(timesheet_id):
    uid, _role = authmod.require("Scheduler")
    row = lookup.get_timesheet(timesheet_id)
    shift = derive.shift_of_timesheet(row)
    _guard_not_billed(row)
    if row["status"] not in ("CAPTURED", "EDITED"):
        fail("ERR_INVALID_STATE", "Only a captured or edited timesheet may be submitted.")
    if shift is None or shift["staffing_status"] != "COMPLETED":
        fail("ERR_INVALID_STATE", "The shift is not COMPLETED.")
    if shift["evv_status"] != "VERIFIED":
        fail("ERR_EVV_NOT_VERIFIED", "Electronic visit verification did not verify this visit.")
    row["status"] = "SUBMITTED"
    row["submitted_by_user_id"] = uid
    cascade.touch(row)
    return cascade.respond(serialize.timesheet, row)


@bp.route("/timesheets/<timesheet_id>/billing-decision", methods=["POST"])
def billing_decision(timesheet_id):
    uid, role = authmod.require("PayerReviewer")
    row = lookup.get_timesheet(timesheet_id)
    case = derive.case_of_timesheet(row)
    authorization = db.authorizations.get(case["authorization_id"]) if case else None
    if authorization is not None:
        authmod.payer_scope(role, uid, authorization["payer_id"])
    data = validate.body()
    decision = validate.req_enum(data, "decision", BILLING_DECISIONS)
    rejection_reason = validate.opt_str(data, "rejection_reason")
    _guard_not_billed(row)
    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED timesheet may be ruled on.")
    if decision == "ACCEPT":
        row["status"] = "BILL_ACCEPTED"
        row["rejection_reason"] = None
    else:
        row["status"] = "BILL_REJECTED"
        row["rejection_reason"] = rejection_reason
    cascade.touch(row)
    return cascade.respond(serialize.timesheet, row)


@bp.route("/timesheets/<timesheet_id>/void", methods=["POST"])
def void_timesheet(timesheet_id):
    authmod.require("Scheduler")
    row = lookup.get_timesheet(timesheet_id)
    data = validate.body()
    validate.req_str(data, "void_reason")
    if row["status"] not in ("SUBMITTED", "BILL_ACCEPTED", "BILL_REJECTED"):
        fail("ERR_INVALID_STATE", "The timesheet cannot be voided from its current state.")
    row["status"] = "VOIDED"
    cascade.touch(row)
    return cascade.respond(serialize.timesheet, row)
