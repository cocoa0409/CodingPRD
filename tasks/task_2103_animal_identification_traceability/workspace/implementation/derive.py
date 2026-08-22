"""Derived counters, the sighting projection and the shared cascades.

PRD 2.8 (derived counters / cascades) and 2.11 (the sighting log as the system
of record). No client ever writes any of these values.
"""
from decimal import Decimal

import calc
from db import base_record, store, touch

LOCATION_SETTERS = ("TAG_APPLIED", "ARRIVAL", "HARVEST")


# --- lookups --------------------------------------------------------------
def animal_rows(animal_id, include_reversed=True):
    rows = [s for s in store.sightings.values() if s["animal_id"] == animal_id]
    if not include_reversed:
        rows = [s for s in rows if not s["reversed"]]
    rows.sort(key=lambda s: s["sequence_no"])
    return rows


def latest_observed_at(animal_id):
    """observed_at of the animal's non-reversed sighting with the highest
    sequence_no (PRD 2.5 band 13)."""
    rows = animal_rows(animal_id, include_reversed=False)
    if not rows:
        return None
    return rows[-1]["observed_at"]


def lot_tags(lot_id):
    return [t for t in store.tags.values() if t["tag_lot_id"] == lot_id]


def supplier_lots(supplier_id):
    return [l for l in store.tag_lots.values() if l["supplier_id"] == supplier_id]


def producer_premises(producer_id):
    return [p for p in store.premises.values() if p["producer_id"] == producer_id]


# --- sighting log ---------------------------------------------------------
def append_sighting(animal, premises_id, sighting_type, observed_at,
                    source_movement_id=None):
    rec = base_record(common_fields=False)
    rec.update({
        "animal_id": animal["id"],
        "premises_id": premises_id,
        "source_movement_id": source_movement_id,
        "sighting_type": sighting_type,
        "observed_at": observed_at,
        "sequence_no": animal["last_sequence_no"] + 1,
        "reversed": False,
    })
    store.sightings[rec["id"]] = rec
    return rec


def reproject_animal(animal):
    """PRD 2.11: replay non-reversed rows in ascending sequence_no (append)
    order; a back-dated observed_at never reorders the replay."""
    all_rows = animal_rows(animal["id"], include_reversed=True)
    live = [s for s in all_rows if not s["reversed"]]
    current = None
    lifecycle = "VOIDED"
    for s in live:
        kind = s["sighting_type"]
        if kind == "TAG_APPLIED":
            current, lifecycle = s["premises_id"], "ACTIVE"
        elif kind == "DEPARTURE":
            current, lifecycle = None, "IN_TRANSIT"
        elif kind == "ARRIVAL":
            current, lifecycle = s["premises_id"], "ACTIVE"
        elif kind == "HARVEST":
            current, lifecycle = s["premises_id"], "HARVESTED"
    last_seq = max((s["sequence_no"] for s in all_rows), default=0)
    changed = (animal["current_premises_id"] != current
               or animal["lifecycle_status"] != lifecycle
               or animal["sighting_count"] != len(live)
               or animal["last_sequence_no"] != last_seq)
    animal["current_premises_id"] = current
    animal["lifecycle_status"] = lifecycle
    animal["sighting_count"] = len(live)
    animal["last_sequence_no"] = last_seq
    if changed:
        touch(animal)
    return changed


# --- roll-ups -------------------------------------------------------------
def recompute_premises_animal_count(premises_ids):
    """A premises' animal_count is the number of animals resident there whose
    lifecycle_status is ACTIVE (PRD 2.11)."""
    seen = set()
    for pid in premises_ids:
        if not pid or pid in seen:
            continue
        seen.add(pid)
        premises = store.premises.get(pid)
        if premises is None:
            continue
        count = sum(1 for a in store.animals.values()
                    if a["current_premises_id"] == pid and a["lifecycle_status"] == "ACTIVE")
        if premises["animal_count"] != count:
            premises["animal_count"] = count
            touch(premises)
            mark_producer(premises["producer_id"])


def compute_head_and_tier(producer_id):
    """(enrolled_head_count, incentive_tier) without mutating the record."""
    total = sum(p["animal_count"] for p in producer_premises(producer_id)
                if p["registration_status"] == "ACTIVE")
    tier, _factor = calc.tier_for_head_count(total)
    return total, tier


def compute_on_time_pct(producer_id):
    denominator = 0
    numerator = 0
    for mv in store.movements.values():
        if mv["status"] not in ("REPORTED", "RECEIVED", "DISPUTED"):
            continue
        origin = store.premises.get(mv["origin_premises_id"])
        if origin is None or origin["producer_id"] != producer_id:
            continue
        denominator += 1
        if mv["on_time"]:
            numerator += 1
    return calc.on_time_pct(numerator, denominator)


# A producer sits at the top of every cascade, so several hops of one request
# can touch it. Marks are collected and flushed once per request, leaving the
# record with exactly one updated_at refresh and one version increment.
_pending_producers = {}


def reset_pending():
    _pending_producers.clear()


def mark_producer(producer_id, on_time=False, allow_lapse=False):
    if not producer_id:
        return
    entry = _pending_producers.setdefault(producer_id,
                                          {"on_time": False, "allow_lapse": False})
    entry["on_time"] = entry["on_time"] or on_time
    entry["allow_lapse"] = entry["allow_lapse"] or allow_lapse


def flush_producers():
    while _pending_producers:
        producer_id, flags = _pending_producers.popitem()
        _recompute_producer(producer_id, **flags)


def _recompute_producer(producer_id, on_time=False, allow_lapse=False):
    producer = store.producers.get(producer_id)
    if producer is None:
        return
    premises_list = producer_premises(producer_id)
    total = sum(p["animal_count"] for p in premises_list
                if p["registration_status"] == "ACTIVE")
    tier, _factor = calc.tier_for_head_count(total)
    changed = (producer["enrolled_head_count"] != total
               or producer["incentive_tier"] != tier)
    producer["enrolled_head_count"] = total
    producer["incentive_tier"] = tier
    if on_time:
        pct = compute_on_time_pct(producer_id)
        if producer["on_time_movement_pct"] != pct:
            producer["on_time_movement_pct"] = pct
            changed = True
    if allow_lapse and producer["enrollment_status"] == "ENROLLED":
        if not any(p["registration_status"] == "ACTIVE" for p in premises_list):
            producer["enrollment_status"] = "LAPSED"
            changed = True
    if changed:
        touch(producer)


def recompute_premises_pending_hold_count(premises):
    count = sum(1 for h in store.hold_orders.values()
                if h["premises_id"] == premises["id"]
                and h["status"] in ("PROPOSED", "ACTIVE", "UNDER_APPEAL"))
    changed = premises["pending_hold_count"] != count
    premises["pending_hold_count"] = count
    return changed


# --- tag lot counters -----------------------------------------------------
def recompute_lot(lot):
    """Lot counters follow the devices; ISSUED -> ACTIVE on the first
    application and ACTIVE -> DEPLETED once unapplied_count reaches 0."""
    tags = lot_tags(lot["id"])
    applied = sum(1 for t in tags if t["device_status"] == "APPLIED")
    retired = sum(1 for t in tags if t["device_status"] == "RETIRED")
    replaced = sum(1 for t in tags if t["device_status"] == "REPLACED")
    voided = sum(1 for t in tags if t["device_status"] == "VOIDED")
    unapplied = lot["quantity"] - applied - retired - replaced - voided
    status = lot["status"]
    if status == "ISSUED" and applied >= 1:
        status = "ACTIVE"
    if status == "ACTIVE" and unapplied == 0:
        status = "DEPLETED"
    changed = (lot["applied_count"] != applied or lot["retired_count"] != retired
               or lot["replaced_count"] != replaced or lot["voided_count"] != voided
               or lot["unapplied_count"] != unapplied or lot["status"] != status)
    lot.update({
        "applied_count": applied,
        "retired_count": retired,
        "replaced_count": replaced,
        "voided_count": voided,
        "unapplied_count": unapplied,
        "status": status,
    })
    if changed:
        touch(lot)
    return changed


# --- supplier conformance -------------------------------------------------
COUNTED_LOT_STATES = ("ISSUED", "ACTIVE", "DEPLETED", "RECALLED")


def supplier_metrics(supplier):
    """The derived conformance figures, computed without mutating anything."""
    lots = supplier_lots(supplier["id"])
    counted = [l for l in lots if l["status"] in COUNTED_LOT_STATES]
    issued = sum(l["quantity"] for l in counted)
    counted_ids = {l["id"] for l in counted}
    retired_tags = [t for t in store.tags.values()
                    if t["device_status"] == "RETIRED" and t["tag_lot_id"] in counted_ids]
    retired = len(retired_tags)
    returned = sum(1 for t in retired_tags if t["tag_returned"] is True)
    score, probation, cap = calc.conformance(supplier["defect_report_count"], issued,
                                             retired, returned)
    return {
        "issued_tag_count": issued,
        "retired_tag_count": retired,
        "retired_returned_count": returned,
        "conformance_score": score,
        "probation": probation,
        "issuance_cap": cap,
    }


def assign_supplier_metrics(supplier, metrics):
    changed = any(supplier[k] != v for k, v in metrics.items())
    supplier.update(metrics)
    return changed


def recompute_supplier(supplier, apply_status_transitions=False, bump_version=False):
    """Re-derives issued/retired counts, conformance_score, probation and
    issuance_cap (PRD 3.2). Automatic status transitions fire only where the
    programme declares them: defect reports and harvest-retirement hop 4."""
    metrics = supplier_metrics(supplier)
    changed = assign_supplier_metrics(supplier, metrics)
    score = metrics["conformance_score"]
    if apply_status_transitions:
        prior = supplier["status"]
        if prior == "APPROVED" and score < Decimal("70.00"):
            supplier["status"] = "SUSPENDED"
            changed = True
            recall_supplier_lots(supplier)
        elif prior == "SUSPENDED" and score < Decimal("40.00"):
            supplier["status"] = "REVOKED"
            changed = True
            recall_supplier_lots(supplier)
    if changed or bump_version:
        touch(supplier)
    return changed


def recall_supplier_lots(supplier):
    """Suspension/revocation recalls every ISSUED or ACTIVE lot; already
    applied devices keep device_status APPLIED."""
    for lot in supplier_lots(supplier["id"]):
        if lot["status"] in ("ISSUED", "ACTIVE"):
            lot["status"] = "RECALLED"
            touch(lot)


# --- reconciliation book balance (PRD 3.8) -------------------------------
BOOK_LOT_STATES = ("ISSUED", "ACTIVE", "DEPLETED")


def book_balance(premises, period_start, period_end):
    basis = "AS_ISSUED" if premises["operation_type"] in ("COW_CALF", "FEEDLOT") else "AS_SIGHTED"
    lots = [l for l in store.tag_lots.values()
            if l["premises_id"] == premises["id"] and l["status"] in BOOK_LOT_STATES]
    if basis == "AS_ISSUED":
        book = sum(l["quantity"] - l["applied_count"] - l["retired_count"]
                   - l["replaced_count"] - l["voided_count"] for l in lots)
    else:
        from timeutil import day_end, day_start
        start = day_start(period_start)
        end = day_end(period_end)
        applied_here = sum(1 for s in store.sightings.values()
                           if s["sighting_type"] == "TAG_APPLIED"
                           and s["premises_id"] == premises["id"]
                           and not s["reversed"]
                           and start <= s["observed_at"] <= end)
        book = sum(l["quantity"] for l in lots) - applied_here
    return basis, book
