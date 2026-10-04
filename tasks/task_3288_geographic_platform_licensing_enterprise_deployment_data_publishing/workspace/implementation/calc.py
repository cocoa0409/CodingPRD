"""Calculation helpers per PRD §2.7, §2.8, §3.7 and scaffold §1.3."""
from decimal import Decimal, ROUND_HALF_UP

import store

TIERS = {
    "GEOCODE": [
        (1, 100, 4),
        (101, 1000, 3),
        (1001, 999999, 2),
    ],
    "ANALYSIS": [
        (1, 10, 40),
        (11, 100, 30),
        (101, 999999, 20),
    ],
    "STORAGE": [
        (1, 999999, 1),
    ],
    "TILE_QUERY": [
        (1, 10000, 1),
        (10001, 999999, 1),
    ],
    "ROUTING": [
        (1, 50, 8),
        (51, 999999, 5),
    ],
}

SERVICE_KINDS = {"GEOCODE", "ANALYSIS", "STORAGE", "TILE_QUERY", "ROUTING"}

LATE_FEE_PER_PERIOD = Decimal("0.1")
BYTES_PER_STORAGE_UNIT = 104857600


def round_half_up(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier_slices(service_kind, requested_units):
    """Yield (in_tier, rate) per tier for the given unit count."""
    remaining = requested_units
    for tmin, tmax, rate in TIERS[service_kind]:
        width = tmax - tmin + 1
        in_tier = min(remaining, width)
        if in_tier <= 0:
            continue
        yield in_tier, rate
        remaining -= in_tier
        if remaining <= 0:
            break


def extension_rate(org_id, extension_code):
    """additional_credit_rate_per_op for an ACTIVE extension grant of the org."""
    if not extension_code:
        return Decimal(0)
    for eg in store.extension_grants.values():
        if eg["status"] != "ACTIVE" or eg["extension_code"] != extension_code:
            continue
        grant = store.license_grants.get(eg["license_grant_id"])
        if not grant or grant["status"] != "ACTIVE":
            continue
        if grant["organization_id"] != org_id:
            continue
        product = store.license_products.get(grant["license_product_id"])
        if not product:
            continue
        for mod in product.get("extension_modules", []):
            if mod.get("extension_code") == extension_code:
                return Decimal(str(mod.get("additional_credit_rate_per_op", 0)))
    return Decimal(0)


def provisional_credits(service_kind, requested_units, ext_rate):
    """Provisional variant: round half up per tier, then sum."""
    total = 0
    for in_tier, rate in tier_slices(service_kind, requested_units):
        total += round_half_up(Decimal(in_tier) * (Decimal(rate) + ext_rate))
    return total


def settled_credits_calc(service_kind, requested_units, ext_rate, periods_pending):
    """Chronological variant: sum raw, apply late fee, round half up once."""
    raw = Decimal(0)
    for in_tier, rate in tier_slices(service_kind, requested_units):
        raw += Decimal(in_tier) * (Decimal(rate) + ext_rate)
    factor = Decimal(1) + LATE_FEE_PER_PERIOD * Decimal(periods_pending)
    return round_half_up(raw * factor)


def pool_available(pool):
    return pool["capacity_credits"] - pool["consumed_credits"] - pool["reserved_credits"]


def compute_posture(pool):
    available = pool_available(pool)
    if available < 0:
        return "OVERDRAWN"
    if available == 0:
        return "EXHAUSTED"
    if available < pool["low_credit_threshold_credits"]:
        return "LOW_CREDIT"
    return "OK"


def refresh_pool(pool):
    """Recompute posture and mirror credit_balance onto the org."""
    pool["posture"] = compute_posture(pool)
    org = store.orgs.get(pool["organization_id"])
    if org is not None:
        org["credit_balance"] = pool_available(pool)


def storage_units(storage_bytes):
    if storage_bytes <= 0:
        return 0
    return -(-storage_bytes // BYTES_PER_STORAGE_UNIT)


def marginal_overage_fee_cents(overage_seat_number):
    """Marginal tier fee for overage seat number n (1-based)."""
    if overage_seat_number <= 5:
        return 250
    if overage_seat_number <= 20:
        return 400
    return 700


def sustained_overage_fee_cents(sustained_seats):
    """Average-rate form over ALL sustained seats."""
    if sustained_seats <= 0:
        return 0
    tier1 = min(sustained_seats, 5)
    tier2 = min(max(sustained_seats - 5, 0), 15)
    tier3 = max(sustained_seats - 20, 0)
    return tier1 * 250 + tier2 * 400 + tier3 * 700


PER_SEAT_BURN = {"NAMED_USER": 2, "CONCURRENT_USE": 5, "DEPLOYMENT_SERVER": 0}


def credit_burn_projection(org_id, periods, mode):
    org = store.orgs[org_id]
    pool = store.pool_for_org(org_id)
    if mode == "chronological":
        total = Decimal(0)
        batches = sorted(
            (b for b in store.credit_batches.values()
             if b["organization_id"] == org_id and b["status"] == "SETTLED"),
            key=lambda b: b["created_at"],
        )
        for b in batches:
            periods_alive = max(1, org["current_period_index"] - b.get("creation_period_index", 0))
            total += Decimal(b.get("settled_credits", 0)) * Decimal(periods) / Decimal(periods_alive)
        return round_half_up(total)
    # forward (default)
    projected = 0
    if pool is not None:
        projected += pool["consumed_credits"] + pool["reserved_credits"]
    per_period = 0
    for g in store.license_grants.values():
        if g["organization_id"] != org_id or g["status"] != "ACTIVE":
            continue
        product = store.license_products.get(g["license_product_id"])
        if not product:
            continue
        per_period += g["seats_in_use"] * PER_SEAT_BURN.get(product["license_kind"], 0)
    return projected + periods * per_period
