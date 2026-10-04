"""Seller onboarding state machine, performance-tier derivation and cascades."""

from db import store, touch, iso, add_days
from errors import fail
from numeric import rhu
from services import exposure as expo
from services import reservations as resv
from vocab import (
    ELITE_THRESHOLD,
    STANDARD_THRESHOLD,
    SUSPENSION_THRESHOLD,
    BLOCKLIST_FINDINGS,
)


# --------------------------------------------------------------- tiers
def tier_for_score(score):
    """PRD §3.7: ELITE >= 85.00, STANDARD >= 70.00, PROBATION > 55.00, else SUSPENDED."""
    if score is None:
        return "PROBATION"
    value = float(score)
    if value >= ELITE_THRESHOLD:
        return "ELITE"
    if value >= STANDARD_THRESHOLD:
        return "STANDARD"
    if value > SUSPENSION_THRESHOLD:
        return "PROBATION"
    return "SUSPENDED"


def remap_tier(seller, clock):
    """Re-derive performance_tier from the seller's latest CLOSED section."""
    score = expo.latest_closed_score(seller["id"])
    seller["performance_tier"] = tier_for_score(score)
    touch(seller, clock)
    return seller


def refresh_latest_score_id(seller, clock):
    section = expo.latest_closed_section(seller["id"])
    seller["latest_score_id"] = section["id"] if section else None


def remap_tier_from_open_sections(seller, clock):
    """A component-source change can take an OPEN section to or below the
    suspension threshold; if it does, the seller is suspended.
    """
    from services import scoring
    for section in store.service_scores.values():
        if section["seller_id"] != seller["id"] or section["section_state"] != "OPEN":
            continue
        scoring.recompute_section(section, clock)
        if section.get("threshold_breached") and seller["onboarding_state"] == "APPROVED":
            seller["onboarding_state"] = "SUSPENDED"
            seller["performance_tier"] = "SUSPENDED"
            seller["suspension_trigger_count"] = seller.get("suspension_trigger_count", 0) + 1
            touch(seller, clock)
            return seller
    if seller["onboarding_state"] == "APPROVED":
        remap_tier(seller, clock)
    return seller


# ------------------------------------------------------------- creation
def create_seller(legal_name, country_code, capacity_units, clock):
    for row in store.sellers.values():
        if row["legal_name"].lower() == legal_name.lower():
            raise fail(
                "ERR_INVALID_REQUEST",
                "A seller with this legal name already exists.",
            )
    payload = {
        "legal_name": legal_name,
        "country_code": country_code,
        "refurbishment_capacity_units": capacity_units,
        "onboarding_state": "APPLICANT",
        "performance_tier": "PROBATION",
        "latest_score_id": None,
        "exposure_floor_cents": 0,
        "suspension_trigger_count": 0,
        "blocklisted": False,
    }
    from db import stamp_new
    stamp_new("sellers", payload, clock)
    store.sellers[payload["id"]] = payload
    return payload


def touch_seller(seller_id, clock):
    seller = store.sellers.get(seller_id)
    if seller is not None:
        touch(seller, clock)
    return seller


# --------------------------------------------------------- onboarding
def verify_documents(seller, clock):
    if seller["onboarding_state"] != "APPLICANT":
        raise fail("ERR_INVALID_STATE")
    if seller.get("blocklisted"):
        raise fail("ERR_INVALID_STATE", "A blocklisted seller cannot be verified.")
    seller["onboarding_state"] = "DOCUMENT_VERIFIED"
    touch(seller, clock)
    return seller


def book_audit_record(seller, scheduled_for, scope_note, throughput, clock):
    if seller["onboarding_state"] != "DOCUMENT_VERIFIED":
        raise fail("ERR_INVALID_STATE")
    for row in store.audit_records.values():
        if row["seller_id"] == seller["id"] and row["audit_state"] == "IN_PROGRESS":
            raise fail("ERR_AUDIT_ALREADY_SCHEDULED")
    payload = {
        "seller_id": seller["id"],
        "audit_state": "IN_PROGRESS",
        "audit_scheduled_for": iso(scheduled_for),
        "audit_scope_note": scope_note,
        "audit_score": None,
        "auditor_user_id": None,
        "declared_monthly_throughput": throughput,
        "_scheduled_dt": scheduled_for,
    }
    from db import stamp_new
    stamp_new("audit_records", payload, clock)
    store.audit_records[payload["id"]] = payload
    seller["onboarding_state"] = "AUDIT_SCHEDULED"
    touch(seller, clock)
    return payload


def transition_audit_record(record, target_state, audit_score, auditor_user_id, clock):
    """Three branches; the capacity cross-check outranks the score band."""
    if record["audit_state"] != "IN_PROGRESS":
        raise fail("ERR_INVALID_STATE")
    seller = store.sellers.get(record["seller_id"])
    if seller is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    if target_state not in ("PASSED", "FAILED"):
        raise fail("ERR_INVALID_REQUEST")

    record["audit_score"] = audit_score
    record["auditor_user_id"] = auditor_user_id

    # Capacity cross-check first (PRD §3.1).
    if record["declared_monthly_throughput"] > seller["refurbishment_capacity_units"]:
        record["audit_state"] = "FAILED"
        seller["onboarding_state"] = "REJECTED"
        touch(record, clock)
        touch(seller, clock)
        return record

    if target_state == "PASSED" or audit_score >= 70:
        if audit_score < 70:
            raise fail("ERR_INVALID_STATE", "A score below 70 cannot pass the audit.")
        record["audit_state"] = "PASSED"
        seller["onboarding_state"] = "APPROVED"
        seller["performance_tier"] = "PROBATION"
        seller["exposure_floor_cents"] = 0
        touch(record, clock)
        touch(seller, clock)
        return record

    record["audit_state"] = "FAILED"
    seller["onboarding_state"] = "APPLICANT"
    touch(record, clock)
    touch(seller, clock)
    return record


# ------------------------------------------------------- seller suspend
def suspend_seller(seller, reason_code, clock):
    """Seller-level remedy: delist the catalogue and start repair exposure."""
    if seller["onboarding_state"] != "APPROVED":
        raise fail("ERR_INVALID_STATE")
    for listing in store.listings.values():
        if listing.get("seller_id") != seller["id"]:
            continue
        if listing["listing_state"] != "LISTED":
            continue
        listing["listing_state"] = "DELISTED"
        touch(listing, clock)
        _flip_servicing_reservation_to_repairing(listing, clock)
    expo.recompute_exposure_floor(seller["id"], clock)
    remap_tier(seller, clock)
    return seller


def _flip_servicing_reservation_to_repairing(listing, clock):
    """Delisting moves the servicing reservation to REPAIRING.

    A reservation already in REPLACED is left alone: the selector does not
    re-select SUSPENDED rows, so overwriting REPLACED with SUSPENDED would
    silently drop a live exposure cell.
    """
    try:
        winner = resv.select_servicing_reservation(listing)
    except Exception:
        return None
    if winner["warranty_state"] in ("ACTIVE", "REPAIRING"):
        winner["warranty_state"] = "REPAIRING"
        touch(winner, clock)
    listing["active_reservation_days"] = listing.get("active_reservation_days", 0) + 1
    return winner


def _flip_servicing_reservation_to_suspended(listing, clock):
    """Blocklist cascade: the servicing reservation is suspended and its
    reserved units are zeroed so the seller's repair term empties out.
    """
    try:
        winner = resv.select_servicing_reservation(listing)
    except Exception:
        return None
    winner["warranty_state"] = "SUSPENDED"
    winner["reserved_units"] = 0
    touch(winner, clock)
    return winner


# ----------------------------------------------------------- blocklist
def blocklist_seller(seller, finding, evidence_digest, clock):
    if finding not in BLOCKLIST_FINDINGS:
        raise fail("ERR_INVALID_REQUEST")
    if seller.get("blocklisted"):
        raise fail("ERR_SELLER_ALREADY_BLOCKLISTED")
    # Ceiling / human-review gate (PRD §2.12).
    expo.check_blocklist_ceiling(seller)

    seller["blocklisted"] = True
    seller["onboarding_state"] = "SUSPENDED"
    seller["performance_tier"] = "SUSPENDED"
    touch(seller, clock)

    # Cascade depth 2: every LISTED device of this seller becomes SUSPENDED.
    for listing in store.listings.values():
        if listing.get("seller_id") != seller["id"]:
            continue
        if listing["listing_state"] != "LISTED":
            continue
        listing["listing_state"] = "SUSPENDED"
        touch(listing, clock)
        # Cascade depth 3: the servicing reservation is suspended and its
        # reserved units are zeroed.
        _flip_servicing_reservation_to_suspended(listing, clock)

    # The owner's exposure floor is recomputed from the now-empty repair term.
    expo.recompute_exposure_floor(seller["id"], clock)
    return seller