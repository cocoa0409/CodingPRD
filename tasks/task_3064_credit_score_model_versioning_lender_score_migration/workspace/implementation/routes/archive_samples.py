"""Archive sample endpoints."""

from flask import Blueprint, request

from core import (
    DB, new_record, store, ok, ok_list, resolve_actor, score_model, archive_sample,
    body_of, reject_unknown, require_fields, as_int, as_str, as_enum,
    read_pagination, paginate, ordered_rows, month_tuple,
    MONTH_MIN, SAMPLE_WINDOW_MAX,
)
from errors import ApiError

bp = Blueprint("archive_samples", __name__)

READ_ROLES = [
    "BureauAdministrator", "ModelDeveloper", "ValidationAnalyst", "ComplianceOfficer",
    "FairLendingOfficer",
]
WRITE_ROLES = ["ModelDeveloper", "ValidationAnalyst"]

SEGMENTS = {"PRIME", "NEAR_PRIME", "SUBPRIME", "THIN_FILE"}
KINDS = {"DEVELOPMENT", "VALIDATION"}


def _windows_conflict(a_start, a_end, b_start, b_end):
    """Containment-tolerant overlap: a window fully contained in another is fine,
    a partial overlap is not."""
    if not (a_start < b_end and b_start < a_end):
        return False
    a_contained = a_start >= b_start and a_end <= b_end
    b_contained = b_start >= a_start and b_end <= a_end
    return not (a_contained or b_contained)


@bp.post("/archive-samples")
def create_sample():
    resolve_actor(request, WRITE_ROLES)
    body = body_of(request)
    reject_unknown(body, {"score_model_id", "sample_ref", "record_count", "segment_name",
                          "sample_kind", "observation_window_months",
                          "window_start_month", "window_end_month"})
    require_fields(body, ["score_model_id", "sample_ref", "record_count", "segment_name",
                          "sample_kind", "observation_window_months",
                          "window_start_month", "window_end_month"])

    model = score_model(as_str(body["score_model_id"], "score_model_id"))
    sample_ref = as_str(body["sample_ref"], "sample_ref")
    record_count = as_int(body["record_count"])
    segment_name = as_enum(body["segment_name"], SEGMENTS, "segment_name")
    sample_kind = as_enum(body["sample_kind"], KINDS, "sample_kind")
    observation_window_months = as_int(body["observation_window_months"])
    window_start_month = as_str(body["window_start_month"], "window_start_month")
    window_end_month = as_str(body["window_end_month"], "window_end_month")

    start = month_tuple(window_start_month)
    end = month_tuple(window_end_month)

    if record_count < 1:
        raise ApiError("ERR_INVALID_REQUEST", "record_count must be at least 1.")
    if observation_window_months < 6:
        raise ApiError("ERR_INVALID_REQUEST", "observation_window_months must be at least 6.")
    if start < MONTH_MIN:
        raise ApiError("ERR_INVALID_REQUEST", "window_start_month must be no earlier than 2015-01.")
    if not (start < end):
        raise ApiError("ERR_INVALID_REQUEST", "window_start_month must be strictly before window_end_month.")
    if end > SAMPLE_WINDOW_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "window_end_month must be no later than 2026-09.")

    for existing in DB["archive_samples"].values():
        if existing["score_model_id"] != model["id"]:
            continue
        same_window = (existing["window_start_month"] == window_start_month
                       and existing["window_end_month"] == window_end_month)
        if existing["sample_ref"] == sample_ref:
            if same_window:
                # Exact retry: undoing the duplicate rather than creating an overlap.
                return ok(existing, 201)
            raise ApiError("ERR_SAMPLE_WINDOW_OVERLAP")
        if _windows_conflict(start, end,
                             month_tuple(existing["window_start_month"]),
                             month_tuple(existing["window_end_month"])):
            raise ApiError("ERR_SAMPLE_WINDOW_OVERLAP")

    rec = new_record()
    rec.update({
        "score_model_id": model["id"],
        "sample_ref": sample_ref,
        "record_count": record_count,
        "segment_name": segment_name,
        "sample_kind": sample_kind,
        "window_start_month": window_start_month,
        "window_end_month": window_end_month,
        "observation_window_months": observation_window_months,
    })
    store("archive_samples", rec)
    return ok(rec, 201)


@bp.get("/archive-samples/<sample_id>")
def get_sample(sample_id):
    resolve_actor(request, READ_ROLES)
    return ok(archive_sample(sample_id))


@bp.get("/archive-samples")
def list_samples():
    resolve_actor(request, READ_ROLES)
    limit, offset = read_pagination(request)
    rows = ordered_rows("archive_samples")

    model_id = request.args.get("score_model_id")
    if model_id is not None:
        rows = [r for r in rows if r["score_model_id"] == model_id]
    kind = request.args.get("sample_kind")
    if kind is not None:
        rows = [r for r in rows if r["sample_kind"] == kind]

    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)