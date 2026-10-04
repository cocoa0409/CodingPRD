# ProductionRun domain (PRD 3.5): OCC-guarded scheduling with line capacity
# reservation, the start/complete/abort lifecycle, and the big completion
# cascade (FIFO lot consumption, batch creation, program credit, line release).
from flask import Blueprint, request

import clock
import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from services import (
    consume_lots_fifo,
    expiry_from,
    recompute_program_attainment,
    required_isolate_kg,
    rhu0_int,
    total_available_isolate_kg,
)
from decimal import Decimal
from store import db, flush_dirty, make_entity, mark, public
from validation import Shape, body_json, get_dt, get_enum, get_int, get_str

bp = Blueprint("runs", __name__, url_prefix="/protein-ops/production-runs")

ANY_ROLE = constants.ROLES
RUN_STATES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "RELEASED", "RECALLED", "ABORTED"]
PLANT_TARGETS = ["IN_PROGRESS", "COMPLETED", "ABORTED"]
QUALITY_TARGETS = ["RELEASED", "RECALLED"]
RUN_TRANSITIONS = {
    ("SCHEDULED", "IN_PROGRESS"),
    ("IN_PROGRESS", "COMPLETED"),
    ("SCHEDULED", "ABORTED"),
    ("IN_PROGRESS", "ABORTED"),
    ("COMPLETED", "RELEASED"),
    ("COMPLETED", "RECALLED"),
}


@bp.route("", methods=["POST"])
def create_run():
    _user_id, role = authenticate()
    authorize(role, ["PlantManager"])

    body = body_json()
    shape = Shape()
    line_id = get_str(body, "production_line_id", shape)
    product_id = get_str(body, "product_id", shape)
    label_id = get_str(body, "label_version_id", shape)
    channel = get_enum(body, "channel", constants.CHANNELS, shape)
    planned_kg = get_int(body, "planned_quantity_kg", shape, minv=1)
    start_raw, start_dt = get_dt(body, "scheduled_start", shape)
    end_raw, end_dt = get_dt(body, "scheduled_end", shape)
    expected_line_version = get_int(body, "expected_line_version", shape)
    program_id = get_str(body, "program_id", shape, required=False)

    # Tier 3: body FK existence in declared input order:
    # production_line_id, product_id, label_version_id, (program_id last).
    line = product = label = program = None
    if line_id is not None:
        line = db["lines"].get(line_id)
        if line is None:
            raise err("ERR_NOT_FOUND", "production_line_id does not reference a production line")
    if product_id is not None:
        product = db["products"].get(product_id)
        if product is None:
            raise err("ERR_NOT_FOUND", "product_id does not reference a product")
    if label_id is not None:
        label = db["labels"].get(label_id)
        if label is None:
            raise err("ERR_NOT_FOUND", "label_version_id does not reference a label version")
    if program_id is not None:
        program = db["programs"].get(program_id)
        if program is None:
            raise err("ERR_NOT_FOUND", "program_id does not reference a program")

    # Tier 4 OCC: expected_line_version must equal the line's current version.
    if line is not None and expected_line_version is not None:
        if expected_line_version != line["version"]:
            raise err("ERR_STALE_LINE_VERSION", "expected_line_version does not match line version")

    # Tier 6 compliance: line certification must be CERTIFIED.
    if line is not None and line["certification_status"] != "CERTIFIED":
        raise err("ERR_LINE_NOT_CERTIFIED", "line certification_status is not CERTIFIED")

    # Tier 7 temporal, in listed order: window validity, line window conflict,
    # dedicated-run containment in the program window.
    if start_dt is not None and end_dt is not None and end_dt <= start_dt:
        raise err("ERR_INVALID_WINDOW", "scheduled_end must be after scheduled_start")
    if line is not None and start_dt is not None and end_dt is not None:
        for other in db["runs"].values():
            if other["production_line_id"] != line["id"]:
                continue
            if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
                continue
            o_start = other["_dt"]["scheduled_start"]
            o_end = other["_dt"]["scheduled_end"]
            # Half-open [start, end): touching windows are legal.
            if start_dt < o_end and o_start < end_dt:
                raise err("ERR_RUN_WINDOW_CONFLICT", "run window overlaps another run on the line")
    if program is not None and start_dt is not None and end_dt is not None:
        p_start = program["_dt"]["window_start"]
        p_end = program["_dt"]["window_end"]
        if not (p_start <= start_dt and end_dt <= p_end):
            raise err("ERR_RUN_OUTSIDE_PROGRAM_WINDOW", "run window is not contained in the program window")

    # Tier 8 structural, in sub-order: isolate support, then channel mapping.
    if line is not None and product is not None:
        if product["isolate_type"] not in line["supported_isolate_types"]:
            raise err("ERR_ISOLATE_NOT_SUPPORTED", "product isolate_type not supported by the line")
    if program is not None and channel is not None:
        if constants.PROGRAM_CHANNEL_MAP[program["program_type"]] != channel:
            raise err("ERR_CHANNEL_PROGRAM_MISMATCH", "run channel does not match the program type mapping")

    # Tier 9 cross-entity: product producibility, label approval, label-product
    # ownership, program acceptance — in listed order.
    if product is not None and product["status"] not in ("PILOT", "ACTIVE"):
        raise err("ERR_PRODUCT_NOT_PRODUCIBLE", "product status is not PILOT or ACTIVE")
    if label is not None and label["status"] != "APPROVED":
        raise err("ERR_LABEL_NOT_APPROVED", "pinned label version is not APPROVED")
    if label is not None and product is not None and label["product_id"] != product["id"]:
        raise err("ERR_LABEL_PRODUCT_MISMATCH", "label version belongs to a different product")
    if program is not None and program["status"] not in ("ACTIVE", "IN_WINDOW"):
        raise err("ERR_PROGRAM_NOT_ACCEPTING_RUNS", "program status is not ACTIVE or IN_WINDOW")

    # Tier 10 capacity: CO_MAN monthly contract, bucketed by scheduled_start's
    # calendar month over SCHEDULED/IN_PROGRESS/COMPLETED runs, plus the new run.
    if line is not None and line["site_type"] == "CO_MAN" and planned_kg is not None and start_dt is not None:
        month_key = (start_dt.year, start_dt.month)
        month_total = 0
        for other in db["runs"].values():
            if other["production_line_id"] != line["id"]:
                continue
            if other["status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
                continue
            o_start = other["_dt"]["scheduled_start"]
            if (o_start.year, o_start.month) == month_key:
                month_total += other["planned_quantity_kg"]
        if month_total + planned_kg > line["monthly_reserved_capacity_kg"]:
            raise err("ERR_CAPACITY_EXCEEDED", "monthly co-man capacity would be exceeded")

    # Tier 11: request shape (missing expected_line_version lands here).
    shape.raise_if_any()

    run = make_entity(
        "runs",
        {
            "production_line_id": line_id,
            "product_id": product_id,
            "label_version_id": label_id,
            "program_id": program_id,
            "is_dedicated": program_id is not None,
            "channel": channel,
            "planned_quantity_kg": planned_kg,
            "scheduled_start": start_raw,
            "scheduled_end": end_raw,
            "status": "SCHEDULED",
            "actual_quantity_kg": None,
            "required_isolate_kg": None,
            "consumed_lot_ids": [],
            "cases_produced": None,
            "unit_cost_cents_per_case": None,
        },
    )
    run["_dt"]["scheduled_start"] = start_dt
    run["_dt"]["scheduled_end"] = end_dt
    line["reserved_capacity_kg"] += planned_kg
    mark(line)
    flush_dirty()
    return success(public(run), "object", 201)


@bp.route("", methods=["GET"])
def list_runs():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["runs"].values())
    for param in ("production_line_id", "product_id", "label_version_id", "program_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r.get(param) == value]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, meta = paginate([public(r) for r in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/<rid>", methods=["GET"])
def get_run(rid):
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    run = db["runs"].get(rid)
    if run is None:
        raise err("ERR_NOT_FOUND", "production run not found")
    return success(public(run), "object", 200)


@bp.route("/<rid>/transitions", methods=["POST"])
def run_transition(rid):
    user_id, role = authenticate()

    body = body_json()
    shape = Shape()
    target = get_enum(body, "target_status", RUN_STATES, shape)
    actual_quantity_kg = get_int(body, "actual_quantity_kg", shape, required=False, minv=1)

    # Tier 2 authorization: endpoint admits PlantManager and QualityManager;
    # the permitted role then depends on the requested target (PRD 2.1).
    if role not in ("PlantManager", "QualityManager"):
        raise err("ERR_UNAUTHORIZED", "role %s is not permitted on this endpoint" % role)
    if target in PLANT_TARGETS and role != "PlantManager":
        raise err("ERR_UNAUTHORIZED", "target %s requires PlantManager" % target)
    if target in QUALITY_TARGETS and role != "QualityManager":
        raise err("ERR_UNAUTHORIZED", "target %s requires QualityManager" % target)

    # Tier 3: path existence.
    run = db["runs"].get(rid)
    if run is None:
        raise err("ERR_NOT_FOUND", "production run not found")

    # Tier 5: transition must exist from the current state.
    if target is not None and (run["status"], target) not in RUN_TRANSITIONS:
        raise err("ERR_INVALID_STATE", "no run transition %s -> %s" % (run["status"], target))

    line = db["lines"][run["production_line_id"]]
    product = db["products"][run["product_id"]]

    if target == "IN_PROGRESS":
        # Tier 6: certification must still be CERTIFIED.
        if line["certification_status"] != "CERTIFIED":
            raise err("ERR_LINE_NOT_CERTIFIED", "line certification_status is not CERTIFIED")
        # Tier 8 (last in sub-order): operational preconditions; dedicated runs
        # require the line to be exactly IDLE.
        if run["is_dedicated"]:
            if line["operational_status"] != "IDLE":
                raise err("ERR_LINE_OPERATIONAL_FORBIDDEN", "dedicated run start requires an IDLE line")
        elif line["operational_status"] not in ("IDLE", "SETUP"):
            raise err("ERR_LINE_OPERATIONAL_FORBIDDEN", "line operational_status forbids run start")

    if target == "COMPLETED":
        # Tier 10: released isolate of the matching type must cover the
        # requirement (ceil(actual * 0.85)).
        if actual_quantity_kg is not None:
            needed = required_isolate_kg(actual_quantity_kg)
            if total_available_isolate_kg(product["isolate_type"]) < needed:
                raise err("ERR_INSUFFICIENT_ISOLATE", "insufficient RELEASED isolate of the matching type")
        # Tier 11: actual_quantity_kg required > 0; must yield a full case.
        if actual_quantity_kg is None:
            shape.add("actual_quantity_kg", "is required when target_status is COMPLETED")
        elif actual_quantity_kg // constants.KG_PER_CASE == 0:
            shape.add("actual_quantity_kg", "must yield at least one full case (>= %d kg)" % constants.KG_PER_CASE)
        shape.raise_if_any()
        _complete_run(run, line, product, actual_quantity_kg)
    elif target == "IN_PROGRESS":
        shape.raise_if_any()
        run["status"] = "IN_PROGRESS"
        mark(run)
        line["operational_status"] = "RUNNING"
        mark(line)
    elif target == "ABORTED":
        shape.raise_if_any()
        was_in_progress = run["status"] == "IN_PROGRESS"
        run["status"] = "ABORTED"
        mark(run)
        line["reserved_capacity_kg"] -= run["planned_quantity_kg"]
        if was_in_progress:
            line["operational_status"] = "CLEANING"
        mark(line)
    elif target == "RELEASED":
        shape.raise_if_any()
        run["status"] = "RELEASED"
        mark(run)
    elif target == "RECALLED":
        shape.raise_if_any()
        run["status"] = "RECALLED"
        mark(run)
        for batch in db["batches"].values():
            if batch["production_run_id"] == run["id"]:
                batch["recall_flag"] = True
                mark(batch)
    else:
        shape.raise_if_any()  # missing/invalid target_status
        return  # unreachable

    flush_dirty()
    return success(public(run), "object", 200)


def _complete_run(run, line, product, actual_quantity_kg):
    """The completion cascade (PRD 3.5): FIFO consumption, lot depletion,
    agreement completion, batch creation, dedicated-program credit, line
    release."""
    needed = required_isolate_kg(actual_quantity_kg)
    consumed_ids, total_cost = consume_lots_fifo(product["isolate_type"], needed)

    cases_produced = actual_quantity_kg // constants.KG_PER_CASE  # floor
    unit_cost_per_case = rhu0_int(Decimal(total_cost) / Decimal(cases_produced))

    run["status"] = "COMPLETED"
    run["actual_quantity_kg"] = actual_quantity_kg
    run["required_isolate_kg"] = needed
    run["consumed_lot_ids"] = consumed_ids
    run["cases_produced"] = cases_produced
    run["unit_cost_cents_per_case"] = unit_cost_per_case
    mark(run)

    produced_dt = clock.now()
    dedicated = run["is_dedicated"]
    batch = make_entity(
        "batches",
        {
            "production_run_id": run["id"],
            "product_id": run["product_id"],
            "channel": run["channel"],
            "quantity_cases": cases_produced,
            "available_cases": 0 if dedicated else cases_produced,
            "reserved_cases": cases_produced if dedicated else 0,
            "written_off_cases": 0,
            "reserved_for_program_id": run["program_id"] if dedicated else None,
            "produced_at": clock.now_canonical(),
            "expiry_date": clock.fmt_canonical(expiry_from(produced_dt, run["channel"])),
            "unit_cost_cents_per_case": unit_cost_per_case,
            "recall_flag": False,
        },
    )
    batch["_dt"]["produced_at"] = produced_dt
    batch["_dt"]["expiry_date"] = expiry_from(produced_dt, run["channel"])

    if dedicated:
        program = db["programs"][run["program_id"]]
        program["delivered_cases"] += cases_produced
        recompute_program_attainment(program)
        mark(program)

    line["operational_status"] = "CLEANING"
    line["reserved_capacity_kg"] -= run["planned_quantity_kg"]
    mark(line)
