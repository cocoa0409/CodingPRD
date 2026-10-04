"""Implementation program endpoints (PRD §4.1)."""

from flask import Blueprint

from db import CUTOVER_READY_SCORE, DB, parse_iso
from errors import (
    ERR_CHANNEL_NOT_VALIDATED,
    ERR_EHR_IMPLEMENTATION_NOT_FOUND,
    ERR_GO_LIVE_BLOCKED,
    ERR_GO_LIVE_AFTER_TARGET,
    ERR_INVALID_STATE,
    ERR_POSTURE_BLOCKS_OPERATION,
    fail,
)
from request_utils import actor, body_fields, collection, filter_args, pagination, payload, require_role
from response import ok
from services import lookups as L
from services import recompute as R
from services.core import serialize, stamp_created

bp = Blueprint("ehr", __name__)

LIST_ROLES = [
    "ImplementationDirector",
    "ImplementationAnalyst",
    "BuildAnalyst",
    "CutoverLead",
    "CommandCenterLead",
]

STATUSES = {
    "PLANNING",
    "BUILD_IN_PROGRESS",
    "VALIDATION_IN_PROGRESS",
    "CUTOVER_READY",
    "GO_LIVE_ACTIVE",
    "COMMAND_CENTER_ACTIVE",
    "STABILIZED",
    "POST_LIVE_OPTIMIZATION",
    "ARCHIVED",
}


def get_program(program_id):
    program = DB.ehr_implementations.get(program_id)
    if program is None:
        fail(ERR_EHR_IMPLEMENTATION_NOT_FOUND, "No implementation program matches the id.")
    return program


def guard_posture(program):
    if program["readiness_posture"] == "ROLLBACK_REQUIRED":
        fail(
            ERR_POSTURE_BLOCKS_OPERATION,
            "The program readiness posture is ROLLBACK_REQUIRED; only remediation is admissible.",
        )


def view(program):
    return serialize("EhrImplementation", program)


@bp.route("/ehr-implementations", methods=["POST"])
def create_program():
    uid, role = actor()
    require_role(role, ["ImplementationDirector"])
    data = body_fields(
        [
            ("program_name", "string", True),
            ("vendor_release", "string", True),
            ("go_live_target_utc", "datetime", True),
        ],
        payload(),
    )
    program = {
        "id": DB.new_id(),
        "program_name": data["program_name"],
        "vendor_release": data["vendor_release"],
        "go_live_target_utc": parse_iso(data["go_live_target_utc"]),
        "status": "PLANNING",
        "readiness_posture": "OPEN",
        "current_epoch_index": 0,
        "readiness_score": 100.0,
        "optimistic_readiness_score": 100.0,
        "net_trainer_count": 0,
        "order_reconciliation_balance": 0,
        "command_center_activated_utc": None,
    }
    stamp_created(program)
    DB.ehr_implementations[program["id"]] = program
    DB.register_created(program)
    R.recompute_program(program)
    return ok(view(program), status=201)


@bp.route("/ehr-implementations", methods=["GET"])
def list_programs():
    uid, role = actor()
    require_role(role, LIST_ROLES)
    filters = filter_args(["status"])
    rows = list(DB.ehr_implementations.values())
    if "status" in filters:
        rows = [p for p in rows if p["status"] == filters["status"]]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([view(p) for p in window], pagination=page)


@bp.route("/ehr-implementations/<program_id>", methods=["GET"])
def get_program_endpoint(program_id):
    uid, role = actor()
    require_role(role, LIST_ROLES)
    program = get_program(program_id)
    R.recompute_program_tree(program["id"])
    return ok(view(program))


@bp.route("/ehr-implementations/<program_id>/advance-epoch", methods=["POST"])
def advance_epoch(program_id):
    uid, role = actor()
    require_role(role, ["ImplementationDirector"])
    program = get_program(program_id)
    program["current_epoch_index"] = int(program["current_epoch_index"]) + 1
    DB.touch(program, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(program))


# --- phase transitions -----------------------------------------------------
def _phase(program_id, trigger, from_states, extra_guard):
    uid, role = actor()
    require_role(role, ["ImplementationDirector"])
    program = get_program(program_id)
    R.recompute_program_tree(program["id"])
    if program["status"] not in from_states:
        fail(
            ERR_INVALID_STATE,
            "The program is in status %s; this operation requires %s."
            % (program["status"], " or ".join(from_states)),
        )
    guard_posture(program)
    extra_guard(program)
    return program


@bp.route("/ehr-implementations/<program_id>/start-build", methods=["POST"])
def start_build(program_id):
    def guard(program):
        facilities = L.program_facilities(program["id"])
        if not any(f["status"] in ("SITE_REGISTERED", "BUILD_CONFIGURED") for f in facilities):
            fail(
                ERR_INVALID_STATE,
                "At least one facility must be SITE_REGISTERED or BUILD_CONFIGURED.",
            )

    program = _phase(program_id, "start-build", ["PLANNING"], guard)
    program["status"] = "BUILD_IN_PROGRESS"
    DB.touch(program, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(program))


@bp.route("/ehr-implementations/<program_id>/start-validation", methods=["POST"])
def start_validation(program_id):
    def guard(program):
        allowed = {"BUILD_COMPLETE", "IN_TESTING", "VALIDATION_COMPLETE"}
        for item in L.program_build_items(program["id"]):
            if item["status"] not in allowed:
                fail(
                    ERR_INVALID_STATE,
                    "Every system build item must have completed build work before validation begins.",
                )

    program = _phase(program_id, "start-validation", ["BUILD_IN_PROGRESS"], guard)
    program["status"] = "VALIDATION_IN_PROGRESS"
    DB.touch(program, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(program))


@bp.route("/ehr-implementations/<program_id>/finalize-validation", methods=["POST"])
def finalize_validation(program_id):
    def guard(program):
        if program["readiness_posture"] != "OPEN":
            fail(
                ERR_INVALID_STATE,
                "Finalizing validation requires the readiness posture to be exactly OPEN.",
            )
        if float(program["readiness_score"]) < CUTOVER_READY_SCORE:
            fail(
                ERR_INVALID_STATE,
                "The readiness score has not reached the cutover threshold of 85.00.",
            )
        for channel in L.program_channels(program["id"]):
            if channel["status"] != "VALIDATED":
                fail(
                    ERR_CHANNEL_NOT_VALIDATED,
                    "Every interface channel of the program must be VALIDATED.",
                )

    program = _phase(program_id, "finalize-validation", ["VALIDATION_IN_PROGRESS"], guard)
    program["status"] = "CUTOVER_READY"
    DB.touch(program, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(program))


@bp.route("/ehr-implementations/<program_id>/execute-go-live", methods=["POST"])
def execute_go_live(program_id):
    def guard(program):
        if program["readiness_posture"] != "OPEN":
            fail(
                ERR_INVALID_STATE,
                "Executing go-live requires the readiness posture to be exactly OPEN.",
            )
        for defect in L.program_defects(program["id"]):
            if defect["severity"] in ("SEV1", "SEV2") and defect["status"] != "RESOLVED":
                fail(
                    ERR_GO_LIVE_BLOCKED,
                    "An open SEV1/SEV2 test defect blocks the go-live decision.",
                )
        decisions = [
            t
            for t in L.program_cutover_tasks(program["id"])
            if t["task_class"] == "GO_NO_GO_DECISION"
        ]
        if not decisions:
            fail(
                ERR_INVALID_STATE,
                "A facility GO_NO_GO_DECISION cutover task must be COMPLETE before go-live.",
            )
        if not any(t["status"] == "COMPLETE" for t in decisions):
            fail(
                ERR_INVALID_STATE,
                "A facility GO_NO_GO_DECISION cutover task must be COMPLETE before go-live.",
            )

    program = _phase(program_id, "execute-go-live", ["CUTOVER_READY"], guard)
    if DB.clock.get() > program["go_live_target_utc"]:
        fail(
            ERR_GO_LIVE_AFTER_TARGET,
            "The go-live instant is later than the contracted target.",
        )
    program["status"] = "GO_LIVE_ACTIVE"
    DB.touch(program, common=True)
    # Cascade link 1: Facility CUTOVER_READY -> LIVE. Link 2 then fires because
    # the facility entered LIVE, not because of the original request.
    for facility in L.program_facilities(program["id"]):
        if facility["status"] == "CUTOVER_READY":
            facility["status"] = "LIVE"
            facility["is_live"] = True
            DB.touch(facility, common=True)
            R.on_facility_entered_live(facility)
    R.recompute_program_tree(program["id"])
    return ok(view(program))


@bp.route("/ehr-implementations/<program_id>/activate-command-center", methods=["POST"])
def activate_command_center(program_id):
    uid, role = actor()
    require_role(role, ["CommandCenterLead"])
    program = get_program(program_id)
    R.recompute_program_tree(program["id"])
    if program["status"] != "GO_LIVE_ACTIVE":
        fail(ERR_INVALID_STATE, "Activating the command center requires GO_LIVE_ACTIVE.")
    guard_posture(program)
    shifts = [
        s
        for s in L.children_by(DB.staffing_shifts, "ehr_implementation_id", program["id"])
        if s["status"] == "SCHEDULED" and s["start_utc"] <= DB.clock.get()
    ]
    if not shifts:
        fail(
            ERR_INVALID_STATE,
            "At least one staffing shift must be SCHEDULED with a start instant at or before the clock.",
        )
    program["status"] = "COMMAND_CENTER_ACTIVE"
    program["command_center_activated_utc"] = DB.clock.get()
    DB.touch(program, common=True)
    for facility in L.program_facilities(program["id"]):
        if facility["status"] in ("LIVE", "STABILIZATION_AT_RISK"):
            facility["status"] = "STABILIZED"
            facility["is_live"] = True
            DB.touch(facility, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(program))


@bp.route("/ehr-implementations/<program_id>/begin-optimization", methods=["POST"])
def begin_optimization(program_id):
    uid, role = actor()
    require_role(role, ["ImplementationDirector"])
    program = get_program(program_id)
    R.recompute_program_tree(program["id"])
    if program["status"] != "STABILIZED":
        fail(ERR_INVALID_STATE, "Opening optimization requires the program to be STABILIZED.")
    for facility in L.program_facilities(program["id"]):
        if float(facility["revenue_cycle_stabilization_index"] or 0) < 80.00:
            fail(
                ERR_INVALID_STATE,
                "Every facility must reach a revenue cycle stabilization index of at least 80.00.",
            )
    program["status"] = "POST_LIVE_OPTIMIZATION"
    DB.touch(program, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(program))


@bp.route("/ehr-implementations/<program_id>/archive", methods=["POST"])
def archive_program(program_id):
    uid, role = actor()
    require_role(role, ["ImplementationDirector"])
    program = get_program(program_id)
    if program["status"] != "POST_LIVE_OPTIMIZATION":
        fail(ERR_INVALID_STATE, "Archiving requires the program to be POST_LIVE_OPTIMIZATION.")
    program["status"] = "ARCHIVED"
    DB.touch(program, common=True)
    R.recompute_program_tree(program["id"])
    return ok(view(program))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = actor()
    require_role(role, ["ImplementationDirector"])
    data = body_fields([("to_iso8601", "datetime", True)], payload())
    DB.clock.set(parse_iso(data["to_iso8601"]))
    for program in DB.ehr_implementations.values():
        R.recompute_program_tree(program["id"])
    return ok({})