"""Rangeland health assessments (PRD 3.7)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import envelope
from errors import ApiError
import find
import store
from validate import bad, field, json_body, parse_body

bp = Blueprint("monitoring", __name__)

ASSESSMENT_FIELDS = [
    field("allotment_id", "str"),
    field("assessment_year", "int", min=2020, max=2060),
    field("monitoring_method", "enum", values=K.MONITORING_METHOD),
    field("upland_score", "int", min=0, max=100),
    field("riparian_score", "int", min=0, max=100),
    field("water_quality_score", "int", min=0, max=100),
    field("observed_utilization_pct", "int", min=1, max=100, required=False,
          nullable=True, default=None),
    field("standards_not_met", "enum_array", values=K.STANDARDS, required=False,
          nullable=True, default=None),
    field("causal_factor_is_livestock", "bool", required=False, nullable=True,
          default=False),
]

REVIEW_FIELDS = [
    field("review_outcome", "enum", values=["CONCUR", "REMAND"]),
    field("review_notes", "str", required=False, nullable=True, default=None),
]


def assessment_state(message):
    raise ApiError("ERR_ASSESSMENT_STATE_INVALID", message)


def duplicate(message):
    raise ApiError("ERR_DUPLICATE_ASSESSMENT_FOR_YEAR", message)


def siblings(allotment_id, assessment_year, exclude_id=None):
    out = []
    for row in store.rows("assessments"):
        if row["allotment_id"] != allotment_id:
            continue
        if row["assessment_year"] != assessment_year:
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        out.append(row)
    return out


@bp.post("/rangeland-health-assessments")
def create_assessment():
    body = parse_body(json_body(), ASSESSMENT_FIELDS)
    if body["monitoring_method"] == "UTILIZATION_MAPPING" \
            and body["observed_utilization_pct"] is None:
        bad("observed_utilization_pct is required for UTILIZATION_MAPPING")
    actor = auth.authenticate(["RangeSpecialist"])
    allotment = find.need("allotments", body["allotment_id"])
    for row in siblings(allotment["id"], body["assessment_year"]):
        if row["assessment_status"] == "FINALIZED":
            duplicate("this allotment already has a finalized assessment for "
                      "that year")
        if row["assessment_status"] in ("DRAFT", "FIELD_REVIEW"):
            duplicate("an assessment for that year is already open")
    record = store.insert("assessments", {
        "allotment_id": allotment["id"],
        "assessment_year": body["assessment_year"],
        "monitoring_method": body["monitoring_method"],
        "upland_score": body["upland_score"],
        "riparian_score": body["riparian_score"],
        "water_quality_score": body["water_quality_score"],
        "observed_utilization_pct": body["observed_utilization_pct"],
        "standards_not_met": body["standards_not_met"] or [],
        "causal_factor_is_livestock": bool(body["causal_factor_is_livestock"]),
        "composite_score": None,
        "determination": None,
        "recommended_reduction_pct": Decimal("0.0000"),
        "assessment_status": "DRAFT",
        "author_user_id": actor.user_id,
        "review_notes": None,
        "remand_count": 0,
    })
    return envelope.created(derive.assessment_json(record))


@bp.get("/rangeland-health-assessments")
def list_assessments():
    envelope.page_params()
    auth.any_operational()
    records = find.apply_filters(
        envelope.sort_default(store.rows("assessments")), [
            ("allotment_id", "allotment_id", "str"),
            ("assessment_year", "assessment_year", "int"),
            ("monitoring_method", "monitoring_method", "str"),
            ("assessment_status", "assessment_status", "str"),
            ("determination", "determination", "str"),
        ])
    return envelope.paginate(records, derive.assessment_json)


@bp.get("/rangeland-health-assessments/<assessment_id>")
def get_assessment(assessment_id):
    auth.any_operational()
    record = find.need("assessments", assessment_id)
    return envelope.ok(derive.assessment_json(record))


@bp.post("/rangeland-health-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    actor = auth.authenticate(["RangeSpecialist"])
    record = find.need("assessments", assessment_id)
    auth.require_identity(actor, record["author_user_id"],
                          "only the authoring specialist may submit this assessment")
    if record["assessment_status"] != "DRAFT":
        assessment_state("only a DRAFT assessment may be submitted")
    if record["monitoring_method"] == "UTILIZATION_MAPPING" \
            and record["observed_utilization_pct"] is None:
        assessment_state("observed_utilization_pct must be recorded before review")
    record["assessment_status"] = "FIELD_REVIEW"
    store.touch(record)
    return envelope.ok(derive.assessment_json(record))


@bp.post("/rangeland-health-assessments/<assessment_id>/review")
def review_assessment(assessment_id):
    body = parse_body(json_body(), REVIEW_FIELDS)
    actor = auth.authenticate(["AuthorizedOfficer"])
    record = find.need("assessments", assessment_id)
    auth.require_segregation(actor, record["author_user_id"],
                             "the reviewing officer may not be the author")
    if record["assessment_status"] != "FIELD_REVIEW":
        assessment_state("only an assessment in FIELD_REVIEW may be reviewed")
    if body["review_outcome"] == "CONCUR":
        for row in siblings(record["allotment_id"], record["assessment_year"],
                            record["id"]):
            if row["assessment_status"] == "FINALIZED":
                duplicate("a finalized assessment already exists for that year")
    elif record["remand_count"] >= K.MAX_ASSESSMENT_REMANDS:
        raise ApiError("ERR_ASSESSMENT_REMAND_LIMIT_EXCEEDED",
                       "this assessment has already been remanded twice")
    if body["review_notes"] is not None:
        record["review_notes"] = body["review_notes"]
    if body["review_outcome"] == "REMAND":
        record["remand_count"] += 1
        record["assessment_status"] = "DRAFT"
        store.touch(record)
        return envelope.ok(derive.assessment_json(record))
    score = calc.composite_score(record["upland_score"], record["riparian_score"],
                                 record["water_quality_score"])
    determination = calc.determination_for(score)
    record["composite_score"] = score
    record["determination"] = determination
    record["recommended_reduction_pct"] = calc.recommended_reduction(
        record["monitoring_method"], record["standards_not_met"],
        record["causal_factor_is_livestock"], record["observed_utilization_pct"],
        determination)
    record["assessment_status"] = "FINALIZED"
    store.touch(record)
    allotment = store.get("allotments", record["allotment_id"])
    if allotment is not None:
        allotment["health_determination"] = determination
        store.touch(allotment)
    return envelope.ok(derive.assessment_json(record))
