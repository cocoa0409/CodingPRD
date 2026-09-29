"""PRD 3.6, 3.7 and the assembly half of 3.8 — stator builds, rotor builds and
assembly records."""

import datetime
from decimal import Decimal

from flask import Blueprint

from auth import authorize
from calc import (CAGE_CONDUCTIVITY_RATIO, GREASE_FILL_PCT_RANGE,
                  INSULATION_SYSTEM_CLASS, MAX_SLOT_FILL_PCT, MIN_SLOT_FILL_PCT,
                  ROTOR_PROCESS_COST_CENTS, SHAFT_FIT_LIMITS_UM, SLIP_PENALTY_PCT,
                  achieved_capability_kv, insulation_margin_kv,
                  permissible_unbalance_g_mm, required_surge_kv, rhu,
                  rotor_air_gap, shaft_fit_deviation_um, work_order_cost)
from envelope import created, paginate, single
from errors import fail
from helpers import eq_filter, load, rows
from ledgers import recompute_oven
from store import base_row, by_created_at, db, touch
from validate import (interval, opt_str, parse_body, present, req_enum,
                      req_instant, req_int, req_num, req_str)

bp = Blueprint("builds", __name__)

INSULATION_SYSTEMS = tuple(INSULATION_SYSTEM_CLASS.keys())
VARNISH_PROCESSES = ("DIP_BAKE", "VPI", "TRICKLE")
BALANCE_GRADES = ("G1_0", "G2_5", "G6_3")
BEARING_INSTALL_METHODS = ("INDUCTION_HEAT", "PRESS", "OIL_BATH")
DISPOSITIONS = ("ACCEPTED", "REJECTED")

SUBASSEMBLY_READERS = ("BuildTechnician", "TestEngineer", "QualityCertifier",
                       "ProductionPlanner", "PlantAdmin")

LIVE_EXCLUDED = ("REJECTED", "SCRAPPED")


def pinned_design(work_order):
    return db.designs[work_order["design_id"]]


def count_reject_surcharge(work_order):
    """PRD 3.5 — recompute cost whenever rework_reject_count changes."""
    work_order["per_unit_direct_cost_cents"] = work_order_cost(
        work_order, pinned_design(work_order))


def fork_join(work_order):
    """PRD 3.7 — RELEASED to SUBASSEMBLIES_DONE the moment at least one stator
    build and at least one rotor build on the work order are ACCEPTED."""
    if work_order["build_status"] != "RELEASED":
        return
    stator = any(b["work_order_id"] == work_order["id"] and b["status"] == "ACCEPTED"
                 for b in db.stator_builds.values())
    rotor = any(b["work_order_id"] == work_order["id"] and b["status"] == "ACCEPTED"
                for b in db.rotor_builds.values())
    if stator and rotor:
        work_order["build_status"] = "SUBASSEMBLIES_DONE"
        touch(work_order)


def has_live_build(table, work_order_id):
    return any(b["work_order_id"] == work_order_id and b["status"] not in LIVE_EXCLUDED
               for b in table.values())


# ---------------------------------------------------------------------------
# Stator builds
# ---------------------------------------------------------------------------

@bp.post("/stator-builds")
def create_stator():
    user_id, _role = authorize("BuildTechnician")
    body = parse_body()
    work_order_id = req_str(body, "work_order_id")
    insulation_system = req_enum(body, "insulation_system", INSULATION_SYSTEMS)
    slot_fill_pct = req_num(body, "slot_fill_pct", places=2)

    work_order = load("work_orders", work_order_id)
    if work_order["build_status"] != "RELEASED":
        fail("ERR_INVALID_WORK_ORDER_STATE",
             "A stator may only be wound against a RELEASED work order.")

    design = pinned_design(work_order)
    if INSULATION_SYSTEM_CLASS[insulation_system] != design["insulation_class"]:
        fail("ERR_INSULATION_SYSTEM_MISMATCH",
             "The applied insulation system does not match the design's thermal class.")

    if has_live_build(db.stator_builds, work_order_id):
        fail("ERR_DUPLICATE_ACTIVE_SUBASSEMBLY",
             "This work order already holds a live stator build.")

    if slot_fill_pct < MIN_SLOT_FILL_PCT or slot_fill_pct > MAX_SLOT_FILL_PCT:
        fail("ERR_SLOT_FILL_OUT_OF_RANGE",
             "Slot fill must lie between 78.00 and 86.00 percent inclusive.")

    row = base_row()
    row.update({
        "work_order_id": work_order_id,
        "insulation_system": insulation_system,
        "slot_fill_pct": slot_fill_pct,
        "status": "WOUND",
        "winder_user_id": user_id,
        "required_surge_kv": required_surge_kv(design["rated_voltage_v"],
                                              design["insulation_class"]),
        "achieved_capability_kv": None,
        "oven_id": None,
        "impregnation_window_start": None,
        "impregnation_window_end": None,
        "impregnation_minutes": None,
        "varnish_process": None,
        "varnish_cycles": None,
        "cure_temp_c": None,
        "surge_test_kv": None,
        "surge_tester_user_id": None,
        "surge_test_result": None,
        "insulation_margin_kv": None,
        "disposition_notes": None,
    })
    db.stator_builds[row["id"]] = row
    touch(work_order)
    return created({k: v for k, v in row.items() if not k.startswith("_")})


@bp.get("/stator-builds/<row_id>")
def read_stator(row_id):
    authorize(*SUBASSEMBLY_READERS)
    return single(load("stator_builds", row_id))


@bp.get("/stator-builds")
def list_stators():
    authorize(*SUBASSEMBLY_READERS)
    collection = rows("stator_builds")
    collection = eq_filter(collection, "work_order_id")
    collection = eq_filter(collection, "oven_id")
    collection = eq_filter(collection, "status")
    collection = eq_filter(collection, "varnish_process")
    return paginate(collection)


@bp.post("/stator-builds/<row_id>/impregnate")
def impregnate(row_id):
    authorize("BuildTechnician")
    # PRD 2.11 — the payload shape band is examined before existence checks, so
    # the path row is resolved softly here and only reported missing after the
    # body has been validated.
    build = db.stator_builds.get(row_id) if isinstance(row_id, str) else None
    body = parse_body()
    oven_id = req_str(body, "oven_id")
    window_start = req_instant(body, "impregnation_window_start")
    window_end = req_instant(body, "impregnation_window_end")
    interval(window_start, window_end,
             "impregnation_window_start", "impregnation_window_end")
    varnish_process = req_enum(body, "varnish_process", VARNISH_PROCESSES)
    varnish_cycles = req_int(body, "varnish_cycles", 1, 6)
    cure_temp_c = req_num(body, "cure_temp_c", places=1)

    if build is None:
        fail("ERR_SUBASSEMBLY_NOT_FOUND")
    oven = load("ovens", oven_id)
    if oven["status"] != "AVAILABLE":
        fail("ERR_RESOURCE_IN_MAINTENANCE", "The curing oven is in MAINTENANCE.")
    if build["status"] != "WOUND":
        fail("ERR_INVALID_SUBASSEMBLY_STATE", "Only a WOUND stator may be impregnated.")
    if cure_temp_c > oven["max_temp_c"]:
        fail("ERR_CURE_TEMP_EXCEEDS_OVEN_LIMIT",
             "The requested cure temperature exceeds the oven's ceiling.")

    buffer_delta = datetime.timedelta(minutes=oven["cooldown_buffer_minutes"])
    for other in by_created_at(list(db.stator_builds.values())):
        if other["id"] == build["id"]:
            continue
        if other.get("oven_id") != oven_id:
            continue
        if other["status"] not in ("IMPREGNATED", "SURGE_TESTED", "ACCEPTED"):
            continue
        effective_end = other["impregnation_window_end"] + buffer_delta
        if (window_start < effective_end
                and other["impregnation_window_start"] < window_end):
            fail("ERR_OVEN_WINDOW_CONFLICT",
                 "The requested window collides with a live booking on this oven.")

    build["oven_id"] = oven_id
    build["impregnation_window_start"] = window_start
    build["impregnation_window_end"] = window_end
    build["varnish_process"] = varnish_process
    build["varnish_cycles"] = varnish_cycles
    build["cure_temp_c"] = cure_temp_c
    build["impregnation_minutes"] = int(
        (window_end - window_start).total_seconds() // 60)
    build["achieved_capability_kv"] = achieved_capability_kv(
        build["required_surge_kv"], varnish_process, varnish_cycles)
    build["status"] = "IMPREGNATED"
    touch(build)
    recompute_oven(oven)
    return single(build)


@bp.post("/stator-builds/<row_id>/surge-test")
def surge_test(row_id):
    user_id, _role = authorize("TestEngineer")
    build = load("stator_builds", row_id)
    # PRD 2.9 — the surge tester must not be the winder.
    if build["winder_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The surge tester must not be the technician who wound the stator.")
    body = parse_body()
    surge_test_kv = req_num(body, "surge_test_kv", places=2)

    if build["status"] != "IMPREGNATED":
        fail("ERR_INVALID_SUBASSEMBLY_STATE",
             "Only an IMPREGNATED stator may be surge tested.")
    if surge_test_kv > build["achieved_capability_kv"]:
        fail("ERR_SURGE_OVERSTRESS",
             "The applied level exceeds the winding's impregnated capability.")
    if surge_test_kv < build["required_surge_kv"]:
        fail("ERR_SURGE_MARGIN_NEGATIVE",
             "The applied level is below the required surge envelope.")

    build["surge_test_kv"] = surge_test_kv
    build["surge_tester_user_id"] = user_id
    build["insulation_margin_kv"] = insulation_margin_kv(
        surge_test_kv, build["required_surge_kv"])
    build["surge_test_result"] = "PASS"
    build["status"] = "SURGE_TESTED"
    touch(build)
    return single(build)


@bp.post("/stator-builds/<row_id>/disposition")
def stator_disposition(row_id):
    authorize("TestEngineer")
    build = load("stator_builds", row_id)
    body = parse_body()
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    notes = opt_str(body, "disposition_notes", min_len=0)

    if disposition == "ACCEPTED":
        if build["status"] != "SURGE_TESTED" or build.get("surge_test_result") != "PASS":
            fail("ERR_INVALID_SUBASSEMBLY_STATE",
                 "Acceptance requires a SURGE_TESTED stator that passed its surge test.")
    else:
        if build["status"] not in ("WOUND", "IMPREGNATED", "SURGE_TESTED"):
            fail("ERR_INVALID_SUBASSEMBLY_STATE",
                 "Only a pre-terminal stator may be rejected.")

    work_order = db.work_orders[build["work_order_id"]]
    if notes is not None:
        build["disposition_notes"] = notes

    if disposition == "ACCEPTED":
        build["status"] = "ACCEPTED"
        touch(build)
        touch(work_order)
        fork_join(work_order)
    else:
        build["status"] = "REJECTED"
        touch(build)
        oven = db.ovens.get(build.get("oven_id")) if build.get("oven_id") else None
        if oven is not None:
            recompute_oven(oven)
        work_order["rework_reject_count"] = work_order["rework_reject_count"] + 1
        count_reject_surcharge(work_order)
        touch(work_order)

    return single(build)


# ---------------------------------------------------------------------------
# Rotor builds
# ---------------------------------------------------------------------------

@bp.post("/rotor-builds")
def create_rotor():
    user_id, _role = authorize("BuildTechnician")
    body = parse_body()
    work_order_id = req_str(body, "work_order_id")

    work_order = load("work_orders", work_order_id)
    if work_order["build_status"] != "RELEASED":
        fail("ERR_INVALID_WORK_ORDER_STATE",
             "A rotor may only be opened against a RELEASED work order.")
    if has_live_build(db.rotor_builds, work_order_id):
        fail("ERR_DUPLICATE_ACTIVE_SUBASSEMBLY",
             "This work order already holds a live rotor build.")

    design = pinned_design(work_order)
    row = base_row()
    row.update({
        "work_order_id": work_order_id,
        "status": "PLANNED",
        "rotor_tech_user_id": user_id,
        "construction": design["rotor_construction"],
        "cage_method": None,
        "melt_temp_c": None,
        "die_preheat_c": None,
        "braze_alloy": None,
        "bar_count": None,
        "cage_conductivity_ratio": None,
        "slip_penalty_pct": None,
        "rotor_process_cost_cents": None,
        "measured_rotor_od_mm": None,
        "rotor_mass_kg": None,
        "measured_air_gap_mm": None,
        "air_gap_deviation_mm": None,
        "balance_grade": None,
        "initial_unbalance_g_mm": None,
        "residual_unbalance_g_mm": None,
        "permissible_unbalance_g_mm": None,
        "disposition_notes": None,
    })
    db.rotor_builds[row["id"]] = row
    touch(work_order)
    return created({k: v for k, v in row.items() if not k.startswith("_")})


@bp.get("/rotor-builds/<row_id>")
def read_rotor(row_id):
    authorize(*SUBASSEMBLY_READERS)
    return single(load("rotor_builds", row_id))


@bp.get("/rotor-builds")
def list_rotors():
    authorize(*SUBASSEMBLY_READERS)
    collection = rows("rotor_builds")
    collection = eq_filter(collection, "work_order_id")
    collection = eq_filter(collection, "construction")
    collection = eq_filter(collection, "status")
    collection = eq_filter(collection, "balance_grade")
    return paginate(collection)


@bp.post("/rotor-builds/<row_id>/form-cage")
def form_cage(row_id):
    authorize("BuildTechnician")
    build = load("rotor_builds", row_id)
    body = parse_body()
    cage_method = req_enum(body, "cage_method", ("DIE_CAST", "BRAZED_BAR"))

    if build["status"] != "PLANNED":
        fail("ERR_INVALID_SUBASSEMBLY_STATE", "Only a PLANNED rotor may be formed.")

    work_order = db.work_orders[build["work_order_id"]]
    design = pinned_design(work_order)

    if cage_method == "DIE_CAST":
        if (build["construction"] != "DIE_CAST_ALUMINUM"
                or not present(body, "melt_temp_c")
                or not present(body, "die_preheat_c")
                or present(body, "braze_alloy")
                or present(body, "bar_count")):
            fail("ERR_ROTOR_CONSTRUCTION_MISMATCH",
                 "The DIE_CAST fork requires melt_temp_c and die_preheat_c on a "
                 "DIE_CAST_ALUMINUM rotor and forbids the brazing fields.")
        melt_temp_c = req_num(body, "melt_temp_c", places=1)
        die_preheat_c = req_num(body, "die_preheat_c", places=1)
        build["melt_temp_c"] = melt_temp_c
        build["die_preheat_c"] = die_preheat_c
        build["status"] = "CAST_POURED"
    else:
        if (build["construction"] != "FABRICATED_COPPER"
                or not present(body, "braze_alloy")
                or not present(body, "bar_count")
                or present(body, "melt_temp_c")
                or present(body, "die_preheat_c")):
            fail("ERR_ROTOR_CONSTRUCTION_MISMATCH",
                 "The BRAZED_BAR fork requires braze_alloy and bar_count on a "
                 "FABRICATED_COPPER rotor and forbids the die-casting fields.")
        braze_alloy = req_str(body, "braze_alloy", 1)
        bar_count = req_int(body, "bar_count")
        if bar_count != design["rotor_bar_count"]:
            fail("ERR_ROTOR_BAR_COUNT_MISMATCH",
                 "bar_count must equal the pinned design's rotor_bar_count.")
        build["braze_alloy"] = braze_alloy
        build["bar_count"] = bar_count
        build["status"] = "BARS_BRAZED"

    build["cage_method"] = cage_method
    build["cage_conductivity_ratio"] = CAGE_CONDUCTIVITY_RATIO[build["construction"]]
    build["slip_penalty_pct"] = SLIP_PENALTY_PCT[build["construction"]]
    build["rotor_process_cost_cents"] = ROTOR_PROCESS_COST_CENTS[build["construction"]]
    touch(build)
    return single(build)


@bp.post("/rotor-builds/<row_id>/machine")
def machine_rotor(row_id):
    authorize("BuildTechnician")
    build = load("rotor_builds", row_id)
    body = parse_body()
    measured_rotor_od_mm = req_num(body, "measured_rotor_od_mm", places=3)
    rotor_mass_kg = req_num(body, "rotor_mass_kg", places=3)

    if build["status"] not in ("CAST_POURED", "BARS_BRAZED"):
        fail("ERR_INVALID_SUBASSEMBLY_STATE",
             "Only a CAST_POURED or BARS_BRAZED rotor may be machined.")

    work_order = db.work_orders[build["work_order_id"]]
    design = pinned_design(work_order)
    measured_gap, deviation = rotor_air_gap(design, measured_rotor_od_mm)
    if abs(deviation) > design["air_gap_tolerance_mm"]:
        fail("ERR_AIR_GAP_OUT_OF_TOLERANCE",
             "The air-gap deviation exceeds the design tolerance.")

    build["measured_rotor_od_mm"] = measured_rotor_od_mm
    build["rotor_mass_kg"] = rotor_mass_kg
    build["measured_air_gap_mm"] = measured_gap
    build["air_gap_deviation_mm"] = deviation
    build["status"] = "MACHINED"
    touch(build)
    return single(build)


@bp.post("/rotor-builds/<row_id>/balance-disposition")
def balance_disposition(row_id):
    authorize("TestEngineer")
    build = load("rotor_builds", row_id)
    body = parse_body()
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    balance_grade = req_enum(body, "balance_grade", BALANCE_GRADES)
    initial = req_num(body, "initial_unbalance_g_mm", places=1)
    residual = req_num(body, "residual_unbalance_g_mm", places=1)
    notes = opt_str(body, "disposition_notes", min_len=0)

    if build["status"] != "MACHINED":
        fail("ERR_INVALID_SUBASSEMBLY_STATE",
             "Only a MACHINED rotor may be balanced and dispositioned.")

    work_order = db.work_orders[build["work_order_id"]]
    design = pinned_design(work_order)
    permissible = permissible_unbalance_g_mm(
        balance_grade, build["rotor_mass_kg"], design["poles"])

    if disposition == "ACCEPTED" and residual > permissible:
        fail("ERR_UNBALANCE_EXCEEDS_GRADE_LIMIT",
             "The residual unbalance exceeds the permissible limit for this grade.")

    build["balance_grade"] = balance_grade
    build["initial_unbalance_g_mm"] = initial
    build["residual_unbalance_g_mm"] = residual
    build["permissible_unbalance_g_mm"] = permissible
    if notes is not None:
        build["disposition_notes"] = notes

    if disposition == "ACCEPTED":
        build["status"] = "ACCEPTED"
        touch(build)
        touch(work_order)
        fork_join(work_order)
    else:
        build["status"] = "REJECTED"
        touch(build)
        work_order["rework_reject_count"] = work_order["rework_reject_count"] + 1
        count_reject_surcharge(work_order)
        touch(work_order)

    return single(build)


# ---------------------------------------------------------------------------
# Assembly records
# ---------------------------------------------------------------------------

@bp.post("/assembly-records")
def create_assembly():
    user_id, _role = authorize("BuildTechnician")
    body = parse_body()
    work_order_id = req_str(body, "work_order_id")
    stator_build_id = req_str(body, "stator_build_id")
    rotor_build_id = req_str(body, "rotor_build_id")
    de_bearing_lot = req_str(body, "de_bearing_lot", 1, 32)
    nde_bearing_lot = req_str(body, "nde_bearing_lot", 1, 32)
    bearing_install_method = req_enum(body, "bearing_install_method",
                                      BEARING_INSTALL_METHODS)
    shaft_measured_diameter_mm = req_num(body, "shaft_measured_diameter_mm", places=3)
    grease_fill_pct = req_num(body, "grease_fill_pct", places=2)

    work_order = load("work_orders", work_order_id)
    stator = load("stator_builds", stator_build_id)
    rotor = load("rotor_builds", rotor_build_id)

    if work_order["build_status"] != "SUBASSEMBLIES_DONE":
        fail("ERR_INVALID_WORK_ORDER_STATE",
             "Assembly requires a SUBASSEMBLIES_DONE work order.")

    if (stator["work_order_id"] != work_order_id or stator["status"] != "ACCEPTED"
            or rotor["work_order_id"] != work_order_id or rotor["status"] != "ACCEPTED"):
        fail("ERR_SUBASSEMBLY_NOT_ACCEPTED",
             "Both cited subassemblies must belong to this work order and be ACCEPTED.")

    design = pinned_design(work_order)
    deviation = shaft_fit_deviation_um(shaft_measured_diameter_mm,
                                       design["shaft_diameter_mm"])
    low, high = SHAFT_FIT_LIMITS_UM[design["shaft_tolerance_class"]]
    if deviation < low or deviation > high:
        fail("ERR_SHAFT_FIT_OUT_OF_TOLERANCE",
             "The shaft fit deviation falls outside the ISO band for %s."
             % design["shaft_tolerance_class"])

    lubrication_spec_applied = design["lubrication_spec"]
    fill_low, fill_high = GREASE_FILL_PCT_RANGE[lubrication_spec_applied]
    compared = rhu(grease_fill_pct, 1)
    if compared < fill_low or compared > fill_high:
        fail("ERR_LUBRICATION_FILL_OUT_OF_RANGE",
             "The grease fill falls outside the range for %s." % lubrication_spec_applied)

    row = base_row()
    row.update({
        "work_order_id": work_order_id,
        "stator_build_id": stator_build_id,
        "rotor_build_id": rotor_build_id,
        "de_bearing_lot": de_bearing_lot,
        "nde_bearing_lot": nde_bearing_lot,
        "bearing_install_method": bearing_install_method,
        "shaft_measured_diameter_mm": shaft_measured_diameter_mm,
        "shaft_fit_deviation_um": deviation,
        "grease_fill_pct": grease_fill_pct,
        "lubrication_spec_applied": lubrication_spec_applied,
        "status": "BUILT",
        "assembler_user_id": user_id,
    })
    db.assembly_records[row["id"]] = row

    work_order["build_status"] = "ASSEMBLED"
    touch(work_order)
    return created({k: v for k, v in row.items() if not k.startswith("_")})


@bp.get("/assembly-records/<row_id>")
def read_assembly(row_id):
    authorize(*SUBASSEMBLY_READERS)
    return single(load("assembly_records", row_id))


@bp.get("/assembly-records")
def list_assemblies():
    authorize(*SUBASSEMBLY_READERS)
    collection = rows("assembly_records")
    collection = eq_filter(collection, "work_order_id")
    collection = eq_filter(collection, "stator_build_id")
    collection = eq_filter(collection, "rotor_build_id")
    collection = eq_filter(collection, "status")
    return paginate(collection)
