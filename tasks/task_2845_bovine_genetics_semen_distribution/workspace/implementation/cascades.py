"""Cascade discipline (PRD 2.11) -- suspensions, valuations, the epoch sweep.

Every cascaded row gets its own updated_at refresh and version increment
(PRD 2.4).
"""

import calc
import config
import store


# -------------------------------------------------------------- bookings ----
def void_bookings(sire_id, cancel_reason, mode):
    """VOID a sire's SCHEDULED bookings.

    mode 'after'        -- start_at strictly after the clock (epoch sweep)
    mode 'at_or_after'  -- start_at at or after the clock (suspension causes)
    mode 'all'          -- every SCHEDULED booking (commercial retirement)
    """
    now = store.clock()
    voided = []
    for booking in store.rows("collection_bookings"):
        if booking["sire_id"] != sire_id or booking["status"] != "SCHEDULED":
            continue
        start_at = store.dt_of(booking["start_at"])
        if mode == "after" and not start_at > now:
            continue
        if mode == "at_or_after" and not start_at >= now:
            continue
        booking["status"] = "VOIDED"
        booking["cancel_reason"] = cancel_reason
        store.touch(booking)
        voided.append(booking["id"])
    return voided


# ---------------------------------------------------------- certificates ----
def revoke_certificates_for_sire(sire_id, reason):
    revoked = []
    for cert in store.rows("export_certificates"):
        if cert["sire_id"] != sire_id or cert["status"] != "ISSUED":
            continue
        cert["status"] = "REVOKED"
        cert["revocation_reason"] = reason
        store.touch(cert)
        revoked.append(cert["id"])
    return revoked


def revoke_certificates_for_lot(lot_id, reason):
    revoked = []
    for cert in store.rows("export_certificates"):
        if cert["straw_lot_id"] != lot_id or cert["status"] != "ISSUED":
            continue
        cert["status"] = "REVOKED"
        cert["revocation_reason"] = reason
        store.touch(cert)
        revoked.append(cert["id"])
    return revoked


# ----------------------------------------------------------------- sires ----
def suspend_sire(sire, suspension_reason, cancel_reason, mode):
    """One bull suspension with its full downhill cascade."""
    sire["collection_status"] = "SUSPENDED"
    sire["suspension_reason"] = suspension_reason
    store.touch(sire)
    voided = void_bookings(sire["id"], cancel_reason, mode)
    revoke_certificates_for_sire(sire["id"], config.REVOKE_SIRE_SUSPENDED)
    return voided


# ------------------------------------------------------------------ lots ----
def maybe_deplete(lot):
    """RELEASED -> DEPLETED fires after any ledger mutation that empties the
    three live buckets (PRD 3.5).  Never operator-driven."""
    if lot["distribution_status"] != "RELEASED":
        return False
    if int(lot["doses_available"]) or int(lot["doses_reserved"]) or int(lot["doses_consigned"]):
        return False
    lot["distribution_status"] = "DEPLETED"
    store.touch(lot)
    return True


# ------------------------------------------------------------ valuation ----
def revalue_for_publication(sire, evaluation):
    """Hop 2 of the publication cascade plus the evaluation's delta."""
    before = calc.plant_inventory()["plant_inventory_value_cents"]
    revalued = []
    for lot in store.rows("straw_lots"):
        if lot["sire_id"] != sire["id"]:
            continue
        if lot["distribution_status"] not in ("QUARANTINE", "RELEASED"):
            continue
        lot["pre_revaluation_unit_value_cents"] = lot["unit_book_value_cents"]
        lot["_pre_revaluation_basis"] = lot["valuation_basis"]
        lot["unit_book_value_cents"] = calc.lot_market_unit_value(lot, sire)
        lot["valuation_basis"] = "MARKET_REVALUED"
        store.touch(lot)
        revalued.append(lot["id"])
    after = calc.plant_inventory()["plant_inventory_value_cents"]
    evaluation["_revalued_lot_ids"] = revalued
    evaluation["revaluation_delta_cents"] = after - before
    return revalued


def restore_for_rollback(evaluation):
    """Compensating hop 2: back to the pre-publication figure, to the cent."""
    for lot_id in list(evaluation.get("_revalued_lot_ids") or []):
        lot = store.get("straw_lots", lot_id)
        if lot is None:
            continue
        previous = lot["pre_revaluation_unit_value_cents"]
        if previous is None:
            continue
        lot["unit_book_value_cents"] = previous
        lot["valuation_basis"] = lot.get("_pre_revaluation_basis") or "STANDARD_COST"
        lot["pre_revaluation_unit_value_cents"] = None
        lot["_pre_revaluation_basis"] = None
        store.touch(lot)


def apply_published_snapshot(sire, evaluation):
    """Hop 1 of the publication cascade."""
    sire["published_production_index"] = evaluation["production_index"]
    sire["published_health_index"] = evaluation["health_index"]
    sire["published_composite_index"] = evaluation["composite_index"]
    sire["published_evaluation_effective_at"] = evaluation["effective_at"]
    sire["progeny_daughter_count"] = evaluation["progeny_daughter_count"]
    store.touch(sire)


def clear_published_snapshot(sire):
    sire["published_production_index"] = 0.00
    sire["published_health_index"] = 0.00
    sire["published_composite_index"] = 0.00
    sire["published_evaluation_effective_at"] = None
    sire["progeny_daughter_count"] = 0
    store.touch(sire)


# ------------------------------------------------------------ epoch sweep ----
def epoch_sweep(new_clock):
    """PRD 2.5, run in a fixed order after the clock has moved."""
    store.set_clock(new_clock)
    expired_health_test_ids = []
    for test in store.rows("health_tests"):
        if test["result"] != "NEGATIVE" or test["valid_until"] is None:
            continue
        if store.dt_of(test["valid_until"]) <= new_clock:
            test["result"] = "EXPIRED"
            store.touch(test)
            expired_health_test_ids.append(test["id"])

    suspended_sire_ids = []
    voided_booking_ids = []
    for sire in store.rows("sires"):
        if sire["collection_status"] != "ELIGIBLE":
            continue
        if calc.health_current(sire["id"]):
            continue
        voided_booking_ids.extend(suspend_sire(
            sire, config.SUSP_TEST_EXPIRED, config.CANCEL_SIRE_SUSPENDED, "after"))
        suspended_sire_ids.append(sire["id"])

    service_due_tank_ids = []
    out_of_service_tank_ids = []
    for tank in store.rows("tanks"):
        _level, _next_due, status = calc.tank_derived(tank)
        if status == "SERVICE_DUE":
            service_due_tank_ids.append(tank["id"])
        elif status == "OUT_OF_SERVICE":
            out_of_service_tank_ids.append(tank["id"])

    return {
        "current_utc": store.iso(new_clock),
        "expired_health_test_ids": expired_health_test_ids,
        "suspended_sire_ids": suspended_sire_ids,
        "voided_booking_ids": voided_booking_ids,
        "service_due_tank_ids": service_due_tank_ids,
        "out_of_service_tank_ids": out_of_service_tank_ids,
    }
