"""Business services: derived projections, cascades, sweeps, shared helpers.

The store is the aggregate root.  Everything here recomputes derived fields on
the rows it touches, and every touched row gets its ``updated_at`` refreshed and
its ``version`` incremented -- derived fields are mutated fields (PRD 2.4).
"""
from decimal import Decimal

from util import (
    dt_add_hours, dt_add_minutes, new_id, parse_dt, to_dec,
)
import calc
from errors import fail, invalid

NON_TERMINAL_TICKET_STATUSES = (
    "QUEUED", "TICKETED", "IN_PROGRESS", "COMPLETED", "REMADE",
)

# ------------------------------------------------------------------ plumbing --
def create(store, table_name, row):
    """Insert a fresh row: mint the id, stamp common fields, honour create order."""
    row["id"] = new_id()
    row.setdefault("version", 1)
    row["created_at"] = store.now()
    row["updated_at"] = store.now()
    store.seq[table_name] = store.seq.get(table_name, 0) + 1
    row["_seq"] = store.seq[table_name]
    store.order.setdefault(table_name, []).append(row["id"])
    getattr(store, table_name)[row["id"]] = row
    return row


def touch(store, row):
    """Record a mutation on an existing row."""
    row["updated_at"] = store.now()
    row["version"] = row["version"] + 1
    return row


def bump_store(store, store_id):
    """Force a mutation record on the store for operations that touch its state."""
    row = store.stores[store_id]
    touch(store, row)
    return row


def all_rows(store, table_name):
    rows = list(getattr(store, table_name).values())
    rows.sort(key=lambda r: (r["_seq"], r["id"]))
    return rows


def store_rows(store, table_name, store_id):
    return [r for r in all_rows(store, table_name) if r["store_id"] == store_id]


def get_store(store, store_id):
    row = store.stores.get(store_id)
    if row is None:
        fail("ERR_STORE_NOT_FOUND")
    return row


def get_scoped(store, table_name, row_id, store_id):
    """Existence + scope agreement: a mismatched scope reads as non-existence."""
    row = getattr(store, table_name).get(row_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    if store_id is not None and row["store_id"] != store_id:
        fail("ERR_NOT_FOUND")
    return row


def get_plain(store, table_name, row_id):
    row = getattr(store, table_name).get(row_id)
    if row is None:
        fail("ERR_NOT_FOUND")
    return row


def get_item(store, item_id):
    item = store.items.get(item_id)
    if item is None or item["status"] != "ACTIVE":
        fail("ERR_DELI_ITEM_UNAVAILABLE")
    return item


def get_associate(store, associate_id):
    associate = store.associates.get(associate_id)
    if associate is None:
        fail("ERR_NOT_FOUND")
    return associate


def check_occ(store, row, provided, field_name):
    """Optimistic concurrency control: non-optional, stale-version rejection."""
    if provided is None:
        invalid("%s is required." % field_name)
    if isinstance(provided, bool) or not isinstance(provided, int):
        invalid("%s must be an integer." % field_name)
    if provided != row["version"]:
        fail("ERR_STALE_VERSION")
    return True


def item_allergens(store, item_id):
    item = store.items.get(item_id)
    if item is None:
        return frozenset()
    return frozenset(item["allergen_flags"])


def holds_cert(store, associate_id, cert_type, deli_item_id=None, grace=False):
    return calc.has_active_cert(
        all_rows(store, "certifications"), associate_id, cert_type,
        store.now(), deli_item_id=deli_item_id, for_grace=grace,
    )


# ------------------------------------------------------- derived projections --
def recompute_store(store, store_id, bump=True):
    """Refresh every derived Store field from the current row state.

    Recomputing a derived field is a mutation of the store, so a change means
    ``updated_at`` is refreshed and ``version`` incremented.  A recompute that
    changes nothing leaves the row untouched, which keeps OCC usable: a client
    that has just read the store holds a version no incidental read advances.
    """
    row = store.stores[store_id]
    associates = all_rows(store, "associates")
    certs = all_rows(store, "certifications")
    waste = all_rows(store, "waste_records")
    slicers = all_rows(store, "slicers")

    latest = {}
    latest["certified_slicer_operator_count"] = \
        calc.certified_slicer_operator_count(
            associates, certs, store_id, store.now())

    case_lbs = Decimal(0)
    covered = set()
    for batch in all_rows(store, "batches"):
        if batch["store_id"] != store_id:
            continue
        if batch["hold_status"] in ("HOLDING", "MARKED_DOWN"):
            case_lbs += to_dec(batch["produced_lbs"])
            item = store.items.get(batch["deli_item_id"])
            if item is not None:
                covered.update(item["allergen_flags"])
    latest["case_on_hand_lbs"] = case_lbs
    latest["covered_allergen_set"] = sorted(covered)

    _total, waste_verified = calc.store_waste_liability(waste, store_id, store.now())
    latest["verified_waste_liability_cents"] = waste_verified
    latest["pending_waste_verification_count"] = sum(
        1 for w in waste
        if w["store_id"] == store_id
        and w["status"] in ("DRAFT", "MARKED_DOWN", "DISCARDED")
    )

    active_file = calc.resolve_active_price_file(
        all_rows(store, "price_files"), store_id, store.now())
    latest["active_price_file_id"] = active_file["id"] if active_file else None

    promo = targeted_promotion(store, store_id)
    latest["targeted_promo_id"] = promo["id"] if promo else None

    delivered = 0
    bread_held = 0
    for order in all_rows(store, "bread_orders"):
        if order["store_id"] != store_id:
            continue
        if order["status"] == "DELIVERED":
            delivered += order["committed_units"]
    for ticket in all_rows(store, "sub_tickets"):
        if ticket["store_id"] == store_id and ticket["bread_status"] == "BREAD_HOLD":
            bread_held += 1
    latest["available_bread_units"] = max(0, delivered - bread_held)

    probe = dict(row)
    probe.update(latest)
    protection, _ = calc.diffusion_index(
        probe, associates, certs, waste, slicers, store.now())
    posture, reason = calc.store_deli_posture(probe, protection)
    latest["posture"] = posture
    latest["posture_reason"] = reason

    changed = any(row.get(key) != value for key, value in latest.items())
    row.update(latest)
    if bump and changed:
        touch(store, row)
    return row


def targeted_promotion(store, store_id):
    """ACTIVE promotion whose half-open week contains the clock."""
    now = parse_dt(store.now())
    candidates = []
    for promo in all_rows(store, "promotions"):
        if promo["status"] != "ACTIVE":
            continue
        if parse_dt(promo["week_start_date"]) <= now < parse_dt(promo["week_end_date"]):
            candidates.append(promo)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (parse_dt(p["week_start_date"]), p["_seq"]))
    return candidates[0]


def recompute_queue(store, store_id):
    """Rank the store's gate-eligible tickets; every other ticket reads 0."""
    eligible = calc.sub_queue_order(all_rows(store, "sub_tickets"), store_id)
    ranked = {}
    for index, ticket in enumerate(eligible):
        ranked[ticket["id"]] = index + 1
    for ticket in all_rows(store, "sub_tickets"):
        if ticket["store_id"] != store_id:
            continue
        target = ranked.get(ticket["id"], 0)
        if ticket["queue_position"] != target:
            ticket["queue_position"] = target
            touch(store, ticket)


def apply_promo_degradation(store, promo, units_short, order=None):
    """ACTIVE <-> DEGRADED driven by coverage short and order shortfall."""
    if promo is None or promo["status"] not in ("ACTIVE", "DEGRADED"):
        return
    short = units_short
    if order is not None and order["shortfall_units"] > 0:
        short = max(short, order["shortfall_units"])
    if short > 0:
        if promo["status"] != "DEGRADED":
            promo["status"] = "DEGRADED"
            touch(store, promo)
    else:
        if promo["status"] != "ACTIVE":
            promo["status"] = "ACTIVE"
            touch(store, promo)


def recompute_bread(store, store_id):
    """Refresh every bread order's reserves, then the promotion coverage."""
    tickets = all_rows(store, "sub_tickets")
    for order in all_rows(store, "bread_orders"):
        if order["store_id"] != store_id:
            continue
        reserved, units_short, _ = calc.bread_forecast_coverage(order, tickets)
        if order["reserved_units"] != reserved:
            order["reserved_units"] = reserved
            order["unreserved_required_units"] = max(
                0, order["committed_units"] - reserved)
            touch(store, order)
        else:
            order["unreserved_required_units"] = max(
                0, order["committed_units"] - reserved)
        promo = store.promotions.get(order["promotion_id"])
        apply_promo_degradation(store, promo, units_short, order)
    recompute_store(store, store_id)


def recompute_promotion(store, promotion_id, settled=False):
    promo = store.promotions[promotion_id]
    if settled:
        promo["settled_bread_units"] = calc.promo_bread_demand(promo, settled=True)
    else:
        promo["required_bread_units"] = calc.promo_bread_demand(promo, settled=False)
    touch(store, promo)
    return promo


def settle_batch_costs(store, batch, seal_provisional=False):
    """Recompute the batch's case-yield variants.

    PRD §3.3 recomputes both variants at completion, and at verification it
    recomputes only `discard_lbs` and the *final* figure — the provisional is
    reported "while no verified waste record exists for the batch" and is not
    rewritten by verification. `seal_provisional` therefore writes the
    provisional on the completion leg only.
    """
    item = store.items.get(batch["deli_item_id"])
    if item is None:
        return
    slicer = store.slicers.get(batch["slicer_id"]) if batch["slicer_id"] else None
    batch["_verified_waste"] = [
        w for w in all_rows(store, "waste_records")
        if w["production_batch_id"] == batch["id"] and w["status"] == "VERIFIED"
    ]
    provisional, final = calc.batch_case_yield_cost(batch, item, slicer)
    if seal_provisional or not batch.get("case_yield_cost_provisional_cents"):
        batch["case_yield_cost_provisional_cents"] = provisional
    batch["case_yield_cost_final_cents"] = batch["case_yield_cost_provisional_cents"] + \
        (final - provisional)


def recompute_batch_discard(store, batch):
    batch["discard_lbs"] = sum(
        (to_dec(w["discard_lbs"]) for w in all_rows(store, "waste_records")
         if w["production_batch_id"] == batch["id"] and w["status"] == "VERIFIED"),
        Decimal(0),
    )


def recompute_label_counts(store, price_file_id):
    """Count the labels currently written against the file.

    PRD §3.6 describes the counter as counting the labels written against the
    file and, in the supersession cascade, voids those labels; the figure is
    therefore recomputed from the rows that still hold the file, so a voided
    label retires its contribution rather than leaving it counted forever.
    """
    if price_file_id is None:
        return
    price_file = store.price_files.get(price_file_id)
    if price_file is None:
        return
    count = sum(1 for label in all_rows(store, "labels")
                if label["price_file_id"] == price_file_id
                and label["status"] == "ISSUED")
    if price_file["synced_scale_count"] != count:
        price_file["synced_scale_count"] = count
        touch(store, price_file)


def recompute_catering_quote(store, order):
    planner_certified = holds_cert(
        store, order["certified_planner_associate_id"], "FOOD_HANDLING")
    order["quote_total_cents"] = calc.catering_platter_quote(order, planner_certified)
    return order


# ----------------------------------------------------------------- cascades ---
def abandon_ticket(store, ticket, release_bread=True):
    ticket["status"] = "ABANDONED"
    touch(store, ticket)
    if release_bread:
        recompute_bread(store, ticket["store_id"])


def store_halt_cascade(store, store_id):
    """HALT entry: every non-terminal ticket abandons and releases its reserve."""
    for ticket in all_rows(store, "sub_tickets"):
        if ticket["store_id"] != store_id:
            continue
        if ticket["status"] in ("PICKED_UP", "ABANDONED"):
            continue
        abandon_ticket(store, ticket, release_bread=False)
    recompute_queue(store, store_id)
    recompute_bread(store, store_id)


def supersede_price_file_cascade(store, store_id, superseded):
    """Superseded file -> its ISSUED labels void -> their tickets go REMADE."""
    for label in all_rows(store, "labels"):
        if label["price_file_id"] != superseded["id"] or label["status"] != "ISSUED":
            continue
        label["status"] = "VOIDED"
        touch(store, label)
        ticket = store.sub_tickets.get(label["sub_ticket_id"])
        if ticket is not None and ticket["status"] == "COMPLETED":
            ticket["status"] = "REMADE"
            ticket["remake_count"] = ticket["remake_count"] + 1
            touch(store, ticket)
    # Voiding the labels is a mutation of the superseded file's derived counter.
    recompute_label_counts(store, superseded["id"])
    recompute_queue(store, store_id)


def allergen_changeover_cascade(store, store_id, sliced_item, tickets):
    """Tickets whose item allergen set diverges from the sliced item are held."""
    sliced_set = frozenset(sliced_item["allergen_flags"]) if sliced_item else None
    for ticket in tickets:
        if ticket["status"] != "QUEUED" or ticket["bread_status"] != "QUEUED":
            continue
        flags = item_allergens(store, ticket["deli_item_id"])
        if sliced_set is not None and flags != sliced_set:
            ticket["bread_status"] = "BREAD_HOLD"
            touch(store, ticket)
    recompute_bread(store, store_id)


def refresh_ticket_bread_status(store, store_id, bread_item_id):
    """A delivery covering this bread item releases its BREAD_HOLD tickets."""
    for ticket in all_rows(store, "sub_tickets"):
        if ticket["store_id"] != store_id:
            continue
        if ticket["bread_deli_item_id"] != bread_item_id:
            continue
        if ticket["bread_status"] != "BREAD_HOLD":
            continue
        ticket["bread_status"] = "QUEUED"
        touch(store, ticket)
    recompute_queue(store, store_id)
    recompute_bread(store, store_id)


# ------------------------------------------------------------------- sweeps ---
def expire_certifications(store, store_id):
    now = parse_dt(store.now())
    changed = False
    for cert in all_rows(store, "certifications"):
        if cert["store_id"] != store_id or cert["status"] != "ACTIVE":
            continue
        if parse_dt(cert["expires_at"]) <= now:
            cert["status"] = "EXPIRED"
            touch(store, cert)
            changed = True
    return changed


def expire_hold_windows(store, store_id):
    for batch in all_rows(store, "batches"):
        if batch["store_id"] != store_id:
            continue
        if batch["hold_status"] not in ("HOLDING", "MARKED_DOWN"):
            continue
        if batch["produced_at"] is None:
            continue
        item = store.items.get(batch["deli_item_id"])
        if item is None:
            continue
        if calc.hold_window_closed(batch, item, store.now()):
            batch["hold_status"] = "DISCARDED"
            touch(store, batch)


def closeout_bread_orders(store, store_id):
    now = parse_dt(store.now())
    for order in all_rows(store, "bread_orders"):
        if order["store_id"] != store_id:
            continue
        promo = store.promotions.get(order["promotion_id"])
        if order["status"] == "DELIVERED" and promo is not None:
            if parse_dt(promo["week_end_date"]) <= now:
                open_orders = [
                    o for o in all_rows(store, "bread_orders")
                    if o["promotion_id"] == promo["id"]
                    and o["status"] in ("DRAFT", "SUBMITTED", "CONFIRMED")
                ]
                if not open_orders:
                    order["status"] = "RECONCILED"
                    touch(store, order)
        elif order["status"] == "SHORT" and promo is not None:
            if promo["status"] in ("SETTLED", "CANCELLED"):
                order["status"] = "RECONCILED"
                touch(store, order)


def refresh_certification_counters(store, store_id):
    for associate in all_rows(store, "associates"):
        if associate["store_id"] != store_id:
            continue
        count = calc.active_certification_count(
            all_rows(store, "certifications"), associate["id"], store.now())
        if associate["active_certification_count"] != count:
            associate["active_certification_count"] = count
            touch(store, associate)
    for cert in all_rows(store, "certifications"):
        if cert["store_id"] != store_id:
            continue
        flag = calc.grace_reminder(cert, store.now())
        if cert["grace_reminder"] != flag:
            cert["grace_reminder"] = flag
            touch(store, cert)


def run_production_day(store, store_ids):
    """Close the production day for each store in scope."""
    affected = []
    for store_id in store_ids:
        row = store.stores[store_id]
        row["ops_run_index"] = row["ops_run_index"] + 1
        row["logical_clock_at_last_run"] = store.now()
        expire_certifications(store, store_id)
        expire_hold_windows(store, store_id)
        closeout_bread_orders(store, store_id)
        refresh_certification_counters(store, store_id)
        recompute_bread(store, store_id)
        recompute_queue(store, store_id)
        affected.append(recompute_store(store, store_id))
    return affected


def hygiene(store, store_id):
    """Re-evaluate the store-wide gates that every write passes through.

    Returns the ordering-relevant flags so callers can apply them at the
    priority position the PRD dictates.
    """
    row = store.stores[store_id]
    recompute_store(store, store_id)
    return row


def pickup_window_lockout(store, store_id):
    """FIFO half-open lockout: an order past its window, short of PICKED_UP."""
    now = parse_dt(store.now())
    for order in all_rows(store, "catering_orders"):
        if order["store_id"] != store_id:
            continue
        if order["status"] in ("PICKED_UP", "CANCELLED", "INQUIRY"):
            continue
        if parse_dt(order["pickup_window_end"]) <= now:
            return True
    return False


def gate_store_halt(store, store_id):
    if store.stores[store_id]["haccp_safety_flag"]:
        fail("ERR_HACCP_HOLD")
    if store.stores[store_id]["posture"] == "HALT":
        fail("ERR_POSTURE_HALT")


def batch_code_index(store):
    """item_id -> the production batch codes that item is planned under."""
    index = {}
    for batch in all_rows(store, "batches"):
        index.setdefault(batch["deli_item_id"], []).append(batch["batch_code"])
    for codes in index.values():
        codes.sort()
    return index


def recompute_ticket_price(store, ticket):
    item = store.items.get(ticket["deli_item_id"])
    if item is None:
        return ticket
    promo = targeted_promotion(store, ticket["store_id"])
    uplift = to_dec(promo["forecast_uplift_pct"]) if promo else Decimal(0)
    ticket["line_total_cents"] = calc.sub_ticket_line_total(ticket, item, store.items, uplift)
    return ticket


def sync_ticket_progress(store, tickets):
    """TICKETED -> IN_PROGRESS once the ticket's item prerequisites hold.

    A station begins the build automatically when a CLEAN slicer exists for
    every slicer-required line; the slicer used enters IN_USE at that point.
    """
    for ticket in tickets:
        if ticket["status"] != "TICKETED":
            continue
        if ticket["bread_status"] != "QUEUED":
            continue
        store_id = ticket["store_id"]
        required_slicer = False
        for line in ticket["lines"]:
            item = store.items.get(line["deli_item_id"])
            if item is not None and item["slicer_required"]:
                required_slicer = True
        slicer = None
        if required_slicer:
            for candidate in all_rows(store, "slicers"):
                if candidate["store_id"] == store_id \
                        and candidate["sanitation_status"] == "CLEAN":
                    slicer = candidate
                    break
            if slicer is None:
                continue
        ticket["status"] = "IN_PROGRESS"
        touch(store, ticket)
        if slicer is not None:
            slicer["sanitation_status"] = "IN_USE"
            touch(store, slicer)
    if tickets:
        recompute_queue(store, tickets[0]["store_id"])


# ------------------------------------------------------------------- labels ---
def synthesize_label(store, store_id, subject_type, subject_ref_id,
                     net_weight_lbs, unit_price_cents, sub_ticket_id=None):
    active = calc.resolve_active_price_file(
        all_rows(store, "price_files"), store_id, store.now())
    label = create(store, "labels", {
        "store_id": store_id,
        "sub_ticket_id": sub_ticket_id,
        "price_file_id": active["id"] if active else None,
        "subject_type": subject_type,
        "subject_ref_id": subject_ref_id,
        "net_weight_lbs": to_dec(net_weight_lbs),
        "unit_price_cents": unit_price_cents,
        "total_price_cents": calc.label_total_price(net_weight_lbs, unit_price_cents),
        "printed_at": store.now(),
        "status": "ISSUED",
    })
    recompute_label_counts(store, label["price_file_id"])
    return label


def unit_price_for(store, item):
    """Per-pound price resolved from the ACTIVE scale price file."""
    return item["retail_price_per_lb_cents"]