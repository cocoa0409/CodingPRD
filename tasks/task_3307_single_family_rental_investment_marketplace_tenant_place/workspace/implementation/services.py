"""Domain services: derived fields, calculations, expiry sweeps, cascades."""
from datetime import timedelta

from db import store, _parse_iso, fmt_iso, wall_now_iso
import errors
from helpers import touch, new_id, stamp_new

# ---- constants (SCAFFOLD constants block) ----
EARNEST_MIN_CENTS = 50000
OFFER_TTL_HOURS = 72
MAX_NEGOTIATION_ROUNDS = 5
LATE_GRACE_DAYS = 5
INSPECTION_MAX_AGE_DAYS = 180
REDACTED_VACANCY_UPLIFT_BPS = 300
DAYS_PER_MONTH = 30


# ---- Seller derived fields ----

def recompute_seller(seller_id):
    seller = store.sellers.get(seller_id)
    if not seller:
        return
    count = sum(
        1 for l in store.listings.values()
        if l["seller_id"] == seller_id and l["status"] not in ("SOLD", "WITHDRAWN")
    )
    seller["listed_count"] = count
    if count >= 10:
        seller["bulk_discount_bps"] = 500
    elif count >= 5:
        seller["bulk_discount_bps"] = 300
    elif count >= 2:
        seller["bulk_discount_bps"] = 100
    else:
        seller["bulk_discount_bps"] = 0
    touch(seller)


# ---- Underwriting calculations ----

def compute_underwriting(listing, rent_estimate_cents, vacancy_rate_bps, opex_rate_bps):
    gross = rent_estimate_cents * 12
    disclosure_limited = bool(listing.get("seller_asks_confidential", False))
    if disclosure_limited:
        vac = (gross * (vacancy_rate_bps + REDACTED_VACANCY_UPLIFT_BPS)) // 10000
    else:
        vac = (gross * vacancy_rate_bps) // 10000
    opex = ((gross - vac) * opex_rate_bps) // 10000
    noi = gross - vac - opex
    if listing["listing_kind"] == "PORTFOLIO":
        price_basis = listing["bulk_price_cents"]
    else:
        price_basis = listing["asking_price_cents"]
    yield_bps = (noi * 10000) // price_basis
    return disclosure_limited, noi, yield_bps


# ---- Payment record late flag ----

def compute_late(due_date_iso, paid_date_iso):
    if paid_date_iso is None:
        return False
    due = _parse_iso(due_date_iso)
    paid = _parse_iso(paid_date_iso)
    return paid > due + timedelta(days=LATE_GRACE_DAYS)


# ---- Latest verified inspection report ----

def latest_verified_report(listing_id):
    cands = [
        r for r in store.reports.values()
        if r["listing_id"] == listing_id and r["status"] == "VERIFIED"
    ]
    if not cands:
        return None
    # latest by inspection_date; tie-break created_at DESC
    cands.sort(key=lambda r: (_parse_iso(r["inspection_date"]), r.get("created_at", "")))
    return cands[-1]


# ---- Offer expiry sweep ----

def offer_expiry_sweep():
    now = store.clock
    for offer in list(store.offers.values()):
        if offer["status"] == "SUBMITTED":
            exp = offer.get("expires_at")
            if exp and _parse_iso(exp) <= now:
                offer["status"] = "EXPIRED"
                touch(offer)
                _maybe_listing_fall_back(offer["listing_id"])


def guarantee_expiry_sweep():
    now = store.clock
    for g in list(store.guarantees.values()):
        if g["status"] == "ACTIVE":
            listing = store.listings.get(g["listing_id"])
            sold_at = listing.get("sold_at") if listing else None
            if sold_at:
                window_end = _parse_iso(sold_at) + timedelta(days=g["coverage_months"] * DAYS_PER_MONTH)
                if now > window_end:
                    g["status"] = "EXPIRED"
                    touch(g)


def run_sweeps():
    offer_expiry_sweep()
    guarantee_expiry_sweep()


# ---- Listing fallback: OFFER_PENDING -> LISTED when no live offers ----

def _maybe_listing_fall_back(listing_id):
    listing = store.listings.get(listing_id)
    if not listing or listing["status"] != "OFFER_PENDING":
        return
    live = any(
        o["listing_id"] == listing_id and o["status"] in ("SUBMITTED", "COUNTERED")
        for o in store.offers.values()
    )
    accepted = any(
        o["listing_id"] == listing_id and o["status"] == "ACCEPTED"
        for o in store.offers.values()
    )
    if not live and not accepted:
        listing["status"] = "LISTED"
        touch(listing)


# ---- Escrow closing / cancellation cascades ----

def _resolve_lease_for_fee(listing_id):
    """Lease in {ACTIVE, ASSIGNED}; if several, max monthly_rent_cents, tie created_at ASC."""
    cands = [
        l for l in store.leases.values()
        if l["listing_id"] == listing_id and l["status"] in ("ACTIVE", "ASSIGNED")
    ]
    if not cands:
        return None
    cands.sort(key=lambda l: (-l["monthly_rent_cents"], l.get("created_at", "")))
    return cands[0]


def escrow_close_cascade(escrow):
    offer = store.offers[escrow["offer_id"]]
    listing = store.listings[offer["listing_id"]]
    listing["status"] = "SOLD"
    listing["sold_at"] = fmt_iso(store.clock)
    touch(listing)
    # Lease ACTIVE -> ASSIGNED (continuity)
    for lease in store.leases.values():
        if lease["listing_id"] == listing["id"] and lease["status"] == "ACTIVE":
            lease["status"] = "ASSIGNED"
            touch(lease)
    # Referrals {REFERRED, ACCEPTED} -> ONBOARDED; fee computed
    for ref in store.referrals.values():
        if ref["listing_id"] == listing["id"] and ref["status"] in ("REFERRED", "ACCEPTED"):
            ref["status"] = "ONBOARDED"
            pm = store.pms.get(ref["property_manager_id"])
            lease = _resolve_lease_for_fee(listing["id"])
            annual = (lease["monthly_rent_cents"] * 12) if lease else 0
            ref["onboarding_fee_cents"] = (annual * pm["onboarding_fee_bps"]) // 10000 if pm else 0
            ref["lease_continuity_confirmed"] = any(
                l["listing_id"] == listing["id"] and l["status"] == "ASSIGNED"
                for l in store.leases.values()
            )
            touch(ref)
    # Guarantee ISSUED -> ACTIVE
    for g in store.guarantees.values():
        if g["listing_id"] == listing["id"] and g["status"] == "ISSUED":
            g["status"] = "ACTIVE"
            touch(g)
    recompute_seller(listing["seller_id"])


def escrow_cancel_cascade(escrow):
    offer = store.offers[escrow["offer_id"]]
    listing = store.listings[offer["listing_id"]]
    if listing["status"] == "UNDER_CONTRACT":
        listing["status"] = "LISTED"
        touch(listing)
    for g in store.guarantees.values():
        if g["listing_id"] == listing["id"] and g["status"] in ("ISSUED", "ACTIVE"):
            g["status"] = "VOID"
            touch(g)


# ---- Offer acceptance cascade ----

def offer_accept_cascade(offer):
    listing = store.listings[offer["listing_id"]]
    listing["status"] = "UNDER_CONTRACT"
    touch(listing)
    # Sibling offers {SUBMITTED, COUNTERED} -> EXPIRED
    for o in store.offers.values():
        if o["listing_id"] == listing["id"] and o["id"] != offer["id"] and o["status"] in ("SUBMITTED", "COUNTERED"):
            o["status"] = "EXPIRED"
            touch(o)
    # Escrow created OPENED
    escrow = stamp_new({
        "id": new_id(),
        "offer_id": offer["id"],
        "escrow_officer_name": None,
        "status": "OPENED",
        "remote_signing_required": bool(offer["is_out_of_state"]),
        "signed_at": None,
        "funded_amount_cents": None,
    })
    store.escrows[escrow["id"]] = escrow
    return escrow


# ---- Listing withdrawal cascade (from LISTED / OFFER_PENDING) ----

def listing_withdraw_cascade(listing):
    for o in store.offers.values():
        if o["listing_id"] == listing["id"] and o["status"] in ("SUBMITTED", "COUNTERED"):
            o["status"] = "WITHDRAWN"
            touch(o)
    for g in store.guarantees.values():
        if g["listing_id"] == listing["id"] and g["status"] in ("ISSUED", "ACTIVE"):
            g["status"] = "VOID"
            touch(g)
    recompute_seller(listing["seller_id"])


# ---- Guarantee claim amount ----

def _lease_for_claim(listing_id):
    """ASSIGNED lease; else most recent TERMINATED (max lease_end, tie created_at DESC)."""
    assigned = [l for l in store.leases.values()
                if l["listing_id"] == listing_id and l["status"] == "ASSIGNED"]
    if assigned:
        assigned.sort(key=lambda l: l.get("created_at", ""))
        return assigned[0]
    term = [l for l in store.leases.values()
            if l["listing_id"] == listing_id and l["status"] == "TERMINATED"]
    if term:
        term.sort(key=lambda l: (_parse_iso(l["lease_end"]), l.get("created_at", "")))
        return term[-1]
    return None


def compute_claim_amount(guarantee, listing):
    """Raises ERR_GUARANTEE_NOT_CLAIMABLE when no lease history exists."""
    sold_at = _parse_iso(listing["sold_at"])
    claimed = store.clock
    lease = _lease_for_claim(listing["id"])
    if lease is None:
        raise errors.not_claimable("No lease history exists to price the claim")
    if guarantee["guarantee_kind"] == "VACANCY":
        elapsed_days = (claimed - sold_at).days
        elapsed_months = elapsed_days // DAYS_PER_MONTH
        payable_months = max(0, guarantee["coverage_months"] - elapsed_months)
        return lease["monthly_rent_cents"] * payable_months
    # LEASE_UP
    lease_ids = {l["id"] for l in store.leases.values() if l["listing_id"] == listing["id"]}
    total = 0
    for p in store.payments.values():
        if p["lease_id"] not in lease_ids:
            continue
        due = _parse_iso(p["due_date"])
        if sold_at <= due <= claimed and (p.get("paid_date") is None or p.get("late")):
            total += p["amount_cents"]
    cap = lease["monthly_rent_cents"] * guarantee["coverage_months"]
    return min(total, cap)
