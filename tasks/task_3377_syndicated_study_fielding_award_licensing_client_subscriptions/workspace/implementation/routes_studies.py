"""Study endpoints: create/list/get and the study state machine."""
from flask import Blueprint

from db import clock, store
from envelope import filter_params, ok_object, paginated
from errors import fail
from middleware import ALL_ROLES, require
from records import new_record, ser_study, touch
from services import (
    close_fielding,
    frames_of,
    reopen_fielding,
)
from validation import Body

bp = Blueprint("studies", __name__, url_prefix="/research")


@bp.post("/studies")
@require("StudyAdmin")
def create_study():
    b = Body()
    code = b.str_("code")
    name = b.str_("name")
    industry = b.str_("industry_code")
    year = b.int_("cycle_year")
    min_sample = b.int_("min_sample_per_brand")
    alpha = b.num_("significance_alpha")
    embargo = b.dt_("embargo_lift_at")
    prior_id = b.str_("prior_study_id", required=False)
    # existence (priority 3)
    if prior_id is not None and prior_id not in store.studies:
        fail("ERR_NOT_FOUND", "prior_study_id does not reference an existing study")
    # domain (priority 8): unique code
    if code is not None and any(s["code"] == code for s in store.studies.values()):
        fail("ERR_DUPLICATE_STUDY_CODE", "Study code already exists")
    # syntactic (priority 11, last resort)
    b.finalize()
    if min_sample < 1:
        fail("ERR_INVALID_REQUEST", "min_sample_per_brand must be >= 1")
    rec = new_record()
    rec.update({
        "code": code,
        "name": name,
        "industry_code": industry,
        "cycle_year": year,
        "prior_study_id": prior_id,
        "min_sample_per_brand": min_sample,
        "significance_alpha": alpha,
        "embargo_lift_at": embargo,
        "status": "DRAFT",
        "active_methodology_id": None,
        "published_at": None,
    })
    store.studies[rec["id"]] = rec
    return ok_object(ser_study(rec), 201)


@bp.get("/studies")
@require(*ALL_ROLES)
def list_studies():
    items = list(store.studies.values())
    items = filter_params(items, ("industry_code", "status", "prior_study_id", "active_methodology_id"))
    return paginated(items, ser_study)


@bp.get("/studies/<sid>")
@require(*ALL_ROLES)
def get_study(sid):
    study = store.studies.get(sid)
    if study is None:
        fail("ERR_NOT_FOUND", "Study not found")
    return ok_object(ser_study(study))


@bp.post("/studies/<sid>/state")
@require("StudyAdmin")
def study_state(sid):
    study = store.studies.get(sid)
    if study is None:
        fail("ERR_NOT_FOUND", "Study not found")
    b = Body()
    to = b.str_("to_status")
    b.finalize()
    cur = study["status"]
    if to == "FIELDING":
        if cur == "DESIGN_LOCKED":
            if not frames_of(sid):
                fail("ERR_NO_FRAMES", "Opening fielding requires at least one sample frame")
            study["status"] = "FIELDING"
        elif cur in ("FIELDING_CLOSED", "SCORING", "SCORED"):
            reopen_fielding(study, from_scored=(cur == "SCORED"))
        else:
            fail("ERR_INVALID_STATE", "Cannot transition study from %s to FIELDING" % cur)
    elif to == "FIELDING_CLOSED":
        if cur != "FIELDING":
            fail("ERR_INVALID_STATE", "Cannot transition study from %s to FIELDING_CLOSED" % cur)
        close_fielding(study)
        study["status"] = "FIELDING_CLOSED"
    elif to == "SCORING":
        if cur != "FIELDING_CLOSED":
            fail("ERR_INVALID_STATE", "Cannot transition study from %s to SCORING" % cur)
        study["status"] = "SCORING"
    elif to == "CANCELLED":
        if cur not in ("DRAFT", "DESIGN_LOCKED", "FIELDING"):
            fail("ERR_INVALID_STATE", "Cannot transition study from %s to CANCELLED" % cur)
        if cur == "FIELDING":
            for f in frames_of(sid):
                if f["status"] == "OPEN":
                    f["status"] = "CLOSED"
                    touch(f)
        study["status"] = "CANCELLED"
    elif to == "PUBLISHED":
        if cur != "AWARDS_SET":
            fail("ERR_INVALID_STATE", "Cannot transition study from %s to PUBLISHED" % cur)
        if clock.now() < study["embargo_lift_at"]:
            fail("ERR_EMBARGO_ACTIVE", "Embargo has not lifted yet")
        for a in store.awards.values():
            if a["study_id"] == sid and a["status"] == "EMBARGOED":
                a["status"] = "PUBLISHED"
                a["published_at"] = clock.now()
                touch(a)
        study["status"] = "PUBLISHED"
        study["published_at"] = clock.now()
    else:
        # Includes DESIGN_LOCKED, which is reachable only via the pin cascade.
        fail("ERR_INVALID_STATE", "Transition to status %r is not defined" % to)
    touch(study)
    return ok_object(ser_study(study), 200)
