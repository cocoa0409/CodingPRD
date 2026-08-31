"""Resource serialisers.  Field sets follow the scaffold entity tables plus the
common resource properties of PRD 2.4."""

from store import iso


def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": iso(row["created_at"])}
    if versioned:
        out["updated_at"] = iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def institution(row):
    out = {
        "lei": row["lei"],
        "name": row["name"],
        "activity_year": row["activity_year"],
        "asset_size_usd_cents": row["asset_size_usd_cents"],
        "prior_year_closed_end_originations": row["prior_year_closed_end_originations"],
        "prior_year_open_end_originations": row["prior_year_open_end_originations"],
        "partial_exemption_eligible": row["partial_exemption_eligible"],
        "quarterly_filer": row["quarterly_filer"],
        "required_field_count": row["required_field_count"],
        "total_application_count": row["total_application_count"],
        "pending_record_count": row["pending_record_count"],
        "reportable_record_count": row["reportable_record_count"],
        "excluded_record_count": row["excluded_record_count"],
        "cleared_record_count": row["cleared_record_count"],
        "open_register_count": row["open_register_count"],
        "filing_posture": row["filing_posture"],
        "filing_deadline_at": iso(row["filing_deadline_at"]),
    }
    out.update(_common(row))
    return out


def application(row):
    out = {
        "institution_id": row["institution_id"],
        "uli": row["uli"],
        "application_date": iso(row["application_date"]),
        "application_channel": row["application_channel"],
        "loan_type": row["loan_type"],
        "loan_purpose": row["loan_purpose"],
        "occupancy_type": row["occupancy_type"],
        "lien_status": row["lien_status"],
        "loan_amount_cents": row["loan_amount_cents"],
        "income_thousands": row["income_thousands"],
        "rate_spread": row["rate_spread"],
        "purchaser_type": row["purchaser_type"],
        "denial_reason_codes": list(row["denial_reason_codes"]),
        "business_or_commercial_purpose": row["business_or_commercial_purpose"],
        "open_end_line_of_credit": row["open_end_line_of_credit"],
        "action_taken": row["action_taken"],
        "action_taken_date": iso(row["action_taken_date"]),
        "supersedes_application_id": row["supersedes_application_id"],
        "is_superseded": row["is_superseded"],
        "stage": row["stage"],
        "lar_status": row["lar_status"],
        "captured_field_count": row["captured_field_count"],
        "applicable_field_count": row["applicable_field_count"],
        "exclusion_reason": row["exclusion_reason"],
    }
    out.update(_common(row))
    return out


def demographic_entry(row):
    out = {
        "application_id": row["application_id"],
        "applicant_role": row["applicant_role"],
        "is_natural_person": row["is_natural_person"],
        "collection_method": row["collection_method"],
        "ethnicity_codes": list(row["ethnicity_codes"]),
        "race_codes": list(row["race_codes"]),
        "sex_code": row["sex_code"],
        "age_years": row["age_years"],
        "observation_basis": row["observation_basis"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def geocode_assignment(row):
    out = {
        "application_id": row["application_id"],
        "census_tract_id": row["census_tract_id"],
        "street_address": row["street_address"],
        "city": row["city"],
        "state_code": row["state_code"],
        "zip_code": row["zip_code"],
        "county_fips": row["county_fips"],
        "submitted_tract_code": row["submitted_tract_code"],
        "candidate_count": row["candidate_count"],
        "msa_md_code": row["msa_md_code"],
        "override_reason": row["override_reason"],
        "is_current": row["is_current"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def census_tract(row):
    out = {
        "tract_code": row["tract_code"],
        "county_fips": row["county_fips"],
        "state_code": row["state_code"],
        "msa_md_code": row["msa_md_code"],
        "minority_population_pct": row["minority_population_pct"],
        "tract_to_msa_income_pct": row["tract_to_msa_income_pct"],
        "owner_occupied_units": row["owner_occupied_units"],
        "median_family_income_cents": row["median_family_income_cents"],
    }
    out.update(_common(row, versioned=False))
    return out


def edit_run(row):
    out = {
        "institution_id": row["institution_id"],
        "run_index": row["run_index"],
        "scope": row["scope"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "snapshot_record_count": row["snapshot_record_count"],
        "syntactical_count": row["syntactical_count"],
        "validity_count": row["validity_count"],
        "quality_count": row["quality_count"],
        "macro_count": row["macro_count"],
        "total_exception_count": row["total_exception_count"],
        "open_exception_count": row["open_exception_count"],
        "verified_exception_count": row["verified_exception_count"],
        "stale_exception_count": row["stale_exception_count"],
        "cleared_record_count": row["cleared_record_count"],
        "required_verified_quota": row["required_verified_quota"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def edit_exception(row):
    out = {
        "edit_run_id": row["edit_run_id"],
        "application_id": row["application_id"],
        "edit_code": row["edit_code"],
        "severity": row["severity"],
        "field_name": row["field_name"],
        "message": row["message"],
        "verification_note": row["verification_note"],
        "verified_by_user_id": row["verified_by_user_id"],
        "verified_at": iso(row["verified_at"]),
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def filing_submission(row):
    out = {
        "institution_id": row["institution_id"],
        "edit_run_id": row["edit_run_id"],
        "activity_year": row["activity_year"],
        "submission_index": row["submission_index"],
        "provisional_record_count": row["provisional_record_count"],
        "final_record_count": row["final_record_count"],
        "certified_by_user_id": row["certified_by_user_id"],
        "certified_at": iso(row["certified_at"]),
        "attestation_text": row["attestation_text"],
        "filed_at": iso(row["filed_at"]),
        "deadline_at": iso(row["deadline_at"]),
        "is_late": row["is_late"],
        "late_by_days": row["late_by_days"],
        "rejection_reason": row["rejection_reason"],
        "resubmission_count": row["resubmission_count"],
        "is_superseded": row["is_superseded"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def disclosure_statement(row):
    out = {
        "submission_id": row["submission_id"],
        "statement_type": row["statement_type"],
        "record_count": row["record_count"],
        "tract_suppression_count": row["tract_suppression_count"],
        "suppressed_record_count": row["suppressed_record_count"],
        "redacted_field_count": row["redacted_field_count"],
        "published_at": iso(row["published_at"]),
    }
    out.update(_common(row, versioned=False))
    return out


def audit_sample(row):
    out = {
        "institution_id": row["institution_id"],
        "sample_index": row["sample_index"],
        "method": row["method"],
        "period_start": iso(row["period_start"]),
        "period_end": iso(row["period_end"]),
        "fields_reviewed_per_record": row["fields_reviewed_per_record"],
        "population_size": row["population_size"],
        "sample_size": row["sample_size"],
        "selected_application_ids": list(row["selected_application_ids"]),
        "defect_count": row["defect_count"],
        "records_with_defect_count": row["records_with_defect_count"],
        "defect_rate_basis": row["defect_rate_basis"],
        "defect_rate_pct": row["defect_rate_pct"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out


def audit_finding(row):
    out = {
        "audit_sample_id": row["audit_sample_id"],
        "application_id": row["application_id"],
        "field_name": row["field_name"],
        "recorded_value": row["recorded_value"],
        "source_document_value": row["source_document_value"],
        "is_defect": row["is_defect"],
        "severity": row["severity"],
        "remediation_start": iso(row["remediation_start"]),
        "remediation_end": iso(row["remediation_end"]),
        "resolution": row["resolution"],
    }
    out.update(_common(row))
    return out


def fair_lending_analysis(row):
    out = {
        "institution_id": row["institution_id"],
        "analysis_index": row["analysis_index"],
        "basis": row["basis"],
        "control_group_code": row["control_group_code"],
        "protected_group_code": row["protected_group_code"],
        "period_start": iso(row["period_start"]),
        "period_end": iso(row["period_end"]),
        "control_total": row["control_total"],
        "control_denied": row["control_denied"],
        "protected_total": row["protected_total"],
        "protected_denied": row["protected_denied"],
        "control_denial_rate_pct": row["control_denial_rate_pct"],
        "protected_denial_rate_pct": row["protected_denial_rate_pct"],
        "disparity_index": row["disparity_index"],
        "significance_flag": row["significance_flag"],
        "status": row["status"],
    }
    out.update(_common(row))
    return out
