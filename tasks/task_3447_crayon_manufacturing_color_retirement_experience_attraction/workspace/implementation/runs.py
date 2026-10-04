"""Production runs and inventory lots (PRD section 3.4)."""
from datetime import timedelta

from flask import request

from calculations import (
    evaluate_packing, recompute_spec, rerun_waterfall, spec_is_deprecated,
)
from constants import LEAD_TIME_DAYS, OPS_ROLES, ROLE_PLATFORM_ADMIN, TOLERANCE_UNITS
from envelope import ok, paginate
from errors import ApiError
from store import STORE, parse_dt
from validation import (
    apply_filters, auth, body, get_or_404, new_entity, pagination_params,
    req_dt, req_enum, req_int, req_str, require_role, touch,
)

ADVANCE_NEXT = {"PLANNED": "MOLDING", "MOLDING": "LABELING", "LABELING": "PACKING"}
HOLDABLE_STAGES = ("MOLDING", "LABELING", "PACKING")
CANCELLABLE_STAGES = ("PLANNED", "MOLDING", "LABELING", "PACKING", "ON_HOLD")


def serialize_run(run):
    return {
        "id": run["id"],
        "assortment_spec_id": run["assortment_spec_id"],
        "pigment_batch_id": run["pigment_batch_id"],
        "planned_boxes": run["planned_boxes"],
        "planned_start_date": run["planned_start_date"],
        "planned_end_date": run["planned_end_date"],
        "stage": run["stage"],
        "stage_before_hold": run["stage_before_hold"],
        "hold_reason": run["hold_reason"],
        "packed_counts": run["packed_counts"],
        "packing_variance_units": run["packing_variance_units"],
        "packing_penalty_cents": run["packing_penalty_cents"],
        "boxes_produced": run["boxes_produced"],
        "waste_units": run["waste_units"],
        "run_seq": run["run_seq"],
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
        "version": run["version"],
    }


def serialize_lot(lot):
    return {
        "id": lot["id"],
        "production_run_id": lot["production_run_id"],
        "boxes_received": lot["boxes_received"],
        "boxes_on_hand": lot["boxes_on_hand"],
        "boxes_committed": lot["boxes_committed"],
        "boxes_shipped": lot["boxes_shipped"],
        "lot_seq": lot["lot_seq"],
        "status": lot["status"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def _batch_has_active_recall(batch_id):
    for case in STORE.recall_cases.values():
        if case["pigment_batch_id"] == batch_id and case["status"] in ("OPEN", "CONTAINED"):
            return True
    return False


def _check_run_gates(spec, batch, start, end):
    """Stage 10 linked-entity gates in the fixed intra-category order, plus the
    licensed term-window check once a covering line is known to exist."""
    # (a) every spec entry color covered by an APPROVED formula.
    for entry in spec["entries"]:
        covered = any(f["color_id"] == entry["color_id"] and f["status"] == "APPROVED"
                      for f in STORE.formulas.values())
        if not covered:
            raise ApiError("ERR_FORMULA_NOT_APPROVABLE")
    # (b) the pigment batch is CERTIFIED.
    if batch["status"] != "CERTIFIED":
        raise ApiError("ERR_BATCH_NOT_CERTIFIED")
    # (c) the spec is ACTIVE (DEPRECATED is the single gate for retired colors).
    if spec_is_deprecated(spec):
        raise ApiError("ERR_SPEC_DEPRECATED")
    # (d) LICENSED spec backed by an APPROVED line covering a spec color, with
    #     the planned dates contained in that line's term.
    if spec["kind"] == "LICENSED":
        color_ids = {e["color_id"] for e in spec["entries"]}
        covering = []
        for line in STORE.lines.values():
            if line["status"] != "APPROVED":
                continue
            formula = STORE.formulas.get(line["formula_id"])
            if formula is not None and formula["color_id"] in color_ids:
                covering.append(line)
        if not covering:
            raise ApiError("ERR_LICENSE_REQUIRED")
        contained = any(
            parse_dt(line["term_start"]) <= start and end <= parse_dt(line["term_end"])
            for line in covering)
        if not contained:
            raise ApiError("ERR_LICENSE_TERM_WINDOW")


def create_run():
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    data = body()
    spec_id = req_str(data, "assortment_spec_id")
    batch_id = req_str(data, "pigment_batch_id")
    planned_boxes = req_int(data, "planned_boxes")
    start_raw, start = req_dt(data, "planned_start_date")
    end_raw, end = req_dt(data, "planned_end_date")
    if planned_boxes < 1:
        raise ApiError("ERR_INVALID_REQUEST", "planned_boxes must be >= 1")
    # Existence (stage 4) in declared input order.
    spec = get_or_404(STORE.specs, spec_id)
    batch = get_or_404(STORE.batches, batch_id)
    # Business safety (stage 7): batch with an OPEN/CONTAINED recall gates runs.
    if _batch_has_active_recall(batch_id):
        raise ApiError("ERR_RECALL_ACTIVE")
    # Temporal (stage 8): end strictly after start; sixty-day lead time.
    if end <= start:
        raise ApiError("ERR_DATE_ORDER")
    if start < STORE.clock_dt + timedelta(days=LEAD_TIME_DAYS):
        raise ApiError("ERR_PLANNED_START_TOO_SOON")
    _check_run_gates(spec, batch, start, end)
    run = new_entity({
        "assortment_spec_id": spec_id,
        "pigment_batch_id": batch_id,
        "planned_boxes": planned_boxes,
        "planned_start_date": start_raw,
        "planned_end_date": end_raw,
        "stage": "PLANNED",
        "stage_before_hold": None,
        "hold_reason": None,
        "packed_counts": None,
        "packing_variance_units": 0,
        "packing_penalty_cents": 0,
        "boxes_produced": 0,
        "waste_units": 0,
        "run_seq": STORE.next_run_seq(),
    })
    STORE.runs[run["id"]] = run
    # A new PLANNED run grows the projected pool: re-run the waterfall.
    recompute_spec(spec)
    rerun_waterfall(spec)
    return ok(serialize_run(run), status=201)


def get_run(run_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    run = get_or_404(STORE.runs, run_id)
    return ok(serialize_run(run))


def list_runs():
    _, role = auth()
    require_role(role, OPS_ROLES)
    limit, offset = pagination_params()
    items = list(STORE.runs.values())
    items = apply_filters(items, [
        ("assortment_spec_id", request.args.get("assortment_spec_id")),
        ("pigment_batch_id", request.args.get("pigment_batch_id")),
        ("stage", request.args.get("stage")),
    ])
    items.sort(key=lambda r: (r["created_at"], r["run_seq"]))
    page, meta = paginate(items, limit, offset)
    return ok([serialize_run(r) for r in page], response_type="array", pagination=meta)


def _validate_packed_counts(spec, packed_counts):
    """packed_counts must cover exactly the spec entry colors (ERR_INVALID_REQUEST)."""
    if not isinstance(packed_counts, list):
        raise ApiError("ERR_INVALID_REQUEST", "packed_counts is required for the PACKING advance")
    packed_map = {}
    for line in packed_counts:
        if not isinstance(line, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each packed_counts line must be an object")
        color_id = line.get("color_id")
        count = line.get("count")
        if not isinstance(color_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "packed_counts.color_id must be a string")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ApiError("ERR_INVALID_REQUEST", "packed_counts.count must be an integer >= 0")
        if color_id in packed_map:
            raise ApiError("ERR_INVALID_REQUEST", "duplicate color in packed_counts")
        packed_map[color_id] = count
    expected_colors = {e["color_id"] for e in spec["entries"]}
    if set(packed_map) != expected_colors:
        raise ApiError("ERR_INVALID_REQUEST", "packed_counts must cover exactly the spec entry colors")
    return packed_map


def _complete_run(run, spec, packed_counts):
    """The packing-accuracy gate of the PACKING advance."""
    packed_map = _validate_packed_counts(spec, packed_counts)
    run["packed_counts"] = packed_counts
    variance, penalty, boxes_produced, waste = evaluate_packing(
        spec, run["planned_boxes"], packed_map)
    run["packing_variance_units"] = variance
    run["packing_penalty_cents"] = penalty
    if variance > TOLERANCE_UNITS:
        # Automatic quality hold: penalty recorded, no lot created.
        run["stage"] = "ON_HOLD"
        run["stage_before_hold"] = "PACKING"
        run["hold_reason"] = "QUALITY"
        touch(run)
        return
    run["stage"] = "COMPLETED"
    run["boxes_produced"] = boxes_produced
    run["waste_units"] = waste
    touch(run)
    lot = new_entity({
        "production_run_id": run["id"],
        "boxes_received": boxes_produced,
        "boxes_on_hand": boxes_produced,
        "boxes_committed": 0,
        "boxes_shipped": 0,
        "lot_seq": STORE.next_scoped(STORE.lot_seq, spec["id"]),
        "status": "AVAILABLE" if boxes_produced > 0 else "DEPLETED",
    })
    STORE.lots[lot["id"]] = lot
    recompute_spec(spec)
    rerun_waterfall(spec)


def run_transition(run_id):
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    data = body()
    action = req_enum(data, "action", ("ADVANCE", "HOLD", "RESUME", "CANCEL"))
    run = get_or_404(STORE.runs, run_id)
    spec = STORE.specs[run["assortment_spec_id"]]
    if action == "ADVANCE":
        if run["stage"] == "ON_HOLD":
            raise ApiError("ERR_RUN_ON_HOLD")
        if run["stage"] in ("COMPLETED", "CANCELLED", "QUARANTINED"):
            raise ApiError("ERR_RUN_STAGE_INVALID")
        if run["stage"] == "PACKING":
            _complete_run(run, spec, data.get("packed_counts"))
        else:
            run["stage"] = ADVANCE_NEXT[run["stage"]]
            touch(run)
    elif action == "HOLD":
        if run["stage"] not in HOLDABLE_STAGES:
            raise ApiError("ERR_RUN_STAGE_INVALID")
        run["stage_before_hold"] = run["stage"]
        run["stage"] = "ON_HOLD"
        run["hold_reason"] = "QUALITY"
        touch(run)
    elif action == "RESUME":
        if run["stage"] != "ON_HOLD":
            raise ApiError("ERR_RUN_STAGE_INVALID")
        run["stage"] = run["stage_before_hold"]
        run["stage_before_hold"] = None
        run["hold_reason"] = None
        touch(run)
    else:  # CANCEL
        if run["stage"] not in CANCELLABLE_STAGES:
            raise ApiError("ERR_RUN_STAGE_INVALID")
        run["stage"] = "CANCELLED"
        touch(run)
        # A cancelled run leaves the projected supply set.
        recompute_spec(spec)
        rerun_waterfall(spec)
    return ok(serialize_run(run))


def list_run_lots(run_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    get_or_404(STORE.runs, run_id)
    limit, offset = pagination_params()
    items = [lot for lot in STORE.lots.values() if lot["production_run_id"] == run_id]
    items = apply_filters(items, [("status", request.args.get("status"))])
    items.sort(key=lambda lot: (lot["created_at"], lot["lot_seq"]))
    page, meta = paginate(items, limit, offset)
    return ok([serialize_lot(lot) for lot in page], response_type="array", pagination=meta)


def register(app):
    app.add_url_rule("/crayon-works/production-runs", view_func=create_run, methods=["POST"])
    app.add_url_rule("/crayon-works/production-runs/<run_id>", view_func=get_run, methods=["GET"])
    app.add_url_rule("/crayon-works/production-runs", view_func=list_runs, methods=["GET"])
    app.add_url_rule("/crayon-works/production-runs/<run_id>/transition",
                     view_func=run_transition, methods=["POST"])
    app.add_url_rule("/crayon-works/production-runs/<run_id>/inventory-lots",
                     view_func=list_run_lots, methods=["GET"])
