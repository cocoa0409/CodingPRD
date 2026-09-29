"""ThemedRoom — immutable guest-flow rooms and the capacity bottleneck
(PRD §3.3). A room carries only id and created_at: no version, no status."""

from flask import Blueprint, request

from db import db, new_row, public, touch
from errors import ApiError
from middleware import EP, GSA, LR, SO, roles
from response import list_response, object_response
from services import calc, derive
from services.validate import Body, fail

bp = Blueprint("rooms", __name__)

ROOM_RUN_STATUSES = ("PLANNED",)


@bp.post("/themed-rooms")
@roles(EP)
def create_room():
    body = Body(require_body=True)
    run_id = body.reference("run_id")
    sequence = body.integer("room_sequence", minimum=1, maximum=12)
    name = body.string("name", min_len=1, max_len=80)
    occupancy_cap = body.integer("room_occupancy_cap", minimum=1, maximum=400)
    target_dwell = body.integer("target_dwell_minutes", minimum=1, maximum=120)
    min_dwell = body.integer("min_dwell_minutes", minimum=1)
    intensity = body.integer("sensory_intensity_level", minimum=1, maximum=5)
    has_bypass = body.boolean("has_quiet_bypass", required=False, default=False)
    accessible = body.boolean("wheelchair_accessible", required=False, default=True)

    if min_dwell > target_dwell:
        fail("min_dwell_minutes may not exceed target_dwell_minutes.")

    # rung 5 — body foreign key
    run_row = derive.run(run_id)
    # rung 8/9 — rooms may only be added while the run is still PLANNED
    if run_row["run_status"] not in ROOM_RUN_STATUSES:
        raise ApiError("ERR_RUN_INVALID_STATE")
    # rung 6 — uniqueness of the flow position
    for peer in derive.rooms_of(run_row):
        if peer["room_sequence"] == sequence:
            raise ApiError("ERR_DUPLICATE_ROOM_SEQUENCE")

    row = new_row(versioned=False)
    row.update({
        "run_id": run_row["id"],
        "room_sequence": sequence,
        "name": name,
        "room_occupancy_cap": occupancy_cap,
        "target_dwell_minutes": target_dwell,
        "min_dwell_minutes": min_dwell,
        "sensory_intensity_level": intensity,
        "has_quiet_bypass": has_bypass,
        "wheelchair_accessible": accessible,
        "throughput_per_slot": calc.room_throughput_per_slot(
            occupancy_cap, run_row["timed_slot_minutes"], target_dwell),
    })
    db.rooms[row["id"]] = row

    # adding a room re-derives the run's bottleneck, taking a version bump
    derive.refresh_effective_capacity(run_row)
    touch(run_row)
    return object_response(public(row), 201)


@bp.get("/themed-rooms/<room_id>")
@roles(EP, SO, GSA, LR)
def read_room(room_id):
    return object_response(public(derive.room(room_id)))


@bp.get("/themed-rooms")
@roles(EP, SO, GSA, LR)
def list_rooms():
    rows = list(db.rooms.values())
    run_id = request.args.get("run_id")
    if run_id:
        rows = [r for r in rows if r["run_id"] == run_id]
    return list_response(rows)
