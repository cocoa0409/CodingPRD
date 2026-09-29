"""Resource representations. Field names come straight from the entity tables."""
from common import iso3, num

COMMON = ("created_at", "updated_at", "version")


def _common(row, out):
    out["created_at"] = iso3(row["created_at"])
    out["updated_at"] = iso3(row["updated_at"])
    out["version"] = row["version"]
    return out


def country_profile(row):
    out = {
        "id": row["id"],
        "country_code": row["country_code"],
        "local_currency": row["local_currency"],
        "data_residency_region": row["data_residency_region"],
        "statutory_filing_deadline_days": row["statutory_filing_deadline_days"],
        "materiality_pct": num(row["materiality_pct"]),
        "materiality_floor_minor": row["materiality_floor_minor"],
        "penalty_daily_rate_minor": row["penalty_daily_rate_minor"],
        "required_filing_types": list(row["required_filing_types"]),
        "local_holidays": list(row["local_holidays"]),
        "open_filing_obligation_count": row["open_filing_obligation_count"],
    }
    return _common(row, out)


def provider(row):
    out = {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "service_scope": list(row["service_scope"]),
        "data_residency_regions": list(row["data_residency_regions"]),
        "annual_fee_minor": row["annual_fee_minor"],
        "indemnity_cap_pct": num(row["indemnity_cap_pct"]),
        "statutory_filing_capable": row["statutory_filing_capable"],
        "status": row["status"],
        "service_score": num(row["service_score"]),
        "score_variant_applied": row["score_variant_applied"],
        "open_penalty_minor": row["open_penalty_minor"],
    }
    return _common(row, out)


def engagement(row):
    out = {
        "id": row["id"],
        "country_profile_id": row["country_profile_id"],
        "provider_id": row["provider_id"],
        "transition_incoming_provider_id": row["transition_incoming_provider_id"],
        "service_scope": list(row["service_scope"]),
        "filing_responsibility": row["filing_responsibility"],
        "data_residency_region": row["data_residency_region"],
        "pay_frequency": row["pay_frequency"],
        "residency_terms_ref": row["residency_terms_ref"],
        "status": row["status"],
        "activated_at": iso3(row["activated_at"]) if row["activated_at"] else None,
        "treasury_committed_minor": row["treasury_committed_minor"],
        "transition_required": row["transition_required"],
        "closed_cycle_count": row["closed_cycle_count"],
        "transition_cutover_start_date": row["transition_cutover_start_date"],
        "transition_cutover_end_date": row["transition_cutover_end_date"],
        "transition_parallel_run_cycles": row["transition_parallel_run_cycles"],
    }
    return _common(row, out)


def cycle(row):
    out = {
        "id": row["id"],
        "engagement_id": row["engagement_id"],
        "prior_cycle_id": row["prior_cycle_id"],
        "period_label": row["period_label"],
        "period_start_date": row["period_start_date"],
        "period_end_date": row["period_end_date"],
        "pay_date": row["pay_date"],
        "cutoff_lead_working_days": row["cutoff_lead_working_days"],
        "input_cutoff_at": iso3(row["input_cutoff_at"]),
        "status": row["status"],
        "hold_reason": row["hold_reason"],
        "gross_total_minor": row["gross_total_minor"],
        "funded_total_minor": row["funded_total_minor"],
        "input_submitter_user_id": row["input_submitter_user_id"],
        "filings_confirmed_count": row["filings_confirmed_count"],
    }
    return _common(row, out)


def input_file(row):
    out = {
        "id": row["id"],
        "cycle_id": row["cycle_id"],
        "source_system": row["source_system"],
        "record_count": row["record_count"],
        "gross_declared_minor": row["gross_declared_minor"],
        "country_elements": dict(row["country_elements"]),
        "residency_region_of_transfer": row["residency_region_of_transfer"],
        "submitted_at": iso3(row["submitted_at"]),
        "status": row["status"],
        "rejection_code": row["rejection_code"],
        "validated_record_count": row["validated_record_count"],
    }
    return _common(row, out)


def gtn_run(row):
    out = {
        "id": row["id"],
        "cycle_id": row["cycle_id"],
        "input_file_id": row["input_file_id"],
        "gross_minor": row["gross_minor"],
        "net_minor": row["net_minor"],
        "employer_cost_minor": row["employer_cost_minor"],
        "provider_fee_minor": row["provider_fee_minor"],
        "employee_count": row["employee_count"],
        "status": row["status"],
        "variance_pct": num(row["variance_pct"]),
        "variance_basis": row["variance_basis"],
        "headcount_drift_pct": num(row["headcount_drift_pct"]),
        "variance_material": row["variance_material"],
        "variance_justification": row["variance_justification"],
        "return_reason": row["return_reason"],
    }
    return _common(row, out)


def bank_account(row):
    out = {
        "id": row["id"],
        "engagement_id": row["engagement_id"],
        "account_ref": row["account_ref"],
        "account_currency": row["account_currency"],
        "residency_region": row["residency_region"],
        "daily_cap_minor": row["daily_cap_minor"],
        "settlement_window_hours": row["settlement_window_hours"],
        "buffer_hours": row["buffer_hours"],
        "status": row["status"],
    }
    return _common(row, out)


def funding_instruction(row):
    out = {
        "id": row["id"],
        "cycle_id": row["cycle_id"],
        "bank_account_id": row["bank_account_id"],
        "value_date": row["value_date"],
        "funding_currency": row["funding_currency"],
        "fx_rate": num(row["fx_rate"]),
        "requested_local_minor": row["requested_local_minor"],
        "component_source_minor": dict(row["component_source_minor"]),
        "funded_source_minor": row["funded_source_minor"],
        "window_start_at": iso3(row["window_start_at"]),
        "window_end_at": iso3(row["window_end_at"]),
        "status": row["status"],
        "approver_user_id": row["approver_user_id"],
        "releaser_user_id": row["releaser_user_id"],
        "recall_reason": row["recall_reason"],
    }
    return _common(row, out)


def filing(row):
    out = {
        "id": row["id"],
        "cycle_id": row["cycle_id"],
        "filing_type": row["filing_type"],
        "responsibility": row["responsibility"],
        "due_at": iso3(row["due_at"]),
        "status": row["status"],
        "filed_at": iso3(row["filed_at"]) if row["filed_at"] else None,
        "submission_ref": row["submission_ref"],
        "confirmation_ref": row["confirmation_ref"],
        "late_days": row["late_days"],
        "penalty_status": row["penalty_status"],
        "base_penalty_minor": row["base_penalty_minor"],
        "surcharge_minor": row["surcharge_minor"],
        "total_penalty_minor": row["total_penalty_minor"],
        "provider_share_minor": row["provider_share_minor"],
        "client_share_minor": row["client_share_minor"],
        "penalty_owner": row["penalty_owner"],
        "dispute_round": row["dispute_round"],
        "dispute_reason": row["dispute_reason"],
    }
    return _common(row, out)


def incident(row):
    out = {
        "id": row["id"],
        "engagement_id": row["engagement_id"],
        "cycle_id": row["cycle_id"],
        "incident_type": row["incident_type"],
        "severity": row["severity"],
        "occurred_at": iso3(row["occurred_at"]),
        "note": row["note"],
        "status": row["status"],
        "escalation_level": row["escalation_level"],
        "weight_points": num(row["weight_points"]),
        "remediation_ref": row["remediation_ref"],
    }
    return _common(row, out)


def evidence(row):
    # Append-only: no updated_at, no version.
    return {
        "id": row["id"],
        "cycle_id": row["cycle_id"],
        "control_ref": row["control_ref"],
        "evidence_type": row["evidence_type"],
        "payload_hash": row["payload_hash"],
        "recorded_by_role": row["recorded_by_role"],
        "recorded_by_user_id": row["recorded_by_user_id"],
        "sequence_no": row["sequence_no"],
        "created_at": iso3(row["created_at"]),
    }
