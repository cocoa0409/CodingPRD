"""Promotions: authoring, two-person approval and channel loading (PRD 3.5)."""

from flask import Blueprint

import calc
import cascade
import guards
import refs
import serialize
import shape
import store
from envelope import created, ok
from errors import fail
from guards import must, page
from refs import get, put, rows, where

bp = Blueprint("promotion", __name__)

INTERNAL = shape.INTERNAL_ROLES
PROMO_KINDS = ("MEMBER_RATE", "PACKAGE_INCLUSION", "GEO_OFFER")
DISCOUNT_KINDS = ("PERCENT", "AMOUNT")
APPROVAL_STATES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
DISTRIBUTION_STATES = ("NOT_LOADED", "LOADING", "LOADED", "LOAD_FAILED")


@bp.post("/distribution/rate-plans/<rid>/promotions")
def create_promotion(rid):
    shape.auth("RevenueManager")
    plan = must("rate_plans", rid, "ERR_RATE_PLAN_NOT_FOUND")
    prop = refs.prop_of_plan(plan)
    body = shape.body_obj()
    code = shape.v_string(body, "code", required=True, minlen=2, maxlen=16,
                          pattern=r"^[A-Z0-9-]+$")
    promo_kind = shape.v_enum(body, "promo_kind", PROMO_KINDS, required=True)
    discount_kind = shape.v_enum(body, "discount_kind", DISCOUNT_KINDS, required=True)
    start_date = shape.v_date(body, "start_date", required=True)
    end_date = shape.v_date(body, "end_date", required=True)
    discount_bp = shape.v_int(body, "discount_bp", lo=1, hi=5000)
    discount_amount = shape.v_int(body, "discount_amount_cents", lo=1, hi=200000)
    markets = shape.v_str_array(body, "geo_market_codes", default=[], minlen=2,
                                maxlen=8, pattern=r"^[A-Z0-9-]+$")
    if end_date < start_date:
        fail("ERR_INVALID_REQUEST", "Field 'end_date' must not precede 'start_date'.")
    if discount_kind == "PERCENT":
        if discount_bp is None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'discount_bp' is required for a PERCENT promotion.")
        if discount_amount is not None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'discount_amount_cents' does not belong on a PERCENT promotion.")
    else:
        if discount_amount is None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'discount_amount_cents' is required for an AMOUNT promotion.")
        if discount_bp is not None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'discount_bp' does not belong on an AMOUNT promotion.")
    if promo_kind == "GEO_OFFER" and not markets:
        fail("ERR_INVALID_REQUEST",
             "A GEO_OFFER promotion must declare at least one geo market.")
    guards.require_horizon(prop, [start_date, end_date])
    for existing in where("promotions", rate_plan_id=plan["id"]):
        if existing["code"] == code:
            fail("ERR_DUPLICATE_RESOURCE",
                 "Promotion code %s already exists on this rate plan." % code)
    rec = store.base_record()
    rec.update({
        "rate_plan_id": plan["id"],
        "code": code,
        "promo_kind": promo_kind,
        "discount_kind": discount_kind,
        "discount_bp": discount_bp,
        "discount_amount_cents": discount_amount,
        "start_date": start_date,
        "end_date": end_date,
        "geo_market_codes": markets,
        "approval_status": "DRAFT",
        "distribution_status": "NOT_LOADED",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "reject_reason": None,
        "revision_count": 0,
    })
    put("promotions", rec)
    return created(serialize.promotion_out(rec))


@bp.post("/distribution/promotions/<pid>/submit")
def submit_promotion(pid):
    uid, role = shape.auth("RevenueManager", "RevenueDirector")
    promo = must("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    if promo["discount_kind"] == "PERCENT" and \
            promo["discount_bp"] > calc.PROMO_STACK_CAP_BP:
        fail("ERR_INVALID_REQUEST",
             "A PERCENT promotion may not exceed 3000 basis points.")
    if promo["approval_status"] != "DRAFT":
        fail("ERR_PROMOTION_STATE_INVALID")
    promo["approval_status"] = "SUBMITTED"
    promo["submitted_by_user_id"] = uid
    store.bump(promo)
    return ok(serialize.promotion_out(promo))


@bp.post("/distribution/promotions/<pid>/approve")
def approve_promotion(pid):
    uid, role = shape.auth("RevenueDirector")
    promo = must("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    if promo["approval_status"] != "SUBMITTED":
        fail("ERR_PROMOTION_STATE_INVALID")
    if uid == promo["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    promo["approval_status"] = "APPROVED"
    promo["approved_by_user_id"] = uid
    store.bump(promo)
    return ok(serialize.promotion_out(promo))


@bp.post("/distribution/promotions/<pid>/reject")
def reject_promotion(pid):
    uid, role = shape.auth("RevenueDirector")
    promo = must("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    body = shape.body_obj()
    reason = shape.v_string(body, "reason")
    if promo["approval_status"] != "SUBMITTED":
        fail("ERR_PROMOTION_STATE_INVALID")
    if uid == promo["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    promo["approval_status"] = "REJECTED"
    promo["reject_reason"] = reason
    store.bump(promo)
    return ok(serialize.promotion_out(promo))


@bp.post("/distribution/promotions/<pid>/revise")
def revise_promotion(pid):
    shape.auth("RevenueManager")
    promo = must("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    if promo["approval_status"] != "REJECTED":
        fail("ERR_PROMOTION_STATE_INVALID")
    promo["approval_status"] = "DRAFT"
    promo["submitted_by_user_id"] = None
    promo["reject_reason"] = None
    promo["revision_count"] += 1
    store.bump(promo)
    return ok(serialize.promotion_out(promo))


@bp.post("/distribution/promotions/<pid>/load")
def load_promotion(pid):
    shape.auth("ChannelOpsEngineer")
    promo = must("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    plan = get("rate_plans", promo["rate_plan_id"])
    if promo["distribution_status"] not in ("NOT_LOADED", "LOAD_FAILED"):
        fail("ERR_PROMOTION_STATE_INVALID")
    verified = refs.verified_mappings_of_plan(plan["id"])
    verdicts = {}
    for mapping in verified:
        verdicts[mapping["id"]] = calc.parity_verdict(mapping)
        channel = get("channels", mapping["channel_id"])
        if channel["requires_content_parity"] and verdicts[mapping["id"]] != "IN_PARITY":
            fail("ERR_CONTENT_PARITY_BLOCKED")
    if not verified:
        fail("ERR_CHANNEL_MAPPING_MISSING")
    for mapping in verified:
        connection = refs.connection_of_channel(mapping["channel_id"])
        if cascade.frozen(connection):
            fail("ERR_CONNECTION_FROZEN")
    for mapping in verified:
        if verdicts[mapping["id"]] != mapping["parity_state"]:
            mapping["parity_state"] = verdicts[mapping["id"]]
            store.bump(mapping)
    promo["distribution_status"] = "LOADING"
    cascade.promotion_batch(promo)
    store.bump(promo)
    return ok(serialize.promotion_out(promo))


@bp.get("/distribution/promotions")
def list_promotions():
    shape.auth(*INTERNAL)
    rate_plan_id = shape.q_id("rate_plan_id")
    approval = shape.q_enum("approval_status", APPROVAL_STATES)
    distribution = shape.q_enum("distribution_status", DISTRIBUTION_STATES)
    records = rows("promotions")
    if rate_plan_id is not None:
        records = [r for r in records if r["rate_plan_id"] == rate_plan_id]
    if approval is not None:
        records = [r for r in records if r["approval_status"] == approval]
    if distribution is not None:
        records = [r for r in records if r["distribution_status"] == distribution]
    return page(serialize.promotion_out, records)


@bp.get("/distribution/promotions/<pid>")
def read_promotion(pid):
    shape.auth(*INTERNAL)
    promo = must("promotions", pid, "ERR_PROMOTION_NOT_FOUND")
    return ok(serialize.promotion_out(promo))
