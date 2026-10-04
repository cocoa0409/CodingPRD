"""Response ingest (with synchronous quality classification) and the
per-frame response listing."""
from flask import Blueprint, request

from db import clock, store
from envelope import ok_list, ok_object
from errors import fail
from middleware import OPS_READ_ROLES, require
from records import new_record, ser_response
from services import factors_of
from validation import Body, parse_limit_offset

bp = Blueprint("responses", __name__, url_prefix="/research")


@bp.post("/responses")
@require("FieldOps")
def create_response():
    b = Body()
    frame_id = b.str_("frame_id")
    token = b.str_("respondent_token")
    duration = b.int_("duration_seconds")
    item_count = b.int_("item_count")
    distinct = b.int_("distinct_values")
    factor_scores = b.list_("factor_scores")
    # existence (priority 3)
    frame = store.sample_frames.get(frame_id) if frame_id is not None else None
    if frame_id is not None and frame is None:
        fail("ERR_NOT_FOUND", "frame_id does not reference an existing sample frame")
    # state (priority 5): parent study gate beats the frame gate
    study = store.studies.get(frame["study_id"]) if frame is not None else None
    if study is not None and study["status"] != "FIELDING":
        fail("ERR_STUDY_NOT_FIELDING", "Response ingest requires the study to be FIELDING")
    if frame is not None and frame["status"] != "OPEN":
        fail("ERR_FRAME_NOT_OPEN", "Response ingest requires an OPEN frame")
    # referential integrity (priority 9): range, then codes, then coverage
    if study is not None and factor_scores is not None:
        entries_ok = all(isinstance(e, dict) for e in factor_scores)
        if not entries_ok:
            b.bad = True
        else:
            mv = store.methodology_versions.get(study["active_methodology_id"])
            codes = {f["code"] for f in factors_of(mv["id"])} if mv is not None else set()
            for e in factor_scores:
                sc = e.get("score")
                if isinstance(sc, bool) or not isinstance(sc, int) or sc < 1 or sc > 10:
                    fail("ERR_SCORE_OUT_OF_RANGE", "factor score must be an integer in 1..10")
            for e in factor_scores:
                if e.get("factor_code") not in codes:
                    fail("ERR_UNKNOWN_FACTOR", "factor_code is not defined by the pinned methodology")
            provided = {e.get("factor_code") for e in factor_scores}
            if not codes.issubset(provided):
                fail("ERR_FACTOR_COVERAGE_INCOMPLETE", "factor_scores must cover every pinned factor")
    # syntactic (priority 11)
    b.finalize()
    if duration < 0 or item_count < 1 or distinct < 1:
        fail("ERR_INVALID_REQUEST", "duration_seconds >= 0, item_count >= 1, distinct_values >= 1 required")
    # synchronous quality classification off the pinned methodology
    mv = store.methodology_versions.get(study["active_methodology_id"])
    if duration < mv["min_duration_seconds"]:
        quality_status, reject_reason = "REJECTED", "SPEEDER"
    elif distinct == 1 and item_count >= mv["straightline_min_items"]:
        quality_status, reject_reason = "REJECTED", "STRAIGHTLINE"
    else:
        quality_status, reject_reason = "ACCEPTED", None
    norm_scores = [
        {"factor_code": e.get("factor_code"), "score": e.get("score")}
        for e in factor_scores
    ]
    rec = new_record()
    rec.update({
        "frame_id": frame_id,
        "respondent_token": token,
        "duration_seconds": duration,
        "item_count": item_count,
        "distinct_values": distinct,
        "factor_scores": norm_scores,
        "study_id": frame["study_id"],
        "brand_id": frame["brand_id"],
        "submitted_at": clock.now(),
        "quality_status": quality_status,
        "reject_reason": reject_reason,
    })
    store.responses[rec["id"]] = rec
    return ok_object(ser_response(rec), 201)


@bp.get("/sample-frames/<fid>/responses")
@require(*OPS_READ_ROLES)
def list_frame_responses(fid):
    frame = store.sample_frames.get(fid)
    if frame is None:
        fail("ERR_NOT_FOUND", "Sample frame not found")
    items = [r for r in store.responses.values() if r["frame_id"] == fid]
    q = request.args.get("quality_status")
    if q is not None:
        items = [r for r in items if r["quality_status"] == q]
    limit, offset = parse_limit_offset()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([ser_response(r) for r in page], total, limit, offset)
