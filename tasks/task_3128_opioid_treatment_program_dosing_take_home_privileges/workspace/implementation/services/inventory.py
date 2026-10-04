"""The dose tariff and the inventory lot selector (PRD 3.4, 2.9; SCAFFOLD R3a, R4b)."""
from decimal import Decimal, ROUND_HALF_UP
from math import ceil

import db
from constants import (
    HANDLING_RATE_PER_MG,
    OVER_CEILING_RATE,
    SECURITY_RATE_PER_MG,
    TIER_1_RATE,
    TIER_2_RATE,
    TIER_3_RATE,
    TIER_4_RATE,
    WASTE_FEE_PER_10MG,
    WASTE_FREE_ALLOWANCE_MG,
)
from errors import ApiError
from services.num import eff, r2


def _d(value):
    return Decimal(str(value))


def _r2d(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Tariff (R3a)
# ---------------------------------------------------------------------------
def step_tier_sum(m):
    """2.90 for the first 10 mg; 3.30 for 11-40; 5.25 for 41-90; 6.80 beyond 90."""
    m = _d(m)
    total = _d(TIER_1_RATE) * min(m, _d(10))
    total += _d(TIER_2_RATE) * min(max(m - _d(10), _d(0)), _d(30))
    total += _d(TIER_3_RATE) * min(max(m - _d(40), _d(0)), _d(50))
    total += _d(TIER_4_RATE) * max(m - _d(90), _d(0))
    return total


def tariff_components(dose, order, program, patient, surcharge=0.0):
    """Every component, rounded half up to 2 dp FIRST, plus the unrounded sum.

    The rounding order is pinned: the rounded components are summed and the
    unrounded sum is never used for the per-component figure.
    """
    posture_normal = program.get("posture") == "NORMAL"
    patient_active = (patient or {}).get("status") == "ACTIVE"
    billed = posture_normal and patient_active
    billed_dispensed = _d(dose.get("dispensed_mg") or 0.0) if billed else _d(0)
    billed_wasted = _d(dose.get("wasted_mg") or 0.0) if billed else _d(0)

    if order.get("medication") == "METHADONE":
        ceiling = program.get("max_daily_mg_methadone")
    else:
        ceiling = program.get("max_daily_mg_buprenorphine")
    ceiling = ceiling if ceiling is not None else 0.0
    over_ceiling_mg = ceil(max(0.0, (dose.get("ordered_mg") or 0.0) - ceiling))

    ordered = dose.get("ordered_mg") or 0.0
    if order.get("split_dose_authorized"):
        base_pair = _d(2.0) * step_tier_sum(_d(ordered) / _d(2))
    else:
        base_pair = step_tier_sum(ordered)
    over_surcharge = _d(OVER_CEILING_RATE) * _d(over_ceiling_mg)
    base_charge = _r2d(base_pair + over_surcharge + _d(surcharge))
    handling_fee = _r2d(_d(HANDLING_RATE_PER_MG) * billed_dispensed)
    security_fee = _r2d(_d(SECURITY_RATE_PER_MG) * billed_dispensed)
    waste_blocks = _d(
        ceil(max(0.0, float(billed_wasted) - WASTE_FREE_ALLOWANCE_MG) / 10.0)
    )
    waste_fee = _r2d(_d(WASTE_FEE_PER_10MG) * waste_blocks)

    per_component = base_charge + handling_fee + security_fee + waste_fee
    unrounded = (
        base_pair
        + over_surcharge
        + _d(surcharge)
        + _d(HANDLING_RATE_PER_MG) * billed_dispensed
        + _d(SECURITY_RATE_PER_MG) * billed_dispensed
        + _d(WASTE_FEE_PER_10MG) * waste_blocks
    )
    return {
        "base_charge": float(base_charge),
        "handling_fee": float(handling_fee),
        "security_fee": float(security_fee),
        "waste_fee": float(waste_fee),
        "per_component_total": float(_r2d(per_component)),
        "sum_then_round_total": float(_r2d(unrounded)),
    }


def dose_tariff(dose, order, program, patient, surcharge=0.0):
    """The pinned rounding order: every component rounded first, then summed."""
    return tariff_components(dose, order, program, patient, surcharge)["per_component_total"]


def dose_tariff_both(dose, order, program, patient, surcharge=0.0):
    parts = tariff_components(dose, order, program, patient, surcharge)
    return parts["per_component_total"], parts["sum_then_round_total"]


# ---------------------------------------------------------------------------
# Lot selector (R4b)
# ---------------------------------------------------------------------------
def lot_is_expired(lot, clock=None):
    if clock is None:
        clock = db.clock_dt()
    expiration = db.parse_date(lot.get("expiration_date"))
    if expiration is None:
        return False
    today = clock.replace(hour=0, minute=0, second=0, microsecond=0)
    return today >= expiration


def lot_candidates(dose, order):
    """Every lot satisfying all of the selector's conditions.

    The status filter admits a lot that has never been drawn from: §2.9 has a
    lot move RECEIVED to IN_USE automatically on its first transaction, so a
    RECEIVED lot is a legitimate candidate. DEPLETED, QUARANTINED and DESTROYED
    stock is excluded, the first of those by the on-hand filter as well.
    """
    out = []
    for lot in db.inventory_lots.values():
        if lot.get("program_id") != dose.get("program_id"):
            continue
        if lot.get("medication") != order.get("medication"):
            continue
        if lot.get("status") not in ("RECEIVED", "IN_USE"):
            continue
        if lot_is_expired(lot):
            continue
        if eff(lot.get("running_on_hand_mg")) < (dose.get("ordered_mg") or 0.0):
            continue
        if dose.get("source_type") == "TAKE_HOME_ISSUANCE" and not lot.get("reusable_for_take_home"):
            continue
        out.append(lot)
    return out


def select_lot(dose, order):
    """Rank by expiration_date ascending, ties broken by created_at ascending."""
    candidates = lot_candidates(dose, order)
    if not candidates:
        return None
    candidates.sort(
        key=lambda lot: (str(lot.get("expiration_date", "")), str(lot.get("created_at", "")))
    )
    return candidates[0]


def select_lot_for_privilege(privilege, patient):
    """The lot a take-home dose draws from: the earliest-expiring reusable lot."""
    program = db.programs.get(privilege.get("program_id"))
    order = None
    for row in db.dose_orders.values():
        if row.get("patient_id") == patient["id"] and row.get("status") == "ACTIVE":
            order = row
            break
    if order is None or program is None:
        return None
    probe = {
        "program_id": program["id"],
        "source_type": "TAKE_HOME_ISSUANCE",
        "ordered_mg": (order.get("ordered_daily_mg") or 0.0),
    }
    winner = select_lot(probe, order)
    return winner["id"] if winner is not None else None


def resolve_dispense_lot(dose, order, requested_lot_id):
    """Resolve the lot for a dispense, distinguishing the three failure families."""
    if requested_lot_id:
        lot = db.inventory_lots.get(requested_lot_id)
        if lot is None:
            raise ApiError("ERR_LOT_NOT_FOUND", "No inventory lot with the supplied id")
        if lot.get("status") == "QUARANTINED":
            raise ApiError("ERR_LOT_QUARANTINED", "The lot is QUARANTINED")
        if lot_is_expired(lot):
            raise ApiError("ERR_LOT_EXPIRED", "The lot is expired")
        return lot
    lot = select_lot(dose, order)
    if lot is None:
        raise ApiError(
            "ERR_NO_ELIGIBLE_LOT",
            "The lot selector candidate set is empty for this dose",
        )
    return lot


# ---------------------------------------------------------------------------
# Inventory accounting
# ---------------------------------------------------------------------------
def recompute_lot(lot, bump=True):
    """quantity_received_mg plus the sum over RECORDED/RECONCILED rows, in order."""
    total = lot.get("quantity_received_mg") or 0.0
    rows = [
        t
        for t in db.inventory_transactions.values()
        if t.get("lot_id") == lot["id"] and t.get("status") in ("RECORDED", "RECONCILED")
    ]
    rows.sort(key=lambda t: (str(t.get("created_at", "")), str(t.get("id", ""))))
    for row in rows:
        total += row.get("quantity_mg") or 0.0
    lot["running_on_hand_mg"] = r2(total)
    status = lot.get("status")
    if status not in ("QUARANTINED", "DESTROYED"):
        if rows and status == "RECEIVED":
            lot["status"] = "IN_USE"
        if eff(lot["running_on_hand_mg"]) <= 0.0 and rows:
            lot["status"] = "DEPLETED"
        elif lot["status"] == "DEPLETED" and eff(lot["running_on_hand_mg"]) > 0.0:
            lot["status"] = "IN_USE"
    if bump:
        db.stamp(lot)
    return lot


def append_transaction(
    lot, transaction_type, quantity_mg, patient_id=None, dose_dispense_id=None,
    witness_staff_id=None, status="RECORDED",
):
    from services import entity

    row = entity.make_transaction(
        lot,
        transaction_type,
        quantity_mg,
        patient_id=patient_id,
        dose_dispense_id=dose_dispense_id,
        witness_staff_id=witness_staff_id,
        status=status,
    )
    db.inventory_transactions[row["id"]] = row
    recompute_lot(lot, bump=True)
    return row


# ---------------------------------------------------------------------------
# Reconciliation (R3b / R3c)
# ---------------------------------------------------------------------------
def _period_bounds(period):
    try:
        year, month = str(period).split("-")
        year = int(year)
        month = int(month)
    except (ValueError, AttributeError):
        raise ApiError("ERR_INVALID_REQUEST", "period must be YYYY-MM")
    if month < 1 or month > 12:
        raise ApiError("ERR_INVALID_REQUEST", "period must be YYYY-MM")
    start = db.clock_dt().replace(
        year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if month == 12:
        end = start.replace(year=year + 1, month=1)
    else:
        end = start.replace(month=month + 1)
    return start, end


def _expired_debits(lot):
    """Magnitude already debited for this lot by DESTRUCTION/ADJUSTMENT on/after expiry."""
    expiration = db.parse_date(lot.get("expiration_date"))
    if expiration is None:
        return 0.0
    total = 0.0
    for row in db.inventory_transactions.values():
        if row.get("lot_id") != lot["id"]:
            continue
        if row.get("transaction_type") not in ("DESTRUCTION", "ADJUSTMENT"):
            continue
        if row.get("status") == "VOIDED":
            continue
        created = db.parse_iso(row.get("created_at"))
        if created is None or created < expiration:
            continue
        total += abs(row.get("quantity_mg") or 0.0)
    return total


def reconciliation_figures(program, period, variant="delivered"):
    """variant 'delivered' nets expired stock out; 'retained' omits that term.

    Only RECONCILED rows participate in the reconciled balance; RECORDED, FLAGGED
    and VOIDED rows are excluded from it (consumed C3).
    """
    start, end = _period_bounds(period)
    lots = sorted(
        [lot for lot in db.inventory_lots.values() if lot.get("program_id") == program["id"]],
        key=lambda lot: (str(lot.get("created_at", "")), str(lot.get("id", ""))),
    )
    reconciled_total = 0.0
    delivered_total = 0.0
    for lot in lots:
        if lot.get("status") == "QUARANTINED":
            continue
        accepted = 0.0
        for row in db.inventory_transactions.values():
            if row.get("lot_id") != lot["id"]:
                continue
            if row.get("status") != "RECONCILED":
                continue
            created = db.parse_iso(row.get("created_at"))
            if created is None or created > end:
                continue
            accepted += row.get("quantity_mg") or 0.0
        reconciled = (lot.get("quantity_received_mg") or 0.0) + accepted
        reconciled_total += reconciled
        if variant == "delivered":
            delivered_total += reconciled - _expired_debits(lot)
        else:
            delivered_total += reconciled

    in_period_dispensed = 0.0
    for row in db.inventory_transactions.values():
        if row.get("program_id") != program["id"]:
            continue
        if row.get("transaction_type") != "DISPENSE":
            continue
        created = db.parse_iso(row.get("created_at"))
        if created is None:
            continue
        if start <= created < end:
            in_period_dispensed += abs(row.get("quantity_mg") or 0.0)

    return {
        "period": period,
        "reconciled_on_hand_mg": r2(reconciled_total),
        "delivered_on_hand_mg": r2(delivered_total),
        "program_variance_mg": r2(delivered_total - reconciled_total),
        "period_dispensed_mg": r2(in_period_dispensed),
    }