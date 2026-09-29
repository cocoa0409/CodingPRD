"""Multi-hop cascades: derates, resequencing, proration runs, settlement."""
from datetime import timedelta
from decimal import Decimal

import calc
from calc import (apply_effective_capacity, capacity_proration, cycle_nominations,
                  cycle_tickets, freeze_history, imbalance_tier, pinned_tariff,
                  recompute_total_transmix, recompute_totals, refresh_exposure,
                  segment_of, tariff_charge)
from core import ZERO, db, fail, new_row, now, r2, r6, touch


# ---------------------------------------------------------------------------
# Segment derate / operational status (PRD 3.8 hop two)
# ---------------------------------------------------------------------------
def governing_derate(segment_id):
    best = ZERO
    for event in db.maintenance_events.values():
        if event["segment_id"] != segment_id:
            continue
        if event["status"] not in ("NOTIFIED", "ACTIVE"):
            continue
        if event["capacity_derate_pct"] > best:
            best = event["capacity_derate_pct"]
    return r2(best)


def recompute_segment_derate(segment):
    derate = governing_derate(segment["id"])
    if derate == 0:
        status = "OPERATIONAL"
    elif derate >= 1:
        status = "SHUT"
    else:
        status = "DERATED"
    changed = (segment["derate_pct"] != derate) or (segment["operational_status"] != status)
    if changed:
        segment["derate_pct"] = derate
        segment["operational_status"] = status
        touch(segment)
    return changed


# ---------------------------------------------------------------------------
# Resequencing (PRD 3.8 hops three, four, five)
# ---------------------------------------------------------------------------
def affected_cycles(event, statuses):
    rows = []
    for cycle in db.cycles.values():
        if cycle["segment_id"] != event["segment_id"]:
            continue
        if cycle["status"] not in statuses:
            continue
        if not calc.windows_intersect_closed_event(cycle, event):
            continue
        rows.append(cycle)
    rows.sort(key=lambda c: (c["window_open_at"], c["created_at"], c["_seq"]))
    return rows


def resequence_cycle(cycle, segment):
    """Hops four and five: re-cut SCHEDULED nominations and clear their tickets."""
    scheduled = [n for n in cycle_nominations(cycle) if n["status"] == "SCHEDULED"]
    alloc = capacity_proration(cycle, segment, scheduled)
    revised = set()
    for nomination in scheduled:
        new_alloc = alloc.get(nomination["id"], ZERO)
        if new_alloc < nomination["allocated_bbl"]:
            nomination["allocated_bbl"] = new_alloc
            nomination["status"] = "REVISION_REQUESTED"
            nomination["revision_count"] = nomination["revision_count"] + 1
            touch(nomination)
            revised.add(nomination["id"])
    for ticket in cycle_tickets(cycle["id"]):
        if ticket["movement_status"] == "PLANNED" and ticket["nomination_id"] in revised:
            ticket["movement_status"] = "CANCELLED"
            ticket["cancel_reason"] = "RESEQUENCING"
            touch(ticket)
    recompute_totals(cycle, factor=True, transmix=True)


def maintenance_derate_cascade(event, segment):
    """Hops two through five, driven by a maintenance status transition."""
    if not recompute_segment_derate(segment):
        return
    for cycle in affected_cycles(event, ("PUBLISHED",)):
        apply_effective_capacity(cycle, segment)
        if cycle["effective_capacity_bbl"] < cycle["allocated_total_bbl"]:
            cycle["status"] = "RESEQUENCING"
            touch(cycle)
            resequence_cycle(cycle, segment)
        else:
            recompute_totals(cycle)


def maintenance_restore_cascade(event, segment):
    """Completion: RESEQUENCING cycles resize but keep their status."""
    recompute_segment_derate(segment)
    for cycle in affected_cycles(event, ("RESEQUENCING",)):
        apply_effective_capacity(cycle, segment)
        recompute_totals(cycle)


# ---------------------------------------------------------------------------
# Proration run (PRD 3.5)
# ---------------------------------------------------------------------------
def proration_input_set(cycle):
    rows = []
    resequencing = cycle["status"] == "RESEQUENCING"
    for nomination in cycle_nominations(cycle):
        status = nomination["status"]
        if status in ("ACCEPTED", "PRORATED", "SCHEDULED"):
            rows.append(nomination)
        elif resequencing and status in ("SUBMITTED", "REVISION_REQUESTED"):
            rows.append(nomination)
    return rows


def tender_minimum_of(nomination):
    tariff = pinned_tariff(nomination)
    if tariff is None:
        return None
    return tariff["tender_minimum_bbl"]


def prorate_cycle(cycle, segment):
    resequencing = cycle["status"] == "RESEQUENCING"
    apply_effective_capacity(cycle, segment)
    input_set = proration_input_set(cycle)

    if resequencing:
        survivors = []
        for nomination in input_set:
            if nomination["status"] in ("SUBMITTED", "REVISION_REQUESTED"):
                minimum = tender_minimum_of(nomination)
                if minimum is not None and nomination["nominated_bbl"] < minimum:
                    nomination["status"] = "REJECTED"
                    nomination["rejection_reason"] = "BELOW_TENDER_MINIMUM"
                    nomination["allocated_bbl"] = ZERO
                    touch(nomination)
                    continue
            survivors.append(nomination)
        input_set = survivors

    freeze_history(cycle, input_set)

    if not input_set:
        for nomination in cycle_nominations(cycle):
            if nomination["status"] in ("ACCEPTED", "PRORATED", "SCHEDULED"):
                if nomination["allocated_bbl"] != 0:
                    nomination["allocated_bbl"] = ZERO
                    touch(nomination)
        cycle["status"] = "PRORATED"
        recompute_totals(cycle)
        cycle["proration_factor"] = r6(1)
        cycle["unallocated_capacity_bbl"] = cycle["effective_capacity_bbl"]
        touch(cycle)
        return

    alloc = capacity_proration(cycle, segment, input_set)
    for nomination in input_set:
        nomination["allocated_bbl"] = alloc.get(nomination["id"], ZERO)
        touch(nomination)

    # single cleanup pass: the tender minimum enforced a second time
    for nomination in input_set:
        minimum = tender_minimum_of(nomination)
        if minimum is not None and nomination["allocated_bbl"] < minimum:
            nomination["allocated_bbl"] = ZERO
            nomination["status"] = "REJECTED"
            nomination["rejection_reason"] = "BELOW_TENDER_AFTER_PRORATION"
            touch(nomination)
        else:
            nomination["status"] = "PRORATED"
            touch(nomination)

    cycle["status"] = "PRORATED"
    recompute_totals(cycle, factor=True)


# ---------------------------------------------------------------------------
# Withdrawal re-proration (PRD 3.3 hop three)
# ---------------------------------------------------------------------------
def reprorate_after_withdrawal(cycle, segment):
    input_set = proration_input_set(cycle)
    if not input_set:
        recompute_totals(cycle, factor=True)
        return
    alloc = capacity_proration(cycle, segment, input_set)
    for nomination in input_set:
        if nomination["status"] != "PRORATED":
            continue
        new_alloc = alloc.get(nomination["id"], ZERO)
        if nomination["allocated_bbl"] != new_alloc:
            nomination["allocated_bbl"] = new_alloc
            touch(nomination)
    recompute_totals(cycle, factor=True)


# ---------------------------------------------------------------------------
# Schedule building (PRD 3.6)
# ---------------------------------------------------------------------------
def build_schedule(cycle, segment):
    planned = calc.planned_sequence(cycle, segment)
    total_transmix = sum((row[1] for row in planned), ZERO)
    if total_transmix > segment["transmix_reserve_bbl"]:
        fail("ERR_TRANSMIX_RESERVE_EXCEEDED",
             "Interface transmix of {} bbl exceeds the segment reserve of {} bbl.".format(
                 total_transmix, segment["transmix_reserve_bbl"]))

    previous_id = None
    position = 0
    for nomination, transmix, flush in planned:
        position += 1
        start = cycle["ship_start_at"] + timedelta(hours=calc.SLOT_HOURS * (position - 1))
        end = start + timedelta(hours=calc.SLOT_HOURS)
        ticket = new_row({
            "cycle_id": cycle["id"],
            "nomination_id": nomination["id"],
            "predecessor_batch_id": previous_id,
            "sequence_position": position,
            "volume_bbl": r2(nomination["allocated_bbl"]),
            "transmix_bbl": transmix,
            "requires_flush": bool(flush),
            "injection_window_start": start,
            "injection_window_end": end,
            "movement_status": "PLANNED",
            "quality_status": "PENDING",
            "measured_sulfur_ppm": None,
            "measured_rvp_psi": None,
            "retest_count": 0,
            "injected_bbl": None,
            "delivered_bbl": None,
            "cancel_reason": None,
        })
        db.batch_tickets[ticket["id"]] = ticket
        previous_id = ticket["id"]

    cycle["status"] = "SCHEDULED"
    touch(cycle)
    recompute_total_transmix(cycle)


# ---------------------------------------------------------------------------
# Settlement (PRD 3.9)
# ---------------------------------------------------------------------------
def billable_tickets(cycle_id, shipper_id):
    rows = []
    for ticket in cycle_tickets(cycle_id):
        if ticket["movement_status"] not in ("PLANNED", "INJECTED", "DELIVERED"):
            continue
        nomination = db.nominations.get(ticket["nomination_id"])
        if nomination is None or nomination["shipper_id"] != shipper_id:
            continue
        rows.append(ticket)
    return rows


def billed_shippers(cycle_id):
    ids = set()
    for ticket in cycle_tickets(cycle_id):
        if ticket["movement_status"] == "CANCELLED":
            continue
        nomination = db.nominations.get(ticket["nomination_id"])
        if nomination is None:
            continue
        ids.add(nomination["shipper_id"])
    rows = [db.shippers[i] for i in ids if i in db.shippers]
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return rows


def penalty_rate_for(cycle_id, shipper_id):
    tickets = [t for t in billable_tickets(cycle_id, shipper_id)]
    if not tickets:
        return ZERO
    tickets.sort(key=lambda t: (t["sequence_position"], t["created_at"], t["_seq"]))
    nomination = db.nominations.get(tickets[0]["nomination_id"])
    tariff = pinned_tariff(nomination) if nomination else None
    if tariff is None:
        return ZERO
    return tariff["imbalance_penalty_rate_usd_per_bbl"]


def settle_cycle(cycle, basis_mode, user_id):
    cycle_id = cycle["id"]
    shippers = billed_shippers(cycle_id)
    delivered_tickets = [t for t in cycle_tickets(cycle_id) if t["movement_status"] == "DELIVERED"]
    total_injected = sum((t["injected_bbl"] or ZERO for t in delivered_tickets), ZERO)
    total_delivered = sum((t["delivered_bbl"] or ZERO for t in delivered_tickets), ZERO)
    system_loss = r2(total_injected - total_delivered)

    per_shipper_delivered = {}
    for shipper in shippers:
        rows = [t for t in billable_tickets(cycle_id, shipper["id"])
                if t["movement_status"] == "DELIVERED"]
        per_shipper_delivered[shipper["id"]] = sum((t["delivered_bbl"] or ZERO for t in rows), ZERO)

    shares = {}
    if total_delivered == 0:
        for shipper in shippers:
            shares[shipper["id"]] = ZERO
    else:
        for shipper in shippers:
            shares[shipper["id"]] = r2(
                system_loss * Decimal(per_shipper_delivered[shipper["id"]]) / Decimal(total_delivered))
        remainder = r2(system_loss - sum(shares.values(), ZERO))
        if remainder != 0 and shippers:
            ordered = sorted(shippers,
                             key=lambda s: (-per_shipper_delivered[s["id"]],
                                            s["created_at"], s["_seq"]))
            target = ordered[0]["id"]
            shares[target] = r2(shares[target] + remainder)

    other_mode = "DELIVERED" if basis_mode == "SCHEDULED" else "SCHEDULED"
    created = []
    for shipper in shippers:
        tickets = billable_tickets(cycle_id, shipper["id"])
        chosen = tariff_charge(tickets, basis_mode)
        alternate = tariff_charge(tickets, other_mode)
        scheduled_bbl = r2(sum((t["volume_bbl"] for t in tickets), ZERO))
        delivered_bbl = r2(per_shipper_delivered[shipper["id"]])
        loss_bbl = r2(shares[shipper["id"]])
        imbalance_bbl = r2(delivered_bbl - scheduled_bbl + loss_bbl)
        if scheduled_bbl == 0:
            imbalance_pct = r6(0)
        else:
            imbalance_pct = r6(abs(imbalance_bbl) / Decimal(scheduled_bbl))
        tier, multiplier = imbalance_tier(imbalance_pct)
        rate = penalty_rate_for(cycle_id, shipper["id"])
        imbalance_charge = r2(abs(imbalance_bbl) * Decimal(rate) * multiplier)
        settlement = new_row({
            "cycle_id": cycle_id,
            "shipper_id": shipper["id"],
            "basis_mode": basis_mode,
            "scheduled_bbl": scheduled_bbl,
            "delivered_bbl": delivered_bbl,
            "loss_allocation_bbl": loss_bbl,
            "imbalance_bbl": imbalance_bbl,
            "imbalance_pct": imbalance_pct,
            "imbalance_tier": tier,
            "tariff_charge_usd": chosen,
            "alt_basis_charge_usd": alternate,
            "basis_delta_usd": r2(alternate - chosen),
            "imbalance_charge_usd": imbalance_charge,
            "total_billed_usd": r2(chosen + imbalance_charge),
            "status": "DRAFT",
            "certified_by_user_id": None,
            "invoice_number": None,
        })
        db.settlements[settlement["id"]] = settlement
        created.append(settlement)

    cycle["settled_at"] = now()
    cycle["status"] = "SETTLED"
    touch(cycle)

    for nomination in cycle_nominations(cycle):
        if nomination["status"] != "SCHEDULED":
            continue
        tickets = calc.nomination_tickets(nomination["id"])
        if tickets and all(t["movement_status"] == "DELIVERED" for t in tickets):
            nomination["status"] = "COMPLETED"
            touch(nomination)

    for shipper in shippers:
        refresh_exposure(shipper)
    return created
