"""FranchiseAgreement resource routes."""

from flask import Blueprint

import db
import middleware
import schemas
import services
import timeutil
from decimal import Decimal
from datetime import timedelta

from errors import fail
from response import ok
from routes.common import SHARED, list_records

bp = Blueprint("agreements", __name__)

AMENDABLE = ("split_pct", "waste_share_pct", "shrink_responsibility_pct",
             "rebate_pass_pct", "minimum_net_worth_cents")


def _percentage(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST")
    try:
        pct = Decimal(str(value))
    except Exception:
        fail("ERR_INVALID_REQUEST")
    if pct < 0 or pct > 1:
        fail("ERR_INVALID_REQUEST")
    return pct


@bp.post("/agreements")
@middleware.auth(("FranchisorAdmin",))
def create_agreement():
    payload = middleware.body(
        required=("franchisee_id", "store_id", "split_pct", "waste_share_pct",
                  "shrink_responsibility_pct", "rebate_pass_pct",
                  "minimum_net_worth_cents", "term_start", "term_end",
                  "renewal_window_days"),
    )
    franchisee = services.require_franchisee(payload["franchisee_id"])
    store = services.require_store(payload["store_id"])
    split_pct = _percentage(payload["split_pct"], "split_pct")
    waste_pct = _percentage(payload["waste_share_pct"], "waste_share_pct")
    shrink_pct = _percentage(payload["shrink_responsibility_pct"], "shrink_responsibility_pct")
    rebate_pct = _percentage(payload["rebate_pass_pct"], "rebate_pass_pct")
    minimum = middleware.non_negative_int(payload["minimum_net_worth_cents"], "minimum_net_worth_cents")
    term_start = timeutil.required_utc(payload["term_start"])
    term_end = timeutil.required_utc(payload["term_end"])
    window_days = middleware.non_negative_int(payload["renewal_window_days"], "renewal_window_days")
    if term_end <= term_start:
        fail("ERR_INVALID_REQUEST")

    record = db.insert("agreements", {
        "franchisee_id": franchisee["id"],
        "store_id": store["id"],
        "split_pct": split_pct,
        "royalty_pct": Decimal("0.0000"),
        "waste_share_pct": waste_pct,
        "shrink_responsibility_pct": shrink_pct,
        "rebate_pass_pct": rebate_pct,
        "minimum_net_worth_cents": minimum,
        "term_start": term_start,
        "term_end": term_end,
        "renewal_window_days": window_days,
        "performance_tier": "STANDARD",
        "renewal_eligibility_score": None,
        "status": "DRAFT",
    })
    return ok(schemas.dump("agreements", record), 201)


@bp.get("/agreements")
@middleware.auth(SHARED)
def list_agreements():
    return list_records("agreements", ("franchisee_id", "store_id", "status"))


@bp.get("/agreements/<agreement_id>")
@middleware.auth(SHARED)
def get_agreement(agreement_id):
    agreement = services.require("agreements", agreement_id)
    return ok(schemas.dump("agreements", agreement))


@bp.post("/agreements/<agreement_id>/activate")
@middleware.auth(("FranchisorAdmin",))
def activate_agreement(agreement_id):
    agreement = services.require("agreements", agreement_id)
    services.require_state(agreement, "DRAFT")
    store = services.require_store(agreement["store_id"])
    if store["status"] != "ACTIVE":
        fail("ERR_STORE_NOT_ACTIVE")
    franchisee = services.require_franchisee(agreement["franchisee_id"])
    if services.dec(franchisee["stated_net_worth_cents"]) < services.dec(agreement["minimum_net_worth_cents"]):
        fail("ERR_MIN_NET_WORTH_NOT_MET")

    agreement["status"] = "ACTIVE"
    agreement["performance_tier"] = "STANDARD"
    db.touch(agreement)
    store["agreement_id"] = agreement["id"]
    services.recalculate_franchisee(franchisee)
    return ok(schemas.dump("agreements", agreement))


@bp.post("/agreements/<agreement_id>/open-renewal")
@middleware.auth(("FranchisorAdmin",))
def open_renewal(agreement_id):
    agreement = services.require("agreements", agreement_id)
    services.require_state(agreement, "ACTIVE")
    window_start = agreement["term_end"] - timedelta(days=int(agreement["renewal_window_days"]))
    if db.clock() < window_start:
        fail("ERR_RENEWAL_WINDOW_NOT_OPEN")
    eligibility = services.renewal_eligibility(agreement)
    if eligibility["score"] < services.ELIGIBILITY_OPEN_MIN:
        fail("ERR_RENEWAL_ELIGIBILITY_FAILED")
    agreement["status"] = "RENEWAL_PENDING"
    agreement["renewal_eligibility_score"] = eligibility["score"]
    db.touch(agreement)
    return ok(schemas.dump("agreements", agreement))


@bp.post("/agreements/<agreement_id>/renew")
@middleware.auth(("FranchisorAdmin",))
def renew_agreement(agreement_id):
    agreement = services.require("agreements", agreement_id)
    services.require_state(agreement, "RENEWAL_PENDING")
    payload = middleware.body(required=("new_term_end",))
    new_term_end = timeutil.required_utc(payload["new_term_end"])

    franchisee = services.require_franchisee(agreement["franchisee_id"])
    eligibility = services.renewal_eligibility(agreement)
    required = max(services.dec(agreement["minimum_net_worth_cents"]), eligibility["required_band"])
    if services.dec(franchisee["audit_adjusted_net_worth_cents"]) < required:
        fail("ERR_RENEWAL_NET_WORTH_INSUFFICIENT")
    if db.find_one("settlements", store_id=agreement["store_id"], status="DISPUTED"):
        fail("ERR_OPEN_DISPUTE_BLOCKS_RENEWAL")

    agreement["status"] = "RENEWED"
    agreement["term_start"] = new_term_end - timedelta(days=365)
    agreement["term_end"] = new_term_end
    agreement["renewal_eligibility_score"] = eligibility["score"]
    db.touch(agreement)

    db.insert("agreements", {
        "franchisee_id": agreement["franchisee_id"],
        "store_id": agreement["store_id"],
        "split_pct": agreement["split_pct"],
        "royalty_pct": Decimal("0.0000"),
        "waste_share_pct": agreement["waste_share_pct"],
        "shrink_responsibility_pct": agreement["shrink_responsibility_pct"],
        "rebate_pass_pct": agreement["rebate_pass_pct"],
        "minimum_net_worth_cents": agreement["minimum_net_worth_cents"],
        "term_start": agreement["term_start"],
        "term_end": agreement["term_end"],
        "renewal_window_days": agreement["renewal_window_days"],
        "performance_tier": "STANDARD",
        "renewal_eligibility_score": None,
        "status": "DRAFT",
    })
    return ok(schemas.dump("agreements", agreement))


@bp.post("/agreements/<agreement_id>/amend")
@middleware.auth(("FranchisorAdmin",))
def amend_agreement(agreement_id):
    agreement = services.require("agreements", agreement_id)
    if agreement["status"] not in ("DRAFT", "ACTIVE"):
        fail("ERR_FORBIDDEN")
    payload = middleware.body(optional=AMENDABLE)
    changed = False
    for field in AMENDABLE:
        if field not in payload:
            continue
        if field == "minimum_net_worth_cents":
            agreement[field] = middleware.non_negative_int(payload[field], field)
        else:
            agreement[field] = _percentage(payload[field], field)
        changed = True
    if changed:
        db.touch(agreement)
    return ok(schemas.dump("agreements", agreement))