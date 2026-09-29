"""Deterministic calculation rules (PRD 3.4 - 3.9)."""
from datetime import timedelta
from decimal import Decimal

from core import ZERO, db, dfloor, now, order_key, r2, r6, touch

# Status sets -----------------------------------------------------------------
TOTALS_STATUSES = ("SUBMITTED", "ACCEPTED", "PRORATED", "REVISION_REQUESTED",
                   "SCHEDULED", "COMPLETED")
BILLABLE_MOVEMENTS = ("PLANNED", "INJECTED", "DELIVERED")

NEW_SHIPPER_RESERVE_PCT = Decimal("0.10")
MIN_HISTORY_RECORDS = 2
HISTORY_LOOKBACK_DAYS = 365
SLOT_HOURS = 24
UPGRADE_MULTIPLIER = Decimal("2")
TOLERANCE_PCT = Decimal("0.005")
STANDARD_PCT = Decimal("0.02")
STANDARD_MULTIPLIER = Decimal("1.0")
PENALTY_MULTIPLIER = Decimal("2.5")
NOTICE_HOURS = 48
MAINTENANCE_BUFFER_HOURS = 24


# --- lookups -----------------------------------------------------------------
def segment_of(cycle):
    return db.segments[cycle["segment_id"]]


def cycle_nominations(cycle):
    rows = [n for n in db.nominations.values() if n["cycle_id"] == cycle["id"]]
    rows.sort(key=order_key)
    return rows


def cycle_tickets(cycle_id):
    rows = [t for t in db.batch_tickets.values() if t["cycle_id"] == cycle_id]
    rows.sort(key=order_key)
    return rows


def nomination_tickets(nomination_id):
    rows = [t for t in db.batch_tickets.values() if t["nomination_id"] == nomination_id]
    rows.sort(key=order_key)
    return rows


def grade_of_nomination(nomination):
    return db.product_grades[nomination["grade_id"]]


def pinned_tariff(nomination):
    tariff_id = nomination.get("pinned_tariff_id")
    if not tariff_id:
        return None
    return db.tariffs.get(tariff_id)


# --- calculations.effective_capacity ----------------------------------------
def effective_capacity(cycle, segment):
    linefill_makeup = segment["linefill_requirement_bbl"] - segment["linefill_bbl"]
    if linefill_makeup < 0:
        linefill_makeup = ZERO
    derated = dfloor(segment["capacity_bbl_per_cycle"] * (Decimal(1) - segment["derate_pct"]))
    value = derated - linefill_makeup - segment["transmix_reserve_bbl"]
    if value < 0:
        value = ZERO
    return dfloor(value)


def apply_effective_capacity(cycle, segment):
    cycle["effective_capacity_bbl"] = effective_capacity(cycle, segment)
    cycle["derate_pct_applied"] = r2(segment["derate_pct"])
    touch(cycle)


# --- cycle aggregates (PRD 3.4 / 2.8) ---------------------------------------
def recompute_totals(cycle, factor=False, transmix=False):
    rows = [n for n in cycle_nominations(cycle) if n["status"] in TOTALS_STATUSES]
    nominated_total = sum((n["nominated_bbl"] for n in rows), ZERO)
    allocated_total = sum((n["allocated_bbl"] for n in rows), ZERO)
    cycle["nominated_total_bbl"] = r2(nominated_total)
    cycle["allocated_total_bbl"] = allocated_total
    cycle["unallocated_capacity_bbl"] = cycle["effective_capacity_bbl"] - allocated_total
    if factor:
        if nominated_total == 0:
            cycle["proration_factor"] = r6(1)
        else:
            cycle["proration_factor"] = r6(Decimal(allocated_total) / Decimal(nominated_total))
    if transmix:
        recompute_total_transmix(cycle)
    touch(cycle)


def recompute_total_transmix(cycle):
    total = sum((t["transmix_bbl"] for t in cycle_tickets(cycle["id"])
                 if t["movement_status"] != "CANCELLED"), ZERO)
    cycle["total_transmix_bbl"] = total
    touch(cycle)


# --- calculations.shipper_history_base --------------------------------------
def shipper_history_base(cycle, nomination):
    lower = cycle["window_open_at"] - timedelta(days=HISTORY_LOOKBACK_DAYS)
    upper = cycle["window_open_at"]
    qualifying = [
        h for h in db.shipping_history.values()
        if h["shipper_id"] == nomination["shipper_id"]
        and h["segment_id"] == cycle["segment_id"]
        and h["record_status"] == "FINAL"
        and h["cycle_end_at"] >= lower
        and h["cycle_end_at"] < upper
    ]
    count = len(qualifying)
    if count == 0:
        base = ZERO
    else:
        total = sum((h["actual_shipped_bbl"] for h in qualifying), ZERO)
        base = r2(Decimal(total) / Decimal(count))
    allocation_class = "HISTORICAL" if count >= MIN_HISTORY_RECORDS else "NEW_SHIPPER"
    return base, allocation_class


def freeze_history(cycle, nominations):
    for nomination in nominations:
        base, klass = shipper_history_base(cycle, nomination)
        if nomination["history_base_bbl"] != base or nomination["allocation_class"] != klass:
            touch(nomination)
        nomination["history_base_bbl"] = base
        nomination["allocation_class"] = klass


# --- calculations.capacity_proration ----------------------------------------
def capacity_proration(cycle, segment, input_set):
    """Returns {nomination_id: Decimal allocation}. Whole barrels."""
    capacity = Decimal(cycle["effective_capacity_bbl"])
    alloc = {}
    if not input_set:
        return alloc

    if segment["proration_policy"] == "HISTORY_WEIGHTED":
        new_pool = dfloor(capacity * NEW_SHIPPER_RESERVE_PCT)
        hist_pool = capacity - new_pool
        historical = [n for n in input_set if n["allocation_class"] == "HISTORICAL"]
        newcomers = [n for n in input_set if n["allocation_class"] != "HISTORICAL"]
        weights = {}
        for nomination in historical:
            weights[nomination["id"]] = min(nomination["nominated_bbl"],
                                            nomination["history_base_bbl"])
        total_weight = sum((weights[n["id"]] for n in historical), ZERO)
        for nomination in historical:
            if total_weight == 0:
                raw = ZERO
            else:
                raw = hist_pool * Decimal(weights[nomination["id"]]) / Decimal(total_weight)
            alloc[nomination["id"]] = min(nomination["nominated_bbl"], dfloor(raw))
        leftover_hist = hist_pool - sum((alloc[n["id"]] for n in historical), ZERO)
        if newcomers:
            raw_new = new_pool / Decimal(len(newcomers))
            for nomination in newcomers:
                alloc[nomination["id"]] = min(nomination["nominated_bbl"], dfloor(raw_new))
            leftover_new = new_pool - sum((alloc[n["id"]] for n in newcomers), ZERO)
        else:
            leftover_new = new_pool
        leftover = leftover_hist + leftover_new
    else:
        total_nominated = sum((n["nominated_bbl"] for n in input_set), ZERO)
        for nomination in input_set:
            if total_nominated == 0:
                raw = ZERO
            else:
                raw = capacity * Decimal(nomination["nominated_bbl"]) / Decimal(total_nominated)
            alloc[nomination["id"]] = min(nomination["nominated_bbl"], dfloor(raw))
        leftover = capacity - sum((alloc[n["id"]] for n in input_set), ZERO)

    # single redistribution pass, identical under both variants
    eligible = [n for n in input_set if alloc[n["id"]] < n["nominated_bbl"]]
    eligible.sort(key=lambda n: (-(n["nominated_bbl"] - alloc[n["id"]]),
                                 n["created_at"], n["_seq"]))
    for nomination in eligible:
        if leftover <= 0:
            break
        unmet = nomination["nominated_bbl"] - alloc[nomination["id"]]
        give = unmet if unmet < leftover else leftover
        alloc[nomination["id"]] = alloc[nomination["id"]] + give
        leftover = leftover - give
    return alloc


# --- calculations.interface_transmix ----------------------------------------
def interface_transmix(segment, own_rank, upstream_rank):
    gap = abs(own_rank - upstream_rank)
    if gap == 0:
        return ZERO, False
    if own_rank > upstream_rank:
        return dfloor(segment["transmix_cut_bbl"] * Decimal(gap)), False
    volume = dfloor(segment["transmix_cut_bbl"] * Decimal(gap) * UPGRADE_MULTIPLIER)
    return volume, gap >= 2


# --- calculations.batch_sequencing ------------------------------------------
def sequence_input(cycle):
    rows = [n for n in cycle_nominations(cycle)
            if n["status"] == "PRORATED" and n["allocated_bbl"] > 0]
    rows.sort(key=lambda n: (grade_of_nomination(n)["sequence_rank"],
                             -n["allocated_bbl"], n["created_at"], n["_seq"]))
    return rows


def planned_sequence(cycle, segment):
    """Returns a list of (nomination, transmix_bbl, requires_flush) in sequence order."""
    linefill_rank = db.product_grades[segment["linefill_grade_id"]]["sequence_rank"]
    result = []
    upstream = linefill_rank
    for nomination in sequence_input(cycle):
        own = grade_of_nomination(nomination)["sequence_rank"]
        volume, flush = interface_transmix(segment, own, upstream)
        result.append((nomination, volume, flush))
        upstream = own
    return result


# --- calculations.tariff_pinning --------------------------------------------
def pin_candidates(cycle, nomination):
    close_at = cycle["window_close_at"]
    candidates = [
        t for t in db.tariffs.values()
        if t["segment_id"] == cycle["segment_id"]
        and t["grade_id"] == nomination["grade_id"]
        and t["status"] == "EFFECTIVE"
        and t["effective_from"] <= close_at
        and (t["effective_to"] is None or t["effective_to"] > close_at)
    ]
    candidates.sort(key=lambda t: (t["effective_from"], t["created_at"], t["_seq"]),
                    reverse=True)
    return candidates


# --- calculations.shipper_exposure ------------------------------------------
def ticket_line_value(ticket):
    nomination = db.nominations.get(ticket["nomination_id"])
    if nomination is None:
        return ZERO
    tariff = pinned_tariff(nomination)
    if tariff is None:
        return ZERO
    return r2(Decimal(ticket["volume_bbl"]) * Decimal(tariff["base_rate_usd_per_bbl"]))


def shipper_exposure(shipper):
    total = ZERO
    for ticket in db.batch_tickets.values():
        if ticket["movement_status"] not in ("INJECTED", "DELIVERED"):
            continue
        nomination = db.nominations.get(ticket["nomination_id"])
        if nomination is None or nomination["shipper_id"] != shipper["id"]:
            continue
        cycle = db.cycles.get(ticket["cycle_id"])
        if cycle is None or cycle["status"] == "SETTLED":
            continue
        total = total + ticket_line_value(ticket)
    return r2(total)


def refresh_exposure(shipper):
    value = shipper_exposure(shipper)
    if shipper["exposure_usd"] != value:
        shipper["exposure_usd"] = value
        touch(shipper)


# --- calculations.shipper_notification_scope --------------------------------
def windows_intersect_closed_event(cycle, event):
    """[ship_start, ship_end) vs closed [window_start, window_end]."""
    return cycle["ship_start_at"] <= event["window_end"] and event["window_start"] < cycle["ship_end_at"]


def notification_scope(event):
    statuses = ("PRORATED", "SCHEDULED", "PUBLISHED", "RESEQUENCING")
    shippers = set()
    for cycle in db.cycles.values():
        if cycle["segment_id"] != event["segment_id"]:
            continue
        if cycle["status"] not in statuses:
            continue
        if not windows_intersect_closed_event(cycle, event):
            continue
        for nomination in cycle_nominations(cycle):
            if nomination["status"] in ("PRORATED", "SCHEDULED", "REVISION_REQUESTED"):
                shippers.add(nomination["shipper_id"])
    return len(shippers)


# --- calculations.terminal_bay_occupancy ------------------------------------
def bay_occupancy(ticket, origin_terminal_id, start, end):
    count = 0
    for peer in db.batch_tickets.values():
        if peer["id"] == ticket["id"]:
            continue
        if peer["movement_status"] != "PLANNED":
            continue
        peer_nomination = db.nominations.get(peer["nomination_id"])
        if peer_nomination is None:
            continue
        if peer_nomination["origin_terminal_id"] != origin_terminal_id:
            continue
        if peer["injection_window_start"] is None or peer["injection_window_end"] is None:
            continue
        if peer["injection_window_start"] < end and start < peer["injection_window_end"]:
            count += 1
    return count


# --- calculations.tariff_charge ---------------------------------------------
def billable_volume(ticket, tariff, basis_mode):
    if basis_mode == "DELIVERED":
        measured = ticket["delivered_bbl"] if ticket["delivered_bbl"] is not None else ZERO
    else:
        measured = ticket["volume_bbl"]
    floor_value = tariff["tender_minimum_bbl"]
    return measured if measured > floor_value else floor_value


def tariff_rate(tariff, volume):
    if volume >= tariff["tier2_min_bbl"]:
        return tariff["tier2_rate_usd_per_bbl"]
    if volume >= tariff["tier1_min_bbl"]:
        return tariff["tier1_rate_usd_per_bbl"]
    return tariff["base_rate_usd_per_bbl"]


def tariff_charge(tickets, basis_mode):
    total = ZERO
    for ticket in tickets:
        nomination = db.nominations.get(ticket["nomination_id"])
        tariff = pinned_tariff(nomination) if nomination else None
        if tariff is None:
            continue
        volume = billable_volume(ticket, tariff, basis_mode)
        rate = tariff_rate(tariff, volume)
        total = total + r2(Decimal(volume) * Decimal(rate))
    return r2(total)


def imbalance_tier(pct):
    if pct <= TOLERANCE_PCT:
        return "TOLERANCE", ZERO
    if pct <= STANDARD_PCT:
        return "STANDARD", STANDARD_MULTIPLIER
    return "PENALTY", PENALTY_MULTIPLIER
