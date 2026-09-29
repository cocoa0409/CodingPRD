"""Processing runs: planning, starting, consumption, closing and traceability."""

import datetime
from decimal import Decimal

from flask import Blueprint

import db
import enums
import serializers
from envelope import (
    actor,
    enum_param,
    listing,
    object_response,
    read_body,
    require,
    str_param,
)
from errors import ApiError
from services import cascades, chemistry, cost, holds, posture, shelflife
from util import floor_int, iso_date, minutes, now_dt, q2

bp = Blueprint("runs", __name__)

CHANGEOVER_BUFFER_MINUTES = 45
READING_FRESHNESS_MINUTES = 60
NON_TERMINAL_RUN_STATES = ("SETUP", "RUNNING")
YIELD_MAX_PCT = Decimal("100.00")

CREATE_RUN = (
    ("line_id", "id", True),
    ("product_id", "id", True),
    ("customer_spec_id", "id", True),
    ("wash_system_id", "id", True),
    ("planned_start_at", "datetime", True),
    ("planned_end_at", "datetime", True),
    ("crew_size", "int", True, {"ge": 1}),
    ("rework_source_run_id", "id", False),
)

CREATE_CONSUMPTION = (
    ("raw_receipt_id", "id", True),
    ("consumed_lb", "num", True, {"gt": Decimal(0)}),
    ("expected_process_run_version", "int", True, {"ge": 1}),
)

VOID_CONSUMPTION = (("expected_process_run_version", "int", True, {"ge": 1}),)

CLOSE_RUN = (
    ("actual_dwell_seconds", "int", True, {"ge": 0}),
    ("spin_rpm", "int", True, {"ge": 0}),
    ("spin_seconds", "int", True, {"ge": 0}),
    ("atmosphere_actual", "enum", True, {"values": enums.ATMOSPHERE}),
    ("water_gal_used", "num", True, {"ge": Decimal(0)}),
    ("cases_produced", "int", True, {"ge": 1}),
)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; windows that merely touch do not overlap."""
    return a_start < b_end and b_start < a_end


def runs_of_receipt(receipt_id):
    return [c for c in db.rows("lot_consumptions") if c["raw_receipt_id"] == receipt_id]


def active_consumed_of_receipt(receipt_id):
    total = Decimal(0)
    for c in runs_of_receipt(receipt_id):
        if c["status"] == "ACTIVE":
            total = total + c["consumed_lb"]
    return q2(total)


def refresh_receipt_balance(receipt):
    remaining = q2(receipt["accepted_lb"] - active_consumed_of_receipt(receipt["id"]))
    if receipt["remaining_lb"] != remaining:
        receipt["remaining_lb"] = remaining
        db.touch(receipt)


def refresh_run_input(run):
    total = Decimal(0)
    for c in shelflife.active_consumptions(run["id"]):
        total = total + c["consumed_lb"]
    run["input_lb"] = q2(total)


def _line_runs(line_id, exclude_id=None):
    return [
        r
        for r in db.rows("process_runs")
        if r["line_id"] == line_id and r["id"] != exclude_id
    ]


@bp.post("/process-runs")
@require("LineOperator")
def create_run():
    body = read_body(CREATE_RUN)
    line = db.get_or_404("lines", body["line_id"])
    product = db.get_or_404("products", body["product_id"])
    spec = db.get_or_404("customer_specs", body["customer_spec_id"])
    system = db.get_or_404("wash_systems", body["wash_system_id"])
    source_run = None
    if body["rework_source_run_id"] is not None:
        source_run = db.get_or_404("process_runs", body["rework_source_run_id"])

    if spec["product_id"] != product["id"]:
        raise ApiError(
            "ERR_SPEC_PRODUCT_MISMATCH",
            "the customer specification belongs to another product",
        )
    if spec["status"] != "ACTIVE":
        raise ApiError("ERR_SPEC_NOT_ACTIVE", "the customer specification is SUPERSEDED")
    if source_run is not None and source_run["disposition_status"] != "REJECTED":
        raise ApiError(
            "ERR_REWORK_SOURCE_NOT_REJECTED",
            "only a REJECTED run may be named as a rework source",
        )

    start_dt = body["planned_start_at"].dt
    end_dt = body["planned_end_at"].dt
    if not end_dt > start_dt:
        raise ApiError(
            "ERR_LINE_INTERVAL_CONFLICT",
            "planned_end_at must be strictly after planned_start_at",
        )
    for other in _line_runs(line["id"]):
        if other["run_status"] not in NON_TERMINAL_RUN_STATES:
            continue
        if _overlaps(
            start_dt,
            end_dt,
            db.dt_of(other, "planned_start_at"),
            db.dt_of(other, "planned_end_at"),
        ):
            raise ApiError(
                "ERR_LINE_INTERVAL_CONFLICT",
                "the planned window overlaps another run on this line",
            )

    preceding = None
    for other in _line_runs(line["id"]):
        if other["run_status"] not in NON_TERMINAL_RUN_STATES:
            continue
        other_end = db.dt_of(other, "planned_end_at")
        if other_end is None or other_end > start_dt:
            continue
        if preceding is None or other_end > db.dt_of(preceding, "planned_end_at"):
            preceding = other
    if preceding is not None:
        prior_product = db.find("products", preceding["product_id"])
        if (
            prior_product is not None
            and prior_product["allergen_group"] != product["allergen_group"]
        ):
            gap = start_dt - db.dt_of(preceding, "planned_end_at")
            if gap < minutes(CHANGEOVER_BUFFER_MINUTES):
                raise ApiError(
                    "ERR_CHANGEOVER_BUFFER_REQUIRED",
                    "an allergen changeover needs at least 45 minutes of gap",
                )

    occupants = 0
    for other in db.rows("process_runs"):
        if other["wash_system_id"] != system["id"]:
            continue
        if other["run_status"] not in NON_TERMINAL_RUN_STATES:
            continue
        if _overlaps(
            start_dt,
            end_dt,
            db.dt_of(other, "planned_start_at"),
            db.dt_of(other, "planned_end_at"),
        ):
            occupants += 1
    if occupants >= system["max_concurrent_runs"]:
        raise ApiError(
            "ERR_WASH_SYSTEM_CAPACITY_EXCEEDED",
            "the wash system has no concurrent-run capacity left in that window",
        )

    changeover_required = (
        line["last_run_allergen_group"] is not None
        and line["last_run_allergen_group"] != product["allergen_group"]
    )
    row = db.new_row(
        "process_runs",
        {
            "line_id": line["id"],
            "product_id": product["id"],
            "customer_spec_id": spec["id"],
            "wash_system_id": system["id"],
            "rework_source_run_id": body["rework_source_run_id"],
            "crew_size": body["crew_size"],
            "run_status": "SETUP",
            "disposition_status": "UNRESTRICTED",
            "started_at": None,
            "_dt_started_at": None,
            "closed_at": None,
            "_dt_closed_at": None,
            "target_ppm_at_start": None,
            "required_dwell_seconds_at_start": None,
            "actual_dwell_seconds": None,
            "spin_rpm": None,
            "spin_seconds": None,
            "atmosphere_actual": None,
            "water_gal_used": None,
            "cases_produced": None,
            "input_lb": q2(Decimal(0)),
            "output_lb": None,
            "yield_pct": None,
            "min_ppm_observed": None,
            "antimicrobial_excursion_count": 0,
            "allergen_changeover_required": changeover_required,
            "provisional_shelf_life_days": None,
            "provisional_code_date": None,
            "final_shelf_life_days": None,
            "final_code_date": None,
            "total_run_cost_cents": None,
            "per_case_cost_cents": None,
            "cost_remainder_cents": None,
            "cases_available": 0,
            "cases_on_hold": 0,
            "cases_shipped": 0,
            "cases_destroyed": 0,
        },
    )
    db.set_instant(row, "planned_start_at", body["planned_start_at"])
    db.set_instant(row, "planned_end_at", body["planned_end_at"])
    return object_response(serializers.process_run(row), 201)


@bp.get("/process-runs")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "LineOperator", "ShippingClerk"
)
def list_runs():
    filters = (
        ("line_id", str_param("line_id")),
        ("product_id", str_param("product_id")),
        ("customer_spec_id", str_param("customer_spec_id")),
        ("wash_system_id", str_param("wash_system_id")),
        ("rework_source_run_id", str_param("rework_source_run_id")),
        ("run_status", enum_param("run_status", enums.RUN_STATUS)),
        ("disposition_status", enum_param("disposition_status", enums.DISPOSITION_STATUS)),
    )
    rows = db.rows("process_runs")
    for field, value in filters:
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, serializers.process_run)


@bp.get("/process-runs/<run_id>")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "LineOperator", "ShippingClerk"
)
def get_run(run_id):
    return object_response(serializers.process_run(db.get_or_404("process_runs", run_id)))


@bp.post("/process-runs/<run_id>/start")
@require("LineOperator")
def start_run(run_id):
    run = db.get_or_404("process_runs", run_id)
    if run["run_status"] != "SETUP":
        raise ApiError("ERR_RUN_NOT_IN_SETUP", "only a SETUP run may be started")
    line = db.get_or_404("lines", run["line_id"])
    product = db.get_or_404("products", run["product_id"])
    system = db.get_or_404("wash_systems", run["wash_system_id"])
    if line["posture"] != "OPEN":
        raise ApiError("ERR_LINE_NOT_OPEN", "the line posture is " + line["posture"])
    if system["status"] != "IN_SERVICE":
        raise ApiError(
            "ERR_WASH_SYSTEM_DUMP_REQUIRED", "the wash system is awaiting a change-out"
        )
    latest = chemistry.latest_reading(system)
    if latest is None:
        raise ApiError(
            "ERR_NO_ANTIMICROBIAL_READINGS",
            "the wash system has no antimicrobial reading",
        )
    now = now_dt()
    if db.dt_of(latest, "reading_at") < now - minutes(READING_FRESHNESS_MINUTES):
        raise ApiError(
            "ERR_ANTIMICROBIAL_READING_STALE",
            "the latest antimicrobial reading is older than 60 minutes",
        )
    if latest["free_chlorine_ppm"] < product["min_antimicrobial_ppm"]:
        raise ApiError(
            "ERR_ANTIMICROBIAL_BELOW_MINIMUM",
            "the latest free chlorine reading is below the product minimum",
        )
    if run["allergen_changeover_required"]:
        event = posture.newest_validated(line["id"])
        ok = (
            event is not None
            and event["is_allergen_changeover"]
            and event["allergen_swab_result"] == "NEGATIVE"
        )
        if ok and line["last_run_ended_at"] is not None:
            validated_dt = db.dt_of(event, "validated_at")
            ended_dt = db.dt_of(line, "last_run_ended_at")
            ok = validated_dt is not None and validated_dt >= ended_dt
        if not ok:
            raise ApiError(
                "ERR_ALLERGEN_CHANGEOVER_NOT_VALIDATED",
                "no validated allergen changeover clean covers this run",
            )

    result = chemistry.compute_chemistry(system)
    db.stamp(run, "started_at", now)
    run["target_ppm_at_start"] = result["target_free_chlorine_ppm"]
    run["required_dwell_seconds_at_start"] = result["required_dwell_seconds"]
    run["run_status"] = "RUNNING"
    run["allergen_changeover_required"] = False
    db.touch(run)
    if line["last_run_allergen_group"] != product["allergen_group"]:
        line["last_run_allergen_group"] = product["allergen_group"]
        db.touch(line)
    return object_response(serializers.process_run(run))


# --------------------------------------------------------------------------
# lot consumptions
# --------------------------------------------------------------------------


def _check_run_version(run, expected):
    if expected != run["version"]:
        raise ApiError(
            "ERR_STALE_PROCESS_RUN_VERSION",
            "expected_process_run_version does not match the run's current version",
        )


@bp.post("/process-runs/<run_id>/lot-consumptions")
@require("LineOperator")
def create_consumption(run_id):
    body = read_body(CREATE_CONSUMPTION)
    run = db.get_or_404("process_runs", run_id)
    receipt = db.get_or_404("raw_receipts", body["raw_receipt_id"])
    _check_run_version(run, body["expected_process_run_version"])
    if run["run_status"] not in NON_TERMINAL_RUN_STATES:
        raise ApiError(
            "ERR_RUN_NOT_RUNNING", "the run no longer accepts consumption writes"
        )
    lot = db.get_or_404("grower_lots", receipt["grower_lot_id"])
    if lot["status"] != "APPROVED":
        raise ApiError(
            "ERR_GROWER_LOT_NOT_APPROVED", "the grower lot is not APPROVED"
        )
    if receipt["status"] != "ACCEPTED":
        raise ApiError("ERR_RECEIPT_NOT_ACCEPTED", "the load is not ACCEPTED")
    product = db.get_or_404("products", run["product_id"])
    if lot["commodity_class"] != product["commodity_class"]:
        raise ApiError(
            "ERR_COMMODITY_CLASS_MISMATCH",
            "the grower lot commodity class does not match the product",
        )
    if body["consumed_lb"] > receipt["remaining_lb"]:
        raise ApiError(
            "ERR_INSUFFICIENT_RECEIPT_BALANCE",
            "consumed_lb exceeds the load's remaining pounds",
        )
    row = db.new_row(
        "lot_consumptions",
        {
            "process_run_id": run["id"],
            "raw_receipt_id": receipt["id"],
            "consumed_lb": body["consumed_lb"],
            "status": "ACTIVE",
            "recorded_by_user_id": actor(),
            "voided_at": None,
            "_dt_voided_at": None,
        },
    )
    refresh_receipt_balance(receipt)
    refresh_run_input(run)
    db.touch(run)
    system = db.find("wash_systems", run["wash_system_id"])
    if system is not None:
        chemistry.apply_chemistry(system)
    return object_response(serializers.lot_consumption(row), 201)


@bp.get("/process-runs/<run_id>/lot-consumptions")
@require("PlantAdmin", "QAManager", "QATechnician", "LineOperator")
def list_run_consumptions(run_id):
    status = enum_param("status", enums.CONSUMPTION_STATUS)
    db.get_or_404("process_runs", run_id)
    rows = [c for c in db.rows("lot_consumptions") if c["process_run_id"] == run_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return listing(rows, serializers.lot_consumption)


@bp.get("/raw-receipts/<receipt_id>/lot-consumptions")
@require("PlantAdmin", "QAManager", "QATechnician", "LineOperator")
def list_receipt_consumptions(receipt_id):
    status = enum_param("status", enums.CONSUMPTION_STATUS)
    db.get_or_404("raw_receipts", receipt_id)
    rows = runs_of_receipt(receipt_id)
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return listing(rows, serializers.lot_consumption)


@bp.post("/lot-consumptions/<consumption_id>/void")
@require("LineOperator")
def void_consumption(consumption_id):
    body = read_body(VOID_CONSUMPTION)
    consumption = db.get_or_404("lot_consumptions", consumption_id)
    run = db.get_or_404("process_runs", consumption["process_run_id"])
    _check_run_version(run, body["expected_process_run_version"])
    if run["run_status"] not in NON_TERMINAL_RUN_STATES:
        raise ApiError("ERR_RUN_NOT_RUNNING", "the run no longer accepts void writes")
    if consumption["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONSUMPTION_ALREADY_VOIDED", "the consumption is already VOIDED"
        )
    consumption["status"] = "VOIDED"
    db.stamp(consumption, "voided_at", now_dt())
    db.touch(consumption)
    receipt = db.find("raw_receipts", consumption["raw_receipt_id"])
    if receipt is not None:
        refresh_receipt_balance(receipt)
    refresh_run_input(run)
    db.touch(run)
    system = db.find("wash_systems", run["wash_system_id"])
    if system is not None:
        chemistry.apply_chemistry(system)
    return object_response(serializers.lot_consumption(consumption))


# --------------------------------------------------------------------------
# closing a run
# --------------------------------------------------------------------------


def _closing_reading(readings):
    """The in-window reading with the greatest reading_at, tie greatest sequence_no."""
    best = None
    for r in readings:
        key = (db.dt_of(r, "reading_at"), r["sequence_no"])
        if best is None or key > (db.dt_of(best, "reading_at"), best["sequence_no"]):
            best = r
    return best


def _excursion_reference(readings, minimum):
    """The in-window reading with the lowest ppm, tie the lowest sequence_no."""
    best = None
    for r in readings:
        if r["free_chlorine_ppm"] >= minimum:
            continue
        key = (r["free_chlorine_ppm"], r["sequence_no"])
        if best is None or key < (best["free_chlorine_ppm"], best["sequence_no"]):
            best = r
    return best


def _pack_date_code(started_dt):
    return "%04d%02d%02d" % (started_dt.year, started_dt.month, started_dt.day)


@bp.post("/process-runs/<run_id>/close")
@require("LineOperator")
def close_run(run_id):
    body = read_body(CLOSE_RUN)
    run = db.get_or_404("process_runs", run_id)
    if run["run_status"] != "RUNNING":
        raise ApiError("ERR_RUN_NOT_RUNNING", "only a RUNNING run may be closed")
    line = db.get_or_404("lines", run["line_id"])
    product = db.get_or_404("products", run["product_id"])
    spec = db.get_or_404("customer_specs", run["customer_spec_id"])
    system = db.get_or_404("wash_systems", run["wash_system_id"])

    now = now_dt()
    started_dt = db.dt_of(run, "started_at")
    window = chemistry.window_readings(system["id"], started_dt, now)
    if not window:
        raise ApiError(
            "ERR_NO_ANTIMICROBIAL_READINGS",
            "no antimicrobial reading falls inside the run window",
        )
    frozen_dwell = run["required_dwell_seconds_at_start"] or 0
    required_dwell = max(product["min_dwell_seconds"], frozen_dwell)
    if body["actual_dwell_seconds"] < required_dwell:
        raise ApiError(
            "ERR_DWELL_TIME_INSUFFICIENT",
            "actual_dwell_seconds is below the required dwell time",
        )
    if body["atmosphere_actual"] != spec["atmosphere_required"]:
        raise ApiError(
            "ERR_ATMOSPHERE_MISMATCH",
            "atmosphere_actual does not match the specification",
        )
    if not shelflife.active_consumptions(run["id"]) or run["input_lb"] <= 0:
        raise ApiError("ERR_NO_LOTS_CONSUMED", "the run consumed no raw pounds")
    output_lb = q2(Decimal(body["cases_produced"]) * spec["case_net_weight_lb"])
    yield_pct = q2(output_lb / run["input_lb"] * Decimal(100))
    if yield_pct < product["min_yield_pct"] or yield_pct > YIELD_MAX_PCT:
        raise ApiError(
            "ERR_YIELD_OUT_OF_TOLERANCE", "the computed yield is outside tolerance"
        )

    run["actual_dwell_seconds"] = body["actual_dwell_seconds"]
    run["spin_rpm"] = body["spin_rpm"]
    run["spin_seconds"] = body["spin_seconds"]
    run["atmosphere_actual"] = body["atmosphere_actual"]
    run["water_gal_used"] = body["water_gal_used"]
    run["cases_produced"] = body["cases_produced"]
    run["output_lb"] = output_lb
    run["yield_pct"] = yield_pct

    minimum = product["min_antimicrobial_ppm"]
    run["min_ppm_observed"] = min(r["free_chlorine_ppm"] for r in window)
    excursions = [r for r in window if r["free_chlorine_ppm"] < minimum]
    run["antimicrobial_excursion_count"] = len(excursions)

    db.stamp(run, "closed_at", now)
    run["run_status"] = "CLOSED"

    days, code_date, label = shelflife.compute(run, started_dt, 0)
    run["provisional_shelf_life_days"] = days
    run["provisional_code_date"] = code_date

    closing = _closing_reading(window)
    run_minutes = floor_int(Decimal((now - started_dt).total_seconds()) / Decimal(60))
    costs = cost.compute(
        run,
        closing["topup_ppm_required"] if closing is not None else None,
        run_minutes,
    )
    run["total_run_cost_cents"] = costs["total_run_cost_cents"]
    run["per_case_cost_cents"] = costs["per_case_cost_cents"]
    run["cost_remainder_cents"] = costs["cost_remainder_cents"]

    prefix = line["line_code"] + "-" + _pack_date_code(started_dt) + "-"
    for sequence in range(1, body["cases_produced"] + 1):
        db.new_row(
            "finished_cases",
            {
                "process_run_id": run["id"],
                "case_sequence": sequence,
                "case_code": prefix + "%04d" % sequence,
                "net_weight_lb": spec["case_net_weight_lb"],
                "code_date": code_date,
                "code_date_label": label,
                "allocated_cost_cents": cost.allocated_for(
                    sequence,
                    costs["per_case_cost_cents"],
                    costs["cost_remainder_cents"],
                ),
                "status": "IN_INVENTORY",
                "shipped_at": None,
                "_dt_shipped_at": None,
            },
        )
    holds.recount(run)
    db.touch(run)

    db.stamp(line, "last_run_ended_at", now)
    db.touch(line)
    chemistry.apply_chemistry(system)

    if product["hold_and_release_required"]:
        holds.open_hold(run, "HOLD_AND_RELEASE_TESTING", now)
    if run["antimicrobial_excursion_count"] > 0:
        holds.open_hold(run, "ANTIMICROBIAL_EXCURSION", now)
        reference = _excursion_reference(window, minimum)
        cascades.open_corrective_action(
            line,
            "ANTIMICROBIAL_EXCURSION",
            reference["id"] if reference is not None else None,
            "MAJOR",
            now,
        )
        posture.recompute(line)
    return object_response(serializers.process_run(run))


@bp.get("/process-runs/<run_id>/finished-cases")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "LineOperator", "ShippingClerk"
)
def list_finished_cases(run_id):
    status = enum_param("status", enums.CASE_STATUS)
    db.get_or_404("process_runs", run_id)
    rows = holds.cases_of(run_id)
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return listing(rows, serializers.finished_case)


@bp.get("/process-runs/<run_id>/traceability")
@require("PlantAdmin", "QAManager", "QATechnician")
def traceability(run_id):
    run = db.get_or_404("process_runs", run_id)
    product = db.find("products", run["product_id"])
    spec = db.find("customer_specs", run["customer_spec_id"])
    consumptions = [
        c for c in db.rows("lot_consumptions") if c["process_run_id"] == run_id
    ]
    active = [c for c in consumptions if c["status"] == "ACTIVE"]
    receipt_ids = []
    lot_ids = []
    grower_codes = []
    for c in active:
        if c["raw_receipt_id"] not in receipt_ids:
            receipt_ids.append(c["raw_receipt_id"])
        receipt = db.find("raw_receipts", c["raw_receipt_id"])
        if receipt is None:
            continue
        lot = db.find("grower_lots", receipt["grower_lot_id"])
        if lot is None or lot["id"] in lot_ids:
            continue
        lot_ids.append(lot["id"])
        if lot["grower_code"] not in grower_codes:
            grower_codes.append(lot["grower_code"])
    cases = holds.cases_of(run_id)
    ancestors = []
    parent_id = run.get("rework_source_run_id")
    while parent_id is not None and parent_id not in ancestors:
        ancestors.append(parent_id)
        parent = db.find("process_runs", parent_id)
        if parent is None:
            break
        parent_id = parent.get("rework_source_run_id")
    effective = run["final_code_date"] or run["provisional_code_date"]
    return object_response(
        {
            "process_run_id": run["id"],
            "product_code": product["code"] if product else None,
            "customer_code": spec["customer_code"] if spec else None,
            "grower_lot_ids": lot_ids,
            "grower_codes": grower_codes,
            "raw_receipt_ids": receipt_ids,
            "active_consumption_count": len(active),
            "voided_consumption_count": len(consumptions) - len(active),
            "case_count": len(cases),
            "shipped_case_count": len([c for c in cases if c["status"] == "SHIPPED"]),
            "on_hold_case_count": len([c for c in cases if c["status"] == "ON_HOLD"]),
            "destroyed_case_count": len(
                [c for c in cases if c["status"] == "DESTROYED"]
            ),
            "effective_code_date": effective,
            "rework_source_run_id": run.get("rework_source_run_id"),
            "rework_ancestor_run_ids": ancestors,
        }
    )
