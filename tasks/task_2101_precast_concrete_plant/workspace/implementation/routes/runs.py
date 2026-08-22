"""Bed runs: scheduling, tensioning, casting, release, stripping (PRD 3.3-3.6)
and the curing cycles that hang off them (PRD 3.4)."""
from flask import Blueprint

import auth
import calc
import cascade
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("runs", __name__)


# ---------------------------------------------------------------------------
# Scheduling a bed run (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.post("/bed-runs")
def create_bed_run():
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    body = validation.get_body()
    bed_id = validation.req_id(body, "bed_id")
    mix_id = validation.req_id(body, "mix_design_id")
    start = validation.req_datetime(body, "scheduled_start")
    end = validation.req_datetime(body, "scheduled_end")
    validation.require_interval(start, end, "scheduled_start", "scheduled_end")

    bed = lookup.casting_bed(bed_id)
    mix = lookup.mix_design(mix_id)

    if mix["status"] != "QUALIFIED":
        errors.fail(errors.ERR_MIX_DESIGN_NOT_QUALIFIED,
                    "The mix design is not QUALIFIED.")
    if calc.bed_occupancy_conflict(bed, start, end):
        errors.fail(errors.ERR_BED_OCCUPIED,
                    "The bed is occupied for part of this window.")

    row = db.new_row(db.store.bed_runs, {
        "bed_id": bed_id,
        "mix_design_id": mix_id,
        "scheduled_start": db.iso_millis(start),
        "scheduled_end": db.iso_millis(end),
        "status": "SCHEDULED",
        "blocked_reason": None,
        "strand_count": None,
        "strand_diameter_in": None,
        "measured_elongation_in": None,
        "theoretical_elongation_in": None,
        "elongation_deviation_pct": None,
        "computed_jacking_force_kips": None,
        "cast_at": None,
        "released_at": None,
        "concrete_cost_cents": None,
        "strand_cost_cents": None,
        "energy_cost_cents": None,
        "form_setup_cents": None,
        "direct_subtotal_cents": None,
        "overhead_rate_pct": None,
        "overhead_cents": None,
        "total_cost_cents": None,
    })
    db.mark_fresh(row)
    return response.object_response(serialize.bed_run(row), 201)


@bp.get("/bed-runs/<run_id>")
def get_bed_run(run_id):
    auth.require_any()
    row = lookup.bed_run(run_id)
    return response.object_response(serialize.bed_run(row), 200)


@bp.get("/bed-runs")
def list_bed_runs():
    auth.require_any()
    bed_id = validation.query_filter("bed_id")
    mix_id = validation.query_filter("mix_design_id")
    status = validation.query_filter("status")
    rows = [r for r in db.store.bed_runs.values()
            if (bed_id is None or r["bed_id"] == bed_id)
            and (mix_id is None or r["mix_design_id"] == mix_id)
            and (status is None or r["status"] == status)]
    return listing.list_response(rows, serialize.bed_run)


# ---------------------------------------------------------------------------
# Tensioning (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.post("/bed-runs/<run_id>/tension")
def tension(run_id):
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    run = lookup.bed_run(run_id)
    body = validation.get_body()
    strand_count = validation.req_int(body, "strand_count", exclusive_min=0)
    diameter = validation.req_decimal_choice(body, "strand_diameter_in",
                                             constants.STRAND_DIAMETERS)
    measured = validation.req_number(body, "measured_elongation_in")

    if run["status"] != "SCHEDULED":
        errors.fail(errors.ERR_BED_RUN_INVALID_STATE,
                    "Only a SCHEDULED run may be tensioned.")
    bed = db.store.casting_beds[run["bed_id"]]
    mix = db.store.mix_designs[run["mix_design_id"]]
    if bed["status"] != "AVAILABLE":
        errors.fail(errors.ERR_PLANT_RESOURCE_UNAVAILABLE,
                    "The casting bed is not AVAILABLE.")
    if mix["status"] != "QUALIFIED":
        errors.fail(errors.ERR_MIX_DESIGN_NOT_QUALIFIED,
                    "The mix design is not QUALIFIED.")

    force, theoretical, deviation = calc.strand_jacking_force(
        bed, mix, strand_count, diameter, measured)

    if abs(deviation) > constants.ELONGATION_TOLERANCE_PCT:
        errors.fail(errors.ERR_ELONGATION_OUT_OF_TOLERANCE,
                    "Measured elongation deviates by %s percent." % deviation)
    if force > calc.Decimal(bed["max_strand_force_kips"]):
        errors.fail(errors.ERR_BED_STRAND_CAPACITY_EXCEEDED,
                    "Jacking force %s kips exceeds the bed's abutment capacity."
                    % force)

    run["status"] = "TENSIONED"
    run["strand_count"] = strand_count
    run["strand_diameter_in"] = diameter
    run["measured_elongation_in"] = measured
    run["computed_jacking_force_kips"] = force
    run["theoretical_elongation_in"] = theoretical
    run["elongation_deviation_pct"] = deviation
    db.touch(run)

    bed["status"] = "OCCUPIED"
    db.touch(bed)
    return response.object_response(serialize.bed_run(run), 200)


@bp.post("/bed-runs/<run_id>/abort-tensioning")
def abort_tensioning(run_id):
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    run = lookup.bed_run(run_id)
    body = validation.get_body()
    validation.req_text(body, "reason")

    if run["status"] != "TENSIONED":
        errors.fail(errors.ERR_BED_RUN_INVALID_STATE,
                    "Only a TENSIONED run may be aborted.")

    run["status"] = "SCHEDULED"
    run["strand_count"] = None
    run["strand_diameter_in"] = None
    run["measured_elongation_in"] = None
    run["theoretical_elongation_in"] = None
    run["elongation_deviation_pct"] = None
    run["computed_jacking_force_kips"] = None
    db.touch(run)

    bed = db.store.casting_beds[run["bed_id"]]
    bed["status"] = "AVAILABLE"
    db.touch(bed)
    return response.object_response(serialize.bed_run(run), 200)


# ---------------------------------------------------------------------------
# Casting (PRD 3.4)
# ---------------------------------------------------------------------------
@bp.post("/bed-runs/<run_id>/cast")
def cast(run_id):
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    run = lookup.bed_run(run_id)
    if run["status"] != "TENSIONED":
        errors.fail(errors.ERR_BED_RUN_INVALID_STATE,
                    "Only a TENSIONED run may be cast.")
    mix = db.store.mix_designs[run["mix_design_id"]]
    if mix["status"] != "QUALIFIED":
        errors.fail(errors.ERR_MIX_DESIGN_NOT_QUALIFIED,
                    "The mix design is not QUALIFIED.")
    assigned = [p for p in db.store.pieces.values()
                if p["bed_run_id"] == run["id"]
                and p["production_status"] != "SCRAPPED"]
    if len(assigned) < 1:
        errors.fail(errors.ERR_NO_PIECES_ASSIGNED,
                    "The run has no assigned pieces.")

    run["status"] = "CURING"
    run["cast_at"] = db.store.now_iso()
    db.touch(run)

    for piece in db.store.pieces.values():
        if piece["bed_run_id"] != run["id"] or piece["production_status"] != "SCHEDULED":
            continue
        piece["production_status"] = "CAST"
        if piece["qc_status"] == "PENDING":
            piece["qc_status"] = "HOLD"
            piece["qc_hold_reason"] = "AWAITING_RELEASE_STRENGTH"
        db.touch(piece)
        cascade.touch_project_of(piece)

    for cycle in db.store.curing_cycles.values():
        if cycle["bed_run_id"] == run["id"] and cycle["status"] == "SCHEDULED":
            cycle["status"] = "RUNNING"
            db.touch(cycle)

    return response.object_response(serialize.bed_run(run), 200)


# ---------------------------------------------------------------------------
# Requesting the detensioning release (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.post("/bed-runs/<run_id>/request-release")
def request_release(run_id):
    user_id, _role = auth.require(constants.ROLE_QUALITY_ENGINEER)
    run = lookup.bed_run(run_id)

    if run["status"] not in ("CURING", "RELEASE_READY"):
        errors.fail(errors.ERR_BED_RUN_INVALID_STATE,
                    "The run is not awaiting release.")

    mix = db.store.mix_designs[run["mix_design_id"]]
    release_sets = [s for s in cascade.run_cylinder_sets(run["id"])
                    if s["purpose"] == "RELEASE"]
    if not release_sets:
        errors.fail(errors.ERR_RELEASE_SET_MISSING,
                    "The run has no RELEASE cylinder set.")
    if not cascade.curing_complete(run["id"]):
        errors.fail(errors.ERR_CURING_NOT_COMPLETE,
                    "Every curing cycle of the run must be COMPLETED.")
    qualified_sets = [s for s in release_sets
                      if s["qualified_strength_psi"] is not None]
    if not qualified_sets:
        errors.fail(errors.ERR_NO_VALID_SPECIMENS,
                    "The release set has no qualified strength.")
    passing = [s for s in qualified_sets
               if s["qualified_strength_psi"] >= mix["required_release_psi"]]
    if not passing:
        errors.fail(errors.ERR_RELEASE_STRENGTH_NOT_MET,
                    "The qualified strength is below the required release strength.")

    signing_set = passing[0]
    if user_id in signing_set["recorded_by_user_ids"]:
        errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                    "The signer recorded a break on the release set.")

    run["status"] = "RELEASED"
    run["released_at"] = db.store.now_iso()
    db.touch(run)
    return response.object_response(serialize.bed_run(run), 200)


# ---------------------------------------------------------------------------
# Stripping and cost allocation (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/bed-runs/<run_id>/strip")
def strip(run_id):
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    run = lookup.bed_run(run_id)
    if run["status"] != "RELEASED":
        errors.fail(errors.ERR_BED_RUN_INVALID_STATE,
                    "Only a RELEASED run may be stripped.")

    bed = db.store.casting_beds[run["bed_id"]]
    mix = db.store.mix_designs[run["mix_design_id"]]
    fields, allocations = calc.bed_run_cost_allocation(run, bed, mix)

    run.update(fields)
    run["status"] = "STRIPPED"
    db.touch(run)

    for piece, allocated in allocations:
        piece["allocated_cost_cents"] = allocated
        piece["production_status"] = "STRIPPED"
        db.touch(piece)
        cascade.touch_project_of(piece)

    bed["status"] = "AVAILABLE"
    db.touch(bed)
    return response.object_response(serialize.bed_run(run), 200)


# ---------------------------------------------------------------------------
# Curing cycles (PRD 3.4)
# ---------------------------------------------------------------------------
@bp.post("/bed-runs/<run_id>/curing-cycles")
def create_curing_cycle(run_id):
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    run = lookup.bed_run(run_id)
    body = validation.get_body()
    zone_id = validation.req_id(body, "steam_zone_id")
    start = validation.req_datetime(body, "planned_start")
    end = validation.req_datetime(body, "planned_end")
    validation.require_interval(start, end, "planned_start", "planned_end")
    ramp = validation.req_number(body, "ramp_rate_f_per_hr", exclusive_min=0)
    soak_temp = validation.req_number(body, "soak_temp_f", exclusive_min=60)
    soak_hours = validation.req_number(body, "soak_hours", exclusive_min=0)
    demand = validation.req_number(body, "steam_demand_bhp", exclusive_min=0)

    zone = lookup.steam_zone(zone_id)

    candidate = {
        "planned_start": db.iso_millis(start),
        "planned_end": db.iso_millis(end),
        "steam_demand_bhp": demand,
    }
    peak = calc.steam_peak_demand(zone_id, candidate)
    if peak > calc.Decimal(zone["boiler_capacity_bhp"]):
        errors.fail(errors.ERR_STEAM_CAPACITY_EXCEEDED,
                    "Peak concurrent demand of %s bhp exceeds the zone capacity."
                    % peak)

    row = db.new_row(db.store.curing_cycles, {
        "bed_run_id": run["id"],
        "steam_zone_id": zone_id,
        "planned_start": db.iso_millis(start),
        "planned_end": db.iso_millis(end),
        "ramp_rate_f_per_hr": ramp,
        "soak_temp_f": soak_temp,
        "soak_hours": soak_hours,
        "steam_demand_bhp": demand,
        "status": "SCHEDULED",
        "metered_therms": None,
        "modeled_therms": calc.modeled_therms(soak_temp, ramp, soak_hours, demand),
        "energy_therms": None,
        "energy_source": None,
        "energy_variance_pct": None,
        "variance_flagged": False,
        "energy_cost_cents": None,
    })
    db.mark_fresh(row)
    return response.object_response(serialize.curing_cycle(row), 201)


@bp.get("/bed-runs/<run_id>/curing-cycles")
def list_run_cycles(run_id):
    auth.require_any()
    lookup.bed_run(run_id)
    rows = [c for c in db.store.curing_cycles.values() if c["bed_run_id"] == run_id]
    return listing.list_response(rows, serialize.curing_cycle)


@bp.post("/curing-cycles/<cycle_id>/complete")
def complete_curing_cycle(cycle_id):
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    cycle = lookup.curing_cycle(cycle_id)
    body = validation.get_body()
    metered = validation.opt_number(body, "metered_therms")

    if cycle["status"] != "RUNNING":
        errors.fail(errors.ERR_CURING_CYCLE_INVALID_STATE,
                    "Only a RUNNING curing cycle may be completed.")

    zone = db.store.steam_zones[cycle["steam_zone_id"]]
    calc.complete_energy(cycle, zone, metered)
    cycle["status"] = "COMPLETED"
    db.touch(cycle)

    run = db.store.bed_runs.get(cycle["bed_run_id"])
    if run is not None:
        cascade.evaluate_release_ready(run)
    return response.object_response(serialize.curing_cycle(cycle), 200)
