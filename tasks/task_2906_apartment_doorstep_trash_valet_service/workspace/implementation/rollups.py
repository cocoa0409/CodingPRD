"""Rollup recomputation and cascade propagation (PRD s2.9, s3.7).

Every row a cascade touches gets its updated_at refreshed and its version
incremented exactly once per request.
"""

from calc import (
    derive_collections_status,
    escalated_incident_count,
    outstanding_fines_cents,
    recompute_assigned_unit_coverage,
    recompute_night_counters,
    residents_of_property,
    routes_of_night,
    nights_of_contract,
)
from store import (
    OPEN_ROUTE_STATUSES,
    PROPERTY_SUSPENSION_ESCALATION_LEVEL,
    db,
    touch,
)


# ---------------------------------------------------------------------------
# Resident / property fine ledger
# ---------------------------------------------------------------------------
def apply_property_fine_rollup(prop):
    if prop is None:
        return
    pending = 0
    delinquent = 0
    for resident in residents_of_property(prop["id"]):
        pending += resident["fines_outstanding_cents"]
        if resident["collections_status"] == "DELINQUENT":
            delinquent += 1
    prop["pending_fine_revenue_cents"] = pending
    prop["delinquent_resident_count"] = delinquent
    touch(prop)


def apply_resident_ledger(resident):
    """Re-derive the resident's fine ledger, then the owning property's rollups."""
    outstanding = outstanding_fines_cents(resident["id"])
    resident["fines_outstanding_cents"] = outstanding
    resident["collections_status"] = derive_collections_status(outstanding)
    touch(resident)
    apply_property_fine_rollup(db.properties.get(resident["property_id"]))


# ---------------------------------------------------------------------------
# Night cancellation cascade
# ---------------------------------------------------------------------------
def cancel_night(night, cancel_route_statuses=OPEN_ROUTE_STATUSES, reschedule_action=None):
    """SCHEDULED/IN_PROGRESS -> CANCELLED plus the route cascade beneath it."""
    night["verification_status"] = "CANCELLED"
    if reschedule_action is not None:
        night["reschedule_action"] = reschedule_action
    for route in routes_of_night(night["id"]):
        if route["status"] in cancel_route_statuses:
            route["status"] = "CANCELLED"
            touch(route)
    recompute_assigned_unit_coverage(night)
    touch(night)


# ---------------------------------------------------------------------------
# Property posture (PRD s2.10, s3.7)
# ---------------------------------------------------------------------------
def suspend_property_cascade(prop):
    """ACTIVE -> SUSPENDED: cancel SCHEDULED nights of the active contract."""
    prop["status"] = "SUSPENDED"
    contract_id = prop.get("active_contract_id")
    if not contract_id:
        return
    for night in nights_of_contract(contract_id):
        if night["verification_status"] == "SCHEDULED":
            cancel_night(night)


def apply_escalation_rollup(prop):
    """Recompute escalation_level and drive the compound posture.

    The caller is responsible for the single touch() of the property row.
    """
    level = escalated_incident_count(prop["id"])
    prop["escalation_level"] = level
    if level >= PROPERTY_SUSPENSION_ESCALATION_LEVEL and prop["status"] == "ACTIVE":
        suspend_property_cascade(prop)
    elif level < PROPERTY_SUSPENSION_ESCALATION_LEVEL and prop["status"] == "SUSPENDED":
        prop["status"] = "ACTIVE"


# ---------------------------------------------------------------------------
# Expected-door recompute cascade after a move-out (PRD s3.2)
# ---------------------------------------------------------------------------
def recompute_scheduled_nights_for_property(prop):
    contract_id = prop.get("active_contract_id")
    if not contract_id:
        return
    for night in nights_of_contract(contract_id):
        if night["verification_status"] != "SCHEDULED":
            continue
        before = (
            night["expected_door_count"],
            night["scanned_door_count"],
            night["coverage_bps"],
        )
        recompute_night_counters(night)
        after = (
            night["expected_door_count"],
            night["scanned_door_count"],
            night["coverage_bps"],
        )
        if before != after:
            touch(night)
