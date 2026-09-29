"""Row -> JSON payload conversion."""

from decimal import Decimal


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def grower(row):
    out = _common(row)
    out.update({
        "legal_name": row["legal_name"],
        "operator_type": row["operator_type"],
        "tax_id": row["tax_id"],
        "mailing_state": row["mailing_state"],
        "status": row["status"],
        "suspension_reason": row["suspension_reason"],
        "total_enrolled_acres": num(row["total_enrolled_acres"]),
        "lifetime_credits_issued": row["lifetime_credits_issued"],
        "net_paid_cents": row["net_paid_cents"],
        "outstanding_clawback_cents": row["outstanding_clawback_cents"],
        "reversal_count": row["reversal_count"],
    })
    return out


def field(row):
    out = _common(row)
    out.update({
        "grower_id": row["grower_id"],
        "field_name": row["field_name"],
        "boundary_min_x": row["boundary_min_x"],
        "boundary_min_y": row["boundary_min_y"],
        "boundary_max_x": row["boundary_max_x"],
        "boundary_max_y": row["boundary_max_y"],
        "gross_acres": num(row["gross_acres"]),
        "mapped_acres": num(row["mapped_acres"]),
        "soil_group": row["soil_group"],
        "county_code": row["county_code"],
        "status": row["status"],
        "surveyor_reference": row["surveyor_reference"],
    })
    return out


def practice_history(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "field_id": row["field_id"],
        "crop_year": row["crop_year"],
        "practice_code": row["practice_code"],
        "adopted": row["adopted"],
        "evidence_source": row["evidence_source"],
        "acres": num(row["acres"]),
        "observed_emissions_per_acre": num(row["observed_emissions_per_acre"]),
    }


def practice_standard(row):
    out = _common(row)
    out.update({
        "practice_code": row["practice_code"],
        "standard_version": row["standard_version"],
        "additionality_lookback_years": row["additionality_lookback_years"],
        "max_prior_adoption_pct": num(row["max_prior_adoption_pct"]),
        "min_documented_years": row["min_documented_years"],
        "min_adoption_years": row["min_adoption_years"],
        "uncertainty_base_pct": num(row["uncertainty_base_pct"]),
        "sequestration_rate_per_acre": num(row["sequestration_rate_per_acre"]),
        "modeled_baseline_rate_per_acre": num(row["modeled_baseline_rate_per_acre"]),
        "buffer_base_pct": num(row["buffer_base_pct"]),
        "telemetry_required": row["telemetry_required"],
        "effective_from": row["effective_from"],
        "status": row["status"],
        "revision_note": row.get("revision_note"),
    })
    return out


def enrollment(row):
    out = _common(row)
    out.update({
        "grower_id": row["grower_id"],
        "field_id": row["field_id"],
        "practice_standard_id": row["practice_standard_id"],
        "practice_code": row["practice_code"],
        "pinned_standard_version": row["pinned_standard_version"],
        "commitment_years": row["commitment_years"],
        "start_crop_year": row["start_crop_year"],
        "enrolled_acres": num(row["enrolled_acres"]),
        "payment_model": row["payment_model"],
        "per_acre_rate_cents": num(row["per_acre_rate_cents"]),
        "per_credit_share_pct": num(row["per_credit_share_pct"]),
        "prior_adoption_pct": num(row["prior_adoption_pct"]),
        "additionality_score": num(row["additionality_score"]),
        "documented_years": row["documented_years"],
        "status": row["status"],
        "permanence_status": row["permanence_status"],
        "screening_decision_admin_id": row["screening_decision_admin_id"],
        "baseline_approval_admin_id": row["baseline_approval_admin_id"],
        "rejection_reason": row["rejection_reason"],
        "missing_items": row["missing_items"],
        "exit_reason": row["exit_reason"],
        "requested_exit_year": row["requested_exit_year"],
        "exit_fee_cents": row["exit_fee_cents"],
        "terminated_effective_year": row["terminated_effective_year"],
        "accrued_payment_cents": row["accrued_payment_cents"],
        "credits_issued_total": row["credits_issued_total"],
    })
    return out


def baseline(row):
    out = _common(row)
    out.update({
        "enrollment_id": row["enrollment_id"],
        "method": row["method"],
        "qualifying_years": row["qualifying_years"],
        "historical_mean_rate": num(row["historical_mean_rate"]),
        "baseline_emissions_t": num(row["baseline_emissions_t"]),
        "uncertainty_pct": num(row["uncertainty_pct"]),
        "status": row["status"],
        "approved_by_admin_id": row["approved_by_admin_id"],
        "rejection_note": row["rejection_note"],
    })
    return out


def data_packet(row):
    out = _common(row)
    out.update({
        "enrollment_id": row["enrollment_id"],
        "crop_year": row["crop_year"],
        "source": row["source"],
        "reported_acres": num(row["reported_acres"]),
        "measured_value": num(row["measured_value"]),
        "coverage_pct": num(row["coverage_pct"]),
        "qc_score": num(row["qc_score"]),
        "qc_status": row["qc_status"],
        "completeness_status": row["completeness_status"],
        "flag_reason": row["flag_reason"],
        "correction_count": row["correction_count"],
    })
    return out


def quantification_run(row):
    out = _common(row)
    out.update({
        "enrollment_id": row["enrollment_id"],
        "baseline_id": row["baseline_id"],
        "crop_year": row["crop_year"],
        "method": row["method"],
        "verified_acres": num(row["verified_acres"]),
        "mean_coverage_pct": num(row["mean_coverage_pct"]),
        "adoption_factor": num(row["adoption_factor"]),
        "sampling_uncertainty_pct": num(row["sampling_uncertainty_pct"]),
        "gross_removals_t": num(row["gross_removals_t"]),
        "uncertainty_deduction_t": num(row["uncertainty_deduction_t"]),
        "net_removals_t": num(row["net_removals_t"]),
        "packet_count": row["packet_count"],
        "status": row["status"],
        "revision_count": row["revision_count"],
    })
    return out


def verification_body(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "accreditation_id": row["accreditation_id"],
        "accredited_practices": list(row["accredited_practices"]),
        "max_concurrent_visits": row["max_concurrent_visits"],
        "status": row["status"],
    })
    return out


def verification(row):
    out = _common(row)
    out.update({
        "quantification_run_id": row["quantification_run_id"],
        "verification_body_id": row["verification_body_id"],
        "sample_pct": num(row["sample_pct"]),
        "site_visit_start": row["site_visit_start"],
        "site_visit_end": row["site_visit_end"],
        "opinion": row["opinion"],
        "restated_removals_t": num(row["restated_removals_t"]),
        "material_discrepancy_pct": num(row["material_discrepancy_pct"]),
        "findings_note": row["findings_note"],
        "resample_count": row["resample_count"],
    })
    return out


def credit_batch(row):
    out = _common(row)
    out.update({
        "enrollment_id": row["enrollment_id"],
        "quantification_run_id": row["quantification_run_id"],
        "supersedes_batch_id": row["supersedes_batch_id"],
        "vintage_year": row["vintage_year"],
        "gross_credits": row["gross_credits"],
        "buffer_pct": num(row["buffer_pct"]),
        "buffer_credits": row["buffer_credits"],
        "issued_credits": row["issued_credits"],
        "risk_tier": row["risk_tier"],
        "serial_start": row["serial_start"],
        "serial_end": row["serial_end"],
        "issuance_status": row["issuance_status"],
        "registry_status": row["registry_status"],
        "registry_account_ref": row["registry_account_ref"],
        "retirement_beneficiary": row["retirement_beneficiary"],
        "cancellation_reason": row["cancellation_reason"],
    })
    return out


def buffer_account(row):
    out = _common(row)
    out.update({
        "pool_code": row["pool_code"],
        "balance_credits": row["balance_credits"],
        "contributed_total": row["contributed_total"],
        "drawn_total": row["drawn_total"],
        "released_total": row["released_total"],
        "unbacked_reversal_credits": row["unbacked_reversal_credits"],
        "outstanding_issued_credits": row["outstanding_issued_credits"],
        "min_reserve_ratio": num(row["min_reserve_ratio"]),
        "required_reserve_credits": row["required_reserve_credits"],
        "next_serial_number": row["next_serial_number"],
        "pool_status": row["pool_status"],
    })
    return out


def reversal_event(row):
    out = _common(row)
    out.update({
        "enrollment_id": row["enrollment_id"],
        "credit_batch_id": row["credit_batch_id"],
        "reversal_type": row["reversal_type"],
        "affected_acres": num(row["affected_acres"]),
        "detected_crop_year": row["detected_crop_year"],
        "affected_credits": row["affected_credits"],
        "buffer_draw_credits": row["buffer_draw_credits"],
        "unbacked_credits": row["unbacked_credits"],
        "grower_clawback_cents": row["grower_clawback_cents"],
        "status": row["status"],
        "reported_by_admin_id": row["reported_by_admin_id"],
        "assessed_by_admin_id": row["assessed_by_admin_id"],
        "resolution_note": row["resolution_note"],
    })
    return out


def grower_payment(row):
    out = _common(row)
    out.update({
        "enrollment_id": row["enrollment_id"],
        "credit_batch_id": row["credit_batch_id"],
        "crop_year": row["crop_year"],
        "payment_model": row["payment_model"],
        "payable_acres": num(row["payable_acres"]),
        "gross_amount_cents": row["gross_amount_cents"],
        "holdback_pct": num(row["holdback_pct"]),
        "holdback_cents": row["holdback_cents"],
        "net_amount_cents": row["net_amount_cents"],
        "status": row["status"],
        "paid_at": row["paid_at"],
    })
    return out
