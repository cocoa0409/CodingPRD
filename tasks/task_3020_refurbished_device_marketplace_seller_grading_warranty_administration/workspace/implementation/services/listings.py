"""Device listing eligibility ladder, review, delisting, withdrawal, buy box."""

from db import store, touch, iso, stamp_new, add_days
from errors import fail
from numeric import rhu, rhu_int
from services import exposure as expo
from services import reservations as resv
from vocab import (
    DEFAULT_RESERVED_UNITS,
    DEFAULT_UNIT_RESERVE_PER_DAY_CENTS,
    DEFAULT_WARRANTY_PERIOD_DAYS,
    ELITE_MIN_SCORE,
    ELITE_MULTIPLIER,
    HARD_BATTERY_FLOOR,
    PRICE_DEVIATION_PCT,
    PROBATION_MIN_SCORE,
    PROBATION_MULTIPLIER,
    REPLACEMENT_WARRANTY_PERIOD_DAYS,
    STANDARD_MIN_SCORE,
    STANDARD_MULTIPLIER,
    SUSPENDED_MULTIPLIER,
)


# ------------------------------------------------------------ grading
def active_grading_definition():
    for row in store.grading_definitions.values():
        if row["definition_state"] == "ACTIVE":
            return row
    return None


def active_battery_floor():
    definition = active_grading_definition()
    if definition is None:
        return HARD_BATTERY_FLOOR
    return max(HARD_BATTERY_FLOOR, int(definition["battery_floor_pct"]))


def reload_binding_definition(listing_id, definition_id):
    """Listings bound to a definition at submission time."""
    return [
        row for row in store.listings.values()
        if row.get("binding_definition_id") == definition_id
        or row.get("_binding_definition_id") == definition_id
    ]


# --------------------------------------------------- eligibility ladder
def check_eligibility(seller, data, clock, exclude_listing_id=None):
    """The nine checks, evaluated in PRD §2.11 priority order."""
    imei = data["imei"]
    model_code = data["model_code"]

    # Priority 6 -- blocklist screening.
    if imei in store.stolen_blocklist or imei in store.counterfeit_blocklist:
        raise fail("ERR_DEVICE_BLOCKLISTED")

    # Priority 7 -- battery floor.
    floor = active_battery_floor()
    if data["battery_health_pct"] < floor:
        raise fail("ERR_BATTERY_BELOW_FLOOR")

    # Priority 9 -- counterfeit price-pattern screening.
    catalog_floor = store.model_floor(model_code)
    if catalog_floor is not None and catalog_floor > 0:
        threshold = catalog_floor * (1 - PRICE_DEVIATION_PCT)
        if data["list_price_cents"] < threshold:
            raise fail("ERR_COUNTERFEIT_PRICE_SIGNAL")

    # Priority 10 -- part provenance documentation.
    if data["part_provenance"] != "OEM_ONLY":
        from requtils import is_hex64
        if not is_hex64(data.get("provenance_doc_digest")):
            raise fail("ERR_PART_PROVENANCE_UNDOCUMENTED")

    # Priority 11 -- model catalogue eligibility.
    if model_code not in store.supported_models:
        raise fail("ERR_MODEL_NOT_ELIGIBLE")
    if store.model_restricted(model_code, clock):
        raise fail("ERR_MODEL_NOT_ELIGIBLE")

    # Priority 12 -- seller approval standing.
    if seller["onboarding_state"] != "APPROVED":
        raise fail("ERR_SELLER_NOT_APPROVED")

    # Priority 29 -- IMEI reuse across non-withdrawn rows.
    for row in store.listings.values():
        if row["id"] == exclude_listing_id:
            continue
        if row.get("seller_id") != seller["id"]:
            continue
        if row["listing_state"] == "WITHDRAWN":
            continue
        if row["imei"] == imei:
            raise fail("ERR_IMEI_ALREADY_LISTED")

    # PRD §3.2: a carrier-locked device cannot be sold as refurbished.  The
    # error catalogue carries no dedicated id for this rule, so it reports the
    # generic malformed-request code; it is evaluated last so that no graded
    # rule is preempted by it.
    if data["carrier_lock_status"] == "LOCKED":
        raise fail("ERR_INVALID_REQUEST",
                   "carrier_lock_status LOCKED is not admissible for a refurbished listing.")
    return True


def build_listing_payload(seller, data, clock):
    binding = active_grading_definition()
    payload = {
        "seller_id": seller["id"],
        "model_code": data["model_code"],
        "imei": data["imei"],
        "cosmetic_grade": data["cosmetic_grade"],
        "functional_grade": data["functional_grade"],
        "battery_health_pct": data["battery_health_pct"],
        "carrier_lock_status": data["carrier_lock_status"],
        "part_provenance": data["part_provenance"],
        "provenance_doc_digest": data.get("provenance_doc_digest"),
        "serving_seller_id": seller["id"],
        "servicing_seller_id": seller["id"],
        "listing_state": "UNDER_REVIEW",
        "active_reservation_days": 0,
        "unit_reserve_per_day_cents": data.get(
            "unit_reserve_per_day_cents", DEFAULT_UNIT_RESERVE_PER_DAY_CENTS),
        "mystery_shop_disclosed": False,
        "servicing_reservation_id": None,
        "list_price_cents": data["list_price_cents"],
        "binding_definition_id": binding["id"] if binding else None,
        "_binding_definition_id": binding["id"] if binding else None,
        "_activation_dt": clock,
    }
    return payload


def create_listing(seller, data, clock):
    check_eligibility(seller, data, clock)
    payload = build_listing_payload(seller, data, clock)
    stamp_new("listings", payload, clock)
    store.listings[payload["id"]] = payload
    touch(seller, clock)
    from services import sellers as seller_svc
    seller_svc.remap_tier_from_open_sections(seller, clock)
    return payload


def resubmit_listing(listing, seller, data, expected_seller_version, clock):
    """Re-submission: re-run the whole ladder, re-capture the binding,
    and serialise against the seller's version.
    """
    check_eligibility(seller, data, clock, exclude_listing_id=listing["id"])

    if listing["listing_state"] not in ("DRAFT", "DELISTED", "SUSPENDED"):
        raise fail("ERR_INVALID_STATE")

    # Priority 24 -- optimistic concurrency against the parent seller.
    if expected_seller_version != seller["version"]:
        raise fail("ERR_STALE_VERSION")

    binding = active_grading_definition()
    listing["listing_state"] = "UNDER_REVIEW"
    listing["binding_definition_id"] = binding["id"] if binding else None
    listing["_binding_definition_id"] = binding["id"] if binding else None
    for key in ("model_code", "imei", "cosmetic_grade", "functional_grade",
                "battery_health_pct", "carrier_lock_status", "part_provenance",
                "list_price_cents"):
        if key in data:
            listing[key] = data[key]
    if "provenance_doc_digest" in data:
        listing["provenance_doc_digest"] = data.get("provenance_doc_digest")
    listing["servicing_seller_id"] = listing.get("serving_seller_id", seller["id"])
    touch(listing, clock)
    touch(seller, clock)
    return listing


# --------------------------------------------------------------- review
def review_listing(listing, decision, clock):
    if listing["listing_state"] != "UNDER_REVIEW":
        raise fail("ERR_INVALID_STATE")

    # Priority 30 -- the captured binding must still be ACTIVE.
    binding_id = listing.get("binding_definition_id") or listing.get("_binding_definition_id")
    if binding_id is not None:
        binding = store.grading_definitions.get(binding_id)
        if binding is None or binding["definition_state"] != "ACTIVE":
            raise fail("ERR_GRADING_DEFINITION_NOT_ACTIVE")

    if decision == "APPROVED":
        listing["listing_state"] = "LISTED"
        touch(listing, clock)
        reservation = _open_reservation_for_listing(listing, clock)
        listing["servicing_reservation_id"] = reservation["id"]
    else:
        listing["listing_state"] = "DRAFT"
        touch(listing, clock)

    seller = store.sellers.get(listing.get("serving_seller_id"))
    if seller is not None:
        from services import sellers as seller_svc
        seller_svc.remap_tier_from_open_sections(seller, clock)
    return listing


def _open_reservation_for_listing(listing, clock):
    payload = {
        "listing_id": listing["id"],
        "originated_claim_id": None,
        "warranty_state": "ACTIVE",
        "activated_on": iso(clock),
        "warranty_period_days": DEFAULT_WARRANTY_PERIOD_DAYS,
        "expired_on": iso(add_days(clock, DEFAULT_WARRANTY_PERIOD_DAYS)),
        "reserved_units": DEFAULT_RESERVED_UNITS,
        "unit_reserve_per_day_cents": listing.get(
            "unit_reserve_per_day_cents", DEFAULT_UNIT_RESERVE_PER_DAY_CENTS),
        "claims_filed_count": 0,
        "repair_obligation_cents": 0,
        "replacement_obligation_cents": 0,
        "_activated_dt": clock,
        "_servicing_seller_id": listing["servicing_seller_id"],
    }
    stamp_new("reservations", payload, clock)
    store.reservations[payload["id"]] = payload
    return payload


def create_reservation(listing, data, clock):
    activated_on = data["_activated_on"]
    period = data["warranty_period_days"]
    payload = {
        "listing_id": listing["id"],
        "originated_claim_id": data.get("originated_claim_id"),
        "warranty_state": "ACTIVE",
        "activated_on": iso(activated_on),
        "warranty_period_days": period,
        "expired_on": iso(add_days(activated_on, period)),
        "reserved_units": data.get("reserved_units", DEFAULT_RESERVED_UNITS),
        "unit_reserve_per_day_cents": data.get(
            "unit_reserve_per_day_cents", DEFAULT_UNIT_RESERVE_PER_DAY_CENTS),
        "claims_filed_count": 0,
        "repair_obligation_cents": 0,
        "replacement_obligation_cents": 0,
        "_activated_dt": activated_on,
        "_servicing_seller_id": listing["servicing_seller_id"],
    }
    stamp_new("reservations", payload, clock)
    store.reservations[payload["id"]] = payload
    return payload


# ----------------------------------------------------- delist / withdraw
def delist_listing(listing, reason_code, clock):
    if listing["listing_state"] != "LISTED":
        raise fail("ERR_INVALID_STATE")
    listing["listing_state"] = "DELISTED"
    touch(listing, clock)
    _flip_servicing_reservation(listing, clock)
    seller_id = listing.get("serving_seller_id")
    if seller_id:
        expo.recompute_exposure_floor(seller_id, clock)
    return listing


def _flip_servicing_reservation(listing, clock):
    try:
        winner = resv.select_servicing_reservation(listing)
    except Exception:
        return None
    winner["warranty_state"] = "SUSPENDED"
    touch(winner, clock)
    listing["active_reservation_days"] = listing.get("active_reservation_days", 0) + 1
    return winner


def withdraw_listing(listing, clock):
    if listing["listing_state"] not in ("DRAFT", "UNDER_REVIEW", "DELISTED"):
        raise fail("ERR_INVALID_STATE")
    for claim in store.claims.values():
        if claim["listing_id"] == listing["id"] and claim["claim_state"] in (
                "FILED", "UNDER_REVIEW", "APPROVED"):
            raise fail("ERR_WITHDRAW_BLOCKED_BY_OPEN_CLAIM")
    for reservation in store.reservations.values():
        if reservation["listing_id"] == listing["id"] and reservation["warranty_state"] == "REPAIRING":
            raise fail("ERR_WITHDRAW_BLOCKED_BY_OPEN_CLAIM")
    listing["listing_state"] = "WITHDRAWN"
    touch(listing, clock)
    return listing


# -------------------------------------------------------------- buy box
def rank_multiplier(rank_score):
    value = float(rank_score)
    if value >= ELITE_MIN_SCORE:
        return ELITE_MULTIPLIER
    if value >= STANDARD_MIN_SCORE:
        return STANDARD_MULTIPLIER
    if value >= PROBATION_MIN_SCORE:
        return PROBATION_MULTIPLIER
    return SUSPENDED_MULTIPLIER


def buy_box(listing, clock):
    candidates = []
    for row in store.listings.values():
        if row["listing_state"] != "LISTED":
            continue
        if row["model_code"] != listing["model_code"]:
            continue
        seller = store.sellers.get(row.get("seller_id"))
        if seller is None or seller["onboarding_state"] != "APPROVED":
            continue
        if seller["performance_tier"] not in ("ELITE", "STANDARD", "PROBATION"):
            continue
        rank_score = expo.latest_closed_score(seller["id"])
        if rank_score is None:
            continue
        candidates.append((row, seller, rank_score))

    if not candidates:
        return {
            "winner_listing_id": listing["id"],
            "winner_seller_id": listing.get("seller_id"),
            "winner_rank_score": 0.0,
            "buy_box_price_cents": listing.get("list_price_cents", 0),
            "ranked_listing_ids": [],
        }

    # Pinned sort key: -1 * round_half_up(list_price_cents * 1.00, 2).
    # "-150000 beats -160000", so a LOWER list price ranks first; the tie-break
    # is created_at ASC.  No id participates in either.  Encoded directly as
    # (price ASC, created_at ASC) so there is no direction to misread.
    candidates.sort(key=lambda item: (
        float(rhu(item[0]["list_price_cents"] * 1.00, 2)),
        item[0].get("created_at", ""),
        item[0].get("_seq", 0),
    ))

    winner_listing, winner_seller, winner_score = candidates[0]
    ranked_ids = [item[0]["id"] for item in candidates]

    others = [item[0]["list_price_cents"] for item in candidates if item[0]["id"] != winner_listing["id"]]
    if others:
        mean = sum(others) / len(others)
        average_competitor_price_cents = int(mean)  # integer floor
    else:
        average_competitor_price_cents = winner_listing["list_price_cents"]

    multiplier = rank_multiplier(winner_score)
    price = rhu_int(multiplier * average_competitor_price_cents, 0)
    if price <= 0:
        price = winner_listing["list_price_cents"]

    return {
        "winner_listing_id": winner_listing["id"],
        "winner_seller_id": winner_listing.get("seller_id"),
        "winner_rank_score": float(winner_score),
        "buy_box_price_cents": int(price),
        "ranked_listing_ids": ranked_ids,
    }