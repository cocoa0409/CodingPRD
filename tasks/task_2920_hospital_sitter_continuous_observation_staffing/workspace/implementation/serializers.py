"""Entity -> JSON projections. Derived fields are recomputed at read time so a
list or fetch always reflects a full recomputation over the store."""
import calc
from db import iso


def _num(value):
    """Render a 1-decimal-place Decimal as a JSON number."""
    if value is None:
        return None
    return float(value)


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def unit_json(unit):
    out = {
        "unit_code": unit["unit_code"],
        "name": unit["name"],
        "video_monitoring_enabled": unit["video_monitoring_enabled"],
        "observation_cost_budget_cents": unit["observation_cost_budget_cents"],
        "observed_cost_to_date_cents": calc.ledger_head(unit),
        "status": unit["status"],
        "restriction_reason": unit["restriction_reason"],
        "open_order_count": calc.open_order_count(unit),
    }
    out.update(_common(unit))
    return out


def patient_json(patient):
    out = {
        "unit_id": patient["unit_id"],
        "mrn": patient["mrn"],
        "full_name": patient["full_name"],
        "age_years": patient["age_years"],
        "status": patient["status"],
        "discharged_at": iso(patient["discharged_at"]),
    }
    out.update(_common(patient))
    return out


def staff_json(staff):
    out = {
        "home_unit_id": staff["home_unit_id"],
        "full_name": staff["full_name"],
        "source_pool": staff["source_pool"],
        "hourly_rate_cents": staff["hourly_rate_cents"],
        "competency_level": staff["competency_level"],
        "deescalation_cert_expires_on": iso(staff["deescalation_cert_expires_on"]),
        "status": staff["status"],
        "suspension_reason": staff["suspension_reason"],
        "last_shift_end_at": iso(calc.last_shift_end_at(staff)),
        "total_watch_minutes": calc.total_watch_minutes(staff),
    }
    out.update(_common(staff))
    return out


def order_json(order):
    out = {
        "patient_id": order["patient_id"],
        "ordering_provider_user_id": order["ordering_provider_user_id"],
        "risk_categories": list(order["risk_categories"]),
        "required_modality": order["required_modality"],
        "clinical_rationale": order["clinical_rationale"],
        "status": order["status"],
        "elopement_risk_score": _num(order["elopement_risk_score"]),
        "risk_score_variant": order["risk_score_variant"],
        "reassessment_interval_hours": order["reassessment_interval_hours"],
        "last_reassessed_at": iso(order["last_reassessed_at"]),
        "next_reassessment_due_at": iso(order["next_reassessment_due_at"]),
        "reassessment_count": calc.reassessment_count(order),
        "coverage_gap_flag": order["coverage_gap_flag"],
        "discontinuation_recommendation": order["discontinuation_recommendation"],
        "discontinuation_review_opened_by_user_id": order["discontinuation_review_opened_by_user_id"],
        "discontinued_at": iso(order["discontinued_at"]),
        "lapsed_at": iso(order["lapsed_at"]),
    }
    out.update(_common(order))
    return out


def assignment_json(assignment):
    out = {
        "order_id": assignment["order_id"],
        "staff_id": assignment["staff_id"],
        "shift_start_at": iso(assignment["shift_start_at"]),
        "shift_end_at": iso(assignment["shift_end_at"]),
        "float_authorization_code": assignment["float_authorization_code"],
        "watch_status": assignment["watch_status"],
        "documentation_status": assignment["documentation_status"],
        "scheduled_minutes": calc.scheduled_minutes(assignment),
        "provisional_cost_cents": assignment["provisional_cost_cents"],
        "final_cost_cents": assignment["final_cost_cents"],
        "watch_segment_count": calc.watch_segment_count(assignment),
        "watched_minutes": calc.watched_minutes(assignment),
        "current_segment_started_at": iso(assignment["current_segment_started_at"]),
        "break_started_at": iso(assignment["break_started_at"]),
        "completion_reason": assignment["completion_reason"],
        "voided_at": iso(assignment["voided_at"]),
    }
    out.update(_common(assignment))
    return out


def station_json(station):
    out = {
        "observer_staff_id": station["observer_staff_id"],
        "station_label": station["station_label"],
        "declared_max_span": station["declared_max_span"],
        "status": station["status"],
        "active_feed_count": calc.active_feed_count(station),
        "active_acuity_weight": _num(calc.active_acuity_weight(station)),
        "effective_span_limit": calc.effective_span_limit(station),
        "offlined_at": iso(station["offlined_at"]),
    }
    out.update(_common(station))
    return out


def feed_json(feed):
    out = {
        "station_id": feed["station_id"],
        "order_id": feed["order_id"],
        "monitor_start_at": iso(feed["monitor_start_at"]),
        "monitor_end_at": iso(feed["monitor_end_at"]),
        "status": feed["status"],
        "acuity_weight": _num(feed["acuity_weight"]),
        "release_reason": feed["release_reason"],
        "released_at": iso(feed["released_at"]),
    }
    out.update(_common(feed))
    return out


def reassessment_json(row):
    # Immutable append-only artifact: only id and created_at, no updated_at, no
    # version (PRD 2.4).
    return {
        "id": row["id"],
        "order_id": row["order_id"],
        "performed_by_user_id": row["performed_by_user_id"],
        "risk_categories_after": list(row["risk_categories_after"]),
        "score_before": _num(row["score_before"]),
        "score_after": _num(row["score_after"]),
        "interval_hours_after": row["interval_hours_after"],
        "reassessed_at": iso(row["reassessed_at"]),
        "created_at": iso(row["created_at"]),
    }


def handoff_json(row):
    out = {
        "outgoing_assignment_id": row["outgoing_assignment_id"],
        "incoming_assignment_id": row["incoming_assignment_id"],
        "behavior_summary": row["behavior_summary"],
        "interventions_used": list(row["interventions_used"]),
        "countersigned_by_staff_id": row["countersigned_by_staff_id"],
        "countersigned_at": iso(row["countersigned_at"]),
        "documentation_state": row["documentation_state"],
    }
    out.update(_common(row))
    return out


def event_json(row):
    out = {
        "order_id": row["order_id"],
        "assignment_id": row["assignment_id"],
        "event_kind": row["event_kind"],
        "narrative": row["narrative"],
        "reported_by_staff_id": row["reported_by_staff_id"],
        "status": row["status"],
        "response_actions": list(row["response_actions"]) if row["response_actions"] is not None else None,
        "review_opened_by_user_id": row["review_opened_by_user_id"],
        "review_findings": row["review_findings"],
        "closed_by_user_id": row["closed_by_user_id"],
        "resolution": row["resolution"],
        "occurred_at": iso(row["occurred_at"]),
    }
    out.update(_common(row))
    return out


def cost_entry_json(row):
    out = {
        "unit_id": row["unit_id"],
        "assignment_id": row["assignment_id"],
        "entry_kind": row["entry_kind"],
        "amount_cents": row["amount_cents"],
        "status": row["status"],
        "source_pool": row["source_pool"],
        "segment_index": row["segment_index"],
        "segment_minutes": row["segment_minutes"],
        "night_differential_applied": row["night_differential_applied"],
        "posted_at": iso(row["posted_at"]),
        "reversed_at": iso(row["reversed_at"]),
    }
    out.update(_common(row))
    return out
