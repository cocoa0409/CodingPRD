"""Contact governance, test-cell measurement and matchback attribution."""

from flask import Blueprint

import validate as v
from db import db, new_row, now, touch
from errors import ApiError
from middleware import ALL_ROLES, MARKETING_ANALYST, NO_BROKER, auth
from response import entity_response, list_response
from services import domain
from routes.drops import find_drop
from routes.lines import find_line

bp = Blueprint("measure", __name__)

CHANNELS = ("MAIL", "EMAIL", "DIGITAL")
TEST_TYPES = ("SEGMENT", "FORMAT", "OFFER")
CELL_ROLES = ("TEST", "CONTROL", "HOLDOUT")
CELL_STATUSES = ("PLANNED", "MEASURED")
ATTRIBUTION_VARIANTS = ("LAST_TOUCH_MAIL", "FRACTIONAL_MULTI_TOUCH")
RUN_STATUSES = ("OPEN", "FINALIZED", "SUPERSEDED")
DEFAULT_ATTRIBUTION_WINDOW_DAYS = 90


def find_test_cell(cell_id):
    cell = db.test_cells.get(cell_id)
    if cell is None:
        raise ApiError("ERR_TEST_CELL_NOT_FOUND")
    return cell


def find_matchback_run(run_id):
    run = db.matchback_runs.get(run_id)
    if run is None:
        raise ApiError("ERR_MATCHBACK_RUN_NOT_FOUND")
    return run


# ---------------------------------------------------------------------------
# 3.8  Contact events
# ---------------------------------------------------------------------------


@bp.post("/contact-events")
def create_contact_event():
    auth(MARKETING_ANALYST)
    body = v.json_body()

    # Ladder step 4 — body foreign keys resolve.
    raw_segment = body.get("housefile_segment_id")
    if isinstance(raw_segment, str) and raw_segment.strip() != "":
        if raw_segment not in db.segments:
            raise ApiError("ERR_SEGMENT_NOT_FOUND")
    raw_drop = body.get("drop_id")
    if isinstance(raw_drop, str) and raw_drop.strip() != "":
        if raw_drop not in db.drops:
            raise ApiError("ERR_DROP_NOT_FOUND")

    # Ladder step 5 — schema.
    segment_id = v.get_id(body, "housefile_segment_id")
    if segment_id not in db.segments:
        raise ApiError("ERR_SEGMENT_NOT_FOUND")
    channel = v.get_enum(body, "channel", CHANNELS)
    contact_date = v.get_dt(body, "contact_date")
    drop_id = v.get_id(body, "drop_id", required=False)
    if drop_id is not None and drop_id not in db.drops:
        raise ApiError("ERR_DROP_NOT_FOUND")
    v.get_optional_text(body, "source")

    segment = db.segments[segment_id]

    # Ladder step 13 — the first matching enabled rule decides the hard cap.
    rule = domain.applicable_suppression_rule(segment["season_id"], channel)
    if rule is not None:
        existing = domain.count_in_window(segment_id, rule)
        if existing + 1 > rule["max_contacts_per_window"]:
            raise ApiError("ERR_CONTACT_CAP_EXCEEDED")

    row = domain.create_contact_event(
        segment_id, drop_id, channel, contact_date, "MANUAL_LOG"
    )
    # The pressure aggregation and sticky suppression follow the new row, and a
    # flip carries on into the line-retirement hops exactly as it does on mail.
    if domain.recompute_fatigue(segment):
        domain.cascade_suppress_segment_lines(segment_id)
    return entity_response(row, 201)


# ---------------------------------------------------------------------------
# 3.9  Test cells
# ---------------------------------------------------------------------------


@bp.post("/circulation-lines/<line_id>/test-cells")
def create_test_cell(line_id):
    auth(MARKETING_ANALYST)
    line = find_line(line_id)
    body = v.json_body()

    # Ladder step 5 — schema.
    cell_code = v.get_str(body, "cell_code", min_len=1)
    test_type = v.get_enum(body, "test_type", TEST_TYPES)
    cell_role = v.get_enum(body, "cell_role", CELL_ROLES)
    quantity = v.get_int(body, "quantity", minimum=1)

    # Ladder step 9 — only an allocated line has names to split.
    if line["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_LINE_STATE")

    siblings = domain.cells_of_line(line["id"])

    # Ladder step 19 — cell code unique within the line.
    for other in siblings:
        if other["cell_code"] == cell_code:
            raise ApiError("ERR_DUPLICATE_TEST_CELL_CODE")

    # Ladder step 24 — at most one control cell per line.
    if cell_role == "CONTROL":
        for other in siblings:
            if other["cell_role"] == "CONTROL":
                raise ApiError("ERR_DUPLICATE_CONTROL_CELL")

    # Ladder step 25 — the design may not consume more names than the line won.
    if sum(c["quantity"] for c in siblings) + quantity > line["allocated_quantity"]:
        raise ApiError("ERR_TEST_CELL_QUANTITY_EXCEEDS_LINE")

    row = new_row()
    row.update(
        {
            "circulation_line_id": line["id"],
            "cell_code": cell_code,
            "test_type": test_type,
            "cell_role": cell_role,
            "quantity": quantity,
            "status": "PLANNED",
            "significance": "UNMEASURED",
            "responders": 0,
            "demand_cents": 0,
            "response_rate_bps": 0,
            "lift_bps": 0,
        }
    )
    db.test_cells[row["id"]] = row
    return entity_response(row, 201)


@bp.get("/circulation-lines/<line_id>/test-cells")
def list_test_cells(line_id):
    auth(*NO_BROKER)
    line = find_line(line_id)
    limit, offset = v.pagination()
    cell_role = v.filter_enum("cell_role", CELL_ROLES)
    status = v.filter_enum("status", CELL_STATUSES)
    matching = [
        c for c in db.test_cells.values() if c["circulation_line_id"] == line["id"]
    ]
    if cell_role is not None:
        matching = [c for c in matching if c["cell_role"] == cell_role]
    if status is not None:
        matching = [c for c in matching if c["status"] == status]
    matching.sort(key=lambda c: (c["cell_code"], c["created_at"], c["_seq"]))
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


@bp.get("/test-cells/<cell_id>")
def read_test_cell(cell_id):
    auth(*NO_BROKER)
    return entity_response(find_test_cell(cell_id))


@bp.post("/test-cells/<cell_id>/measure")
def measure_test_cell(cell_id):
    auth(MARKETING_ANALYST)
    cell = find_test_cell(cell_id)
    body = v.json_body()

    # Ladder step 5 — schema.
    responders = v.get_int(body, "responders", minimum=0)
    demand_cents = v.get_int(body, "demand_cents", minimum=0)
    if responders > cell["quantity"]:
        v.invalid("Field 'responders' may not exceed the cell's quantity.")

    line = db.lines[cell["circulation_line_id"]]
    drop = domain.drop_of_line(line)

    # Ladder step 9 — the mail must have gone out, and MEASURED is terminal.
    if drop["production_status"] not in ("MAILED", "DELIVERED"):
        raise ApiError("ERR_INVALID_DROP_STATE")
    if cell["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_TEST_CELL_STATE")

    cell["responders"] = responders
    cell["demand_cents"] = demand_cents
    cell["status"] = "MEASURED"
    domain.score_test_cell(cell)
    touch(cell)

    # A sibling's lift depends on a control that may not have existed when the
    # sibling was measured, so every other measured cell is re-scored.
    for sibling in domain.cells_of_line(line["id"]):
        if sibling["id"] == cell["id"]:
            continue
        if sibling["status"] != "MEASURED":
            continue
        domain.score_test_cell(sibling)
    return entity_response(cell)


# ---------------------------------------------------------------------------
# 3.9  Matchback attribution
# ---------------------------------------------------------------------------


@bp.post("/drops/<drop_id>/matchback-runs")
def create_matchback_run(drop_id):
    auth(MARKETING_ANALYST)
    drop = find_drop(drop_id)
    body = v.json_body()

    # Ladder step 5 — schema.
    expected_drop_version = v.get_int(body, "expected_drop_version", minimum=0)
    variant = v.get_enum(body, "attribution_variant", ATTRIBUTION_VARIANTS)
    window_days = v.get_int(
        body,
        "attribution_window_days",
        required=False,
        default=DEFAULT_ATTRIBUTION_WINDOW_DAYS,
        minimum=1,
        maximum=180,
    )

    # Ladder step 9 — the single guard that couples the two dimensions, read
    # without changing the production side, then the measurement dimension.
    if drop["production_status"] not in ("MAILED", "DELIVERED"):
        raise ApiError("ERR_INVALID_DROP_STATE")
    if drop["measurement_status"] == "MATCHBACK_CLOSED":
        raise ApiError("ERR_INVALID_MEASUREMENT_STATE")

    # Ladder step 10 — optimistic concurrency on the drop.
    if expected_drop_version != drop["version"]:
        raise ApiError("ERR_STALE_DROP_VERSION")

    if drop["measurement_status"] == "PENDING":
        drop["measurement_status"] = "MATCHBACK_OPEN"
    else:
        # Self-loop: a fresh read supersedes every prior run on this drop.
        for other in domain.by_created(list(db.matchback_runs.values())):
            if other["drop_id"] != drop["id"]:
                continue
            if other["status"] not in ("OPEN", "FINALIZED"):
                continue
            other["status"] = "SUPERSEDED"
            touch(other)

    figures = domain.compute_matchback(drop, variant, window_days)
    row = new_row()
    row.update(
        {
            "drop_id": drop["id"],
            "observed_drop_version": expected_drop_version,
            "attribution_variant": variant,
            "attribution_window_days": window_days,
            "status": "OPEN",
            "finalized_at": None,
        }
    )
    row.update(figures)
    db.matchback_runs[row["id"]] = row
    touch(drop)
    return entity_response(row, 201)


@bp.get("/drops/<drop_id>/matchback-runs")
def list_matchback_runs(drop_id):
    auth(*NO_BROKER)
    drop = find_drop(drop_id)
    limit, offset = v.pagination()
    status = v.filter_enum("status", RUN_STATUSES)
    matching = [r for r in db.matchback_runs.values() if r["drop_id"] == drop["id"]]
    if status is not None:
        matching = [r for r in matching if r["status"] == status]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    page, total = v.paginate(matching, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/matchback-runs/<run_id>/finalize")
def finalize_matchback_run(run_id):
    auth(MARKETING_ANALYST)
    run = find_matchback_run(run_id)
    v.json_body()
    drop = db.drops[run["drop_id"]]

    # Ladder step 9 — the run's own state, then the drop's measurement state.
    if run["status"] != "OPEN":
        raise ApiError("ERR_INVALID_MATCHBACK_STATE")
    if drop["measurement_status"] != "MATCHBACK_OPEN":
        raise ApiError("ERR_INVALID_MEASUREMENT_STATE")

    run["finalized_at"] = now()
    run["status"] = "FINALIZED"
    touch(run)
    drop["measurement_status"] = "MATCHBACK_CLOSED"
    touch(drop)
    return entity_response(run)
