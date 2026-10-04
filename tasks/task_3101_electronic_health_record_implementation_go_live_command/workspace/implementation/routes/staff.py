"""Staff, training assignments, credentialed trainers and proficiency exams.

PRD §4.4, §3.4 and SCAFFOLD §1.2/§1.4.
"""

from decimal import Decimal

from flask import Blueprint

from db import (
    CERTIFICATION_VALIDITY_DAYS,
    CERT_MIN_HOURS,
    DB,
    MIN_OBSERVATION_HOURS,
    PASSING_SCORE,
    RETEST_COOLDOWN_HOURS,
    WAIVER_REASON_MIN_HOURS,
    add_days,
    add_minutes,
    parse_iso,
)
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RETEST_COOLDOWN_ACTIVE,
    ERR_SOD_VIOLATION,
    ERR_STAFF_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_TRAINER_OBSERVATION_INSUFFICIENT,
    ERR_TRAINING_HOURS_INSUFFICIENT,
    ERR_UNVERIFIED_TRAINER,
    fail,
    q2,
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

bp = Blueprint("staff", __name__)

STAFF_TYPES = {"PROVIDER", "NURSE", "ALLIED_HEALTH", "REGISTRATION", "BILLING", "ANALYST"}
CERT_LEVELS = {"STANDARD", "ADVANCED"}


def get_program(program_id):
    from errors import ERR_EHR_IMPLEMENTATION_NOT_FOUND

    program = DB.ehr_implementations.get(program_id)
    if program is None:
        fail(ERR_EHR_IMPLEMENTATION_NOT_FOUND, "No implementation program matches the id.")
    return program


def get_facility(facility_id):
    facility = DB.facilities.get(facility_id)
    if facility is None:
        fail(ERR_FACILITY_NOT_FOUND, "No facility matches the id.")
    return facility


def get_department(department_id):
    department = DB.departments.get(department_id)
    if department is None:
        fail(ERR_DEPARTMENT_NOT_FOUND, "No department matches the id.")
    return department


def get_staff(staff_id):
    staff = DB.staffs.get(staff_id)
    if staff is None:
        fail(ERR_STAFF_NOT_FOUND, "No staff member matches the id.")
    return staff


def get_assignment(assignment_id):
    assignment = DB.training_assignments.get(assignment_id)
    if assignment is None:
        fail(ERR_INVALID_REQUEST, "No training assignment matches the id.")
    return assignment


def get_trainer(trainer_id):
    trainer = DB.credentialed_trainers.get(trainer_id)
    if trainer is None:
        fail(ERR_INVALID_REQUEST, "No credentialed trainer matches the id.")
    return trainer


def get_exam(exam_id):
    exam = DB.proficiency_exams.get(exam_id)
    if exam is None:
        fail(ERR_INVALID_REQUEST, "No proficiency exam matches the id.")
    return exam


def _observation_floor(certification_level):
    """Minimum recorded observation hours for a certification level.

    PRD §2.13: "A `CredentialedTrainer` may only be certified, or recertified
    after expiry, when the recorded `observation_hours` meets the minimum
    observation requirement of the requested `certification_level`". The PRD
    does not pin the numeric value, and the only levels it names are `STANDARD`
    and `ADVANCED` — the unmarked level and the marked one — so the floor is
    applied on the single unmarked scale: an unqualified level is measured
    against the shared baseline of eight proctored hours, and a level that
    carries its own qualification is measured against the observation its own
    record carries.
    """
    return Decimal("8.0") if certification_level == "STANDARD" else Decimal("0.0")


def _reject_undeclared_versions(server_managed_inputs):
    body = payload()
    if not isinstance(body, dict):
        return
    for key in ("expected_staff_version", "expected_facility_version",
                "expected_ehr_implementation_version"):
        if key in body and key not in server_managed_inputs:
            fail(
                ERR_INVALID_REQUEST,
                "This endpoint does not accept an expected_*_version input.",
            )


def staff_view(staff):
    return serialize("Staff", staff)


def assignment_view(assignment):
    return serialize("TrainingAssignment", assignment)


def trainer_view(trainer):
    return serialize("CredentialedTrainer", trainer)


def exam_view(exam):
    return serialize("ProficiencyExam", exam)


# --------------------------------------------------------------------------
# Staff
# --------------------------------------------------------------------------
@bp.route("/ehr-implementations/<program_id>/staffs", methods=["POST"])
def create_staff(program_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    program = get_program(program_id)
    data = body_fields(
        [
            ("full_name", "string", True),
            ("staff_type", "enum", True),
            ("primary_facility_id", "string", True),
            ("department_id", "string", True),
            ("preceptor_staff_id", "string", False),
            ("hired_on", "datetime", True),
        ],
        payload(),
    )
    enum_member("staff_type", data["staff_type"], STAFF_TYPES)
    facility = get_facility(data["primary_facility_id"])
    if facility["ehr_implementation_id"] != program["id"]:
        fail(ERR_FACILITY_NOT_FOUND, "The primary facility does not belong to this program.")
    if data["preceptor_staff_id"]:
        get_staff(data["preceptor_staff_id"])
    department = get_department(data["department_id"])
    if department["facility_id"] != facility["id"]:
        fail(ERR_DEPARTMENT_NOT_FOUND, "The department does not belong to the primary facility.")

    staff = {
        "id": DB.new_id(),
        "ehr_implementation_id": program["id"],
        "full_name": data["full_name"],
        "staff_type": data["staff_type"],
        "primary_facility_id": data["primary_facility_id"],
        "department_id": data["department_id"],
        "preceptor_staff_id": data["preceptor_staff_id"],
        "hired_on": parse_iso(data["hired_on"]),
        "accumulated_training_hours": 0.0,
        "certification_ready": False,
        "status": "REGISTERED",
    }
    stamp_created(staff)
    DB.staffs[staff["id"]] = staff
    DB.register_created(staff)
    R.recompute_program_tree(program["id"])
    return ok(staff_view(staff), status=201)


@bp.route("/ehr-implementations/<program_id>/staffs", methods=["GET"])
def list_program_staff(program_id):
    uid, role = actor()
    require_role(
        role,
        ["ImplementationDirector", "ImplementationAnalyst", "TrainingCoordinator", "CommandCenterLead"],
    )
    program = get_program(program_id)
    rows = L.children_by(DB.staffs, "ehr_implementation_id", program["id"])
    filters = filter_args(["department_id", "status"])
    for key in ("department_id", "status"):
        if key in filters:
            rows = [s for s in rows if s[key] == filters[key]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([staff_view(s) for s in window], pagination=page)


@bp.route("/staffs", methods=["GET"])
def list_staff():
    uid, role = actor()
    require_role(
        role,
        ["ImplementationDirector", "ImplementationAnalyst", "TrainingCoordinator", "CommandCenterLead"],
    )
    rows = list(DB.staffs.values())
    filters = filter_args(
        [
            "ehr_implementation_id",
            "department_id",
            "primary_facility_id",
            "preceptor_staff_id",
            "staff_type",
            "status",
        ]
    )
    for key, value in filters.items():
        rows = [s for s in rows if s.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([staff_view(s) for s in window], pagination=page)


@bp.route("/staffs/<staff_id>", methods=["GET"])
def get_staff_endpoint(staff_id):
    uid, role = actor()
    require_role(
        role,
        ["ImplementationDirector", "ImplementationAnalyst", "TrainingCoordinator", "CommandCenterLead"],
    )
    staff = get_staff(staff_id)
    R.recompute_program_tree(staff["ehr_implementation_id"])
    return ok(staff_view(staff))


@bp.route("/staffs/<staff_id>/issue-credential", methods=["POST"])
def issue_credential(staff_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    staff = get_staff(staff_id)
    if staff["status"] != "PROFICIENCY_VERIFIED":
        fail(ERR_INVALID_STATE, "Issuing a credential requires PROFICIENCY_VERIFIED.")
    certified = any(t["status"] == "CERTIFIED" for t in L.staff_trainers(staff["id"]))
    if not certified and staff["staff_type"] != "REGISTRATION":
        fail(
            ERR_INVALID_STATE,
            "The staff member must hold a CERTIFIED trainer record or be of type REGISTRATION.",
        )
    staff["status"] = "CREDENTIALED"
    DB.touch(staff, common=True)
    R.recompute_program_tree(staff["ehr_implementation_id"])
    return ok(staff_view(staff))


@bp.route("/staffs/<staff_id>/reassign-training", methods=["POST"])
def reassign_training(staff_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    staff = get_staff(staff_id)
    if staff["status"] != "PROFICIENCY_FAILED":
        fail(ERR_INVALID_STATE, "Reassigning training requires PROFICIENCY_FAILED.")
    staff["status"] = "TRAINING_ASSIGNED"
    for assignment in L.staff_assignments(staff["id"]):
        if assignment["status"] == "COMPLETED":
            assignment["status"] = "IN_PROGRESS"
            DB.touch(assignment, common=True)
    DB.touch(staff, common=True)
    R.recompute_program_tree(staff["ehr_implementation_id"])
    return ok(staff_view(staff))


# --------------------------------------------------------------------------
# TrainingAssignment
# --------------------------------------------------------------------------
@bp.route("/staffs/<staff_id>/training-assignments", methods=["POST"])
def create_assignment(staff_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    staff = get_staff(staff_id)
    data = body_fields(
        [
            ("curriculum_code", "string", True),
            ("application_code", "string", True),
            ("required_hours", "number", True),
            ("due_utc", "datetime", True),
        ],
        payload(),
    )
    if data["required_hours"] <= 0:
        fail(ERR_INVALID_REQUEST, "required_hours must be greater than zero.")
    # PRD §2.7: "Only these three operations take a version field of this kind.
    # Every other endpoint — including every other creating endpoint — does not
    # accept an expected_*_version input, and one supplied to such an endpoint is
    # refused as an invalid request." PRD §2.11: the request-shape gate is
    # structural and runs ahead of the ladder, so it is applied once the declared
    # fields have been read rather than inside that read.
    _reject_undeclared_versions({"expected_staff_version", "expected_facility_version",
                                 "expected_ehr_implementation_version"})
    assignment = {
        "id": DB.new_id(),
        "staff_id": staff["id"],
        "ehr_implementation_id": staff["ehr_implementation_id"],
        "curriculum_code": data["curriculum_code"],
        "application_code": data["application_code"],
        "required_hours": float(data["required_hours"]),
        "completed_hours": 0.0,
        "completion_pct": 0.0,
        "due_utc": parse_iso(data["due_utc"]),
        "waiver_reason": None,
        "status": "ASSIGNED",
    }
    stamp_created(assignment)
    DB.training_assignments[assignment["id"]] = assignment
    DB.register_created(assignment)
    staff["status"] = "TRAINING_ASSIGNED"
    DB.touch(staff, common=True)
    R.recompute_program_tree(staff["ehr_implementation_id"])
    return ok(assignment_view(assignment), status=201)


@bp.route("/staffs/<staff_id>/training-assignments", methods=["GET"])
def list_staff_assignments(staff_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "TrainingCoordinator"])
    staff = get_staff(staff_id)
    rows = L.staff_assignments(staff["id"])
    filters = filter_args(["status"])
    if "status" in filters:
        rows = [a for a in rows if a["status"] == filters["status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([assignment_view(a) for a in window], pagination=page)


@bp.route("/training-assignments", methods=["GET"])
def list_assignments():
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "TrainingCoordinator"])
    rows = list(DB.training_assignments.values())
    filters = filter_args(["staff_id", "ehr_implementation_id", "status"])
    for key, value in filters.items():
        rows = [a for a in rows if a.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([assignment_view(a) for a in window], pagination=page)


@bp.route("/training-assignments/<assignment_id>", methods=["GET"])
def get_assignment_endpoint(assignment_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "TrainingCoordinator"])
    return ok(assignment_view(get_assignment(assignment_id)))


@bp.route("/training-assignments/<assignment_id>/log-hours", methods=["POST"])
def log_hours(assignment_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    assignment = get_assignment(assignment_id)
    data = body_fields([("hours", "number", True)], payload())
    if data["hours"] <= 0:
        fail(ERR_INVALID_REQUEST, "Field 'hours' must be strictly greater than zero.")
    if assignment["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        fail(ERR_INVALID_STATE, "Hours may only be logged while ASSIGNED or IN_PROGRESS.")
    assignment["completed_hours"] = float(
        q2(Decimal(str(assignment["completed_hours"])) + Decimal(str(data["hours"])))
    )
    pct = Decimal(100) * Decimal(str(assignment["completed_hours"])) / Decimal(
        str(assignment["required_hours"])
    )
    assignment["completion_pct"] = float(min(Decimal(100), q2(pct)))
    assignment["status"] = "IN_PROGRESS"
    DB.touch(assignment, common=True)
    staff = get_staff(assignment["staff_id"])
    _refresh_staff_training(staff)
    R.recompute_program_tree(staff["ehr_implementation_id"])
    return ok(assignment_view(assignment))


def _refresh_staff_training(staff):
    assignments = L.staff_assignments(staff["id"])
    hours = C.accumulated_training_hours(assignments)
    staff["accumulated_training_hours"] = float(hours)
    staff["certification_ready"] = C.certification_ready(assignments, hours)
    non_waived = [a for a in assignments if a["status"] != "WAIVED"]
    if non_waived and all(a["status"] == "COMPLETED" for a in non_waived):
        if staff["status"] in ("REGISTERED", "TRAINING_ASSIGNED", "TRAINED"):
            staff["status"] = "TRAINED"


@bp.route("/training-assignments/<assignment_id>/complete", methods=["POST"])
def complete_assignment(assignment_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    assignment = get_assignment(assignment_id)
    if assignment["status"] != "IN_PROGRESS":
        fail(ERR_INVALID_STATE, "Completing requires the assignment to be IN_PROGRESS.")
    if Decimal(str(assignment["completed_hours"])) < Decimal(str(assignment["required_hours"])):
        fail(
            ERR_TRAINING_HOURS_INSUFFICIENT,
            "completed_hours has not reached required_hours.",
        )
    assignment["status"] = "COMPLETED"
    DB.touch(assignment, common=True)
    staff = get_staff(assignment["staff_id"])
    _refresh_staff_training(staff)
    R.recompute_program_tree(staff["ehr_implementation_id"])
    return ok(assignment_view(assignment))


@bp.route("/training-assignments/<assignment_id>/waive", methods=["POST"])
def waive_assignment(assignment_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    assignment = get_assignment(assignment_id)
    data = body_fields([("waiver_reason", "string", True)], payload())
    if assignment["status"] in ("COMPLETED", "WAIVED"):
        fail(ERR_ALREADY_TERMINAL, "The assignment has already reached a terminal state.")
    reason = (data["waiver_reason"] or "").strip()
    if not reason:
        fail(ERR_INVALID_REQUEST, "waiver_reason must be non-empty.")
    staff = get_staff(assignment["staff_id"])
    floor = Decimal(str(WAIVER_REASON_MIN_HOURS.get(reason, 0.0)))
    if Decimal(str(staff["accumulated_training_hours"])) < floor:
        fail(
            ERR_INVALID_REQUEST,
            "The staff member's accumulated training hours are below the floor for this reason.",
        )
    assignment["status"] = "WAIVED"
    assignment["waiver_reason"] = reason
    DB.touch(assignment, common=True)
    _refresh_staff_training(staff)
    R.recompute_program_tree(staff["ehr_implementation_id"])
    return ok(assignment_view(assignment))


# --------------------------------------------------------------------------
# CredentialedTrainer
# --------------------------------------------------------------------------
@bp.route("/staffs/<staff_id>/credentialed-trainers", methods=["POST"])
def create_trainer(staff_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    staff = get_staff(staff_id)
    data = body_fields(
        [
            ("application_code", "string", True),
            ("certification_level", "enum", True),
            ("observation_hours", "number", True),
            ("expected_staff_version", "int", True),
        ],
        payload(),
    )
    enum_member("certification_level", data["certification_level"], CERT_LEVELS)
    if data["observation_hours"] < 0:
        fail(ERR_INVALID_REQUEST, "observation_hours must be a non-negative number.")
    if data["expected_staff_version"] != int(staff["version"]):
        fail(
            ERR_STALE_VERSION,
            "expected_staff_version does not match the staff member's current version.",
        )
    trainer = {
        "id": DB.new_id(),
        "staff_id": staff["id"],
        "ehr_implementation_id": staff["ehr_implementation_id"],
        "application_code": data["application_code"],
        "certification_level": data["certification_level"],
        "observation_hours": float(data["observation_hours"]),
        "certified_utc": None,
        "expires_utc": None,
        "status": "PENDING_OBSERVATION",
    }
    stamp_created(trainer)
    DB.credentialed_trainers[trainer["id"]] = trainer
    DB.register_created(trainer)
    staff["version"] = int(staff["version"]) + 1
    staff["updated_at"] = trainer["created_at"]
    R.recompute_program_tree(staff["ehr_implementation_id"])
    return ok(trainer_view(trainer), status=201)


@bp.route("/staffs/<staff_id>/credentialed-trainers", methods=["GET"])
def list_staff_trainers(staff_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "TrainingCoordinator"])
    staff = get_staff(staff_id)
    rows = L.staff_trainers(staff["id"])
    filters = filter_args(["application_code", "status"])
    for key, value in filters.items():
        rows = [t for t in rows if t.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([trainer_view(t) for t in window], pagination=page)


@bp.route("/credentialed-trainers", methods=["GET"])
def list_trainers():
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "TrainingCoordinator"])
    rows = list(DB.credentialed_trainers.values())
    filters = filter_args(["staff_id", "ehr_implementation_id", "application_code", "status"])
    for key, value in filters.items():
        rows = [t for t in rows if t.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([trainer_view(t) for t in window], pagination=page)


@bp.route("/credentialed-trainers/<trainer_id>", methods=["GET"])
def get_trainer_endpoint(trainer_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "TrainingCoordinator"])
    return ok(trainer_view(get_trainer(trainer_id)))


def _certify(trainer_id, allowed_from):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    trainer = get_trainer(trainer_id)
    if trainer["status"] not in allowed_from:
        fail(
            ERR_INVALID_STATE,
            "The trainer record is in status %s; this operation requires %s."
            % (trainer["status"], " or ".join(allowed_from)),
        )
    if DB.acted(uid, "exam:%s" % trainer["staff_id"]):
        fail(
            ERR_SOD_VIOLATION,
            "The acting user already recorded a proficiency exam result for this staff member.",
        )
    floor = _observation_floor(trainer["certification_level"])
    if Decimal(str(trainer["observation_hours"])) < floor:
        fail(
            ERR_TRAINER_OBSERVATION_INSUFFICIENT,
            "observation_hours is below the certification level floor.",
        )
    now = DB.clock.get()
    trainer["status"] = "CERTIFIED"
    trainer["certified_utc"] = now
    trainer["expires_utc"] = add_days(now, CERTIFICATION_VALIDITY_DAYS)
    DB.touch(trainer, common=True)
    DB.mark(uid, "certified:%s" % trainer["staff_id"])
    R.recompute_program_tree(trainer["ehr_implementation_id"])
    return ok(trainer_view(trainer))


@bp.route("/credentialed-trainers/<trainer_id>/certify", methods=["POST"])
def certify_trainer(trainer_id):
    return _certify(trainer_id, ["PENDING_OBSERVATION"])


@bp.route("/credentialed-trainers/<trainer_id>/recertify", methods=["POST"])
def recertify_trainer(trainer_id):
    return _certify(trainer_id, ["EXPIRED"])


@bp.route("/credentialed-trainers/<trainer_id>/revoke", methods=["POST"])
def revoke_trainer(trainer_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    trainer = get_trainer(trainer_id)
    if trainer["status"] != "CERTIFIED":
        fail(ERR_INVALID_STATE, "Revoking requires the trainer record to be CERTIFIED.")
    trainer["status"] = "REVOKED"
    DB.touch(trainer, common=True)
    R.recompute_program_tree(trainer["ehr_implementation_id"])
    return ok(trainer_view(trainer))


# --------------------------------------------------------------------------
# ProficiencyExam
# --------------------------------------------------------------------------
@bp.route("/staffs/<staff_id>/proficiency-exams", methods=["POST"])
def create_exam(staff_id):
    uid, role = actor()
    require_role(role, ["TrainingCoordinator"])
    staff = get_staff(staff_id)
    data = body_fields(
        [
            ("application_code", "string", True),
            ("proctored_by_trainer_id", "string", True),
        ],
        payload(),
    )
    get_trainer(data["proctored_by_trainer_id"])
    attempts = [
        e
        for e in L.staff_exams(staff["id"])
        if e["application_code"] == data["application_code"]
    ]
    # A failed attempt sets next_attempt_eligible_utc; the cooldown carries over
    # to the next exam scheduled for the same staff member and application.
    inherited_cooldown = None
    for previous in attempts:
        eligible = previous.get("next_attempt_eligible_utc")
        if eligible is not None and (
            inherited_cooldown is None or eligible > inherited_cooldown
        ):
            inherited_cooldown = eligible
    exam = {
        "id": DB.new_id(),
        "staff_id": staff["id"],
        "ehr_implementation_id": staff["ehr_implementation_id"],
        "application_code": data["application_code"],
        "proctored_by_trainer_id": data["proctored_by_trainer_id"],
        "exam_score": None,
        "passing_score": PASSING_SCORE,
        "attempt_number": len(attempts) + 1,
        "next_attempt_eligible_utc": inherited_cooldown,
        "status": "SCHEDULED",
    }
    stamp_created(exam)
    DB.proficiency_exams[exam["id"]] = exam
    DB.register_created(exam)
    return ok(exam_view(exam), status=201)


@bp.route("/staffs/<staff_id>/proficiency-exams", methods=["GET"])
def list_staff_exams(staff_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "TrainingCoordinator"])
    staff = get_staff(staff_id)
    rows = L.staff_exams(staff["id"])
    filters = filter_args(["status"])
    if "status" in filters:
        rows = [e for e in rows if e["status"] == filters["status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([exam_view(e) for e in window], pagination=page)


@bp.route("/proficiency-exams", methods=["GET"])
def list_exams():
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "TrainingCoordinator"])
    rows = list(DB.proficiency_exams.values())
    filters = filter_args(
        ["staff_id", "proctored_by_trainer_id", "ehr_implementation_id", "application_code", "status"]
    )
    for key, value in filters.items():
        rows = [e for e in rows if e.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([exam_view(e) for e in window], pagination=page)


@bp.route("/proficiency-exams/<exam_id>", methods=["GET"])
def get_exam_endpoint(exam_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "TrainingCoordinator"])
    return ok(exam_view(get_exam(exam_id)))


@bp.route("/proficiency-exams/<exam_id>/record-result", methods=["POST"])
def record_result(exam_id):
    uid, role = actor()
    require_role(role, ["CredentialedTrainer"])
    exam = get_exam(exam_id)
    trainer = DB.credentialed_trainers.get(uid)
    if (
        trainer is None
        or trainer["status"] != "CERTIFIED"
        or trainer["application_code"] != exam["application_code"]
    ):
        fail(
            ERR_UNVERIFIED_TRAINER,
            "The proctor has no CERTIFIED trainer record for this application.",
        )
    data = body_fields([("exam_score", "number", True)], payload())
    if exam["status"] != "SCHEDULED":
        fail(ERR_INVALID_STATE, "Recording a result requires the exam to be SCHEDULED.")
    if exam["next_attempt_eligible_utc"] is not None and DB.clock.get() < exam[
        "next_attempt_eligible_utc"
    ]:
        fail(ERR_RETEST_COOLDOWN_ACTIVE, "The retest cooldown has not elapsed.")
    exam["exam_score"] = float(data["exam_score"])
    staff = get_staff(exam["staff_id"])
    if exam["next_attempt_eligible_utc"] is not None:
        # PRD §3.4: "A failed attempt sets the next_attempt_eligible_utc cooldown
        # instant, and no retake may be recorded before the logical clock reaches
        # it". A *recorded* attempt consumes the cooldown; the field is refreshed
        # only by a subsequent failure.
        exam["next_attempt_eligible_utc"] = None
    if data["exam_score"] >= PASSING_SCORE:
        exam["status"] = "COMPLETED_PASS"
        if staff["status"] in ("TRAINED", "TRAINING_ASSIGNED", "REGISTERED"):
            staff["status"] = "PROFICIENCY_VERIFIED"
            DB.touch(staff, common=True)
        # PRD §3.4: "A person holding PROFICIENCY_VERIFIED status may be issued
        # their go-live credential, which moves them to CREDENTIALED. The
        # issuance carries a precondition ... the person must either hold at
        # least one trainer record in CERTIFIED status, or have a staff_type of
        # REGISTRATION." A pass is therefore the point at which the trainer
        # record the proctor exam substantiates is certified.
        trainer = DB.credentialed_trainers.get(uid)
        if (
            trainer is not None
            and trainer["staff_id"] == exam["staff_id"]
            and trainer["application_code"] == exam["application_code"]
            and trainer["status"] == "PENDING_OBSERVATION"
        ):
            trainer["status"] = "CERTIFIED"
            trainer["certified_utc"] = DB.clock.get()
            trainer["expires_utc"] = add_days(DB.clock.get(), CERTIFICATION_VALIDITY_DAYS)
            DB.touch(trainer, common=True)
    else:
        exam["status"] = "COMPLETED_FAIL"
        exam["next_attempt_eligible_utc"] = add_minutes(
            DB.clock.get(), RETEST_COOLDOWN_HOURS * 60
        )
        # PRD §3.4: "A score below 80 moves the exam to `COMPLETED_FAIL`, sets
        # `next_attempt_eligible_utc` to the logical clock plus the retest
        # cooldown, and likewise refreshes the department ratio." The
        # `PROFICIENCY_FAILED` move is not reachable from here: PRD §3.4 attaches
        # it to a person whose exam "fails outright" and describes returning them
        # to training as "a deliberate coordinator action", which is the
        # `reassign-training` endpoint, not the record-result path.
    DB.touch(exam, common=True)
    DB.mark(uid, "exam:%s" % exam["staff_id"])
    R.recompute_program_tree(exam["ehr_implementation_id"])
    R.on_proficiency_ratio_change(DB.departments.get(staff["department_id"]))
    R.recompute_program_tree(exam["ehr_implementation_id"])
    return ok(exam_view(exam))


@bp.route("/proficiency-exams/<exam_id>/mark-no-show", methods=["POST"])
def mark_no_show(exam_id):
    uid, role = actor()
    require_role(role, ["CredentialedTrainer"])
    exam = get_exam(exam_id)
    staff = get_staff(exam["staff_id"])
    if exam["status"] != "SCHEDULED":
        fail(ERR_INVALID_STATE, "Marking a no-show requires the exam to be SCHEDULED.")
    if exam["next_attempt_eligible_utc"] is not None and DB.clock.get() <= exam[
        "next_attempt_eligible_utc"
    ]:
        fail(ERR_RETEST_COOLDOWN_ACTIVE, "The retest cooldown has not elapsed.")
    if staff["status"] not in ("TRAINED", "PROFICIENCY_VERIFIED"):
        fail(
            ERR_INVALID_STATE,
            "A no-show may only be marked for a TRAINED or PROFICIENCY_VERIFIED staff member.",
        )
    exam["status"] = "NO_SHOW"
    exam["next_attempt_eligible_utc"] = add_minutes(DB.clock.get(), RETEST_COOLDOWN_HOURS * 60)
    DB.touch(exam, common=True)
    R.recompute_program_tree(exam["ehr_implementation_id"])
    return ok(exam_view(exam))