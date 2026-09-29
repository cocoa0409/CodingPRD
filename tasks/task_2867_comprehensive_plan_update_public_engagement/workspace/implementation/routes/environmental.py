"""Environmental review, alternatives and the preferred selector (PRD 3.7)."""
from flask import Blueprint

import constants as K
import serial
import validation as V
from db import add_days, bump, clock_now, db, new_row, sort_rows
from errors import ApiError
from response import (authenticate, created, filter_param, ok, paginate,
                      pagination)
from services import calc, planservice, repo

bp = Blueprint("environmental", __name__)

_READERS = K.ALL_ROLES
_PERIOD = {"EIR": K.EIR_COMMENT_PERIOD_DAYS,
           "NEGATIVE_DECLARATION": K.ND_COMMENT_PERIOD_DAYS}


@bp.post("/planning/environmental-reviews")
def create_review():
    authenticate([K.ROLE_CONSULTANT])
    data = V.body()
    plan_id = V.get_str(data, "plan_update_id", 1, None)
    document_type = V.get_enum(data, "document_type", K.DOCUMENT_TYPES)
    title = V.get_str(data, "title", 1, 160)

    plan = repo.plan(plan_id)
    planservice.ensure_not_adopted(plan)
    row = new_row({
        "plan_update_id": plan["id"],
        "document_type": document_type,
        "title": title,
        "status": "DRAFT",
        "comment_period_days": None,
        "circulated_at": None,
        "comment_period_ends_at": None,
        "preferred_alternative_id": None,
        "alternative_count": 0,
        "certified_at": None,
    })
    db.environmental_reviews[row["id"]] = row
    return created(serial.review(row))


@bp.get("/planning/environmental-reviews/<row_id>")
def read_review(row_id):
    authenticate(_READERS)
    return ok(serial.review(repo.review(row_id)))


@bp.get("/planning/environmental-reviews")
def list_reviews():
    authenticate(_READERS)
    limit, offset = pagination()
    plan_id = filter_param("plan_update_id")
    status = filter_param("status")
    document_type = filter_param("document_type")
    preferred_id = filter_param("preferred_alternative_id")
    rows = sort_rows(list(db.environmental_reviews.values()))
    if plan_id is not None:
        rows = [r for r in rows if r["plan_update_id"] == plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if document_type is not None:
        rows = [r for r in rows if r["document_type"] == document_type]
    if preferred_id is not None:
        rows = [r for r in rows if r["preferred_alternative_id"] == preferred_id]
    return paginate(rows, limit, offset, serial.review)


@bp.post("/planning/environmental-reviews/<row_id>/circulate")
def circulate_review(row_id):
    authenticate([K.ROLE_CONSULTANT])
    row = repo.review(row_id)
    plan = db.plan_updates.get(row["plan_update_id"])
    if plan is not None:
        planservice.ensure_not_adopted(plan)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_REVIEW_NOT_DRAFT")

    days = _PERIOD[row["document_type"]]
    window_start = clock_now()
    window_end = add_days(window_start, days)
    # Rung 14 - the window overlap is tested before the alternatives are counted.
    for other in repo.reviews_of(row["plan_update_id"]):
        if other["id"] == row["id"]:
            continue
        if other["status"] not in ("CIRCULATED", "CERTIFIED"):
            continue
        if other["circulated_at"] is None or other["comment_period_ends_at"] is None:
            continue
        if window_start <= other["comment_period_ends_at"] and \
                window_end >= other["circulated_at"]:
            raise ApiError("ERR_REVIEW_WINDOW_OVERLAP")
    if int(row["alternative_count"]) < K.MIN_ALTERNATIVES:
        raise ApiError("ERR_INSUFFICIENT_ALTERNATIVES")

    row["status"] = "CIRCULATED"
    row["circulated_at"] = window_start
    row["comment_period_days"] = days
    row["comment_period_ends_at"] = window_end
    bump(row)
    return ok(serial.review(row))


@bp.post("/planning/environmental-reviews/<row_id>/select-preferred-alternative")
def select_preferred(row_id):
    authenticate([K.ROLE_CONSULTANT])
    row = repo.review(row_id)
    plan = db.plan_updates.get(row["plan_update_id"])
    if plan is not None:
        planservice.ensure_not_adopted(plan)
    if row["status"] != "CIRCULATED":
        raise ApiError("ERR_REVIEW_NOT_CIRCULATED")

    alternatives = repo.alternatives_of(row["id"])
    candidates = [a for a in alternatives if a["status"] == "EVALUATED"]
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_ALTERNATIVE")
    winner = calc.rank_alternatives(candidates)[0]
    for other in alternatives:
        if other["status"] == "PREFERRED" and other["id"] != winner["id"]:
            other["status"] = "SUPERSEDED"
            bump(other)
    winner["status"] = "PREFERRED"
    bump(winner)
    row["preferred_alternative_id"] = winner["id"]
    bump(row)
    return ok(serial.alternative(winner))


@bp.post("/planning/environmental-reviews/<row_id>/certify")
def certify_review(row_id):
    authenticate([K.ROLE_DIRECTOR])
    row = repo.review(row_id)
    plan = repo.plan(row["plan_update_id"])
    planservice.ensure_not_adopted(plan)
    if row["status"] != "CIRCULATED":
        raise ApiError("ERR_REVIEW_NOT_CIRCULATED")
    if clock_now() < row["comment_period_ends_at"]:
        raise ApiError("ERR_COMMENT_PERIOD_OPEN")
    if row["preferred_alternative_id"] is None:
        raise ApiError("ERR_PREFERRED_ALTERNATIVE_NOT_SELECTED")

    row["status"] = "CERTIFIED"
    row["certified_at"] = clock_now()
    bump(row)
    # A plan carries exactly one live environmental document.
    for other in repo.reviews_of(plan["id"]):
        if other["id"] == row["id"]:
            continue
        if other["status"] in ("DRAFT", "CIRCULATED", "CERTIFIED"):
            other["status"] = "SUPERSEDED"
            bump(other)
    bump(plan)
    return ok(serial.review(row))


# --- plan alternatives ------------------------------------------------------

@bp.post("/planning/plan-alternatives")
def create_alternative():
    authenticate([K.ROLE_CONSULTANT])
    data = V.body()
    review_id = V.get_str(data, "environmental_review_id", 1, None)
    label = V.get_str(data, "label", 1, 80)
    traffic = V.get_num(data, "traffic_vmt_index", 0, 100)
    ghg = V.get_num(data, "ghg_index", 0, 100)
    habitat = V.get_num(data, "habitat_index", 0, 100)
    water = V.get_num(data, "water_index", 0, 100)

    review = repo.review(review_id)
    plan = db.plan_updates.get(review["plan_update_id"])
    if plan is not None:
        planservice.ensure_not_adopted(plan)
    if review["status"] != "DRAFT":
        raise ApiError("ERR_REVIEW_NOT_DRAFT")

    raw, credit, net = calc.score_alternative(traffic, ghg, habitat, water)
    row = new_row({
        "environmental_review_id": review["id"],
        "label": label,
        "traffic_vmt_index": traffic,
        "ghg_index": ghg,
        "habitat_index": habitat,
        "water_index": water,
        "raw_impact_score": raw,
        "mitigation_credit": credit,
        "net_impact_score": net,
        "status": "EVALUATED",
    })
    db.plan_alternatives[row["id"]] = row
    review["alternative_count"] = int(review["alternative_count"]) + 1
    bump(review)
    return created(serial.alternative(row))


@bp.get("/planning/environmental-reviews/<row_id>/plan-alternatives")
def list_alternatives(row_id):
    authenticate(_READERS)
    review = repo.review(row_id)
    limit, offset = pagination()
    status = filter_param("status")
    rows = repo.alternatives_of(review["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, serial.alternative)
