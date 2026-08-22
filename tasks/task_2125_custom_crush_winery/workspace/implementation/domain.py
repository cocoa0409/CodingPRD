"""Entity lookups, derived-field reconciliation, cascades and serialization."""

from decimal import Decimal

import calc
import errors as E
from errors import ApiError
from store import db, iso, public, rhu, sort_key, touch, whole_days

D = Decimal

LIVE_ALLOCATION_STATUSES = ("RESERVED", "COMMITTED")


# ---------------------------------------------------------------------------
# Lookups (ladder rungs 10 and 15 -- the same code serves path ids and body FKs)
# ---------------------------------------------------------------------------
def _find(table, entity_id, error_id):
    if not isinstance(entity_id, str):
        raise ApiError(error_id)
    found = table.get(entity_id)
    if found is None:
        raise ApiError(error_id)
    return found


def get_client(cid):
    return _find(db.clients, cid, E.ERR_CLIENT_NOT_FOUND)


def get_contract(cid):
    return _find(db.contracts, cid, E.ERR_CONTRACT_NOT_FOUND)


def get_vessel(vid):
    return _find(db.vessels, vid, E.ERR_VESSEL_NOT_FOUND)


def get_allocation(aid):
    return _find(db.allocations, aid, E.ERR_ALLOCATION_NOT_FOUND)


def get_intake(iid):
    return _find(db.intakes, iid, E.ERR_INTAKE_NOT_FOUND)


def get_lot(lid):
    return _find(db.lots, lid, E.ERR_LOT_NOT_FOUND)


def get_trial(tid):
    return _find(db.trials, tid, E.ERR_TRIAL_NOT_FOUND)


def get_work_order(wid):
    return _find(db.work_orders, wid, E.ERR_WORK_ORDER_NOT_FOUND)


def get_line(lid):
    return _find(db.lines, lid, E.ERR_LINE_NOT_FOUND)


def get_run(rid):
    return _find(db.runs, rid, E.ERR_RUN_NOT_FOUND)


def get_dry_goods(did):
    return _find(db.dry_goods, did, E.ERR_DRY_GOODS_ITEM_NOT_FOUND)


def get_report(rid):
    return _find(db.reports, rid, E.ERR_TTB_REPORT_NOT_FOUND)


def get_release_order(rid):
    return _find(db.release_orders, rid, E.ERR_RELEASE_ORDER_NOT_FOUND)


# ---------------------------------------------------------------------------
# Ownership resolution
# ---------------------------------------------------------------------------
def contract_client_id(contract):
    return contract.get("client_id")


def lot_client_id(lot):
    contract = db.contracts.get(lot.get("contract_id"))
    return contract.get("client_id") if contract else None


def trial_client_id(trial):
    contract = db.contracts.get(trial.get("contract_id"))
    return contract.get("client_id") if contract else None


def allocation_client_id(allocation):
    contract = db.contracts.get(allocation.get("contract_id"))
    return contract.get("client_id") if contract else None


def intake_client_id(intake):
    contract = db.contracts.get(intake.get("contract_id"))
    return contract.get("client_id") if contract else None


def work_order_client_id(order):
    lot = db.lots.get(order.get("lot_id"))
    return lot_client_id(lot) if lot else None


def run_client_id(run):
    lot = db.lots.get(run.get("lot_id"))
    return lot_client_id(lot) if lot else None


def release_order_client_id(order):
    lot = db.lots.get(order.get("lot_id"))
    return lot_client_id(lot) if lot else None


def client_contracts(client_id):
    return sorted((c for c in db.contracts.values() if c["client_id"] == client_id),
                  key=sort_key)


def client_lots(client_id):
    contract_ids = {c["id"] for c in db.contracts.values()
                    if c["client_id"] == client_id}
    return sorted((l for l in db.lots.values() if l["contract_id"] in contract_ids),
                  key=sort_key)


def contract_allocations(contract_id):
    return sorted((a for a in db.allocations.values()
                   if a["contract_id"] == contract_id), key=sort_key)


def client_release_orders(client_id):
    lot_ids = {l["id"] for l in client_lots(client_id)}
    return sorted((o for o in db.release_orders.values() if o["lot_id"] in lot_ids),
                  key=sort_key)


def client_runs(client_id):
    lot_ids = {l["id"] for l in client_lots(client_id)}
    return sorted((r for r in db.runs.values() if r["lot_id"] in lot_ids),
                  key=sort_key)


def client_trials(client_id):
    contract_ids = {c["id"] for c in db.contracts.values()
                    if c["client_id"] == client_id}
    return sorted((t for t in db.trials.values() if t["contract_id"] in contract_ids),
                  key=sort_key)


def client_reports(client_id):
    return sorted((r for r in db.reports.values() if r["client_id"] == client_id),
                  key=sort_key)


# ---------------------------------------------------------------------------
# Derived / reconciled projections
# ---------------------------------------------------------------------------
def bond_gallons_in_bond(client_id):
    total = sum((D(l["volume_gallons"]) for l in client_lots(client_id)
                 if l["bond_status"] == "IN_BOND"), D(0))
    return rhu(total, 2)


def taxpaid_gallons_ytd(client_id):
    year = db.now().year
    total = D(0)
    for order in client_release_orders(client_id):
        if order["status"] != "EXECUTED":
            continue
        if order["release_type"] != "TAXPAID_REMOVAL":
            continue
        executed = order.get("_executed_dt")
        if executed is not None and executed.year == year:
            total += D(order["gallons"])
    return rhu(total, 2)


def last_filed_period_end(client_id):
    filed = [r for r in client_reports(client_id) if r["status"] == "FILED"]
    if not filed:
        return None
    filed.sort(key=lambda r: (r["_pe_dt"], -r["_seq"]), reverse=True)
    return filed[0]["period_end"]


def recompute_contract_counters(contract):
    """gallons_allocated / barrel_slots_used from the surviving live allocations."""
    gallons = D(0)
    slots = 0
    for allocation in contract_allocations(contract["id"]):
        if allocation["status"] not in LIVE_ALLOCATION_STATUSES:
            continue
        vessel = db.vessels.get(allocation["vessel_id"])
        if vessel is None:
            continue
        if vessel["vessel_type"] == "TANK":
            gallons += D(allocation["allocated_gallons"])
        elif vessel["vessel_type"] == "BARREL":
            slots += 1
    contract["gallons_allocated"] = rhu(gallons, 2)
    contract["barrel_slots_used"] = slots


def recompute_contract_counters_and_touch(contract):
    recompute_contract_counters(contract)
    touch(contract)


def recompute_dry_goods(item):
    item["available_units"] = item["on_hand_units"] - item["reserved_units"]


def book_loss(client_id, gallons):
    if client_id is None:
        return
    db.loss_events.append({
        "client_id": client_id,
        "at": db.now(),
        "gallons": D(gallons),
    })


# ---------------------------------------------------------------------------
# Shared cascade: ending a vessel occupancy
# ---------------------------------------------------------------------------
def release_allocation(allocation, clear_lot_housing, recompute_contract=True):
    """The release side effects: allocation, vessel and contract counters.

    `clear_lot_housing` is true only for the directly requested RELEASE, which
    additionally clears the housed lot's current_vessel_id.
    """
    now = db.now()
    allocation["status"] = "RELEASED"
    allocation["released_at"] = iso(now)
    allocation["_released_dt"] = now
    allocation["occupied_days"] = whole_days(allocation.get("_committed_dt"), now)
    touch(allocation)

    if clear_lot_housing and allocation.get("lot_id"):
        lot = db.lots.get(allocation["lot_id"])
        if lot is not None:
            lot["current_vessel_id"] = None
            touch(lot)

    vessel = db.vessels.get(allocation["vessel_id"])
    if vessel is not None:
        vessel["condition"] = "DIRTY"
        vessel["last_released_at"] = allocation["end_at"]
        touch(vessel)

    if recompute_contract:
        contract = db.contracts.get(allocation["contract_id"])
        if contract is not None:
            recompute_contract_counters_and_touch(contract)
    return allocation


def committed_allocation_for_lot(lot_id):
    for allocation in sorted(db.allocations.values(), key=sort_key):
        if allocation["lot_id"] == lot_id and allocation["status"] == "COMMITTED":
            return allocation
    return None


def cascade_lot_left_vessel(lot, recompute_contract=True):
    """A housed lot left its vessel by itself (blend merge / bottling run)."""
    allocation = committed_allocation_for_lot(lot["id"])
    if allocation is None:
        return None
    return release_allocation(allocation, clear_lot_housing=False,
                              recompute_contract=recompute_contract)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize_client(client):
    data = public(client)
    data["bond_gallons_in_bond"] = bond_gallons_in_bond(client["id"])
    data["taxpaid_gallons_ytd"] = taxpaid_gallons_ytd(client["id"])
    data["last_filed_period_end"] = last_filed_period_end(client["id"])
    return data


def serialize_lot(lot):
    data = public(lot)
    aging_start = lot.get("_aging_dt")
    data["aging_days"] = whole_days(aging_start, db.now()) if aging_start else 0
    return data


def serialize(entity):
    return public(entity)


# ---------------------------------------------------------------------------
# Traceability (GET /lots/{id}/traceability)
# ---------------------------------------------------------------------------
def traceability(lot):
    manifest = lot.get("component_manifest") or []
    if lot["origin"] == "INTAKE":
        total = D(0)
        for intake_id in lot.get("source_intake_ids") or []:
            intake = db.intakes.get(intake_id)
            if intake is not None:
                total += D(intake["estimated_gallons"])
        ancestors = []
    else:
        total = sum((D(entry["volume_gallons"]) for entry in manifest), D(0))
        ancestors = []
        seen = set()
        frontier = [entry["source_lot_id"] for entry in manifest]
        while frontier:
            nxt = []
            for lot_id in frontier:
                if lot_id in seen:
                    continue
                seen.add(lot_id)
                ancestors.append(lot_id)
                parent = db.lots.get(lot_id)
                if parent is not None:
                    for entry in parent.get("component_manifest") or []:
                        nxt.append(entry["source_lot_id"])
            frontier = nxt
    return {
        "lot_id": lot["id"],
        "origin": lot["origin"],
        "source_intake_ids": list(lot.get("source_intake_ids") or []),
        "component_manifest": [dict(entry) for entry in manifest],
        "ancestor_lot_ids": ancestors,
        "total_source_gallons": rhu(total, 2),
    }


# ---------------------------------------------------------------------------
# Storage accrual projection (both variants)
# ---------------------------------------------------------------------------
def storage_projection(contract, through_dt, variant):
    base = contract.get("_billed_through_dt") or contract.get("_eff_from_dt")
    rate = contract["storage_rate_cents_per_gallon_month"]
    charge = 0
    subject_count = 0

    if variant == "VESSEL_FOOTPRINT":
        for allocation in contract_allocations(contract["id"]):
            if allocation["status"] not in ("COMMITTED", "RELEASED"):
                continue
            clock_start = allocation.get("_committed_dt")
            if clock_start is None:
                continue
            subject_count += 1
            window_from = _later(clock_start, base)
            days = whole_days(window_from, through_dt)
            charge += calc.storage_charge(allocation["allocated_gallons"], rate, days)
    else:
        contract_lots = sorted(
            (l for l in db.lots.values() if l["contract_id"] == contract["id"]),
            key=sort_key)
        for lot in contract_lots:
            if lot["bond_status"] not in ("IN_BOND", "TAX_DETERMINED"):
                continue
            if lot["production_status"] == "CONSUMED":
                continue
            clock_start = lot.get("_aging_dt")
            if clock_start is None:
                continue
            subject_count += 1
            window_from = _later(clock_start, base)
            days = whole_days(window_from, through_dt)
            charge += calc.storage_charge(lot["volume_gallons"], rate, days)

    return subject_count, charge


def _later(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return a if a > b else b


# ---------------------------------------------------------------------------
# TTB reconciliation (both variants)
# ---------------------------------------------------------------------------
def ttb_reconciliation(report):
    client_id = report["client_id"]
    period_start = report["_ps_dt"]
    period_end = report["_pe_dt"]
    variant = report.get("variant") or "BONDED"

    def in_window(moment):
        return moment is not None and period_start <= moment < period_end

    # opening_gallons -- the closing count of the latest previously FILED report.
    opening = D(0)
    candidates = [r for r in client_reports(client_id)
                  if r["id"] != report["id"] and r["status"] == "FILED"
                  and r["_pe_dt"] <= period_start]
    if candidates:
        candidates.sort(key=lambda r: (r["_pe_dt"], -r["_seq"]), reverse=True)
        opening = D(candidates[0]["closing_gallons"])

    removed_taxpaid = D(0)
    removed_in_bond = D(0)
    for order in client_release_orders(client_id):
        if order["status"] != "EXECUTED" or not in_window(order.get("_executed_dt")):
            continue
        if order["release_type"] == "TAXPAID_REMOVAL":
            removed_taxpaid += D(order["gallons"])
        else:
            removed_in_bond += D(order["gallons"])

    lots = client_lots(client_id)
    closing = sum((D(l["volume_gallons"]) for l in lots
                   if l["bond_status"] == "IN_BOND"), D(0))

    produced = sum((D(l["_created_volume"]) for l in lots
                    if l["origin"] == "INTAKE" and in_window(l.get("_created_dt"))),
                   D(0))

    losses = sum((D(event["gallons"]) for event in db.loss_events
                  if event["client_id"] == client_id and in_window(event["at"])), D(0))
    packaged = sum((D(r["gallons_consumed"]) for r in client_runs(client_id)
                    if r["status"] == "COMPLETED" and in_window(r.get("_completed_dt"))),
                   D(0))
    loss = losses + packaged

    if variant == "GROSS":
        produced += sum((D(l["_created_volume"]) for l in lots
                         if l["origin"] == "BLEND" and in_window(l.get("_created_dt"))),
                        D(0))
        executed_trials = [t for t in client_trials(client_id)
                           if t.get("_executed_dt") is not None
                           and in_window(t["_executed_dt"])]
        loss -= sum((D(t["projected_loss_gallons"]) for t in executed_trials), D(0))
        loss += sum((D(t["total_component_gallons"]) for t in executed_trials), D(0))

    opening = rhu(opening, 2)
    produced = rhu(produced, 2)
    removed_taxpaid = rhu(removed_taxpaid, 2)
    removed_in_bond = rhu(removed_in_bond, 2)
    loss = rhu(loss, 2)
    closing = rhu(closing, 2)
    variance = rhu(
        closing - (opening + produced - removed_taxpaid - removed_in_bond - loss), 2)

    report["opening_gallons"] = opening
    report["produced_gallons"] = produced
    report["removed_taxpaid_gallons"] = removed_taxpaid
    report["removed_in_bond_gallons"] = removed_in_bond
    report["loss_gallons"] = loss
    report["closing_gallons"] = closing
    report["variance_gallons"] = variance
    return report
