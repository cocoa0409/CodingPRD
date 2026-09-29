"""Derived fields, entity serializers and version-bump reconciliation.

Every derived value in this module is recomputed from its current inputs at the
moment it is read (PRD 2.11); nothing derived is ever persisted on a row.
"""

import math

from flask import g

import num
import store
from store import db

LIVE_DOWNTIME = ("OPEN", "DIAGNOSED", "AWAITING_PARTS", "RESOLVED")
COMMITTED_REQUISITION = ("RESERVED", "BACKORDERED", "RECEIVED")
HOLDING_INCIDENT = ("RIDE_HELD", "UNDER_INVESTIGATION", "REGULATOR_NOTIFIED")
OVERHAUL_ACTIVE = ("TEARDOWN", "INSPECTION", "REBUILD")
EVALUATED_ACTION = ("PENDING", "IN_WORK", "DEFERRED")

NDT_GRACE_NUMERATOR = 6      # 1.20 expressed exactly as 6/5
NDT_GRACE_DENOMINATOR = 5


def _kids(collection, field, value):
    return [r for r in store.rows(collection) if r.get(field) == value]


# ---------------------------------------------------------------------------
# attraction aggregates (PRD 2.9)
# ---------------------------------------------------------------------------

def components_of(attraction_id):
    return _kids("components", "attraction_id", attraction_id)


def committed_cents(attraction):
    total = 0
    for req in _kids("requisitions", "attraction_id", attraction["id"]):
        if req["status"] in COMMITTED_REQUISITION:
            total += req["total_cost_cents"]
    return total


def ytd_downtime_minutes(attraction):
    total = 0
    for event in _kids("downtime_events", "attraction_id", attraction["id"]):
        if event["status"] == "CLOSED" and event.get("duration_minutes"):
            total += event["duration_minutes"]
    return total


def regulatory_hold(attraction):
    for incident in _kids("incidents", "attraction_id", attraction["id"]):
        if incident["status"] in HOLDING_INCIDENT:
            return True
    return False


def active_template(attraction):
    for template in store.by_seq(_kids("templates", "attraction_id",
                                       attraction["id"])):
        if template["status"] == "ACTIVE":
            return template
    return None


def active_template_id(attraction):
    template = active_template(attraction)
    return template["id"] if template else None


def signed_off_inspections(attraction):
    return [i for i in _kids("inspections", "attraction_id", attraction["id"])
            if i["status"] == "SIGNED_OFF"]


def last_signed_off_service_date(attraction):
    dates = [i["service_date"] for i in signed_off_inspections(attraction)]
    return max(dates) if dates else None


def certified_certifications(attraction):
    return [c for c in _kids("certifications", "attraction_id", attraction["id"])
            if certification_status(c) == "CERTIFIED"]


def certified_operator_count(attraction):
    return len(certified_certifications(attraction))


def inspection_for_date(attraction, service_date):
    for inspection in store.by_seq(_kids("inspections", "attraction_id",
                                         attraction["id"])):
        if inspection["service_date"] == service_date:
            return inspection
    return None


# ---------------------------------------------------------------------------
# component nondestructive-testing status (PRD 3.1)
# ---------------------------------------------------------------------------

def elapsed_cycles(component):
    attraction = db.attractions.get(component["attraction_id"])
    current = attraction["cumulative_cycles"] if attraction else 0
    return current - component["last_ndt_cycles"]


def elapsed_days(component):
    last = store.instant_of(component.get("last_ndt_at"))
    if last is None:
        return 0
    seconds = (store.now() - last).total_seconds()
    return int(math.floor(seconds / 86400.0))


def _grace(interval):
    return num.ceil_div(interval * NDT_GRACE_NUMERATOR, NDT_GRACE_DENOMINATOR)


def ndt_status(component):
    cycles = elapsed_cycles(component)
    days = elapsed_days(component)
    interval_cycles = component["ndt_interval_cycles"]
    interval_days = component["ndt_interval_days"]
    if cycles >= _grace(interval_cycles) or days >= _grace(interval_days):
        return "OVERDUE"
    if cycles >= interval_cycles or days >= interval_days:
        return "DUE"
    return "CURRENT"


def has_overdue_safety_critical(attraction):
    for component in components_of(attraction["id"]):
        if component["criticality"] == "SAFETY_CRITICAL":
            if ndt_status(component) == "OVERDUE":
                return True
    return False


# ---------------------------------------------------------------------------
# certification status (PRD 3.7)
# ---------------------------------------------------------------------------

def certification_status(certification):
    now = store.now()
    expires = store.instant_of(certification["expires_at"])
    effective = store.instant_of(certification["effective_from"])
    if expires is not None and now >= expires:
        return "EXPIRED"
    if certification.get("suspended_at"):
        return "SUSPENDED"
    if effective is not None and now < effective:
        return "TRAINEE"
    if (certification["restraint_verification_score"] >= 85
            and certification["dispatch_procedure_score"] >= 80):
        return "CERTIFIED"
    return "TRAINEE"


# ---------------------------------------------------------------------------
# operational posture (PRD 2.8)
# ---------------------------------------------------------------------------

def operational_posture(attraction):
    for order in _kids("work_orders", "attraction_id", attraction["id"]):
        if order["status"] in OVERHAUL_ACTIVE:
            return "OVERHAUL"
    if regulatory_hold(attraction):
        return "HOLD"
    for event in _kids("downtime_events", "attraction_id", attraction["id"]):
        if event["status"] in LIVE_DOWNTIME:
            return "DOWN"
    if has_overdue_safety_critical(attraction):
        return "DOWN"
    today = inspection_for_date(attraction, store.today_str())
    if today is not None and today["status"] == "BLOCKED":
        return "DOWN"
    if last_signed_off_service_date(attraction) != store.today_str():
        return "CLOSED_PENDING_INSPECTION"
    return "OPEN"


# ---------------------------------------------------------------------------
# inspection counters (PRD 3.2)
# ---------------------------------------------------------------------------

def results_of(inspection):
    return _kids("item_results", "inspection_id", inspection["id"])


def pending_item_count(inspection):
    return len([r for r in results_of(inspection) if r["outcome"] == "PENDING"])


def blocking_item_count(inspection):
    return len([r for r in results_of(inspection)
                if r["outcome"] == "FAIL"
                and r["severity_class"] == "SAFETY_CRITICAL"])


def essential_fail_count(inspection):
    return len([r for r in results_of(inspection)
                if r["outcome"] == "FAIL"
                and r["severity_class"] == "ESSENTIAL"])


def item_count(template):
    return len(_kids("checklist_items", "template_id", template["id"]))


def checklist_items_of(template_id):
    items = _kids("checklist_items", "template_id", template_id)
    return sorted(items, key=lambda r: (r["sequence_no"], r["_seq"]))


# ---------------------------------------------------------------------------
# bulletin and fleet-action aggregates (PRD 3.6)
# ---------------------------------------------------------------------------

def actions_of(bulletin_id):
    return store.by_seq(_kids("bulletin_actions", "bulletin_id", bulletin_id))


def action_total_count(bulletin):
    return len([a for a in actions_of(bulletin["id"])
                if a["status"] != "CANCELLED"])


def action_verified_count(bulletin):
    return len([a for a in actions_of(bulletin["id"])
                if a["status"] == "VERIFIED"])


def required_part_received(action):
    linked = [r for r in store.rows("requisitions")
              if r.get("bulletin_action_id") == action["id"]]
    if not linked:
        return True
    return any(r["status"] == "RECEIVED" for r in linked)


def booked_order_count(shop_bay):
    return len([o for o in _kids("work_orders", "shop_bay_id", shop_bay["id"])
                if o["status"] != "RECOMMISSIONED"])


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------

def _audit(row, view, versioned=True):
    view["id"] = row["id"]
    view["created_at"] = row["created_at"]
    if versioned:
        view["updated_at"] = row["updated_at"]
        view["version"] = row["version"]
    return view


def ser_attraction(row):
    return _audit(row, {
        "name": row["name"],
        "park_area": row["park_area"],
        "manufacturer": row["manufacturer"],
        "model_code": row["model_code"],
        "ride_class": row["ride_class"],
        "theoretical_hourly_capacity": row["theoretical_hourly_capacity"],
        "min_operators_required": row["min_operators_required"],
        "parts_budget_cents": row["parts_budget_cents"],
        "mean_repair_minutes": row["mean_repair_minutes"],
        "cumulative_cycles": row["cumulative_cycles"],
        "parts_budget_committed_cents": committed_cents(row),
        "ytd_downtime_minutes": ytd_downtime_minutes(row),
        "certified_operator_count": certified_operator_count(row),
        "regulatory_hold": regulatory_hold(row),
        "active_template_id": active_template_id(row),
        "last_signed_off_service_date": last_signed_off_service_date(row),
        "operational_posture": operational_posture(row),
    })


def ser_component(row):
    return _audit(row, {
        "attraction_id": row["attraction_id"],
        "name": row["name"],
        "component_type": row["component_type"],
        "criticality": row["criticality"],
        "ndt_interval_cycles": row["ndt_interval_cycles"],
        "ndt_interval_days": row["ndt_interval_days"],
        "last_ndt_at": row["last_ndt_at"],
        "last_ndt_cycles": row["last_ndt_cycles"],
        "last_ndt_method": row["last_ndt_method"],
        "condition_flag": row["condition_flag"],
        "ndt_status": ndt_status(row),
    })


def ser_template(row):
    return _audit(row, {
        "attraction_id": row["attraction_id"],
        "revision": row["revision"],
        "effective_from_date": row["effective_from_date"],
        "status": row["status"],
        "item_count": item_count(row),
        "activated_at": row["activated_at"],
    })


def ser_checklist_item(row):
    return _audit(row, {
        "template_id": row["template_id"],
        "sequence_no": row["sequence_no"],
        "description": row["description"],
        "severity_class": row["severity_class"],
        "component_id": row["component_id"],
        "requires_photo": row["requires_photo"],
    }, versioned=False)


def ser_inspection(row):
    return _audit(row, {
        "attraction_id": row["attraction_id"],
        "service_date": row["service_date"],
        "template_id": row["template_id"],
        "template_revision": row["template_revision"],
        "status": row["status"],
        "pending_item_count": pending_item_count(row),
        "blocking_item_count": blocking_item_count(row),
        "essential_fail_count": essential_fail_count(row),
        "opened_by_user_id": row["opened_by_user_id"],
        "recorded_by_user_ids": list(row["recorded_by_user_ids"]),
        "signed_off_by_user_id": row["signed_off_by_user_id"],
        "signed_off_at": row["signed_off_at"],
        "rejection_reason": row["rejection_reason"],
        "rework_round": row["rework_round"],
    })


def ser_item_result(row):
    return _audit(row, {
        "inspection_id": row["inspection_id"],
        "checklist_item_id": row["checklist_item_id"],
        "severity_class": row["severity_class"],
        "outcome": row["outcome"],
        "note": row["note"],
        "requires_photo": row["requires_photo"],
        "recorded_by_user_id": row["recorded_by_user_id"],
        "recorded_at": row["recorded_at"],
    })


def ser_bulletin(row):
    return _audit(row, {
        "bulletin_ref": row["bulletin_ref"],
        "manufacturer": row["manufacturer"],
        "model_code": row["model_code"],
        "severity": row["severity"],
        "issued_date": row["issued_date"],
        "compliance_deadline_date": row["compliance_deadline_date"],
        "supersedes_bulletin_id": row["supersedes_bulletin_id"],
        "status": row["status"],
        "action_total_count": action_total_count(row),
        "action_verified_count": action_verified_count(row),
        "acknowledged_at": row["acknowledged_at"],
        "acknowledged_by_user_id": row["acknowledged_by_user_id"],
    })


def ser_bulletin_action(row):
    return _audit(row, {
        "bulletin_id": row["bulletin_id"],
        "attraction_id": row["attraction_id"],
        "status": row["status"],
        "required_part_received": required_part_received(row),
        "deferral_reason": row["deferral_reason"],
        "deferred_until_date": row["deferred_until_date"],
        "verified_by_user_id": row["verified_by_user_id"],
        "verified_at": row["verified_at"],
    })


def ser_downtime_event(row):
    settled = row.get("_settled_hundredths")
    return _audit(row, {
        "attraction_id": row["attraction_id"],
        "service_date": row["service_date"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "cause_category": row["cause_category"],
        "status": row["status"],
        "auto_opened": row["auto_opened"],
        "duration_minutes": row["duration_minutes"],
        "peak_minutes": row["peak_minutes"],
        "off_peak_minutes": row["off_peak_minutes"],
        "settled_guest_slots_lost":
            None if settled is None else num.from_hundredths(settled),
        "root_cause_code": row["root_cause_code"],
        "failed_component_id": row["failed_component_id"],
        "void_reason": row["void_reason"],
    })


def ser_requisition(row):
    return _audit(row, {
        "attraction_id": row["attraction_id"],
        "part_number": row["part_number"],
        "quantity": row["quantity"],
        "unit_cost_cents": row["unit_cost_cents"],
        "total_cost_cents": row["total_cost_cents"],
        "needed_by_date": row["needed_by_date"],
        "downtime_event_id": row["downtime_event_id"],
        "bulletin_action_id": row["bulletin_action_id"],
        "status": row["status"],
        "expected_availability_date": row["expected_availability_date"],
        "cancel_reason": row["cancel_reason"],
    })


def ser_certification(row):
    return _audit(row, {
        "attraction_id": row["attraction_id"],
        "operator_user_id": row["operator_user_id"],
        "effective_from": row["effective_from"],
        "expires_at": row["expires_at"],
        "restraint_verification_score": row["restraint_verification_score"],
        "dispatch_procedure_score": row["dispatch_procedure_score"],
        "status": certification_status(row),
        "suspended_at": row["suspended_at"],
        "suspension_reason": row["suspension_reason"],
    })


def ser_incident(row):
    return _audit(row, {
        "attraction_id": row["attraction_id"],
        "occurred_at": row["occurred_at"],
        "injury_severity": row["injury_severity"],
        "guest_count_affected": row["guest_count_affected"],
        "narrative": row["narrative"],
        "status": row["status"],
        "regulator_notification_due_at": row["regulator_notification_due_at"],
        "notified_at": row["notified_at"],
        "notified_late": row["notified_late"],
        "regulator_case_ref": row["regulator_case_ref"],
        "investigator_user_id": row["investigator_user_id"],
        "suspended_certification_count": row["suspended_certification_count"],
        "regulator_clearance_ref": row["regulator_clearance_ref"],
        "cleared_at": row["cleared_at"],
    })


def ser_shop_bay(row):
    return _audit(row, {
        "name": row["name"],
        "concurrent_slot_capacity": row["concurrent_slot_capacity"],
        "booked_order_count": booked_order_count(row),
    })


def ser_work_order(row):
    return _audit(row, {
        "attraction_id": row["attraction_id"],
        "component_id": row["component_id"],
        "shop_bay_id": row["shop_bay_id"],
        "window_start_date": row["window_start_date"],
        "window_end_date": row["window_end_date"],
        "parts_subtotal_cents": row["parts_subtotal_cents"],
        "labor_hours": row["labor_hours"],
        "expedite_requested": row["expedite_requested"],
        "status": row["status"],
        "off_season": row["off_season"],
        "base_total_cents": row["base_total_cents"],
        "off_season_discount_cents": row["off_season_discount_cents"],
        "discounted_base_cents": row["discounted_base_cents"],
        "expedite_pct": row["expedite_pct"],
        "expedite_fee_cents": row["expedite_fee_cents"],
        "estimated_total_cents": row["estimated_total_cents"],
        "recommissioned_at": row["recommissioned_at"],
    })


SERIALIZERS = {
    "attractions": ser_attraction,
    "components": ser_component,
    "templates": ser_template,
    "checklist_items": ser_checklist_item,
    "inspections": ser_inspection,
    "item_results": ser_item_result,
    "bulletins": ser_bulletin,
    "bulletin_actions": ser_bulletin_action,
    "downtime_events": ser_downtime_event,
    "requisitions": ser_requisition,
    "certifications": ser_certification,
    "incidents": ser_incident,
    "shop_bays": ser_shop_bay,
    "work_orders": ser_work_order,
}


# ---------------------------------------------------------------------------
# version-bump reconciliation (PRD 2.5 / 2.11)
# ---------------------------------------------------------------------------
#
# A row's version increments by exactly one per mutation, and a cascade hop
# counts as a genuine mutation of the row it touches. Rather than sprinkling
# increments through every handler (which double-counts when two hops touch the
# same row), the request captures a snapshot of every row before the handler
# runs and bumps precisely those rows whose observable state changed.
#
# Aggregate counters that live on a parent row are part of that observable
# state, so moving a child requisition into RESERVED bumps the attraction whose
# committed ledger moved. Values that drift purely because the logical clock
# advanced -- ndt_status, certification status -- are deliberately excluded, as
# clock movement persists nothing and moves no state machine.

_VOLATILE = ("version", "updated_at", "_seq")

DERIVED_STATE = {
    "attractions": lambda r: (
        operational_posture(r),
        committed_cents(r),
        ytd_downtime_minutes(r),
        certified_operator_count(r),
        regulatory_hold(r),
        active_template_id(r),
        last_signed_off_service_date(r),
    ),
    "templates": lambda r: (item_count(r),),
    "inspections": lambda r: (
        pending_item_count(r),
        blocking_item_count(r),
        essential_fail_count(r),
    ),
    "bulletins": lambda r: (
        action_total_count(r),
        action_verified_count(r),
    ),
    "bulletin_actions": lambda r: (required_part_received(r),),
    "shop_bays": lambda r: (booked_order_count(r),),
}


def snapshot(collection, row):
    stored = tuple(sorted(
        (key, repr(value)) for key, value in row.items()
        if key not in _VOLATILE
    ))
    extra = DERIVED_STATE.get(collection)
    return (stored, repr(extra(row)) if extra else None)


def snapshot_all():
    snap = {}
    for collection in store.COLLECTIONS:
        for row_id, row in getattr(db, collection).items():
            snap[(collection, row_id)] = snapshot(collection, row)
    return snap


def apply_bumps(before):
    for collection in store.COLLECTIONS:
        for row_id, row in list(getattr(db, collection).items()):
            key = (collection, row_id)
            if key not in before:
                continue
            if before[key] != snapshot(collection, row):
                store.touch(row)


def commit():
    """Reconcile version/updated_at for every row this request mutated.

    Must be called before the response body is serialized so the caller sees
    the post-mutation version.
    """
    before = getattr(g, "pre_snapshot", None)
    if before is not None:
        g.pre_snapshot = None
        apply_bumps(before)
