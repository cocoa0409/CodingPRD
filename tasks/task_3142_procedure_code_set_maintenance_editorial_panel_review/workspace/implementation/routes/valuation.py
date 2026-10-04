"""Relative-value work: the recommending committee's valuation track."""

from datetime import datetime, timezone

from flask import Blueprint, request

import auth
import parsers as P
import resolvers as R
import store
from clock import logical_now
from errors import (
    ERR_INVALID_STATE,
    ERR_UNSUPPORTED_RELEASE,
    ERR_VALUATION_NOT_FORWARDABLE,
    ApiError,
)
from response import object_response
from routes.common import guard, list_response, one
from services import valuation as VA
from services import votes as VT

bp = Blueprint("valuation", __name__)

REVIEWERS = (auth.COMMITTEE_REVIEWER,)
STAFF = (auth.EDITORIAL_STAFF,)
READERS = (auth.COMMITTEE_REVIEWER, auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR)

# The closed set of four permitted FAQ/data-set release kinds.
RELEASE_KINDS = ("FAQ", "DATA_SET", "FAQ_AND_DATA_SET", "REFERENCE_DATA")


def _valuation_effective_date():
    """January 1 of the release year following the valuation's cycle year."""
    return datetime(logical_now().year + 1, 1, 1, tzinfo=timezone.utc)


@bp.post("/ruc-value-recommendations")
@guard(REVIEWERS)
def open_valuation(actor):
    data = P.body()
    specialty_id = P.text_or_none(data.get("specialty_id"))
    if specialty_id is not None:
        R.fk(store.societies, specialty_id, "SpecialtySociety")
    code_value_id = P.text_or_none(data.get("code_value_id"))
    if code_value_id is not None:
        R.fk(store.code_values, code_value_id, "CodeValue")

    # The published date is January 1 of the release year following the cycle
    # year; when no code value yet ties the valuation to a cycle, the year
    # following the current logical year is used.
    effective_date = _valuation_effective_date()
    if code_value_id is not None:
        linked = store.code_values.get(code_value_id)
        if linked is not None and linked.get("effective_date") is not None:
            effective_date = linked["effective_date"]

    valuation = store.create(store.valuations, {
        "code": P.text(data.get("code")),
        "code_value_id": code_value_id,
        "work_rvu": P.number(data.get("work_rvu"), 0),
        "facility_pe_rvu": P.number(data.get("facility_pe_rvu"), 0),
        "nonfacility_pe_rvu": P.number(data.get("nonfacility_pe_rvu"), 0),
        "mp_rvu": P.number(data.get("mp_rvu"), 0),
        "survey_median_minutes": P.number(data.get("survey_median_minutes"), 0),
        "specialty_id": specialty_id,
        "conversion_factor_tier": P.text_or_none(data.get("conversion_factor_tier")),
        "status": "BEING_CONVENED",
        "recommendation_status": "PENDING",
        "recommended_work_rvu": None,
        "forward_status": "WITHHELD",
        "payability_status": "NOT_PAYABLE",
        "effective_date": effective_date,
        "vote_percent": None,
    })
    return object_response(one(valuation), 201)


@bp.get("/ruc-value-recommendations")
@guard(READERS)
def list_valuations(actor):
    rows = store.sorted_rows(store.valuations)
    for field in ("status", "forward_status", "specialty_id", "code", "code_value_id"):
        wanted = request.args.get(field)
        if wanted not in (None, ""):
            rows = [r for r in rows if r.get(field) == wanted]
    return list_response(rows)


@bp.get("/ruc-value-recommendations/<valuation_id>")
@guard(READERS)
def read_valuation(actor, valuation_id):
    return object_response(one(R.valuation(valuation_id)))


@bp.get("/specialty-societies/<society_id>/value-recommendations")
@guard(READERS)
def list_society_valuations(actor, society_id):
    society = R.society(society_id)
    rows = [v for v in store.sorted_rows(store.valuations)
            if v.get("specialty_id") == society["id"]]
    return list_response(rows)


@bp.post("/ruc-value-recommendations/<valuation_id>/votes")
@guard(REVIEWERS)
def convene_valuation(actor, valuation_id):
    valuation = R.valuation(valuation_id)
    data = P.body()
    if valuation.get("status") != "BEING_CONVENED":
        raise ApiError(ERR_INVALID_STATE, "the committee has already convened on this valuation")

    yes = P.integer(data.get("yes_votes"), 0)
    no = P.integer(data.get("no_votes"), 0)
    if yes + no <= 0:
        raise ApiError(ERR_INVALID_STATE, "the ballot total must be greater than zero")

    pct = VT.committee_recommendation_vote(yes, no)
    valuation["vote_percent"] = float(pct) if pct is not None else None
    valuation["recommendation_status"] = VT.committee_recommendation_status(pct)
    valuation["status"] = "CONVENED"
    valuation["forward_status"] = "WITHHELD"
    store.bump(valuation)
    return object_response(one(valuation), 200)


@bp.post("/ruc-value-recommendations/<valuation_id>/recommendations")
@guard(REVIEWERS)
def publish_recommendation(actor, valuation_id):
    valuation = R.valuation(valuation_id)
    if valuation.get("status") != "CONVENED":
        raise ApiError(ERR_INVALID_STATE, "the valuation is not convened")
    if valuation.get("recommendation_status") != "RECOMMENDED":
        raise ApiError(ERR_INVALID_STATE, "the committee did not reach a recommendation")
    if valuation.get("forward_status") != "WITHHELD":
        raise ApiError(ERR_INVALID_STATE, "the valuation is no longer withheld")
    effective = valuation.get("effective_date")
    if effective is not None and logical_now() >= effective:
        raise ApiError(ERR_INVALID_STATE, "the effective date has already passed")

    VA.recompute_recommended_work_rvu(valuation)
    # Cascade hop 1 + 2: upsert the code value and recompute its dollar split.
    value = VA.upsert_code_value_for(
        valuation.get("code"),
        {
            "work_rvu": P.number(valuation.get("work_rvu"), 0),
            "facility_pe_rvu": P.number(valuation.get("facility_pe_rvu"), 0),
            "nonfacility_pe_rvu": P.number(valuation.get("nonfacility_pe_rvu"), 0),
            "mp_rvu": P.number(valuation.get("mp_rvu"), 0),
        },
        release_id=None,
        specialty_id=valuation.get("specialty_id"),
        effective_date=valuation.get("effective_date"),
    )
    valuation["code_value_id"] = value["id"]
    valuation["narrative"] = P.text_or_none(P.body().get("narrative"))
    valuation["status"] = "RECOMMENDED"
    store.bump(valuation)
    return object_response(one(valuation), 200)


@bp.post("/ruc-value-recommendations/<valuation_id>/refusals")
@guard(REVIEWERS)
def record_refusal(actor, valuation_id):
    valuation = R.valuation(valuation_id)
    if valuation.get("status") != "BEING_CONVENED":
        raise ApiError(ERR_INVALID_STATE, "the valuation is not being convened")
    if valuation.get("forward_status") != "WITHHELD":
        raise ApiError(ERR_INVALID_STATE, "the valuation is no longer withheld")

    valuation["recommendation_status"] = "DEEMED_NOT_RECOMMENDED"
    # The refusal recomputes the published work RVU and creates or mutates no
    # code value at all.
    VA.recompute_recommended_work_rvu(valuation)
    valuation["narrative"] = P.text_or_none(P.body().get("narrative"))
    store.bump(valuation)
    return object_response(one(valuation), 200)


@bp.post("/ruc-value-recommendations/<valuation_id>/forwards")
@guard(STAFF)
def forward_valuation(actor, valuation_id):
    valuation = R.valuation(valuation_id)
    status = valuation.get("status")
    recommendation_status = valuation.get("recommendation_status")
    effective = valuation.get("effective_date")

    if status == "RECOMMENDED":
        if valuation.get("forward_status") != "WITHHELD":
            raise ApiError(ERR_VALUATION_NOT_FORWARDABLE, "the valuation is no longer withheld")
        if effective is None or logical_now() >= effective:
            raise ApiError(ERR_VALUATION_NOT_FORWARDABLE,
                           "a valuation may only be forwarded before its effective date")
        if valuation.get("payability_status") != "NOT_PAYABLE":
            raise ApiError(ERR_VALUATION_NOT_FORWARDABLE, "payability is already locked")

        _set_code_value_status(valuation.get("code"), "ACTIVE")
        valuation["forward_status"] = "FORWARDED"
        valuation["status"] = "FORWARDED"
        valuation["payability_status"] = "PAYABLE_LOCKED"
    elif status == "CONVENED" and recommendation_status == "DEEMED_NOT_RECOMMENDED":
        if effective is None or logical_now() >= effective:
            raise ApiError(ERR_VALUATION_NOT_FORWARDABLE,
                           "a valuation may only be forwarded before its effective date")
        # The reference-committee median becomes a payable figure: upsert the
        # code value with it as the work component.
        VA.upsert_code_value_for(
            valuation.get("code"),
            {"work_rvu": P.number(valuation.get("recommended_work_rvu"), 0)},
            specialty_id=valuation.get("specialty_id"),
            value_status="ACTIVE",
            effective_date=valuation.get("effective_date"),
        )
        valuation["forward_status"] = "FORWARDED"
        valuation["status"] = "FORWARDED"
    else:
        raise ApiError(ERR_VALUATION_NOT_FORWARDABLE,
                       "the valuation is not in a forwardable state")

    store.bump(valuation)
    return object_response(one(valuation), 200)


@bp.post("/ruc-value-recommendations/<valuation_id>/releases")
@guard(STAFF)
def release_held_valuation(actor, valuation_id):
    valuation = R.valuation(valuation_id)
    data = P.body()
    kind = data.get("release_kind")
    if kind not in RELEASE_KINDS:
        raise ApiError(ERR_UNSUPPORTED_RELEASE,
                       "release_kind must be one of the four permitted kinds")

    valuation["forward_status"] = "RETAINED_FOR_RECONSIDERATION"
    valuation["release_kind"] = kind
    # Payability is deliberately left undisturbed by a release.
    store.bump(valuation)
    return object_response(one(valuation), 200)


@bp.post("/ruc-value-recommendations/<valuation_id>/reconsiderations")
@guard(STAFF)
def recall_valuation(actor, valuation_id):
    valuation = R.valuation(valuation_id)
    effective = valuation.get("effective_date")

    if valuation.get("payability_status") != "PAYABLE_LOCKED":
        raise ApiError(ERR_INVALID_STATE, "the valuation is not payable-locked")
    if effective is None or logical_now() >= effective:
        raise ApiError(ERR_INVALID_STATE, "the effective date has passed")

    _set_code_value_status(valuation.get("code"), "RETAINED")
    valuation["status"] = "BEING_CONVENED"
    valuation["forward_status"] = "RETAINED_FOR_RECONSIDERATION"
    valuation["payability_status"] = "NOT_PAYABLE"
    valuation["reconsideration_reason"] = P.text_or_none(P.body().get("reason"))
    store.bump(valuation)
    return object_response(one(valuation), 200)


def _set_code_value_status(code, new_status):
    for value in store.code_values.values():
        if value.get("code") == code:
            value["value_status"] = new_status
            store.bump(value)