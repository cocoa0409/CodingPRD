"""Re-derivation of every computed field.

PRD §2.5 is load-bearing here: "Because a derived field is still a mutation, a
recomputation of a computed field updates updated_at and increments version
exactly as a client-supplied edit would." So the refresh helpers below go
through touch() exactly as a client edit would.

Because computed fields depend on live configuration (a price point's shelf
price or ratio, an item's pack sizes, a vendor's flag) as well as on the rows
that own them, every configuration mutation funnels through
refresh_after_config_change(), which re-derives vendors, price points, season
windows, items, containers, stores and audits. Re-derivation is signature
gated so unchanged rows are not mutated (an untouched row must not have its
version bumped).
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from db import db
from common import serialize, touch

CENT = Decimal("1")
MILLI = Decimal("0.001")

MISMATCH_TOLERANCE_PCT = Decimal("0.052")
TARGET_MARGIN_BUFFER_PCT = Decimal("0.12")
COVERAGE_TOLERANCE_PCT = Decimal("-0.50")
SHORTFALL_FLOOR_AISLES = 1
BASE_DECK_ALLOWANCE_CASES = 1

# Only allocation lines on items in these states draw container units (PRD §3.7).
DRAWING_ITEM_STATES = ("PRICE_ASSIGNED", "COST_PENDING", "ACTIVE")
TERMINAL_LINE_STATES = ("RELEASED", "SHORTED", "REVERSED")
EXECUTED_RESET = "EXECUTED"
PROJECTED_RESET_STATES = ("PLANNED", "EXECUTING")


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------

def round_half_up(value, places):
    """Round exactly HALF UP (not Python's banker's rounding)."""
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def floor_at_cent(value):
    """Floor at the cent — the cost-ceiling narrowing (PRD §3.5).

    PRD §3.5 names the cent rounding "half down". On a cent-indexed value that
    phrase denotes truncating the sub-cent decimals (a cent cannot be halved
    downward to the next cent), i.e. the integral cent at or below the exact
    rational — a true floor. This is the narrowing the PRD's own worked
    examples use: floor(300 * 0.40 * 0.88) == floor(105.6) == 105 and
    floor(400 * 0.35 * 0.88) == floor(123.2) == 123. Decimal.quantize with
    ROUND_HALF_DOWN would instead round 105.6 and 123.2 *up* to 106 and 124,
    which is not a floor at all.
    """
    return Decimal(value).quantize(CENT, rounding=ROUND_FLOOR)


def dec(value):
    return Decimal(str(value)) if not isinstance(value, Decimal) else value


# ---------------------------------------------------------------------------
# Item-derived scalars
# ---------------------------------------------------------------------------

def compute_broken_case_allowance(item):
    return (dec(item["units_per_case"]) * dec(item["sqft_per_unit"])) > dec(item["shelf_package_capacity"])


def compute_is_shelf_overflow(item):
    return (dec(item["on_hand_units"]) * dec(item["sqft_per_unit"])) > dec(item["shelf_package_capacity"])


def item_history(item_id):
    return [r for r in db.landed_costs.values() if r["item_id"] == item_id]


def current_cost_row(item_id):
    rows = item_history(item_id)
    if not rows:
        return None
    return max(rows, key=lambda r: r["effective_sequence"])


def compute_landed_cost_cents(item):
    row = current_cost_row(item["id"])
    return 0 if row is None else int(row["applied_amount_cents"])


def compute_net_contribution(item):
    return int(item["unit_retail_cents"]) - int(item["landed_cost_cents"]) - int(item["variable_store_cost_cents"])


def compute_break_even(item):
    """Pinned order: total_landed_cost_cents, then unit_margin_cents, then branch."""
    total_landed_cost_cents = int(item["landed_cost_cents"]) * int(item["units_per_case"]) + int(item["fixed_store_handling_cents"])
    unit_margin_cents = int(item["unit_retail_cents"]) - int(item["variable_store_cost_cents"])

    if item["landed_cost_cents"] == 0 and not item_history(item["id"]):
        return 0, "PRICE_PENDING"
    if unit_margin_cents <= 0:
        return 0, "DIVERGENCE_OR_ZERO_MARGIN"

    ratio = Decimal(total_landed_cost_cents) / Decimal(unit_margin_cents)
    units = int(ratio.to_integral_value(rounding="ROUND_CEILING"))
    return units, "CONVERGENCE"


def unit_shelf_capacity(item):
    return int(dec(item["shelf_package_capacity"]) / dec(item["sqft_per_unit"]))


def capacity_ceiling(item):
    base = unit_shelf_capacity(item)
    if item["broken_case_allowance"]:
        return base + int(item["units_per_case"])
    return base


def item_has_active_pack(item):
    for program in db.pack_programs.values():
        if (
            program["vendor_id"] == item["sourcing_vendor_id"]
            and program["price_point_id"] == item["price_point_id"]
            and program["status"] == "ACTIVE"
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Signature-gated item derivation
# ---------------------------------------------------------------------------

def _dependency_signature(item):
    pp = db.price_points.get(item["price_point_id"]) if item["price_point_id"] else None
    packing = []
    for program in db.pack_programs.values():
        if program["vendor_id"] == item["sourcing_vendor_id"] and program["price_point_id"] == item["price_point_id"]:
            packing.append((program["id"], program["status"]))
    history = []
    for row in item_history(item["id"]):
        history.append((row["id"], row["applied_amount_cents"], row["effective_sequence"]))
    return (
        item["id"],
        item["price_point_id"],
        item["unit_retail_cents"],
        item["variable_store_cost_cents"],
        item["units_per_case"],
        item["fixed_store_handling_cents"],
        item["sqft_per_unit"],
        item["shelf_package_capacity"],
        item["on_hand_units"],
        None if pp is None else (pp["shelf_price_cents"], pp["target_landed_cost_ratio"]),
        tuple(sorted(packing)),
        tuple(sorted(history)),
        item.get("status"),
    )


def derive_item(item, mint=True, partial_create=False):
    """Re-derive every computed field on an Item.

    `mint=False` is the creation path: the row is settled with its true
    derived values while still reporting the initial version, so registering
    an item does not leave it looking already-modified (PRD §2.5 — version
    starts at its initial value and increments on every modification).

    `partial_create` suppresses a DELETE_REVIEW drop while the item is still
    being denominated — at that instant its price-point binding does not
    exist yet, so it must not be judged as a losing item.
    """
    broken = compute_broken_case_allowance(item)
    overflow = compute_is_shelf_overflow(item)
    landed = compute_landed_cost_cents(item)
    item["landed_cost_cents"] = landed
    item["broken_case_allowance"] = broken
    item["is_shelf_overflow"] = overflow
    net = compute_net_contribution(item)
    status = item.get("status")
    if not partial_create:
        # PRD §3.3/§3.4 — the cost state follows the contribution the current cost
        # row produces, in both directions. §3.4 makes COST_PENDING → DELETE_REVIEW
        # a system transition, and DELETE_REVIEW's only forward edge is → ACTIVE
        # (§3.4: "Choosing `RETAIN` returns the item to `ACTIVE`"), so once the
        # vendor revises the cost back to a non-negative contribution the recovery
        # is the same automatic re-evaluation that queued it. COST_PENDING is never
        # re-entered from DELETE_REVIEW, which is why the explicit activation step
        # is never required again for a recovered item.
        if status in ("COST_PENDING", "PRICE_ASSIGNED") and net < 0 and not item_has_active_pack(item):
            item["status"] = "DELETE_REVIEW"
        elif status == "DELETE_REVIEW" and net >= 0:
            item["status"] = "ACTIVE"
    break_even, regime = compute_break_even(item)
    if item.get("status") == "DELETE_REVIEW":
        # PRD §3.4 — the DELETE_REVIEW drop is not free of consequences for the
        # item's own derived numbers: break_even_units is set to 0 in that
        # regime. The regime label itself still follows §3.3's unit-margin
        # conditions, which are the ones the break-even read reports.
        break_even = 0
    item["net_contribution_cents_per_unit"] = net
    item["break_even_units"] = break_even
    item["break_even_regime"] = regime

    signature = _dependency_signature(item)
    if not mint:
        item["__sig"] = signature
        return False
    if item.get("__sig") == signature:
        return False
    item["__sig"] = signature
    touch(item)
    return True


def apply_item_state_cascade(item, net_contribution, pre_status=None):
    """The landed-cost side-effect branch (PRD §3.4).

    Called after the new cost row has already been recorded and derive_item has
    re-derived the numbers. ``pre_status`` is the item's state before the write,
    because derive_item has by now already applied the automatic
    COST_PENDING/PRICE_ASSIGNED → DELETE_REVIEW drop and the DELETE_REVIEW →
    ACTIVE recovery. The paths are:

      * a DELETE_REVIEW item re-applying a cost is decided entirely by
        derive_item: a non-negative contribution recovers it to ACTIVE, and a
        still-negative one leaves it queued. Nothing further is forced here.
      * leaving a cost-bearing state with a negative contribution and no curing
        pack lands in DELETE_REVIEW;
      * leaving a cost-bearing state with a negative contribution while an
        ACTIVE pack cures the item stays in COST_PENDING and reports the loss;
      * otherwise the item simply stays COST_PENDING awaiting activation.

    Returns the error id to raise on the response, if any.
    """
    if pre_status == "DELETE_REVIEW":
        return None
    if net_contribution < 0 and not item_has_active_pack(item):
        item["status"] = "DELETE_REVIEW"
        derive_item(item)
        return None
    if net_contribution < 0:
        item["status"] = "COST_PENDING"
        derive_item(item)
        return "ERR_COST_EXCEEDS_PRICE_POINT"
    item["status"] = "COST_PENDING"
    derive_item(item)
    return None


# ---------------------------------------------------------------------------
# Container / allocation derivations
# ---------------------------------------------------------------------------

def container_lines(container_id):
    return [r for r in db.allocation_lines.values() if r["container_id"] == container_id]


def recompute_container_status(container_id, allow_audit_cascade=False):
    """RECEIVED -> ALLOCATED once every line is terminal; no line-free advance.

    Only two ways an audit closes (PRD §3.11): a StoreOperationsManager resolves
    it, or the audited store's own conversion completes (§3.8). Neither the
    release nor the short of an allocation line closes one, so nothing here
    touches PriceIntegrityAudit rows — only the open_violation_count is
    recomputed, which is the single side effect §3.7 declares for a short.
    """
    container = db.containers.get(container_id)
    if container is None:
        return False
    lines = container_lines(container_id)
    if not lines:
        return False
    all_terminal = all(line["status"] in TERMINAL_LINE_STATES for line in lines)
    target = "ALLOCATED" if all_terminal else "RECEIVED"
    if container["status"] == target:
        return False
    if container["status"] not in ("RECEIVED", "ALLOCATED"):
        return False
    container["status"] = target
    touch(container)
    return True


def _group_keys():
    keys = set()
    for line in db.allocation_lines.values():
        keys.add((line["container_id"], line["item_id"], line["store_id"]))
    return keys


def run_waterfall(only_item_id=None):
    """shelf_allocation_waterfall — grouped, sequence-ordered, never pooled."""
    keys = _group_keys()
    impacted_containers = set()
    changed = False
    for container_id, item_id, store_id in sorted(keys):
        if only_item_id is not None and item_id != only_item_id:
            continue
        item = db.items.get(item_id)
        if item is None:
            continue
        ceiling = capacity_ceiling(item)
        group = [
            line for line in container_lines(container_id)
            if line["item_id"] == item_id and line["store_id"] == store_id
        ]
        group.sort(key=lambda r: r["sequence"])
        already = 0
        for line in group:
            if line["status"] == "REVERSED":
                continue
            remaining_capacity = max(0, ceiling - already)
            allocated = min(int(line["requested_units"]), remaining_capacity)
            overflow = int(line["requested_units"]) - allocated
            already += allocated
            if line["allocated_units"] != allocated or line["overflow_units"] != overflow:
                changed = True
                impacted_containers.add(container_id)
            line["allocated_units"] = allocated
            line["overflow_units"] = overflow
            line["remaining_units"] = allocated - int(line["released_units"])
            if line["status"] in ("ALLOCATED", "OVERFLOW"):
                line["status"] = "OVERFLOW" if (allocated == 0 and int(line["requested_units"]) > 0) else "ALLOCATED"
    for container_id in impacted_containers:
        recompute_container_status(container_id)
    return changed


# ---------------------------------------------------------------------------
# Store / audit / vendor / price point / season window derivations
# ---------------------------------------------------------------------------

def recompute_store_derived(store):
    """Compare-and-touch: an unchanged count is not a modification."""
    audits = [r for r in db.audits.values() if r["store_id"] == store["id"]]
    count = len(audits)
    open_violations = sum(1 for r in audits if r["result"] == "VIOLATION" and r["status"] == "OPEN")
    if store.get("price_integrity_audit_count") == count and store.get("open_violation_count") == open_violations:
        return False
    store["price_integrity_audit_count"] = count
    store["open_violation_count"] = open_violations
    touch(store)
    return True


def _store_signature(store):
    audits = sorted(
        (r["id"], r["result"], r["status"]) for r in db.audits.values() if r["store_id"] == store["id"]
    )
    return (store["id"], tuple(audits))


def refresh_store(store):
    """Re-derive audit_count and open_violation_count.

    Returns True when the row was mutated. A short recomputes the line's
    store's open_violation_count (PRD §3.7) even though the short itself
    changes no audit, so this compares the stored numbers rather than the
    audit set.
    """
    signature = _store_signature(store)
    if store.get("__audit_sig") != signature:
        store["__audit_sig"] = signature
        return recompute_store_derived(store)
    return False


def refresh_vendor(vendor):
    count = sum(
        1 for p in db.pack_programs.values()
        if p["vendor_id"] == vendor["id"] and p["status"] == "ACTIVE"
    )
    if vendor.get("exclusivity_program_count") == count:
        return False
    vendor["exclusivity_program_count"] = count
    touch(vendor)
    return True


def refresh_price_point(price_point):
    stores = {
        reset["store_id"]
        for reset in db.aisle_resets.values()
        if reset["price_point_id"] == price_point["id"] and reset["status"] in ("PLANNED", "EXECUTING", "EXECUTED")
    }
    count = len(stores)
    if price_point.get("issued_store_count") == count:
        return False
    price_point["issued_store_count"] = count
    touch(price_point)
    return True


def season_window_status(window):
    """Clock-derived status (PRD §2.9); stored status stands before opens_on."""
    clock = db.logical_clock
    opens_on = window["opens_on"]
    closes_on = window["closes_on"]
    if clock < opens_on:
        return window["status"] if window["status"] in ("DRAFT", "SCHEDULED") else window["status"]
    if clock <= closes_on:
        return "OPEN"
    return "CLOSED"


def refresh_season_window(window):
    count = 0
    for reset in db.aisle_resets.values():
        if reset["starts_at"] <= window["closes_on"] and reset["ends_at"] >= window["opens_on"]:
            count += 1
    if window.get("overlapping_reset_count") == count:
        return False
    window["overlapping_reset_count"] = count
    touch(window)
    return True


# ---------------------------------------------------------------------------
# Global sweep
# ---------------------------------------------------------------------------

def refresh_after_config_change():
    """Re-derive everything configuration-sensitive.

    Called after any mutation that changes a structural number another row
    reads: price points, season windows, pack programs, items, vendors,
    containers, allocation lines, audits.
    """
    for vendor in db.vendors.values():
        refresh_vendor(vendor)
    for price_point in db.price_points.values():
        refresh_price_point(price_point)
    for window in db.season_windows.values():
        refresh_season_window(window)
    for item in db.items.values():
        derive_item(item)
    for container in db.containers.values():
        recompute_container_status(container["id"])
    for store in db.stores.values():
        refresh_store(store)


def clock_sweep(incumbent_containers=()):
    """POST /_clock/set_current_utc side effects (PRD §2.9)."""
    item_count = 0
    for item in db.items.values():
        derive_item(item)
        item_count += 1
    window_count = 0
    for window in db.season_windows.values():
        refresh_season_window(window)
        window_count += 1
    run_waterfall()
    for store_id in incumbent_containers:
        recompute_container_status(store_id)
    return item_count, window_count


def serialize_price_point(row):
    return serialize("price_point", row)


def serialize_season_window(row):
    return serialize("season_window", row)


def serialize_pack(row):
    return serialize("pack_program", row)


def serialize_item(row):
    return serialize("item", row)


def serialize_vendor(row):
    return serialize("vendor", row)


def serialize_container(row):
    return serialize("container", row)


def serialize_store(row):
    return serialize("store", row)


def serialize_reset(row):
    return serialize("aisle_reset", row)


def serialize_project(row):
    return serialize("conversion_project", row)


def serialize_audit(row):
    return serialize("audit", row)


def serialize_cost_row(row):
    return serialize("landed_cost", row)


def serialize_line(row):
    return serialize("allocation_line", row)