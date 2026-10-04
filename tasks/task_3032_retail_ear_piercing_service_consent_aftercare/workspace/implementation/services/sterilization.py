"""Sterilization cycles, lot traceability and their cascades (PRD 2.7)."""

import db
import errors as E
import calculations as calc
from services import common


def _lot_rows_of_cycle(cycle_id):
    return [lot for lot in db.DB.lots.values()
            if lot.sterilization_cycle_id == cycle_id]


def validate_autoclave_window(autoclave_unit_id, start_at, end_at):
    """Closed-interval overlap on the same autoclave unit (scaffold 1.2).

    Both endpoints are inclusive, so touching intervals are rejected too.
    """
    start = db.floor_to_second(start_at)
    end = db.floor_to_second(end_at)
    for cycle in db.DB.cycles.values():
        if cycle.autoclave_unit_id != autoclave_unit_id:
            continue
        other_start = db.parse_instant(cycle.cycle_start_at)
        other_end = db.parse_instant(cycle.cycle_end_at)
        if other_start is None or other_end is None:
            continue
        other_start = db.floor_to_second(other_start)
        other_end = db.floor_to_second(other_end)
        if start <= other_end and other_start <= end:
            E.fail(E.ERR_AUTOCLAVE_CYCLE_OVERLAP,
                   "The cycle interval overlaps an existing cycle on this autoclave")


def complete_cycle(cycle, temperature_celsius, biological_indicator_passed):
    """IN_PROGRESS -> PASSED or FAILED, with the failure cascade chain."""
    if cycle.status != "IN_PROGRESS":
        E.fail(E.ERR_INVALID_STATE, "Cycle is not IN_PROGRESS")

    start = db.parse_instant(cycle.cycle_start_at)
    end = db.parse_instant(cycle.cycle_end_at)
    if start is not None and end is not None:
        _validate_no_overlap_excluding(cycle, start, end)

    cycle.temperature_celsius = temperature_celsius
    cycle.biological_indicator_passed = biological_indicator_passed
    cycle.touch()

    if temperature_celsius >= 134.0 and biological_indicator_passed is True:
        cycle.status = "PASSED"
        cycle.touch()
        for lot in _lot_rows_of_cycle(cycle.id):
            lot.status = "AVAILABLE"
            lot.units_available = lot.units_received
            lot.touch()
        return cycle

    cycle.status = "FAILED"
    cycle.touch()
    _run_failure_cascade(cycle)
    return cycle


def _validate_no_overlap_excluding(cycle, start, end):
    start = db.floor_to_second(start)
    end = db.floor_to_second(end)
    for other in db.DB.cycles.values():
        if other.id == cycle.id:
            continue
        if other.autoclave_unit_id != cycle.autoclave_unit_id:
            continue
        other_start = db.parse_instant(other.cycle_start_at)
        other_end = db.parse_instant(other.cycle_end_at)
        if other_start is None or other_end is None:
            continue
        if start <= db.floor_to_second(other_end) and db.floor_to_second(other_start) <= end:
            E.fail(E.ERR_AUTOCLAVE_CYCLE_OVERLAP,
                   "The cycle interval overlaps another cycle on this autoclave")


def _run_failure_cascade(cycle):
    """FAILED cycle -> bound lots QUARANTINED -> store posture -> piercer score."""
    store = db.DB.stores.get(cycle.store_location_id)
    affected_stores = set()

    for lot in _lot_rows_of_cycle(cycle.id):
        common.quarantine_lot(lot)
        affected_stores.add(lot.store_location_id)
        if store is None or lot.store_location_id != store.id:
            lot_store = db.DB.stores.get(lot.store_location_id)
            if lot_store is not None:
                lot_store.open_incident_count += 1
                lot_store.touch()
                common.recompute_store_posture(lot_store)

    if store is not None:
        common.recompute_store_posture(store)

    for store_id in affected_stores:
        _apply_piercer_penalty(store_id)


def _apply_piercer_penalty(store_id):
    """Every ACTIVE piercer rostered to the store loses 20 eligibility points."""
    for piercer in list(db.DB.piercers.values()):
        if piercer.home_store_id != store_id or piercer.status != "ACTIVE":
            continue
        piercer.eligibility_score = max(piercer.eligibility_score - 20, 0)
        piercer.touch()
        if piercer.eligibility_score < 60:
            common.cascade_customer_flags(piercer.id)
        common.evaluate_piercer_suspension(piercer)


def quarantine_cycle(cycle):
    """PASSED -> QUARANTINED, with lot quarantine and exposure recording."""
    if cycle.status != "PASSED":
        E.fail(E.ERR_INVALID_STATE, "Cycle is not PASSED")
    cycle.quarantine_scope_units = calc.quarantine_unit_exposure(db.DB, cycle.id)
    cycle.status = "QUARANTINED"
    cycle.touch()

    for lot in _lot_rows_of_cycle(cycle.id):
        _quarantine_and_flag_consumed(lot)
    return cycle


def _quarantine_and_flag_consumed(lot):
    """Quarantine a lot; file a MODERATE incident per already-consumed session."""
    consumed_sessions = []
    if lot.units_consumed > 0:
        consumed_sessions = [s for s in db.DB.sessions.values()
                             if s.cartridge_lot_id == lot.id
                             and s.service_status in ("IN_PROGRESS", "COMPLETED")]
        consumed_sessions.sort(key=lambda s: (s.created_at, s.id))

    common.quarantine_lot(lot)

    for session in consumed_sessions:
        common.file_incident(session.id, "MODERATE", [])
        store = common.session_store(session)
        if store is not None:
            store.open_incident_count += 1
            store.touch()
            common.recompute_store_posture(store)

    if not consumed_sessions:
        store = db.DB.stores.get(lot.store_location_id)
        if store is not None:
            common.recompute_store_posture(store)


def release_cycle(cycle):
    if cycle.status != "QUARANTINED":
        E.fail(E.ERR_INVALID_STATE, "Cycle is not QUARANTINED")
    if cycle.temperature_celsius is None or cycle.temperature_celsius < 134.0:
        E.fail(E.ERR_INVALID_STATE, "temperature_celsius must be at least 134.0")
    if cycle.biological_indicator_passed is not True:
        E.fail(E.ERR_INVALID_STATE, "biological_indicator_passed must be true")
    cycle.status = "RELEASED"
    cycle.touch()
    for lot in _lot_rows_of_cycle(cycle.id):
        if lot.status == "QUARANTINED":
            common.release_lot(lot)
    return cycle


def recall_cycle(cycle):
    if cycle.status != "RELEASED":
        E.fail(E.ERR_INVALID_STATE, "Cycle is not RELEASED")
    cycle.status = "QUARANTINED"
    cycle.touch()
    for lot in _lot_rows_of_cycle(cycle.id):
        common.quarantine_lot(lot)
    return cycle