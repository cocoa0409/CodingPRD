"""Buyer warranty claims: evidence, adjudication and return routing (PRD §3.6)."""

from db import store, touch, iso, stamp_new, add_days, calendar_days_between
from errors import fail
from numeric import rhu, rhu_int
from services import exposure as expo
from services import reservations as resv
from vocab import (
    BUYER_GOODWILL_RATE,
    INBOUND_SHIPPING_CENTS,
    MARKETPLACE_FVF_RATE,
    ON_TIME_WINDOW_DAYS,
    REFUSED_FUNDED_CENTS,
    REPAIR_CAP_CENTS,
    REPLACEMENT_WARRANTY_PERIOD_DAYS,
    REPLACE_CAP_CENTS,
    RETURN_SLOT_SECONDS,
)

# Carrier slots already booked, as (carrier, start_dt, end_dt).
booked_return_slots = []


def reset_runtime_state():
    del booked_return_slots[:]


# --------------------------------------------------------------- creation
def create_claim(listing, seller, data, clock):
    payload = {
        "listing_id": listing["id"],
        "routed_seller_id": listing.get("servicing_seller_id"),
        "claim_state": "FILED",
        "resolution_type": None,
        "resolution_obligation_cents": None,
        "claim_reason_code": data["claim_reason_code"],
        "diagnostic_evidence_digest": None,
        "return_carrier": None,
        "return_shipment_cents": 0,
        "seller_funded_amount_cents": 0,
        "claim_reserve_cents": 0,
        "replacement_listing_id": None,
        "on_time_flag": False,
        "evidence_included": bool(data.get("evidence_included", False)),
        "_evidence_user_id": None,
        "_resolved_dt": None,
        "_return_start_dt": None,
    }
    stamp_new("claims", payload, clock)
    store.claims[payload["id"]] = payload
    return payload


def _listing_of(claim):
    listing = store.listings.get(claim["listing_id"])
    if listing is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return listing


def _servicing_reservation_or_404(claim):
    listing = _listing_of(claim)
    return resv.select_servicing_reservation(listing)


def _recompute_seller_after_claim(claim, clock):
    seller_id = claim.get("routed_seller_id")
    if seller_id:
        from services import sellers as seller_svc
        seller_svc.remap_tier_from_open_sections(store.sellers[seller_id], clock) \
            if seller_id in store.sellers else None
        expo.recompute_exposure_floor(seller_id, clock)


# --------------------------------------------------------------- evidence
def attach_evidence(claim, digest_present, digest_value, actor_user_id, clock):
    """Priority 14 rejects a malformed or absent digest before the transition."""
    from requtils import is_hex64

    if claim["claim_state"] in ("REJECTED", "RESOLVED"):
        raise fail("ERR_CLAIM_TERMINAL")
    if not is_hex64(digest_value):
        raise fail("ERR_DIAGNOSTIC_EVIDENCE_REQUIRED")
    if claim["claim_state"] != "FILED":
        raise fail("ERR_INVALID_STATE")

    listing = _listing_of(claim)
    reservation = _servicing_reservation_or_404(claim)

    claim["claim_state"] = "UNDER_REVIEW"
    claim["diagnostic_evidence_digest"] = digest_value
    claim["routed_seller_id"] = listing.get("servicing_seller_id")
    claim["_evidence_user_id"] = actor_user_id

    reservation["claims_filed_count"] = reservation.get("claims_filed_count", 0) + 1
    claim["claim_reserve_cents"] = resv.reserve_cents_for_claim(reservation)
    touch(reservation, clock)
    touch(claim, clock)

    seller_id = claim.get("routed_seller_id")
    if seller_id in store.sellers:
        from services import sellers as seller_svc
        seller_svc.remap_tier_from_open_sections(store.sellers[seller_id], clock)
        expo.recompute_exposure_floor(seller_id, clock)
    return claim


# ------------------------------------------------------------- adjudicate
def adjudicate(claim, decision, data, clock):
    if claim["claim_state"] in ("REJECTED", "RESOLVED"):
        raise fail("ERR_CLAIM_TERMINAL")
    if claim["claim_state"] == "APPROVED":
        raise fail("ERR_CLAIM_ALREADY_UPHELD")
    if claim["claim_state"] != "UNDER_REVIEW":
        raise fail("ERR_INVALID_STATE")

    if decision == "REJECTED":
        claim["claim_state"] = "REJECTED"
        claim["claim_reserve_cents"] = 0
        touch(claim, clock)
        try:
            reservation = _servicing_reservation_or_404(claim)
            reservation["claims_filed_count"] = max(
                0, reservation.get("claims_filed_count", 0) - 1)
            touch(reservation, clock)
        except Exception:
            pass
        _recompute_seller_after_claim(claim, clock)
        return claim

    # An uphold requires the diagnostic digest and a within-cap obligation.
    if not claim.get("diagnostic_evidence_digest"):
        raise fail("ERR_DIAGNOSTIC_EVIDENCE_REQUIRED")
    if claim.get("_evidence_user_id") is not None and \
            claim["_evidence_user_id"] == data.get("adjudicator_user_id"):
        raise fail("ERR_SOD_VIOLATION")

    resolution_type = data.get("resolution_type")
    if resolution_type not in ("REPAIR", "REPLACE"):
        raise fail("ERR_INVALID_REQUEST")
    obligation = data.get("resolution_obligation_cents")
    if obligation is None or obligation < 0:
        raise fail("ERR_INVALID_REQUEST")
    cap = REPAIR_CAP_CENTS if resolution_type == "REPAIR" else REPLACE_CAP_CENTS
    if obligation > cap:
        raise fail("ERR_OBLIGATION_EXCEEDS_CAP")

    shipment = data.get("return_shipment_cents") or 0
    reservation = _servicing_reservation_or_404(claim)

    claim["claim_state"] = "APPROVED"
    claim["resolution_type"] = resolution_type
    claim["resolution_obligation_cents"] = obligation
    claim["seller_funded_amount_cents"] = obligation + shipment
    claim["return_shipment_cents"] = shipment

    if resolution_type == "REPAIR":
        reservation["repair_obligation_cents"] = \
            reservation.get("repair_obligation_cents", 0) + obligation
    else:
        reservation["replacement_obligation_cents"] = \
            reservation.get("replacement_obligation_cents", 0) + obligation
        nominated = data.get("replacement_listing_id")
        if nominated is not None:
            claim["replacement_listing_id"] = nominated

    # Cascade: the reservation flips to REPAIRING or REPLACED.
    if reservation["warranty_state"] in ("ACTIVE", "REPAIRING", "REPLACED"):
        reservation["warranty_state"] = "REPAIRING" if resolution_type == "REPAIR" else "REPLACED"
    touch(reservation, clock)
    listing = _listing_of(claim)
    listing["active_reservation_days"] = listing.get("active_reservation_days", 0) + 1
    touch(listing, clock)
    touch(claim, clock)

    seller_id = claim.get("routed_seller_id")
    if seller_id in store.sellers:
        from services import sellers as seller_svc
        seller_svc.remap_tier_from_open_sections(store.sellers[seller_id], clock)
        expo.recompute_exposure_floor(seller_id, clock)
    return claim


# ------------------------------------------------------------ route return
def route_return(claim, data, clock):
    if claim["claim_state"] in ("REJECTED", "RESOLVED"):
        raise fail("ERR_CLAIM_TERMINAL")
    if claim["claim_state"] != "APPROVED":
        raise fail("ERR_INVALID_STATE")

    # The routed-seller binding is immutable (PRD §2.5).  A carrier-less return
    # would be admissible under the reclamation policy but the binding cannot
    # lawfully be rewritten, so it is refused.
    if "return_carrier" not in data or data.get("return_carrier") is None:
        raise fail("ERR_ROUTED_SELLER_IMMUTABLE")

    carrier = data["return_carrier"]
    if carrier not in ("CARRIER_A", "CARRIER_B", "CARRIER_C"):
        raise fail("ERR_INVALID_REQUEST")

    shipment = data.get("return_shipment_cents")
    if shipment is None:
        raise fail("ERR_INVALID_REQUEST")
    if shipment < 0:
        raise fail("ERR_INVALID_REQUEST")

    start_raw = data.get("return_shipment_start")
    if start_raw is not None:
        from db import parse_iso
        start = parse_iso(start_raw)
        if start is None:
            raise fail("ERR_INVALID_REQUEST", "return_shipment_start must be an ISO 8601 instant.")
        end = start + __import__("datetime").timedelta(seconds=RETURN_SLOT_SECONDS)
        if _slot_collides(carrier, start, end):
            raise fail("ERR_RETURN_SLOT_COLLISION")
        booked_return_slots.append((carrier, start, end))

    claim["claim_state"] = "RESOLVED"
    claim["return_carrier"] = carrier
    claim["return_shipment_cents"] = shipment
    claim["seller_funded_amount_cents"] = claim.get("seller_funded_amount_cents", 0) + shipment
    claim["_resolved_dt"] = clock
    claim["on_time_flag"] = _on_time(claim, clock)
    claim["claim_reserve_cents"] = 0
    touch(claim, clock)

    _recompute_seller_after_claim(claim, clock)
    return claim


def _slot_collides(carrier, start, end):
    for booked_carrier, booked_start, booked_end in booked_return_slots:
        if booked_carrier != carrier:
            continue
        # Touching at either boundary collides.
        if start <= booked_end and end >= booked_start:
            return True
    return False


def _on_time(claim, clock):
    created = claim.get("_created_dt")
    if created is None:
        return False
    return calendar_days_between(created, clock) <= ON_TIME_WINDOW_DAYS


# ------------------------------------------------------------- settlement
def settlement_view(claim):
    """Extra read-only figures carried alongside a claim (PRD §3.6)."""
    if claim.get("resolution_type") != "REPLACE":
        return {}
    listing = store.listings.get(claim["listing_id"])
    sold_price = listing.get("list_price_cents", 0) if listing else 0

    gross = rhu_int(claim.get("claim_reserve_cents", 0) + rhu_int(sold_price * BUYER_GOODWILL_RATE, 0), 0)
    replacement_id = claim.get("replacement_listing_id")
    replacement = store.listings.get(replacement_id) if replacement_id else None
    if replacement is not None and claim.get("_resolved_dt") is not None:
        activated = replacement.get("_activation_dt")
        if activated is not None:
            incurred = calendar_days_between(activated, claim["_resolved_dt"])
        else:
            incurred = 0
    else:
        incurred = 0
    incurred = max(0, min(incurred, REPLACEMENT_WARRANTY_PERIOD_DAYS))
    chargeback = max(0, rhu_int(
        REFUSED_FUNDED_CENTS * incurred / REPLACEMENT_WARRANTY_PERIOD_DAYS, 0))
    return {
        "payout_to_buyer_cents": gross,
        "seller_chargeback_cents": chargeback,
        "marketplace_fvf_cents": rhu_int(sold_price * MARKETPLACE_FVF_RATE, 0),
        "inbound_shipping_cents": INBOUND_SHIPPING_CENTS,
    }