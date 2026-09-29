"""Employee and EligibilityClassification routes."""
from decimal import Decimal

from flask import Blueprint

import calc
import clock
import db
import guards
import middleware
import recompute
from errors import fail
from middleware import ALL_ROLES, EMPLOYEE, HR_BUSINESS_PARTNER, PEOPLE_MANAGER

bp = Blueprint("employees", __name__)

READ_ROLES = tuple(r for r in ALL_ROLES if r != EMPLOYEE)
READ_ROLES_WITH_EMPLOYEE = ALL_ROLES

DEMOGRAPHIC_BANDS = ("BAND_A", "BAND_B", "BAND_C", "BAND_D")
EMPLOYEE_STATUSES = ("ACTIVE", "ON_LEAVE", "SEPARATED")
STATUS_TRANSITIONS = {
    "ACTIVE": ("ON_LEAVE", "SEPARATED"),
    "ON_LEAVE": ("ACTIVE", "SEPARATED"),
    "SEPARATED": (),
}
ELIGIBILITY_CLASSES = ("FULLY_REMOTE", "HYBRID", "ONSITE_REQUIRED")
JUSTIFICATION_CODES = ("ROLE_DESIGN", "EQUIPMENT_BOUND", "CUSTOMER_ONSITE",
                       "TALENT_RETENTION", "ACCOMMODATION_LINKED")
CLASSIFICATION_STATES = ("DRAFT", "PENDING_MANAGER", "APPROVED", "SUPERSEDED")


@bp.route("/employees", methods=["POST"])
def create_employee():
    middleware.authorize((HR_BUSINESS_PARTNER,))
    payload = middleware.body()
    team_id = middleware.req_present(payload, "team_id")
    team = middleware.must_exist("team", team_id)
    cycle = recompute.cycle_of_team(team)

    employee_number = middleware.req_string(payload, "employee_number", 1, 24)
    work_email = middleware.req_string(payload, "work_email", 1, None)
    if "@" not in work_email:
        fail("ERR_INVALID_REQUEST", "work_email must contain '@'")
    home_timezone = middleware.req_string(payload, "home_timezone", 1, None)
    tenure_start_date = middleware.req_date(payload, "tenure_start_date")
    band = middleware.req_enum(payload, "demographic_band", DEMOGRAPHIC_BANDS)
    manager_user_id = middleware.req_string(payload, "manager_user_id", 1, None)
    hr_partner_user_id = middleware.req_string(payload, "hr_partner_user_id", 1, None)
    accommodation = middleware.opt_bool(payload, "disability_accommodation_on_file", False)

    guards.gate_cycle_not_locked(cycle)

    for existing in db.all_rows("employee"):
        if existing["employee_number"] == employee_number:
            fail("ERR_DUPLICATE_EMPLOYEE_NUMBER", "employee_number is already in use")
    for existing in db.all_rows("employee"):
        if existing["work_email"] == work_email:
            fail("ERR_DUPLICATE_WORK_EMAIL", "work_email is already in use")

    row = db.insert("employee", {
        "team_id": team["id"],
        "employee_number": employee_number,
        "work_email": work_email,
        "home_timezone": home_timezone,
        "tenure_start_date": tenure_start_date.isoformat(),
        "demographic_band": band,
        "manager_user_id": manager_user_id,
        "hr_partner_user_id": hr_partner_user_id,
        "disability_accommodation_on_file": accommodation,
        "status": "ACTIVE",
        "current_eligibility_class": "ONSITE_REQUIRED",
        "cumulative_shortfall_days": 0,
        "consecutive_breach_weeks": 0,
        "approved_relief_days_total": 0,
        "non_compliance_pressure": Decimal("0.00"),
        "compliance_state": "COMPLIANT",
        "escalation_stage": "NONE",
    })
    recompute.recompute_cycle_rollups(cycle)
    return guards.single("employee", row, 201)


@bp.route("/employees/<employee_id>", methods=["GET"])
def get_employee(employee_id):
    actor = middleware.authorize(READ_ROLES_WITH_EMPLOYEE)
    row = middleware.must_exist("employee", employee_id)
    guards.require_owner(actor, row["id"])
    return guards.single("employee", row)


@bp.route("/employees", methods=["GET"])
def list_employees():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("employee")
    for arg, field in (("team_id", "team_id"), ("status", "status"),
                       ("compliance_state", "compliance_state"),
                       ("escalation_stage", "escalation_stage"),
                       ("current_eligibility_class", "current_eligibility_class")):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return guards.paged("employee", rows,
                        sort_key=lambda e: (e["employee_number"], db.seq_key(e)))


@bp.route("/employees/<employee_id>/status", methods=["POST"])
def set_employee_status(employee_id):
    middleware.authorize((HR_BUSINESS_PARTNER,))
    employee = middleware.must_exist("employee", employee_id)
    payload = middleware.body()
    target = middleware.req_enum(payload, "target_status", EMPLOYEE_STATUSES)
    middleware.opt_string(payload, "note", 1, None)
    if target not in STATUS_TRANSITIONS[employee["status"]]:
        fail("ERR_INVALID_EMPLOYEE_STATUS_TRANSITION",
             "cannot move employee status from %s to %s" % (employee["status"], target))

    db.apply_changes(employee, {"status": target})
    if target == "SEPARATED":
        _separation_cascade(employee)
    else:
        team = recompute.team_of_employee(employee)
        recompute.recompute_cycle_rollups(recompute.cycle_of_team(team) if team else None)
    return guards.single("employee", employee)


def _separation_cascade(employee):
    assignments = db.find("desk_assignment", employee_id=employee["id"])
    assignments.sort(key=lambda a: (a["start_date"], a["desk_index"], db.seq_key(a)))
    for assignment in assignments:
        if assignment["status"] == "ASSIGNED":
            db.apply_changes(assignment, {
                "status": "VACATED",
                "vacated_at": clock.now_iso(),
            })
    case = recompute.live_case(employee)
    if case is not None:
        db.apply_changes(case, {"stage": "CLOSED_SEPARATION"})
    db.apply_changes(employee, {"escalation_stage": "NONE"})
    team = recompute.team_of_employee(employee)
    recompute.recompute_team_counters(team)
    recompute.recompute_cycle_rollups(recompute.cycle_of_team(team) if team else None)


# --------------------------------------------------------------------------
# eligibility classifications
# --------------------------------------------------------------------------
def _current_approved_classification(employee):
    candidates = db.find("eligibility_classification",
                         employee_id=employee["id"], state="APPROVED")
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["effective_from"], db.seq_key(c)), reverse=True)
    return candidates[0]


@bp.route("/eligibility-classifications", methods=["POST"])
def create_classification():
    actor = middleware.authorize((PEOPLE_MANAGER, HR_BUSINESS_PARTNER))
    payload = middleware.body()
    employee_id = middleware.req_present(payload, "employee_id")
    employee = middleware.must_exist("employee", employee_id)
    cycle = recompute.cycle_of_employee(employee)

    requested_class = middleware.req_enum(payload, "requested_class", ELIGIBILITY_CLASSES)
    justification = middleware.req_enum(payload, "justification_code", JUSTIFICATION_CODES)
    effective_from = middleware.req_date(payload, "effective_from")
    expected_version = middleware.req_int(payload, "expected_employee_version")
    decision_note = middleware.opt_string(payload, "decision_note", 1, None)

    guards.occ_check(expected_version, employee, "employee")
    guards.gate_cycle_not_locked(cycle)
    guards.gate_employee_active(employee)

    prior = _current_approved_classification(employee)
    row = db.insert("eligibility_classification", {
        "employee_id": employee["id"],
        "supersedes_classification_id": prior["id"] if prior else None,
        "requested_class": requested_class,
        "justification_code": justification,
        "effective_from": effective_from.isoformat(),
        "state": "DRAFT",
        "created_by_user_id": actor.user_id,
        "decided_by_user_id": None,
        "decision_note": decision_note,
    })
    db.touch(employee)
    return guards.single("eligibility_classification", row, 201)


@bp.route("/eligibility-classifications/<classification_id>/submit", methods=["POST"])
def submit_classification(classification_id):
    middleware.authorize((PEOPLE_MANAGER, HR_BUSINESS_PARTNER))
    row = middleware.must_exist("eligibility_classification", classification_id)
    employee = db.get("employee", row["employee_id"])
    cycle = recompute.cycle_of_employee(employee)

    guards.gate_cycle_open(cycle)
    if row["state"] != "DRAFT":
        fail("ERR_CLASSIFICATION_NOT_DRAFT", "classification is not DRAFT")
    guards.gate_employee_active(employee)

    db.apply_changes(row, {"state": "PENDING_MANAGER"})
    return guards.single("eligibility_classification", row)


@bp.route("/eligibility-classifications/<classification_id>/decision", methods=["POST"])
def decide_classification(classification_id):
    actor = middleware.authorize((PEOPLE_MANAGER,))
    row = middleware.must_exist("eligibility_classification", classification_id)
    employee = db.get("employee", row["employee_id"])
    cycle = recompute.cycle_of_employee(employee)

    if actor.user_id != employee["manager_user_id"]:
        fail("ERR_UNAUTHORIZED", "only the employee's own manager may decide this classification")
    if actor.user_id == row["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the author of a classification may not decide it")

    payload = middleware.body()
    decision = middleware.req_enum(payload, "decision", ("APPROVE", "REVISE"))
    decision_note = middleware.opt_string(payload, "decision_note", 1, None)

    guards.gate_cycle_open(cycle)
    if row["state"] != "PENDING_MANAGER":
        fail("ERR_CLASSIFICATION_NOT_PENDING", "classification is not PENDING_MANAGER")

    changes = {"decided_by_user_id": actor.user_id}
    if decision_note is not None:
        changes["decision_note"] = decision_note
    if decision == "APPROVE":
        changes["state"] = "APPROVED"
        db.apply_changes(row, changes)
        superseded = db.get("eligibility_classification", row["supersedes_classification_id"])
        if superseded is not None and superseded["state"] == "APPROVED":
            db.apply_changes(superseded, {"state": "SUPERSEDED"})
        recompute.refresh_eligibility(employee)
        recompute.settle_employee(employee)
    else:
        changes["state"] = "DRAFT"
        db.apply_changes(row, changes)
    return guards.single("eligibility_classification", row)


@bp.route("/eligibility-classifications/<classification_id>", methods=["GET"])
def get_classification(classification_id):
    middleware.authorize(READ_ROLES)
    row = middleware.must_exist("eligibility_classification", classification_id)
    return guards.single("eligibility_classification", row)


@bp.route("/eligibility-classifications", methods=["GET"])
def list_classifications():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("eligibility_classification")
    for arg in ("employee_id", "supersedes_classification_id", "state"):
        value = middleware.filter_arg(arg)
        if value is not None:
            rows = [r for r in rows if r[arg] == value]
    return guards.paged("eligibility_classification", rows,
                        sort_key=lambda c: (c["effective_from"], db.seq_key(c)),
                        reverse=True)
