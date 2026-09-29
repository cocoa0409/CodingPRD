"""Clock, show-up curves, checkpoints, lanes and equipment units."""

from datetime import timedelta

from flask import Blueprint

import cascade
import consts
import derive
import envelope
import req
import serial
import store
from errors import ApiError, bad_request, fail
from util import dec, iso

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    req.actor(["PlatformAdmin"])
    values = req.parse_body([{"name": "current_utc", "kind": "datetime", "required": True}])
    store.set_now(values["current_utc"])
    return envelope.obj({"current_utc": iso(store.now())})


# ---------------------------------------------------------------------------
# show-up curves
# ---------------------------------------------------------------------------
CURVE_SPEC = [
    {"name": "name", "kind": "string", "required": True, "max_len": 60},
    {"name": "carrier_type", "kind": "enum", "required": True, "values": consts.CARRIER_TYPES},
    {"name": "season_code", "kind": "enum", "required": True, "values": consts.SEASON_CODES},
    {
        "name": "window_start_minutes_before",
        "kind": "integer",
        "required": True,
        "min": 0,
        "max": 600,
    },
    {"name": "window_end_minutes_before", "kind": "integer", "required": True, "min": 0},
    {"name": "buckets", "kind": "buckets", "required": True},
]


def _validate_buckets(values):
    start = values["window_start_minutes_before"]
    end = values["window_end_minutes_before"]
    buckets = values["buckets"]
    ordered = sorted(buckets, key=lambda b: b["minutes_before_end"])
    for bucket in ordered:
        if bucket["minutes_before_start"] <= bucket["minutes_before_end"]:
            fail("ERR_CURVE_BUCKETS_INVALID", "bucket start must exceed bucket end")
    cursor = end
    for bucket in ordered:
        if bucket["minutes_before_end"] != cursor:
            fail("ERR_CURVE_BUCKETS_INVALID", "buckets must tile the curve window exactly")
        cursor = bucket["minutes_before_start"]
    if cursor != start:
        fail("ERR_CURVE_BUCKETS_INVALID", "buckets must tile the curve window exactly")
    total = sum((b["share_pct"] for b in buckets), dec(0))
    if total != dec(100):
        fail("ERR_CURVE_BUCKETS_INVALID", "share_pct values must sum to exactly 100")


@bp.post("/show-up-curves")
def create_curve():
    req.actor(["PlatformAdmin", "StaffingPlanner"])
    values = req.parse_body(CURVE_SPEC)
    if values["window_start_minutes_before"] <= values["window_end_minutes_before"]:
        bad_request("window_start_minutes_before must exceed window_end_minutes_before")
    _validate_buckets(values)
    row = store.base(versioned=False)
    row.update(
        {
            "name": values["name"],
            "carrier_type": values["carrier_type"],
            "season_code": values["season_code"],
            "window_start_minutes_before": values["window_start_minutes_before"],
            "window_end_minutes_before": values["window_end_minutes_before"],
            "buckets": values["buckets"],
        }
    )
    store.add("show_up_curves", row)
    return envelope.obj(serial.show_up_curve(row), 201)


@bp.get("/show-up-curves/<show_up_curve_id>")
def read_curve(show_up_curve_id):
    req.actor(req.READ_ROLES)
    row = req.load("show_up_curve", show_up_curve_id)
    return envelope.obj(serial.show_up_curve(row))


# ---------------------------------------------------------------------------
# checkpoints
# ---------------------------------------------------------------------------
CHECKPOINT_SPEC = [
    {"name": "name", "kind": "string", "required": True, "max_len": 80},
    {"name": "terminal_code", "kind": "string", "required": True, "max_len": 4, "upper_alnum": True},
    {"name": "total_lane_positions", "kind": "integer", "required": True, "min": 1},
    {"name": "wait_threshold_minutes_standard", "kind": "integer", "required": True, "min": 1},
    {"name": "wait_threshold_minutes_expedited", "kind": "integer", "required": True, "min": 1},
    {"name": "connecting_pax_discount_pct", "kind": "number", "min": 0, "max": 50},
    {"name": "secondary_slot_capacity", "kind": "integer", "required": True, "min": 0},
    {"name": "plan_cost_cap_cents", "kind": "integer", "required": True, "min": 0},
    {"name": "suspended", "kind": "boolean"},
]

CHECKPOINT_PATCH_SPEC = [
    {"name": "wait_threshold_minutes_standard", "kind": "integer", "min": 1},
    {"name": "wait_threshold_minutes_expedited", "kind": "integer", "min": 1},
    {"name": "connecting_pax_discount_pct", "kind": "number", "min": 0, "max": 50},
    {"name": "secondary_slot_capacity", "kind": "integer", "min": 0},
    {"name": "plan_cost_cap_cents", "kind": "integer", "min": 0},
    {"name": "suspended", "kind": "boolean"},
]


@bp.post("/checkpoints")
def create_checkpoint():
    req.actor(["PlatformAdmin"])
    values = req.parse_body(CHECKPOINT_SPEC)
    row = store.base()
    row.update(
        {
            "name": values["name"],
            "terminal_code": values["terminal_code"],
            "total_lane_positions": values["total_lane_positions"],
            "available_lane_positions": values["total_lane_positions"],
            "open_lane_count": 0,
            "suspended": values.get("suspended", False),
            "posture": "NORMAL",
            "wait_threshold_minutes_standard": values["wait_threshold_minutes_standard"],
            "wait_threshold_minutes_expedited": values["wait_threshold_minutes_expedited"],
            "connecting_pax_discount_pct": values.get("connecting_pax_discount_pct", dec(0)),
            "secondary_slot_capacity": values["secondary_slot_capacity"],
            "secondary_slots_in_use": 0,
            "plan_cost_cap_cents": values["plan_cost_cap_cents"],
            "consecutive_breach_count_standard": 0,
            "consecutive_breach_count_expedited": 0,
            "diverted_pax_total": 0,
            "leo_referral_count": 0,
            "denied_entry_count": 0,
            "cleared_referral_count": 0,
        }
    )
    if row["suspended"]:
        row["posture"] = "SUSPENDED"
    store.add("checkpoints", row)
    return envelope.obj(serial.checkpoint(row), 201)


@bp.get("/checkpoints/<checkpoint_id>")
def read_checkpoint(checkpoint_id):
    req.actor(req.READ_ROLES)
    row = req.load("checkpoint", checkpoint_id)
    return envelope.obj(serial.checkpoint(row))


@bp.patch("/checkpoints/<checkpoint_id>")
def patch_checkpoint(checkpoint_id):
    role, _user = req.actor(["PlatformAdmin", "CheckpointManager"])
    values = req.parse_body(CHECKPOINT_PATCH_SPEC)
    checkpoint = req.load("checkpoint", checkpoint_id)
    if "suspended" in values and role != "CheckpointManager":
        fail("ERR_FORBIDDEN_ACTION_FOR_ROLE", "only a CheckpointManager may set suspended")
    if "plan_cost_cap_cents" in values and role != "PlatformAdmin":
        fail(
            "ERR_FORBIDDEN_ACTION_FOR_ROLE",
            "only a PlatformAdmin may change plan_cost_cap_cents",
        )
    before = derive.posture(checkpoint)
    if "suspended" in values:
        target = values["suspended"]
        if target == checkpoint["suspended"]:
            fail("ERR_INVALID_STATE_TRANSITION", "suspended is already %s" % target)
        if target is False:
            if (
                derive.open_escalation_count(checkpoint["id"]) > 0
                or derive.oos_lane_count(checkpoint["id"]) > 0
            ):
                fail(
                    "ERR_INVALID_STATE_TRANSITION",
                    "open escalations or out-of-service lanes remain",
                )
    for field in (
        "wait_threshold_minutes_standard",
        "wait_threshold_minutes_expedited",
        "connecting_pax_discount_pct",
        "secondary_slot_capacity",
        "plan_cost_cap_cents",
    ):
        if field in values:
            checkpoint[field] = values[field]
    if "suspended" in values:
        checkpoint["suspended"] = values["suspended"]
        if values["suspended"]:
            cascade.suspend_checkpoint(checkpoint)
    cascade.bump_checkpoint(checkpoint)
    cascade.settle_posture(checkpoint, before)
    return envelope.obj(serial.checkpoint(checkpoint))


# ---------------------------------------------------------------------------
# lanes
# ---------------------------------------------------------------------------
LANE_SPEC = [
    {
        "name": "checkpoint_id",
        "kind": "string",
        "required": True,
        "fk": "checkpoint",
        "collection": "checkpoints",
    },
    {"name": "lane_type", "kind": "enum", "required": True, "values": consts.LANE_TYPES},
    {"name": "position_index", "kind": "integer", "required": True, "min": 1},
    {"name": "required_officer_count", "kind": "integer", "required": True, "min": 1},
    {"name": "max_concurrent_officers", "kind": "integer", "required": True, "min": 1},
    {"name": "secondary_positions", "kind": "integer", "required": True, "min": 0},
]


@bp.post("/lanes")
def create_lane():
    req.actor(["PlatformAdmin", "CheckpointManager"])
    values = req.parse_body(LANE_SPEC)
    parents = req.resolve_fks(values, LANE_SPEC)
    checkpoint = parents["checkpoint_id"]
    for lane in derive.checkpoint_lanes(checkpoint["id"]):
        if (
            lane["lane_state"] != "DECOMMISSIONED"
            and lane["position_index"] == values["position_index"]
        ):
            fail("ERR_DUPLICATE_LANE_POSITION", "position_index is already in use")
    row = store.base()
    row.update(
        {
            "checkpoint_id": checkpoint["id"],
            "lane_type": values["lane_type"],
            "position_index": values["position_index"],
            "required_officer_count": values["required_officer_count"],
            "max_concurrent_officers": values["max_concurrent_officers"],
            "secondary_positions": values["secondary_positions"],
            "lane_state": "CLOSED",
            "equipment_state": "OUT_OF_SERVICE",
            "opened_at_utc": None,
            "paused_reason_code": None,
        }
    )
    store.add("lanes", row)
    cascade.bump_checkpoint(checkpoint)
    derive.refresh_checkpoint(checkpoint)
    return envelope.obj(serial.lane(row), 201)


@bp.get("/lanes/<lane_id>")
def read_lane(lane_id):
    req.actor(req.READ_ROLES)
    row = req.load("lane", lane_id)
    return envelope.obj(serial.lane(row))


@bp.get("/lanes")
def list_lanes():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    lane_type = req.query_enum("lane_type", consts.LANE_TYPES)
    lane_state = req.query_enum("lane_state", consts.LANE_STATES)
    equipment_state = req.query_enum("equipment_state", consts.EQUIPMENT_STATES)
    checkpoint_id = req.query_value("checkpoint_id")
    rows = store.rows("lanes")
    for row in rows:
        row["equipment_state"] = derive.lane_equipment_state(row)
    rows = req.filter_rows(
        rows,
        {
            "checkpoint_id": checkpoint_id,
            "lane_type": lane_type,
            "lane_state": lane_state,
            "equipment_state": equipment_state,
        },
    )
    rows.sort(key=lambda l: (l["position_index"], l["_seq"]))
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(serial.many(serial.lane, page), limit, offset, total)


def _acting_officer(user_id):
    return store.get("officers", user_id)


def _require_supervisor(user_id):
    officer = _acting_officer(user_id)
    if officer is None or "SUPERVISOR" not in officer["certifications"]:
        fail(
            "ERR_SUPERVISOR_CERTIFICATION_REQUIRED",
            "the acting officer must hold the SUPERVISOR certification",
        )
    return officer


@bp.post("/lanes/<lane_id>/open")
def open_lane(lane_id):
    role, user_id = req.actor(["CheckpointManager", "SupervisoryOfficer"])
    lane = req.load("lane", lane_id)
    checkpoint = store.get("checkpoints", lane["checkpoint_id"])
    if derive.posture(checkpoint) == "SUSPENDED":
        fail("ERR_CHECKPOINT_SUSPENDED", "the checkpoint is suspended")
    if lane["lane_state"] not in ("CLOSED", "PAUSED"):
        fail("ERR_INVALID_STATE_TRANSITION", "a %s lane cannot be opened" % lane["lane_state"])
    required = consts.REQUIRED_EQUIPMENT_BY_LANE_TYPE[lane["lane_type"]]
    units = derive.lane_units(lane["id"])
    usable = {}
    for kind in required:
        matching = [
            u
            for u in units
            if u["equipment_type"] == kind and u["state"] in ("SERVICEABLE", "DEGRADED")
        ]
        if not matching:
            fail(
                "ERR_LANE_EQUIPMENT_UNAVAILABLE",
                "equipment type %s is missing or out of service" % kind,
            )
        usable[kind] = matching
    now = store.now()
    for kind in required:
        for unit in usable[kind]:
            if unit["calibration_due_utc"] < now:
                fail("ERR_CALIBRATION_OVERDUE", "unit %s calibration has lapsed" % kind)
    if role == "SupervisoryOfficer":
        _require_supervisor(user_id)
    if derive.available_lane_positions(checkpoint) < lane["required_officer_count"]:
        fail("ERR_LANE_POSITIONS_EXHAUSTED", "not enough free floor positions")
    before = derive.posture(checkpoint)
    cascade.reopen_lane(lane)
    cascade.bump_checkpoint(checkpoint)
    cascade.settle_posture(checkpoint, before)
    return envelope.obj(serial.lane(lane))


STAND_DOWN_SPEC = [
    {
        "name": "target_state",
        "kind": "enum",
        "required": True,
        "values": ("PAUSED", "CLOSED", "DECOMMISSIONED"),
    },
    {
        "name": "paused_reason_code",
        "kind": "enum",
        "values": consts.PAUSED_REASON_CODES,
    },
]


@bp.post("/lanes/<lane_id>/stand-down")
def stand_down_lane(lane_id):
    req.actor(["CheckpointManager", "SupervisoryOfficer"])
    values = req.parse_body(STAND_DOWN_SPEC)
    target = values["target_state"]
    if target == "PAUSED" and "paused_reason_code" not in values:
        bad_request("paused_reason_code is required when target_state is PAUSED")
    lane = req.load("lane", lane_id)
    checkpoint = store.get("checkpoints", lane["checkpoint_id"])
    current = lane["lane_state"]
    legal = (
        (current == "OPEN" and target == "PAUSED")
        or (current in ("OPEN", "PAUSED") and target == "CLOSED")
        or (current == "CLOSED" and target == "DECOMMISSIONED")
    )
    if not legal:
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "a %s lane cannot move to %s" % (current, target),
        )
    if target == "CLOSED":
        for referral in derive.checkpoint_referrals(checkpoint["id"]):
            if referral["lane_id"] == lane["id"] and referral["state"] in (
                "RAISED",
                "IN_PROGRESS",
            ):
                fail("ERR_INVALID_STATE_TRANSITION", "an open referral remains on this lane")
    if target == "DECOMMISSIONED":
        for assignment in cascade.lane_assignments(
            lane["id"], ("SCHEDULED", "CHECKED_IN", "REASSIGN_PENDING")
        ):
            fail("ERR_INVALID_STATE_TRANSITION", "live assignments remain on this lane")
    before = derive.posture(checkpoint)
    if target == "PAUSED":
        cascade.pause_lane(lane, values["paused_reason_code"])
    elif target == "CLOSED":
        cascade.close_lane(lane, values.get("paused_reason_code"))
    else:
        lane["lane_state"] = "DECOMMISSIONED"
        store.touch(lane)
    cascade.bump_checkpoint(checkpoint)
    cascade.settle_posture(checkpoint, before)
    return envelope.obj(serial.lane(lane))


# ---------------------------------------------------------------------------
# equipment units
# ---------------------------------------------------------------------------
UNIT_SPEC = [
    {"name": "lane_id", "kind": "string", "required": True, "fk": "lane", "collection": "lanes"},
    {
        "name": "equipment_type",
        "kind": "enum",
        "required": True,
        "values": consts.EQUIPMENT_TYPES,
    },
    {"name": "serial_number", "kind": "string", "required": True, "max_len": 40},
    {"name": "calibration_due_utc", "kind": "datetime", "required": True},
]


@bp.post("/equipment-units")
def create_unit():
    req.actor(["PlatformAdmin", "CheckpointManager"])
    values = req.parse_body(UNIT_SPEC)
    parents = req.resolve_fks(values, UNIT_SPEC)
    lane = parents["lane_id"]
    row = store.base()
    row.update(
        {
            "lane_id": lane["id"],
            "equipment_type": values["equipment_type"],
            "serial_number": values["serial_number"],
            "calibration_due_utc": values["calibration_due_utc"],
            "state": "SERVICEABLE",
            "last_state_note": None,
        }
    )
    store.add("equipment_units", row)
    checkpoint = store.get("checkpoints", lane["checkpoint_id"])
    if checkpoint is not None:
        derive.refresh_checkpoint(checkpoint)
    return envelope.obj(serial.equipment_unit(row), 201)


@bp.get("/equipment-units/<equipment_unit_id>")
def read_unit(equipment_unit_id):
    req.actor(req.READ_ROLES)
    row = req.load("equipment_unit", equipment_unit_id)
    return envelope.obj(serial.equipment_unit(row))


@bp.get("/equipment-units")
def list_units():
    req.actor(req.READ_ROLES)
    limit, offset = req.pagination()
    state = req.query_enum("state", consts.EQUIPMENT_STATES)
    equipment_type = req.query_enum("equipment_type", consts.EQUIPMENT_TYPES)
    lane_id = req.query_value("lane_id")
    rows = req.filter_rows(
        store.rows("equipment_units"),
        {"lane_id": lane_id, "state": state, "equipment_type": equipment_type},
    )
    rows.sort(key=lambda u: (u["created_at"], u["_seq"]))
    page, total = req.paginate(rows, limit, offset)
    return envelope.listing(serial.many(serial.equipment_unit, page), limit, offset, total)


REPORT_STATE_SPEC = [
    {"name": "state", "kind": "enum", "required": True, "values": consts.EQUIPMENT_STATES},
    {"name": "note", "kind": "string", "max_len": 500, "non_blank": False, "min_len": 0},
]


@bp.post("/equipment-units/<equipment_unit_id>/report-state")
def report_unit_state(equipment_unit_id):
    req.actor(["CheckpointManager", "SupervisoryOfficer"])
    values = req.parse_body(REPORT_STATE_SPEC)
    unit = req.load("equipment_unit", equipment_unit_id)
    lane = store.get("lanes", unit["lane_id"])
    if lane is not None and lane["lane_state"] == "DECOMMISSIONED":
        fail("ERR_INVALID_STATE_TRANSITION", "the host lane is decommissioned")
    if unit["state"] == values["state"]:
        fail("ERR_INVALID_STATE_TRANSITION", "the unit is already %s" % values["state"])
    checkpoint = store.get("checkpoints", lane["checkpoint_id"]) if lane else None
    before = derive.posture(checkpoint) if checkpoint else None
    unit["state"] = values["state"]
    unit["last_state_note"] = values.get("note")
    store.touch(unit)
    paused = False
    if lane is not None:
        paused = cascade.equipment_cascade(lane)
    if checkpoint is not None:
        after = cascade.settle_posture(checkpoint, before)
        if paused or after != before:
            cascade.bump_checkpoint(checkpoint)
    return envelope.obj(serial.equipment_unit(unit))
