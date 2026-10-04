"""Build order endpoints (PRD 3.2), including the OCC-guarded stage advance."""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import (
    MATERIAL_COST_CENTS,
    NEXT_STAGE,
    SEASONING_MIN_DAYS,
    STAGE_TO_OP,
    maybe_promote_endorsement,
    recompute_endorsement_hours,
    stage_logs_for,
    wip_actual,
    wip_provisional,
)
from db import STORE, clock_now, creation_seq, new_entity, new_id, next_serial, touch, whole_days_between
from envelope import ok, paged
from errors import raise_err
from serialize import build_order as ser_build, stage_log as ser_log
from validate import get_body, opt_fk, opt_str, req_enum, req_number

bp = Blueprint("builds", __name__, url_prefix="/piano-works")

MODELS = ("MODEL_D", "MODEL_B", "MODEL_O", "ART_CASE")
BUILD_STAGES = ("RIM_BENT", "SEASONING", "ACTION_REGULATION", "VOICING", "COMPLETED")
WM = ("WorkshopManager",)
ADVANCERS = ("MasterCraftsman", "Apprentice")
MASTER_ONLY_OPS = ("ACTION_REGULATION", "VOICING")


def _get_build(bid):
    o = STORE["build_orders"].get(bid)
    if o is None:
        raise_err("ERR_NOT_FOUND", "build order %s not found" % bid)
    return o


@bp.post("/build-orders")
def create_build():
    authenticate(WM)
    body = get_body()
    model = req_enum(body, "model", MODELS)
    wb_id = opt_fk(body, "wood_batch_id")
    if wb_id is None:
        raise_err("ERR_VALIDATION", "wood_batch_id is required")
    batch = STORE["wood_batches"].get(wb_id)
    if batch is None:
        raise_err("ERR_NOT_FOUND", "wood batch %s not found" % wb_id)
    note = opt_str(body, "commissioned_note", "")
    if batch["status"] == "ALLOCATED":
        raise_err("ERR_WOOD_ALREADY_ALLOCATED", "batch already allocated to another build")
    if batch["status"] != "CONDITIONED":
        raise_err("ERR_WOOD_NOT_CONDITIONED", "batch is not CONDITIONED")
    o = new_entity()
    o.update({
        "model": model,
        "wood_batch_id": wb_id,
        "status": "COMMISSIONED",
        "seasoning_started_at": None,
        "commissioned_note": note,
        "wip_value_cents": MATERIAL_COST_CENTS[model],
    })
    STORE["build_orders"][o["id"]] = o
    batch["status"] = "ALLOCATED"
    touch(batch)
    return ok(ser_build(o), 201)


@bp.get("/build-orders")
def list_builds():
    authenticate(ALL_ROLES)
    items = list(STORE["build_orders"].values())
    for field in ("status", "model", "wood_batch_id"):
        v = request.args.get(field)
        if v is not None:
            items = [o for o in items if o[field] == v]
    return paged(items, ser_build)


@bp.get("/build-orders/<bid>")
def get_build(bid):
    authenticate(ALL_ROLES)
    return ok(ser_build(_get_build(bid)))


@bp.get("/build-orders/<bid>/stage-logs")
def list_stage_logs(bid):
    authenticate(ALL_ROLES)
    o = _get_build(bid)
    return paged(stage_logs_for(o["id"]), ser_log)


@bp.get("/build-orders/<bid>/valuation")
def build_valuation(bid):
    authenticate(ALL_ROLES)
    o = _get_build(bid)
    actual = wip_actual(o)
    provisional = wip_provisional(o)
    return ok({
        "provisional_wip_cents": provisional,
        "actual_wip_cents": actual,
        "delta_cents": provisional - actual,
    })


def _actor_gate(caller, op, sup_id):
    """Returns the apprentice's matching endorsement track, or None for masters."""
    if op in MASTER_ONLY_OPS:
        if caller["role"] != "MasterCraftsman":
            raise_err("ERR_ENDORSEMENT_REQUIRED", "operation %s is master-only" % op)
        if STORE["craftsmen"][caller["id"]]["specialty"] != op:
            raise_err("ERR_ENDORSEMENT_REQUIRED", "specialty must be %s" % op)
        return None
    if caller["role"] == "MasterCraftsman":
        if STORE["craftsmen"][caller["id"]]["specialty"] != op:
            raise_err("ERR_ENDORSEMENT_REQUIRED", "specialty must be %s" % op)
        return None
    track = None
    for t in STORE["endorsements"].values():
        if (
            t["apprentice_id"] == caller["id"]
            and t["operation_type"] == op
            and t["status"] in ("IN_TRAINING", "PENDING_ASSESSMENT", "ENDORSED")
        ):
            track = t
            break
    if track is None:
        raise_err("ERR_ENDORSEMENT_REQUIRED", "no live endorsement track for %s" % op)
    if track["status"] != "ENDORSED":
        if sup_id is None or STORE["craftsmen"][sup_id]["specialty"] != op:
            raise_err("ERR_ENDORSEMENT_REQUIRED", "supervision by a %s specialist required" % op)
    return track


@bp.post("/build-orders/<bid>/advance")
def advance_build(bid):
    caller = authenticate(ADVANCERS)
    o = _get_build(bid)
    body = get_body()
    sup_id = opt_fk(body, "supervising_craftsman_id")
    if sup_id is not None and sup_id not in STORE["craftsmen"]:
        raise_err("ERR_NOT_FOUND", "supervising_craftsman_id %s not found" % sup_id)
    wb_id = opt_fk(body, "wood_batch_id")
    if wb_id is not None and wb_id not in STORE["wood_batches"]:
        raise_err("ERR_NOT_FOUND", "wood_batch_id %s not found" % wb_id)
    to_stage = req_enum(body, "to_stage", BUILD_STAGES)
    hours = req_number(body, "hours_applied")
    if not (hours > 0 and hours <= 500):
        raise_err("ERR_VALIDATION", "hours_applied must be in (0, 500]")
    expected = body.get("expected_build_order_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err("ERR_VALIDATION", "expected_build_order_version is a required integer")
    # Priority 4: OCC first, then state-transition checks.
    if expected != o["version"]:
        raise_err("ERR_STALE_VERSION", "build order mutated since your read")
    if o["status"] == "COMPLETED":
        raise_err("ERR_INVALID_STATE", "COMPLETED build accepts no advance")
    if to_stage != NEXT_STAGE[o["status"]]:
        raise_err("ERR_BUILD_STAGE_INVALID", "%s is not the legal next stage from %s" % (to_stage, o["status"]))
    # Priority 6: wood and actor gates.
    if to_stage == "RIM_BENT":
        if not o["wood_batch_id"] or STORE["wood_batches"][o["wood_batch_id"]]["status"] != "ALLOCATED":
            raise_err("ERR_INVALID_STATE", "order must hold its allocated batch to enter RIM_BENT")
    realloc_batch = None
    if to_stage == "SEASONING" and o["wood_batch_id"] is None:
        if wb_id is None:
            raise_err("ERR_WOOD_NOT_CONDITIONED", "a CONDITIONED batch must be named to re-enter SEASONING")
        realloc_batch = STORE["wood_batches"][wb_id]
        if realloc_batch["status"] == "ALLOCATED":
            raise_err("ERR_WOOD_ALREADY_ALLOCATED", "batch already allocated to another build")
        if realloc_batch["status"] != "CONDITIONED":
            raise_err("ERR_WOOD_NOT_CONDITIONED", "batch is not CONDITIONED")
    op = STAGE_TO_OP[to_stage]
    track = _actor_gate(caller, op, sup_id)
    # Priority 7: seasoning gate.
    if to_stage == "ACTION_REGULATION":
        if whole_days_between(clock_now(), o["seasoning_started_at"]) < SEASONING_MIN_DAYS:
            raise_err("ERR_SEASONING_INCOMPLETE", "fewer than 365 whole days seasoned")
    # Side effects.
    now = clock_now()
    if realloc_batch is not None:
        realloc_batch["status"] = "ALLOCATED"
        touch(realloc_batch)
        o["wood_batch_id"] = realloc_batch["id"]
    if to_stage == "SEASONING":
        o["seasoning_started_at"] = now
    log = {
        "id": new_id(),
        "created_at": now,
        "_seq": creation_seq(),
        "build_order_id": o["id"],
        "to_stage": to_stage,
        "operation_type": op,
        "hours_applied": hours,
        "actor_role": caller["role"],
        "actor_id": caller["id"],
        "supervising_craftsman_id": sup_id,
        "logged_at": now,
    }
    STORE["stage_logs"][log["id"]] = log
    if track is not None:
        match = True if sup_id is None else STORE["craftsmen"][sup_id]["specialty"] == op
        track["supervision_log"].append({
            "supervising_craftsman_id": sup_id,
            "hours": hours,
            "specialty_match": match,
            "logged_at": now,
        })
        recompute_endorsement_hours(track)
        touch(track)
        if maybe_promote_endorsement(track):
            touch(track)
    o["status"] = to_stage
    o["wip_value_cents"] = wip_actual(o)
    touch(o)
    if to_stage == "COMPLETED":
        inst = new_entity()
        inst.update({
            "build_order_id": o["id"],
            "model": o["model"],
            "serial_number": next_serial(),
            "status": "SHOWROOM",
            "condition_grade": "A",
            "certified_authentic": True,
        })
        STORE["instruments"][inst["id"]] = inst
        if o["wood_batch_id"]:
            batch = STORE["wood_batches"][o["wood_batch_id"]]
            batch["status"] = "CONSUMED"
            touch(batch)
    return ok(ser_build(o))
