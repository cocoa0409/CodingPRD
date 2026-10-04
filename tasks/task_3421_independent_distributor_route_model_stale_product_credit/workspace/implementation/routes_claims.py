"""Stale return claim routes: file/list, decide, resubmit, issue-credit."""
from datetime import timedelta

from flask import Blueprint, request

import auth
import clock
import domain
import store
import validators as V
from constants import (
    ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR,
    DECISIONS, CLAIM_PULL_GRACE_DAYS, CLAIM_SUBMIT_WINDOW_DAYS,
    CLAIM_BLOCKED_AGREEMENT_STATUSES,
)
from errors import (
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_AGREEMENT_NOT_ACTIVE, ERR_CLAIM_NOT_REVIEWABLE, ERR_SKU_UNKNOWN,
    ERR_CLAIM_QTY_EXCEEDS, ERR_CLAIM_NOT_STALE_YET, ERR_CLAIM_WINDOW_EXPIRED,
    ERR_STALE_CAP_EXHAUSTED, raise_err,
)
from response import ok_object, ok_list, pagination_params, body

bp = Blueprint("claims", __name__)

ALL = (ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR)


def parse_items(raw_items):
    if not isinstance(raw_items, list) or not raw_items:
        raise_err(ERR_INVALID_REQUEST, "Field items must be a non-empty array")
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise_err(ERR_INVALID_REQUEST, "items entries must be objects")
        sku = V.get_str(raw, "sku")
        delivery_str, delivery_date = V.get_date(raw, "delivery_date")
        pulled_qty = V.get_int(raw, "pulled_qty", minimum=1)
        pull_str, pull_date = V.get_date(raw, "pull_date")
        items.append({
            "sku": sku,
            "delivery_date": delivery_str,
            "pulled_qty": pulled_qty,
            "pull_date": pull_str,
            "_delivery": delivery_date,
            "_pull": pull_date,
        })
    return items


def claim_gate_agreement(distributor_id):
    agreement = domain.resolve_agreement(distributor_id)
    if agreement is None or agreement["status"] in CLAIM_BLOCKED_AGREEMENT_STATUSES:
        raise_err(ERR_AGREEMENT_NOT_ACTIVE,
                  "Stale claims are blocked in the agreement's current state")
    return agreement


def validate_items(distributor_id, agreement, items):
    """Pipeline stages 9-10: referential integrity, then temporal windows."""
    catalog = domain.catalog_of(agreement)
    for item in items:
        sku = item["sku"]
        if sku not in catalog or domain.delivered_qty_any_date(distributor_id, sku) <= 0:
            raise_err(ERR_SKU_UNKNOWN,
                      f"sku {sku} is unknown or was never delivered to this distributor")
        eligible = (domain.delivered_qty_for(distributor_id, sku, item["delivery_date"])
                    - domain.credited_qty_for(distributor_id, sku, item["delivery_date"]))
        if item["pulled_qty"] > eligible:
            raise_err(ERR_CLAIM_QTY_EXCEEDS,
                      "pulled_qty exceeds delivered minus already-credited qty")
    today = clock.today()
    for item in items:
        shelf_life = catalog[item["sku"]]["shelf_life_days"]
        stale_from = item["_delivery"] + timedelta(days=shelf_life)
        if item["_pull"] < stale_from:
            raise_err(ERR_CLAIM_NOT_STALE_YET,
                      "pull_date is earlier than delivery_date + shelf_life_days")
        if item["_pull"] > stale_from + timedelta(days=CLAIM_PULL_GRACE_DAYS):
            raise_err(ERR_CLAIM_WINDOW_EXPIRED, "pull_date is past the claim window")
        if today > item["_pull"] + timedelta(days=CLAIM_SUBMIT_WINDOW_DAYS):
            raise_err(ERR_CLAIM_WINDOW_EXPIRED,
                      "claim submitted more than 2 days after pull_date")


@bp.route("/distributors/<rid>/stale-claims", methods=["POST"])
def create_claim(rid):
    user_id, role = auth.caller()
    auth.require_role(role, (ROLE_DISTRIBUTOR,))
    auth.require_path_distributor(user_id, role, rid)
    if store.get("distributors", rid) is None:
        raise_err(ERR_NOT_FOUND, "Distributor not found")
    data = body()
    if "items" not in data or data["items"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: items")
    items = parse_items(data["items"])
    agreement = claim_gate_agreement(rid)
    validate_items(rid, agreement, items)
    provisional = domain.claim_base_credit(items, agreement)
    for item in items:
        item.pop("_delivery", None)
        item.pop("_pull", None)
    claim = store.insert("stale_claims", {
        "distributor_id": rid,
        "items": items,
        "status": "SUBMITTED",
        "provisional_credit_cents": provisional,
        "approved_credit_cents": None,
        "issued_credit_cents": None,
        "cap_truncated_cents": None,
        "denial_reason": None,
        "_agreement_id": agreement["id"],
        "_submitted_date": clock.today(),
        "_created_date": clock.today(),
    })
    return ok_object(claim, 201)


@bp.route("/distributors/<rid>/stale-claims", methods=["GET"])
def list_claims(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ALL)
    auth.require_path_distributor(user_id, role, rid)
    if store.get("distributors", rid) is None:
        raise_err(ERR_NOT_FOUND, "Distributor not found")
    claims = domain.claims_of(rid)
    status = request.args.get("status")
    if status is not None:
        claims = [c for c in claims if c["status"] == status]
    page = pagination_params()
    total = len(claims)
    window = claims[page["offset"]:page["offset"] + page["limit"]]
    return ok_list(window, total, page)


@bp.route("/stale-claims/<rid>/decide", methods=["POST"])
def decide_claim(rid):
    user_id, role = auth.caller()
    auth.require_role(role, (ROLE_ROUTE_OPS,))
    claim = store.get("stale_claims", rid)
    if claim is None:
        raise_err(ERR_NOT_FOUND, "Stale claim not found")
    data = body()
    decision = V.get_enum(data, "decision", DECISIONS)
    if claim["status"] != "SUBMITTED":
        raise_err(ERR_CLAIM_NOT_REVIEWABLE,
                  "Only a SUBMITTED claim can be decided")
    if decision == "APPROVE":
        agreement = store.get("agreements", claim["_agreement_id"])
        claim["approved_credit_cents"] = domain.claim_base_credit(
            claim["items"], agreement)
        claim["status"] = "APPROVED"
    elif decision == "DENY":
        claim["status"] = "DENIED"
        claim["denial_reason"] = "DENIED_BY_REVIEW"
    else:
        claim["status"] = "NEEDS_INFO"
    store.touch(claim)
    return ok_object(claim)


@bp.route("/stale-claims/<rid>/resubmit", methods=["POST"])
def resubmit_claim(rid):
    user_id, role = auth.caller()
    auth.require_role(role, (ROLE_DISTRIBUTOR,))
    claim = store.get("stale_claims", rid)
    if claim is None:
        raise_err(ERR_NOT_FOUND, "Stale claim not found")
    auth.check_resource_owner(user_id, role, claim["distributor_id"])
    data = body()
    if "items" not in data or data["items"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: items")
    items = parse_items(data["items"])
    if claim["status"] != "NEEDS_INFO":
        raise_err(ERR_INVALID_STATE, "Only a NEEDS_INFO claim can be resubmitted")
    agreement = claim_gate_agreement(claim["distributor_id"])
    validate_items(claim["distributor_id"], agreement, items)
    claim["provisional_credit_cents"] = domain.claim_base_credit(items, agreement)
    for item in items:
        item.pop("_delivery", None)
        item.pop("_pull", None)
    claim["items"] = items
    claim["status"] = "SUBMITTED"
    claim["_submitted_date"] = clock.today()
    claim["_agreement_id"] = agreement["id"]
    store.touch(claim)
    return ok_object(claim)


@bp.route("/stale-claims/<rid>/issue-credit", methods=["POST"])
def issue_credit(rid):
    user_id, role = auth.caller()
    auth.require_role(role, (ROLE_CREDIT_ANALYST,))
    claim = store.get("stale_claims", rid)
    if claim is None:
        raise_err(ERR_NOT_FOUND, "Stale claim not found")
    if claim["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Only an APPROVED claim can be issued credit")
    week_t = domain.week_tuple_of(claim["_submitted_date"])
    cap, used = domain.weekly_stale_cap(claim["distributor_id"], week_t)
    remaining = cap - used
    if remaining <= 0:
        raise_err(ERR_STALE_CAP_EXHAUSTED,
                  "The weekly stale credit cap is exhausted for this claim's week")
    issued = min(claim["approved_credit_cents"], remaining)
    claim["issued_credit_cents"] = issued
    claim["cap_truncated_cents"] = claim["approved_credit_cents"] - issued
    claim["status"] = "CREDIT_ISSUED"
    store.touch(claim)
    distributor = store.get("distributors", claim["distributor_id"])
    distributor["trade_balance_cents"] -= issued
    store.touch(distributor)
    domain.recompute_standing(distributor)
    return ok_object(claim)
