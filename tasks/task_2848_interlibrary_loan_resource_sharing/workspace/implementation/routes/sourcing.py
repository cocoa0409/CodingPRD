"""Copyright clearance, rota rounds and supply offers (PRD 3.4, 3.5, 3.6)."""
from flask import Blueprint

from db import add_hours, base_row, db, now, touch
from errors import ApiError
from middleware import (ADMIN, ILL_STAFF, PARTNER_AGENT, auth, get_offer,
                        get_request, own_offer)
from response import ok_row
from routes.common import filter_eq, list_response
from routes.requests import new_clearance
from services import calc, derive
from validate import (body, opt_int, q_enum, q_str, req_enum, req_int, req_str)

bp = Blueprint("sourcing", __name__)

OFFER_STATUSES = ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED")
DECLINE_REASONS = ("NOT_HELD", "IN_USE", "POLICY", "COST")


@bp.route("/ill/requests/<request_id>/copyright-clearances", methods=["POST"])
def record_royalty_clearance(request_id):
    user_id, role = auth(ILL_STAFF)
    req = get_request(request_id)
    # rung 28: the intake user may not clear their own request
    if user_id == req.get("intake_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    data = body()
    royalty_cents = req_int(data, "royalty_cents", 0)
    # rung 40: a terminal request is dead to every operation demanding a live one
    if req["status"] in calc.REQUEST_TERMINAL:
        raise ApiError("ERR_REQUEST_INVALID_STATE")
    # rung 51: a royalty is only recordable against a request that is on copyright
    # hold and not already covered by an automatic clearance
    if req["status"] != "COPYRIGHT_HOLD":
        raise ApiError("ERR_COPYRIGHT_CLEARANCE_NOT_REQUIRED")
    for clearance in calc.active_clearances(req["id"]):
        if clearance["method"] in ("CONTU_FREE", "PRE_WINDOW_EXEMPT"):
            raise ApiError("ERR_COPYRIGHT_CLEARANCE_NOT_REQUIRED")
    # rung 52: the declared amount must equal the computed fee
    expected = calc.royalty_fee_cents(req.get("pages_requested"))
    if royalty_cents != expected:
        raise ApiError("ERR_ROYALTY_AMOUNT_MISMATCH")
    bib = db.bib_items.get(req["bib_item_id"]) or {}
    row = new_clearance(req, bib.get("issn"), "ROYALTY_PAID", 0, royalty_cents,
                        approved_by_user_id=user_id)
    req["royalty_cents"] = royalty_cents
    req["status"] = "SOURCING"
    calc.price_request(req)
    touch(req)
    derive.recompute_patron_for_request(req, ("pending_charge_cents",))
    return ok_row(row, 201)


@bp.route("/ill/requests/<request_id>/source", methods=["POST"])
def run_rota_round(request_id):
    user_id, role = auth(ILL_STAFF)
    req = get_request(request_id)
    # rung 40
    if req["status"] != "SOURCING":
        raise ApiError("ERR_REQUEST_INVALID_STATE")
    # rung 50: an article copy needs live copyright cover
    if req["copyright_required"] and not calc.active_clearances(req["id"]):
        raise ApiError("ERR_COPYRIGHT_LIMIT_REACHED")
    rota = db.rotas[req["rota_id"]]
    # rung 74
    if req["attempt_count"] >= rota["max_attempts"]:
        raise ApiError("ERR_ROTA_ATTEMPTS_EXHAUSTED")
    days_avail = calc.days_available(req["needed_by"], now())
    answered = set(o["partner_id"] for o in db.offers.values()
                   if o["request_id"] == req["id"]
                   and o["status"] in ("DECLINED", "EXPIRED", "ACCEPTED"))
    candidates = []
    for entry in db.rota_entries.values():
        if entry["rota_id"] != rota["id"]:
            continue
        if entry["status"] != "ACTIVE" or not entry["is_enabled"]:
            continue
        partner = db.partners.get(entry["partner_id"])
        if partner is None or partner["status"] != "ACTIVE":
            continue
        if req["service_type"] == "LOAN" and not partner["ships_physical"]:
            continue
        if req["service_type"] == "COPY" and not partner["supplies_electronic"]:
            continue
        if partner["id"] in answered:
            continue
        agreement = calc.applicable_agreement(partner["id"], now())
        effective_fee = calc.effective_fee_cents(entry["quoted_fee_cents"], agreement)
        if effective_fee > req["max_supply_fee_cents"]:
            continue
        tolerance = calc.tolerance_items(agreement)
        penalty = (calc.IMBALANCE_PENALTY_CENTS
                   if partner["net_borrow_imbalance_items"] > tolerance else 0)
        landed = calc.landed_cost(effective_fee, entry["quoted_turnaround_days"],
                                  days_avail, penalty)
        candidates.append({
            "entry": entry,
            "partner": partner,
            "effective_fee": effective_fee,
            "imbalance_penalty": penalty,
            "landed_cost": landed,
        })
    # rung 78: nothing at all is written when no lender qualifies
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_LENDER")
    if rota["selection_policy"] == "MANUAL_RANK":
        candidates.sort(key=lambda c: (c["entry"]["manual_rank"], c["landed_cost"],
                                       c["entry"]["created_at"], c["entry"]["_seq"]))
    else:
        candidates.sort(key=lambda c: (c["landed_cost"],
                                       c["entry"]["quoted_turnaround_days"],
                                       c["entry"]["manual_rank"],
                                       c["entry"]["created_at"], c["entry"]["_seq"]))
    winner = candidates[0]
    req["attempt_count"] += 1
    req["days_available_at_source"] = days_avail
    req["status"] = "OFFER_PENDING"
    touch(req)
    offered_at = now()
    row = base_row()
    row.update({
        "request_id": req["id"],
        "partner_id": winner["partner"]["id"],
        "attempt_seq": req["attempt_count"],
        "quoted_fee_cents": winner["entry"]["quoted_fee_cents"],
        "quoted_turnaround_days": winner["entry"]["quoted_turnaround_days"],
        "effective_fee_cents": winner["effective_fee"],
        "landed_cost_cents": winner["landed_cost"],
        "imbalance_penalty_cents": winner["imbalance_penalty"],
        "offered_at": offered_at,
        "respond_by": add_hours(offered_at, rota["offer_response_hours"]),
        "status": "OFFERED",
        "decline_reason": "NONE",
        "offered_by_user_id": user_id,
    })
    db.offers[row["id"]] = row
    return ok_row(row, 201)


@bp.route("/ill/supply-offers/<offer_id>/accept", methods=["POST"])
def accept_offer(offer_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF)
    offer = get_offer(offer_id)
    own_offer(offer, user_id, role)
    # rung 41
    if offer["status"] != "OFFERED":
        raise ApiError("ERR_OFFER_NOT_OPEN")
    req = db.requests[offer["request_id"]]
    partner = db.partners[offer["partner_id"]]
    # rung 76: the partner must still be able to supply
    if partner["status"] != "ACTIVE":
        raise ApiError("ERR_PARTNER_NOT_ELIGIBLE")
    if req["service_type"] == "LOAN" and not partner["ships_physical"]:
        raise ApiError("ERR_PARTNER_NOT_ELIGIBLE")
    if req["service_type"] == "COPY" and not partner["supplies_electronic"]:
        raise ApiError("ERR_PARTNER_NOT_ELIGIBLE")
    offer["status"] = "ACCEPTED"
    touch(offer)
    req["committed_partner_id"] = partner["id"]
    req["committed_fee_cents"] = offer["effective_fee_cents"]
    req["committed_loan_period_days"] = partner["loan_period_days"]
    req["status"] = "SUPPLY_COMMITTED"
    calc.price_request(req)
    touch(req)
    derive.recompute_partner(partner)
    derive.recompute_patron_for_request(req, ("pending_charge_cents",))
    return ok_row(offer)


@bp.route("/ill/supply-offers/<offer_id>/decline", methods=["POST"])
def decline_offer(offer_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF)
    offer = get_offer(offer_id)
    own_offer(offer, user_id, role)
    data = body()
    decline_reason = req_enum(data, "decline_reason", DECLINE_REASONS)
    # rung 41
    if offer["status"] != "OFFERED":
        raise ApiError("ERR_OFFER_NOT_OPEN")
    offer["status"] = "DECLINED"
    offer["decline_reason"] = decline_reason
    touch(offer)
    req = db.requests[offer["request_id"]]
    if req["status"] == "OFFER_PENDING":
        req["status"] = "SOURCING"
        touch(req)
    return ok_row(offer)


@bp.route("/ill/supply-offers/<offer_id>", methods=["GET"])
def get_one_offer(offer_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF, ADMIN)
    offer = get_offer(offer_id)
    own_offer(offer, user_id, role)
    return ok_row(offer)


@bp.route("/ill/supply-offers", methods=["GET"])
def list_offers():
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF, ADMIN)
    rows = list(db.offers.values())
    if role == PARTNER_AGENT:
        rows = [o for o in rows if o["partner_id"] == user_id]
    rows = filter_eq(rows, "request_id", q_str("request_id"))
    rows = filter_eq(rows, "partner_id", q_str("partner_id"))
    rows = filter_eq(rows, "status", q_enum("status", OFFER_STATUSES))
    return list_response(rows)


@bp.route("/ill/supply-offers/<offer_id>/shipments", methods=["POST"])
def ship_offer(offer_id):
    user_id, role = auth(PARTNER_AGENT, ILL_STAFF)
    offer = get_offer(offer_id)
    own_offer(offer, user_id, role)
    data = body()
    carrier = req_str(data, "carrier")
    tracking_code = req_str(data, "tracking_code")
    insured_value = opt_int(data, "insured_value_cents", 0, 0)
    # rung 41: the commitment behind the parcel must be the accepted offer
    if offer["status"] != "ACCEPTED":
        raise ApiError("ERR_OFFER_NOT_OPEN")
    req = db.requests[offer["request_id"]]
    if req["status"] != "SUPPLY_COMMITTED" or req["service_type"] != "LOAN":
        raise ApiError("ERR_REQUEST_INVALID_STATE")
    row = base_row()
    row.update({
        "request_id": req["id"],
        "direction": "INBOUND",
        "carrier": carrier,
        "tracking_code": tracking_code,
        "insured_value_cents": insured_value,
        "shipped_at": now(),
        "received_at": None,
        "confirmed_at": None,
        "status": "IN_TRANSIT",
    })
    db.shipments[row["id"]] = row
    req["status"] = "IN_TRANSIT"
    touch(req)
    return ok_row(row, 201)
