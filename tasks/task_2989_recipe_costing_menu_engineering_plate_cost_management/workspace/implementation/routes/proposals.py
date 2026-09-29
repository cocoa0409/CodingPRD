"""Price change proposals and the elasticity projection (PRD 3.7)."""
from flask import Blueprint

import serial
from calc import price_projection
from core import (
    COOLING_OFF_DAYS, DAY, MARGIN_FLOOR_CENTS, MAX_REVISION_ROUNDS, db,
    order_key, rhu, stamp_new, touch,
)
from envelope import created, listing, ok
from errors import fail
from guards import (
    ANY_ROLE, authenticate, find_menu_item, find_proposal, get_body,
    opt_instant, opt_int, pagination, paginate, query_enum, query_str, req_id,
    req_instant, req_int, req_str,
)

bp = Blueprint("proposals", __name__)

LIVE_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED")
EDITABLE_STATUSES = ("DRAFT", "REVISION_REQUESTED")
PROPOSAL_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED",
                     "EFFECTIVE", "REJECTED")


@bp.post("/culinary/price-change-proposals")
def create_proposal():
    authenticate(("RecipeDeveloper",))
    body = get_body()
    menu_item_id = req_id(body, "menu_item_id")
    proposed_price_cents = req_int(body, "proposed_price_cents", minimum=1)
    effective_from = req_instant(body, "effective_from")
    elasticity_bps = req_int(body, "elasticity_bps", minimum=0, maximum=50000)
    item = find_menu_item(menu_item_id)
    for existing in db.proposals.values():
        if existing["menu_item_id"] == item["id"] and existing["status"] in LIVE_STATUSES:
            fail("ERR_PROPOSAL_ALREADY_OPEN",
                 "The menu item already has a live price change proposal.")
    row = stamp_new({
        "menu_item_id": item["id"],
        "proposed_price_cents": proposed_price_cents,
        "effective_from": effective_from,
        "elasticity_bps": elasticity_bps,
        "status": "DRAFT",
        "revision_round": 0,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "last_revision_reason": None,
        "applied_at": None,
    })
    db.proposals[row["id"]] = row
    return created(serial.proposal(row))


@bp.get("/culinary/price-change-proposals/<proposal_id>")
def get_proposal(proposal_id):
    authenticate(ANY_ROLE)
    return ok(serial.proposal(find_proposal(proposal_id)))


@bp.get("/culinary/price-change-proposals")
def list_proposals():
    authenticate(ANY_ROLE)
    limit, offset = pagination()
    status = query_enum("status", PROPOSAL_STATUSES)
    menu_item_id = query_str("menu_item_id")
    rows = list(db.proposals.values())
    if menu_item_id is not None:
        rows = [p for p in rows if p["menu_item_id"] == menu_item_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows.sort(key=order_key)
    page, limit, offset, total = paginate(rows, limit, offset, serial.proposal)
    return listing(page, limit, offset, total)


@bp.patch("/culinary/price-change-proposals/<proposal_id>")
def edit_proposal(proposal_id):
    authenticate(("RecipeDeveloper",))
    body = get_body()
    proposed_price_cents = opt_int(body, "proposed_price_cents", minimum=1)
    effective_from = opt_instant(body, "effective_from")
    elasticity_bps = opt_int(body, "elasticity_bps", minimum=0, maximum=50000)
    proposal = find_proposal(proposal_id)
    if proposal["status"] not in EDITABLE_STATUSES:
        fail("ERR_PROPOSAL_INVALID_STATE",
             "Only a DRAFT or REVISION_REQUESTED proposal may be edited.")
    if proposed_price_cents is not None:
        proposal["proposed_price_cents"] = proposed_price_cents
    if effective_from is not None:
        proposal["effective_from"] = effective_from
    if elasticity_bps is not None:
        proposal["elasticity_bps"] = elasticity_bps
    touch(proposal)
    return ok(serial.proposal(proposal))


@bp.post("/culinary/price-change-proposals/<proposal_id>/submit")
def submit_proposal(proposal_id):
    user_id, _role = authenticate(("RecipeDeveloper",))
    proposal = find_proposal(proposal_id)
    item = db.menu_items.get(proposal["menu_item_id"])
    if item is None:
        fail("ERR_MENU_ITEM_NOT_FOUND", "The target menu item no longer exists.")
    # 20 -- the item must be on the menu.
    if item["status"] != "ACTIVE":
        fail("ERR_MENU_ITEM_INVALID_STATE",
             "Only an ACTIVE menu item can carry a submitted price proposal.")
    # 21 -- the proposal's own status.
    if proposal["status"] not in EDITABLE_STATUSES:
        fail("ERR_PROPOSAL_INVALID_STATE",
             "Only a DRAFT or REVISION_REQUESTED proposal may be submitted.")
    # 26 -- a projection needs a known plate cost.
    if item["plate_cost_state"] != "FRESH":
        fail("ERR_COST_STALE", "The menu item's plate cost is STALE.")
    # 42 -- the cooling-off interval since the last applied change.
    last_change = item["last_price_change_at"]
    if last_change is not None:
        if proposal["effective_from"] < last_change + COOLING_OFF_DAYS * DAY:
            fail("ERR_PRICE_CHANGE_COOLING_OFF",
                 "effective_from must be at least %d whole days after the last "
                 "applied price change." % COOLING_OFF_DAYS)

    projection = price_projection(item, proposal["proposed_price_cents"],
                                 proposal["elasticity_bps"])
    # 47 -- the relieved cap, never the un-relieved market cap.
    if proposal["proposed_price_cents"] > projection["effective_cap_price_cents"]:
        fail("ERR_MARKET_CAP_EXCEEDED",
             "The proposed price exceeds the effective cap price of %d cents."
             % projection["effective_cap_price_cents"])
    # 48 -- the margin floor.
    if proposal["proposed_price_cents"] - item["plate_cost_cents"] < MARGIN_FLOOR_CENTS:
        fail("ERR_MARGIN_FLOOR_BREACH",
             "The proposed price must stand at least %d cents above the plate cost."
             % MARGIN_FLOOR_CENTS)

    proposal.update(projection)
    proposal["status"] = "SUBMITTED"
    proposal["submitted_by_user_id"] = user_id
    touch(proposal)
    return ok(serial.proposal(proposal))


@bp.post("/culinary/price-change-proposals/<proposal_id>/request-revision")
def request_revision(proposal_id):
    authenticate(("CulinaryDirector",))
    body = get_body()
    reason = req_str(body, "last_revision_reason", min_len=None)
    proposal = find_proposal(proposal_id)
    if proposal["status"] != "SUBMITTED":
        fail("ERR_PROPOSAL_INVALID_STATE",
             "Only a SUBMITTED proposal can be sent back for revision.")
    proposal["last_revision_reason"] = reason
    if proposal["revision_round"] < MAX_REVISION_ROUNDS:
        proposal["status"] = "REVISION_REQUESTED"
        proposal["revision_round"] = proposal["revision_round"] + 1
    else:
        proposal["status"] = "REJECTED"
    touch(proposal)
    return ok(serial.proposal(proposal))


@bp.post("/culinary/price-change-proposals/<proposal_id>/approve")
def approve_proposal(proposal_id):
    user_id, _role = authenticate(("CulinaryDirector",))
    proposal = find_proposal(proposal_id)
    if proposal["status"] != "SUBMITTED":
        fail("ERR_PROPOSAL_INVALID_STATE", "Only a SUBMITTED proposal can be approved.")
    item = db.menu_items.get(proposal["menu_item_id"])
    if item is None:
        fail("ERR_MENU_ITEM_NOT_FOUND", "The target menu item no longer exists.")
    # 26 before 27: a stale plate cost voids the projection.
    if item["plate_cost_state"] != "FRESH":
        fail("ERR_COST_STALE", "The menu item's plate cost is STALE.")
    if user_id == proposal["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The approver must differ from the submitter.")
    proposal["status"] = "APPROVED"
    proposal["approved_by_user_id"] = user_id
    touch(proposal)
    return ok(serial.proposal(proposal))


@bp.post("/culinary/price-change-proposals/<proposal_id>/apply")
def apply_proposal(proposal_id):
    authenticate(("CostAnalyst",))
    proposal = find_proposal(proposal_id)
    if proposal["status"] != "APPROVED":
        fail("ERR_PROPOSAL_INVALID_STATE", "Only an APPROVED proposal can be applied.")
    now = db.now()
    if now < proposal["effective_from"]:
        fail("ERR_EFFECTIVE_DATE_NOT_REACHED",
             "The logical clock has not yet reached effective_from.")
    item = db.menu_items.get(proposal["menu_item_id"])
    if item is None:
        fail("ERR_MENU_ITEM_NOT_FOUND", "The target menu item no longer exists.")
    proposal["status"] = "EFFECTIVE"
    proposal["applied_at"] = now
    touch(proposal)

    item["current_price_cents"] = proposal["proposed_price_cents"]
    item["last_price_change_at"] = now
    item["food_cost_bps"] = rhu(item["plate_cost_cents"] * 10000,
                                item["current_price_cents"])
    item["contribution_margin_cents"] = (item["current_price_cents"]
                                        - item["plate_cost_cents"])
    item["margin_class"] = "UNCLASSIFIED"
    touch(item)
    return ok(serial.proposal(proposal))
