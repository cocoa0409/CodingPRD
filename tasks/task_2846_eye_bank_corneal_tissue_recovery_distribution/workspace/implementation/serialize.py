"""Entity representations. Field lists follow SCAFFOLD entities exactly."""

from decimal import Decimal

import store


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, out, versioned=True):
    out["id"] = row["id"]
    out["created_at"] = store.iso(row["created_at"])
    if versioned:
        out["updated_at"] = store.iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def donor(row):
    out = {
        "donor_code": row["donor_code"],
        "referral_source": row["referral_source"],
        "death_at": store.iso(row["death_at"]),
        "death_time_basis": row["death_time_basis"],
        "body_cooled_at": store.iso(row["body_cooled_at"]),
        "age_years": row["age_years"],
        "cause_of_death_category": row["cause_of_death_category"],
        "status": row["status"],
        "consent_type": row["consent_type"],
        "consent_scope": row["consent_scope"],
        "authorizing_party_name": row["authorizing_party_name"],
        "consent_obtained_at": store.iso(row["consent_obtained_at"]),
        "recovery_window_minutes": row["recovery_window_minutes"],
        "recovery_deadline_at": store.iso(row["recovery_deadline_at"]),
        "screening_risk_score": row["screening_risk_score"],
        "screening_risk_variant": row["screening_risk_variant"],
        "serology_status": row["serology_status"],
        "deferral_reason": row["deferral_reason"],
        "lookback_flag": row["lookback_flag"],
        "tissues_recovered_count": row["tissues_recovered_count"],
    }
    return _common(row, out)


def screening_record(row):
    out = {
        "donor_id": row["donor_id"],
        "question_code": row["question_code"],
        "response": row["response"],
        "historian_relationship": row["historian_relationship"],
        "recorded_by_user_id": row["recorded_by_user_id"],
        "weight_applied": row["weight_applied"],
    }
    return _common(row, out, versioned=False)


def serology_panel(row):
    out = {
        "donor_id": row["donor_id"],
        "specimen_type": row["specimen_type"],
        "drawn_at": store.iso(row["drawn_at"]),
        "hemodilution_pct": _num(row["hemodilution_pct"]),
        "status": row["status"],
        "hiv_result": row["hiv_result"],
        "hbv_result": row["hbv_result"],
        "hcv_result": row["hcv_result"],
        "syphilis_result": row["syphilis_result"],
        "overall_result": row["overall_result"],
        "resulted_at": store.iso(row["resulted_at"]),
        "donor_version_after": row["donor_version_after"],
        "superseded_at": store.iso(row["superseded_at"]),
    }
    return _common(row, out)


def technician(row):
    out = {
        "full_name": row["full_name"],
        "certification_level": row["certification_level"],
        "certification_expires_at": store.iso(row["certification_expires_at"]),
        "status": row["status"],
        "open_dispatch_count": row["open_dispatch_count"],
    }
    return _common(row, out)


def recovery(row):
    out = {
        "donor_id": row["donor_id"],
        "technician_id": row["technician_id"],
        "dispatched_at": store.iso(row["dispatched_at"]),
        "planned_release_at": store.iso(row["planned_release_at"]),
        "arrival_at": store.iso(row["arrival_at"]),
        "preservation_at": store.iso(row["preservation_at"]),
        "preservation_medium": row["preservation_medium"],
        "status": row["status"],
        "abort_reason": row["abort_reason"],
        "occupation_end_at": store.iso(row["occupation_end_at"]),
        "death_to_preservation_minutes": row["death_to_preservation_minutes"],
        "time_limit_band": row["time_limit_band"],
        "recovered_lateralities": list(row["recovered_lateralities"]),
    }
    return _common(row, out)


def tissue(row):
    out = {
        "recovery_id": row["recovery_id"],
        "donor_id": row["donor_id"],
        "laterality": row["laterality"],
        "preservation_medium": row["preservation_medium"],
        "preserved_at": store.iso(row["preserved_at"]),
        "shelf_life_hours": row["shelf_life_hours"],
        "shelf_life_variant": row["shelf_life_variant"],
        "expires_at": store.iso(row["expires_at"]),
        "tissue_quality_score": row["tissue_quality_score"],
        "classification": row["classification"],
        "disposition_status": row["disposition_status"],
        "custody_status": row["custody_status"],
        "issue_count": row["issue_count"],
        "reissue_generation": row["reissue_generation"],
        "quarantine_reason": row["quarantine_reason"],
        "disposal_method": row["disposal_method"],
    }
    return _common(row, out)


def evaluation(row):
    out = {
        "tissue_id": row["tissue_id"],
        "evaluator_technician_id": row["evaluator_technician_id"],
        "method": row["method"],
        "performed_at": store.iso(row["performed_at"]),
        "epithelium_defect_grade": row["epithelium_defect_grade"],
        "stromal_clarity_grade": row["stromal_clarity_grade"],
        "dm_folds_grade": row["dm_folds_grade"],
        "guttata_grade": row["guttata_grade"],
        "endothelial_cell_count": row["endothelial_cell_count"],
        "status": row["status"],
        "tissue_version_after": row["tissue_version_after"],
    }
    return _common(row, out)


def surgeon(row):
    out = {
        "full_name": row["full_name"],
        "center_code": row["center_code"],
        "specialty": row["specialty"],
        "credential_status": row["credential_status"],
        "gross_billed_cents": row["gross_billed_cents"],
        "credited_fee_cents": row["credited_fee_cents"],
        "outstanding_fee_cents": row["outstanding_fee_cents"],
        "substantiated_reaction_count": row["substantiated_reaction_count"],
    }
    return _common(row, out)


def surgeon_request(row):
    out = {
        "surgeon_id": row["surgeon_id"],
        "procedure_type": row["procedure_type"],
        "surgery_date": store.iso(row["surgery_date"]),
        "min_ecd": row["min_ecd"],
        "max_donor_age_years": row["max_donor_age_years"],
        "laterality_preference": row["laterality_preference"],
        "urgency": row["urgency"],
        "status": row["status"],
        "base_score": row["base_score"],
        "priority_tier": row["priority_tier"],
        "priority_score": row["priority_score"],
        "cancel_reason": row["cancel_reason"],
    }
    return _common(row, out)


def allocation(row):
    out = {
        "tissue_id": row["tissue_id"],
        "request_id": row["request_id"],
        "allocated_at": store.iso(row["allocated_at"]),
        "status": row["status"],
        "source": row["source"],
        "reserved_ecd_snapshot": row["reserved_ecd_snapshot"],
        "reserved_classification_snapshot": row["reserved_classification_snapshot"],
        "processing_fee_cents": row["processing_fee_cents"],
        "expiry_margin_hours": row["expiry_margin_hours"],
        "cancel_reason": row["cancel_reason"],
    }
    return _common(row, out)


def shipment(row):
    out = {
        "allocation_id": row["allocation_id"],
        "replaces_shipment_id": row["replaces_shipment_id"],
        "carrier": row["carrier"],
        "shipped_at": store.iso(row["shipped_at"]),
        "delivered_at": store.iso(row["delivered_at"]),
        "status": row["status"],
        "min_temp_c": _num(row["min_temp_c"]),
        "max_temp_c": _num(row["max_temp_c"]),
        "temp_excursion_minutes_over": row["temp_excursion_minutes_over"],
        "integrity_verdict": row["integrity_verdict"],
    }
    return _common(row, out)


def temperature_reading(row):
    out = {
        "shipment_id": row["shipment_id"],
        "recorded_at": store.iso(row["recorded_at"]),
        "temperature_c": _num(row["temperature_c"]),
    }
    return _common(row, out, versioned=False)


def report(row):
    out = {
        "tissue_id": row["tissue_id"],
        "surgeon_id": row["surgeon_id"],
        "reaction_type": row["reaction_type"],
        "severity": row["severity"],
        "narrative": row["narrative"],
        "reported_at": store.iso(row["reported_at"]),
        "status": row["status"],
        "adjudication_note": row["adjudication_note"],
    }
    return _common(row, out)


def investigation(row):
    out = {
        "donor_id": row["donor_id"],
        "source_report_id": row["source_report_id"],
        "trigger_reason": row["trigger_reason"],
        "status": row["status"],
        "opened_at": store.iso(row["opened_at"]),
        "notified_at": store.iso(row["notified_at"]),
        "closed_at": store.iso(row["closed_at"]),
        "impacted_tissue_count": row["impacted_tissue_count"],
        "quarantined_count": row["quarantined_count"],
        "notified_recipient_count": row["notified_recipient_count"],
        "closure_note": row["closure_note"],
    }
    return _common(row, out)
