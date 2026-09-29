"""Kiln runs and kiln outages (PRD 3.4, 3.5, 3.6)."""

from datetime import timedelta

from flask import Blueprint

from core import (
    API_PREFIX, INTERNAL_ROLES,
    D, ZERO, rnd, r2, guard, body, fail, actor, actor_role, now,
    want_str, want_num, want_bool, want_enum, want_dt,
    fk_ref, path_row, put_row, new_row, touch, get_row, rows, ordered,
    respond_object, filtered_list, field_eq, hours_between,
)
import calc
import cascades
import serial

bp = Blueprint("kiln", __name__, url_prefix=API_PREFIX)

READ = INTERNAL_ROLES


def _closed_overlap(a_start, a_end, b_start, b_end):
    """PRD 3.4: run-versus-run windows are closed on both ends."""
    return a_start <= b_end and b_start <= a_end


def _half_open_overlap(a_start, a_end, b_start, b_end):
    """PRD 3.4 / 3.9: outage-versus-outage and spout windows merely touching."""
    return a_start < b_end and b_start < a_end


def _clearance_ok(run_start, run_end, out_start, out_end, buffer_hours):
    buffer = timedelta(hours=buffer_hours)
    return (run_end + buffer <= out_start) or (out_end + buffer <= run_start)


def _window_ordering(start, end):
    """Rung 81 — shared by kiln runs, outages and loadout orders."""
    if not (start < end) or start < now():
        fail("ERR_INVALID_WINDOW")


# ===========================================================================
# Kiln runs
# ===========================================================================
@bp.post("/kiln-runs")
@guard(["KilnOperator", "ProcessEngineer"])
def create_run():
    payload = body()
    kiln = fk_ref(payload, "kiln_id", "kilns")
    pile = fk_ref(payload, "blended_pile_id", "piles")
    silo = fk_ref(payload, "clinker_silo_id", "silos")
    want_str(payload, "kiln_id")
    want_str(payload, "blended_pile_id")
    want_str(payload, "clinker_silo_id")
    window_start = want_dt(payload, "window_start")
    window_end = want_dt(payload, "window_end")
    _window_ordering(window_start, window_end)
    for other in rows("kiln_runs"):
        if other["kiln_id"] != kiln["id"]:
            continue
        if other["process_state"] not in ("SCHEDULED", "BURNING", "COMPLETED"):
            continue
        if _closed_overlap(window_start, window_end,
                           other["window_start"], other["window_end"]):
            fail("ERR_KILN_WINDOW_CONFLICT")
    for outage in rows("outages"):
        if outage["kiln_id"] != kiln["id"]:
            continue
        if outage["status"] not in ("APPROVED", "IN_PROGRESS"):
            continue
        if not _clearance_ok(window_start, window_end,
                             outage["window_start"], outage["window_end"],
                             kiln["cooldown_buffer_hours"]):
            fail("ERR_KILN_WINDOW_CONFLICT")
    if silo["material_kind"] != "CLINKER" or silo["plant_id"] != kiln["plant_id"]:
        fail("ERR_SILO_KIND_MISMATCH")
    row = new_row("kiln_runs")
    row.update({
        "kiln_id": kiln["id"],
        "blended_pile_id": pile["id"],
        "clinker_silo_id": silo["id"],
        "window_start": window_start,
        "window_end": window_end,
        "scheduled_hours": hours_between(window_start, window_end),
        "process_state": "SCHEDULED",
        "quality_state": "PENDING_LAB",
        "fuel_charges": [],
        "lit_at": None,
        "completed_at": None,
        "abort_reason": None,
    })
    calc.recompute_run_thermal(row, kiln)
    put_row("kiln_runs", row)
    return respond_object(serial.run_out(row), 201)


@bp.post("/kiln-runs/<kiln_run_id>/light")
@guard(["KilnOperator"])
def light_run(kiln_run_id):
    run = path_row("kiln_runs", kiln_run_id)
    if run["process_state"] != "SCHEDULED":
        fail("ERR_INVALID_RUN_STATE")
    kiln = get_row("kilns", run["kiln_id"])
    if calc.kiln_availability_state(kiln) != "AVAILABLE":
        fail("ERR_KILN_UNAVAILABLE")
    for other in rows("kiln_runs"):
        if (other["id"] != run["id"] and other["kiln_id"] == kiln["id"]
                and other["process_state"] == "BURNING"):
            fail("ERR_KILN_UNAVAILABLE")
    pile = get_row("piles", run["blended_pile_id"])
    if pile is None or pile["status"] != "SEALED":
        fail("ERR_INVALID_PILE_STATE")
    if not (run["window_start"] <= now() < run["window_end"]):
        fail("ERR_RUN_WINDOW_NOT_ACTIVE")
    run["process_state"] = "BURNING"
    run["lit_at"] = now()
    touch(run)
    pile["status"] = "CONSUMED"
    touch(pile)
    design = get_row("designs", pile["raw_mix_design_id"])
    if design is not None:
        touch(design)
    return respond_object(serial.run_out(run))


@bp.post("/kiln-runs/<kiln_run_id>/fuel-charges")
@guard(["KilnOperator"])
def charge_fuel(kiln_run_id):
    run = path_row("kiln_runs", kiln_run_id)
    payload = body()
    fuel = fk_ref(payload, "fuel_id", "fuels")
    want_str(payload, "fuel_id")
    tonnes = want_num(payload, "tonnes")
    if run["process_state"] != "BURNING":
        fail("ERR_INVALID_RUN_STATE")
    kiln = get_row("kilns", run["kiln_id"])
    plant = get_row("plants", kiln["plant_id"])
    charge = {
        "fuel_id": fuel["id"],
        "tonnes": tonnes,
        "energy_gj": float(calc.charge_energy_gj(tonnes, fuel)),
        "charged_at": now(),
    }
    trial = run["fuel_charges"] + [charge]
    probe = dict(run)
    probe["fuel_charges"] = trial
    calc.recompute_run_thermal(probe, kiln, trial)
    # Rung 70 — the chlorine safety stop outranks the authorisation window.
    if D(probe["chlorine_input_kg"]) > D(plant["permit_max_chlorine_kg_per_run"]):
        fail("ERR_CHLORINE_INPUT_EXCEEDED")
    charged_authorized = True
    if fuel.get("is_alternative"):
        charged_authorized = calc.applicable_authorization(plant["id"], fuel["id"]) is not None
    # Rung 72 — only computable once the charged alternative fuel is authorised.
    if charged_authorized:
        ceiling = calc.effective_tsr_ceiling(plant, trial)
        if D(probe["tsr_pct"]) > ceiling:
            fail("ERR_TSR_CAP_EXCEEDED")
    # Rung 80 — authorisation currency for the charged alternative fuel.
    if fuel.get("is_alternative") and not charged_authorized:
        if not calc.authorized_rows_exist(plant["id"], fuel["id"]):
            fail("ERR_BURN_TEST_NOT_AUTHORIZED")
        fail("ERR_BURN_TEST_EXPIRED")
    # Rung 100 — the annual NOx budget must not go negative.
    consumed = ZERO
    for other in calc.plant_runs(plant["id"]):
        if other["id"] == run["id"]:
            continue
        if other["process_state"] in ("SCHEDULED", "BURNING", "COMPLETED"):
            consumed += D(other["nox_emitted_kg"])
    consumed += D(probe["nox_emitted_kg"])
    if r2(D(plant["permit_annual_nox_budget_kg"]) - consumed) < 0:
        fail("ERR_NOX_BUDGET_EXCEEDED")
    run["fuel_charges"] = trial
    calc.recompute_run_thermal(run, kiln, trial)
    touch(run)
    return respond_object(serial.run_out(run))


@bp.post("/kiln-runs/<kiln_run_id>/complete")
@guard(["KilnOperator"])
def complete_run(kiln_run_id):
    run = path_row("kiln_runs", kiln_run_id)
    if run["process_state"] != "BURNING" or not run["fuel_charges"]:
        fail("ERR_INVALID_RUN_STATE")
    silo = get_row("silos", run["clinker_silo_id"])
    if silo is None or silo["status"] != "OPEN":
        fail("ERR_SILO_BLOCKED")
    if now() < run["window_end"]:
        fail("ERR_RUN_WINDOW_NOT_ELAPSED")
    clinker = D(run["clinker_tonnes"])
    feed_needed = rnd(clinker * calc.KILN_FEED_FACTOR, 2)
    pile = get_row("piles", run["blended_pile_id"])
    if pile is None or feed_needed > D(pile["dry_tonnes"]):
        fail("ERR_INSUFFICIENT_KILN_FEED")
    if D(silo["tonnes_on_hand"]) + clinker > D(silo["capacity_tonnes"]):
        fail("ERR_SILO_CAPACITY_EXCEEDED")
    run["process_state"] = "COMPLETED"
    run["completed_at"] = now()
    touch(run)
    silo["tonnes_on_hand"] = r2(D(silo["tonnes_on_hand"]) + clinker)
    silo["unreleased_tonnes"] = r2(D(silo["unreleased_tonnes"]) + clinker)
    touch(silo)
    pile["consumed_dry_tonnes"] = float(feed_needed)
    touch(pile)
    kiln = get_row("kilns", run["kiln_id"])
    if kiln is not None:
        accrued = int(rnd(D(run["scheduled_hours"]), 0))
        kiln["refractory_hours_since_reline"] = kiln["refractory_hours_since_reline"] + accrued
        touch(kiln)
    return respond_object(serial.run_out(run))


@bp.post("/kiln-runs/<kiln_run_id>/abort")
@guard(["KilnOperator"])
def abort_run(kiln_run_id):
    run = path_row("kiln_runs", kiln_run_id)
    payload = body()
    reason = want_str(payload, "abort_reason")
    if run["process_state"] != "BURNING":
        fail("ERR_INVALID_RUN_STATE")
    run["process_state"] = "ABORTED"
    run["abort_reason"] = reason
    run["nox_emitted_kg"] = 0.0
    run["clinker_tonnes"] = 0.0
    touch(run)
    return respond_object(serial.run_out(run))


@bp.post("/kiln-runs/<kiln_run_id>/release-clinker")
@guard(["QualityManager"])
def release_clinker(kiln_run_id):
    run = path_row("kiln_runs", kiln_run_id)
    if run["process_state"] != "COMPLETED" or run["quality_state"] != "PENDING_LAB":
        fail("ERR_INVALID_RUN_STATE")
    silo = get_row("silos", run["clinker_silo_id"])
    if silo is None or silo["status"] != "OPEN":
        fail("ERR_SILO_BLOCKED")
    kiln = get_row("kilns", run["kiln_id"])
    plant = get_row("plants", kiln["plant_id"])
    newest = calc.newest_lab_test("kiln_run_id", run["id"], "FREE_LIME")
    if newest is None or D(newest["value"]) > D(plant["clinker_free_lime_max_pct"]):
        fail("ERR_FREE_LIME_OUT_OF_SPEC")
    rolling = calc.rolling_nox_intensity(plant)
    if D(rolling) > D(plant["permit_nox_kg_per_tonne_clinker_cap"]):
        fail("ERR_PERMIT_NOX_INTENSITY_EXCEEDED")
    run["quality_state"] = "RELEASED"
    touch(run)
    cascades.release_clinker_cascade(run, silo)
    return respond_object(serial.run_out(run))


@bp.get("/kiln-runs/<kiln_run_id>")
@guard(READ)
def get_run(kiln_run_id):
    return respond_object(serial.run_out(path_row("kiln_runs", kiln_run_id)))


@bp.get("/kiln-runs")
@guard(READ)
def list_runs():
    return filtered_list("kiln_runs", serial.run_out, {
        "kiln_id": field_eq("kiln_id"),
        "blended_pile_id": field_eq("blended_pile_id"),
        "clinker_silo_id": field_eq("clinker_silo_id"),
        "process_state": field_eq("process_state"),
        "quality_state": field_eq("quality_state"),
    })


# ===========================================================================
# Kiln outages
# ===========================================================================
def _outage_window_free(outage_id, kiln, window_start, window_end):
    """Rung 87 — re-checked at planning time and again at approval time."""
    for run in rows("kiln_runs"):
        if run["kiln_id"] != kiln["id"]:
            continue
        if run["process_state"] not in ("SCHEDULED", "BURNING"):
            continue
        if not _clearance_ok(run["window_start"], run["window_end"],
                             window_start, window_end,
                             kiln["cooldown_buffer_hours"]):
            fail("ERR_OUTAGE_WINDOW_CONFLICT")
    for other in rows("outages"):
        if other["kiln_id"] != kiln["id"] or other["id"] == outage_id:
            continue
        if other["status"] not in ("PLANNED", "APPROVED", "IN_PROGRESS"):
            continue
        if _half_open_overlap(window_start, window_end,
                              other["window_start"], other["window_end"]):
            fail("ERR_OUTAGE_WINDOW_CONFLICT")


@bp.post("/kiln-outages")
@guard(["PlantAdmin", "ProcessEngineer"])
def create_outage():
    payload = body()
    kiln = fk_ref(payload, "kiln_id", "kilns")
    want_str(payload, "kiln_id")
    window_start = want_dt(payload, "window_start")
    window_end = want_dt(payload, "window_end")
    scope = want_enum(payload, "scope", calc.OUTAGE_SCOPES)
    override = want_bool(payload, "peak_season_override", required=False, default=False)
    override = False if override is None else override
    _window_ordering(window_start, window_end)
    _outage_window_free(None, kiln, window_start, window_end)
    plant = get_row("plants", kiln["plant_id"])
    season = calc.demand_season_class(plant, window_start, window_end)
    if season == "PEAK" and not (override and actor_role() == "PlantAdmin"):
        fail("ERR_PEAK_SEASON_OUTAGE")
    row = new_row("outages")
    row.update({
        "kiln_id": kiln["id"],
        "window_start": window_start,
        "window_end": window_end,
        "scope": scope,
        "peak_season_override": override,
        "demand_season_class": season,
        "status": "PLANNED",
        "refractory_replaced": False,
        "approved_by_user_id": None,
        "started_at": None,
        "completed_at": None,
    })
    put_row("outages", row)
    return respond_object(serial.outage_out(row), 201)


@bp.post("/kiln-outages/<outage_id>/approve")
@guard(["PlantAdmin"])
def approve_outage(outage_id):
    outage = path_row("outages", outage_id)
    if outage["status"] != "PLANNED":
        fail("ERR_INVALID_OUTAGE_STATE")
    kiln = get_row("kilns", outage["kiln_id"])
    _outage_window_free(outage["id"], kiln, outage["window_start"], outage["window_end"])
    outage["status"] = "APPROVED"
    outage["approved_by_user_id"] = actor()
    touch(outage)
    return respond_object(serial.outage_out(outage))


@bp.post("/kiln-outages/<outage_id>/start")
@guard(["ProcessEngineer"])
def start_outage(outage_id):
    outage = path_row("outages", outage_id)
    if outage["status"] != "APPROVED":
        fail("ERR_INVALID_OUTAGE_STATE")
    kiln = get_row("kilns", outage["kiln_id"])
    for run in rows("kiln_runs"):
        if run["kiln_id"] == kiln["id"] and run["process_state"] == "BURNING":
            fail("ERR_KILN_UNAVAILABLE")
    if now() < outage["window_start"]:
        fail("ERR_INVALID_WINDOW")
    outage["status"] = "IN_PROGRESS"
    outage["started_at"] = now()
    touch(outage)
    touch(kiln)
    return respond_object(serial.outage_out(outage))


@bp.post("/kiln-outages/<outage_id>/complete")
@guard(["ProcessEngineer"])
def complete_outage(outage_id):
    outage = path_row("outages", outage_id)
    payload = body()
    replaced = want_bool(payload, "refractory_replaced")
    if outage["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_OUTAGE_STATE")
    if now() < outage["window_start"]:
        fail("ERR_INVALID_WINDOW")
    outage["status"] = "COMPLETED"
    outage["completed_at"] = now()
    outage["refractory_replaced"] = replaced
    touch(outage)
    kiln = get_row("kilns", outage["kiln_id"])
    if kiln is not None:
        if replaced:
            kiln["refractory_hours_since_reline"] = 0
        touch(kiln)
    return respond_object(serial.outage_out(outage))


@bp.get("/kiln-outages/<outage_id>")
@guard(READ)
def get_outage(outage_id):
    return respond_object(serial.outage_out(path_row("outages", outage_id)))


@bp.get("/kiln-outages")
@guard(READ)
def list_outages():
    return filtered_list("outages", serial.outage_out, {
        "kiln_id": field_eq("kiln_id"),
        "status": field_eq("status"),
        "demand_season_class": field_eq("demand_season_class"),
    })
