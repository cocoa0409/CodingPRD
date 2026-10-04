"""Service-score sections and the weighted seller service score (PRD §3.7).

Rounding order is pinned and load-bearing: each of the four components is
rounded half-up to two decimals FIRST, then combined by weight, and the
weighted sum is rounded half-up to two decimals ONCE MORE.  Summing the raw
ratios first and rounding only at the end is the non-conforming order.
"""

from db import store, touch, iso
from errors import fail
from numeric import dec, rhu, rhu_int
from services import exposure as expo
from vocab import (
    MIN_SECTION_DAYS,
    SUSPENSION_THRESHOLD,
    WEIGHT_CLAIM_FAILURE,
    WEIGHT_GRADING_COMPLIANCE,
    WEIGHT_ON_TIME_RESOLUTION,
    WEIGHT_RETURN_RATE,
)


def in_window(row, opened, closed):
    """Half-open window: lower bound EXCLUSIVE, upper bound INCLUSIVE."""
    created = row.get("_created_dt")
    if created is None:
        return False
    return created > opened and created <= closed


def compute_components(section, window_end):
    """Return (components dict, raw counts) for the section at `window_end`."""
    seller_id = section["seller_id"]
    opened = section["_opened_dt"]

    routed_rows = [
        claim for claim in store.claims.values()
        if claim.get("routed_seller_id") == seller_id and in_window(claim, opened, window_end)
    ]
    routed = len(routed_rows)
    rejected = sum(1 for c in routed_rows if c["claim_state"] == "REJECTED")
    on_time = sum(1 for c in routed_rows if c.get("on_time_flag"))

    shop_rows = [
        row for row in store.verifications.values()
        if row["seller_id"] == seller_id and in_window(row, opened, window_end)
    ]
    shops = len(shop_rows)
    violations = sum(row.get("value_at_risk", 0) or 0 for row in shop_rows)

    seller_listings = [
        row for row in store.listings.values()
        if row.get("seller_id") == seller_id and in_window(row, opened, window_end)
    ]
    listed = len(seller_listings)
    returned = 0
    listing_ids = {row["id"] for row in seller_listings}
    for reservation in store.reservations.values():
        if reservation["listing_id"] in listing_ids and reservation["warranty_state"] == "REPAIRING":
            returned += 1

    claim_failure_rate_pct = rhu(dec(100) * rejected / max(1, routed), 2)
    on_time_resolution_pct = rhu(dec(100) * on_time / max(1, routed), 2)
    grading_compliance_pct = rhu(dec(100) * (shops - violations) / max(1, shops), 2)
    return_rate_pct = rhu(dec(100) * returned / max(1, listed), 2)

    score = rhu(
        dec(WEIGHT_CLAIM_FAILURE) * (dec(100) - claim_failure_rate_pct)
        + dec(WEIGHT_ON_TIME_RESOLUTION) * on_time_resolution_pct
        + dec(WEIGHT_GRADING_COMPLIANCE) * grading_compliance_pct
        + dec(WEIGHT_RETURN_RATE) * (dec(100) - return_rate_pct),
        2,
    )

    components = {
        "claim_failure_rate_pct": float(claim_failure_rate_pct),
        "on_time_resolution_pct": float(on_time_resolution_pct),
        "grading_compliance_pct": float(grading_compliance_pct),
        "return_rate_pct": float(return_rate_pct),
        "service_score": float(score),
    }
    counts = {
        "routed": routed,
        "rejected": rejected,
        "on_time": on_time,
        "shops": shops,
        "violations": violations,
        "listed": listed,
        "returned": returned,
    }
    return components, counts


def recompute_section(section, clock):
    """Re-derive the section's components; for an OPEN section the window's
    upper bound is the current logical clock instant.
    """
    if section["section_state"] == "CLOSED":
        window_end = section.get("_closed_dt")
        if window_end is None:
            return section
    else:
        window_end = clock
    components, _counts = compute_components(section, window_end)
    section.update(components)
    section["threshold_breached"] = float(components["service_score"]) <= SUSPENSION_THRESHOLD
    return section


def create_section(seller_id, opened_on, clock):
    payload = {
        "seller_id": seller_id,
        "section_opened_on": iso(opened_on),
        "section_state": "OPEN",
        "section_closed_on": None,
        "claim_failure_rate_pct": 0.0,
        "on_time_resolution_pct": 0.0,
        "grading_compliance_pct": 0.0,
        "return_rate_pct": 0.0,
        "service_score": 0.0,
        "threshold_breached": False,
        "_opened_dt": opened_on,
        "_closed_dt": None,
    }
    from db import stamp_new
    stamp_new("service_scores", payload, clock)
    store.service_scores[payload["id"]] = payload
    recompute_section(payload, clock)
    return payload


def close_section(section, clock):
    """Close the section, recompute it and drive the seller's tier.

    Guard ordering matters (PRD §3.7): the open-approved-claim guard fires
    BEFORE the section-age guard.
    """
    if section["section_state"] != "OPEN":
        raise fail("ERR_INVALID_STATE")
    seller_id = section["seller_id"]

    for claim in store.claims.values():
        if claim.get("routed_seller_id") == seller_id and claim["claim_state"] == "APPROVED":
            raise fail("ERR_SECTION_BLOCKED_BY_OPEN_CLAIM")

    age_days = (clock - section["_opened_dt"]).days
    if age_days < MIN_SECTION_DAYS:
        raise fail("ERR_SECTION_TOO_YOUNG")

    section["section_state"] = "CLOSED"
    section["section_closed_on"] = iso(clock)
    section["_closed_dt"] = clock
    recompute_section(section, clock)
    touch(section, clock)

    seller = store.sellers.get(seller_id)
    if seller is not None:
        seller["latest_score_id"] = section["id"]
        if section["threshold_breached"]:
            seller["suspension_trigger_count"] = seller.get("suspension_trigger_count", 0) + 1
            if seller["onboarding_state"] == "APPROVED":
                seller["onboarding_state"] = "SUSPENDED"
                seller["performance_tier"] = "SUSPENDED"
                touch(seller, clock)
        elif seller["onboarding_state"] == "APPROVED":
            from services.sellers import remap_tier
            remap_tier(seller, clock)
        else:
            touch(seller, clock)
        expo.recompute_exposure_floor(seller_id, clock)
    return section