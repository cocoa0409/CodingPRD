"""Post-weld heat treatment: furnace charges, soak requirements and charts."""

import datetime as _dt
from decimal import Decimal

from flask import Blueprint

import db
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from services import calc, derive

bp = Blueprint("pwht", __name__)

FURNACES = ("FURNACE_A", "FURNACE_B")
COOLDOWN = _dt.timedelta(minutes=180)
BATCH_JOB_STATES = ("FABRICATION", "NDE_HOLD")


def _batch_p_numbers(welds):
    numbers = set()
    for weld in welds:
        procedure = db.get("wps", weld["wps_id"])
        if procedure is not None:
            numbers.add(procedure["base_metal_p_number"])
    return numbers


def _band_violated(batch, welds):
    numbers = _batch_p_numbers(welds)
    if numbers == {1}:
        return not (Decimal("1100") <= batch["soak_temp_f"] <= Decimal("1250"))
    return False


@bp.post("/pwht-batches")
@guard(["WeldingEngineer"])
def create_batch(ctx):
    body = validation.body()
    job_id = validation.string_field(body, "job_id")
    furnace_code = validation.enum_field(body, "furnace_code", FURNACES)
    scheduled_start = validation.instant_field(body, "scheduled_start")
    scheduled_end = validation.instant_field(body, "scheduled_end")
    if scheduled_end <= scheduled_start:
        fail("ERR_INVALID_REQUEST",
             "Field 'scheduled_end' must fall strictly after 'scheduled_start'.")
    soak_temp = validation.decimal_field(body, "soak_temp_f", minimum=500,
                                         maximum=1600)
    weld_ids = validation.string_array_field(body, "weld_ids", distinct=True)

    job = db.get("jobs", job_id)
    if job is None:
        fail("ERR_JOB_NOT_FOUND", "No job carries id %s." % job_id)
    welds = []
    for weld_id in weld_ids:
        weld = db.get("welds", weld_id)
        if weld is None:
            fail("ERR_WELD_NOT_FOUND", "No joint carries id %s." % weld_id)
        welds.append(weld)

    if job["status"] not in BATCH_JOB_STATES:
        fail("ERR_INVALID_JOB_STATE",
             "Scheduling a charge needs the job in FABRICATION or NDE_HOLD.")
    for weld in welds:
        if weld["job_id"] != job_id:
            fail("ERR_WELD_NOT_IN_JOB",
                 "Joint %s belongs to another job." % weld["weld_number"])
    if not welds:
        fail("ERR_EMPTY_WELD_SET", "A furnace charge needs at least one joint.")
    if len(_batch_p_numbers(welds)) > 1:
        fail("ERR_INVALID_BATCH_STATE",
             "A charge mixing base-metal P-Numbers has no coherent soak band.")

    for other in db.all_of("batches"):
        if other["furnace_code"] != furnace_code:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        other_start = calc.parse_instant(other["scheduled_start"])
        other_end = calc.parse_instant(other["scheduled_end"])
        if (scheduled_start < other_end + COOLDOWN
                and scheduled_end > other_start - COOLDOWN):
            fail("ERR_FURNACE_WINDOW_CONFLICT",
                 "%s is booked over that window." % furnace_code)

    governing = max(weld["thickness_in"] for weld in welds)
    record = db.insert("batches", {
        "job_id": job_id,
        "furnace_code": furnace_code,
        "scheduled_start": db.iso_instant(scheduled_start),
        "scheduled_end": db.iso_instant(scheduled_end),
        "soak_temp_f": soak_temp,
        "weld_count": len(welds),
        "governing_thickness_in": governing,
        "required_soak_minutes": calc.required_soak_minutes(governing),
        "actual_soak_minutes": None,
        "chart_record_number": None,
        "chart_uploaded": False,
        "scheduled_by_personnel_id": ctx.user_id,
        "chart_reviewed_by_personnel_id": None,
        "status": "SCHEDULED",
    })
    for weld in welds:
        db.mutate(weld, {"pwht_batch_id": record["id"]})
    return common.created("batches", record)


@bp.get("/pwht-batches/<batch_id>")
@guard(ALL_ROLES)
def get_batch(ctx, batch_id):
    return common.one("batches", common.must_exist("batches", batch_id))


@bp.get("/pwht-batches")
@guard(ALL_ROLES)
def list_batches(ctx):
    return common.listing("batches", ["job_id", "scheduled_by_personnel_id",
                                      "chart_reviewed_by_personnel_id",
                                      "furnace_code", "status"])


@bp.post("/pwht-batches/<batch_id>/start")
@guard(["WeldingEngineer"])
def start_batch(ctx, batch_id):
    batch = common.must_exist("batches", batch_id)
    if batch["status"] != "SCHEDULED":
        fail("ERR_INVALID_BATCH_STATE", "Only a SCHEDULED charge may be started.")
    job = db.get("jobs", batch["job_id"])
    if job["status"] not in BATCH_JOB_STATES:
        fail("ERR_INVALID_JOB_STATE",
             "Charging the furnace needs the job in FABRICATION or NDE_HOLD.")
    welds = derive.batch_welds(batch_id)
    for weld in welds:
        if weld["fab_status"] != "WELDED":
            fail("ERR_INVALID_BATCH_STATE",
                 "Joint %s has not been welded yet." % weld["weld_number"])
    if _band_violated(batch, welds):
        fail("ERR_INVALID_BATCH_STATE",
             "The soak temperature falls outside the band for this base metal.")

    db.mutate(batch, {"status": "IN_PROGRESS"})
    for weld in welds:
        if weld["pwht_status"] == "PENDING":
            db.mutate(weld, {"pwht_status": "IN_PROGRESS"})
    return common.one("batches", batch)


@bp.post("/pwht-batches/<batch_id>/complete")
@guard(["WeldingEngineer"])
def complete_batch(ctx, batch_id):
    body = validation.body()
    actual_soak = validation.int_field(body, "actual_soak_minutes", minimum=0)
    chart_record_number = validation.string_field(body, "chart_record_number",
                                                  allow_blank=True)
    chart_uploaded = validation.bool_field(body, "chart_uploaded")

    batch = common.must_exist("batches", batch_id)
    if batch["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_BATCH_STATE", "Only an IN_PROGRESS charge may be completed.")
    job = db.get("jobs", batch["job_id"])
    if job["status"] not in BATCH_JOB_STATES:
        fail("ERR_INVALID_JOB_STATE",
             "Chart review needs the job in FABRICATION or NDE_HOLD.")
    if ctx.user_id == batch["scheduled_by_personnel_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The engineer who scheduled the charge may not certify its chart.")
    if not chart_uploaded or not chart_record_number.strip():
        fail("ERR_CHART_RECORD_MISSING",
             "The time-temperature chart record is not on file.")
    if actual_soak < batch["required_soak_minutes"]:
        fail("ERR_SOAK_TIME_INSUFFICIENT",
             "The charge held for less than %s minutes."
             % batch["required_soak_minutes"])
    for other in db.all_of("batches"):
        if other["id"] != batch_id and other["chart_record_number"] == chart_record_number:
            fail("ERR_DUPLICATE_CHART_RECORD_NUMBER",
                 "Chart record %s is already filed." % chart_record_number)

    db.mutate(batch, {"status": "COMPLETE", "actual_soak_minutes": actual_soak,
                      "chart_record_number": chart_record_number,
                      "chart_uploaded": chart_uploaded,
                      "chart_reviewed_by_personnel_id": ctx.user_id})
    for weld in derive.batch_welds(batch_id):
        if weld["pwht_status"] == "IN_PROGRESS":
            db.mutate(weld, {"pwht_status": "COMPLETE"})
    derive.recompute_job(job)
    derive.sync_job_reports(job)
    return common.one("batches", batch)
