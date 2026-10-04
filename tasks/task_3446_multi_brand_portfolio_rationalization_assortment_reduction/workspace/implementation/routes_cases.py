"""Rationalization cases: propose (scored at creation), decide, finalize."""

from flask import Blueprint, request

import clock
import storage
from calculations import (new_record, bump, compute_case_scores,
                          discontinue_item, sell_through_deadline_for)
from envelope import success, paginate, sorted_by_created
from errors import fail
from rbac import guard, synchronized, ALL_ROLES
from serializers import case_out
from validation import body_json, f_str, f_enum

bp = Blueprint("cases", __name__, url_prefix="/portfolio")

OPEN_CASE_STATES = ("SCORED", "EXECUTING")


def open_case_for(item_id):
    for c in storage.cases.values():
        if c["item_id"] == item_id and c["case_status"] in OPEN_CASE_STATES:
            return c
    return None


@bp.post("/rationalization-cases")
@synchronized
def create_case():
    user_id = guard(["PortfolioManager"])
    body = body_json(required=True)
    item_id = f_str(body, "item_id")
    # step 6: body FK resolves
    item = storage.items.get(item_id)
    if item is None:
        fail("ERR_NOT_FOUND", f"item {item_id} not found")
    # step 7: a DISCONTINUED item cannot be proposed
    if item["item_status"] == "DISCONTINUED":
        fail("ERR_INVALID_STATE", "case create requires item not DISCONTINUED")
    # step 11: at most one open case per item (CUT_PROPOSED / SELL_THROUGH
    # imply an open case and land here)
    if open_case_for(item_id) is not None:
        fail("ERR_CASE_ALREADY_OPEN",
             "item already has an open rationalization case")
    brand = storage.brands[item["brand_id"]]
    scores = compute_case_scores(item, brand)
    rec = new_record()
    rec.update({
        "item_id": item_id,
        "proposer_user_id": user_id,
        "volume_score": scores["volume_score"],
        "margin_score": scores["margin_score"],
        "shelf_resilience_score": scores["shelf_resilience_score"],
        "backlash_resilience_score": scores["backlash_resilience_score"],
        "composite_score": scores["composite_score"],
        "recommendation": scores["recommendation"],
        "case_status": "SCORED",
        "decider_user_id": None,
    })
    storage.cases[rec["id"]] = rec
    # side effect: item LISTED -> CUT_PROPOSED
    item["item_status"] = "CUT_PROPOSED"
    bump(item)
    return success(case_out(rec), status=201)


@bp.get("/rationalization-cases")
@synchronized
def list_cases():
    guard(ALL_ROLES)
    records = list(storage.cases.values())
    for param in ("item_id", "case_status"):
        value = request.args.get(param)
        if value is not None:
            records = [c for c in records if c[param] == value]
    page, meta = paginate(sorted_by_created(records))
    return success([case_out(c) for c in page], response_type="array",
                   pagination=meta)


@bp.get("/rationalization-cases/<cid>")
@synchronized
def get_case(cid):
    guard(ALL_ROLES)
    case = storage.cases.get(cid)
    if case is None:
        fail("ERR_NOT_FOUND", f"rationalization case {cid} not found")
    return success(case_out(case))


@bp.post("/rationalization-cases/<cid>/decide")
@synchronized
def decide_case(cid):
    user_id = guard(["PortfolioManager"])
    body = body_json(required=True)
    decision = f_enum(body, "decision", ("APPROVE", "REJECT"))
    # step 5: path id resolves
    case = storage.cases.get(cid)
    if case is None:
        fail("ERR_NOT_FOUND", f"rationalization case {cid} not found")
    # step 7: state guards
    if case["case_status"] != "SCORED":
        fail("ERR_INVALID_STATE", "decide requires case SCORED")
    item = storage.items[case["item_id"]]
    if decision == "APPROVE" and item["item_status"] != "CUT_PROPOSED":
        fail("ERR_INVALID_STATE", "APPROVE requires item still CUT_PROPOSED")
    # step 10: segregation of duties
    if user_id == case["proposer_user_id"]:
        fail("ERR_SELF_DECISION",
             "decider must differ from the case proposer")
    case["decider_user_id"] = user_id
    if decision == "APPROVE":
        case["case_status"] = "EXECUTING"
        item["item_status"] = "SELL_THROUGH"
        item["sell_through_deadline"] = sell_through_deadline_for(clock.now())
    else:
        case["case_status"] = "REJECTED"
        # compensating revert: item CUT_PROPOSED -> LISTED
        item["item_status"] = "LISTED"
    bump(case)
    bump(item)
    return success(case_out(case))


@bp.post("/rationalization-cases/<cid>/finalize")
@synchronized
def finalize_case(cid):
    guard(["PortfolioManager"])
    case = storage.cases.get(cid)
    if case is None:
        fail("ERR_NOT_FOUND", f"rationalization case {cid} not found")
    # step 7: case EXECUTING and item SELL_THROUGH
    if case["case_status"] != "EXECUTING":
        fail("ERR_INVALID_STATE", "finalize requires case EXECUTING")
    item = storage.items[case["item_id"]]
    if item["item_status"] != "SELL_THROUGH":
        fail("ERR_INVALID_STATE", "finalize requires item still SELL_THROUGH")
    # step 19: logical clock >= sell_through_deadline (boundary inclusive)
    if clock.now() < item["sell_through_deadline"]:
        fail("ERR_SELL_THROUGH_OPEN",
             "sell-through window has not elapsed yet")
    case["case_status"] = "EXECUTED"
    bump(case)
    # item -> DISCONTINUED with obsolescence charge and write-off
    discontinue_item(item)
    return success(case_out(case))
