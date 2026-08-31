"""Entity serialisation — exactly the fields declared in §1.1."""

from calc import num
from rollups import effective_posture

COMMON = ("id", "created_at", "updated_at", "version")


def _base(row):
    return {k: row[k] for k in COMMON}


def program(row):
    out = _base(row)
    out.update({
        "name": row["name"],
        "fiscal_year": row["fiscal_year"],
        "budget_cents": row["budget_cents"],
        "cost_per_participant_ceiling_cents": row["cost_per_participant_ceiling_cents"],
        "staff_hourly_rate_cents": row["staff_hourly_rate_cents"],
        "eligible_jurisdiction_codes": list(row["eligible_jurisdiction_codes"]),
        "posture": effective_posture(row),
        "posture_override": row["posture_override"],
        "posture_override_expires_utc": row["posture_override_expires_utc"],
        "budget_encumbered_cents": row["budget_encumbered_cents"],
        "budget_in_transit_cents": row["budget_in_transit_cents"],
        "budget_spent_cents": row["budget_spent_cents"],
        "open_containment_deficiency_count": row["open_containment_deficiency_count"],
        "budget_alert_count": row["budget_alert_count"],
        "participant_count_ytd": row["participant_count_ytd"],
        "tonnage_ytd_kg": num(row["tonnage_ytd_kg"]),
    })
    return out


def site(row):
    out = _base(row)
    out.update({
        "program_id": row["program_id"],
        "replaces_site_id": row["replaces_site_id"],
        "name": row["name"],
        "address": row["address"],
        "impervious_surface": row["impervious_surface"],
        "secondary_containment_liters": row["secondary_containment_liters"],
        "storm_drain_distance_m": num(row["storm_drain_distance_m"]),
        "lane_count": row["lane_count"],
        "status": row["status"],
        "approved_by_user_id": row["approved_by_user_id"],
        "last_inspection_result": row["last_inspection_result"],
    })
    return out


def material_category(row):
    out = _base(row)
    out.update({
        "program_id": row["program_id"],
        "code": row["code"],
        "display_name": row["display_name"],
        "acceptance_policy": row["acceptance_policy"],
        "compatibility_class": row["compatibility_class"],
        "dot_hazard_class": row["dot_hazard_class"],
        "max_kg_per_resident_per_event": num(row["max_kg_per_resident_per_event"]),
        "max_kg_per_resident_per_year": num(row["max_kg_per_resident_per_year"]),
        "disposal_rate_cents_per_kg": row["disposal_rate_cents_per_kg"],
        "business_referral_program_code": row["business_referral_program_code"],
    })
    return out


def resident(row):
    out = _base(row)
    out.update({
        "program_id": row["program_id"],
        "full_name": row["full_name"],
        "street_address": row["street_address"],
        "claimed_jurisdiction_code": row["claimed_jurisdiction_code"],
        "eligibility_status": row["eligibility_status"],
        "verified_jurisdiction_code": row["verified_jurisdiction_code"],
        "annual_quantity_reserved_kg": num(row["annual_quantity_reserved_kg"]),
        "annual_quantity_settled_kg": num(row["annual_quantity_settled_kg"]),
        "no_show_strike_count": row["no_show_strike_count"],
        "completed_visit_count": row["completed_visit_count"],
    })
    return out


def collection_event(row):
    out = _base(row)
    out.update({
        "program_id": row["program_id"],
        "site_id": row["site_id"],
        "window_start_utc": row["window_start_utc"],
        "window_end_utc": row["window_end_utc"],
        "min_viable_registrations": row["min_viable_registrations"],
        "event_date": row["event_date"],
        "window_duration_hours": num(row["window_duration_hours"]),
        "lifecycle_status": row["lifecycle_status"],
        "containment_status": row["containment_status"],
        "containment_findings": [dict(f) for f in row["containment_findings"]],
        "open_lane_count": row["open_lane_count"],
        "certified_staff_hours": num(row["certified_staff_hours"]),
        "staffing_cost_cents": row["staffing_cost_cents"],
        "slot_capacity": row["slot_capacity"],
        "reserved_slot_count": row["reserved_slot_count"],
        "participant_count": row["participant_count"],
        "accepted_tonnage_kg": num(row["accepted_tonnage_kg"]),
        "rejected_tonnage_kg": num(row["rejected_tonnage_kg"]),
        "tonnage_reported_kg": num(row["tonnage_reported_kg"]),
        "projected_cost_per_participant_cents": row["projected_cost_per_participant_cents"],
        "discrepancy_container_count": row["discrepancy_container_count"],
        "cancel_reason": row["cancel_reason"],
    })
    return out


def staffer(row):
    out = _base(row)
    out.update({
        "program_id": row["program_id"],
        "full_name": row["full_name"],
        "role_code": row["role_code"],
        "hazwoper_expires_on": row["hazwoper_expires_on"],
        "status": row["status"],
        "assigned_hours": num(row["assigned_hours"]),
    })
    return out


def lane_assignment(row):
    out = _base(row)
    out.update({
        "event_id": row["event_id"],
        "staffer_id": row["staffer_id"],
        "lane_number": row["lane_number"],
        "start_utc": row["start_utc"],
        "end_utc": row["end_utc"],
        "duration_hours": num(row["duration_hours"]),
        "status": row["status"],
        "released_reason": row["released_reason"],
    })
    return out


def appointment(row):
    out = _base(row)
    out.update({
        "event_id": row["event_id"],
        "resident_id": row["resident_id"],
        "slot_start_utc": row["slot_start_utc"],
        "waste_origin": row["waste_origin"],
        "declared_total_kg": num(row["declared_total_kg"]),
        "declared_category_ids": list(row["declared_category_ids"]),
        "vehicle_count": row["vehicle_count"],
        "status": row["status"],
        "waitlist_reason": row["waitlist_reason"],
        "cancel_reason": row["cancel_reason"],
        "referral_program_code": row["referral_program_code"],
        "referral_packet_code": row["referral_packet_code"],
        "queue_seq": row["queue_seq"],
        "reserved_kg": num(row["reserved_kg"]),
        "settled_kg": num(row["settled_kg"]),
        "check_in_utc": row["check_in_utc"],
        "unload_complete_utc": row["unload_complete_utc"],
    })
    return out


def dropoff_line(row):
    out = _base(row)
    out.update({
        "appointment_id": row["appointment_id"],
        "material_category_id": row["material_category_id"],
        "container_id": row["container_id"],
        "declared_kg": num(row["declared_kg"]),
        "net_weight_kg": num(row["net_weight_kg"]),
        "disposition": row["disposition"],
        "rejection_reason_code": row["rejection_reason_code"],
        "estimated_disposal_cost_cents": row["estimated_disposal_cost_cents"],
        "screened_by_user_id": row["screened_by_user_id"],
    })
    return out


def packed_container(row):
    out = _base(row)
    out.update({
        "event_id": row["event_id"],
        "manifest_id": row["manifest_id"],
        "container_code": row["container_code"],
        "compatibility_class": row["compatibility_class"],
        "capacity_kg": num(row["capacity_kg"]),
        "status": row["status"],
        "line_count": row["line_count"],
        "net_weight_kg": num(row["net_weight_kg"]),
        "estimated_disposal_cost_cents": row["estimated_disposal_cost_cents"],
        "sealed_by_user_id": row["sealed_by_user_id"],
        "discrepancy_flag": row["discrepancy_flag"],
    })
    return out


def manifest(row):
    out = _base(row)
    out.update({
        "event_id": row["event_id"],
        "manifest_tracking_number": row["manifest_tracking_number"],
        "tsdf_epa_id": row["tsdf_epa_id"],
        "status": row["status"],
        "container_ids": list(row["container_ids"]),
        "net_weight_kg": num(row["net_weight_kg"]),
        "estimated_disposal_cost_cents": row["estimated_disposal_cost_cents"],
        "blended_rate_cents_per_kg": num(row["blended_rate_cents_per_kg"]),
        "invoiced_disposal_cost_cents": row["invoiced_disposal_cost_cents"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "signed_by_user_id": row["signed_by_user_id"],
        "signed_at_utc": row["signed_at_utc"],
        "discrepancy_code": row["discrepancy_code"],
        "superseded_by_manifest_id": row["superseded_by_manifest_id"],
    })
    return out
