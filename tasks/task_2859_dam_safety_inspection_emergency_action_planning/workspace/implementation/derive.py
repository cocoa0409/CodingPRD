"""Derived (`source: computed`) fields and JSON serialisers.

Computed fields are re-derived on every read so that advancing the logical clock
never mutates a row yet a subsequent read reports the fresh value (PRD Section 2.4).
Stored fields carry only what an operation explicitly writes.
"""

from decimal import Decimal

import calc
from common import add_days, fmt_dt, num
from store import (
    db, dam_deficiencies, dam_drawdowns, dam_inspections, dam_orders, dam_plans,
    engineer_inspections, event_readings, insertion_order, owner_dams, owner_entries,
    pick_greatest, pick_newest_created, plan_exercises, reach_drawdowns,
)

ACTIVE_COMMITMENT_STATUSES = ("COORDINATED", "ACTIVE")
OPEN_INSPECTION_STATUSES = ("SCHEDULED", "SUBMITTED", "RETURNED")


# ---------------------------------------------------------------------------
# Owner
# ---------------------------------------------------------------------------

def ledger_replay(owner_id):
    """Replay the owner's append-only ledger in ascending sequence_no, producing
    the running balance carried by each row and the owner's final balance."""
    entries = sorted(owner_entries(owner_id), key=lambda r: r["sequence_no"])
    balance = 0
    running = {}
    for entry in entries:
        balance += entry["amount_cents"]
        running[entry["id"]] = balance
    return running, balance


def owner_balance_cents(owner_id):
    return ledger_replay(owner_id)[1]


def owner_delinquency_status(owner_id):
    return "DELINQUENT" if owner_balance_cents(owner_id) >= calc.DELINQUENCY_THRESHOLD_CENTS else "CURRENT"


def owner_is_delinquent(owner_id):
    return owner_delinquency_status(owner_id) == "DELINQUENT"


def next_ledger_sequence_no(owner_id):
    entries = owner_entries(owner_id)
    highest = 0
    for entry in entries:
        if entry["sequence_no"] > highest:
            highest = entry["sequence_no"]
    return highest + 1


def serialize_owner(owner):
    return {
        "id": owner["id"],
        "legal_name": owner["legal_name"],
        "owner_type": owner["owner_type"],
        "contact_email": owner["contact_email"],
        "financial_assurance_bond_cents": owner["financial_assurance_bond_cents"],
        "fee_balance_cents": owner_balance_cents(owner["id"]),
        "delinquency_status": owner_delinquency_status(owner["id"]),
        "registered_dam_count": len(owner_dams(owner["id"])),
        "created_at": fmt_dt(owner["created_at"]),
        "updated_at": fmt_dt(owner["updated_at"]),
        "version": owner["version"],
    }


def serialize_ledger_entry(entry, running=None):
    if running is None:
        running = ledger_replay(entry["owner_id"])[0]
    return {
        "id": entry["id"],
        "owner_id": entry["owner_id"],
        "sequence_no": entry["sequence_no"],
        "entry_type": entry["entry_type"],
        "amount_cents": entry["amount_cents"],
        "source_ref": entry["source_ref"],
        "memo": entry["memo"],
        "balance_after_cents": running.get(entry["id"]),
        "posted_by_user_id": entry["posted_by_user_id"],
        "created_at": fmt_dt(entry["created_at"]),
    }


# ---------------------------------------------------------------------------
# Engineer
# ---------------------------------------------------------------------------

def engineer_license_status(engineer):
    return "ACTIVE" if engineer["license_expires_at"] > db.clock else "EXPIRED"


def engineer_open_inspection_count(engineer_id):
    return len([i for i in engineer_inspections(engineer_id)
                if i["status"] in OPEN_INSPECTION_STATUSES])


def serialize_engineer(engineer):
    return {
        "id": engineer["id"],
        "full_name": engineer["full_name"],
        "license_number": engineer["license_number"],
        "license_expires_at": fmt_dt(engineer["license_expires_at"]),
        "certified_hazard_classes": list(engineer["certified_hazard_classes"]),
        "license_status": engineer_license_status(engineer),
        "open_inspection_count": engineer_open_inspection_count(engineer["id"]),
        "created_at": fmt_dt(engineer["created_at"]),
        "updated_at": fmt_dt(engineer["updated_at"]),
        "version": engineer["version"],
    }


# ---------------------------------------------------------------------------
# River reach
# ---------------------------------------------------------------------------

def reach_committed_release_cfs(reach_id):
    total = 0
    for order in reach_drawdowns(reach_id):
        if order["status"] in ACTIVE_COMMITMENT_STATUSES:
            total += order["requested_release_cfs"]
    return total


def reach_active_drawdown_count(reach_id):
    return len([o for o in reach_drawdowns(reach_id)
                if o["status"] in ACTIVE_COMMITMENT_STATUSES])


def serialize_reach(reach):
    return {
        "id": reach["id"],
        "name": reach["name"],
        "channel_capacity_cfs": reach["channel_capacity_cfs"],
        "downstream_community": reach["downstream_community"],
        "committed_release_cfs": reach_committed_release_cfs(reach["id"]),
        "active_drawdown_count": reach_active_drawdown_count(reach["id"]),
        "created_at": fmt_dt(reach["created_at"]),
        "updated_at": fmt_dt(reach["updated_at"]),
        "version": reach["version"],
    }


# ---------------------------------------------------------------------------
# Dam
# ---------------------------------------------------------------------------

def dam_certified_assessment(dam_id):
    rows = [a for a in db.assessments.values()
            if a["dam_id"] == dam_id and a["status"] == "CERTIFIED"]
    return pick_newest_created(rows)


def dam_hazard_class(dam):
    assessment = dam_certified_assessment(dam["id"])
    if assessment is None:
        return "UNCLASSIFIED"
    return assessment["certified_hazard_class"]


def dam_consequence_score(dam):
    assessment = dam_certified_assessment(dam["id"])
    if assessment is None:
        return None
    return assessment["certified_score"]


def dam_latest_accepted_inspection(dam_id, inspection_type=None):
    rows = [i for i in dam_inspections(dam_id) if i["status"] == "ACCEPTED"]
    if inspection_type is not None:
        rows = [i for i in rows if i["inspection_type"] == inspection_type]
    rows = [i for i in rows if i.get("performed_at") is not None]
    return pick_greatest(rows, "performed_at")


def dam_safety_status(dam):
    inspection = dam_latest_accepted_inspection(dam["id"])
    if inspection is None:
        return "UNRATED"
    return inspection["condition_rating"]


def dam_next_inspection_due_at(dam):
    baseline_inspection = dam_latest_accepted_inspection(dam["id"], "PERIODIC")
    baseline = baseline_inspection["performed_at"] if baseline_inspection else dam["registered_at"]
    return calc.next_inspection_due(baseline, dam_hazard_class(dam))


def dam_inspection_overdue(dam):
    return db.clock > dam_next_inspection_due_at(dam)


def dam_open_deficiency_count(dam_id):
    return len([d for d in dam_deficiencies(dam_id) if d["status"] != "CLOSED_VERIFIED"])


def dam_escalated_deficiency_count(dam_id):
    return len([d for d in dam_deficiencies(dam_id) if d["status"] == "ESCALATED"])


def dam_newest_plan(dam_id):
    return pick_newest_created(dam_plans(dam_id))


def dam_latest_eap_status(dam_id):
    plan = dam_newest_plan(dam_id)
    return plan["status"] if plan else "NONE"


def dam_approved_plan(dam_id):
    rows = [p for p in dam_plans(dam_id) if p["status"] == "APPROVED"]
    return pick_newest_created(rows)


def dam_eap_required(dam):
    return calc.EAP_REQUIRED[dam_hazard_class(dam)]


def dam_committed_drawdown_acre_ft(dam_id):
    total = Decimal("0")
    for order in dam_drawdowns(dam_id):
        if order["status"] in ACTIVE_COMMITMENT_STATUSES:
            total += order["planned_release_acre_ft"]
    return total


def dam_available_storage_acre_ft(dam):
    return calc.available_storage_acre_ft(
        dam["gross_storage_acre_ft"], dam_committed_drawdown_acre_ft(dam["id"]))


def dam_outstanding_penalty_cents(dam_id):
    return sum(o["assessed_penalty_cents"] for o in dam_orders(dam_id))


def serialize_dam(dam):
    hazard = dam_hazard_class(dam)
    return {
        "id": dam["id"],
        "owner_id": dam["owner_id"],
        "river_reach_id": dam["river_reach_id"],
        "name": dam["name"],
        "nid_code": dam["nid_code"],
        "height_ft": dam["height_ft"],
        "gross_storage_acre_ft": dam["gross_storage_acre_ft"],
        "crest_elevation_ft": dam["crest_elevation_ft"],
        "normal_pool_elevation_ft": dam["normal_pool_elevation_ft"],
        "year_completed": dam["year_completed"],
        "registered_at": fmt_dt(dam["registered_at"]),
        "hazard_class": hazard,
        "current_consequence_score": num(dam_consequence_score(dam)),
        "safety_status": dam_safety_status(dam),
        "regulatory_status": dam["regulatory_status"],
        "next_inspection_due_at": fmt_dt(dam_next_inspection_due_at(dam)),
        "inspection_overdue": dam_inspection_overdue(dam),
        "open_deficiency_count": dam_open_deficiency_count(dam["id"]),
        "latest_eap_status": dam_latest_eap_status(dam["id"]),
        "eap_required": calc.EAP_REQUIRED[hazard],
        "committed_drawdown_acre_ft": num(calc.rhu_committed(dam_committed_drawdown_acre_ft(dam["id"]))),
        "available_conservation_storage_acre_ft": num(dam_available_storage_acre_ft(dam)),
        "created_at": fmt_dt(dam["created_at"]),
        "updated_at": fmt_dt(dam["updated_at"]),
        "version": dam["version"],
    }


# ---------------------------------------------------------------------------
# Consequence assessment
# ---------------------------------------------------------------------------

def serialize_assessment(assessment):
    return {
        "id": assessment["id"],
        "dam_id": assessment["dam_id"],
        "prepared_by_user_id": assessment["prepared_by_user_id"],
        "population_at_risk": assessment["population_at_risk"],
        "habitable_structures": assessment["habitable_structures"],
        "critical_facilities": assessment["critical_facilities"],
        "breach_peak_outflow_cfs": assessment["breach_peak_outflow_cfs"],
        "breach_travel_time_minutes": assessment["breach_travel_time_minutes"],
        "inundation_area_acres": assessment["inundation_area_acres"],
        "inundation_map_ref": assessment["inundation_map_ref"],
        "screening_score": num(assessment["screening_score"]),
        "recommended_hazard_class": assessment["recommended_hazard_class"],
        "certified_score": num(assessment["certified_score"]),
        "certified_hazard_class": assessment["certified_hazard_class"],
        "status": assessment["status"],
        "certified_at": fmt_dt(assessment["certified_at"]),
        "superseded_at": fmt_dt(assessment["superseded_at"]),
        "created_at": fmt_dt(assessment["created_at"]),
        "updated_at": fmt_dt(assessment["updated_at"]),
        "version": assessment["version"],
    }


# ---------------------------------------------------------------------------
# Inspection / deficiency / remediation order
# ---------------------------------------------------------------------------

def serialize_inspection(inspection):
    return {
        "id": inspection["id"],
        "dam_id": inspection["dam_id"],
        "engineer_id": inspection["engineer_id"],
        "inspection_type": inspection["inspection_type"],
        "window_start": fmt_dt(inspection["window_start"]),
        "window_end": fmt_dt(inspection["window_end"]),
        "performed_at": fmt_dt(inspection["performed_at"]),
        "condition_rating": inspection["condition_rating"],
        "narrative": inspection["narrative"],
        "status": inspection["status"],
        "deficiency_count": inspection["deficiency_count"],
        "return_count": inspection["return_count"],
        "accepted_by_user_id": inspection["accepted_by_user_id"],
        "accepted_at": fmt_dt(inspection["accepted_at"]),
        "created_at": fmt_dt(inspection["created_at"]),
        "updated_at": fmt_dt(inspection["updated_at"]),
        "version": inspection["version"],
    }


def deficiency_order_count(deficiency_id):
    return len([o for o in db.orders.values() if o["deficiency_id"] == deficiency_id])


def serialize_deficiency(deficiency):
    return {
        "id": deficiency["id"],
        "dam_id": deficiency["dam_id"],
        "inspection_id": deficiency["inspection_id"],
        "source": deficiency["source"],
        "category": deficiency["category"],
        "severity": deficiency["severity"],
        "description": deficiency["description"],
        "status": deficiency["status"],
        "remediation_due_at": fmt_dt(deficiency["remediation_due_at"]),
        "order_count": deficiency_order_count(deficiency["id"]),
        "closed_at": fmt_dt(deficiency["closed_at"]),
        "created_at": fmt_dt(deficiency["created_at"]),
        "updated_at": fmt_dt(deficiency["updated_at"]),
        "version": deficiency["version"],
    }


def serialize_order(order):
    return {
        "id": order["id"],
        "deficiency_id": order["deficiency_id"],
        "dam_id": order["dam_id"],
        "owner_id": order["owner_id"],
        "order_type": order["order_type"],
        "requested_response_days": order["requested_response_days"],
        "effective_response_days": order["effective_response_days"],
        "issued_at": fmt_dt(order["issued_at"]),
        "compliance_deadline_at": fmt_dt(order["compliance_deadline_at"]),
        "daily_penalty_rate_cents": order["daily_penalty_rate_cents"],
        "status": order["status"],
        "response_filed_at": fmt_dt(order["response_filed_at"]),
        "corrective_action_summary": order["corrective_action_summary"],
        "completed_at": fmt_dt(order["completed_at"]),
        "verified_by_user_id": order["verified_by_user_id"],
        "defaulted_at": fmt_dt(order["defaulted_at"]),
        "assessed_penalty_cents": order["assessed_penalty_cents"],
        "created_at": fmt_dt(order["created_at"]),
        "updated_at": fmt_dt(order["updated_at"]),
        "version": order["version"],
    }


# ---------------------------------------------------------------------------
# Emergency action plan / exercise
# ---------------------------------------------------------------------------

def plan_accepted_exercises(plan_id):
    return [e for e in plan_exercises(plan_id) if e["outcome"] == "ACCEPTED"]


def plan_accepted_exercise_count(plan_id):
    return len(plan_accepted_exercises(plan_id))


def plan_last_accepted_exercise_at(plan_id):
    row = pick_greatest(plan_accepted_exercises(plan_id), "conducted_at")
    return row["conducted_at"] if row else None


def plan_exercise_current(plan):
    """Exercises attached to a SUPERSEDED or EXPIRED plan never count."""
    if plan["status"] != "APPROVED":
        return False
    horizon = add_days(db.clock, -calc.EXERCISE_CURRENCY_DAYS)
    for exercise in plan_accepted_exercises(plan["id"]):
        if exercise["conducted_at"] > horizon and exercise["conducted_at"] <= db.clock:
            return True
    return False


def dam_exercise_current(dam_id):
    plan = dam_approved_plan(dam_id)
    if plan is None:
        return False
    return plan_exercise_current(plan)


def serialize_plan(plan):
    return {
        "id": plan["id"],
        "dam_id": plan["dam_id"],
        "version_label": plan["version_label"],
        "inundation_map_ref": plan["inundation_map_ref"],
        "notification_flowchart_ref": plan["notification_flowchart_ref"],
        "notification_contact_count": plan["notification_contact_count"],
        "drawdown_procedure_ref": plan["drawdown_procedure_ref"],
        "status": plan["status"],
        "review_findings": plan["review_findings"],
        "approved_at": fmt_dt(plan["approved_at"]),
        "expires_at": fmt_dt(plan["expires_at"]),
        "last_accepted_exercise_at": fmt_dt(plan_last_accepted_exercise_at(plan["id"])),
        "accepted_exercise_count": plan_accepted_exercise_count(plan["id"]),
        "exercise_current": plan_exercise_current(plan),
        "created_at": fmt_dt(plan["created_at"]),
        "updated_at": fmt_dt(plan["updated_at"]),
        "version": plan["version"],
    }


def serialize_exercise(exercise):
    return {
        "id": exercise["id"],
        "eap_id": exercise["eap_id"],
        "exercise_type": exercise["exercise_type"],
        "conducted_at": fmt_dt(exercise["conducted_at"]),
        "participant_count": exercise["participant_count"],
        "notification_test_passed": exercise["notification_test_passed"],
        "outcome": exercise["outcome"],
        "deficiency_reason": exercise["deficiency_reason"],
        "logged_by_user_id": exercise["logged_by_user_id"],
        "created_at": fmt_dt(exercise["created_at"]),
    }


# ---------------------------------------------------------------------------
# Permit
# ---------------------------------------------------------------------------

def serialize_permit(permit):
    return {
        "id": permit["id"],
        "dam_id": permit["dam_id"],
        "owner_id": permit["owner_id"],
        "review_engineer_id": permit["review_engineer_id"],
        "permit_type": permit["permit_type"],
        "scope_description": permit["scope_description"],
        "estimated_project_cost_cents": permit["estimated_project_cost_cents"],
        "proposed_start_date": fmt_dt(permit["proposed_start_date"]),
        "base_fee_cents": permit["base_fee_cents"],
        "engineering_review_fee_cents": permit["engineering_review_fee_cents"],
        "delinquency_surcharge_cents": permit["delinquency_surcharge_cents"],
        "volume_credit_cents": permit["volume_credit_cents"],
        "total_fee_cents": permit["total_fee_cents"],
        "status": permit["status"],
        "decision_findings": permit["decision_findings"],
        "conditions": permit["conditions"],
        "revision_count": permit["revision_count"],
        "issued_at": fmt_dt(permit["issued_at"]),
        "created_at": fmt_dt(permit["created_at"]),
        "updated_at": fmt_dt(permit["updated_at"]),
        "version": permit["version"],
    }


# ---------------------------------------------------------------------------
# High-water event / elevation reading / drawdown order
# ---------------------------------------------------------------------------

def event_latest_reading(event_id):
    return pick_greatest(event_readings(event_id), "reading_at")


def event_current_alert_level(event_id):
    reading = event_latest_reading(event_id)
    return reading["alert_level"] if reading else "NORMAL"


def event_peak_pool_elevation_ft(event_id):
    readings = event_readings(event_id)
    if not readings:
        return None
    peak = None
    for reading in readings:
        value = reading["pool_elevation_ft"]
        if peak is None or value > peak:
            peak = value
    return peak


def serialize_event(event):
    return {
        "id": event["id"],
        "dam_id": event["dam_id"],
        "declared_at": fmt_dt(event["declared_at"]),
        "trigger_description": event["trigger_description"],
        "declared_inflow_cfs": event["declared_inflow_cfs"],
        "status": event["status"],
        "current_alert_level": event_current_alert_level(event["id"]),
        "peak_pool_elevation_ft": event_peak_pool_elevation_ft(event["id"]),
        "reading_count": len(event_readings(event["id"])),
        "escalated_at": fmt_dt(event["escalated_at"]),
        "stood_down_at": fmt_dt(event["stood_down_at"]),
        "final_pool_elevation_ft": event["final_pool_elevation_ft"],
        "created_at": fmt_dt(event["created_at"]),
        "updated_at": fmt_dt(event["updated_at"]),
        "version": event["version"],
    }


def serialize_reading(reading):
    return {
        "id": reading["id"],
        "high_water_event_id": reading["high_water_event_id"],
        "reading_at": fmt_dt(reading["reading_at"]),
        "pool_elevation_ft": reading["pool_elevation_ft"],
        "observed_inflow_cfs": reading["observed_inflow_cfs"],
        "freeboard_ft": num(reading["freeboard_ft"]),
        "alert_level": reading["alert_level"],
        "rising": reading["rising"],
        "recorded_by_user_id": reading["recorded_by_user_id"],
        "created_at": fmt_dt(reading["created_at"]),
    }


def serialize_drawdown(order):
    return {
        "id": order["id"],
        "dam_id": order["dam_id"],
        "river_reach_id": order["river_reach_id"],
        "high_water_event_id": order["high_water_event_id"],
        "requested_release_cfs": order["requested_release_cfs"],
        "window_start": fmt_dt(order["window_start"]),
        "window_end": fmt_dt(order["window_end"]),
        "planned_release_acre_ft": num(order["planned_release_acre_ft"]),
        "actual_release_acre_ft": num(order["actual_release_acre_ft"]),
        "status": order["status"],
        "coordinated_at": fmt_dt(order["coordinated_at"]),
        "activated_at": fmt_dt(order["activated_at"]),
        "completed_at": fmt_dt(order["completed_at"]),
        "cancelled_at": fmt_dt(order["cancelled_at"]),
        "cancel_reason": order["cancel_reason"],
        "created_at": fmt_dt(order["created_at"]),
        "updated_at": fmt_dt(order["updated_at"]),
        "version": order["version"],
    }


# ---------------------------------------------------------------------------
# Compliance summary projection (GET /dams/{dam_id}/compliance-summary)
# ---------------------------------------------------------------------------

def compliance_summary(dam):
    newest_plan = dam_newest_plan(dam["id"])
    return {
        "dam_id": dam["id"],
        "hazard_class": dam_hazard_class(dam),
        "safety_status": dam_safety_status(dam),
        "regulatory_status": dam["regulatory_status"],
        "current_consequence_score": num(dam_consequence_score(dam)),
        "next_inspection_due_at": fmt_dt(dam_next_inspection_due_at(dam)),
        "inspection_overdue": dam_inspection_overdue(dam),
        "open_deficiency_count": dam_open_deficiency_count(dam["id"]),
        "escalated_deficiency_count": dam_escalated_deficiency_count(dam["id"]),
        "latest_eap_status": dam_latest_eap_status(dam["id"]),
        "eap_expires_at": fmt_dt(newest_plan["expires_at"]) if newest_plan else None,
        "eap_exercise_current": dam_exercise_current(dam["id"]),
        "outstanding_penalty_cents": dam_outstanding_penalty_cents(dam["id"]),
        "owner_delinquency_status": owner_delinquency_status(dam["owner_id"]),
        "committed_drawdown_acre_ft": num(calc.rhu_committed(dam_committed_drawdown_acre_ft(dam["id"]))),
        "available_conservation_storage_acre_ft": num(dam_available_storage_acre_ft(dam)),
    }


# ---------------------------------------------------------------------------
# List helper
# ---------------------------------------------------------------------------

def paginate(rows, limit, offset, serializer):
    ordered = insertion_order(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [serializer(row) for row in window], total
