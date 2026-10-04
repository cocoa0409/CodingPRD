"""Claim studies: comparative-claim testing under segregation of duties; the
study lifecycle drives the variant's parallel claim_clearance dimension."""

from decimal import Decimal

from flask import Blueprint

from auth import require_roles
from constants import CONSTANTS
from errors import ApiError
from serializers import ser_study
from services import (get_or_404, posture_gate, req_fk, season_of_variant,
                      season_of_via_variant)
from state import DB, base_fields, bump, touch
from util import body, dec, ok_object, q4, req_int, req_number, req_string

bp = Blueprint("studies", __name__)

SCIENTIST = ("ClaimsScientist",)


def _set_clearance(study, clearance):
    variant = DB.variants.get(study["variant_id"])
    if variant is not None and variant["claim_clearance"] != clearance:
        variant["claim_clearance"] = clearance
        touch(variant)  # parallel-dimension flip; no ModelVariant version bump


@bp.post("/claim-studies")
def create_study():
    uid, _ = require_roles(SCIENTIST)
    data = body()
    variant = req_fk(data, "variant_id", DB.variants, "ERR_VARIANT_NOT_FOUND")
    claim_text = req_string(data, "claim_text")
    posture_gate(season_of_variant(variant))
    if variant["lifecycle"] != "TOOLED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "claim studies can only be opened on a TOOLED variant")
    s = base_fields()
    s.update({
        "variant_id": variant["id"],
        "claim_text": claim_text,
        "conducted_by_user_id": uid,
        "status": "RUNNING",
        "our_metric": None,
        "baseline_metric": None,
        "sample_size": None,
        "margin": None,
        "substantiated_by_user_id": None,
        "challenge_reason": None,
    })
    DB.studies[s["id"]] = s
    return ok_object(ser_study(s), 201)


@bp.post("/claim-studies/<sid>/complete")
def complete_study(sid):
    require_roles(SCIENTIST)
    s = get_or_404(DB.studies, sid, "ERR_STUDY_NOT_FOUND")
    posture_gate(season_of_via_variant(s))
    if s["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE", 409, "only a RUNNING study can be completed")
    data = body()
    our_metric = req_number(data, "our_metric")
    baseline_metric = req_number(data, "baseline_metric")
    sample_size = req_int(data, "sample_size")
    if sample_size < CONSTANTS["CLAIM_MIN_SAMPLES"]:
        raise ApiError("ERR_SAMPLE_SIZE_TOO_SMALL", 422,
                       "sample_size must be at least %d" % CONSTANTS["CLAIM_MIN_SAMPLES"])
    base = dec(baseline_metric)
    if base <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "baseline_metric must be > 0")
    s["our_metric"] = our_metric
    s["baseline_metric"] = baseline_metric
    s["sample_size"] = sample_size
    s["margin"] = q4((dec(our_metric) - base) / base)
    s["status"] = "RESULTS_RECORDED"
    bump(s)
    return ok_object(ser_study(s))


@bp.post("/claim-studies/<sid>/substantiate")
def substantiate_study(sid):
    uid, _ = require_roles(SCIENTIST)
    s = get_or_404(DB.studies, sid, "ERR_STUDY_NOT_FOUND")
    posture_gate(season_of_via_variant(s))
    if s["status"] != "RESULTS_RECORDED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a RESULTS_RECORDED study can be substantiated")
    if uid == s["conducted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "the substantiating scientist must differ from the conductor")
    if s["margin"] < Decimal(CONSTANTS["CLAIM_MIN_MARGIN"]):
        raise ApiError("ERR_MARGIN_BELOW_MINIMUM", 422,
                       "margin is below the substantiation threshold; the study stays RESULTS_RECORDED")
    s["substantiated_by_user_id"] = uid
    s["status"] = "SUBSTANTIATED"
    bump(s)
    _set_clearance(s, "SUBSTANTIATED")
    return ok_object(ser_study(s))


@bp.post("/claim-studies/<sid>/challenge")
def challenge_study(sid):
    require_roles(("LegalCounsel",))
    s = get_or_404(DB.studies, sid, "ERR_STUDY_NOT_FOUND")
    posture_gate(season_of_via_variant(s))
    if s["status"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a SUBSTANTIATED study can be challenged")
    reason = req_string(body(), "reason")
    s["challenge_reason"] = reason
    s["status"] = "CHALLENGED"
    bump(s)
    _set_clearance(s, "CHALLENGED")
    return ok_object(ser_study(s))


@bp.post("/claim-studies/<sid>/retest")
def retest_study(sid):
    require_roles(SCIENTIST)
    s = get_or_404(DB.studies, sid, "ERR_STUDY_NOT_FOUND")
    posture_gate(season_of_via_variant(s))
    if s["status"] != "CHALLENGED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a CHALLENGED study can be retested")
    s["our_metric"] = None
    s["baseline_metric"] = None
    s["sample_size"] = None
    s["margin"] = None
    s["challenge_reason"] = None
    s["status"] = "RUNNING"
    bump(s)
    _set_clearance(s, "UNSUBSTANTIATED")
    return ok_object(ser_study(s))
