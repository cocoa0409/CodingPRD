"""Lazy expiry materialization and the multi-hop cascades of PRD 2.6, 3.2, 3.5, 3.6."""

import calc
from store import bump, db, now, ordered


# --------------------------------------------------------------------------
# suspension cascade (PRD 3.6)
# --------------------------------------------------------------------------


def cancel_zone_appointments(zone):
    """Hop 3 and 4: cancel the zone's SCHEDULED appointments, release crew minutes."""
    crew_ids = []
    for appointment in ordered(calc.zone_appointments(zone["id"])):
        if appointment["status"] != "SCHEDULED":
            continue
        appointment["status"] = "CANCELLED"
        appointment["cancellation_reason"] = "ZONE_SUSPENDED"
        bump(appointment)
        if appointment["crew_id"] not in crew_ids:
            crew_ids.append(appointment["crew_id"])
    for crew_id in crew_ids:
        crew = db.install_crews.get(crew_id)
        if crew is not None:
            bump(crew)


def suspend_zone(zone, reason, bump_zone=True):
    """Move construction_status to SUSPENDED and run the cascade."""
    zone["construction_status"] = "SUSPENDED"
    zone["suspension_reason"] = reason
    if bump_zone:
        bump(zone)
    cancel_zone_appointments(zone)


# --------------------------------------------------------------------------
# MDU agreement outcome cascades (PRD 3.2)
# --------------------------------------------------------------------------


def _zone_of_address(address):
    return db.build_zones.get(address["build_zone_id"])


def sign_cascade(agreement):
    """SIGNED: CONDITIONAL_MDU address becomes SERVICEABLE, zone rate recomputed."""
    address = db.service_addresses.get(agreement["service_address_id"])
    if address is None or address["serviceability"] != "CONDITIONAL_MDU":
        return
    address["serviceability"] = "SERVICEABLE"
    address["serviceability_determined_at"] = now()
    address["not_serviceable_reason"] = None
    bump(address)
    zone = _zone_of_address(address)
    if zone is not None:
        bump(zone)


def withdrawn_cascade(agreement):
    """DECLINED or EXPIRED: the address loses its conditional path when nothing is signed."""
    address = db.service_addresses.get(agreement["service_address_id"])
    if address is None or address["serviceability"] != "CONDITIONAL_MDU":
        return
    if calc.has_signed_agreement(address["id"]):
        return
    address["serviceability"] = "NOT_SERVICEABLE"
    address["not_serviceable_reason"] = "MDU_AGREEMENT_UNAVAILABLE"
    bump(address)
    zone = _zone_of_address(address)
    if zone is not None:
        bump(zone)


# --------------------------------------------------------------------------
# lazy expiry (PRD 2.4)
# --------------------------------------------------------------------------


def expire_agreement(agreement):
    if agreement["status"] not in ("SENT", "COUNTERED"):
        return agreement
    if now() < agreement["expires_at"]:
        return agreement
    agreement["status"] = "EXPIRED"
    bump(agreement)
    withdrawn_cascade(agreement)
    return agreement


def expire_permit(permit):
    if permit["status"] != "APPROVED":
        return permit
    if permit["expires_at"] is None or now() < permit["expires_at"]:
        return permit
    permit["status"] = "EXPIRED"
    bump(permit)
    zone = db.build_zones.get(permit["build_zone_id"])
    if zone is not None and zone["construction_status"] == "IN_CONSTRUCTION":
        suspend_zone(zone, "PERMIT_EXPIRED")
    return permit


def expire_offer(offer):
    if offer["status"] != "OFFERED":
        return offer
    if now() < offer["expires_at"]:
        return offer
    offer["status"] = "EXPIRED"
    bump(offer)
    return offer


def touch_zone(zone):
    """Materialize every lapsed permit approval of the zone before it is observed."""
    for permit in ordered(calc.zone_permits(zone["id"])):
        expire_permit(permit)
    return zone


def touch_address(address):
    """Materialize every lapsed agreement of the address before it is observed."""
    for agreement in ordered(calc.address_agreements(address["id"])):
        expire_agreement(agreement)
    return address


# --------------------------------------------------------------------------
# deposit movements (PRD 2.8)
# --------------------------------------------------------------------------

MEMOS = {
    "DEPOSIT_HELD": "preorder deposit held",
    "DEPOSIT_REFUNDED": "preorder deposit refunded",
    "DEPOSIT_APPLIED": "preorder deposit applied to install settlement",
    "DEPOSIT_FORFEITED": "preorder deposit forfeited",
    "CLAIM_PAYOUT": "damage claim payout",
}


def move_deposit(preorder, deposit_status, entry_type):
    """Set the money dimension and append the single matching ledger entry."""
    preorder["deposit_status"] = deposit_status
    amount = preorder["deposit_amount_cents"]
    if entry_type != "DEPOSIT_HELD":
        amount = -amount
    calc.append_entry(
        preorder["account_id"],
        entry_type,
        amount,
        MEMOS[entry_type],
        preorder_id=preorder["id"],
    )
