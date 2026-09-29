"""Master data: plants, raw materials, fuels, customers, kilns, silos, clock."""

from flask import Blueprint

from core import (
    API_PREFIX, INTERNAL_ROLES, CLOCK,
    D, ZERO, guard, body, fail, actor, now, now_iso,
    need, want_str, want_num, want_int, want_bool, want_enum, want_dt,
    want_array, is_number, fk_ref, path_row, put_row, new_row, touch,
    respond_object, filtered_list, field_eq, computed_eq, query_int, _bad,
)
import calc
import cascades
import serial

bp = Blueprint("master", __name__, url_prefix=API_PREFIX)

READ = INTERNAL_ROLES


# ===========================================================================
# Plants
# ===========================================================================
@bp.post("/plants")
@guard(["PlantAdmin"])
def create_plant():
    payload = body()
    name = want_str(payload, "name")
    region_code = want_str(payload, "region_code")
    nox_cap = want_num(payload, "permit_nox_kg_per_tonne_clinker_cap")
    nox_budget = want_num(payload, "permit_annual_nox_budget_kg")
    max_tsr = want_num(payload, "permit_max_tsr_pct")
    max_chlorine = want_num(payload, "permit_max_chlorine_kg_per_run")
    months = want_array(payload, "peak_season_months")
    for month in months:
        if isinstance(month, bool) or not isinstance(month, int) or month < 1 or month > 12:
            _bad("peak_season_months", "must contain integers between 1 and 12")
    free_lime = want_num(payload, "clinker_free_lime_max_pct")
    row = new_row("plants")
    row.update({
        "name": name,
        "region_code": region_code,
        "permit_nox_kg_per_tonne_clinker_cap": nox_cap,
        "permit_annual_nox_budget_kg": nox_budget,
        "permit_max_tsr_pct": max_tsr,
        "permit_max_chlorine_kg_per_run": max_chlorine,
        "peak_season_months": list(months),
        "clinker_free_lime_max_pct": free_lime,
    })
    put_row("plants", row)
    return respond_object(serial.plant_out(row), 201)


@bp.get("/plants/<plant_id>")
@guard(READ)
def get_plant(plant_id):
    return respond_object(serial.plant_out(path_row("plants", plant_id)))


@bp.get("/plants")
@guard(READ)
def list_plants():
    return filtered_list("plants", serial.plant_out,
                         {"region_code": field_eq("region_code")})


@bp.get("/plants/<plant_id>/distribution-plan")
@guard(["PlantAdmin", "LogisticsPlanner"])
def distribution_plan(plant_id):
    plant = path_row("plants", plant_id)
    as_of_month = query_int("as_of_month")
    if as_of_month < 1 or as_of_month > 12:
        _bad("as_of_month", "must be between 1 and 12 inclusive")
    customers = calc.eligible_customers(plant)
    if not customers:
        fail("ERR_NO_ELIGIBLE_CUSTOMERS")
    return respond_object(calc.distribution_plan(plant, as_of_month, customers))


# ===========================================================================
# Raw materials
# ===========================================================================
@bp.post("/raw-materials")
@guard(["PlantAdmin", "ProcessEngineer"])
def create_raw_material():
    payload = body()
    row = new_row("raw_materials")
    row.update({
        "code": want_str(payload, "code"),
        "category": want_enum(payload, "category", calc.CATEGORIES_RAW),
        "cao_pct": want_num(payload, "cao_pct"),
        "sio2_pct": want_num(payload, "sio2_pct"),
        "al2o3_pct": want_num(payload, "al2o3_pct"),
        "fe2o3_pct": want_num(payload, "fe2o3_pct"),
        "so3_pct": want_num(payload, "so3_pct"),
        "moisture_pct": want_num(payload, "moisture_pct"),
        "cost_per_tonne": want_num(payload, "cost_per_tonne"),
        "is_alternative": want_bool(payload, "is_alternative", required=False, default=False),
        "max_substitution_pct": want_num(payload, "max_substitution_pct", required=False),
    })
    if row["max_substitution_pct"] is None:
        row["max_substitution_pct"] = 0
    put_row("raw_materials", row)
    return respond_object(serial.raw_material_out(row), 201)


@bp.get("/raw-materials/<raw_material_id>")
@guard(READ)
def get_raw_material(raw_material_id):
    return respond_object(serial.raw_material_out(path_row("raw_materials", raw_material_id)))


@bp.get("/raw-materials")
@guard(READ)
def list_raw_materials():
    return filtered_list("raw_materials", serial.raw_material_out, {
        "category": field_eq("category"),
        "is_alternative": field_eq("is_alternative"),
    })


# ===========================================================================
# Fuels
# ===========================================================================
@bp.post("/fuels")
@guard(["PlantAdmin", "EnvironmentalOfficer"])
def create_fuel():
    payload = body()
    row = new_row("fuels")
    row.update({
        "code": want_str(payload, "code"),
        "category": want_enum(payload, "category", calc.CATEGORIES_FUEL),
        "lhv_gj_per_tonne": want_num(payload, "lhv_gj_per_tonne"),
        "nox_kg_per_gj": want_num(payload, "nox_kg_per_gj"),
        "co2_kg_per_gj": want_num(payload, "co2_kg_per_gj"),
        "chlorine_pct": want_num(payload, "chlorine_pct"),
        "is_alternative": want_bool(payload, "is_alternative", required=False, default=False),
    })
    put_row("fuels", row)
    return respond_object(serial.fuel_out(row), 201)


@bp.get("/fuels/<fuel_id>")
@guard(READ)
def get_fuel(fuel_id):
    return respond_object(serial.fuel_out(path_row("fuels", fuel_id)))


@bp.get("/fuels")
@guard(READ)
def list_fuels():
    return filtered_list("fuels", serial.fuel_out, {
        "category": field_eq("category"),
        "is_alternative": field_eq("is_alternative"),
    })


# ===========================================================================
# Customers
# ===========================================================================
@bp.post("/customers")
@guard(["PlantAdmin", "LogisticsPlanner"])
def create_customer():
    payload = body()
    row = new_row("customers")
    contract_state = want_enum(payload, "contract_state", calc.CONTRACT_STATES, required=False)
    credit_hold = want_bool(payload, "credit_hold", required=False, default=False)
    row.update({
        "name": want_str(payload, "name"),
        "region_code": want_str(payload, "region_code"),
        "contract_priority": want_int(payload, "contract_priority", non_negative=False),
        "contract_monthly_tonnes": want_num(payload, "contract_monthly_tonnes"),
        "required_cement_type": want_enum(payload, "required_cement_type", calc.CEMENT_TYPES),
        "max_so3_pct": want_num(payload, "max_so3_pct"),
        "contract_state": contract_state or "ACTIVE",
        "credit_hold": False if credit_hold is None else credit_hold,
    })
    put_row("customers", row)
    return respond_object(serial.customer_out(row), 201)


@bp.patch("/customers/<customer_id>")
@guard(["PlantAdmin", "LogisticsPlanner"])
def amend_customer(customer_id):
    customer = path_row("customers", customer_id)
    payload = body()
    contract_state = want_enum(payload, "contract_state", calc.CONTRACT_STATES, required=False)
    credit_hold = want_bool(payload, "credit_hold", required=False)
    priority = want_int(payload, "contract_priority", required=False, non_negative=False)
    monthly = want_num(payload, "contract_monthly_tonnes", required=False)
    max_so3 = want_num(payload, "max_so3_pct", required=False)
    if contract_state is not None:
        customer["contract_state"] = contract_state
    if credit_hold is not None:
        customer["credit_hold"] = credit_hold
    if priority is not None:
        customer["contract_priority"] = priority
    if monthly is not None:
        customer["contract_monthly_tonnes"] = monthly
    if max_so3 is not None:
        customer["max_so3_pct"] = max_so3
    touch(customer)
    return respond_object(serial.customer_out(customer))


@bp.get("/customers/<customer_id>")
@guard(READ)
def get_customer(customer_id):
    return respond_object(serial.customer_out(path_row("customers", customer_id)))


@bp.get("/customers")
@guard(READ)
def list_customers():
    return filtered_list("customers", serial.customer_out, {
        "region_code": field_eq("region_code"),
        "contract_state": field_eq("contract_state"),
    })


# ===========================================================================
# Kilns
# ===========================================================================
@bp.post("/kilns")
@guard(["PlantAdmin"])
def create_kiln():
    payload = body()
    plant = fk_ref(payload, "plant_id", "plants")
    row = new_row("kilns")
    row.update({
        "plant_id": want_str(payload, "plant_id"),
        "code": want_str(payload, "code"),
        "nominal_shc_gj_per_tonne": want_num(payload, "nominal_shc_gj_per_tonne"),
        "cooldown_buffer_hours": want_int(payload, "cooldown_buffer_hours"),
        "reline_due_hours": want_int(payload, "reline_due_hours"),
        "refractory_hours_since_reline": 0,
    })
    if D(row["nominal_shc_gj_per_tonne"]) <= ZERO:
        _bad("nominal_shc_gj_per_tonne", "must be greater than zero")
    row["plant_id"] = plant["id"]
    put_row("kilns", row)
    return respond_object(serial.kiln_out(row), 201)


@bp.get("/kilns/<kiln_id>")
@guard(READ)
def get_kiln(kiln_id):
    return respond_object(serial.kiln_out(path_row("kilns", kiln_id)))


@bp.get("/kilns")
@guard(READ)
def list_kilns():
    return filtered_list("kilns", serial.kiln_out, {
        "plant_id": field_eq("plant_id"),
        "availability_state": computed_eq(calc.kiln_availability_state),
    })


# ===========================================================================
# Silos
# ===========================================================================
@bp.post("/silos")
@guard(["PlantAdmin"])
def create_silo():
    payload = body()
    plant = fk_ref(payload, "plant_id", "plants")
    row = new_row("silos")
    spouts = want_int(payload, "loadout_spouts", required=False)
    row.update({
        "plant_id": want_str(payload, "plant_id"),
        "code": want_str(payload, "code"),
        "material_kind": want_enum(payload, "material_kind", calc.MATERIAL_KINDS),
        "capacity_tonnes": want_num(payload, "capacity_tonnes"),
        "draw_rate_tonnes_per_hour": want_num(payload, "draw_rate_tonnes_per_hour"),
        "loadout_spouts": 1 if spouts is None else spouts,
        "tonnes_on_hand": 0.0,
        "reserved_tonnes": 0.0,
        "unreleased_tonnes": 0.0,
        "status": "OPEN",
        "block_reason": None,
    })
    row["plant_id"] = plant["id"]
    put_row("silos", row)
    return respond_object(serial.silo_out(row), 201)


@bp.patch("/silos/<silo_id>")
@guard(["PlantAdmin"])
def patch_silo(silo_id):
    silo = path_row("silos", silo_id)
    payload = body()
    status = want_enum(payload, "status", calc.SILO_STATUSES)
    block_reason = want_str(payload, "block_reason", required=False)
    if status == silo["status"]:
        # PRD 3.8: blocking a BLOCKED silo or unblocking an OPEN one is not a
        # legal transition, and the catalogue carries no silo state error.
        _bad("status", "does not name a legal transition from %s" % silo["status"])
    if status == "BLOCKED":
        cascades.block_silo(silo, block_reason)
    else:
        cascades.unblock_silo(silo)
    return respond_object(serial.silo_out(silo))


@bp.get("/silos/<silo_id>")
@guard(READ)
def get_silo(silo_id):
    return respond_object(serial.silo_out(path_row("silos", silo_id)))


@bp.get("/silos")
@guard(READ)
def list_silos():
    return filtered_list("silos", serial.silo_out, {
        "plant_id": field_eq("plant_id"),
        "material_kind": field_eq("material_kind"),
        "status": field_eq("status"),
    })


# ===========================================================================
# Logical clock (PRD 2.4)
# ===========================================================================
@bp.post("/_clock/set_current_utc")
@guard(READ)
def set_clock():
    payload = body()
    instant = want_dt(payload, "to_iso8601")
    CLOCK.set(instant)
    return respond_object({"current_utc": now_iso()})
