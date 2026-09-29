"""Resource representations (PRD 2.5 common fields + the entity field lists)."""

from clockmod import fmt_dt

FIELDS = {
    "pilots": ["full_name", "email", "operator_category", "status", "certified_at",
               "currency_expires_at", "currency_basis", "last_completed_flight_end",
               "knowledge_attempt_count", "risk_score", "open_waiver_count",
               "suspension_reason"],
    "knowledge_tests": ["pilot_id", "test_code", "scheduled_at", "status",
                        "attempt_number", "raw_score", "passed", "graded_at"],
    "certifications": ["pilot_id", "originating_test_id", "supersedes_certification_id",
                       "certificate_number", "category", "issued_at", "expires_at",
                       "status"],
    "aircraft": ["owner_pilot_id", "model", "serial_number", "takeoff_weight_g",
                 "max_altitude_ft", "remote_id_required", "registration_number",
                 "registration_status", "grounding_reason"],
    "modules": ["aircraft_id", "module_serial", "broadcast_protocol", "firmware_version",
                "broadcast_sample_ref", "status", "verified_at", "verified_until",
                "failure_reason"],
    "zones": ["designator", "class_code", "class_ceiling_ft", "requires_authorization",
              "max_concurrent_authorizations", "structure_relief_eligible",
              "reserved_slot_count"],
    "tfrs": ["zone_id", "reason", "effective_from", "effective_until",
             "max_permitted_altitude_ft", "status", "published_by_user_id"],
    "authorizations": ["pilot_id", "aircraft_id", "zone_id", "waiver_id",
                       "requested_ceiling_ft", "window_start", "window_end", "status",
                       "granted_ceiling_ft", "approved_by_user_id", "decided_at",
                       "denial_reason"],
    "waivers": ["pilot_id", "aircraft_id", "waiver_type", "requested_ceiling_ft",
                "operation_description", "status", "revision_round",
                "granted_ceiling_ft", "valid_until", "approved_by_user_id",
                "denial_reason"],
    "safety_cases": ["waiver_id", "mitigation_summary", "ground_risk_class",
                     "air_risk_class", "contingency_procedures", "sail_level",
                     "review_status", "reviewer_findings", "cleared_by_user_id"],
    "policies": ["pilot_id", "insurer_name", "policy_number", "coverage_limit_cents",
                 "deductible_cents", "effective_from", "effective_until",
                 "indemnification_clause_accepted", "coverage_status",
                 "open_reserved_cents_total", "settled_cents_total",
                 "remaining_coverage_cents"],
    "flights": ["pilot_id", "aircraft_id", "zone_id", "authorization_id", "waiver_id",
                "covering_policy_id", "operation_category", "planned_start",
                "planned_end", "planned_max_altitude_ft", "launch_latitude",
                "launch_longitude", "over_people", "night_operation",
                "beyond_visual_line_of_sight", "status", "investigation_status",
                "actual_start", "actual_end", "max_altitude_reached_ft",
                "incident_occurred", "incident_summary", "altitude_exceedance",
                "logged_minutes", "cancellation_reason"],
    "preflight_checks": ["flight_id", "checked_at", "result", "blocking_findings",
                         "active_tfr_ids", "acknowledged_tfr_ids", "airspace_class_code",
                         "effective_ceiling_ft"],
    "reports": ["flight_id", "policy_id", "occurred_at", "injury_level",
                "reported_property_damage_cents", "narrative", "status",
                "remediation_round", "remediation_findings", "damage_line_items",
                "reserved_cents", "settlement_cents", "probable_cause",
                "closed_by_user_id"],
}

DATETIME_FIELDS = {
    "certified_at", "currency_expires_at", "last_completed_flight_end", "scheduled_at",
    "graded_at", "issued_at", "expires_at", "verified_at", "verified_until",
    "window_start", "window_end", "decided_at", "valid_until", "effective_from",
    "effective_until", "planned_start", "planned_end", "actual_start", "actual_end",
    "checked_at", "occurred_at",
}

# PreflightCheck is the sole entity carrying neither updated_at nor version
# (PRD 2.5).
UNVERSIONED = {"preflight_checks"}


def view(row):
    if row is None:
        return None
    kind = row["_kind"]
    out = {"id": row["id"], "created_at": fmt_dt(row["created_at"])}
    if kind not in UNVERSIONED:
        out["updated_at"] = fmt_dt(row["updated_at"])
        out["version"] = row["version"]
    for field in FIELDS[kind]:
        value = row.get(field)
        if field in DATETIME_FIELDS:
            out[field] = fmt_dt(value)
        else:
            out[field] = value
    return out


def view_all(rows):
    return [view(row) for row in rows]
