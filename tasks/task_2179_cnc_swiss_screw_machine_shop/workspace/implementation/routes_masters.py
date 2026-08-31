"""Clock, operators, machines, parts, characteristics, gauges, bar lots, tooling."""
from flask import Blueprint

import calc
import services
from core import (db, dec, fail, now, parse_dt, public, respond_list, respond_object,
                  sorted_rows, stamp_new, touch)
from guards import (ALL_ROLES, active_operator, authenticate, body, ensure_unique, f_bool,
                    f_dt, f_enum, f_enum_list, f_int, f_num, f_str, lookup, paginate,
                    pagination)

bp = Blueprint("masters", __name__)


# ==========================================================================
# logical clock
# ==========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("ShopPlanner", "QualityManager"))
    payload = body()
    raw, parsed = f_dt(payload, "to_iso8601")
    db.clock = parsed
    return respond_object({"current_utc": raw})


# ==========================================================================
# operators
# ==========================================================================
@bp.post("/swiss-shop/operators")
def create_operator():
    authenticate(("ShopPlanner",))
    payload = body()
    name = f_str(payload, "name")
    badge_code = f_str(payload, "badge_code", max_len=32)
    certifications = f_enum_list(payload, "certifications", calc.CERTIFICATIONS,
                                 required=False, default=[])
    status = f_enum(payload, "status", ("ACTIVE", "INACTIVE"), required=False, default="ACTIVE")
    ensure_unique("operators", "badge_code", badge_code)
    row = stamp_new({
        "name": name,
        "badge_code": badge_code,
        "certifications": certifications,
        "status": status,
    })
    db.operators[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/operators/<oid>")
def get_operator(oid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("operators", oid)))


# ==========================================================================
# machines
# ==========================================================================
@bp.post("/swiss-shop/machines")
def create_machine():
    authenticate(("ShopPlanner",))
    payload = body()
    asset_tag = f_str(payload, "asset_tag")
    max_bar_diameter_mm = f_num(payload, "max_bar_diameter_mm", exclusive_min=0)
    model = f_str(payload, "model", required=False, default="SWISS-20")
    lights_out_certified = f_bool(payload, "lights_out_certified", required=False, default=False)
    ensure_unique("machines", "asset_tag", asset_tag)
    row = stamp_new({
        "asset_tag": asset_tag,
        "model": model,
        "max_bar_diameter_mm": max_bar_diameter_mm,
        "lights_out_certified": lights_out_certified,
        "status": "AVAILABLE",
        "current_work_order_id": None,
        "chip_accrual_by_alloy": {},
        "coolant_makeup_liters": dec(0),
        "last_reclamation_credit_cents": None,
        "lifetime_reclamation_credit_cents": 0,
    })
    db.machines[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/machines/<mid>")
def get_machine(mid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("machines", mid)))


@bp.post("/swiss-shop/machines/<mid>/restore")
def restore_machine(mid):
    user_id, _role = authenticate(("Machinist",))
    machine = lookup("machines", mid)
    active_operator(user_id)
    if machine["status"] != "DOWN":
        fail("ERR_INVALID_STATE")
    if services.held_stations(machine["id"]):
        fail("ERR_TOOL_LIFE_EXPIRED")
    machine["status"] = "AVAILABLE"
    touch(machine)
    return respond_object(public(machine))


@bp.post("/swiss-shop/machines/<mid>/reclaim")
def reclaim_machine(mid):
    authenticate(("ShopPlanner",))
    payload = body()
    f_dt(payload, "collected_at")
    machine = lookup("machines", mid)
    net = calc.reclamation_credit(machine)
    machine["last_reclamation_credit_cents"] = net
    machine["lifetime_reclamation_credit_cents"] = int(machine["lifetime_reclamation_credit_cents"]) + net
    machine["chip_accrual_by_alloy"] = {}
    machine["coolant_makeup_liters"] = dec(0)
    touch(machine)
    return respond_object(public(machine))


# ==========================================================================
# parts
# ==========================================================================
@bp.post("/swiss-shop/parts")
def create_part():
    authenticate(("ShopPlanner",))
    payload = body()
    part_number = f_str(payload, "part_number")
    alloy_code = f_enum(payload, "alloy_code", calc.ALLOY_CODES)
    bar_diameter_mm = f_num(payload, "bar_diameter_mm", exclusive_min=0)
    cut_off_length_mm = f_num(payload, "cut_off_length_mm", exclusive_min=0)
    cycle_time_sec = f_num(payload, "cycle_time_sec", exclusive_min=0)
    setup_hours = f_num(payload, "setup_hours", minimum=0)
    material_cost_cents_per_meter = f_int(payload, "material_cost_cents_per_meter", minimum=0)
    finished_mass_g = f_num(payload, "finished_mass_g", exclusive_min=0)
    lights_out_eligible = f_bool(payload, "lights_out_eligible", required=False, default=False)
    secondary_required = f_bool(payload, "secondary_required", required=False, default=False)
    secondary_minutes_per_piece = f_num(payload, "secondary_minutes_per_piece",
                                        required=False, default=dec(0), minimum=0)
    ensure_unique("parts", "part_number", part_number)
    row = stamp_new({
        "part_number": part_number,
        "alloy_code": alloy_code,
        "bar_diameter_mm": bar_diameter_mm,
        "cut_off_length_mm": cut_off_length_mm,
        "cycle_time_sec": cycle_time_sec,
        "setup_hours": setup_hours,
        "lights_out_eligible": lights_out_eligible,
        "secondary_required": secondary_required,
        "secondary_minutes_per_piece": secondary_minutes_per_piece,
        "material_cost_cents_per_meter": material_cost_cents_per_meter,
        "finished_mass_g": finished_mass_g,
        "observed_avg_cycle_time_sec": None,
        "observed_accepted_qty": 0,
    })
    db.parts[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/parts/<pid>")
def get_part(pid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("parts", pid)))


# ==========================================================================
# characteristics
# ==========================================================================
@bp.post("/swiss-shop/characteristics")
def create_characteristic():
    authenticate(("ShopPlanner",))
    payload = body()
    part_id = f_str(payload, "part_id")
    char_code = f_str(payload, "char_code")
    nominal = f_num(payload, "nominal")
    usl = f_num(payload, "usl")
    lsl = f_num(payload, "lsl")
    if usl <= lsl:
        fail("ERR_INVALID_REQUEST", "usl must be strictly greater than lsl.")
    sample_freq_pieces = f_int(payload, "sample_freq_pieces", minimum=1)
    required_gauge_type = f_enum(payload, "required_gauge_type", calc.GAUGE_TYPES)
    cpk_min = f_num(payload, "cpk_min", required=False, default=calc.CPK_MIN_DEFAULT, exclusive_min=0)
    subgroup_size = f_int(payload, "subgroup_size", required=False, default=5)
    if subgroup_size not in (3, 5):
        fail("ERR_INVALID_REQUEST", "subgroup_size must be 3 or 5.")
    lookup("parts", part_id)
    ensure_unique("characteristics", "char_code", char_code, "part_id", part_id)
    row = stamp_new({
        "part_id": part_id,
        "char_code": char_code,
        "nominal": nominal,
        "usl": usl,
        "lsl": lsl,
        "cpk_min": cpk_min,
        "subgroup_size": subgroup_size,
        "sample_freq_pieces": sample_freq_pieces,
        "required_gauge_type": required_gauge_type,
    })
    db.characteristics[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/characteristics/<cid>")
def get_characteristic(cid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("characteristics", cid)))


@bp.get("/swiss-shop/characteristics")
def list_characteristics():
    from flask import request
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.characteristics.values())
    part_id = request.args.get("part_id")
    if part_id:
        rows = [r for r in rows if r["part_id"] == part_id]
    rows = sorted_rows(rows)
    window, total = paginate(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


# ==========================================================================
# gauges
# ==========================================================================
@bp.post("/swiss-shop/gauges")
def create_gauge():
    authenticate(("QualityManager",))
    payload = body()
    gauge_code = f_str(payload, "gauge_code")
    gauge_type = f_enum(payload, "gauge_type", calc.GAUGE_TYPES)
    calibrated_at, _cal_dt = f_dt(payload, "calibrated_at")
    calibration_due_at, cal_due_dt = f_dt(payload, "calibration_due_at")
    grr_pct = f_num(payload, "grr_pct", minimum=0)
    ensure_unique("gauges", "gauge_code", gauge_code)
    row = stamp_new({
        "gauge_code": gauge_code,
        "gauge_type": gauge_type,
        "calibrated_at": calibrated_at,
        "calibration_due_at": calibration_due_at,
        "grr_pct": grr_pct,
        "status": services.gauge_status_from_study(grr_pct, cal_due_dt),
        "calibration_count": 0,
        "_cal_due_dt": cal_due_dt,
    })
    db.gauges[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/gauges/<gid>")
def get_gauge(gid):
    authenticate(ALL_ROLES)
    gauge = lookup("gauges", gid)
    services.refresh_gauge(gauge)
    return respond_object(public(gauge))


@bp.post("/swiss-shop/gauges/<gid>/calibrations")
def calibrate_gauge(gid):
    authenticate(("QualityManager",))
    payload = body()
    calibrated_at, _cal_dt = f_dt(payload, "calibrated_at")
    calibration_due_at, cal_due_dt = f_dt(payload, "calibration_due_at")
    grr_pct = f_num(payload, "grr_pct", minimum=0)
    gauge = lookup("gauges", gid)
    services.refresh_gauge(gauge)
    if gauge["status"] not in ("IN_SERVICE", "CALIBRATION_DUE", "GRR_FAILED"):
        fail("ERR_INVALID_STATE")
    gauge["calibrated_at"] = calibrated_at
    gauge["calibration_due_at"] = calibration_due_at
    gauge["_cal_due_dt"] = cal_due_dt
    gauge["grr_pct"] = grr_pct
    gauge["calibration_count"] = int(gauge["calibration_count"]) + 1
    gauge["status"] = services.gauge_status_from_study(grr_pct, cal_due_dt)
    touch(gauge)
    return respond_object(public(gauge))


# ==========================================================================
# bar stock lots
# ==========================================================================
@bp.post("/swiss-shop/bar-stock-lots")
def create_bar_lot():
    authenticate(("ShopPlanner",))
    payload = body()
    heat_number = f_str(payload, "heat_number")
    alloy_code = f_enum(payload, "alloy_code", calc.ALLOY_CODES)
    bar_diameter_mm = f_num(payload, "bar_diameter_mm", exclusive_min=0)
    bar_length_mm = f_num(payload, "bar_length_mm", exclusive_min=0)
    bars_received = f_int(payload, "bars_received", minimum=1)
    mass_kg_per_meter = f_num(payload, "mass_kg_per_meter", exclusive_min=0)
    feeder_slots = f_int(payload, "feeder_slots", required=False, default=1, minimum=1)
    ensure_unique("bar_stock_lots", "heat_number", heat_number)
    total = dec(bars_received) * bar_length_mm
    row = stamp_new({
        "heat_number": heat_number,
        "alloy_code": alloy_code,
        "bar_diameter_mm": bar_diameter_mm,
        "bar_length_mm": bar_length_mm,
        "bars_received": bars_received,
        "mass_kg_per_meter": mass_kg_per_meter,
        "feeder_slots": feeder_slots,
        "total_length_mm": total,
        "available_length_mm": total,
        "reserved_length_mm": dec(0),
        "consumed_length_mm": dec(0),
        "status": "RECEIVED",
        "certificate_number": None,
    })
    db.bar_stock_lots[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/bar-stock-lots/<lid>")
def get_bar_lot(lid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("bar_stock_lots", lid)))


@bp.post("/swiss-shop/bar-stock-lots/<lid>/certify")
def certify_bar_lot(lid):
    authenticate(("QualityManager",))
    payload = body()
    certificate_number = f_str(payload, "certificate_number")
    lot = lookup("bar_stock_lots", lid)
    if lot["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE")
    lot["certificate_number"] = certificate_number
    lot["status"] = "QUARANTINED" if certificate_number == "QUARANTINE" else "CERTIFIED"
    touch(lot)
    return respond_object(public(lot))


# ==========================================================================
# tool assignments
# ==========================================================================
@bp.post("/swiss-shop/tool-assignments")
def create_tool_assignment():
    authenticate(("ShopPlanner",))
    payload = body()
    machine_id = f_str(payload, "machine_id")
    station = f_int(payload, "station", minimum=1)
    tool_code = f_str(payload, "tool_code")
    expected_life_pieces = f_int(payload, "expected_life_pieces", minimum=1)
    drift_limit_um = f_num(payload, "drift_limit_um", required=False,
                           default=calc.OFFSET_DRIFT_LIMIT_UM_DEFAULT, exclusive_min=0)
    lookup("machines", machine_id)
    ensure_unique("tool_assignments", "station", station, "machine_id", machine_id)
    row = stamp_new({
        "machine_id": machine_id,
        "station": station,
        "tool_code": tool_code,
        "expected_life_pieces": expected_life_pieces,
        "drift_limit_um": drift_limit_um,
        "pieces_since_index": 0,
        "cumulative_drift_um": dec(0),
        "offset_log_count": 0,
        "status": "IN_SERVICE",
    })
    db.tool_assignments[row["id"]] = row
    return respond_object(public(row), 201)


@bp.get("/swiss-shop/tool-assignments/<tid>")
def get_tool_assignment(tid):
    authenticate(ALL_ROLES)
    return respond_object(public(lookup("tool_assignments", tid)))


@bp.get("/swiss-shop/tool-assignments")
def list_tool_assignments():
    from flask import request
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = list(db.tool_assignments.values())
    machine_id = request.args.get("machine_id")
    if machine_id:
        rows = [r for r in rows if r["machine_id"] == machine_id]
    rows = sorted_rows(rows)
    window, total = paginate(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


@bp.post("/swiss-shop/tool-assignments/<tid>/offset-logs")
def post_offset_log(tid):
    user_id, _role = authenticate(("Machinist",))
    payload = body()
    pieces_produced = f_int(payload, "pieces_produced", minimum=0)
    measured_drift_um = f_num(payload, "measured_drift_um")
    station = lookup("tool_assignments", tid)
    active_operator(user_id)
    if station["status"] != "IN_SERVICE":
        fail("ERR_INVALID_STATE")
    station["pieces_since_index"] = int(station["pieces_since_index"]) + pieces_produced
    station["cumulative_drift_um"] = dec(station["cumulative_drift_um"]) + measured_drift_um
    station["offset_log_count"] = int(station["offset_log_count"]) + 1
    new_status = calc.tool_wear_state(station)
    station["status"] = new_status
    touch(station)
    if new_status in ("OFFSET_HOLD", "LIFE_EXPIRED"):
        machine = db.machines.get(station["machine_id"])
        if machine is not None:
            services.machine_down_chain(machine)
    return respond_object(public(station))


@bp.post("/swiss-shop/tool-assignments/<tid>/index")
def index_tool_assignment(tid):
    user_id, _role = authenticate(("Machinist",))
    payload = body()
    new_tool_code = f_str(payload, "new_tool_code", required=False, default=None)
    retire = f_bool(payload, "retire", required=False, default=False)
    station = lookup("tool_assignments", tid)
    active_operator(user_id)
    if station["status"] not in ("OFFSET_HOLD", "LIFE_EXPIRED"):
        fail("ERR_INVALID_STATE")
    if new_tool_code is not None:
        station["tool_code"] = new_tool_code
    if retire:
        station["status"] = "RETIRED"
    else:
        station["status"] = "IN_SERVICE"
        station["pieces_since_index"] = 0
        station["cumulative_drift_um"] = dec(0)
        station["offset_log_count"] = 0
    touch(station)
    return respond_object(public(station))
