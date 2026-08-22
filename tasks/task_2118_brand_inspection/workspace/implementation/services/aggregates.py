"""Derived aggregates. Every one is recomputed from its source rows, never nudged."""

from db import db, now, touch
from services import constants as C


def recompute_territory(territory):
    """impound_current_head and the ninety-percent intake breakpoint."""
    live_head = sum(
        case["head_count"]
        for case in db.estrays.values()
        if case["territory_id"] == territory["id"] and case["status"] in C.LIVE_ESTRAY_STATUSES
    )
    restricted = live_head * 100 >= territory["impound_capacity_head"] * C.INTAKE_RESTRICTION_PERCENT
    intake = "RESTRICTED" if restricted else "OPEN"
    changed = territory["impound_current_head"] != live_head or territory["intake_status"] != intake
    territory["impound_current_head"] = live_head
    territory["intake_status"] = intake
    if changed:
        touch(territory)
    return changed


def recompute_inspector_assignments(inspector, bump=False):
    """Refresh active_assignment_count from the order table.

    ``bump`` marks the operations the PRD declares as mutations of the inspector
    row (assignment, withdrawal of an assigned order, a cascade that released a
    window, a commission status change); only those advance the OCC token. Every
    other refresh keeps the derived count honest without invalidating a
    scheduling token the caller is holding.
    """
    count = sum(
        1
        for order in db.orders.values()
        if order["inspector_id"] == inspector["id"]
        and order["schedule_status"] in C.OCCUPYING_SCHEDULE_STATUSES
    )
    changed = inspector["active_assignment_count"] != count
    inspector["active_assignment_count"] = count
    if bump:
        touch(inspector)
    return changed


def recompute_encumbrance(registration):
    count = sum(
        1
        for inv in db.investigations.values()
        if inv["brand_registration_id"] == registration["id"]
        and inv["status"] in C.OPEN_INVESTIGATION_STATUSES
    )
    changed = registration["encumbrance_count"] != count
    registration["encumbrance_count"] = count
    return changed


def recompute_head_count_presented(order):
    total = sum(
        lot["head_count"]
        for lot in db.lots.values()
        if lot["inspection_order_id"] == order["id"] and lot["lot_status"] in C.COUNTED_LOT_STATUSES
    )
    changed = order["head_count_presented"] != total
    order["head_count_presented"] = total
    return changed


def owner_arrears(owner_id):
    posted = 0
    projected = 0
    for order in db.orders.values():
        if order["owner_id"] != owner_id:
            continue
        if order["fee_status"] == "DELINQUENT":
            posted += order["assessed_fee_cents"]
        if order["fee_status"] in C.OPEN_FEE_STATUSES:
            projected += order["assessed_fee_cents"]
    return posted, projected


def recompute_owner(owner):
    """Both arrears flavours, the standing gate and suspended_since.

    Returns (changed, flipped_to_suspended).
    """
    posted, projected = owner_arrears(owner["id"])
    standing = "SUSPENDED" if posted >= C.ARREARS_SUSPENSION_THRESHOLD_CENTS else "GOOD"

    changed = False
    flipped_to_suspended = False
    if owner["posted_arrears_cents"] != posted:
        owner["posted_arrears_cents"] = posted
        changed = True
    if owner["projected_arrears_cents"] != projected:
        owner["projected_arrears_cents"] = projected
        changed = True
    if owner["standing"] != standing:
        owner["standing"] = standing
        if standing == "SUSPENDED":
            owner["suspended_since"] = now()
            flipped_to_suspended = True
        else:
            owner["suspended_since"] = None
        changed = True
    if changed:
        touch(owner)
    return changed, flipped_to_suspended


def recompute_owner_by_id(owner_id):
    owner = db.owners.get(owner_id)
    if owner is None:
        return False, False
    return recompute_owner(owner)
