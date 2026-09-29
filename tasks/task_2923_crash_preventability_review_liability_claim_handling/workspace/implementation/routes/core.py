"""Clock control, the terminal network, terminal analytics and the driver roster."""

from decimal import Decimal

from flask import Blueprint

import calc
import serializers
from auth import require, TERMINAL_READ, SAFETY_READ
from common import filtered, lookup, paginate, retraining_pending
from envelope import fmt_dt, num, ok, created
from errors import fail
from shape import MISSING, f, filters, given, present, read_body
from store import base_row, db, touch

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    require("SafetyAdmin")
    values = read_body([f("current_utc", "instant", required=True)])
    db.now = values["current_utc"]
    return ok({"current_utc": fmt_dt(db.now)})


# ---------------------------------------------------------------------------
# Terminals
# ---------------------------------------------------------------------------
TERMINAL_SPEC = [
    f("name", "string", required=True),
    f("terminal_code", "string", required=True, pattern=r"^[A-Z0-9]{3,10}$"),
    f("region_code", "string", required=True, pattern=r"^[A-Za-z]{2}$"),
    f("annual_miles_millions", "number", required=True, exclusive_min=0,
      decimals=4),
]


@bp.post("/terminals")
def create_terminal():
    require("SafetyAdmin")
    values = read_body(TERMINAL_SPEC)
    code = values["terminal_code"]
    for row in db.terminals.values():
        if row["terminal_code"] == code:
            fail("ERR_TERMINAL_CODE_DUPLICATE",
                 "Terminal code '%s' is already registered" % code)
    row = base_row()
    row["name"] = values["name"]
    row["terminal_code"] = code
    row["region_code"] = values["region_code"]
    row["annual_miles_millions"] = values["_raw"]["annual_miles_millions"]
    row["_miles"] = values["annual_miles_millions"]
    db.terminals[row["id"]] = row
    return created(serializers.terminal(row))


@bp.get("/terminals/<entity_id>")
def read_terminal(entity_id):
    require(*TERMINAL_READ)
    return ok(serializers.terminal(lookup("terminals", entity_id)))


@bp.get("/terminals")
def list_terminals():
    require(*TERMINAL_READ)
    criteria = filters({
        "region_code": None,
        "risk_tier": calc.RISK_TIERS,
        "staffing_posture": calc.STAFFING_POSTURES,
    })
    region = criteria.pop("region_code", None)
    tier = criteria.pop("risk_tier", None)
    posture = criteria.pop("staffing_posture", None)

    def keep(row):
        if region is not None and row["region_code"] != region:
            return False
        if tier is not None:
            rate = calc.crash_rate(calc.terminal_preventable_count(row["id"]),
                                   row["_miles"])
            if calc.risk_tier(rate) != tier:
                return False
        if posture is not None and calc.staffing_posture(row["id"]) != posture:
            return False
        return True

    return paginate(filtered("terminals", {}, keep), serializers.terminal)


# ---------------------------------------------------------------------------
# Terminal crash analytics
# ---------------------------------------------------------------------------
@bp.get("/terminals/<entity_id>/crash-analytics")
def crash_analytics(entity_id):
    require("SafetyAdmin", "SafetyManager", "Auditor")
    criteria = filters({
        "basis": calc.ANALYTICS_BASES,
        "route_class": calc.ROUTE_CLASSES,
        "tenure_band": calc.TENURE_BANDS,
    })
    terminal = lookup("terminals", entity_id)
    basis = criteria.get("basis", "AS_DETERMINED")
    route_class = criteria.get("route_class")
    tenure = criteria.get("tenure_band")
    start, end = calc.analytics_window()

    def band_of(crash):
        driver = db.drivers.get(crash["driver_id"])
        return None if driver is None else calc.tenure_band(driver)

    population = []
    for crash in calc.crashes_in_window(terminal["id"]):
        if route_class is not None and crash["route_class"] != route_class:
            continue
        if tenure is not None and band_of(crash) != tenure:
            continue
        population.append(crash)

    def counted(subset):
        if basis == "AS_REPORTED":
            return len(subset)
        return len([c for c in subset
                    if c["preventability_status"] == "PREVENTABLE"])

    def block(subset):
        crash_count = len(subset)
        preventable = counted(subset)
        rate = calc.crash_rate(preventable, terminal["_miles"])
        return crash_count, preventable, rate

    crash_count, preventable, rate = block(population)
    by_route = []
    for value in calc.ROUTE_CLASSES:
        subset = [c for c in population if c["route_class"] == value]
        if not subset:
            continue
        sub_count, sub_prev, sub_rate = block(subset)
        by_route.append({
            "route_class": value,
            "crash_count": sub_count,
            "preventable_crash_count": sub_prev,
            "crash_rate_per_million_miles": num(sub_rate),
        })
    by_tenure = []
    for value in calc.TENURE_BANDS:
        subset = [c for c in population if band_of(c) == value]
        if not subset:
            continue
        sub_count, sub_prev, sub_rate = block(subset)
        by_tenure.append({
            "tenure_band": value,
            "crash_count": sub_count,
            "preventable_crash_count": sub_prev,
            "crash_rate_per_million_miles": num(sub_rate),
        })
    return ok({
        "terminal_id": terminal["id"],
        "basis": basis,
        "window_start_at": fmt_dt(start),
        "window_end_at": fmt_dt(end),
        "crash_count": crash_count,
        "preventable_crash_count": preventable,
        "crash_rate_per_million_miles": num(rate),
        "risk_tier": calc.risk_tier(rate),
        "by_route_class": by_route,
        "by_tenure_band": by_tenure,
    })


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------
DRIVER_SPEC = [
    f("terminal_id", "string", required=True),
    f("employee_code", "string", required=True),
    f("full_name", "string", required=True),
    f("cdl_number", "string", required=True),
    f("hire_date", "date", required=True),
]


@bp.post("/drivers")
def create_driver():
    require("SafetyAdmin")
    values = read_body(DRIVER_SPEC)
    terminal = lookup("terminals", values["terminal_id"])
    code = values["employee_code"]
    for row in db.drivers.values():
        if row["terminal_id"] == terminal["id"] and row["employee_code"] == code:
            fail("ERR_EMPLOYEE_CODE_DUPLICATE",
                 "Employee code '%s' is already used at this terminal" % code)
    row = base_row()
    row["terminal_id"] = terminal["id"]
    row["employee_code"] = code
    row["full_name"] = values["full_name"]
    row["cdl_number"] = values["cdl_number"]
    row["hire_date"] = values["hire_date"]
    row["status"] = "ACTIVE"
    row["continued_employment_decision"] = "PENDING"
    row["decision_note"] = None
    db.drivers[row["id"]] = row
    return created(serializers.driver(row))


@bp.get("/drivers/<entity_id>")
def read_driver(entity_id):
    require(*SAFETY_READ)
    return ok(serializers.driver(lookup("drivers", entity_id)))


@bp.get("/drivers")
def list_drivers():
    require(*SAFETY_READ)
    criteria = filters({
        "terminal_id": None,
        "status": calc.DRIVER_STATUSES,
        "tenure_band": calc.TENURE_BANDS,
        "required_action_tier": calc.ACTION_TIERS,
    })
    terminal_id = criteria.get("terminal_id")
    status = criteria.get("status")
    band = criteria.get("tenure_band")
    tier = criteria.get("required_action_tier")

    def keep(row):
        if terminal_id is not None and row["terminal_id"] != terminal_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if band is not None and calc.tenure_band(row) != band:
            return False
        if tier is not None and calc.required_action_tier(row) != tier:
            return False
        return True

    return paginate(filtered("drivers", {}, keep), serializers.driver)


@bp.post("/drivers/<entity_id>/employment-decision")
def employment_decision(entity_id):
    require("SafetyManager")
    values = read_body([
        f("decision", "string", required=True, enum=("CONTINUE", "SEPARATE")),
        f("decision_note", "string"),
    ])
    driver = lookup("drivers", entity_id)
    if driver["status"] == "TERMINATED":
        fail("ERR_DRIVER_STATE_INVALID",
             "A terminated driver accepts no further employment decision")
    decision = values["decision"]
    if decision == "CONTINUE":
        if retraining_pending(driver["id"]):
            fail("ERR_RETRAINING_INCOMPLETE",
                 "A mandated retraining is still outstanding for this driver")
    else:
        if calc.required_action_tier(driver) != "TERMINATION_REVIEW":
            fail("ERR_SEPARATION_NOT_SUPPORTED",
                 "Separation requires a required_action_tier of TERMINATION_REVIEW")
    driver["continued_employment_decision"] = decision
    driver["decision_note"] = given(values, "decision_note")
    if decision == "SEPARATE":
        driver["status"] = "TERMINATED"
    touch(driver)
    return ok(serializers.driver(driver))
