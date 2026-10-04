"""Derived-field recomputation (PRD §2.5, §3.1-§3.9).

Every derived figure named in the scaffold's entity table is materialised here so
that a mutation refreshes it in one place.  Recomputing a derived field counts as
a modification: it refreshes ``updated_at`` and increments ``version``.
"""
from decimal import Decimal, ROUND_HALF_UP
import math

from helpers import h
from errors import ApiError
from clockutil import clock, parse_ts, fmt, earlier, diff_hours_rounded

ENTRY_TYPES = [
    "RELEASE", "THAW", "TRANSFER_IN", "TRANSFER_OUT", "ADMINISTER",
    "PUNCTURE", "EXPIRE", "WASTE", "DESTROY", "REVERSE",
]
LOSS_ENTRY_TYPES = ["WASTE", "EXPIRE", "DESTROY"]
PHYSICAL_STATES = ["ULTRA_COLD", "THAWED", "REFRIGERATED", "PUNCTURED",
                   "PALLET_STAGED"]

REF_SLOTS = 780
REF_ICE_SLOT_BASE_DOSES = 400
ICE_SLOT_HOURS_DIVISOR = 2
MAX_PACKING_HOURS = 48
LOGGER_READING_GRACE_MINUTES = 120
MAX_STAGED_CARTON_HOURS = 48
MAX_RECOVERY_HOURS = 48
APPEAL_WINDOW_HOURS = 72
TOTAL_WEEKLY_CARTONS = 500


# ---------------------------------------------------------------------------
# cross-lookups
# ---------------------------------------------------------------------------
def batch_of_carton(carton):
    return h.get("allocation_batches", carton.get("allocation_batch_id"))


def product_of_batch(batch):
    if not batch:
        return None
    return h.get("product_configurations", batch.get("product_configuration_id"))


def program_of_batch(batch):
    if not batch:
        return None
    return h.get("jurisdiction_programs", batch.get("jurisdiction_program_id"))


def product_of_carton(carton):
    return product_of_batch(batch_of_carton(carton))


def window_of_entitlement(ent):
    if not ent:
        return None
    return h.get("allocation_windows", ent.get("allocation_window_id"))


def batch_of_entitlement(ent):
    win = window_of_entitlement(ent)
    if not win:
        return None
    return h.get("allocation_batches", win.get("allocation_batch_id"))


def entries_of_carton(carton_id):
    return [e for e in h.all("dose_ledger_entries") if e.get("carton_id") == carton_id]


def excursions_of_carton(carton_id):
    return [x for x in h.all("temperature_excursions") if x.get("carton_id") == carton_id]


def reservations_of_carton(carton_id):
    return [r for r in h.all("carton_storage_reservations") if r.get("carton_id") == carton_id]


def shippers_of_dispatch(dispatch_id):
    return [s for s in h.all("cold_chain_shippers") if s.get("dispatch_order_id") == dispatch_id]


def cartons_of_shipper(shipper_id):
    return [c for c in h.all("cartons") if c.get("cold_chain_shipper_id") == shipper_id]


def dispatches_of_order(order_id):
    return [d for d in h.all("dispatch_orders") if d.get("site_order_id") == order_id]


def cartons_of_dispatch(dispatch):
    out = []
    for ship in shippers_of_dispatch(dispatch["id"]):
        out.extend(cartons_of_shipper(ship["id"]))
    return out


def cartons_of_batch(batch_id):
    return [c for c in h.all("cartons") if c.get("allocation_batch_id") == batch_id]


def entitlements_of_batch(batch_id):
    out = []
    for win in h.all("allocation_windows"):
        if win.get("allocation_batch_id") != batch_id:
            continue
        for ent in h.all("allocation_entitlements"):
            if ent.get("allocation_window_id") == win["id"]:
                out.append(ent)
    return out


def entitlements_of_window(window_id):
    return [e for e in h.all("allocation_entitlements")
            if e.get("allocation_window_id") == window_id]


def orders_of_entitlement(ent_id):
    return [o for o in h.all("site_orders") if o.get("allocation_entitlement_id") == ent_id]


# ---------------------------------------------------------------------------
# site attribution
# ---------------------------------------------------------------------------
def cartons_at_site(site_id):
    """Cartons attributed to a site.

    A carton carries no site foreign key of its own, so custody is read from the
    dispatch that delivered it and from a received transfer.
    """
    out = []
    seen = set()
    for disp in h.all("dispatch_orders"):
        if disp.get("storage_site_id") != site_id:
            continue
        if disp.get("status") not in ("DELIVERED", "PACKED", "IN_TRANSIT"):
            continue
        for carton in cartons_of_dispatch(disp):
            if carton["id"] not in seen:
                seen.add(carton["id"])
                out.append(carton)
    for tr in h.all("site_transfers"):
        if tr.get("status") == "RECEIVED" and tr.get("to_site_id") == site_id:
            carton = h.get("cartons", tr.get("carton_id"))
            if carton and carton["id"] not in seen:
                seen.add(carton["id"])
                out.append(carton)
    return out


def _entry_type_for_state(state):
    if state in ("THAWED", "REFRIGERATED", "PUNCTURED", "EXPIRED"):
        return "REFRIGERATED"
    return "ULTRA_COLD"


# ---------------------------------------------------------------------------
# carton
# ---------------------------------------------------------------------------
def recompute_carton(carton):
    product = product_of_carton(carton)
    vials = carton.get("vials_per_carton") or 0
    if product is not None:
        carton["doses_per_carton"] = product.get("doses_per_vial", 0) * vials

    entries = entries_of_carton(carton["id"])
    # PRD 3.9: "remaining_doses is the carton's doses_per_carton less the doses
    # removed by its entries".  The physical count is reduced by a loss -- an
    # EXPIRE, WASTE or DESTROY -- and given back when such an entry is reversed; a
    # RELEASE and a TRANSFER move custody without removing doses.
    removed = sum(abs(e.get("quantity_doses", 0)) for e in entries
                  if e.get("entry_type") in LOSS_ENTRY_TYPES)
    restored = 0
    administered = 0
    for entry in entries:
        if entry.get("entry_type") == "ADMINISTER":
            administered += abs(entry.get("quantity_doses", 0))
            continue
        if entry.get("entry_type") != "REVERSE":
            continue
        target = h.get("dose_ledger_entries", entry.get("reverses_entry_id"))
        if target is None:
            continue
        if target.get("entry_type") in LOSS_ENTRY_TYPES:
            restored += abs(entry.get("quantity_doses", 0))
        elif target.get("entry_type") == "ADMINISTER":
            administered -= abs(entry.get("quantity_doses", 0))
    balance = carton.get("doses_per_carton", 0) - removed + restored
    carton["remaining_doses"] = max(0, balance)
    # The administrative count is the physical count less what has been drawn out of
    # the vial, which is the "administrative burn" the dose position is taken
    # against (PRD 4).
    carton["administrative_remaining_doses"] = max(0, balance - administered)
    carton["cumulative_released_doses"] = sum(
        e.get("quantity_doses", 0) for e in entries
        if e.get("entry_type") in ("RELEASE", "TRANSFER_IN", "REVERSE")
    )
    # PRD 3.9: "dose_shortfall_doses is the amount by which cumulative_released_doses
    # exceeds remaining_doses plus the administered doses, floored at zero."
    carton["dose_shortfall_doses"] = max(
        0, carton["cumulative_released_doses"] - carton["remaining_doses"] - administered
    )
    return h.touch(carton)


# ---------------------------------------------------------------------------
# entitlement / window / batch
# ---------------------------------------------------------------------------
HELD_ORDER_STATES = ("ACCEPTED", "PARTIALLY_ACCEPTED", "FULFILLED")


def recompute_entitlement(ent):
    """Refresh the entitlement's availability and release rate.

    PRD §3.2 defines `held_cartons` as "the cartons currently held by
    accepted-but-unfulfilled orders", so the figure is read back from the orders
    rather than kept as a running total: an order holds the quantity it declared
    when it was submitted (`requested_cartons_snapshot`), which is also the figure
    PRD §3.3's rejection arithmetic is taken against.
    """
    held = 0
    for order in orders_of_entitlement(ent["id"]):
        if order.get("order_status") not in HELD_ORDER_STATES:
            continue
        held += (order.get("requested_cartons_snapshot")
                 if order.get("requested_cartons_snapshot") is not None
                 else order.get("requested_cartons", 0)) or 0
    ent["held_cartons"] = held
    # A lapsed entitlement holds nothing: the cartons released by the lapse have
    # gone back to the batch, so both figures are zero (PRD §3.1 resets held_cartons
    # to zero on a recall lapse and PRD §3.2 does the same on a window-close lapse).
    if ent.get("acceptance_status") == "LAPSED":
        ent["held_cartons"] = 0
        ent["available_cartons"] = 0
    else:
        ent["available_cartons"] = max(0, ent.get("computed_cartons", 0) - held)
    computed = ent.get("computed_cartons", 0)
    if computed:
        # release_rate = accepted_cartons / computed_cartons, 4 dp round half up
        ent["release_rate"] = float(
            (Decimal(ent.get("accepted_cartons", 0)) / Decimal(computed))
            .quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        )
    else:
        ent["release_rate"] = 0.0
    return h.touch(ent)


def recompute_window(win, bump=False):
    """Refresh the window's aggregate carton figures.

    These two fields are aggregates the window rolls up; the window's own
    ``version`` is bumped only by the operations that commit against it (open,
    accept, reject and close), so the default here leaves it alone.
    """
    orders = [o for o in h.all("site_orders")
              if entitlement_of(o) and entitlement_of(o).get("allocation_window_id") == win["id"]]
    win["requested_cartons"] = sum(
        o.get("requested_cartons_snapshot") or o.get("requested_cartons") or 0
        for o in orders if o.get("order_status") != "REJECTED"
    )
    win["accepted_cartons"] = sum(o.get("accepted_cartons", 0) for o in orders)
    return h.touch(win) if bump else win


def entitlement_of(order):
    return h.get("allocation_entitlements", order.get("allocation_entitlement_id"))


def recompute_batch(batch):
    ents = entitlements_of_batch(batch["id"])
    batch["allocated_cartons"] = sum(e.get("computed_cartons", 0) for e in ents)
    batch["unallocated_cartons"] = max(
        0, batch.get("released_cartons", 0) - batch["allocated_cartons"]
    )
    product = product_of_batch(batch)
    if product is not None:
        batch["doses_released_total"] = batch.get("released_cartons", 0) * product.get(
            "doses_per_carton", 0
        )
    return h.touch(batch)


def recompute_program(program):
    batches = [b for b in h.all("allocation_batches")
               if b.get("jurisdiction_program_id") == program["id"]]
    program["released_cartons_to_date"] = sum(b.get("allocated_cartons", 0) for b in batches)
    if program.get("credit_balance_cartons", 0) < 0:
        program["credit_balance_cartons"] = 0
    return h.touch(program)


# ---------------------------------------------------------------------------
# site
# ---------------------------------------------------------------------------
def recompute_site(site):
    program = h.get("jurisdiction_programs", site.get("jurisdiction_program_id"))

    now = clock()
    verifying = []
    for v in h.all("site_equipment_verifications"):
        if v.get("storage_site_id") != site["id"]:
            continue
        if v.get("status") != "RECORDED":
            continue
        if v.get("outcome") != "PASSED":
            continue
        exp = parse_ts(v.get("certificate_expires_at"))
        if exp is None or exp > now:
            verifying.append(v)
    verifying.sort(key=lambda v: (parse_ts(v.get("verified_at")) or now, v.get("created_at", "")))
    site["equipment_certified"] = bool(verifying)
    site["equipment_verification_id"] = verifying[-1]["id"] if verifying else None

    cartons = [c for c in cartons_at_site(site["id"])
               if c.get("temperature_state") != "DESTROYED"]
    site["reported_entry_type"] = _mode_entry_type(cartons)
    # PRD §4 names the dose position "physical inventory minus administrative
    # burn", and PRD §3.3 scopes both site aggregates to the physical, non-in-transit
    # cartons.  A destroyed carton is no longer physical inventory, so it
    # contributes nothing.
    site["usable_doses"] = sum(
        c.get("administrative_remaining_doses", 0) for c in cartons
        if c.get("temperature_state") != "IN_TRANSIT"
    )
    site["administrative_remaining_doses"] = site["usable_doses"]
    site["open_excursion_count"] = sum(
        1 for x in h.all("temperature_excursions")
        if x.get("storage_site_id") == site["id"] and x.get("review_status") != "ADJUDICATED"
    )
    if program is not None and program.get("standing_status") == "FROZEN":
        site["inventory_status"] = "FROZEN"
    elif site["open_excursion_count"] > 0 and program is not None and \
            program.get("quarantine_on_review"):
        site["inventory_status"] = "RESTRICTED"
    else:
        site["inventory_status"] = "OPEN"
    return h.touch(site)


def _mode_entry_type(cartons):
    counts = {"ULTRA_COLD": 0, "REFRIGERATED": 0}
    for c in cartons:
        if c.get("temperature_state") == "IN_TRANSIT":
            continue
        counts[_entry_type_for_state(c.get("temperature_state"))] += 1
    if counts["REFRIGERATED"] > counts["ULTRA_COLD"]:
        return "REFRIGERATED"
    return "ULTRA_COLD"


def prospective_entry_type(site, incoming):
    """The site's reported_entry_type once ``incoming`` has become REFRIGERATED.

    Used by the transfer-receipt gate in PRD §3.7: the parked-destination branch
    compares the required entry type against a site's weighted mode, and the carton
    in flight is one of the cartons the site will hold.
    """
    cartons = [c for c in cartons_at_site(site["id"])
               if c.get("temperature_state") != "DESTROYED" and c["id"] != incoming["id"]]
    counts = {"ULTRA_COLD": 0, "REFRIGERATED": 1}
    for c in cartons:
        if c.get("temperature_state") == "IN_TRANSIT":
            continue
        counts[_entry_type_for_state(c.get("temperature_state"))] += 1
    if counts["REFRIGERATED"] > counts["ULTRA_COLD"]:
        return "REFRIGERATED"
    return "ULTRA_COLD"


def recompute_sites_for_carton(carton):
    for site in h.all("storage_sites"):
        if any(c["id"] == carton["id"] for c in cartons_at_site(site["id"])):
            recompute_site(site)


def recompute_family_sites(site_id):
    for member in family_closure(site_id):
        site = h.get("storage_sites", member)
        if site:
            recompute_site(site)


# ---------------------------------------------------------------------------
# carton family graph
# ---------------------------------------------------------------------------
def family_neighbours(site_id):
    out = set()
    for link in h.all("carton_families"):
        if link.get("site_id") == site_id:
            out.add(link.get("member_site_id"))
        if link.get("member_site_id") == site_id:
            out.add(link.get("site_id"))
    out.discard(None)
    return out


def family_closure(site_id):
    """Transitive closure over membership links, including the site itself.

    A cycle must not cause the traversal to visit a site twice (PRD §3.8).
    """
    seen = set()
    stack = [site_id]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for nxt in family_neighbours(cur):
            if nxt not in seen:
                stack.append(nxt)
    return seen


# ---------------------------------------------------------------------------
# shipper
# ---------------------------------------------------------------------------
def recompute_shipper(shipper):
    dispatch = h.get("dispatch_orders", shipper.get("dispatch_order_id"))
    cartons = [c for c in cartons_of_shipper(shipper["id"])
               if c.get("temperature_state") != "DESTROYED"]

    reference = _reference_product(cartons, dispatch)
    if reference is None:
        shipper["required_dry_ice_kg"] = 0
        shipper["dry_ice_deficit_kg"] = 0
        shipper["punctured_ice_slots"] = 0
        return h.touch(shipper)

    ref_vials = reference.get("vials_per_carton") or 1
    tapered = 0.0
    for carton in cartons:
        weight = (carton.get("vials_per_carton") or 0) / float(ref_vials)
        if carton.get("temperature_state") in ("THAWED", "REFRIGERATED", "PUNCTURED"):
            weight = weight * 0.5
        tapered += carton.get("doses_per_carton", 0) * weight

    n = len(cartons)
    adjustment = max(tapered + 0.25 * (n - 1), 0.0)
    if n >= 1:
        reference_doses = tapered * (math.sqrt(adjustment) / max(n, 1))
    else:
        reference_doses = 0.0
    shipper["punctured_ice_slots"] = float(
        Decimal(str(reference_doses)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    )

    shelf_life = reference.get("refrigerated_shelf_life_hours", 0)
    numerator = n * shelf_life
    divisor = REF_ICE_SLOT_BASE_DOSES * ICE_SLOT_HOURS_DIVISOR
    required = -(-numerator // divisor) if divisor else 0
    shipper["required_dry_ice_kg"] = required

    deficit = max(0, required - (shipper.get("dry_ice_kg") or 0))
    shipper["dry_ice_deficit_kg"] = float(
        Decimal(str(deficit)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
    return h.touch(shipper)


def _reference_product(cartons, dispatch):
    """The product configuration with the greatest number of attached cartons.

    Ties break by product_code ascending; identity is never used (PRD §3.4).
    """
    counts = {}
    products = {}
    for carton in cartons:
        batch = batch_of_carton(carton)
        product = product_of_batch(batch)
        if product is None:
            continue
        key = product["id"]
        counts[key] = counts.get(key, 0) + 1
        products[key] = product
    if not counts:
        return None
    best = sorted(products.values(), key=lambda p: (-counts[p["id"]], p.get("product_code", "")))
    return best[0]


def recompute_dispatch(dispatch):
    cartons = cartons_of_dispatch(dispatch)
    dispatch["carton_count"] = len([c for c in cartons if c.get("temperature_state") != "DESTROYED"])
    # The shortfall is charged on the shipper payload against the BATCH
    # PRODUCT's pack size, never the program minimum.
    product = None
    order = h.get("site_orders", dispatch.get("site_order_id"))
    if order:
        ent = entitlement_of(order)
        batch = batch_of_entitlement(ent) if ent else None
        product = product_of_batch(batch)
    if product is not None:
        dispatch["min_order_shortfall_cartons"] = max(
            0, product.get("min_order_cartons", 0) - dispatch["carton_count"]
        )
    # PRD 3.4: "Packing also recomputes freeze_required, which is true exactly when
    # the destination's reported_entry_type is ULTRA_COLD after the route is applied."
    destination = h.get("storage_sites", dispatch.get("storage_site_id"))
    dispatch["route_cartons"] = dispatch["carton_count"]
    dispatch["freeze_required"] = bool(
        destination and destination.get("reported_entry_type") == "ULTRA_COLD"
    )
    return h.touch(dispatch)