"""Cascade integrity across the sponsorship graph (PRD 2.9, 3.8, 3.9)."""

from decimal import Decimal

import db
from db import store, touch, touch_if, set_fields
from util import dec, rhu, minutes_between
from services.calc import renewal_likelihood


# --------------------------------------------------------------------------
# booking derived fields
# --------------------------------------------------------------------------
def derive_proof_state(booking_id):
    """Strict precedence: DEFICIENT > VERIFIED > PENDING_REVIEW > NONE."""
    proofs = db.proofs_of_booking(booking_id)
    if any(p["status"] == "REJECTED" for p in proofs):
        return "DEFICIENT"
    if any(p["status"] == "VERIFIED" for p in proofs):
        return "VERIFIED"
    if any(p["status"] == "SUBMITTED" for p in proofs):
        return "PENDING_REVIEW"
    return "NONE"


def derive_verified_impressions(booking_id):
    return sum(p["measured_value"] for p in db.proofs_of_booking(booking_id)
               if p["status"] == "VERIFIED" and p["evidence_type"] in ("IMPRESSIONS", "SOCIAL"))


def refresh_booking_evidence(booking):
    """Recompute proof_state and verified_impressions; always a mutation of the
    booking row, because a proof event changed the inputs it summarises."""
    booking["proof_state"] = derive_proof_state(booking["id"])
    booking["verified_impressions"] = derive_verified_impressions(booking["id"])
    touch(booking)


# --------------------------------------------------------------------------
# delivery_rollup
# --------------------------------------------------------------------------
def rollup_entitlement(entitlement):
    delivered = 0
    for b in db.bookings_of_entitlement(entitlement["id"]):
        if b["status"] == "DELIVERED" and b["proof_state"] != "DEFICIENT":
            delivered += b["units_booked"]
    promised = entitlement["promised_units"]
    pct = rhu(Decimal("100") * dec(delivered) / dec(promised), 2) if promised else Decimal("0.00")
    if entitlement["status"] == "WAIVED":
        status = "WAIVED"
    elif delivered == 0:
        status = "PENDING"
    elif delivered < promised:
        status = "PARTIAL"
    else:
        status = "FULFILLED"
    entitlement["delivered_units"] = delivered
    entitlement["delivery_pct"] = pct
    entitlement["status"] = status
    touch(entitlement)


def rollup_contract(contract):
    """fulfillment_status only moves while the contract is COUNTERSIGNED or
    ACTIVE; delivered_media_value_cents is always recomputed."""
    ents = db.entitlements_of_contract(contract["id"])
    if contract["status"] in ("COUNTERSIGNED", "ACTIVE"):
        if not ents:
            fulfillment = "FULFILLED"
        elif all(e["status"] in ("FULFILLED", "WAIVED") for e in ents):
            fulfillment = "FULFILLED"
        elif all(e["status"] in ("PENDING", "WAIVED") for e in ents):
            fulfillment = "NOT_STARTED"
        else:
            fulfillment = "IN_PROGRESS"
        contract["fulfillment_status"] = fulfillment

    by_id = dict((e["id"], e) for e in ents)
    delivered_value = 0
    for b in db.bookings_of_contract(contract["id"]):
        if b["status"] == "DELIVERED" and b["proof_state"] != "DEFICIENT":
            ent = by_id.get(b["entitlement_id"])
            if ent is not None:
                delivered_value += b["units_booked"] * ent["unit_value_cents"]
    contract["delivered_media_value_cents"] = delivered_value
    touch(contract)


# --------------------------------------------------------------------------
# property_inventory_rollup
# --------------------------------------------------------------------------
def rollup_property(prop):
    contracts = db.contracts_of_property(prop["id"])
    committed = sum(c["total_recognized_value_cents"] for c in contracts
                    if c["status"] in ("COUNTERSIGNED", "ACTIVE"))
    delivered = sum(c["delivered_media_value_cents"] for c in contracts
                    if c["status"] in ("ACTIVE", "CLOSED"))
    target = prop["inventory_target_value_cents"]
    sellout = Decimal("0.00") if target == 0 else rhu(Decimal("100") * dec(committed) / dec(target), 2)
    prop["committed_gross_value_cents"] = committed
    prop["delivered_media_value_cents"] = delivered
    prop["sellout_pct"] = sellout
    touch(prop)


# --------------------------------------------------------------------------
# staffing releases
# --------------------------------------------------------------------------
def release_assignments(booking, assigned_to="RELEASED", checked_in_to="RELEASED"):
    """Move a booking's working assignments out of ASSIGNED / CHECKED_IN,
    subtracting each shift's whole-minute length from scheduled_minutes."""
    for assignment in db.assignments_of_booking(booking["id"]):
        if assignment["status"] == "ASSIGNED":
            new_status = assigned_to
        elif assignment["status"] == "CHECKED_IN":
            new_status = checked_in_to
        else:
            continue
        assignment["status"] = new_status
        touch(assignment)
        member = store.staff_members.get(assignment["staff_member_id"])
        if member is not None:
            length = minutes_between(assignment["_shift_start_dt"], assignment["_shift_end_dt"])
            member["scheduled_minutes"] = member["scheduled_minutes"] - length
            touch(member)


def release_asset_units(booking):
    asset = store.inventory_assets.get(booking["inventory_asset_id"])
    if asset is not None:
        asset["reserved_units_total"] = asset["reserved_units_total"] - booking["units_booked"]
        touch(asset)


# --------------------------------------------------------------------------
# renewal_likelihood_scoring
# --------------------------------------------------------------------------
def rescore_sponsor(sponsor):
    """The target is the sponsor's CLOSED contract with the greatest term_end,
    ties broken by created_at ascending and never by identifier."""
    closed = [c for c in db.contracts_of_sponsor(sponsor["id"]) if c["status"] == "CLOSED"]
    target = None
    if closed:
        closed.sort(key=lambda c: (c["_term_end_dt"], ), reverse=True)
        best_end = closed[0]["_term_end_dt"]
        tied = [c for c in closed if c["_term_end_dt"] == best_end]
        tied.sort(key=lambda c: (c["created_at"], c["_seq"]))
        target = tied[0]

    if target is None:
        score, band = renewal_likelihood(None, [], [])
    else:
        score, band = renewal_likelihood(
            target,
            db.entitlements_of_contract(target["id"]),
            db.surveys_of_contract(target["id"]),
        )
    touch_if(sponsor, set_fields(sponsor, renewal_likelihood_score=score, renewal_band=band))
    return score, band
