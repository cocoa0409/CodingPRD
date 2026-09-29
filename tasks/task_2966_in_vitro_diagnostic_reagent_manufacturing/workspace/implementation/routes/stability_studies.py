"""The stability programme: chambers, timepoints and shelf life (PRD 3.6)."""

from flask import Blueprint

import calc
import lookup
import recompute
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import create_row, db, rows, touch
from validation import (ALL_ROLES, Body, STUDY_STATUSES, STUDY_TYPES,
                        authenticate_and_authorize, enum_filter, json_body,
                        pagination, paginate, str_filter)

bp = Blueprint("stability_studies", __name__)

CHAMBER_CAPACITY = 2
LIVE_STATUSES = ("PROTOCOL_DRAFT", "APPROVED", "IN_PROGRESS")


def _peak_occupancy(chamber_code, start, end):
    """Highest number of live studies sharing a single instant of [start, end).

    The occupation interval is half-open, so a study starting at exactly the
    instant another ends does not overlap it.
    """
    events = []
    for study in rows(db.stability_studies):
        if study["chamber_code"] != chamber_code:
            continue
        if study["status"] not in LIVE_STATUSES:
            continue
        clipped_start = max(study["protocol_start"], start)
        clipped_end = min(study["protocol_end"], end)
        if clipped_start >= clipped_end:
            continue
        events.append((clipped_start, 1))
        events.append((clipped_end, -1))
    # A closing event at the same instant is applied before an opening one.
    events.sort(key=lambda item: (item[0], item[1]))
    running = 0
    peak = 0
    for _instant, delta in events:
        running += delta
        peak = max(peak, running)
    return peak


@bp.post("/stability-studies")
def create_stability_study():
    authenticate_and_authorize(("RegulatoryAffairs",))
    body = Body(json_body())
    spec_id = body.req_str("product_specification_id")
    reagent_lot_id = body.req_str("reagent_lot_id")
    study_type = body.req_enum("study_type", STUDY_TYPES)
    chamber_code = body.req_str("chamber_code")
    storage_temp_c = body.req_number("storage_temp_c")
    protocol_start = body.req_ts("protocol_start")
    protocol_end = body.req_ts("protocol_end")
    if not protocol_end > protocol_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "protocol_end must be strictly later than protocol_start.")
    planned_timepoints = body.req_month_array("planned_timepoints_months")
    baseline_value = body.req_number("baseline_value", gt=0)

    # Rung 45 - body foreign keys, in entity field-declaration order.
    lookup.product_specification(spec_id)
    lookup.reagent_lot(reagent_lot_id)

    # Rung 102 - the chamber has aggregate capacity 2.
    if _peak_occupancy(chamber_code, protocol_start, protocol_end) >= CHAMBER_CAPACITY:
        raise ApiError("ERR_CHAMBER_CAPACITY_EXCEEDED")

    row = create_row(db.stability_studies, {
        "product_specification_id": spec_id,
        "reagent_lot_id": reagent_lot_id,
        "study_type": study_type,
        "chamber_code": chamber_code,
        "storage_temp_c": storage_temp_c,
        "protocol_start": protocol_start,
        "protocol_end": protocol_end,
        "planned_timepoints_months": planned_timepoints,
        "baseline_value": baseline_value,
        "status": "PROTOCOL_DRAFT",
        "timepoint_count": 0,
        "last_conforming_month": None,
        "established_shelf_life_months": None,
        "shelf_life_method": None,
        "protocol_approved_by_user_id": None,
    })
    return created_response(serialize.stability_study(row))


@bp.get("/stability-studies/<study_id>")
def read_stability_study(study_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.stability_study(study_id)
    return object_response(serialize.stability_study(row))


@bp.get("/stability-studies")
def list_stability_studies():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    spec_id = str_filter("product_specification_id")
    reagent_lot_id = str_filter("reagent_lot_id")
    study_type = enum_filter("study_type", STUDY_TYPES)
    status = enum_filter("status", STUDY_STATUSES)
    chamber_code = str_filter("chamber_code")
    items = rows(db.stability_studies)
    if spec_id is not None:
        items = [r for r in items if r["product_specification_id"] == spec_id]
    if reagent_lot_id is not None:
        items = [r for r in items if r["reagent_lot_id"] == reagent_lot_id]
    if study_type is not None:
        items = [r for r in items if r["study_type"] == study_type]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if chamber_code is not None:
        items = [r for r in items if r["chamber_code"] == chamber_code]
    page = paginate(items, limit, offset)
    return list_response([serialize.stability_study(r) for r in page],
                         limit, offset, len(items))


@bp.post("/stability-studies/<study_id>/approve-protocol")
def approve_protocol(study_id):
    user_id, _role = authenticate_and_authorize(("QAReleaser",))
    json_body()
    study = lookup.stability_study(study_id)

    # Rung 60 - state precondition.
    if study["status"] != "PROTOCOL_DRAFT":
        raise ApiError("ERR_STABILITY_STUDY_STATE_INVALID",
                       "A study in %s cannot have its protocol approved."
                       % study["status"])

    study["status"] = "APPROVED"
    study["protocol_approved_by_user_id"] = user_id
    touch(study)
    return object_response(serialize.stability_study(study))


@bp.post("/stability-studies/<study_id>/conclude")
def conclude_study(study_id):
    authenticate_and_authorize(("RegulatoryAffairs",))
    json_body()
    study = lookup.stability_study(study_id)
    product = db.product_specifications[study["product_specification_id"]]

    # Rung 60 - state precondition.
    if study["status"] != "IN_PROGRESS":
        raise ApiError("ERR_STABILITY_STUDY_STATE_INVALID",
                       "A study in %s cannot be concluded." % study["status"])
    if study["last_conforming_month"] is None:
        raise ApiError("ERR_STABILITY_STUDY_STATE_INVALID",
                       "The study has no conforming timepoint prefix.")

    months, method = calc.established_shelf_life(study, product)
    study["status"] = "COMPLETE"
    study["established_shelf_life_months"] = months
    study["shelf_life_method"] = method
    touch(study)
    return object_response(serialize.stability_study(study))
