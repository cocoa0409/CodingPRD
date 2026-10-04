"""Cross-entity cascades and clock sweeps (PRD 2.4, 2.10, 3.2, 3.4)."""

from datetime import timedelta

from calc import allocate_order_lines, fefo_allocate, uptime_credit
from store import DB, now, touch


def _program_adjust_pipeline(program_id, delta):
    if not program_id:
        return
    prog = DB["programs"].get(program_id)
    if prog is not None:
        prog["pipeline_spend_cents"] += delta
        touch(prog)


def _apply_reservations(order, reservations):
    for r in reservations:
        lot = DB["lots"][r["lot_id"]]
        lot["reserved_units"] += r["quantity"]
        touch(lot)


def release_lot_reservations_and_backorder(failed_lot):
    """Field corrective action / expiry sweep on a released lot.

    Hop 1: release every reservation on this lot.
    Hop 2: each ALLOCATED order that held a reservation and cannot be fully
    re-allocated from remaining usable lots -> BACKORDERED, all reservations
    released, attributed amount leaves the program pipeline.
    """
    affected = [
        o
        for o in DB["orders"].values()
        if o["order_state"] == "ALLOCATED"
        and any(r["lot_id"] == failed_lot["id"] for r in o["line_reservations"])
    ]
    affected.sort(key=lambda o: (o["created_at"], o["_seq"]))
    for order in affected:
        kept = []
        for r in order["line_reservations"]:
            if r["lot_id"] == failed_lot["id"]:
                failed_lot["reserved_units"] -= r["quantity"]
            else:
                kept.append(r)
        order["line_reservations"] = kept
        # shortage per kit_code after losing this lot's reservations
        need = {}
        for ln in order["lines"]:
            need[ln["kit_code"]] = need.get(ln["kit_code"], 0) + ln["quantity"]
        have = {}
        for r in kept:
            have[r["kit_code"]] = have.get(r["kit_code"], 0) + r["quantity"]
        pending = {}
        new_reservations = []
        satisfiable = True
        for kit_code, qty in need.items():
            shortage = qty - have.get(kit_code, 0)
            if shortage <= 0:
                continue
            takes = fefo_allocate(kit_code, shortage, pending)
            if takes is None:
                satisfiable = False
                break
            new_reservations.extend(takes)
        if satisfiable:
            _apply_reservations(order, new_reservations)
            order["line_reservations"].extend(new_reservations)
            touch(order)
        else:
            for r in list(order["line_reservations"]):
                lot = DB["lots"][r["lot_id"]]
                lot["reserved_units"] -= r["quantity"]
                touch(lot)
            order["line_reservations"] = []
            order["order_state"] = "BACKORDERED"
            _program_adjust_pipeline(order["program_id"], -order["attributed_total_cents"])
            touch(order)


def reallocation_sweep():
    """On a QC_PASSED verdict: BACKORDERED orders whose lines can now be fully
    satisfied are re-allocated in created_at ASC order (FEFO per line)."""
    backordered = [o for o in DB["orders"].values() if o["order_state"] == "BACKORDERED"]
    backordered.sort(key=lambda o: (o["created_at"], o["_seq"]))
    for order in backordered:
        reservations = allocate_order_lines(order["lines"])
        if reservations is None:
            continue
        _apply_reservations(order, reservations)
        order["line_reservations"] = reservations
        order["order_state"] = "ALLOCATED"
        _program_adjust_pipeline(order["program_id"], order["attributed_total_cents"])
        touch(order)


def decommission_instrument(instrument):
    """PRD 3.2 decommission cascade: stamp decommissioned_at, close any open
    service window at the same instant, terminate ACTIVE contracts with a final
    uptime reconciliation, and post the credits to the contract's account."""
    t = now()
    instrument["decommissioned_at"] = t
    for w in instrument["service_windows"]:
        if w["closed_at"] is None:
            w["closed_at"] = t
    instrument["install_state"] = "DECOMMISSIONED"
    for contract in list(DB["contracts"].values()):
        if contract["instrument_id"] != instrument["id"]:
            continue
        if contract["contract_state"] != "ACTIVE":
            continue
        contract["contract_state"] = "TERMINATED"
        contract["terminated_reason"] = "AUTO_DECOMMISSION"
        period_start = contract["last_reconciliation_end"] or contract["coverage_start"]
        if contract["coverage_start"] > period_start:
            period_start = contract["coverage_start"]
        credit = 0
        if t > period_start:
            _, _, credit = uptime_credit(contract, instrument, period_start, t)
        contract["credits_issued_ytd_cents"] += credit
        touch(contract)
        if credit:
            account = DB["accounts"].get(contract["account_id"])
            if account is not None:
                account["credit_balance_cents"] += credit
                touch(account)
    touch(instrument)


def run_clock_sweeps():
    """Expiry sweeps fired by POST /genomics/_clock/set_current_utc."""
    t = now()
    lots_expired = 0
    contracts_expired = 0
    transitions_expired = 0
    for lot in list(DB["lots"].values()):
        if lot["qc_status"] == "QC_PASSED" and lot["expiry_date"] <= t:
            lot["qc_status"] = "EXPIRED"
            release_lot_reservations_and_backorder(lot)
            touch(lot)
            lots_expired += 1
    for contract in list(DB["contracts"].values()):
        if contract["contract_state"] == "ACTIVE" and contract["coverage_end"] <= t:
            contract["contract_state"] = "EXPIRED"
            touch(contract)
            contracts_expired += 1
    for prog in list(DB["transitions"].values()):
        if prog["program_state"] == "ENROLLED" and t > prog["enrollment_window_end"]:
            prog["program_state"] = "EXPIRED"
            touch(prog)
            transitions_expired += 1
        elif (
            prog["program_state"] == "APPRAISED"
            and prog["appraised_at"] is not None
            and t > prog["appraised_at"] + timedelta(days=30)
        ):
            prog["program_state"] = "EXPIRED"
            touch(prog)
            transitions_expired += 1
    return lots_expired, contracts_expired, transitions_expired
