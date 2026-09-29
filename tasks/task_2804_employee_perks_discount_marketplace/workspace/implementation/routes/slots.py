"""Placement slots: reservation, five-step pricing, confirmation, release (PRD 3.6)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import response
import support
import validate
from errors import ApiError

bp = Blueprint("slots", __name__)

# PRD 3.6: the featured-concurrency ceiling counts only live occupants, while the
# per-partner separation rule reaches back over runs that have already finished.
CAPACITY_STATES = ("RESERVED", "CONFIRMED")
COOLDOWN_STATES = ("RESERVED", "CONFIRMED", "COMPLETED")


def _intersects(a_start, a_end, b_start, b_end):
    """Run intervals are CLOSED on both ends, so touching endpoints intersect."""
    return a_start <= b_end and b_start <= a_end


def _gap_days(a_start, a_end, b_start, b_end):
    if _intersects(a_start, a_end, b_start, b_end):
        return 0
    if b_start > a_end:
        return calc.floor_days(a_end, b_start)
    return calc.floor_days(b_end, a_start)


def _posture_guard(employer):
    posture = derive.program_posture(employer)
    if posture == "SETUP":
        raise ApiError("ERR_PROGRAM_NOT_LIVE", "The employer programme is not live.")
    if posture == "FROZEN":
        raise ApiError("ERR_PROGRAM_FROZEN", "The employer programme is frozen.")
    return posture


def _category_of(slot):
    offer = db.offers.get(slot["offer_id"])
    return offer["category"] if offer is not None else None


@bp.post("/perks/offers/<row_id>/placement-slots")
def reserve_slot(row_id):
    principal = auth.require(auth.MERCHANT)
    offer = support.fetch("offers", row_id)
    auth.check_merchant_scope(principal, offer["merchant_id"])
    body = validate.json_body()
    employer = support.resolve_fk(body, "employer_id", "employers")
    data = validate.fields(body, [
        {"name": "expected_offer_version", "type": "int", "required": True},
        {"name": "employer_id", "type": "str", "required": True},
        {"name": "placement_tier", "type": "enum", "required": True,
         "values": ["STANDARD", "FEATURED"]},
        {"name": "slot_window_start", "type": "datetime", "required": True},
        {"name": "slot_window_end", "type": "datetime", "required": True},
    ])
    start = data["slot_window_start"]
    end = data["slot_window_end"]
    validate.window(start, end)
    support.occ(offer, body, "expected_offer_version")
    if offer["status"] != "ACTIVE":
        raise ApiError("ERR_OFFER_INVALID_STATE",
                       "The offer is not in a state that permits placement.")
    merchant = db.merchants.get(offer["merchant_id"])
    if merchant is None or merchant["status"] in ("SUSPENDED", "TERMINATED"):
        raise ApiError("ERR_MERCHANT_SUSPENDED", "The partner may not place offers.")
    # A RESTRICTED posture does not block placement.
    _posture_guard(employer)
    category = offer["category"]
    if data["placement_tier"] == "FEATURED":
        occupants = 0
        for other in db.placement_slots.values():
            if other["employer_id"] != employer["id"]:
                continue
            if other["placement_tier"] != "FEATURED":
                continue
            if other["status"] not in CAPACITY_STATES:
                continue
            if _category_of(other) != category:
                continue
            if _intersects(other["slot_window_start"], other["slot_window_end"],
                           start, end):
                occupants += 1
        if occupants >= calc.MAX_CONCURRENT_FEATURED_PER_CATEGORY:
            raise ApiError("ERR_SLOT_CAPACITY_CONFLICT",
                           "Featured placement capacity is full for this storefront "
                           "and category over the requested run.")
    # The separation rule looks only at the EXISTING slot's tier, so a STANDARD
    # reservation is still refused inside a partner's featured quiet period.
    for other in db.placement_slots.values():
        if other["employer_id"] != employer["id"]:
            continue
        if other["merchant_id"] != offer["merchant_id"]:
            continue
        if other["placement_tier"] != "FEATURED":
            continue
        if other["status"] not in COOLDOWN_STATES:
            continue
        if _category_of(other) != category:
            continue
        gap = _gap_days(other["slot_window_start"], other["slot_window_end"], start, end)
        if gap < calc.MERCHANT_SLOT_COOLDOWN_DAYS:
            raise ApiError("ERR_SLOT_COOLDOWN_CONFLICT",
                           "The partner's placement cooldown of %d days is not "
                           "satisfied." % calc.MERCHANT_SLOT_COOLDOWN_DAYS)
    agreement = db.agreements.get(offer["agreement_id"])
    base_rate = 0
    if agreement is not None and agreement.get("placement_fee_base_cents") is not None:
        base_rate = agreement["placement_fee_base_cents"]
    pricing = calc.price_slot(base_rate, start, end,
                              derive.eligible_headcount(employer["id"]))
    fields = {
        "offer_id": offer["id"],
        "merchant_id": offer["merchant_id"],
        "employer_id": employer["id"],
        "placement_tier": data["placement_tier"],
        "slot_window_start": start,
        "slot_window_end": end,
        "status": "RESERVED",
        "confirmed_at": None,
        "released_at": None,
        "release_reason": None,
    }
    fields.update(pricing)
    row = db.insert(db.placement_slots, fields)
    # PRD 2.7: an earlier slot reservation invalidates a caller's read of the offer.
    db.touch(offer)
    return response.created(derive.slot_json(row))


@bp.get("/perks/placement-slots/<row_id>")
def get_slot(row_id):
    principal = auth.require(auth.MERCHANT, auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN,
                             auth.EMPLOYER_ADMIN)
    row = support.fetch("placement_slots", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    auth.check_employer_scope(principal, row["employer_id"])
    return response.ok(derive.slot_json(row))


@bp.get("/perks/placement-slots")
def list_slots():
    principal = auth.require(auth.MERCHANT, auth.PARTNER_MANAGER, auth.PLATFORM_ADMIN,
                             auth.EMPLOYER_ADMIN)
    offer_id = support.arg("offer_id")
    employer_id = support.arg("employer_id")
    status = support.arg("status")
    tier = support.arg("placement_tier")
    rows = []
    for row in db.placement_slots.values():
        if principal.is_merchant and row["merchant_id"] != principal.user_id:
            continue
        if principal.is_employer_admin and row["employer_id"] != principal.user_id:
            continue
        if not support.matches(row, "offer_id", offer_id):
            continue
        if not support.matches(row, "employer_id", employer_id):
            continue
        if not support.matches(row, "status", status):
            continue
        if not support.matches(row, "placement_tier", tier):
            continue
        rows.append(row)
    return support.paged_sorted(rows, derive.slot_json)


@bp.post("/perks/placement-slots/<row_id>/confirm")
def confirm_slot(row_id):
    # Reservation and billing are split across the two peer roles precisely so
    # that a partner cannot bill itself: confirmation is the manager's act.
    auth.require(auth.PARTNER_MANAGER)
    row = support.fetch("placement_slots", row_id)
    if row["status"] != "RESERVED":
        raise ApiError("ERR_SLOT_INVALID_STATE", "Only a RESERVED slot can be confirmed.")
    offer = db.offers.get(row["offer_id"])
    if offer is None or offer["status"] != "ACTIVE":
        raise ApiError("ERR_OFFER_INVALID_STATE", "The parent offer is not ACTIVE.")
    employer = db.employers.get(row["employer_id"])
    if employer is not None:
        _posture_guard(employer)
    row["status"] = "CONFIRMED"
    row["confirmed_at"] = clock.now()
    db.touch(row)
    cascade.write_ledger(
        "PLACEMENT_FEE",
        int(row["placement_fee_cents"]),
        row["merchant_id"],
        "Placement fee for confirmed slot %s" % row["id"],
        placement_slot_id=row["id"],
    )
    return response.ok(derive.slot_json(row))


@bp.post("/perks/placement-slots/<row_id>/release")
def release_slot_route(row_id):
    principal = auth.require(auth.MERCHANT, auth.PARTNER_MANAGER)
    row = support.fetch("placement_slots", row_id)
    auth.check_merchant_scope(principal, row["merchant_id"])
    body = validate.json_body()
    data = validate.fields(body, [
        {"name": "release_reason", "type": "str", "required": True},
    ])
    if row["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError("ERR_SLOT_INVALID_STATE",
                       "A RELEASED or COMPLETED slot cannot be released again.")
    cascade.release_slot(row, data["release_reason"])
    return response.ok(derive.slot_json(row))
