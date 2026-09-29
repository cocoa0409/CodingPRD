"""Residual batches: ingest, lines, normalize, recall, post, reverse (PRD 3.4, 3.5)."""
from flask import Blueprint

from apierrors import fail
from auth import authorize
from calc import lines_of_batch, normalize_batch, post_batch, recall_batch, reverse_batch
from envelope import apply_filters, list_response, object_response
from serial import batch as ser_batch
from serial import line as ser_line
from shapes import as_date, as_id, as_int, as_month_string, as_str, body, check_month
from store import (
    db,
    index_to_month,
    month_first_day,
    month_index,
    new_id,
    next_month_first_day,
    ordered,
    parse_date,
    stamp_new,
    touch,
)

bp = Blueprint("batches", __name__)


def _lookup(batch_id):
    row = db.batches.get(batch_id)
    if row is None:
        fail("ERR_BATCH_NOT_FOUND", "no residual batch with id %s" % batch_id)
    return row


def _program_of(batch):
    return db.programs.get(batch["processor_program_id"])


def _require_program_active(batch):
    """Band 12: ERR_PROGRAM_SUSPENDED whenever the governing program is not ACTIVE."""
    program = _program_of(batch)
    if program is None or program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_SUSPENDED", "the governing processor program is SUSPENDED")


def _require_period_open(batch):
    """Band 11: ERR_PERIOD_LOCKED once any statement for the month has been reported."""
    for statement in db.statements.values():
        if statement["period_month"] != batch["period_month"]:
            continue
        if statement["lifecycle_state"] in ("ISSUED", "FINALIZED"):
            fail("ERR_PERIOD_LOCKED",
                 "period %s already carries an issued or finalized statement"
                 % batch["period_month"])


@bp.route("/residual-batches", methods=["POST"])
def ingest_batch():
    authorize("IsoAdmin", "ResidualAnalyst")
    payload = body()
    # band 4
    processor_program_id = as_id(payload, "processor_program_id")
    period_month = as_month_string(payload, "period_month")
    coverage_start = as_date(payload, "coverage_start")
    coverage_end = as_date(payload, "coverage_end")
    file_checksum = as_str(payload, "file_checksum", min_len=8, max_len=80)
    # band 5
    check_month(period_month, "period_month")
    # band 7
    program = db.programs.get(processor_program_id)
    if program is None:
        fail("ERR_REFERENCED_PROGRAM_NOT_FOUND",
             "no processor program with id %s" % processor_program_id)
    # band 11 -- coverage window shape, then collision with an existing file
    start = parse_date(coverage_start)
    end = parse_date(coverage_end)
    first_day = month_first_day(period_month)
    next_first_day = next_month_first_day(period_month)
    spill_limit = month_first_day(index_to_month(month_index(period_month) + 2))
    if end <= start:
        fail("ERR_COVERAGE_WINDOW_INVALID",
             "coverage_end must be strictly later than coverage_start")
    if start < first_day or start >= next_first_day:
        fail("ERR_COVERAGE_WINDOW_INVALID",
             "coverage_start must fall inside the accounting month")
    if end > spill_limit:
        fail("ERR_COVERAGE_WINDOW_INVALID",
             "coverage_end may spill at most one month past the accounting month")
    for other in db.batches.values():
        if other["processor_program_id"] != processor_program_id:
            continue
        if other["state"] == "REVERSED":
            continue
        other_start = parse_date(other["coverage_start"])
        other_end = parse_date(other["coverage_end"])
        if start < other_end and other_start < end:
            fail("ERR_COVERAGE_OVERLAP",
                 "the coverage window overlaps an existing batch of this program")
    # band 12
    if program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_SUSPENDED", "the named processor program is SUSPENDED")
    for other in db.batches.values():
        if other["state"] == "REVERSED":
            continue
        if other["file_checksum"] == file_checksum:
            fail("ERR_DUPLICATE_FILE_CHECKSUM",
                 "file_checksum %s is already in use" % file_checksum)
    row = {
        "id": new_id(),
        "processor_program_id": processor_program_id,
        "period_month": period_month,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "file_checksum": file_checksum,
        "state": "RECEIVED",
        "line_count": 0,
        "recall_count": 0,
        "gross_volume_cents": 0,
        "total_normalized_net_revenue_cents": 0,
        "iso_retained_cents": 0,
        "posted_at": None,
    }
    stamp_new(row)
    db.batches[row["id"]] = row
    return object_response(ser_batch(row), 201)


@bp.route("/residual-batches", methods=["GET"])
def list_batches():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    rows = apply_filters(
        list(db.batches.values()),
        [("processor_program_id", "processor_program_id"),
         ("period_month", "period_month"), ("state", "state")])
    return list_response(ordered(rows), ser_batch)


@bp.route("/residual-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    return object_response(ser_batch(_lookup(batch_id)))


@bp.route("/residual-batches/<batch_id>/lines", methods=["POST"])
def append_line(batch_id):
    authorize("IsoAdmin", "ResidualAnalyst")
    payload = body()
    # band 4
    merchant_id = as_id(payload, "merchant_id")
    transaction_count = as_int(payload, "transaction_count", minimum=0)
    sales_volume_cents = as_int(payload, "sales_volume_cents", minimum=0)
    interchange_cents = as_int(payload, "interchange_cents", minimum=0)
    assessments_cents = as_int(payload, "assessments_cents", minimum=0)
    gross_income_cents = as_int(payload, "gross_income_cents", minimum=0)
    # band 6
    batch = _lookup(batch_id)
    # band 7
    merchant = db.merchants.get(merchant_id)
    if merchant is None:
        fail("ERR_REFERENCED_MERCHANT_NOT_FOUND", "no merchant with id %s" % merchant_id)
    # band 9
    if batch["state"] != "RECEIVED":
        fail("ERR_BATCH_STATE_INVALID", "lines may only be appended while the batch is RECEIVED")
    # band 12
    _require_program_active(batch)
    for line in db.lines.values():
        if line["residual_batch_id"] == batch_id and line["merchant_id"] == merchant_id:
            fail("ERR_DUPLICATE_LINE_FOR_MERCHANT",
                 "this batch already carries a line for merchant %s" % merchant_id)
    if merchant["processor_program_id"] != batch["processor_program_id"]:
        fail("ERR_LINE_PROGRAM_MISMATCH",
             "the merchant is not boarded on this batch's processor program")
    row = {
        "id": new_id(),
        "residual_batch_id": batch_id,
        "merchant_id": merchant_id,
        "transaction_count": transaction_count,
        "sales_volume_cents": sales_volume_cents,
        "interchange_cents": interchange_cents,
        "assessments_cents": assessments_cents,
        "gross_income_cents": gross_income_cents,
        "processor_cost_cents": 0,
        "normalized_net_revenue_cents": 0,
        "normalization_mode_applied": None,
    }
    stamp_new(row)
    db.lines[row["id"]] = row
    batch["line_count"] = len(lines_of_batch(batch_id))
    touch(batch)
    return object_response(ser_line(row), 201)


@bp.route("/residual-batches/<batch_id>/normalize", methods=["POST"])
def normalize(batch_id):
    authorize("IsoAdmin", "ResidualAnalyst")
    batch = _lookup(batch_id)
    if batch["state"] != "RECEIVED":
        fail("ERR_BATCH_STATE_INVALID", "normalization is only available from RECEIVED")
    _require_program_active(batch)
    normalize_batch(batch)
    return object_response(ser_batch(batch))


@bp.route("/residual-batches/<batch_id>/recall", methods=["POST"])
def recall(batch_id):
    authorize("IsoAdmin", "ResidualAnalyst")
    batch = _lookup(batch_id)
    if batch["state"] != "NORMALIZED":
        fail("ERR_BATCH_STATE_INVALID", "recall is only available from NORMALIZED")
    recall_batch(batch)
    return object_response(ser_batch(batch))


@bp.route("/residual-batches/<batch_id>/post", methods=["POST"])
def post(batch_id):
    authorize("ResidualController")
    batch = _lookup(batch_id)
    # band 9
    if batch["state"] != "NORMALIZED":
        fail("ERR_BATCH_STATE_INVALID", "posting is only available from NORMALIZED")
    # band 11
    _require_period_open(batch)
    # band 12
    _require_program_active(batch)
    post_batch(batch)
    return object_response(ser_batch(batch))


@bp.route("/residual-batches/<batch_id>/reverse", methods=["POST"])
def reverse(batch_id):
    authorize("ResidualController")
    batch = _lookup(batch_id)
    # band 9
    if batch["state"] != "POSTED":
        fail("ERR_BATCH_STATE_INVALID", "reversal is only available from POSTED")
    # band 11
    _require_period_open(batch)
    reverse_batch(batch)
    return object_response(ser_batch(batch))
