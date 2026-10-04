"""Freight estimate and subsidy arithmetic (PRD 3.6, integer cents)."""

FREIGHT_CENTS_PER_MILE = 185
NATIONAL_TRANSPORT_PCT = 30
REGIONAL_TRANSPORT_PCT = 55
LOCAL_TRANSPORT_PCT = 75
NONE_TRANSPORT_PCT = 100
REMOTE_DISTANCE_THRESHOLD_MILES = 400
REMOTE_UPLIFT_PCT = 15
MAX_SUBSIDY_PER_LOAD_CENTS = 250000
MIN_SUBSIDY_CENTS = 5000

TRANSPORT_PCT = {
    "NATIONAL": NATIONAL_TRANSPORT_PCT,
    "REGIONAL": REGIONAL_TRANSPORT_PCT,
    "LOCAL": LOCAL_TRANSPORT_PCT,
    "NONE": NONE_TRANSPORT_PCT,
}


def _ceil_pct(base, pct):
    """ceil(base * pct / 100) in integer cents."""
    return -((-base * pct) // 100)


def base_cents(load, detour_miles=0):
    return (int(load["distance_miles"]) + int(detour_miles or 0)) * FREIGHT_CENTS_PER_MILE


def transport_share_pct(member, can_self_transport):
    if can_self_transport:
        return 0
    return TRANSPORT_PCT.get(member["transport_ability"], NONE_TRANSPORT_PCT)


def compute_subsidy(load, member, can_self_transport, detour_miles=0, pool_remaining_cents=0):
    """Return (subsidy_cents, base_cents, due_cents) for the final/provisional pass.

    Per-component ceil, then sum, then the nested min cap, then the minimum
    grantable collapse.
    """
    base = base_cents(load, detour_miles)
    raw = _ceil_pct(base, transport_share_pct(member, can_self_transport))
    uplift = 0
    if (not can_self_transport
            and int(load["distance_miles"]) >= REMOTE_DISTANCE_THRESHOLD_MILES
            and member["transport_ability"] in ("NONE", "LOCAL")):
        uplift = _ceil_pct(base, REMOTE_UPLIFT_PCT)
    subsidy = min(raw + uplift, int(pool_remaining_cents), MAX_SUBSIDY_PER_LOAD_CENTS)
    if subsidy < MIN_SUBSIDY_CENTS:
        subsidy = 0
    return subsidy, base, base - subsidy


def pool_remaining(agreement):
    return int(agreement["freight_subsidy_pool_cents"]) - int(agreement["freight_subsidy_used_cents"])
