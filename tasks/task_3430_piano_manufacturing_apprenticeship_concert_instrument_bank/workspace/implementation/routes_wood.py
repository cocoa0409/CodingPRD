"""Wood batch endpoints (PRD 3.1)."""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import MIN_DRYING_DAYS, MOISTURE_READY_PCT, d_num, wip_actual
from db import STORE, clock_now, new_entity, touch, whole_days_between
from envelope import ok, paged
from errors import raise_err
from serialize import wood_batch as ser_batch
from validate import get_body, req_enum, req_number

bp = Blueprint("wood", __name__, url_prefix="/piano-works")

SPECIES = ("SPRUCE", "MAPLE", "MAHOGANY", "BIRCH")
WM = ("WorkshopManager",)


def _get_batch(bid):
    b = STORE["wood_batches"].get(bid)
    if b is None:
        raise_err("ERR_NOT_FOUND", "wood batch %s not found" % bid)
    return b


@bp.post("/wood-batches")
def create_batch():
    authenticate(WM)
    body = get_body()
    species = req_enum(body, "species", SPECIES)
    moisture = req_number(body, "moisture_content_pct")
    b = new_entity()
    b.update({
        "species": species,
        "moisture_content_pct": moisture,
        "status": "DRYING",
        "drying_started_at": clock_now(),
        "conditioned_at": None,
    })
    STORE["wood_batches"][b["id"]] = b
    return ok(ser_batch(b), 201)


@bp.get("/wood-batches")
def list_batches():
    authenticate(ALL_ROLES)
    items = list(STORE["wood_batches"].values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    species = request.args.get("species")
    if species is not None:
        items = [b for b in items if b["species"] == species]
    return paged(items, ser_batch)


@bp.get("/wood-batches/<bid>")
def get_batch(bid):
    authenticate(ALL_ROLES)
    return ok(ser_batch(_get_batch(bid)))


@bp.post("/wood-batches/<bid>/moisture-readings")
def moisture_reading(bid):
    authenticate(WM)
    b = _get_batch(bid)
    body = get_body()
    moisture = req_number(body, "moisture_content_pct")
    if b["status"] in ("CONSUMED", "REJECTED"):
        raise_err("ERR_INVALID_STATE", "terminal batch accepts no moisture readings")
    b["moisture_content_pct"] = moisture
    touch(b)
    # Drying gate: moisture <= 8.0 and >= 240 whole days; CONDITIONED is sticky.
    if (
        b["status"] == "DRYING"
        and d_num(moisture) <= MOISTURE_READY_PCT
        and whole_days_between(clock_now(), b["drying_started_at"]) >= MIN_DRYING_DAYS
    ):
        b["status"] = "CONDITIONED"
        b["conditioned_at"] = clock_now()
        touch(b)
    return ok(ser_batch(b))


@bp.post("/wood-batches/<bid>/reject")
def reject_batch(bid):
    authenticate(WM)
    b = _get_batch(bid)
    if b["status"] in ("CONSUMED", "REJECTED"):
        raise_err("ERR_INVALID_STATE", "terminal batch accepts no transitions")
    if b["status"] == "ALLOCATED":
        owner = None
        for o in STORE["build_orders"].values():
            if o["wood_batch_id"] == b["id"]:
                owner = o
                break
        if owner is None or owner["status"] != "SEASONING":
            raise_err("ERR_INVALID_STATE", "allocated batch is rejectable only while its build is in SEASONING")
        # Rework cascade: SEASONING -> RIM_BENT, strip batch and seasoning start.
        owner["status"] = "RIM_BENT"
        owner["wood_batch_id"] = None
        owner["seasoning_started_at"] = None
        owner["wip_value_cents"] = wip_actual(owner)
        touch(owner)
    b["status"] = "REJECTED"
    touch(b)
    return ok(ser_batch(b))
