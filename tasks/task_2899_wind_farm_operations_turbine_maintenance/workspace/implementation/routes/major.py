"""Major component work: cranes, spare parts and component replacements."""

from datetime import timedelta
from decimal import Decimal
from fractions import Fraction

from flask import Blueprint, request

import calc
import enums
import svc
from auth import ALL_ROLES, authenticate
from envelope import created, listing, ok
from errors import ApiError
from ladder import gate, invalid_state, path_row, ref_row, unique_or_bad
from store import DB
from validate import F, parse, require_interval

bp = Blueprint("major", __name__)

BUFFER = timedelta(hours=calc.CRANE_BUFFER_HOURS)
CRANE_SLOT_STATES = ("REQUESTED", "MOBILIZED")


# ------------------------------------------------------------ crane mobilizations
@bp.post("/crane-mobilizations")
def create_mobilization():
    authenticate(["MaintenancePlanner"])
    vals = parse(
        [
            F("wind_farm_id", "string"),
            F("crane_class", "enum", members=enums.CRANE_CLASSES),
            F("mobilization_start_utc", "datetime"),
            F("demobilization_end_utc", "datetime"),
            F("day_rate_cents", "integer", minv=0),
            F("mobilization_fee_cents", "integer", minv=0),
            F("max_lift_wind_speed_ms", "number", gt=0),
        ]
    )
    require_interval(vals, "mobilization_start_utc", "demobilization_end_utc")
    farm = ref_row("farms", vals["wind_farm_id"])

    start = vals["mobilization_start_utc"] - BUFFER
    end = vals["demobilization_end_utc"] + BUFFER
    for other in DB.all("crane_mobilizations"):
        if other["wind_farm_id"] != farm["id"]:
            continue
        if other["state"] not in CRANE_SLOT_STATES:
            continue
        o_start = other["mobilization_start_utc"] - BUFFER
        o_end = other["demobilization_end_utc"] + BUFFER
        if start < o_end and end > o_start:
            raise ApiError(
                "ERR_CRANE_BUFFER_CONFLICT",
                "The buffered mobilization window collides with the farm's crane slot.",
            )

    row = DB.new_row(
        wind_farm_id=farm["id"],
        crane_class=vals["crane_class"],
        mobilization_start_utc=vals["mobilization_start_utc"],
        demobilization_end_utc=vals["demobilization_end_utc"],
        day_rate_cents=vals["day_rate_cents"],
        mobilization_fee_cents=vals["mobilization_fee_cents"],
        max_lift_wind_speed_ms=vals["max_lift_wind_speed_ms"],
        state="REQUESTED",
        reserved_replacement_count=0,
        lift_days=0,
        standby_days=0,
        billable_days=0,
        subtotal_cents=0,
        volume_credit_cents=0,
        total_crane_cost_cents=0,
    )
    DB.insert("crane_mobilizations", row)
    return created(row)


@bp.get("/crane-mobilizations/<row_id>")
def get_mobilization(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("crane_mobilizations", row_id))


@bp.get("/crane-mobilizations")
def list_mobilizations():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("crane_mobilizations"),
        request.args,
        [
            ("wind_farm_id", "wind_farm_id", "string", None),
            ("state", "state", "enum", enums.CRANE_STATES),
            ("crane_class", "crane_class", "enum", enums.CRANE_CLASSES),
        ],
    )


@bp.post("/crane-mobilizations/<row_id>/demobilize")
def demobilize(row_id):
    authenticate(["MaintenancePlanner"])
    parse([])
    mob = path_row("crane_mobilizations", row_id)
    if mob["state"] != "MOBILIZED":
        invalid_state(
            "Only a MOBILIZED crane may be demobilized; it is %s." % mob["state"]
        )
    for rep in DB.all("component_replacements"):
        if rep["crane_mobilization_id"] != mob["id"]:
            continue
        if rep["state"] not in ("EXECUTED", "CLOSED", "CANCELLED"):
            invalid_state(
                "A replacement holding this crane is still in %s." % rep["state"]
            )
    mob["state"] = "DEMOBILIZED"
    DB.touch(mob)
    return ok(mob)


# ------------------------------------------------------------------- spare parts
@bp.post("/spare-parts")
def create_spare_part():
    authenticate(["SiteAdmin"])
    vals = parse(
        [
            F("component_type", "enum", members=enums.COMPONENT_TYPES),
            F("part_number", "string", minlen=1, maxlen=60, nonblank=True),
            F("quantity_on_hand", "integer", minv=0),
            F("lead_time_days", "integer", minv=0),
            F("reorder_point", "integer", minv=0),
            F("unit_cost_cents", "integer", minv=0),
            F("uptower_repairable", "boolean"),
        ]
    )
    unique_or_bad(
        "spare_parts",
        "part_number is already registered.",
        part_number=vals["part_number"],
    )
    row = DB.new_row(
        component_type=vals["component_type"],
        part_number=vals["part_number"],
        quantity_on_hand=vals["quantity_on_hand"],
        quantity_reserved=0,
        quantity_consumed=0,
        total_units_accounted=0,
        lead_time_days=vals["lead_time_days"],
        reorder_point=vals["reorder_point"],
        unit_cost_cents=vals["unit_cost_cents"],
        uptower_repairable=vals["uptower_repairable"],
        status="IN_STOCK",
        procurement_flag=False,
    )
    svc.derive_spare_part(row)
    DB.insert("spare_parts", row)
    return created(row)


@bp.get("/spare-parts/<row_id>")
def get_spare_part(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("spare_parts", row_id))


@bp.get("/spare-parts")
def list_spare_parts():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("spare_parts"),
        request.args,
        [
            ("component_type", "component_type", "enum", enums.COMPONENT_TYPES),
            ("status", "status", "enum", enums.PART_STATUSES),
        ],
    )


@bp.post("/spare-parts/<row_id>/receipts")
def book_receipt(row_id):
    authenticate(["SiteAdmin"])
    vals = parse([F("quantity_received", "integer", gt=0)])
    part = path_row("spare_parts", row_id)
    part["quantity_on_hand"] = int(part["quantity_on_hand"]) + vals["quantity_received"]
    svc.derive_spare_part(part)
    DB.touch(part)
    return ok(part)


# --------------------------------------------------------- component replacements
@bp.post("/component-replacements")
def create_replacement():
    authenticate(["MaintenancePlanner"])
    vals = parse(
        [
            F("work_order_id", "string"),
            F("spare_part_id", "string"),
            F("component_type", "enum", members=enums.COMPONENT_TYPES),
            F("estimated_lift_hours", "number", minv=0),
            F("uptower_labor_hours", "number", required=False, gt=0),
        ]
    )
    work_order = ref_row("work_orders", vals["work_order_id"])
    part = ref_row("spare_parts", vals["spare_part_id"])
    if work_order["work_type"] != "MAJOR_COMPONENT":
        invalid_state(
            "A component replacement requires a MAJOR_COMPONENT work order; this order "
            "is %s." % work_order["work_type"]
        )
    gate(
        part["component_type"] != vals["component_type"],
        "ERR_SPARE_PART_TYPE_MISMATCH",
        "The spare part covers %s, not %s."
        % (part["component_type"], vals["component_type"]),
    )
    gate(
        int(part["quantity_on_hand"]) < 1,
        "ERR_SPARE_PART_UNAVAILABLE",
        "The spare part has no unreserved units on hand.",
    )

    row = DB.new_row(
        work_order_id=work_order["id"],
        spare_part_id=part["id"],
        crane_mobilization_id=None,
        component_type=vals["component_type"],
        estimated_lift_hours=vals["estimated_lift_hours"],
        uptower_labor_hours=vals.get("uptower_labor_hours"),
        execution_path=None,
        state="PLANNED",
        allocated_crane_cost_cents=0,
    )
    DB.insert("component_replacements", row)
    part["quantity_on_hand"] = int(part["quantity_on_hand"]) - 1
    part["quantity_reserved"] = int(part["quantity_reserved"]) + 1
    svc.derive_spare_part(part)
    DB.touch(part)
    return created(row)


@bp.get("/component-replacements/<row_id>")
def get_replacement(row_id):
    authenticate(ALL_ROLES)
    return ok(path_row("component_replacements", row_id))


@bp.get("/component-replacements")
def list_replacements():
    authenticate(ALL_ROLES)
    return listing(
        DB.all("component_replacements"),
        request.args,
        [
            ("work_order_id", "work_order_id", "string", None),
            ("spare_part_id", "spare_part_id", "string", None),
            ("crane_mobilization_id", "crane_mobilization_id", "string", None),
            ("state", "state", "enum", enums.REPLACEMENT_STATES),
        ],
    )


@bp.post("/component-replacements/<row_id>/reserve-crane")
def reserve_crane(row_id):
    authenticate(["MaintenancePlanner"])
    vals = parse([F("crane_mobilization_id", "string")])
    rep = path_row("component_replacements", row_id)
    mob = ref_row("crane_mobilizations", vals["crane_mobilization_id"])
    if rep["state"] != "PLANNED":
        invalid_state(
            "Only a PLANNED replacement may reserve a crane; it is %s." % rep["state"]
        )
    if mob["state"] not in CRANE_SLOT_STATES:
        invalid_state(
            "The crane mobilization is %s, not REQUESTED or MOBILIZED." % mob["state"]
        )

    reserved = svc.crane_reserved_set(mob["id"], extra_id=rep["id"])
    figures = svc.crane_figures(mob, reserved)
    gate(
        figures["lift_days"] > figures["workable_days"],
        "ERR_LIFT_WIND_LIMIT_EXCEEDED",
        "The mobilization window offers %d workable days but the lift needs %d."
        % (figures["workable_days"], figures["lift_days"]),
    )

    work_order = DB.get("work_orders", rep["work_order_id"])
    turbine = DB.get("turbines", work_order["turbine_id"])
    gate(
        mob["wind_farm_id"] != turbine["wind_farm_id"],
        "ERR_CRANE_FARM_MISMATCH",
        "The crane is mobilized to a different farm than the turbine.",
    )
    if (
        rep["component_type"] in enums.HEAVY_LIFT_COMPONENTS
        and mob["crane_class"] != enums.HEAVY_LIFT_CRANE_CLASS
    ):
        invalid_state(
            "A %s may be lifted only by a %s."
            % (rep["component_type"], enums.HEAVY_LIFT_CRANE_CLASS)
        )

    rep["state"] = "CRANE_RESERVED"
    rep["execution_path"] = "CRANE_LIFT"
    rep["crane_mobilization_id"] = mob["id"]
    if mob["state"] == "REQUESTED":
        mob["state"] = "MOBILIZED"
    svc.apply_crane_figures(mob, reserved, figures, skip_id=rep["id"])
    DB.touch(rep)
    DB.touch(mob)
    return ok(rep)


@bp.post("/component-replacements/<row_id>/plan-uptower")
def plan_uptower(row_id):
    authenticate(["MaintenancePlanner"])
    parse([])
    rep = path_row("component_replacements", row_id)
    if rep["state"] != "PLANNED":
        invalid_state(
            "Only a PLANNED replacement may take the up-tower branch; it is %s."
            % rep["state"]
        )
    part = DB.get("spare_parts", rep["spare_part_id"])
    permitted = rep["component_type"] == "GENERATOR" and bool(
        part is not None and part["uptower_repairable"]
    )
    gate(
        not permitted,
        "ERR_UPTOWER_NOT_PERMITTED",
        "The up-tower branch requires a GENERATOR on an up-tower repairable line.",
    )
    rep["state"] = "UPTOWER_READY"
    rep["execution_path"] = "UPTOWER_REPAIR"
    rep["crane_mobilization_id"] = None
    rep["estimated_lift_hours"] = Decimal(0)
    rep["allocated_crane_cost_cents"] = 0
    DB.touch(rep)

    work_order = DB.get("work_orders", rep["work_order_id"])
    labor = rep["uptower_labor_hours"]
    if work_order is not None and labor is not None:
        work_order["estimated_hours"] = Decimal(work_order["estimated_hours"]) + Decimal(
            labor
        )
        DB.touch(work_order)
    return ok(rep)


@bp.post("/component-replacements/<row_id>/execute")
def execute_replacement(row_id):
    authenticate(["CrewLead", "ReliabilityEngineer"])
    parse([])
    rep = path_row("component_replacements", row_id)
    if rep["state"] not in ("CRANE_RESERVED", "UPTOWER_READY"):
        invalid_state(
            "Only a CRANE_RESERVED or UPTOWER_READY replacement may be executed; it is "
            "%s." % rep["state"]
        )
    work_order = DB.get("work_orders", rep["work_order_id"])
    if work_order is None or work_order["state"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_WORK_ORDER_INVALID_STATE",
            "The parent MAJOR_COMPONENT work order is not IN_PROGRESS.",
        )

    rep["state"] = "EXECUTED"
    DB.touch(rep)

    part = DB.get("spare_parts", rep["spare_part_id"])
    if part is not None:
        part["quantity_reserved"] = int(part["quantity_reserved"]) - 1
        part["quantity_consumed"] = int(part["quantity_consumed"]) + 1
        svc.derive_spare_part(part)
        DB.touch(part)

    turbine = DB.get("turbines", work_order["turbine_id"])
    farm = svc.farm_of_turbine(turbine)
    if rep["execution_path"] == "CRANE_LIFT":
        svc.post_maintenance_spend(farm, int(rep["allocated_crane_cost_cents"]))
    else:
        labor = rep["uptower_labor_hours"]
        amount = 0
        if labor is not None:
            amount = calc.rhu_cents(
                Fraction(Decimal(labor))
                * Fraction(calc.UPTOWER_LABOR_RATE_CENTS_PER_HOUR)
            )
        svc.post_maintenance_spend(farm, amount)
    return ok(rep)


@bp.post("/component-replacements/<row_id>/cancel")
def cancel_replacement_endpoint(row_id):
    authenticate(["MaintenancePlanner"])
    parse([F("cancellation_reason", "string", minlen=1, nonblank=True)])
    rep = path_row("component_replacements", row_id)
    if rep["state"] not in ("PLANNED", "CRANE_RESERVED", "UPTOWER_READY"):
        invalid_state(
            "Only a PLANNED, CRANE_RESERVED or UPTOWER_READY replacement may be "
            "cancelled; it is %s." % rep["state"]
        )
    svc.cancel_replacement(rep)
    return ok(rep)
