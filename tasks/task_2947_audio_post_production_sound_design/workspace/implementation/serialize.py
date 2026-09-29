"""Wire representations.

PRD §2.5 splits resources in two: most carry id/created_at/updated_at/version,
while PlatformSpec, QcReport and ArchivePackage are immutable and carry only id
and created_at — no updated_at and no version.
"""

import clock


def _num(value):
    """Decimal quantities are emitted as JSON numbers carried to 2 decimals."""
    if value is None:
        return None
    return float(value)


def _inst(value):
    return clock.fmt(value)


def _common(record, versioned=True):
    out = {"created_at": _inst(record["created_at"])}
    if versioned:
        out["updated_at"] = _inst(record["updated_at"])
        out["version"] = record["version"]
    return out


def platform_spec(rec):
    out = {
        "id": rec["id"],
        "platform": rec["platform"],
        "spec_label": rec["spec_label"],
        "target_lufs": _num(rec["target_lufs"]),
        "tolerance_lu": _num(rec["tolerance_lu"]),
        "true_peak_max_dbtp": _num(rec["true_peak_max_dbtp"]),
        "channel_layout": rec["channel_layout"],
        "requires_me_stems": rec["requires_me_stems"],
        "max_remediation_rounds": rec["max_remediation_rounds"],
        "qc_turnaround_hours": rec["qc_turnaround_hours"],
    }
    out.update(_common(rec, versioned=False))
    return out


def mix_stage(rec):
    out = {
        "id": rec["id"],
        "room_code": rec["room_code"],
        "display_name": rec["display_name"],
        "hourly_rate_cents": rec["hourly_rate_cents"],
        "supports_remote_review": rec["supports_remote_review"],
        "changeover_minutes": rec["changeover_minutes"],
    }
    out.update(_common(rec))
    return out


def mixer(rec):
    out = {
        "id": rec["id"],
        "full_name": rec["full_name"],
        "certified_platforms": list(rec["certified_platforms"]),
        "max_daily_hours": _num(rec["max_daily_hours"]),
    }
    out.update(_common(rec))
    return out


def voice_talent(rec):
    out = {
        "id": rec["id"],
        "full_name": rec["full_name"],
        "union_status": rec["union_status"],
        "daily_cap_minutes": rec["daily_cap_minutes"],
        "min_call_minutes": rec["min_call_minutes"],
    }
    out.update(_common(rec))
    return out


def library_asset(rec):
    out = {
        "id": rec["id"],
        "asset_code": rec["asset_code"],
        "kind": rec["kind"],
        "license_type": rec["license_type"],
        "territory_scope": rec["territory_scope"],
        "fee_cents": rec["fee_cents"],
        "expires_at_utc": _inst(rec["expires_at_utc"]),
        "status": rec["status"],
        "revocation_reason": rec["revocation_reason"],
    }
    out.update(_common(rec))
    return out


def project(rec):
    out = {
        "id": rec["id"],
        "title": rec["title"],
        "client_name": rec["client_name"],
        "client_user_id": rec["client_user_id"],
        "delivery_deadline_utc": _inst(rec["delivery_deadline_utc"]),
        "turnaround_class": rec["turnaround_class"],
        "stage_hours_authorized": _num(rec["stage_hours_authorized"]),
        "picture_status": rec["picture_status"],
        "picture_locked_at_utc": _inst(rec["picture_locked_at_utc"]),
        "picture_lock_revision": rec["picture_lock_revision"],
        "pipeline_stage": rec["pipeline_stage"],
        "posture": rec["posture"],
        "stage_hours_reserved": _num(rec["stage_hours_reserved"]),
        "stage_hours_consumed": _num(rec["stage_hours_consumed"]),
        "stage_hours_available": _num(rec["stage_hours_available"]),
        "stage_cost_subtotal_cents": rec["stage_cost_subtotal_cents"],
        "adr_cost_cents": rec["adr_cost_cents"],
        "license_fee_accrued_cents": rec["license_fee_accrued_cents"],
        "billing_total_cents": rec["billing_total_cents"],
        "license_risk_score_intake": _num(rec["license_risk_score_intake"]),
        "license_risk_score_audit": _num(rec["license_risk_score_audit"]),
        "unlicensed_usage_count": rec["unlicensed_usage_count"],
        "stale_stem_count": rec["stale_stem_count"],
        "conformed_stem_count": rec["conformed_stem_count"],
    }
    out.update(_common(rec))
    return out


def stem_package(rec):
    out = {
        "id": rec["id"],
        "project_id": rec["project_id"],
        "reel_label": rec["reel_label"],
        "stem_layout": rec["stem_layout"],
        "includes_me_stems": rec["includes_me_stems"],
        "status": rec["status"],
        "conform_round": rec["conform_round"],
        "cue_count": rec["cue_count"],
        "total_stem_minutes": _num(rec["total_stem_minutes"]),
        "conform_fee_cents": rec["conform_fee_cents"],
        "conformed_at_utc": _inst(rec["conformed_at_utc"]),
        "stale_reason": rec["stale_reason"],
    }
    out.update(_common(rec))
    return out


def music_cue(rec):
    out = {
        "id": rec["id"],
        "stem_package_id": rec["stem_package_id"],
        "cue_number": rec["cue_number"],
        "duration_seconds": rec["duration_seconds"],
        "source": rec["source"],
        "composer_delivery_ref": rec["composer_delivery_ref"],
        "status": rec["status"],
    }
    out.update(_common(rec))
    return out


def asset_usage(rec):
    out = {
        "id": rec["id"],
        "library_asset_id": rec["library_asset_id"],
        "stem_package_id": rec["stem_package_id"],
        "usage_seconds": rec["usage_seconds"],
        "territory_declared": rec["territory_declared"],
        "clearance_status": rec["clearance_status"],
        "accrued_fee_cents": rec["accrued_fee_cents"],
        "cleared_at_utc": _inst(rec["cleared_at_utc"]),
        "unlicensed_reason": rec["unlicensed_reason"],
    }
    out.update(_common(rec))
    return out


def adr_session(rec):
    out = {
        "id": rec["id"],
        "project_id": rec["project_id"],
        "voice_talent_id": rec["voice_talent_id"],
        "window_start_utc": _inst(rec["window_start_utc"]),
        "window_end_utc": _inst(rec["window_end_utc"]),
        "lines_scheduled": rec["lines_scheduled"],
        "lines_recorded": rec["lines_recorded"],
        "status": rec["status"],
        "scheduled_minutes": _num(rec["scheduled_minutes"]),
        "billable_minutes": _num(rec["billable_minutes"]),
        "session_cost_cents": rec["session_cost_cents"],
        "cancellation_reason": rec["cancellation_reason"],
    }
    out.update(_common(rec))
    return out


def mix_booking(rec):
    out = {
        "id": rec["id"],
        "project_id": rec["project_id"],
        "mix_stage_id": rec["mix_stage_id"],
        "mixer_id": rec["mixer_id"],
        "booking_type": rec["booking_type"],
        "platform": rec["platform"],
        "window_start_utc": _inst(rec["window_start_utc"]),
        "window_end_utc": _inst(rec["window_end_utc"]),
        "client_attendance": rec["client_attendance"],
        "status": rec["status"],
        "reserved_hours": _num(rec["reserved_hours"]),
        "provisional_cost_cents": rec["provisional_cost_cents"],
        "actual_start_utc": _inst(rec["actual_start_utc"]),
        "actual_end_utc": _inst(rec["actual_end_utc"]),
        "billable_hours_final": _num(rec["billable_hours_final"]),
        "overtime_hours": _num(rec["overtime_hours"]),
        "final_cost_cents": rec["final_cost_cents"],
        "client_signoff_at_utc": _inst(rec["client_signoff_at_utc"]),
        "release_reason": rec["release_reason"],
    }
    out.update(_common(rec))
    return out


def deliverable(rec):
    out = {
        "id": rec["id"],
        "project_id": rec["project_id"],
        "platform_spec_id": rec["platform_spec_id"],
        "stem_package_id": rec["stem_package_id"],
        "mix_booking_id": rec["mix_booking_id"],
        "status": rec["status"],
        "measured_integrated_lufs": _num(rec["measured_integrated_lufs"]),
        "measured_true_peak_dbtp": _num(rec["measured_true_peak_dbtp"]),
        "me_stems_present": rec["me_stems_present"],
        "deviation_lu": _num(rec["deviation_lu"]),
        "remediation_round": rec["remediation_round"],
        "qc_rejection_codes": list(rec["qc_rejection_codes"]),
        "prepared_by_user_id": rec["prepared_by_user_id"],
        "delivery_reference": rec["delivery_reference"],
        "delivered_at_utc": _inst(rec["delivered_at_utc"]),
        "invalidation_reason": rec["invalidation_reason"],
    }
    out.update(_common(rec))
    return out


def qc_report(rec):
    out = {
        "id": rec["id"],
        "deliverable_id": rec["deliverable_id"],
        "round": rec["round"],
        "verdict": rec["verdict"],
        "rejection_codes": list(rec["rejection_codes"]),
        "measured_integrated_lufs": _num(rec["measured_integrated_lufs"]),
        "measured_true_peak_dbtp": _num(rec["measured_true_peak_dbtp"]),
        "target_lufs": _num(rec["target_lufs"]),
        "deviation_lu": _num(rec["deviation_lu"]),
        "submitted_by_user_id": rec["submitted_by_user_id"],
        "evaluated_by_user_id": rec["evaluated_by_user_id"],
        "evaluated_at_utc": _inst(rec["evaluated_at_utc"]),
    }
    out.update(_common(rec, versioned=False))
    return out


def archive_package(rec):
    out = {
        "id": rec["id"],
        "project_id": rec["project_id"],
        "session_file_count": rec["session_file_count"],
        "retention_years": rec["retention_years"],
        "stem_manifest_count": rec["stem_manifest_count"],
        "archived_stem_package_ids": list(rec["archived_stem_package_ids"]),
        "delivered_deliverable_count": rec["delivered_deliverable_count"],
        "sealed_at_utc": _inst(rec["sealed_at_utc"]),
        "sealed_by_user_id": rec["sealed_by_user_id"],
    }
    out.update(_common(rec, versioned=False))
    return out


def project_ledger(rec):
    """PRD §3.8: the ledger read returns exactly these fields."""
    return {
        "stage_hours_authorized": _num(rec["stage_hours_authorized"]),
        "stage_hours_reserved": _num(rec["stage_hours_reserved"]),
        "stage_hours_consumed": _num(rec["stage_hours_consumed"]),
        "stage_hours_available": _num(rec["stage_hours_available"]),
        "stage_cost_subtotal_cents": rec["stage_cost_subtotal_cents"],
        "adr_cost_cents": rec["adr_cost_cents"],
        "conform_fee_total_cents": rec["conform_fee_total_cents"],
        "license_fee_accrued_cents": rec["license_fee_accrued_cents"],
        "pre_discount_total_cents": rec["pre_discount_total_cents"],
        "volume_discount_cents": rec["volume_discount_cents"],
        "discounted_base_cents": rec["discounted_base_cents"],
        "rush_surcharge_cents": rec["rush_surcharge_cents"],
        "billing_total_cents": rec["billing_total_cents"],
        "license_risk_score_intake": _num(rec["license_risk_score_intake"]),
        "license_risk_score_audit": _num(rec["license_risk_score_audit"]),
        "unlicensed_usage_count": rec["unlicensed_usage_count"],
        "stale_stem_count": rec["stale_stem_count"],
        "conformed_stem_count": rec["conformed_stem_count"],
        "posture": rec["posture"],
        "pipeline_stage": rec["pipeline_stage"],
        "picture_status": rec["picture_status"],
    }
