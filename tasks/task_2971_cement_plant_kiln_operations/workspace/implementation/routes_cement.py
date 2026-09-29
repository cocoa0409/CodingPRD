"""Finish milling and the laboratory (PRD 3.6, 3.7)."""

from flask import Blueprint

from core import (
    API_PREFIX, INTERNAL_ROLES,
    D, ZERO, r2, guard, body, fail, actor, now,
    want_str, want_num, want_int, want_enum,
    fk_ref, path_row, put_row, new_row, touch, get_row, rows,
    respond_object, filtered_list, field_eq, _bad,
)
import calc
import cascades
import serial

bp = Blueprint("cement", __name__, url_prefix=API_PREFIX)

READ = INTERNAL_ROLES


# ===========================================================================
# Cement batches
# ===========================================================================
@bp.post("/cement-batches")
@guard(["ProcessEngineer"])
def create_batch():
    payload = body()
    plant = fk_ref(payload, "plant_id", "plants")
    clinker_silo = fk_ref(payload, "clinker_silo_id", "silos")
    cement_silo = fk_ref(payload, "cement_silo_id", "silos")
    want_str(payload, "plant_id")
    want_str(payload, "clinker_silo_id")
    want_str(payload, "cement_silo_id")
    cement_type = want_enum(payload, "cement_type", calc.CEMENT_TYPES)
    drawn = want_num(payload, "clinker_tonnes_drawn")
    gypsum_pct = want_num(payload, "gypsum_pct")
    limestone_pct = want_num(payload, "limestone_pct")
    blaine = want_int(payload, "blaine_target_m2_per_kg")
    expected = want_int(payload, "expected_clinker_silo_version")
    spec = calc.CEMENT_TYPE_SPECS[cement_type]
    if not (calc.GYPSUM_MIN_PCT <= D(gypsum_pct) <= calc.GYPSUM_MAX_PCT):
        _bad("gypsum_pct", "must lie between 2.00 and 7.00 inclusive")
    if not (spec["blaine_min"] <= blaine <= spec["blaine_max"]):
        _bad("blaine_target_m2_per_kg", "must sit inside the cement type's Blaine band")
    if expected != clinker_silo["version"]:
        fail("ERR_STALE_SILO_VERSION")
    if clinker_silo["status"] != "OPEN" or cement_silo["status"] != "OPEN":
        fail("ERR_SILO_BLOCKED")
    if (clinker_silo["material_kind"] != "CLINKER"
            or cement_silo["material_kind"] != "CEMENT"
            or clinker_silo["plant_id"] != plant["id"]
            or cement_silo["plant_id"] != plant["id"]):
        fail("ERR_SILO_KIND_MISMATCH")
    if D(limestone_pct) > spec["limestone_max_pct"]:
        fail("ERR_LIMESTONE_LIMIT_EXCEEDED")
    figures = calc.proportion_batch(drawn, gypsum_pct, limestone_pct)
    if figures is None:
        _bad("limestone_pct", "leaves no room for clinker in the batch")
    if D(figures["so3_pct"]) > spec["so3_max_pct"]:
        fail("ERR_SO3_LIMIT_EXCEEDED")
    if D(drawn) > D(calc.silo_available(clinker_silo)):
        fail("ERR_INSUFFICIENT_CLINKER")
    row = new_row("batches")
    row.update({
        "plant_id": plant["id"],
        "clinker_silo_id": clinker_silo["id"],
        "cement_silo_id": cement_silo["id"],
        "cement_type": cement_type,
        "clinker_tonnes_drawn": drawn,
        "gypsum_pct": gypsum_pct,
        "limestone_pct": limestone_pct,
        "blaine_target_m2_per_kg": blaine,
        "status": "PLANNED",
        "strength_branch_state": "PENDING",
        "fineness_branch_state": "PENDING",
        "feed_state": "FEED_READY",
        "rejection_reason": None,
        "grinding_started_at": None,
        "ground_at": None,
        "qualified_at": None,
    })
    row.update(figures)
    put_row("batches", row)
    clinker_silo["reserved_tonnes"] = r2(D(clinker_silo["reserved_tonnes"]) + D(drawn))
    touch(clinker_silo)
    return respond_object(serial.batch_out(row), 201)


@bp.post("/cement-batches/<cement_batch_id>/start-grinding")
@guard(["KilnOperator"])
def start_grinding(cement_batch_id):
    batch = path_row("batches", cement_batch_id)
    if batch["status"] != "PLANNED":
        fail("ERR_INVALID_BATCH_STATE")
    clinker_silo = get_row("silos", batch["clinker_silo_id"])
    cement_silo = get_row("silos", batch["cement_silo_id"])
    if (clinker_silo is None or cement_silo is None
            or clinker_silo["status"] != "OPEN" or cement_silo["status"] != "OPEN"):
        fail("ERR_SILO_BLOCKED")
    if batch["feed_state"] != "FEED_READY":
        fail("ERR_BATCH_FEED_SHORT")
    drawn = D(batch["clinker_tonnes_drawn"])
    batch["status"] = "GRINDING"
    batch["grinding_started_at"] = now()
    touch(batch)
    clinker_silo["tonnes_on_hand"] = r2(D(clinker_silo["tonnes_on_hand"]) - drawn)
    clinker_silo["reserved_tonnes"] = r2(D(clinker_silo["reserved_tonnes"]) - drawn)
    touch(clinker_silo)
    return respond_object(serial.batch_out(batch))


@bp.post("/cement-batches/<cement_batch_id>/finish-grinding")
@guard(["KilnOperator"])
def finish_grinding(cement_batch_id):
    batch = path_row("batches", cement_batch_id)
    if batch["status"] != "GRINDING":
        fail("ERR_INVALID_BATCH_STATE")
    cement_silo = get_row("silos", batch["cement_silo_id"])
    if cement_silo is None or cement_silo["status"] != "OPEN":
        fail("ERR_SILO_BLOCKED")
    cement = D(batch["cement_tonnes"])
    if D(cement_silo["tonnes_on_hand"]) + cement > D(cement_silo["capacity_tonnes"]):
        fail("ERR_SILO_CAPACITY_EXCEEDED")
    batch["status"] = "GROUND"
    batch["ground_at"] = now()
    batch["strength_branch_state"] = "PENDING"
    batch["fineness_branch_state"] = "PENDING"
    touch(batch)
    cement_silo["tonnes_on_hand"] = r2(D(cement_silo["tonnes_on_hand"]) + cement)
    cement_silo["unreleased_tonnes"] = r2(D(cement_silo["unreleased_tonnes"]) + cement)
    touch(cement_silo)
    return respond_object(serial.batch_out(batch))


@bp.get("/cement-batches/<cement_batch_id>")
@guard(READ)
def get_batch(cement_batch_id):
    return respond_object(serial.batch_out(path_row("batches", cement_batch_id)))


@bp.get("/cement-batches")
@guard(READ)
def list_batches():
    return filtered_list("batches", serial.batch_out, {
        "plant_id": field_eq("plant_id"),
        "clinker_silo_id": field_eq("clinker_silo_id"),
        "cement_silo_id": field_eq("cement_silo_id"),
        "status": field_eq("status"),
        "feed_state": field_eq("feed_state"),
    })


# ===========================================================================
# Laboratory tests
# ===========================================================================
@bp.post("/lab-tests")
@guard(["LabTechnician"])
def create_lab_test():
    payload = body()
    run = fk_ref(payload, "kiln_run_id", "kiln_runs")
    batch = fk_ref(payload, "cement_batch_id", "batches")
    test_type = want_enum(payload, "test_type", calc.TEST_TYPES)
    value = want_num(payload, "value")
    run_id = payload.get("kiln_run_id")
    batch_id = payload.get("cement_batch_id")
    # Rung 89 — exactly one subject, and of the kind the test type demands.
    if test_type == "FREE_LIME":
        if run_id is None or batch_id is not None or run is None:
            fail("ERR_TEST_SUBJECT_INVALID")
    else:
        if batch_id is None or run_id is not None or batch is None:
            fail("ERR_TEST_SUBJECT_INVALID")
    # Rung 90 — the subject must be in a testable condition.
    plant = None
    if test_type == "FREE_LIME":
        if run["process_state"] not in ("BURNING", "COMPLETED"):
            fail("ERR_LAB_SUBJECT_STATE_INVALID")
        kiln = get_row("kilns", run["kiln_id"])
        plant = get_row("plants", kiln["plant_id"]) if kiln is not None else None
    else:
        if batch["status"] != "GROUND":
            fail("ERR_LAB_SUBJECT_STATE_INVALID")
    bounds = calc.lab_spec_bounds(test_type, value, plant=plant, batch=batch)
    row = new_row("lab_tests", common_fields=False)
    row.update({
        "test_type": test_type,
        "kiln_run_id": run["id"] if run is not None and test_type == "FREE_LIME" else None,
        "cement_batch_id": batch["id"] if batch is not None and test_type != "FREE_LIME" else None,
        "value": value,
        "unit": bounds["unit"],
        "spec_min": bounds["spec_min"],
        "spec_max": bounds["spec_max"],
        "in_spec": bounds["in_spec"],
        "recorded_by_user_id": actor(),
    })
    put_row("lab_tests", row)
    if test_type == "FREE_LIME":
        cascades.apply_free_lime_result(run, plant, value)
    else:
        cascades.apply_cement_result(batch, test_type, bounds["in_spec"])
    return respond_object(serial.lab_test_out(row), 201)


@bp.get("/lab-tests/<lab_test_id>")
@guard(READ)
def get_lab_test(lab_test_id):
    return respond_object(serial.lab_test_out(path_row("lab_tests", lab_test_id)))


@bp.get("/lab-tests")
@guard(READ)
def list_lab_tests():
    return filtered_list("lab_tests", serial.lab_test_out, {
        "kiln_run_id": field_eq("kiln_run_id"),
        "cement_batch_id": field_eq("cement_batch_id"),
        "test_type": field_eq("test_type"),
    })
