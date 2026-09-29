"""Pool aggregates, the balance verdict and scrapping (PRD 3.5)."""

from decimal import Decimal

from store import db, find, set_field, touch
from util import dec, round_half_up

MIN_DISTINCT_DONORS = 3
MAX_DISTINCT_DONORS = 5
KCAL_MIN = Decimal("19.00")
KCAL_MAX = Decimal("21.00")
POOL_VOLUME_MIN = 1500
POOL_VOLUME_MAX = 6000

POOL_OPEN_STATES = ("DRAFT", "BALANCED")
POOL_SCRAPPABLE = ("DRAFT", "BALANCED", "COMMITTED")


def components_of(pool_id):
    return [c for c in db.rows("components") if c["pool_id"] == pool_id]


def components_of_donation(donation_id):
    return [c for c in db.rows("components") if c["donation_id"] == donation_id]


def recompute_aggregates(pool):
    """Recompute the pool's three aggregates from its ALLOCATED components only.

    Called on exactly three occasions (PRD 3.5): a component add, a scrap, and a
    recall cascade that voids one of the pool's components.
    """
    included = [c for c in components_of(pool["id"]) if c["status"] == "ALLOCATED"]
    if not included:
        set_field(pool, "distinct_donor_count", 0)
        set_field(pool, "total_volume_ml", 0)
        set_field(pool, "projected_kcal_per_oz", None)
        return
    total = sum(c["allocated_volume_ml"] for c in included)
    numerator = Decimal(0)
    for c in included:
        numerator += dec(c["allocated_volume_ml"]) * dec(c["component_kcal_per_oz"])
    projected = round_half_up(numerator / dec(total), 2)
    donors = set(c["component_donor_id"] for c in included)
    set_field(pool, "distinct_donor_count", len(donors))
    set_field(pool, "total_volume_ml", total)
    set_field(pool, "projected_kcal_per_oz", projected)


def is_balanced(pool):
    projected = pool["projected_kcal_per_oz"]
    if projected is None:
        return False
    return (
        pool["distinct_donor_count"] >= MIN_DISTINCT_DONORS
        and KCAL_MIN <= dec(projected) <= KCAL_MAX
        and POOL_VOLUME_MIN <= pool["total_volume_ml"] <= POOL_VOLUME_MAX
    )


def reevaluate_balance(pool):
    """DRAFT <-> BALANCED oscillation after every component write."""
    if pool["status"] in POOL_OPEN_STATES:
        set_field(pool, "status", "BALANCED" if is_balanced(pool) else "DRAFT")


def recompute_donation_remaining(donation):
    used = sum(
        c["allocated_volume_ml"]
        for c in components_of_donation(donation["id"])
        if c["status"] != "VOIDED"
    )
    remaining = donation["volume_ml"] - used
    if remaining < 0:
        remaining = 0
    set_field(donation, "remaining_ml", remaining)


def recompute_bottled_volume(pool):
    runs = [r for r in db.rows("runs") if r["pool_id"] == pool["id"]]
    run_ids = set(r["id"] for r in runs)
    total = sum(
        lot["total_volume_ml"]
        for lot in db.rows("lots")
        if lot["run_id"] in run_ids and lot["release_status"] != "DISCARDED"
    )
    set_field(pool, "bottled_volume_ml", total)


def scrap_pool(pool):
    """Scrap a pool, returning every still-allocated draw to its donation."""
    for component in components_of(pool["id"]):
        if component["status"] != "ALLOCATED":
            continue
        set_field(component, "status", "VOIDED")
        donation = find("donations", component["donation_id"])
        if donation is not None:
            recompute_donation_remaining(donation)
            if donation["status"] == "ALLOCATED":
                set_field(donation, "status", "ELIGIBLE")
    recompute_aggregates(pool)
    for run in db.rows("runs"):
        if run["pool_id"] == pool["id"] and run["run_status"] in ("SCHEDULED", "IN_PROGRESS"):
            set_field(run, "run_status", "VOIDED")
    set_field(pool, "status", "SCRAPPED")
    touch(pool)
