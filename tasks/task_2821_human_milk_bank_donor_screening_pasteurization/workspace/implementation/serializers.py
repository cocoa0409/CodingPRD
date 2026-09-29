"""Row -> JSON representations.

The nine mutable entities expose id / created_at / updated_at / version; the six
immutable event records expose only id / created_at (PRD 2.4).  Decimal
quantities are emitted as JSON numbers, never strings (PRD 2.6).
"""

from util import num_out


def _audit(row, versioned=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def donor_out(row):
    out = {
        "id": row["id"],
        "donor_code": row["donor_code"],
        "full_name": row["full_name"],
        "email": row["email"],
        "zone_code": row["zone_code"],
        "status": row["status"],
        "screening_risk_score": row["screening_risk_score"],
        "surveillance_risk_score": row["surveillance_risk_score"],
        "qualified_at": row["qualified_at"],
        "qualified_by_user_id": row["qualified_by_user_id"],
        "reimbursement_balance_cents": row["reimbursement_balance_cents"],
        "lifetime_accepted_volume_ml": row["lifetime_accepted_volume_ml"],
        "temporary_deferral_count": row["temporary_deferral_count"],
        "active_deferral_until_date": row["active_deferral_until_date"],
    }
    out.update(_audit(row))
    return out


def questionnaire_out(row):
    out = {
        "id": row["id"],
        "donor_id": row["donor_id"],
        "medication_flag_count": row["medication_flag_count"],
        "travel_risk_flag": row["travel_risk_flag"],
        "tobacco_use": row["tobacco_use"],
        "alcohol_units_per_week": row["alcohol_units_per_week"],
        "months_postpartum": row["months_postpartum"],
        "base_risk_points": row["base_risk_points"],
        "screening_risk_score": row["screening_risk_score"],
        "status": row["status"],
        "submitted_at": row["submitted_at"],
    }
    out.update(_audit(row, False))
    return out


def serology_out(row):
    out = {
        "id": row["id"],
        "donor_id": row["donor_id"],
        "collected_on": row["collected_on"],
        "hiv_result": row["hiv_result"],
        "htlv_result": row["htlv_result"],
        "hbv_result": row["hbv_result"],
        "hcv_result": row["hcv_result"],
        "syphilis_result": row["syphilis_result"],
        "panel_status": row["panel_status"],
        "expires_on": row["expires_on"],
        "recorded_by_user_id": row["recorded_by_user_id"],
    }
    out.update(_audit(row, False))
    return out


def approval_out(row):
    out = {
        "id": row["id"],
        "donor_id": row["donor_id"],
        "physician_npi": row["physician_npi"],
        "approved_on": row["approved_on"],
        "valid_until": row["valid_until"],
        "status": row["status"],
        "recorded_by_user_id": row["recorded_by_user_id"],
    }
    out.update(_audit(row, False))
    return out


def deferral_out(row):
    out = {
        "id": row["id"],
        "donor_id": row["donor_id"],
        "reason_code": row["reason_code"],
        "deferral_type": row["deferral_type"],
        "effective_from": row["effective_from"],
        "deferral_days": row["deferral_days"],
        "lookback_days": row["lookback_days"],
        "recall_scope": row["recall_scope"],
        "status": row["status"],
        "recalled_donation_count": row["recalled_donation_count"],
        "quarantined_pool_count": row["quarantined_pool_count"],
        "recalled_lot_count": row["recalled_lot_count"],
        "recalled_dispense_count": row["recalled_dispense_count"],
        "reversed_subsidy_cents": row["reversed_subsidy_cents"],
        "recorded_by_user_id": row["recorded_by_user_id"],
    }
    out.update(_audit(row, False))
    return out


def shipment_out(row):
    out = {
        "id": row["id"],
        "donor_id": row["donor_id"],
        "tracking_code": row["tracking_code"],
        "zone_code": row["zone_code"],
        "container_count": row["container_count"],
        "uses_dry_ice": row["uses_dry_ice"],
        "declared_volume_ml": row["declared_volume_ml"],
        "shipped_on": row["shipped_on"],
        "estimated_reimbursement_cents": row["estimated_reimbursement_cents"],
        "final_reimbursement_cents": row["final_reimbursement_cents"],
        "credited_reimbursement_cents": row["credited_reimbursement_cents"],
        "excursion_minutes": row["excursion_minutes"],
        "arrival_max_temp_celsius": num_out(row["arrival_max_temp_celsius"]),
        "verified_volume_ml": row["verified_volume_ml"],
        "status": row["status"],
        "received_at": row["received_at"],
        "received_by_user_id": row["received_by_user_id"],
    }
    out.update(_audit(row))
    return out


def donation_out(row):
    out = {
        "id": row["id"],
        "shipment_id": row["shipment_id"],
        "donor_id": row["donor_id"],
        "container_label": row["container_label"],
        "expressed_on": row["expressed_on"],
        "volume_ml": row["volume_ml"],
        "kcal_per_oz": num_out(row["kcal_per_oz"]),
        "milk_class": row["milk_class"],
        "remaining_ml": row["remaining_ml"],
        "status": row["status"],
    }
    out.update(_audit(row))
    return out


def pool_out(row):
    out = {
        "id": row["id"],
        "pool_code": row["pool_code"],
        "pool_sequence": row["pool_sequence"],
        "target_milk_class": row["target_milk_class"],
        "distinct_donor_count": row["distinct_donor_count"],
        "total_volume_ml": row["total_volume_ml"],
        "projected_kcal_per_oz": num_out(row["projected_kcal_per_oz"]),
        "bottled_volume_ml": row["bottled_volume_ml"],
        "status": row["status"],
        "committed_at": row["committed_at"],
        "committed_by_user_id": row["committed_by_user_id"],
    }
    out.update(_audit(row))
    return out


def component_out(row):
    out = {
        "id": row["id"],
        "pool_id": row["pool_id"],
        "donation_id": row["donation_id"],
        "allocated_volume_ml": row["allocated_volume_ml"],
        "component_kcal_per_oz": num_out(row["component_kcal_per_oz"]),
        "component_donor_id": row["component_donor_id"],
        "status": row["status"],
    }
    out.update(_audit(row, False))
    return out


def run_out(row):
    out = {
        "id": row["id"],
        "pool_id": row["pool_id"],
        "pasteurizer_id": row["pasteurizer_id"],
        "scheduled_start_at": row["scheduled_start_at"],
        "cycle_minutes": row["cycle_minutes"],
        "run_status": row["run_status"],
        "thermal_status": row["thermal_status"],
        "culture_status": row["culture_status"],
        "release_eligibility": row["release_eligibility"],
        "reading_count": row["reading_count"],
        "longest_hold_seconds": row["longest_hold_seconds"],
        "peak_celsius": num_out(row["peak_celsius"]),
        "completed_at": row["completed_at"],
        "completed_by_user_id": row["completed_by_user_id"],
        "culture_cfu_per_ml": row["culture_cfu_per_ml"],
        "culture_organism": row["culture_organism"],
        "culture_recorded_by_user_id": row["culture_recorded_by_user_id"],
    }
    out.update(_audit(row))
    return out


def reading_out(row):
    out = {
        "id": row["id"],
        "run_id": row["run_id"],
        "offset_seconds": row["offset_seconds"],
        "celsius": num_out(row["celsius"]),
        "qualifies": row["qualifies"],
        "recorded_by_user_id": row["recorded_by_user_id"],
    }
    out.update(_audit(row, False))
    return out


def lot_out(row):
    out = {
        "id": row["id"],
        "run_id": row["run_id"],
        "lot_code": row["lot_code"],
        "lot_sequence": row["lot_sequence"],
        "milk_class": row["milk_class"],
        "bottle_count": row["bottle_count"],
        "bottle_volume_ml": row["bottle_volume_ml"],
        "total_volume_ml": row["total_volume_ml"],
        "dispensed_ml": row["dispensed_ml"],
        "available_ml": row["available_ml"],
        "kcal_per_oz": num_out(row["kcal_per_oz"]),
        "pasteurization_date": row["pasteurization_date"],
        "expiration_date": row["expiration_date"],
        "release_status": row["release_status"],
        "released_at": row["released_at"],
        "released_by_user_id": row["released_by_user_id"],
    }
    out.update(_audit(row))
    return out


def program_out(row):
    out = {
        "id": row["id"],
        "program_code": row["program_code"],
        "name": row["name"],
        "coverage_pct": num_out(row["coverage_pct"]),
        "annual_cap_cents": row["annual_cap_cents"],
        "consumed_cents": row["consumed_cents"],
        "status": row["status"],
    }
    out.update(_audit(row))
    return out


def prescription_out(row):
    out = {
        "id": row["id"],
        "prescription_code": row["prescription_code"],
        "subsidy_program_id": row["subsidy_program_id"],
        "patient_reference": row["patient_reference"],
        "patient_type": row["patient_type"],
        "clinical_acuity": row["clinical_acuity"],
        "priority_tier": row["priority_tier"],
        "requires_preterm_milk": row["requires_preterm_milk"],
        "subsidy_required": row["subsidy_required"],
        "prescribed_ml": row["prescribed_ml"],
        "cumulative_dispensed_ml": row["cumulative_dispensed_ml"],
        "remaining_ml": row["remaining_ml"],
        "needed_by_date": row["needed_by_date"],
        "waitlist_position": row["waitlist_position"],
        "status": row["status"],
        "prescriber_user_id": row["prescriber_user_id"],
    }
    out.update(_audit(row))
    return out


def dispense_out(row):
    out = {
        "id": row["id"],
        "prescription_id": row["prescription_id"],
        "lot_id": row["lot_id"],
        "volume_ml": row["volume_ml"],
        "tier_discount_pct": num_out(row["tier_discount_pct"]),
        "gross_fee_cents": row["gross_fee_cents"],
        "subsidy_cents": row["subsidy_cents"],
        "payer_due_cents": row["payer_due_cents"],
        "allocation_cycle_sequence": row["allocation_cycle_sequence"],
        "dispensed_by_user_id": row["dispensed_by_user_id"],
        "status": row["status"],
    }
    out.update(_audit(row))
    return out
