"""Entity serializers. Every resource carries id/created_at/updated_at/version."""
from response import iso, num


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def agency(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "agency_code": row["agency_code"],
        "agency_type": row["agency_type"],
        "fee_basis": row["fee_basis"],
        "interop_privilege": row["interop_privilege"],
        "console_position_count": row["console_position_count"],
        "recorder_retention_days": row["recorder_retention_days"],
        "billing_status": row["billing_status"],
        "billable_subscriber_count": row["billable_subscriber_count"],
        "last_assessed_fee_cents": row["last_assessed_fee_cents"],
        "fee_balance_cents": row["fee_balance_cents"],
        "lifetime_assessed_cents": row["lifetime_assessed_cents"],
        "lifetime_paid_cents": row["lifetime_paid_cents"],
        "last_assessment_period_start": iso(row["last_assessment_period_start"]),
        "last_assessment_period_end": iso(row["last_assessment_period_end"]),
        "payment_due_at": iso(row["payment_due_at"]),
        "governance_vote_weight": row["governance_vote_weight"],
        "voting_eligible": row["voting_eligible"],
        "active_patch_request_count": row["active_patch_request_count"],
    })
    return out


def site(row):
    out = _common(row)
    out.update({
        "site_code": row["site_code"],
        "name": row["name"],
        "channel_capacity": row["channel_capacity"],
        "backup_power_type": row["backup_power_type"],
        "battery_runtime_minutes": row["battery_runtime_minutes"],
        "generator_fuel_hours": num(row["generator_fuel_hours"]),
        "covered_test_points": row["covered_test_points"],
        "total_test_points": row["total_test_points"],
        "coverage_reliability_pct": num(row["coverage_reliability_pct"]),
        "coverage_derate_tier": row["coverage_derate_tier"],
        "coverage_class": row["coverage_class"],
        "status": row["status"],
        "capacity_mode": row["capacity_mode"],
        "busy_talkpaths": row["busy_talkpaths"],
        "peak_talkpaths": row["peak_talkpaths"],
        "granted_request_count": row["granted_request_count"],
        "busied_request_count": row["busied_request_count"],
        "grade_of_service_pct": num(row["grade_of_service_pct"]),
        "migration_standard": row["migration_standard"],
    })
    return out


def template(row):
    out = _common(row)
    out.update({
        "template_name": row["template_name"],
        "template_version": row["template_version"],
        "supersedes_template_id": row["supersedes_template_id"],
        "target_standard": row["target_standard"],
        "talkgroup_slot_count": row["talkgroup_slot_count"],
        "encryption_required": row["encryption_required"],
        "status": row["status"],
        "created_by_user_id": row["created_by_user_id"],
        "deployed_unit_count": row["deployed_unit_count"],
    })
    return out


def unit(row):
    out = _common(row)
    out.update({
        "agency_id": row["agency_id"],
        "template_id": row["template_id"],
        "active_keyset_id": row["active_keyset_id"],
        "serial_number": row["serial_number"],
        "radio_id": row["radio_id"],
        "model": row["model"],
        "provision_status": row["provision_status"],
        "key_status": row["key_status"],
        "priority_class": row["priority_class"],
        "emergency_button_enabled": row["emergency_button_enabled"],
        "assigned_at": iso(row["assigned_at"]),
        "retired_at": iso(row["retired_at"]),
        "last_otar_at": iso(row["last_otar_at"]),
        "billable": row["billable"],
        "days_in_service_last_period": row["days_in_service_last_period"],
    })
    return out


def keyset(row):
    out = _common(row)
    out.update({
        "keyset_name": row["keyset_name"],
        "algorithm": row["algorithm"],
        "crypto_period_start": iso(row["crypto_period_start"]),
        "crypto_period_end": iso(row["crypto_period_end"]),
        "status": row["status"],
        "created_by_user_id": row["created_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "loaded_unit_count": row["loaded_unit_count"],
        "compromised_at": iso(row["compromised_at"]),
    })
    return out


def campaign(row):
    out = _common(row)
    out.update({
        "keyset_id": row["keyset_id"],
        "agency_id": row["agency_id"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "status": row["status"],
        "target_unit_count": row["target_unit_count"],
        "rekeyed_unit_count": row["rekeyed_unit_count"],
        "failed_unit_count": row["failed_unit_count"],
        "executed_at": iso(row["executed_at"]),
    })
    return out


def talkgroup(row):
    out = _common(row)
    out.update({
        "owner_agency_id": row["owner_agency_id"],
        "home_site_id": row["home_site_id"],
        "alias": row["alias"],
        "tg_decimal_id": row["tg_decimal_id"],
        "kind": row["kind"],
        "encryption_mode": row["encryption_mode"],
        "priority_level": row["priority_level"],
        "status": row["status"],
        "lock_reason": row["lock_reason"],
        "active_patch_count": row["active_patch_count"],
    })
    return out


def patch(row):
    out = _common(row)
    out.update({
        "source_talkgroup_id": row["source_talkgroup_id"],
        "target_talkgroup_id": row["target_talkgroup_id"],
        "requesting_agency_id": row["requesting_agency_id"],
        "scheduled_start": iso(row["scheduled_start"]),
        "scheduled_end": iso(row["scheduled_end"]),
        "status": row["status"],
        "activated_at": iso(row["activated_at"]),
        "released_at": iso(row["released_at"]),
        "release_reason": row["release_reason"],
        "duration_minutes": num(row["duration_minutes"]),
        "recorder_retention_days_at_activation": row["recorder_retention_days_at_activation"],
    })
    return out


def site_event(row):
    out = _common(row)
    out.update({
        "site_id": row["site_id"],
        "event_class": row["event_class"],
        "cause": row["cause"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "detected_at": iso(row["detected_at"]),
        "status": row["status"],
        "escalation_tier": row["escalation_tier"],
        "backup_minutes_remaining": num(row["backup_minutes_remaining"]),
        "restored_at": iso(row["restored_at"]),
        "preempted_talkpath_count": row["preempted_talkpath_count"],
    })
    return out


def talkpath(row):
    out = _common(row)
    out.update({
        "site_id": row["site_id"],
        "talkgroup_id": row["talkgroup_id"],
        "unit_id": row["unit_id"],
        "site_event_id": row["site_event_id"],
        "preempted_request_id": row["preempted_request_id"],
        "request_kind": row["request_kind"],
        "outcome": row["outcome"],
        "priority_class_at_grant": row["priority_class_at_grant"],
        "available_talkpaths_at_decision": row["available_talkpaths_at_decision"],
        "reserve_talkpaths_at_decision": row["reserve_talkpaths_at_decision"],
        "granted_at": iso(row["granted_at"]),
        "released_at": iso(row["released_at"]),
        "hold_seconds": num(row["hold_seconds"]),
    })
    return out


def change_request(row):
    out = _common(row)
    out.update({
        "template_id": row["template_id"],
        "target_agency_id": row["target_agency_id"],
        "title": row["title"],
        "status": row["status"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "revision_count": row["revision_count"],
        "review_comment": row["review_comment"],
        "pinned_template_version": row["pinned_template_version"],
        "pinned_template_record_version": row["pinned_template_record_version"],
        "target_unit_count": row["target_unit_count"],
        "deployed_unit_count": row["deployed_unit_count"],
        "failed_unit_count": row["failed_unit_count"],
        "deployment_started_at": iso(row["deployment_started_at"]),
        "deployed_at": iso(row["deployed_at"]),
    })
    return out


SERIALIZERS = {
    "agencies": agency,
    "sites": site,
    "templates": template,
    "units": unit,
    "keysets": keyset,
    "campaigns": campaign,
    "talkgroups": talkgroup,
    "patches": patch,
    "site_events": site_event,
    "talkpaths": talkpath,
    "change_requests": change_request,
}
