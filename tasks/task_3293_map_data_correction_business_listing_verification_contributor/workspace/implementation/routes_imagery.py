"""ImageryTask endpoints with privacy ledger side effects."""
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from validation import require_fields, require_enum, require_int, get_or_404

bp = Blueprint("imagery", __name__)

OBLIGATIONS = {"FACES_ONLY", "FACES_AND_PLATES", "FULL_PRIVACY"}
READ_ROLES = {"PlatformAdmin", "ImageryOperator", "Moderator"}
ACTIVE_STATUSES = {"PLANNED", "SCHEDULED", "CAPTURED", "BLUR_PENDING",
                   "REPROCESS", "BLURRED"}
OVERLAP_STATUSES = {"SCHEDULED", "CAPTURED", "BLUR_PENDING", "REPROCESS", "BLURRED"}


def _overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap."""
    return a_start < b_end and b_start < a_end


def _check_window_and_capacity(region, task):
    for t in store.imagery.values():
        if t["id"] == task["id"]:
            continue
        if t["region_id"] != region["id"] or t["collection_zone"] != task["collection_zone"]:
            continue
        if t["status"] not in OVERLAP_STATUSES:
            continue
        if _overlap(clock.parse(task["window_start"]), clock.parse(task["window_end"]),
                    clock.parse(t["window_start"]), clock.parse(t["window_end"])):
            raise_err("ERR_WINDOW_OVERLAP", "window overlaps an existing task")
    active = sum(1 for t in store.imagery.values()
                 if t["id"] != task["id"]
                 and t["region_id"] == region["id"] and t["status"] in ACTIVE_STATUSES)
    if active >= region["max_active_imagery_tasks"]:
        raise_err("ERR_IMAGERY_CAPACITY", "region imagery capacity reached")


@bp.post("/v1/imagery-tasks")
def create_task():
    require_roles({"ImageryOperator", "PlatformAdmin"})
    data = body()
    require_fields(data, ["region_id", "collection_zone", "operator_id",
                          "window_start", "window_end", "blur_obligation"])
    region = store.regions.get(data["region_id"])
    if region is None:
        raise_err("ERR_NOT_FOUND", "region not found")
    obligation = require_enum(data, "blur_obligation", OBLIGATIONS)
    try:
        ws = clock.parse(data["window_start"])
        we = clock.parse(data["window_end"])
    except (ValueError, TypeError):
        raise_err("ERR_INVALID_REQUEST", "malformed window datetimes")
    if not ws < we:
        raise_err("ERR_INVALID_REQUEST", "window_start must precede window_end")
    now = clock.iso(clock.now())
    rec = {
        "id": domain.new_id(),
        "region_id": region["id"],
        "collection_zone": data["collection_zone"],
        "operator_id": data["operator_id"],
        "status": "PLANNED",
        "window_start": clock.iso(ws),
        "window_end": clock.iso(we),
        "blur_obligation": obligation,
        "capture_media_count": 0,
        "blurred_media_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.imagery[rec["id"]] = rec
    return envelope(domain.imagery_view(rec), status=201)


@bp.get("/v1/imagery-tasks")
def list_tasks():
    require_roles(READ_ROLES)
    items = list(store.imagery.values())
    for f in ("region_id", "status", "collection_zone"):
        v = request.args.get(f)
        if v is not None:
            items = [t for t in items if t.get(f) == v]
    page, pg = paginate(items, request.args)
    return envelope([domain.imagery_view(t) for t in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/imagery-tasks/<tid>")
def get_task(tid):
    require_roles(READ_ROLES)
    t = get_or_404(store.imagery, tid)
    return envelope(domain.imagery_view(t))


@bp.post("/v1/imagery-tasks/<tid>/schedule")
def schedule(tid):
    require_roles({"ImageryOperator"})
    t = get_or_404(store.imagery, tid)
    if t["status"] != "PLANNED":
        raise_err("ERR_INVALID_STATE", "only PLANNED tasks can be scheduled")
    region = store.regions.get(t["region_id"])
    domain.recompute_region(region)
    if region["posture"] == "FROZEN":
        raise_err("ERR_REGION_FROZEN", "region frozen")
    _check_window_and_capacity(region, t)
    t["status"] = "SCHEDULED"
    domain.touch(t)
    return envelope(domain.imagery_view(t))


@bp.post("/v1/imagery-tasks/<tid>/capture")
def capture(tid):
    require_roles({"ImageryOperator"})
    t = get_or_404(store.imagery, tid)
    data = body()
    require_fields(data, ["capture_media_count"])
    count = require_int(data, "capture_media_count")
    if count < 1:
        raise_err("ERR_INVALID_REQUEST", "capture_media_count must be >= 1")
    if t["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "only SCHEDULED tasks can be captured")
    now = clock.now()
    if not (clock.parse(t["window_start"]) <= now < clock.parse(t["window_end"])):
        raise_err("ERR_OUTSIDE_WINDOW", "capture outside window")
    t["capture_media_count"] = count
    t["status"] = "BLUR_PENDING"  # CAPTURED -> BLUR_PENDING in same request
    domain.touch(t)
    region = store.regions.get(t["region_id"])
    domain.recompute_region(region)
    domain.touch(region)
    return envelope(domain.imagery_view(t))


@bp.post("/v1/imagery-tasks/<tid>/blur-complete")
def blur_complete(tid):
    require_roles({"ImageryOperator"})
    t = get_or_404(store.imagery, tid)
    data = body()
    if t["status"] not in ("BLUR_PENDING", "REPROCESS"):
        raise_err("ERR_INVALID_STATE", "task not awaiting blur")
    require_fields(data, ["blurred_media_count"])
    blurred = require_int(data, "blurred_media_count")
    if data.get("reprocess") is True:
        t["status"] = "REPROCESS"
        t["blurred_media_count"] = 0
        domain.touch(t)
        return envelope(domain.imagery_view(t))
    if t["blur_obligation"] == "FACES_ONLY":
        required = 1
    else:
        required = t["capture_media_count"]
    if blurred < required:
        raise_err("ERR_BLUR_INCOMPLETE", "blurred_media_count below requirement")
    t["blurred_media_count"] = blurred
    t["status"] = "BLURRED"
    domain.touch(t)
    return envelope(domain.imagery_view(t))


@bp.post("/v1/imagery-tasks/<tid>/publish")
def publish(tid):
    require_roles({"ImageryOperator"})
    t = get_or_404(store.imagery, tid)
    if t["status"] != "BLURRED":
        raise_err("ERR_INVALID_STATE", "only BLURRED tasks can be published")
    region = store.regions.get(t["region_id"])
    domain.recompute_region(region)
    if region["posture"] == "FROZEN":
        raise_err("ERR_REGION_FROZEN", "region frozen")
    t["status"] = "PUBLISHED"
    domain.touch(t)
    domain.recompute_region(region)
    domain.touch(region)
    return envelope(domain.imagery_view(t))


@bp.post("/v1/imagery-tasks/<tid>/cancel")
def cancel(tid):
    require_roles({"ImageryOperator"})
    t = get_or_404(store.imagery, tid)
    if t["status"] == "PLANNED":
        pass
    elif t["status"] == "SCHEDULED":
        if clock.now() >= clock.parse(t["window_start"]):
            raise_err("ERR_OUTSIDE_WINDOW", "window already started")
    else:
        raise_err("ERR_INVALID_STATE", "task cannot be cancelled")
    t["status"] = "CANCELLED"
    domain.touch(t)
    region = store.regions.get(t["region_id"])
    if region is not None:
        domain.recompute_region(region)
        domain.touch(region)
    return envelope(domain.imagery_view(t))
