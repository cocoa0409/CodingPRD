"""Furnaces, glass-lining batches and test cells (PRD 3.3 / 3.5)."""

from flask import Blueprint

import db
import response
import serializers
import validation
from db import make_row, ordered, touch
from errors import ApiError
from middleware import endpoint
from services.core import require_unique, resolve, rows

bp = Blueprint("assets", __name__)

BATCH_STATUSES = ("MIXED", "FIRED", "QUARANTINED")

FURNACE_READ_ROLES = ["PlantAdmin", "PlantOperator", "QualityInspector", "ComplianceEngineer"]
BATCH_READ_ROLES = ["PlantOperator", "QualityInspector", "PlantAdmin", "ComplianceEngineer"]
CELL_READ_ROLES = ["PlantAdmin", "ComplianceEngineer", "CertificationApprover", "QualityInspector"]


# --------------------------------------------------------------------------
# Furnaces
# --------------------------------------------------------------------------

@bp.post("/furnaces")
@endpoint(["PlantAdmin"])
def create_furnace():
    body = validation.json_body()
    code = validation.string(body, "furnace_code", max_length=20)
    max_temp = validation.integer(body, "max_firing_temp_c", minimum=700, maximum=1000)
    require_unique("furnace", "furnace_code", code)
    row = make_row({"furnace_code": code, "max_firing_temp_c": max_temp})
    db.db.furnaces[row["id"]] = row
    return response.created(serializers.furnace(row))


@bp.get("/furnaces/<fid>")
@endpoint(FURNACE_READ_ROLES)
def read_furnace(fid):
    return response.ok(serializers.furnace(resolve("furnace", fid)))


@bp.get("/furnaces")
@endpoint(FURNACE_READ_ROLES)
def list_furnaces():
    return response.paginate(ordered(rows("furnace")), serializers.furnace)


# --------------------------------------------------------------------------
# Glass-lining batches
# --------------------------------------------------------------------------

@bp.post("/glass-lining-batches")
@endpoint(["PlantOperator"])
def create_batch():
    body = validation.json_body()
    furnace_id = validation.string(body, "furnace_id")
    batch_code = validation.string(body, "batch_code", max_length=20)
    slurry_mix_code = validation.string(body, "slurry_mix_code", max_length=20)
    firing_temp_c = validation.integer(body, "firing_temp_c", minimum=700)
    firing_start = validation.timestamp(body, "firing_start")
    firing_end = validation.timestamp(body, "firing_end")

    furnace = resolve("furnace", furnace_id)
    require_unique("batch", "batch_code", batch_code)

    # Position 24: furnace exclusivity, on the half-open interval.
    for other in rows("batch"):
        if other["furnace_id"] != furnace["id"] or other["status"] not in ("MIXED", "FIRED"):
            continue
        if firing_start < other["firing_end"] and other["firing_start"] < firing_end:
            raise ApiError("ERR_FURNACE_WINDOW_CONFLICT")

    # Position 26: window orientation.
    if firing_start >= firing_end:
        raise ApiError("ERR_INVALID_WINDOW")

    # Position 38: firing temperature ceiling.
    if firing_temp_c > furnace["max_firing_temp_c"]:
        raise ApiError("ERR_FIRING_TEMP_EXCEEDS_FURNACE_MAX")

    row = make_row(
        {
            "furnace_id": furnace["id"],
            "batch_code": batch_code,
            "slurry_mix_code": slurry_mix_code,
            "firing_temp_c": firing_temp_c,
            "firing_start": firing_start,
            "firing_end": firing_end,
            "status": "MIXED",
            "rejected_lot_count": 0,
            "quarantine_reason_code": None,
        }
    )
    db.db.batches[row["id"]] = row
    return response.created(serializers.batch(row))


@bp.get("/glass-lining-batches/<bid>")
@endpoint(BATCH_READ_ROLES)
def read_batch(bid):
    return response.ok(serializers.batch(resolve("batch", bid)))


@bp.get("/glass-lining-batches")
@endpoint(BATCH_READ_ROLES)
def list_batches():
    furnace_id = validation.query_string("furnace_id")
    status = validation.query_enum("status", BATCH_STATUSES)
    result = rows("batch")
    if furnace_id is not None:
        result = [r for r in result if r["furnace_id"] == furnace_id]
    if status is not None:
        result = [r for r in result if r["status"] == status]
    return response.paginate(ordered(result), serializers.batch)


@bp.post("/glass-lining-batches/<bid>/fire")
@endpoint(["PlantOperator"])
def fire_batch(bid):
    batch = resolve("batch", bid)
    if batch["status"] != "MIXED":
        raise ApiError("ERR_INVALID_BATCH_STATE")
    if db.db.now() < batch["firing_end"]:
        raise ApiError("ERR_FIRING_WINDOW_NOT_ELAPSED")
    batch["status"] = "FIRED"
    touch(batch)
    return response.ok(serializers.batch(batch))


# --------------------------------------------------------------------------
# Test cells
# --------------------------------------------------------------------------

@bp.post("/test-cells")
@endpoint(["PlantAdmin"])
def create_test_cell():
    body = validation.json_body()
    code = validation.string(body, "cell_code", max_length=20)
    parallel_slots = validation.integer(body, "parallel_slots", minimum=1, maximum=8)
    cooldown_hours = validation.integer(body, "cooldown_hours", minimum=0, maximum=72)
    require_unique("test_cell", "cell_code", code)
    row = make_row(
        {
            "cell_code": code,
            "parallel_slots": parallel_slots,
            "cooldown_hours": cooldown_hours,
        }
    )
    db.db.test_cells[row["id"]] = row
    return response.created(serializers.test_cell(row))


@bp.get("/test-cells/<cid>")
@endpoint(CELL_READ_ROLES)
def read_test_cell(cid):
    return response.ok(serializers.test_cell(resolve("test_cell", cid)))


@bp.get("/test-cells")
@endpoint(CELL_READ_ROLES)
def list_test_cells():
    return response.paginate(ordered(rows("test_cell")), serializers.test_cell)
