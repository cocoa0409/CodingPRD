"""Device lot selection, per-device reimbursement and the conserved ledgers
(PRD 2.8, 3.6, 3.9)."""

from datetime import timedelta
from decimal import Decimal

import db
import domain
import util
from db import store, touch
from errors import ApiError


def lot_status_for(lot):
    """PRD 2.8: derived - DEPLETED when on_hand_qty reaches 0."""
    return "DEPLETED" if lot["on_hand_qty"] == 0 else "AVAILABLE"


def refresh_grant_available(grant):
    grant["available_cents"] = (
        grant["authorized_cents"] - grant["reserved_cents"] - grant["committed_cents"]
    )


def reimbursable_for(grant, device_type, reserved_cost_cents):
    """PRD 3.9 per-device reimbursement, rounded half up to a whole cent."""
    if grant["reimbursement_basis"] == "UNIT_RATE":
        base = util.to_decimal(grant["unit_rate_cents_by_type"].get(device_type, 0))
    else:
        base = util.to_decimal(reserved_cost_cents + domain.LABOUR_ALLOCATION_CENTS)
    return util.round_cents(base * util.to_decimal(grant["reimbursement_pct"]) / Decimal(100))


def grant_of_lot(lot):
    return store.grants.get(lot["funding_grant_id"])


def installations_of_visit(visit_id):
    rows = [i for i in store.installations.values() if i["visit_id"] == visit_id]
    return db.by_created_at(rows)


def select_lot(device_type):
    """The waterfall selection policy of PRD 3.6: eight eligibility predicates
    over every lot in the system, then FIFO on shelf life, then price, then
    created_at - never the lot's id."""
    today = util.clock.today()
    threshold = today + timedelta(days=domain.LOT_SHELF_LIFE_DAYS)
    candidates = []
    for lot in store.device_lots.values():
        if lot["device_type"] != device_type:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        if lot["on_hand_qty"] - lot["reserved_qty"] < 1:
            continue
        if lot["expiry_date"] < threshold:
            continue
        grant = grant_of_lot(lot)
        if grant is None:
            continue
        if grant["status"] != "ACTIVE":
            continue
        if device_type not in grant["allowed_device_types"]:
            continue
        if today < grant["period_start_date"] or today > grant["period_end_date"]:
            continue
        if grant["available_cents"] < lot["unit_cost_cents"]:
            continue
        candidates.append(lot)
    if not candidates:
        return None
    candidates.sort(
        key=lambda l: (l["expiry_date"], l["unit_cost_cents"], l["created_at"], l["_seq"])
    )
    return candidates[0]


def reserve(visit, lot, device_type, placement_location, storey, serial_number, crew_id):
    """Land a RESERVED installation and move both conserved ledgers (PRD 3.6)."""
    grant = grant_of_lot(lot)
    reserved_cost_cents = lot["unit_cost_cents"]
    reimbursable_cents = reimbursable_for(grant, device_type, reserved_cost_cents)
    row = {}
    db.stamp_new(row)
    installation = {
        "id": row["id"],
        "visit_id": visit["id"],
        "device_lot_id": lot["id"],
        "device_type": device_type,
        "placement_location": placement_location,
        "storey": storey,
        "serial_number": serial_number,
        "installed_by_crew_id": crew_id,
        "verified_by_crew_id": None,
        "reserved_cost_cents": reserved_cost_cents,
        "reimbursable_cents": reimbursable_cents,
        "status": "RESERVED",
        "voided_reason": None,
        "installed_at": None,
        "verified_at": None,
        "voided_at": None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "_seq": row["_seq"],
    }
    store.installations[installation["id"]] = installation

    lot["reserved_qty"] = lot["reserved_qty"] + 1
    lot["status"] = lot_status_for(lot)
    touch(lot)

    grant["reserved_cents"] = grant["reserved_cents"] + reimbursable_cents
    refresh_grant_available(grant)
    touch(grant)
    return installation


def commit(installation):
    """Hops one to four of the close-out cascade (PRD 3.6/2.11)."""
    from services import reports as report_service

    installation["status"] = "INSTALLED"
    installation["installed_at"] = util.clock.now()
    touch(installation)

    lot = store.device_lots.get(installation["device_lot_id"])
    if lot is not None:
        lot["reserved_qty"] = lot["reserved_qty"] - 1
        lot["on_hand_qty"] = lot["on_hand_qty"] - 1
        lot["consumed_qty"] = lot["consumed_qty"] + 1
        lot["status"] = lot_status_for(lot)
        touch(lot)
        grant = grant_of_lot(lot)
        if grant is not None:
            grant["reserved_cents"] = (
                grant["reserved_cents"] - installation["reimbursable_cents"]
            )
            grant["committed_cents"] = (
                grant["committed_cents"] + installation["reimbursable_cents"]
            )
            refresh_grant_available(grant)
            touch(grant)
            report_service.recompute_draft_reports(
                grant, installation["installed_at"]
            )


def void(installation, voided_reason):
    """The compensating action for a reservation or a commitment (PRD 3.6)."""
    from services import reports as report_service

    origin = installation["status"]
    installation["status"] = "VOIDED"
    installation["voided_reason"] = voided_reason
    installation["voided_at"] = util.clock.now()
    touch(installation)

    lot = store.device_lots.get(installation["device_lot_id"])
    grant = grant_of_lot(lot) if lot is not None else None
    if lot is not None:
        if origin == "RESERVED":
            lot["reserved_qty"] = lot["reserved_qty"] - 1
        else:
            lot["consumed_qty"] = lot["consumed_qty"] - 1
            lot["on_hand_qty"] = lot["on_hand_qty"] + 1
        lot["status"] = lot_status_for(lot)
        touch(lot)
    if grant is not None:
        if origin == "RESERVED":
            grant["reserved_cents"] = (
                grant["reserved_cents"] - installation["reimbursable_cents"]
            )
        else:
            grant["committed_cents"] = (
                grant["committed_cents"] - installation["reimbursable_cents"]
            )
        refresh_grant_available(grant)
        touch(grant)
        if origin == "INSTALLED":
            report_service.recompute_draft_reports(grant, installation["installed_at"])


def void_reserved_of_visit(visit, voided_reason):
    for installation in installations_of_visit(visit["id"]):
        if installation["status"] == "RESERVED":
            void(installation, voided_reason)


def coverage_counts(visit):
    """PRD 3.6 close-out coverage, counted over this visit's installations only."""
    smoke = visit["pre_existing_working_smoke_alarms"] or 0
    carbon = visit["pre_existing_working_co_alarms"] or 0
    strobe = 0
    for installation in installations_of_visit(visit["id"]):
        if installation["status"] not in domain.INSTALLATION_LIVE:
            continue
        if installation["device_type"] in domain.SMOKE_FAMILIES:
            smoke += 1
        if installation["device_type"] in domain.CO_FAMILIES:
            carbon += 1
        if installation["device_type"] == "STROBE_HOH":
            strobe += 1
    return smoke, carbon, strobe
