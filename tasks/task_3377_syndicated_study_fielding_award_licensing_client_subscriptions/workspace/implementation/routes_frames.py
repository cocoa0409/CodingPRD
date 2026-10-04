"""SampleFrame endpoints: create (OPEN), list, get, manual close."""
from flask import Blueprint

from db import store
from envelope import filter_params, ok_object, paginated
from errors import fail
from middleware import OPS_READ_ROLES, require
from records import new_record, ser_frame, touch
from validation import Body

bp = Blueprint("frames", __name__, url_prefix="/research")


@bp.post("/sample-frames")
@require("FieldOps")
def create_frame():
    b = Body()
    study_id = b.str_("study_id")
    brand_id = b.str_("brand_id")
    source_type = b.enum_("source_type", ("PANEL", "CUSTOMER_LIST"))
    target = b.int_("target_completes")
    # existence (priority 3)
    study = store.studies.get(study_id) if study_id is not None else None
    if study_id is not None and study is None:
        fail("ERR_NOT_FOUND", "study_id does not reference an existing study")
    brand = store.brands.get(brand_id) if brand_id is not None else None
    if brand_id is not None and brand is None:
        fail("ERR_NOT_FOUND", "brand_id does not reference an existing brand")
    # state (priority 5): frame create requires the study DESIGN_LOCKED
    if study is not None and study["status"] != "DESIGN_LOCKED":
        fail("ERR_INVALID_STATE", "Sample frames may be created only while the study is DESIGN_LOCKED")
    # domain (priority 8): one frame per (study, brand)
    if study_id is not None and brand_id is not None:
        if any(
            f["study_id"] == study_id and f["brand_id"] == brand_id
            for f in store.sample_frames.values()
        ):
            fail("ERR_DUPLICATE_FRAME", "A sample frame already exists for this (study_id, brand_id)")
    # syntactic (priority 11)
    b.finalize()
    if target < 1:
        fail("ERR_INVALID_REQUEST", "target_completes must be >= 1")
    rec = new_record()
    rec.update({
        "study_id": study_id,
        "brand_id": brand_id,
        "source_type": source_type,
        "target_completes": target,
        "status": "OPEN",
    })
    store.sample_frames[rec["id"]] = rec
    return ok_object(ser_frame(rec), 201)


@bp.get("/sample-frames")
@require(*OPS_READ_ROLES)
def list_frames():
    items = list(store.sample_frames.values())
    items = filter_params(items, ("study_id", "brand_id", "status"))
    return paginated(items, ser_frame)


@bp.get("/sample-frames/<fid>")
@require(*OPS_READ_ROLES)
def get_frame(fid):
    frame = store.sample_frames.get(fid)
    if frame is None:
        fail("ERR_NOT_FOUND", "Sample frame not found")
    return ok_object(ser_frame(frame))


@bp.post("/sample-frames/<fid>/state")
@require("FieldOps")
def frame_state(fid):
    frame = store.sample_frames.get(fid)
    if frame is None:
        fail("ERR_NOT_FOUND", "Sample frame not found")
    b = Body()
    to = b.str_("to_status")
    b.finalize()
    # Manual drive is OPEN -> CLOSED only; reopen is cascade-only.
    if to == "CLOSED" and frame["status"] == "OPEN":
        frame["status"] = "CLOSED"
        touch(frame)
    else:
        fail("ERR_INVALID_STATE", "Frame transition from %s to %r is not defined" % (frame["status"], to))
    return ok_object(ser_frame(frame), 200)
