"""Artwork proofs: up to three rounds per order, Buyer submits, PrepressTech
reviews; approval computes the FINAL quote and confirms a held reservation."""
from flask import Blueprint, request

from auth import context, forbidden, require_roles
from calc import compute_quote_cents, peak_probe_final
from envelope import (
    get_body, new_entity, req_int, req_str, req_str_array, sort_created,
    success, success_list, touch,
)
from errors import fail
from serialize import ser_proof
from store import DB

bp = Blueprint("proofs", __name__)

MAX_PROOF_ROUNDS = 3


def load_proof(proof_id):
    p = DB.proofs.get(proof_id)
    if p is None:
        fail("ERR_PROOF_NOT_FOUND", "no artwork proof with id %s" % proof_id)
    return p


@bp.post("/drinkware/artwork-proofs")
def create_proof():
    uid, role = context()
    require_roles(role, ["Buyer"])
    body = get_body()
    order_id = req_str(body, "order_id")
    artwork_file_ref = req_str(body, "artwork_file_ref")
    color_count = req_int(body, "color_count", minimum=1, maximum=8)
    placement_count = req_int(body, "placement_count", minimum=1, maximum=4)
    pantone_codes = req_str_array(body, "pantone_codes")
    order = DB.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND", "no customization order with id %s" % order_id)
    if order["buyer_ref"] != uid:
        forbidden("Buyer role may submit proofs only on its own orders")
    if order["order_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "the order is CANCELLED")
    if order["proof_round"] >= MAX_PROOF_ROUNDS:
        fail("ERR_PROOF_ROUND_EXHAUSTED", "the order's three proof rounds are spent")
    if order["artwork_status"] not in ("NO_ART", "CHANGES_REQUESTED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "the artwork axis does not accept a new proof round")
    order["proof_round"] += 1
    for prior in DB.proofs.values():
        if prior["order_id"] == order_id and prior["status"] == "CHANGES_REQUESTED":
            prior["status"] = "SUPERSEDED"
            touch(prior)
    proof = new_entity({
        "order_id": order_id,
        "artwork_file_ref": artwork_file_ref,
        "color_count": color_count,
        "placement_count": placement_count,
        "pantone_codes": pantone_codes,
        "round_number": order["proof_round"],
        "status": "SUBMITTED",
        "review_notes": None,
        "submitted_by": uid,
    })
    DB.proofs[proof["id"]] = proof
    order["artwork_status"] = "PROOF_SUBMITTED"
    touch(order)
    return success(ser_proof(proof), 201)


@bp.get("/drinkware/artwork-proofs/<proof_id>")
def get_proof(proof_id):
    uid, role = context()
    require_roles(role, ["Buyer", "PrepressTech", "PlatformAdmin"])
    proof = load_proof(proof_id)
    if role == "Buyer":
        order = DB.orders.get(proof["order_id"])
        if order is None or order["buyer_ref"] != uid:
            forbidden("Buyer role may read only its own orders' proofs")
    return success(ser_proof(proof))


@bp.get("/drinkware/artwork-proofs")
def list_proofs():
    _, role = context()
    require_roles(role, ["PrepressTech", "PlatformAdmin"])
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    items = sort_created(list(DB.proofs.values()))
    if order_id is not None:
        items = [p for p in items if p["order_id"] == order_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return success_list([ser_proof(p) for p in items])


def _load_reviewable_proof(proof_id):
    """Shared preconditions for approve / request-changes: the proof must be
    the latest SUBMITTED round of an ACTIVE order."""
    proof = load_proof(proof_id)
    order = DB.orders.get(proof["order_id"])
    if order is None:
        fail("ERR_ORDER_NOT_FOUND", "no customization order with id %s" % proof["order_id"])
    if order["order_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "the order is CANCELLED")
    if proof["status"] != "SUBMITTED" or proof["round_number"] != order["proof_round"]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "only the latest SUBMITTED proof round is reviewable")
    return proof, order


@bp.post("/drinkware/artwork-proofs/<proof_id>/approve")
def approve_proof(proof_id):
    _, role = context()
    require_roles(role, ["PrepressTech"])
    get_body()
    proof, order = _load_reviewable_proof(proof_id)
    proof["status"] = "APPROVED"
    touch(proof)
    order["artwork_status"] = "ART_APPROVED"
    line = DB.product_lines.get(order["product_line_id"])
    peak = peak_probe_final(order)
    total = compute_quote_cents(
        line, order["buyer_type"], order["quantity"],
        proof["color_count"], proof["placement_count"], peak)
    order["final_quote_cents"] = total
    order["quote_variant"] = "FINAL"
    order["peak_applied"] = peak
    if order["reservation_status"] == "HELD":
        order["reservation_status"] = "CONFIRMED"
        order["schedule_status"] = "CONFIRMED"
    touch(order)
    return success(ser_proof(proof))


@bp.post("/drinkware/artwork-proofs/<proof_id>/request-changes")
def request_changes(proof_id):
    _, role = context()
    require_roles(role, ["PrepressTech"])
    body = get_body()
    review_notes = req_str(body, "review_notes")
    proof, order = _load_reviewable_proof(proof_id)
    proof["status"] = "CHANGES_REQUESTED"
    proof["review_notes"] = review_notes
    touch(proof)
    if order["proof_round"] >= MAX_PROOF_ROUNDS:
        order["artwork_status"] = "PROOF_EXHAUSTED"  # cycle closes
    else:
        order["artwork_status"] = "CHANGES_REQUESTED"
    touch(order)
    return success(ser_proof(proof))
