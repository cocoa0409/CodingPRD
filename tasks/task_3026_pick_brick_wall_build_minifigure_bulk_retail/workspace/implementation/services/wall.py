"""The wall: fill percentage, bin status, restock, rotation and shrinkage."""

from db import (
    EMPTY_BACKFILL_PCT,
    FILL_EMPTY_PCT,
    FILL_LOW_PCT,
    RESTOCK_BATCH_SIZE,
    SHRINKAGE_ALERT_BPS,
    db,
)
from services.core import (
    apply_freeze_consequences,
    bins_of_store,
    recompute_store,
    rh,
    rh1,
    touch,
)


def recompute_bin(bin_record):
    """wall_bin_fill_pct -- boundaries are strictly less-than, and RETIRED is sticky."""
    fill = rh1(bin_record["bin_mass_grams"] * 100.0 / bin_record["bin_capacity_grams"])
    bin_record["fill_pct"] = fill
    previous = bin_record.get("status")
    if previous == "RETIRED":
        # A retired bin is not revived by a recalculated percentage; it returns
        # to the wall only through the rotation procedure.
        return bin_record
    if fill < FILL_EMPTY_PCT:
        bin_record["status"] = "EMPTY"
    elif fill < FILL_LOW_PCT:
        bin_record["status"] = "LOW"
    else:
        bin_record["status"] = "OPEN"
    return bin_record


def mutate_bin(bin_record, delta):
    """Apply a mass delta, re-derive status, then the store's engine mass and posture."""
    bin_record["bin_mass_grams"] += delta
    if bin_record["bin_mass_grams"] < 0:
        bin_record["bin_mass_grams"] -= delta
        from errors import fail
        fail("ERR_CONSTRAINT_VIOLATION", "A bin mass may not be driven negative.")
    recompute_bin(bin_record)
    touch(bin_record)
    store = db().stores.get(bin_record["store_id"])
    if store is not None:
        recompute_store(store)
        apply_freeze_consequences(store)
        touch(store)
    return bin_record


def element_bin_occupied(element_id):
    return any(b["element_id"] == element_id and b["bin_mass_grams"] > 0
               for b in db().wall_bins.values())


def element_on_wall(store_id, element_id):
    return any(b["store_id"] == store_id
               and b["element_id"] == element_id
               and b["bin_mass_grams"] > 0
               for b in db().wall_bins.values())


def activate_element_if_loaded(element):
    """An element becomes ACTIVE the first time a bin loading it holds mass."""
    if element["status"] == "PENDING_CATALOG":
        element["status"] = "ACTIVE"


def rotation_rank_parts(bin_record):
    priority = 0 if bin_record["status"] == "EMPTY" else 1
    return (priority, bin_record["fill_pct"],
            -float(bin_record.get("depletion_rate_pct_per_day") or 0.0),
            bin_record["created_at"])


def run_rotation(store_id, bin_ids):
    """wall_depletion_restock -- the selector policy for POST /stores/wall-bins/rotate."""
    supplied = set(bin_ids or [])
    candidates = [b for b in bins_of_store(store_id)
                  if b["status"] in ("EMPTY", "LOW") and b["id"] in supplied]
    candidates.sort(key=rotation_rank_parts)
    restock_set = candidates[:RESTOCK_BATCH_SIZE]
    if not restock_set:
        return []

    retained = [b for b in bins_of_store(store_id) if b["status"] == "OPEN"]
    retained.sort(key=lambda b: (-b["fill_pct"], b["created_at"]))
    retiring = retained[:len(restock_set)]

    store = db().stores.get(store_id)
    run_index = store["last_event_run_index"] if store else 0

    # Each retiring bin hands its element to the restock row at the same index.
    for index, target in enumerate(restock_set):
        if index < len(retiring):
            donor = retiring[index]
            target["element_id"] = donor["element_id"]
            donor["status"] = "RETIRED"
            touch(donor)
        if target["bin_mass_grams"] == 0:
            capacity = target["bin_capacity_grams"]
            target["bin_mass_grams"] = rh(float(capacity) * float(EMPTY_BACKFILL_PCT))
        target["status"] = "OPEN"
        target["fill_pct"] = rh1(target["bin_mass_grams"] * 100.0 / target["bin_capacity_grams"])
        target["last_restock_index"] = run_index
        touch(target)
        activate_element_if_loaded(db().elements.get(target["element_id"]))

    if store is not None:
        recompute_store(store)
        apply_freeze_consequences(store)
        touch(store)
    return restock_set


def order_variance(order_id):
    """one order's variance_grams: declared mass minus the sum of its draws."""
    order = db().fusion_orders.get(order_id)
    if order is None:
        return 0
    drawn = sum(a["allocation_grams"] for a in db().fusion_allocations.values()
                if a["fusion_order_id"] == order_id)
    return order["declared_mass_grams"] - drawn


def recompute_shrinkage(store):
    """store_shrinkage_basis_points -- over VOID and CLOSED orders only."""
    included = [o for o in db().fusion_orders.values()
                if o["store_id"] == store["id"] and o["status"] in ("VOID", "CLOSED")]
    total_declared = sum(o["declared_mass_grams"] for o in included)
    if total_declared == 0:
        store["shrinkage_basis_points"] = 0
    else:
        total_variance = sum(order_variance(o["id"]) for o in included)
        store["shrinkage_basis_points"] = rh(
            total_variance * 10000 / total_declared)
    return store


def shrinkage_alert(store):
    return store["shrinkage_basis_points"] >= SHRINKAGE_ALERT_BPS