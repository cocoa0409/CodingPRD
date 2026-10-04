"""Inspection workflow endpoints (PRD section 3.3)."""
from flask import Blueprint, g, request

import clock
import services_cycles
import store
from constants import (
    BUSINESS_READ_ROLES,
    INSPECTION_KINDS,
    OCCUPIED_INSPECTION_STATUSES,
    REQUIRED_PLAN_TYPES,
    ROLE_DISTRICT_MANAGER,
    ROLE_INSPECTOR,
)
from envelope import list_response, ok_object
from errors import (
    ApiError,
    ERR_IMMINENT_DANGER_ACTIVE,
    ERR_INSPECTOR_CONFLICT,
    ERR_INSPECTOR_DOUBLE_BOOKED,
    ERR_INSPECTOR_ENGAGED,
    ERR_INSPECTOR_MISMATCH,
    ERR_INSPECTOR_NOT_CERTIFIED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REQUIRED_PLAN_NOT_APPROVED,
)
from serialize import inspection as ser_inspection
from validate import ensure_empty_body, get_or_404, parse_body, require_roles

bp = Blueprint("inspections", __name__, url_prefix="/msha")


def _certification_covers(certification, mine_type):
    return certification == "BOTH" or certification == mine_type


def _assert_assignment_gates(mine, inspector, planned_start=None, planned_end=None):
    """Tier-10 assignment gates in scaffold order: conflict, certification,
    then (on creation only) double-booking under half-open semantics."""
    if mine["operator_id"] in inspector["conflicted_operator_ids"]:
        raise ApiError(
            ERR_INSPECTOR_CONFLICT,
            "inspector is conflicted for this mine's operator",
        )
    if not _certification_covers(inspector["certification"], mine["mine_type"]):
        raise ApiError(
            ERR_INSPECTOR_NOT_CERTIFIED,
            "inspector certification does not cover this mine_type",
        )
    if planned_start is not None:
        for other in store.inspections.values():
            if other["inspector_id"] != inspector["id"]:
                continue
            if other["status"] not in OCCUPIED_INSPECTION_STATUSES:
                continue
            # Half-open [start, end): touching at exactly one endpoint is not
            # an overlap.
            if planned_start < other["planned_end_at"] and other["planned_start_at"] < planned_end:
                raise ApiError(
                    ERR_INSPECTOR_DOUBLE_BOOKED,
                    "planned window overlaps another occupied window of this inspector",
                )


def _assert_assigned_inspector(inspection):
    if g.uid != inspection["inspector_id"]:
        raise ApiError(
            ERR_INSPECTOR_MISMATCH,
            "X-User-ID must be the inspector assigned to this inspection",
        )


@bp.route("/inspections", methods=["POST"])
def create_inspection():
    require_roles(ROLE_DISTRICT_MANAGER)
    body = parse_body({
        "mine_id": ("str", True),
        "inspector_id": ("str", True),
        "kind": ("enum", True, INSPECTION_KINDS),
        "planned_start_at": ("datetime", True),
        "planned_end_at": ("datetime", True),
        "cycle_id": ("str", False),
        "accident_id": ("str", False),
    })
    if body["planned_end_at"] <= body["planned_start_at"]:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "planned_end_at must be strictly after planned_start_at",
        )
    kind = body["kind"]
    cycle_id = body["cycle_id"]
    accident_id = body["accident_id"]
    if kind == "REGULAR":
        if cycle_id is None:
            raise ApiError(ERR_INVALID_REQUEST, "cycle_id is required for REGULAR inspections")
        if accident_id is not None:
            raise ApiError(ERR_INVALID_REQUEST, "accident_id must be omitted for REGULAR inspections")
    elif kind == "ACCIDENT_INVESTIGATION":
        if accident_id is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "accident_id is required for ACCIDENT_INVESTIGATION inspections",
            )
        if cycle_id is not None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "cycle_id must be omitted for ACCIDENT_INVESTIGATION inspections",
            )
    else:
        if cycle_id is not None or accident_id is not None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "cycle_id and accident_id must be omitted for {} inspections".format(kind),
            )
    mine = get_or_404(store.mines, body["mine_id"], "mine")
    inspector = get_or_404(store.inspectors, body["inspector_id"], "inspector")
    if cycle_id is not None:
        get_or_404(store.cycles, cycle_id, "inspection cycle")
    if accident_id is not None:
        get_or_404(store.accidents, accident_id, "accident")
    _assert_assignment_gates(mine, inspector, body["planned_start_at"], body["planned_end_at"])
    entity = store.new_entity(store.inspections, {
        "mine_id": mine["id"],
        "cycle_id": cycle_id,
        "inspector_id": inspector["id"],
        "kind": kind,
        "accident_id": accident_id,
        "planned_start_at": body["planned_start_at"],
        "planned_end_at": body["planned_end_at"],
        "file_reviewed_at": None,
        "actual_entry_at": None,
        "completed_at": None,
        "status": "ASSIGNED",
    })
    return ok_object(ser_inspection(entity), 201)


@bp.route("/inspections/<inspectionId>", methods=["GET"])
def get_inspection(inspectionId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_inspection(get_or_404(store.inspections, inspectionId, "inspection")))


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    require_roles(*BUSINESS_READ_ROLES)
    items = list(store.inspections.values())
    for param in ("mine_id", "cycle_id", "inspector_id", "accident_id", "kind", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [i for i in items if i.get(param) is not None and i[param] == value]
    return list_response(items, ser_inspection)


@bp.route("/inspections/<inspectionId>/file-review", methods=["POST"])
def file_review(inspectionId):
    require_roles(ROLE_INSPECTOR)
    ensure_empty_body()
    inspection = get_or_404(store.inspections, inspectionId, "inspection")
    _assert_assigned_inspector(inspection)
    if inspection["status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE, "file review requires ASSIGNED status")
    inspection["file_reviewed_at"] = clock.now()
    inspection["status"] = "FILE_REVIEWED"
    store.touch(inspection)
    return ok_object(ser_inspection(inspection))


@bp.route("/inspections/<inspectionId>/start", methods=["POST"])
def start_inspection(inspectionId):
    require_roles(ROLE_INSPECTOR)
    ensure_empty_body()
    inspection = get_or_404(store.inspections, inspectionId, "inspection")
    _assert_assigned_inspector(inspection)
    if inspection["status"] != "FILE_REVIEWED":
        raise ApiError(ERR_INVALID_STATE, "start requires FILE_REVIEWED status")
    # Tier 8 safety gate.
    if any(
        o["mine_id"] == inspection["mine_id"] and o["status"] != "TERMINATED"
        for o in store.idos.values()
    ):
        raise ApiError(
            ERR_IMMINENT_DANGER_ACTIVE,
            "a non-terminated imminent-danger order exists at this mine",
        )
    # Tier 10 engagement gate: capacity one IN_PROGRESS inspection per inspector.
    if any(
        other["inspector_id"] == inspection["inspector_id"]
        and other["id"] != inspection["id"]
        and other["status"] == "IN_PROGRESS"
        for other in store.inspections.values()
    ):
        raise ApiError(
            ERR_INSPECTOR_ENGAGED,
            "inspector already holds another IN_PROGRESS inspection",
        )
    inspection["actual_entry_at"] = clock.now()
    inspection["status"] = "IN_PROGRESS"
    store.touch(inspection)
    if inspection["kind"] == "ACCIDENT_INVESTIGATION" and inspection["accident_id"]:
        accident = store.accidents.get(inspection["accident_id"])
        if accident is not None and accident["status"] == "REPORTED":
            accident["status"] = "UNDER_INVESTIGATION"
            store.touch(accident)
    return ok_object(ser_inspection(inspection))


@bp.route("/inspections/<inspectionId>/complete", methods=["POST"])
def complete_inspection(inspectionId):
    require_roles(ROLE_INSPECTOR)
    ensure_empty_body()
    inspection = get_or_404(store.inspections, inspectionId, "inspection")
    _assert_assigned_inspector(inspection)
    if inspection["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "complete requires IN_PROGRESS status")
    if inspection["kind"] == "REGULAR":
        # Tier 9 required-plan gate.
        mine = store.mines.get(inspection["mine_id"])
        for plan_type in REQUIRED_PLAN_TYPES[mine["mine_type"]]:
            approved = any(
                p["mine_id"] == mine["id"]
                and p["plan_type"] == plan_type
                and p["status"] == "APPROVED"
                for p in store.plans.values()
            )
            if not approved:
                raise ApiError(
                    ERR_REQUIRED_PLAN_NOT_APPROVED,
                    "no APPROVED {} plan exists for this mine".format(plan_type),
                )
    inspection["completed_at"] = clock.now()
    inspection["status"] = "COMPLETED"
    store.touch(inspection)
    if inspection["kind"] == "REGULAR":
        services_cycles.credit_completion(inspection["mine_id"], inspection["completed_at"])
    return ok_object(ser_inspection(inspection))


@bp.route("/inspections/<inspectionId>/reassign", methods=["POST"])
def reassign_inspection(inspectionId):
    require_roles(ROLE_DISTRICT_MANAGER)
    body = parse_body({"new_inspector_id": ("str", True)})
    inspection = get_or_404(store.inspections, inspectionId, "inspection")
    new_inspector = get_or_404(store.inspectors, body["new_inspector_id"], "inspector")
    if inspection["status"] not in ("ASSIGNED", "FILE_REVIEWED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "reassignment is permitted only from ASSIGNED or FILE_REVIEWED",
        )
    mine = store.mines.get(inspection["mine_id"])
    _assert_assignment_gates(mine, new_inspector)
    inspection["inspector_id"] = new_inspector["id"]
    inspection["file_reviewed_at"] = None
    inspection["status"] = "ASSIGNED"
    store.touch(inspection)
    return ok_object(ser_inspection(inspection))


@bp.route("/inspections/<inspectionId>/cancel", methods=["POST"])
def cancel_inspection(inspectionId):
    require_roles(ROLE_DISTRICT_MANAGER)
    ensure_empty_body()
    inspection = get_or_404(store.inspections, inspectionId, "inspection")
    if inspection["status"] not in ("ASSIGNED", "FILE_REVIEWED", "SUSPENDED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "cancel is permitted only from ASSIGNED, FILE_REVIEWED, or SUSPENDED",
        )
    inspection["status"] = "CANCELLED"
    store.touch(inspection)
    return ok_object(ser_inspection(inspection))
