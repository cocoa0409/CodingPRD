"""Licensor royalty ledger: accrual rows, the ledger triple and settlements.

Implements licensor_royalty_accrual (PRD 3.8) and licensor_royalty_settlement
(PRD 3.9, SCAFFOLD 1.3) with the pinned evaluation order:

  RESET -> EARNED -> DROP -> FLOOR -> CAP -> UNSETTLED

Rounding: each accrual row's royalty and its designer premium are rounded
HALF_UP to the cent BEFORE the rows are summed; the sum is not re-rounded.  The
ledger quantities therefore carry two decimal places (the specification's own
reference values are 168.76 and 843.75), so they are held as 2dp decimals
rather than being truncated to whole cents.
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (ERR_GUARANTEE_FLOOR_BREACH, ERR_INVALID_STATE,
                    ERR_NO_ACCRUED_ROYALTY, ERR_SETTLEMENT_NOOP, fail)

SKU_ROYALTY_RATE = {
    "JERSEY": Decimal("0.08"),
    "TRACTOR": Decimal("0.02"),
    "DUFFEL": Decimal("0.04"),
    "CAP": Decimal("0.06"),
    "MINI": Decimal("0.06"),
    "PENNANT": Decimal("0.00"),
}
DESIGNER_PREMIUM_PCT = Decimal("0.125")
GUARANTEE_BLOCK_CAP_CENTS = Decimal("12500")

# Bases that carry a version sequence / are supersedable.
RUSH_OR_STANDARD = "RUSH_or_STANDARD"
EVENT_SHORTFALL = "EVENT_shortfall"
STANDARD = "STANDARD"
SHORTFALL = "shortfall"

CENT = Decimal("0.01")
ONE = Decimal("1")


def round_half_up(value):
    """Round a Decimal HALF_UP to the cent (two decimal places)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_cents(value):
    """Round a (possibly fractional) money figure to a whole number of cents."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def q2(value):
    """A ledger quantity: HALF_UP to two decimal places, carried as a float so
    it serialises as 168.76 rather than as a Decimal object."""
    return float(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value if value is not None else 0))


# --- The ledger triple (PRD 2.4) ------------------------------------------

def recompute_unsettled(licensor):
    """INVARIANT, checked at every observable point: U = max(0, A - B)."""
    a = dec(licensor.get("accrued_royalty_cents", 0))
    b = dec(licensor.get("guarantee_recovery_block_cents", 0))
    licensor["accrued_unsettled_cents"] = q2(max(Decimal("0"), a - b))
    return licensor["accrued_unsettled_cents"]


def apply_cap(licensor):
    """CAP is applied last: when the recovery block exceeds the cap the excess is
    not blocked, so B is capped at 12500 and the excess is folded back into A."""
    b = dec(licensor.get("guarantee_recovery_block_cents", 0))
    if b > GUARANTEE_BLOCK_CAP_CENTS:
        excess = b - GUARANTEE_BLOCK_CAP_CENTS
        licensor["guarantee_recovery_block_cents"] = q2(GUARANTEE_BLOCK_CAP_CENTS)
        licensor["accrued_royalty_cents"] = q2(
            dec(licensor.get("accrued_royalty_cents", 0)) + excess)
    return licensor


# --- Accrual rows ---------------------------------------------------------

def _order_rows(licensor_id):
    """Every accrual row belonging to the licensor, in created_at order."""
    rows = [r for r in db.store.royalty_accruals.values()
            if r.get("licensor_id") == licensor_id]
    return db.created_order(rows)


def _next_version_seq(licensor_id):
    seq = 0
    for row in _order_rows(licensor_id):
        if row.get("basis") == RUSH_OR_STANDARD:
            seq = max(seq, int(row.get("version_seq", 0) or 0))
    return seq + 1


def accrue(licensor, production_order_id, accrued_value, incurred_at=None,
           basis=None):
    """Append one accrual row.  A later rush-or-standard accrual on the same
    licensor supersedes the earlier one: the earlier row is flagged
    `superseded` and its accrued_cents is driven to 0 so it contributes nothing
    to the licensor's running total."""
    seq = _next_version_seq(licensor["id"])
    for row in _order_rows(licensor["id"]):
        if row.get("basis") == RUSH_OR_STANDARD:
            row["superseded"] = True
            row["accrued_cents"] = 0
            row["settled_cents"] = 0
            db.touch(row)
    entity = {
        "licensor_id": licensor["id"],
        "production_order_id": production_order_id,
        "gross_wholesale_cents": to_cents(dec(accrued_value)),
        "basis": basis or RUSH_OR_STANDARD,
        "version_seq": seq,
        "accrual_state": "ACCRUED",
        "settled_cents": 0,
        "accrued_cents": q2(accrued_value),
        "superseded": False,
        "incurred_at": incurred_at,
    }
    db.init_common(entity)
    db.store.royalty_accruals[entity["id"]] = entity
    return entity


def recompute_licensor_accrued(licensor_id, production_order_id, design,
                               incurred_at=None):
    """Walk every FulfillmentOrder of the licensor's runs whose status is
    DELIVERED or RETURNED, in created_at order, and sum each row's
    HALF_UP-rounded royalty plus its HALF_UP-rounded designer premium."""
    licensor = db.store.licensors.get(licensor_id)
    if licensor is None:
        return None
    gross = Decimal("0")
    for order in db.created_order(list(db.store.fulfillment_orders.values())):
        if order.get("status") not in ("DELIVERED", "RETURNED"):
            continue
        run = db.store.production_orders.get(order.get("production_order_id"))
        if run is None or run.get("licensor_id") != licensor_id:
            continue
        dsn = db.store.designs.get(run.get("design_id"))
        if dsn is None:
            continue
        rate = SKU_ROYALTY_RATE.get(dsn.get("garment_sku"), Decimal("0"))
        row_royalty = round_half_up(dec(order.get("realized_wholesale_cents", 0)) * rate)
        row_premium = round_half_up(row_royalty * DESIGNER_PREMIUM_PCT)
        gross += row_royalty + row_premium
    total = q2(gross)
    licensor["accrued_royalty_cents"] = total
    # Whenever any operation touches the ledger the unsettled figure is
    # recomputed from the other two rather than adjusted independently (PRD 2.4).
    recompute_unsettled(licensor)
    if dec(total) > 0:
        accrue(licensor, production_order_id, total, incurred_at)
    return total


# --- Settlements (PRD 3.9) ------------------------------------------------

def _ledger_a(licensor):
    return dec(licensor.get("accrued_royalty_cents", 0))


def _ledger_b(licensor):
    return dec(licensor.get("guarantee_recovery_block_cents", 0))


def _ledger_u(licensor):
    return max(Decimal("0"), _ledger_a(licensor) - _ledger_b(licensor))


def apply_settlement(licensor, reserved_cents, accept_guarantee_breach):
    """APPLY(reserved_cents R, accept_guarantee_breach G), in the pinned order."""
    r = Decimal(int(reserved_cents or 0))
    u_before = _ledger_u(licensor)

    # Preconditions: U > 0 and R <= U (ERR_NO_ACCRUED_ROYALTY otherwise).
    if u_before <= 0:
        fail(ERR_NO_ACCRUED_ROYALTY, "the licensor has no unsettled accrual")
    if r > u_before:
        fail(ERR_NO_ACCRUED_ROYALTY,
             "reserved_cents exceeds the licensor's accrued_unsettled_cents")

    a = _ledger_a(licensor)
    guarantee = dec(licensor.get("minimum_guarantee_cents", 0))
    min_accrued_after = max(Decimal("0"), a - r)
    shortfall = max(Decimal("0"), guarantee - min_accrued_after)

    # SETTLEMENT_NOOP: a settlement that would reserve nothing and leave all
    # three ledger quantities unchanged moves no royalty at all.
    if r == 0 and shortfall == 0:
        fail(ERR_SETTLEMENT_NOOP,
             "the settlement would reserve nothing and move no ledger quantity")

    # FLOOR: below the guarantee while the breach is not accepted.
    if min_accrued_after < guarantee and not accept_guarantee_breach:
        fail(ERR_GUARANTEE_FLOOR_BREACH,
             "settlement would leave accrued royalty below the minimum guarantee; "
             "shortfall %s" % render(shortfall))

    settlement = {
        "licensor_id": licensor["id"],
        "status": "APPROVED",
        "snapped_accrued_cents": q2(a),
        "guarantee_shortfall_cents": q2(shortfall),
        "max_recoverable_early_cents": q2(u_before),
        "reserved_cents": int(r),
        "licensor_version": 0,
    }
    db.init_common(settlement)

    # EARNED / DROP / FLOOR / CAP / UNSETTLED
    licensor["accrued_royalty_cents"] = q2(min_accrued_after)
    licensor["guarantee_recovery_block_cents"] = q2(_ledger_b(licensor) + shortfall)
    apply_cap(licensor)
    recompute_unsettled(licensor)

    db.touch(licensor)
    settlement["licensor_version"] = int(licensor["version"])
    db.store.settlements[settlement["id"]] = settlement
    return settlement


def latest_approved_settlement(licensor_id):
    approved = [s for s in db.store.settlements.values()
                if s.get("licensor_id") == licensor_id and s.get("status") == "APPROVED"]
    if not approved:
        return None
    return db.created_order(approved)[-1]


def reverse_settlement(licensor):
    """REVERSE(): A := snapped_accrued_cents; B := B - guarantee_shortfall_cents."""
    settlement = latest_approved_settlement(licensor["id"])
    if settlement is None:
        fail(ERR_INVALID_STATE, "no APPROVED settlement exists to reverse")

    licensor["accrued_royalty_cents"] = q2(settlement.get("snapped_accrued_cents", 0))
    licensor["guarantee_recovery_block_cents"] = q2(
        _ledger_b(licensor) - dec(settlement.get("guarantee_shortfall_cents", 0)))
    recompute_unsettled(licensor)
    db.touch(licensor)

    settlement["status"] = "REVERSED"
    settlement["licensor_version"] = int(licensor["version"])
    db.touch(settlement)
    return settlement


def render(value):
    """Render a money figure without a spurious `.0` on whole cents."""
    d = dec(value)
    if d == d.to_integral_value():
        return str(int(d))
    return str(d.normalize())