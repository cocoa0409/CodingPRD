"""Registry endpoints: logical clock, farms, turbine models, turbines, crews,
fault code rules."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import enums
import svc
from auth import ALL_ROLES, authenticate
from envelope import created, listing, ok, ok_raw
from ladder import path_row, ref_row, unique_or_bad
from store import DB, iso
from validate import F, parse

bp = Blueprint("setup", __name__)


# ---------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["SiteAdmin"])
    vals = parse([F("current_utc", "datetime")])
    DB.set_clock(vals["current_utc"])
    svc.expire_windows()
    return ok_raw({"current_utc": iso(DB.now())})


# ------------------------------------------------------------------------ farms
@bp.post("/farms")
def create_farm():
    authenticate(["SiteAdmin"])
    vals = parse(
        [
            F("name", "string", minlen=1, maxlen=120, nonblank=True),
            F("region_code", "string", minlen=2, maxlen=8, upper=True),
            F("grid_operator_code", "string", minlen=1),
            F("road_levy_pct", "number", required=False, default=Decimal("2.5"),
              minv=0, maxv=20),
            F("community_levy_pct", "number", required=False, default=Decimal("1.5"),
              minv=0, maxv=20),
            F("landowner_budget_cap_cents", "integer", minv=0),
        ]
    )
    row = DB.new_row(
        name=vals["name"],
        region_code=vals["region_code"],
        grid_operator_code=vals["grid_operator_code"],
        road_levy_pct=vals["road_levy_pct"],
        community_levy_pct=vals["community_levy_pct"],
        landowner_budget_cap_cents=vals["landowner_budget_cap_cents"],
        turbine_count=0,
        installed_capacity_kw=0,
        landowner_payable_cents=0,
        road_maintenance_reserve_cents=0,
        community_fund_balance_cents=0,
        maintenance_spend_cents=0,
        opex_accrued_cents=0,
    )
    DB.insert("farms", row)
    return created(row)


@bp.get("/farms/<row_id>")
def get_farm(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("farms", row_id))


@bp.get("/farms")
def list_farms():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("farms"), request.args, [("region_code", "region_code", "string", None)]
    )


# --------------------------------------------------------------- turbine models
@bp.post("/turbine-models")
def create_turbine_model():
    authenticate(["SiteAdmin"])
    vals = parse(
        [
            F("model_code", "string", minlen=1, maxlen=40, nonblank=True),
            F("rated_power_kw", "integer", gt=0),
            F("hub_height_m", "number", gt=0),
            F("rotor_diameter_m", "number", gt=0),
            F("service_interval_hours", "integer", gt=0),
            F("service_interval_tolerance_hours", "integer", minv=0),
            F("gearbox_lead_time_days", "integer", minv=0),
            F("blade_lead_time_days", "integer", minv=0),
            F("generator_lead_time_days", "integer", minv=0),
        ]
    )
    unique_or_bad(
        "turbine_models", "model_code is already registered.", model_code=vals["model_code"]
    )
    row = DB.new_row(**vals)
    DB.insert("turbine_models", row)
    return created(row)


@bp.get("/turbine-models/<row_id>")
def get_turbine_model(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("turbine_models", row_id))


@bp.get("/turbine-models")
def list_turbine_models():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("turbine_models"),
        request.args,
        [("model_code", "model_code", "string", None)],
    )


# --------------------------------------------------------------------- turbines
@bp.post("/farms/<farm_id>/turbines")
def commission_turbine(farm_id):
    authenticate(["SiteAdmin"])
    vals = parse(
        [
            F("turbine_model_id", "string"),
            F("asset_tag", "string", minlen=1, maxlen=40, nonblank=True),
            F("commissioning_date", "date"),
            F("expected_kwh_per_hour", "number", gt=0),
            F("operating_hours", "number", required=False, default=Decimal(0), minv=0),
            F("last_service_operating_hours", "number", required=False,
              default=Decimal(0), minv=0),
        ]
    )
    farm = path_row("farms", farm_id)
    model = ref_row("turbine_models", vals["turbine_model_id"])
    unique_or_bad(
        "turbines",
        "asset_tag is already used on this farm.",
        wind_farm_id=farm_id,
        asset_tag=vals["asset_tag"],
    )
    row = DB.new_row(
        wind_farm_id=farm_id,
        turbine_model_id=model["id"],
        asset_tag=vals["asset_tag"],
        commissioning_date=vals["commissioning_date"],
        expected_kwh_per_hour=vals["expected_kwh_per_hour"],
        operating_hours=vals["operating_hours"],
        last_service_operating_hours=vals["last_service_operating_hours"],
        service_due_operating_hours=Decimal(0),
        service_due_flag=False,
        service_interval_breached=False,
        availability_state="ONLINE",
        curtailment_state="UNCONSTRAINED",
        active_fault_code=None,
        remote_reset_count_24h=0,
        reset_window_start_utc=None,
        active_curtailment_count=0,
        effective_power_limit_kw=Decimal(model["rated_power_kw"]),
        period_actual_energy_kwh=Decimal(0),
        period_potential_energy_kwh=Decimal(0),
        counted_downtime_hours_period=Decimal(0),
        cumulative_lost_energy_kwh=Decimal(0),
    )
    svc.recompute_service_figures(row)
    DB.insert("turbines", row)
    svc.recompute_farm_capacity(farm)
    DB.touch(farm)
    return created(row)


@bp.get("/turbines/<row_id>")
def get_turbine(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("turbines", row_id))


@bp.get("/turbines")
def list_turbines():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("turbines"),
        request.args,
        [
            ("wind_farm_id", "wind_farm_id", "string", None),
            ("turbine_model_id", "turbine_model_id", "string", None),
            ("availability_state", "availability_state", "enum", enums.AVAILABILITY_STATES),
            ("curtailment_state", "curtailment_state", "enum", enums.CURTAILMENT_STATES),
        ],
    )


# ------------------------------------------------------------------------ crews
@bp.post("/crews")
def create_crew():
    authenticate(["SiteAdmin"])
    vals = parse(
        [
            F("wind_farm_id", "string"),
            F("crew_code", "string", minlen=1, maxlen=40, nonblank=True),
            F("technician_count", "integer", minv=1),
            F("certifications", "enum_array", members=enums.CERTIFICATIONS),
            F("max_work_wind_speed_ms", "number", gt=0),
            F("daily_hours_capacity", "number", gt=0),
            F("hourly_rate_cents", "integer", minv=0),
            F("status", "enum", required=False, default="AVAILABLE",
              members=enums.CREW_STATUS_INPUTS),
        ]
    )
    farm = ref_row("farms", vals["wind_farm_id"])
    unique_or_bad(
        "crews",
        "crew_code is already used on this farm.",
        wind_farm_id=farm["id"],
        crew_code=vals["crew_code"],
    )
    certs = []
    for cert in vals["certifications"]:
        if cert not in certs:
            certs.append(cert)
    row = DB.new_row(
        wind_farm_id=farm["id"],
        crew_code=vals["crew_code"],
        technician_count=vals["technician_count"],
        certifications=certs,
        max_work_wind_speed_ms=vals["max_work_wind_speed_ms"],
        daily_hours_capacity=vals["daily_hours_capacity"],
        hourly_rate_cents=vals["hourly_rate_cents"],
        status=vals["status"],
    )
    DB.insert("crews", row)
    return created(row)


@bp.get("/crews/<row_id>")
def get_crew(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("crews", row_id))


@bp.get("/crews")
def list_crews():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("crews"),
        request.args,
        [
            ("wind_farm_id", "wind_farm_id", "string", None),
            ("status", "status", "enum", enums.CREW_STATUSES),
        ],
    )


# -------------------------------------------------------------- fault code rules
@bp.post("/fault-code-rules")
def create_fault_code_rule():
    authenticate(["SiteAdmin"])
    vals = parse(
        [
            F("fault_code", "string", minlen=1, maxlen=24, nonblank=True),
            F("severity_class", "enum", members=enums.SEVERITY_CLASSES),
            F("max_remote_resets_per_24h", "integer", minv=0),
            F("requires_dispatch", "boolean"),
            F("contractual_exclusion", "boolean"),
        ]
    )
    unique_or_bad(
        "fault_code_rules",
        "fault_code is already registered.",
        fault_code=vals["fault_code"],
    )
    row = DB.new_row(**vals)
    DB.insert("fault_code_rules", row)
    return created(row)


@bp.get("/fault-code-rules/<row_id>")
def get_fault_code_rule(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("fault_code_rules", row_id))


@bp.get("/fault-code-rules")
def list_fault_code_rules():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("fault_code_rules"),
        request.args,
        [
            ("severity_class", "severity_class", "enum", enums.SEVERITY_CLASSES),
            ("fault_code", "fault_code", "string", None),
        ],
    )


@bp.patch("/fault-code-rules/<row_id>")
def patch_fault_code_rule(row_id):
    authenticate(["SiteAdmin"])
    vals = parse(
        [
            F("max_remote_resets_per_24h", "integer", required=False, minv=0),
            F("requires_dispatch", "boolean", required=False),
            F("contractual_exclusion", "boolean", required=False),
        ]
    )
    rule = path_row("fault_code_rules", row_id)
    for key, value in vals.items():
        rule[key] = value
    DB.touch(rule)
    return ok(rule)
