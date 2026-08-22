"""Record lifecycle helpers, derived quantities, and the cascades of PRD 2.8."""



import clock
from db import db, new_id, next_seq

from services import calc

CLOSED_LOT_STATUSES = ("RELEASED", "REJECTED", "SCRAPPED", "RECALLED")
NON_TERMINAL_CYCLE_STATUSES = (
    "PLANNED", "LOADING", "READY", "RUNNING", "COMPLETED", "DOSIMETRY_REVIEW",
)
TERMINAL_SCHEDULING_STATUSES = ("CANCELLED", "DOSE_CONFORMING", "DOSE_DEVIATION")


# ---------------------------------------------------------------------------
# record lifecycle
# ---------------------------------------------------------------------------
def new_record(fields, common_fields=True):
    record = dict(fields)
    record["id"] = new_id()
    record["created_at"] = clock.now()
    if common_fields:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """A persisted mutation: refresh updated_at and advance version by one."""
    record["updated_at"] = clock.now()
    record["version"] = record["version"] + 1


def by_seq(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# relationship lookups
# ---------------------------------------------------------------------------
def positions_of_cycle(cycle_id):
    return by_seq([p for p in db.load_positions.values() if p["cycle_id"] == cycle_id])


def positions_of_lot(lot_id):
    return by_seq([p for p in db.load_positions.values() if p["lot_id"] == lot_id])


def indicators_of_position(position_id):
    return by_seq(
        [i for i in db.indicators.values() if i["load_position_id"] == position_id]
    )


def indicators_of_cycle(cycle_id):
    position_ids = {p["id"] for p in db.load_positions.values()
                    if p["cycle_id"] == cycle_id}
    return by_seq(
        [i for i in db.indicators.values() if i["load_position_id"] in position_ids]
    )


def lots_of_cycle(cycle_id):
    """Distinct lots referenced by the cycle's load map, in the pinned order:
    ascending LoadPosition.created_at, ties broken by position_index ascending."""
    positions = sorted(
        positions_of_cycle(cycle_id),
        key=lambda p: (clock.truncate_ms(p["created_at"]), p["position_index"], p["_seq"]),
    )
    seen = []
    seen_ids = set()
    for position in positions:
        if position["lot_id"] in seen_ids:
            continue
        seen_ids.add(position["lot_id"])
        lot = db.lots.get(position["lot_id"])
        if lot is not None:
            seen.append(lot)
    return seen


def chamber_of_cycle(cycle):
    return db.chambers.get(cycle["chamber_id"])


def recipe_of_cycle(cycle):
    return db.recipes.get(cycle["recipe_id"])


def permit_of_chamber(chamber):
    return db.permits.get(chamber["permit_id"])


def product_of_lot(lot):
    return db.products.get(lot["product_id"])


def customer_of_lot(lot):
    return db.customers.get(lot["customer_id"])


# ---------------------------------------------------------------------------
# governing_cycle_selector (PRD 3.8)
# ---------------------------------------------------------------------------
def governing_cycle(lot):
    candidates = [p for p in db.load_positions.values() if p["lot_id"] == lot["id"]]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["position_index"], p["_seq"]))
    candidates.sort(key=lambda p: clock.truncate_ms(p["created_at"]), reverse=True)
    return db.cycles.get(candidates[0]["cycle_id"])


# ---------------------------------------------------------------------------
# conserved quantities (PRD 2.9)
# ---------------------------------------------------------------------------
def recompute_cycle_load(cycle):
    positions = positions_of_cycle(cycle["id"])
    cycle["loaded_pallet_count"] = sum(p["pallet_count"] for p in positions)
    rows = []
    for position in positions:
        lot = db.lots.get(position["lot_id"])
        product = db.products.get(lot["product_id"]) if lot else None
        if product is None:
            continue
        rows.append((position["pallet_count"],
                     product["pallet_mass_kg"],
                     product["pallet_volume_m3"]))
    cycle["load_density_g_per_cm3"] = calc.cycle_load_density(rows)


def refresh_lot_pallets(lot):
    staged = sum(p["pallet_count"] for p in db.load_positions.values()
                 if p["lot_id"] == lot["id"])
    lot["staged_pallet_count"] = staged
    lot["available_pallet_count"] = lot["total_pallet_count"] - staged


def recompute_open_lot_count(customer_id):
    customer = db.customers.get(customer_id)
    if customer is None:
        return
    count = sum(
        1 for lot in db.lots.values()
        if lot["customer_id"] == customer_id and lot["status"] not in CLOSED_LOT_STATUSES
    )
    if customer["open_lot_count"] != count:
        customer["open_lot_count"] = count
        touch(customer)


# ---------------------------------------------------------------------------
# qualifications
# ---------------------------------------------------------------------------
def lazy_audit_due(qualification):
    """QUALIFIED -> AUDIT_DUE / CONDITIONAL -> AUDIT_DUE on the logical clock."""
    if qualification["status"] not in ("QUALIFIED", "CONDITIONAL"):
        return
    due = qualification.get("next_audit_due_at")
    if due is not None and clock.now() >= due:
        qualification["status"] = "AUDIT_DUE"
        touch(qualification)


def qualifications_for_pair(product_id, recipe_id):
    return by_seq([
        q for q in db.qualifications.values()
        if q["product_id"] == product_id and q["recipe_id"] == recipe_id
    ])


def current_qualification(product_id, recipe_id):
    """Validation priority 60.  Lapsed qualifications are moved lazily first."""
    matches = qualifications_for_pair(product_id, recipe_id)
    for qualification in matches:
        lazy_audit_due(qualification)
    for qualification in matches:
        if qualification["status"] in ("QUALIFIED", "CONDITIONAL"):
            return qualification
    return None


# ---------------------------------------------------------------------------
# load-map removal (the compensating action of PRD 2.9)
# ---------------------------------------------------------------------------
def delete_position_row(position, cycle):
    """Hard-delete one slot and recompute the parent cycle's aggregates.

    Lot-side bookkeeping is left to the caller so that a lot touched several
    times by one operation still advances its version exactly once.
    """
    db.load_positions.pop(position["id"], None)
    recompute_cycle_load(cycle)


def settle_lot_after_removal(lot, running_abort=False):
    """Refresh the pallet ledger of a lot whose slots were removed and walk its
    status back.  Advances the lot's version exactly once."""
    refresh_lot_pallets(lot)
    if running_abort and lot["status"] == "IN_PROCESS":
        lot["status"] = "RECEIVED"
    elif lot["status"] == "STAGED" and not positions_of_lot(lot["id"]):
        lot["status"] = "RECEIVED"
    touch(lot)
    recompute_open_lot_count(lot["customer_id"])


def unwind_cycle_state(cycle):
    """READY -> LOADING, or LOADING -> PLANNED when no positions remain."""
    remaining = positions_of_cycle(cycle["id"])
    if not remaining:
        if cycle["status"] in ("LOADING", "READY"):
            cycle["status"] = "PLANNED"
    else:
        if cycle["status"] == "READY":
            cycle["status"] = "LOADING"


# ---------------------------------------------------------------------------
# CASCADE A hops 3 and 4 (PRD 3.7)
# ---------------------------------------------------------------------------
def deviation_qualification_cascade(quarantined_lots, recipe_id):
    """Hop three then hop four."""
    audit_due_products = []
    for lot in quarantined_lots:
        for qualification in qualifications_for_pair(lot["product_id"], recipe_id):
            if qualification["status"] in ("QUALIFIED", "CONDITIONAL"):
                qualification["status"] = "AUDIT_DUE"
                qualification["next_audit_due_at"] = clock.now()
                touch(qualification)
                if qualification["product_id"] not in audit_due_products:
                    audit_due_products.append(qualification["product_id"])

    quarantined_ids = {lot["id"] for lot in quarantined_lots}
    for product_id in audit_due_products:
        siblings = by_seq([
            lot for lot in db.lots.values()
            if lot["product_id"] == product_id
            and lot["id"] not in quarantined_ids
            and lot["status"] == "STAGED"
        ])
        for sibling in siblings:
            sibling["schedulable"] = False
            sibling["status"] = "RECEIVED"
            for position in positions_of_lot(sibling["id"]):
                cycle = db.cycles.get(position["cycle_id"])
                if cycle is None or cycle["status"] not in ("PLANNED", "LOADING", "READY"):
                    continue
                delete_position_row(position, cycle)
                unwind_cycle_state(cycle)
                touch(cycle)
            refresh_lot_pallets(sibling)
            touch(sibling)
            recompute_open_lot_count(sibling["customer_id"])
