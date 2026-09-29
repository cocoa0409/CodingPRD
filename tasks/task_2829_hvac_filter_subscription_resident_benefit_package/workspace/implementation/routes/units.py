"""Units, the move-in measurement and telemetry ingestion (PRD 3.2)."""
from flask import Blueprint

import calc
import clock
import envelope
import guards
import validate
import views
from errors import fail
from store import base_record, db, touch

bp = Blueprint("units", __name__)

READING_SOURCES = ("SMART_THERMOSTAT", "PRESSURE_SENSOR", "GATEWAY_BACKFILL")
REPRICED_STATUSES = ("PENDING_SETUP", "ACTIVE", "SUSPENDED")


@bp.get("/units/<unit_id>")
def read_unit(unit_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    rec = guards.get_unit(unit_id)
    guards.own_unit(uid, role, rec)
    return envelope.object_response(views.unit_view(rec))


@bp.post("/units/<unit_id>/filter-size-captures")
def capture_filter_size(unit_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    unit = guards.get_unit(unit_id)
    guards.own_unit(uid, role, unit)
    body = validate.json_body()
    measured = validate.req_string(body, "actual_measured_size_code",
                                   pattern=validate.SIZE_CODE_RE)
    expected_version = validate.req_int(body, "expected_unit_version")
    if expected_version != unit["version"]:
        fail("ERR_STALE_UNIT_VERSION",
             "expected_unit_version does not match the unit's current version")

    # Re-derive the whole pricing chain for every live subscription on the unit
    # BEFORE committing anything: a single unmappable subscription rejects the
    # entire capture (PRD 3.2).
    probe = dict(unit)
    probe["actual_measured_size_code"] = measured
    affected = [s for s in calc.subscriptions_of_unit(unit["id"])
                if s["status"] in REPRICED_STATUSES]
    repricings = []
    for sub in affected:
        resident = db.residents[sub["resident_id"]]
        repricings.append((sub, calc.reprice_without_benefit_change(probe, resident,
                                                                   sub)))

    unit["actual_measured_size_code"] = measured
    unit["size_capture_count"] = unit["size_capture_count"] + 1
    touch(unit)
    # The capture re-derives the pricing chain on each live subscription. PRD 3.2
    # declares only the unit's version increment for this operation, so the
    # subscriptions' own version counters are deliberately left alone.
    for sub, priced in repricings:
        sub.update(priced)
    return envelope.object_response(views.unit_view(unit))


@bp.post("/units/<unit_id>/runtime-readings")
def ingest_runtime_reading(unit_id):
    guards.auth(["ProgramOperator"])
    unit = guards.get_unit(unit_id)
    body = validate.json_body()
    window_start = validate.req_instant(body, "window_start")
    window_end = validate.req_instant(body, "window_end")
    runtime_minutes = validate.req_int(body, "runtime_minutes", 0)
    pressure = validate.req_int(body, "static_pressure_delta_pa")
    source = validate.req_enum(body, "source", READING_SOURCES)
    if not window_end > window_start:
        fail("ERR_INVALID_RUNTIME_WINDOW",
             "window_end must be strictly after window_start")
    if pressure <= 0:
        fail("ERR_INVALID_RUNTIME_WINDOW",
             "static_pressure_delta_pa must be greater than zero")

    rec = base_record(with_version=False)
    rec["unit_id"] = unit["id"]
    rec["window_start"] = clock.fmt_instant(window_start)
    rec["window_end"] = clock.fmt_instant(window_end)
    rec["runtime_minutes"] = runtime_minutes
    rec["static_pressure_delta_pa"] = pressure
    rec["source"] = source
    db.readings[rec["id"]] = rec
    return envelope.object_response(views.reading_view(rec), 201)


@bp.get("/units/<unit_id>/runtime-readings")
def list_runtime_readings(unit_id):
    guards.auth(["ProgramOperator"])
    unit = guards.get_unit(unit_id)
    limit, offset, filters = guards.pagination({"source": READING_SOURCES})
    rows = [r for r in calc.readings_of(unit["id"])
            if all(r[k] == v for k, v in filters.items())]
    return envelope.list_response([views.reading_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))
