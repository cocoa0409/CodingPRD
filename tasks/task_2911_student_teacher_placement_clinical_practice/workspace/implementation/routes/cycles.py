"""Observation cycle endpoints (PRD 3.7)."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import shapes
import store
import views
from auth import endpoint
from errors import ApiError

bp = Blueprint("cycles", __name__)

READERS = ["SupervisionLead", "UniversitySupervisorUser",
           "PlacementCoordinator", "ProgramAdmin"]


def _cycle_state_invalid(message):
    return ApiError("ERR_CYCLE_STATE_INVALID", message)


def _refresh(cycle):
    placement = store.PLACEMENTS.get(cycle["placement_id"])
    if placement is not None:
        derive.derive_placement_observations(placement, sweep=False)
    return placement


@bp.post("/epp/observation-cycles")
@endpoint(["SupervisionLead"])
def schedule_cycle():
    body = shapes.body_of(request)
    placement_id = shapes.req_str(body, "placement_id", 1, None)
    sequence_no = shapes.req_int(body, "sequence_no", 1, 6)
    cycle_type = shapes.req_enum(body, "cycle_type", shapes.CYCLE_TYPES)
    window_start = shapes.req_instant(body, "window_start")
    window_end = shapes.req_instant(body, "window_end")

    placement = store.get_placement(placement_id)

    for existing in store.cycles_of_placement(placement["id"]):
        if int(existing["sequence_no"]) == sequence_no:
            raise shapes.bad(
                "sequence_no %d is already used by this placement."
                % sequence_no)

    if not window_end > window_start:
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_end must be strictly later than window_start.")

    agreement = store.AGREEMENTS.get(placement["agreement_id"])
    if agreement is not None:
        derive.expire_agreement(agreement)
        if agreement["status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE",
                           "The placement's backing agreement is not ACTIVE.")

    row = store.new_row({
        "placement_id": placement["id"],
        "supervisor_id": placement["supervisor_id"],
        "sequence_no": sequence_no,
        "cycle_type": cycle_type,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "observed_at": None,
        "rubric_score": None,
        "reschedule_count": 0,
        "resolution_note": None,
    })
    store.CYCLES[row["id"]] = row
    derive.derive_placement_observations(placement, sweep=False)
    return envelope.created(views.dump(row, views.CYCLE))


@bp.get("/epp/observation-cycles/<cycle_id>")
@endpoint(READERS)
def read_cycle(cycle_id):
    row = store.get_cycle(cycle_id)
    if derive.miss_cycle(row):
        _refresh(row)
    return envelope.ok(views.dump(row, views.CYCLE))


@bp.get("/epp/observation-cycles")
@endpoint(READERS)
def list_cycles():
    page, page_size = shapes.pagination(request.args)
    placement_id = request.args.get("placement_id") or None
    supervisor_id = request.args.get("supervisor_id") or None
    cycle_type = shapes.query_enum(request.args, "cycle_type",
                                   shapes.CYCLE_TYPES)
    status = shapes.query_enum(request.args, "status", shapes.CYCLE_STATUSES)
    rows = []
    for row in store.all_of(store.CYCLES):
        if placement_id is not None and row["placement_id"] != placement_id:
            continue
        if supervisor_id is not None and row["supervisor_id"] != supervisor_id:
            continue
        if cycle_type is not None and row["cycle_type"] != cycle_type:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    sliced, total = shapes.paginate(rows, page, page_size)
    return envelope.listing(views.dump_all(sliced, views.CYCLE),
                            page, page_size, total)


@bp.post("/epp/observation-cycles/<cycle_id>/complete")
@endpoint(["UniversitySupervisorUser"])
def complete_cycle(cycle_id):
    row = store.get_cycle(cycle_id)

    # Rung 4 -- only the cycle's own supervisor may record the visit.
    auth.require_owner(row["supervisor_id"])

    body = shapes.body_of(request)
    observed_at = shapes.req_instant(body, "observed_at")
    rubric_score = shapes.req_number(body, "rubric_score", "1.0", "5.0", "0.5")

    # The clock's own transition runs before the state gate.
    if derive.miss_cycle(row):
        _refresh(row)

    # Rung 20 -- the cycle must still be SCHEDULED.
    if row["status"] != "SCHEDULED":
        raise _cycle_state_invalid(
            "Only a SCHEDULED cycle may record an observation.")

    # Rung 32 -- the half-open observation window.
    if not (row["window_start"] <= observed_at < row["window_end"]):
        raise ApiError("ERR_OBSERVATION_OUTSIDE_WINDOW",
                       "observed_at must fall inside the cycle's half-open "
                       "window.")

    row["status"] = "COMPLETED"
    row["observed_at"] = observed_at
    row["rubric_score"] = rubric_score
    store.touch(row)
    _refresh(row)
    return envelope.ok(views.dump(row, views.CYCLE))


@bp.post("/epp/observation-cycles/<cycle_id>/reschedule")
@endpoint(["SupervisionLead"])
def reschedule_cycle(cycle_id):
    row = store.get_cycle(cycle_id)
    body = shapes.body_of(request)
    window_start = shapes.req_instant(body, "window_start")
    window_end = shapes.req_instant(body, "window_end")
    resolution_note = shapes.req_str(body, "resolution_note", 1, None)

    # Rung 8 -- the interval itself must be well formed.
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_WINDOW",
                       "window_end must be strictly later than window_start.")

    if derive.miss_cycle(row):
        _refresh(row)

    # Rung 20 -- only a MISSED cycle may be rescued.
    if row["status"] != "MISSED":
        raise _cycle_state_invalid("Only a MISSED cycle may be rescheduled.")

    # Rung 33 -- the new window's placement in time.
    placement = store.PLACEMENTS.get(row["placement_id"])
    conflict = window_start < clock.now()
    if placement is not None and not conflict:
        if window_end > clock.end_of_day(placement["end_date"]):
            conflict = True
    if placement is not None and not conflict:
        for other in store.cycles_of_placement(placement["id"]):
            if other["id"] == row["id"]:
                continue
            if other["status"] not in ("SCHEDULED", "COMPLETED"):
                continue
            if (window_start < other["window_end"]
                    and other["window_start"] < window_end):
                conflict = True
                break
    if conflict:
        raise ApiError("ERR_CYCLE_WINDOW_CONFLICT",
                       "The new window is out of bounds or overlaps another "
                       "cycle of the same placement.")

    # Rung 37 -- the reschedule ceiling.
    if int(row["reschedule_count"]) >= calc.MAX_RESCHEDULES_PER_CYCLE:
        raise ApiError("ERR_RESCHEDULE_LIMIT_REACHED",
                       "The cycle has already been rescheduled twice.")

    row["status"] = "SCHEDULED"
    row["window_start"] = window_start
    row["window_end"] = window_end
    row["reschedule_count"] = int(row["reschedule_count"]) + 1
    row["resolution_note"] = resolution_note
    store.touch(row)
    _refresh(row)
    return envelope.ok(views.dump(row, views.CYCLE))
