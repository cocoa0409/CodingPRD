"""Facility and cutover-task endpoints (PRD §4.2, §3.2, §3.9)."""

from datetime import timedelta

from flask import Blueprint

from db import DB, HANDOFF_BUFFER_MINUTES, parse_iso
from errors import (
    ERR_BATCH_SIZE_INVALID,
    ERR_CHANNEL_NOT_VALIDATED,
    ERR_DEFECT_BLOCKS_DEPARTMENT,
    ERR_FACILITY_NOT_FOUND,
    ERR_GO_LIVE_AFTER_TARGET,
    ERR_GO_LIVE_BLOCKED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_POSTURE_BLOCKS_OPERATION,
    ERR_PRECEDING_STEP_INCOMPLETE,
    ERR_TEMPORAL_OVERLAP,
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
from services import lookups as L
from services import recompute as R
from services.core import serialize, stamp_created

bp = Blueprint("facilities", __name__)

READ_ROLES = [
    "ImplementationDirector",
    "ImplementationAnalyst",
    "BuildAnalyst",
    "CutoverLead",
    "CommandCenterLead",
]

FACILITY_TYPES = {"ACUTE_CARE", "CRITICAL_ACCESS", "AMBULATORY", "SPECIALTY"}
CONVERSION_SCOPES = {"FULL_RECORD", "DEMOGRAPHICS_ONLY", "SCHEDULING_ONLY"}
TASK_CLASSES = {
    "DOWNTIME_PREP",
    "ORDER_RECONCILIATION",
    "PAPER_BACKFILL",
    "DRESS_REHEARSAL",
    "GO_NO_GO_DECISION",
}


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


def get_task(task_id):
    from errors import ERR_INVALID_REQUEST as _ERR_INVALID_REQUEST

    task = DB.cutover_tasks.get(task_id)
    if task is None:
        fail(_ERR_INVALID_REQUEST, "No cutover task matches the id.")
    return task


def view(facility):
    return serialize("Facility", facility)


@bp.route("/ehr-implementations/<program_id>/facilities", methods=["POST"])
def create_facility(program_id):
    uid, role = actor()
    require_role(role, ["ImplementationDirector"])
    program = get_program(program_id)
    data = body_fields(
        [
            ("name", "string", True),
            ("facility_type", "enum", True),
            ("bed_count", "int", True),
            ("rollout_wave", "int", True),
            ("conversion_scope", "enum", True),
        ],
        payload(),
    )
    enum_member("facility_type", data["facility_type"], FACILITY_TYPES)
    enum_member("conversion_scope", data["conversion_scope"], CONVERSION_SCOPES)
    if data["bed_count"] < 0:
        fail(ERR_INVALID_REQUEST, "Field 'bed_count' must be a non-negative integer.")
    if data["rollout_wave"] < 1:
        fail(ERR_INVALID_REQUEST, "Field 'rollout_wave' must be a positive integer.")
    facility = {
        "id": DB.new_id(),
        "ehr_implementation_id": program["id"],
        "name": data["name"],
        "facility_type": data["facility_type"],
        "bed_count": data["bed_count"],
        "rollout_wave": data["rollout_wave"],
        "conversion_scope": data["conversion_scope"],
        "converted_patient_count": 0,
        "conversion_variance_index": 0.0,
        "revenue_cycle_stabilization_index": 0.0,
        "status": "SITE_REGISTERED",
        "is_live": False,
    }
    stamp_created(facility)
    DB.facilities[facility["id"]] = facility
    DB.register_created(facility)
    DB.register_ref(facility["id"], "Facility")
    # PRD §2.7: "epoch advances and department-tree mutations change the program
    # between reads". A facility registered under the program is a mutation of
    # the program's own tree, so the program's version moves with it (PRD §2.4).
    program["version"] = int(program["version"]) + 1
    program["updated_at"] = facility["created_at"]
    R.recompute_program_tree(program["id"])
    return ok(view(facility), status=201)


@bp.route("/ehr-implementations/<program_id>/facilities", methods=["GET"])
def list_program_facilities(program_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    program = get_program(program_id)
    rows = L.program_facilities(program["id"])
    filters = filter_args(["rollout_wave", "status"])
    if "rollout_wave" in filters:
        rows = [f for f in rows if str(f["rollout_wave"]) == filters["rollout_wave"]]
    if "status" in filters:
        rows = [f for f in rows if f["status"] == filters["status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([view(f) for f in window], pagination=page)


@bp.route("/facilities", methods=["GET"])
def list_facilities():
    uid, role = actor()
    require_role(role, READ_ROLES)
    rows = list(DB.facilities.values())
    filters = filter_args(["ehr_implementation_id", "rollout_wave", "status"])
    if "ehr_implementation_id" in filters:
        rows = [f for f in rows if f["ehr_implementation_id"] == filters["ehr_implementation_id"]]
    if "rollout_wave" in filters:
        rows = [f for f in rows if str(f["rollout_wave"]) == filters["rollout_wave"]]
    if "status" in filters:
        rows = [f for f in rows if f["status"] == filters["status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([view(f) for f in window], pagination=page)


@bp.route("/facilities/<facility_id>", methods=["GET"])
def get_facility_endpoint(facility_id):
    uid, role = actor()
    require_role(role, READ_ROLES)
    facility = get_facility(facility_id)
    R.recompute_program_tree(facility["ehr_implementation_id"])
    return ok(view(facility))


@bp.route("/facilities/<facility_id>/configure-build", methods=["POST"])
def configure_build(facility_id):
    uid, role = actor()
    require_role(role, ["BuildAnalyst"])
    facility = get_facility(facility_id)
    program = DB.ehr_implementations[facility["ehr_implementation_id"]]
    R.recompute_program_tree(program["id"])
    if facility["status"] != "SITE_REGISTERED":
        fail(ERR_INVALID_STATE, "Configuring build requires the facility to be SITE_REGISTERED.")
    if program["readiness_posture"] != "OPEN":
        fail(
            ERR_POSTURE_BLOCKS_OPERATION,
            "Configuring facility build requires the program readiness posture to be OPEN.",
        )
    facility["status"] = "BUILD_CONFIGURED"
    DB.touch(facility, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(facility))


@bp.route("/facilities/<facility_id>/mark-validated", methods=["POST"])
def mark_validated(facility_id):
    uid, role = actor()
    require_role(role, ["ImplementationDirector"])
    facility = get_facility(facility_id)
    program = DB.ehr_implementations[facility["ehr_implementation_id"]]
    R.recompute_program_tree(program["id"])
    if facility["status"] != "BUILD_CONFIGURED":
        fail(ERR_INVALID_STATE, "Marking validated requires the facility to be BUILD_CONFIGURED.")
    if program["readiness_posture"] != "OPEN":
        fail(
            ERR_POSTURE_BLOCKS_OPERATION,
            "Marking a facility validated requires the program readiness posture to be OPEN.",
        )
    for department in L.facility_departments(facility["id"]):
        if department["build_blocking_defect_count"] > 0:
            fail(
                ERR_DEFECT_BLOCKS_DEPARTMENT,
                "A department of this facility has an open SEV1/SEV2 build-and-test defect.",
            )
    for department in L.facility_departments(facility["id"]):
        if not department["proficiency_gate_open"]:
            fail(
                ERR_INVALID_STATE,
                "Every department of this facility must have an open proficiency gate.",
            )
    facility["status"] = "VALIDATED"
    DB.touch(facility, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(facility))


@bp.route("/facilities/<facility_id>/complete-cutover-dress-rehearsal", methods=["POST"])
def complete_dress_rehearsal(facility_id):
    uid, role = actor()
    require_role(role, ["CutoverLead"])
    facility = get_facility(facility_id)
    program = DB.ehr_implementations[facility["ehr_implementation_id"]]
    R.recompute_program_tree(program["id"])
    if facility["status"] != "VALIDATED":
        fail(ERR_INVALID_STATE, "The dress rehearsal requires the facility to be VALIDATED.")
    if program["readiness_posture"] != "OPEN":
        fail(
            ERR_POSTURE_BLOCKS_OPERATION,
            "Completing the dress rehearsal requires the program readiness posture to be OPEN.",
        )
    for channel in L.program_channels(program["id"]):
        if channel["status"] != "VALIDATED":
            fail(
                ERR_CHANNEL_NOT_VALIDATED,
                "Every interface channel of the program must be VALIDATED.",
            )
    for task in L.facility_tasks(facility["id"]):
        if task["task_class"] != "GO_NO_GO_DECISION" and task["status"] not in ("COMPLETE", "SKIPPED"):
            fail(
                ERR_INVALID_STATE,
                "Every cutover task other than the go/no-go decision must be COMPLETE or SKIPPED.",
            )
    passed_c2c = any(
        scenario["scenario_class"] == "CHARGE_CAPTURE_TO_CLAIM" and scenario["status"] == "PASSED"
        for item in L.facility_departments(facility["id"])
        for bi in L.department_build_items(item["id"])
        for scenario in L.build_item_scenarios(bi["id"])
    )
    if not passed_c2c:
        fail(
            ERR_INVALID_STATE,
            "At least one CHARGE_CAPTURE_TO_CLAIM test scenario of this facility must have PASSED.",
        )
    facility["status"] = "CUTOVER_READY"
    DB.touch(facility, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(facility))


@bp.route("/facilities/<facility_id>/stabilize", methods=["POST"])
def stabilize_facility(facility_id):
    uid, role = actor()
    require_role(role, ["CommandCenterLead"])
    facility = get_facility(facility_id)
    program = DB.ehr_implementations[facility["ehr_implementation_id"]]
    R.recompute_program_tree(program["id"])
    if facility["status"] != "LIVE":
        fail(ERR_INVALID_STATE, "Stabilizing requires the facility to be LIVE.")
    if float(facility["revenue_cycle_stabilization_index"] or 0) < 80.00:
        fail(
            ERR_INVALID_STATE,
            "The facility revenue cycle stabilization index must reach at least 80.00.",
        )
    for defect in L.program_defects(program["id"]):
        if defect["severity"] in ("SEV1", "SEV2") and defect["status"] != "RESOLVED":
            fail(ERR_GO_LIVE_BLOCKED, "An open SEV1/SEV2 test defect blocks stabilization.")
    for order in L.facility_orders(facility["id"]):
        if order["billing_state"] == "CLAIM_DENIED":
            fail(ERR_INVALID_STATE, "No patient order of this facility may be CLAIM_DENIED.")
    facility["status"] = "STABILIZED"
    DB.touch(facility, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(facility))


# --------------------------------------------------------------------------
# Cutover tasks
# --------------------------------------------------------------------------
def task_view(task):
    return serialize("CutoverTask", task)


@bp.route("/facilities/<facility_id>/cutover-tasks", methods=["POST"])
def create_cutover_task(facility_id):
    uid, role = actor()
    require_role(role, ["CutoverLead"])
    facility = get_facility(facility_id)
    data = body_fields(
        [
            ("task_class", "enum", True),
            ("sequence_index", "int", True),
            ("planned_start_utc", "datetime", True),
            ("planned_end_utc", "datetime", True),
        ],
        payload(),
    )
    enum_member("task_class", data["task_class"], TASK_CLASSES)
    start = parse_iso(data["planned_start_utc"])
    end = parse_iso(data["planned_end_utc"])
    if end <= start:
        fail(ERR_INVALID_REQUEST, "planned_end_utc must be later than planned_start_utc.")

    existing = L.facility_tasks(facility["id"])
    for task in existing:
        # PRD §3.9 half-open windows: "a `planned_start_utc` that is inclusive
        # and a `planned_end_utc` that is exclusive". A step whose start lies on
        # the preceding step's end instant neither overlaps it ("must not overlap
        # the step that follows it" is the overlap rule) nor omits the standard
        # handoff buffer, because the buffer is the preceding step's window that
        # the start instant does not intrude on.
        if task["sequence_index"] < data["sequence_index"]:
            if start < task["planned_end_utc"]:
                fail(
                    ERR_TEMPORAL_OVERLAP,
                    "The new step must leave a handoff buffer after the preceding step.",
                )
        elif task["sequence_index"] > data["sequence_index"]:
            if end > task["planned_start_utc"]:
                fail(ERR_TEMPORAL_OVERLAP, "The new step overlaps the step that follows it.")

    duration = (end - start).total_seconds() / 60.0
    task = {
        "id": DB.new_id(),
        "facility_id": facility["id"],
        "ehr_implementation_id": facility["ehr_implementation_id"],
        "task_class": data["task_class"],
        "sequence_index": data["sequence_index"],
        "planned_start_utc": start,
        "planned_end_utc": end,
        "duration_minutes": float(round(duration, 2)),
        "block_reason": None,
        "status": "PLANNED",
    }
    stamp_created(task)
    DB.cutover_tasks[task["id"]] = task
    DB.register_created(task)
    return ok(task_view(task), status=201)


@bp.route("/facilities/<facility_id>/cutover-tasks", methods=["GET"])
def list_facility_tasks(facility_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "CutoverLead"])
    facility = get_facility(facility_id)
    rows = L.facility_tasks(facility["id"])
    filters = filter_args(["task_class", "status"])
    if "task_class" in filters:
        rows = [t for t in rows if t["task_class"] == filters["task_class"]]
    if "status" in filters:
        rows = [t for t in rows if t["status"] == filters["status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([task_view(t) for t in window], pagination=page)


@bp.route("/cutover-tasks", methods=["GET"])
def list_cutover_tasks():
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "CutoverLead"])
    rows = list(DB.cutover_tasks.values())
    filters = filter_args(["facility_id", "ehr_implementation_id", "task_class", "status"])
    for key in ("facility_id", "ehr_implementation_id", "task_class", "status"):
        if key in filters:
            rows = [t for t in rows if t[key] == filters[key]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([task_view(t) for t in window], pagination=page)


@bp.route("/cutover-tasks/<task_id>", methods=["GET"])
def get_cutover_task(task_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "CutoverLead"])
    task = get_task(task_id)
    return ok(task_view(task))


def _task_transition(task_id, allowed_from, mutate):
    uid, role = actor()
    require_role(role, ["CutoverLead"])
    task = get_task(task_id)
    if task["status"] not in allowed_from:
        fail(
            ERR_INVALID_STATE,
            "The cutover task is in status %s; this operation requires %s."
            % (task["status"], " or ".join(allowed_from)),
        )
    mutate(uid, task)
    DB.touch(task, common=True)
    R.recompute_program_tree(task["ehr_implementation_id"])
    return ok(task_view(task))


@bp.route("/cutover-tasks/<task_id>/start", methods=["POST"])
def start_cutover_task(task_id):
    def mutate(uid, task):
        siblings = L.facility_tasks(task["facility_id"])
        preceding = [
            t
            for t in siblings
            if t["sequence_index"] < task["sequence_index"] and t["id"] != task["id"]
        ]
        for other in preceding:
            if other["status"] not in ("COMPLETE", "SKIPPED"):
                fail(
                    ERR_PRECEDING_STEP_INCOMPLETE,
                    "An earlier-sequence cutover step is still open.",
                )
        task["status"] = "IN_PROGRESS"

    return _task_transition(task_id, ["PLANNED"], mutate)


@bp.route("/cutover-tasks/<task_id>/complete", methods=["POST"])
def complete_cutover_task(task_id):
    def mutate(uid, task):
        program = DB.ehr_implementations[task["ehr_implementation_id"]]
        for defect in L.program_defects(program["id"]):
            if defect["severity"] in ("SEV1", "SEV2") and defect["status"] != "RESOLVED":
                fail(ERR_GO_LIVE_BLOCKED, "An open SEV1/SEV2 test defect blocks go-live.")
        for channel in L.program_channels(program["id"]):
            if channel["status"] != "VALIDATED":
                fail(
                    ERR_CHANNEL_NOT_VALIDATED,
                    "Every interface channel of the program must be VALIDATED.",
                )
        if task["task_class"] == "GO_NO_GO_DECISION":
            if DB.clock.get() > program["go_live_target_utc"]:
                fail(
                    ERR_GO_LIVE_AFTER_TARGET,
                    "The decision instant is later than the contracted go-live target.",
                )
            DB.mark(uid, "go_no_go_approved")
        task["status"] = "COMPLETE"

    return _task_transition(task_id, ["IN_PROGRESS"], mutate)


@bp.route("/cutover-tasks/<task_id>/skip", methods=["POST"])
def skip_cutover_task(task_id):
    def mutate(uid, task):
        if task["task_class"] not in ("DOWNTIME_PREP", "DRESS_REHEARSAL"):
            fail(
                ERR_INVALID_STATE,
                "Only DOWNTIME_PREP and DRESS_REHEARSAL steps may be skipped.",
            )
        task["status"] = "SKIPPED"

    return _task_transition(task_id, ["PLANNED"], mutate)


@bp.route("/cutover-tasks/<task_id>/block", methods=["POST"])
def block_cutover_task(task_id):
    uid, role = actor()
    require_role(role, ["CutoverLead"])
    task = get_task(task_id)
    if task["status"] != "IN_PROGRESS":
        fail(ERR_INVALID_STATE, "Blocking requires the cutover task to be IN_PROGRESS.")
    data = body_fields([("block_reason", "string", True)], payload())
    if not (data["block_reason"] or "").strip():
        fail(ERR_INVALID_REQUEST, "block_reason must be non-empty.")
    task["block_reason"] = data["block_reason"]
    task["status"] = "BLOCKED"
    DB.touch(task, common=True)
    return ok(task_view(task))


@bp.route("/cutover-tasks/<task_id>/unblock", methods=["POST"])
def unblock_cutover_task(task_id):
    def mutate(uid, task):
        task["status"] = "IN_PROGRESS"

    return _task_transition(task_id, ["BLOCKED"], mutate)