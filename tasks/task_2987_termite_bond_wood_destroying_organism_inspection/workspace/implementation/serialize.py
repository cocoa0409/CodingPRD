"""Response projections, one per entity (PRD 1.1 field tables, PRD 2.4)."""

from envelope import fmt_date, fmt_instant


def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_instant(row["created_at"]),
        "updated_at": fmt_instant(row["updated_at"]),
        "version": row["version"],
    }


def _immutable(row):
    return {"id": row["id"], "created_at": fmt_instant(row["created_at"])}


def property_out(row):
    out = _common(row)
    out.update({
        "address_line1": row["address_line1"],
        "state_code": row["state_code"],
        "construction_type": row["construction_type"],
        "square_footage": row["square_footage"],
        "linear_footage": row["linear_footage"],
        "crawl_clearance_inches": row["crawl_clearance_inches"],
        "year_built": row["year_built"],
        "has_attached_structures": row["has_attached_structures"],
        "total_conducive_condition_count": row["total_conducive_condition_count"],
        "waived_conducive_condition_count": row["waived_conducive_condition_count"],
        "open_conducive_condition_count": row["open_conducive_condition_count"],
        "active_infestation_on_record": row["active_infestation_on_record"],
    })
    return out


def inspector_out(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "license_number": row["license_number"],
        "license_state": row["license_state"],
        "license_categories": list(row["license_categories"]),
        "license_expires_on": fmt_date(row["license_expires_on"]),
        "fumigation_endorsement": row["fumigation_endorsement"],
        "ce_credits": row["ce_credits"],
        "status": row["status"],
    })
    return out


def inspection_out(row):
    out = _common(row)
    out.update({
        "property_id": row["property_id"],
        "inspector_id": row["inspector_id"],
        "supersedes_inspection_id": row["supersedes_inspection_id"],
        "purpose": row["purpose"],
        "status": row["status"],
        "scheduled_start_at": fmt_instant(row["scheduled_start_at"]),
        "scheduled_end_at": fmt_instant(row["scheduled_end_at"]),
        "closing_date": fmt_date(row["closing_date"]),
        "sequence_no": row["sequence_no"],
        "graph_completed_at": fmt_instant(row["graph_completed_at"]),
        "no_findings_attested": row["no_findings_attested"],
        "findings_count": row["findings_count"],
        "conducive_condition_count": row["conducive_condition_count"],
        "active_infestation_found": row["active_infestation_found"],
        "damage_estimate_total_usd": row["damage_estimate_total_usd"],
    })
    return out


def finding_out(row):
    out = _immutable(row)
    out.update({
        "inspection_id": row["inspection_id"],
        "finding_type": row["finding_type"],
        "organism": row["organism"],
        "grid_ref": row["grid_ref"],
        "severity": row["severity"],
        "conducive_code": row["conducive_code"],
        "damage_estimate_usd": row["damage_estimate_usd"],
        "pre_existing": row["pre_existing"],
    })
    return out


def plan_out(row):
    out = _common(row)
    out.update({
        "property_id": row["property_id"],
        "inspection_id": row["inspection_id"],
        "applicator_id": row["applicator_id"],
        "method": row["method"],
        "chemical_product_code": row["chemical_product_code"],
        "fumigation_permit_number": row["fumigation_permit_number"],
        "fumigation_start_at": fmt_instant(row["fumigation_start_at"]),
        "fumigation_reentry_at": fmt_instant(row["fumigation_reentry_at"]),
        "status": row["status"],
        "target_gallons": row["target_gallons"],
        "target_station_count": row["target_station_count"],
        "quoted_price_usd": row["quoted_price_usd"],
        "gallons_applied_total": row["gallons_applied_total"],
        "escalated_station_count": row["escalated_station_count"],
        "retreat_required": row["retreat_required"],
        "completed_at": fmt_instant(row["completed_at"]),
    })
    return out


def record_out(row):
    out = _immutable(row)
    out.update({
        "treatment_plan_id": row["treatment_plan_id"],
        "applicator_license_number": row["applicator_license_number"],
        "applicator_license_state": row["applicator_license_state"],
        "state_code": row["state_code"],
        "product_epa_number": row["product_epa_number"],
        "gallons_applied": row["gallons_applied"],
        "concentration_pct": row["concentration_pct"],
        "applied_at": fmt_instant(row["applied_at"]),
        "retention_until": fmt_date(row["retention_until"]),
    })
    return out


def bond_out(row):
    out = _common(row)
    out.update({
        "property_id": row["property_id"],
        "treatment_plan_id": row["treatment_plan_id"],
        "coverage_tier": row["coverage_tier"],
        "conducive_waiver_codes": list(row["conducive_waiver_codes"]),
        "issued_by_user_id": row["issued_by_user_id"],
        "status": row["status"],
        "issued_on": fmt_date(row["issued_on"]),
        "current_term_start": fmt_date(row["current_term_start"]),
        "current_term_end": fmt_date(row["current_term_end"]),
        "renewal_window_opens_on": fmt_date(row["renewal_window_opens_on"]),
        "term_index": row["term_index"],
        "lapse_date": fmt_date(row["lapse_date"]),
        "reinstatement_count": row["reinstatement_count"],
        "base_premium_usd": row["base_premium_usd"],
        "repair_liability_cap_usd": row["repair_liability_cap_usd"],
        "annual_premium_usd": row["annual_premium_usd"],
        "claims_paid_to_date_usd": row["claims_paid_to_date_usd"],
        "reserved_claim_amount_usd": row["reserved_claim_amount_usd"],
        "remaining_repair_cap_usd": row["remaining_repair_cap_usd"],
        "retreat_credit_count": row["retreat_credit_count"],
        "retreat_required": row["retreat_required"],
        "coverage_watch": row["coverage_watch"],
    })
    return out


def renewal_out(row):
    out = _common(row)
    out.update({
        "bond_id": row["bond_id"],
        "inspection_id": row["inspection_id"],
        "term_index": row["term_index"],
        "status": row["status"],
        "due_on": fmt_date(row["due_on"]),
        "base_renewal_fee_usd": row["base_renewal_fee_usd"],
        "inspection_fee_usd": row["inspection_fee_usd"],
        "conducive_surcharge_usd": row["conducive_surcharge_usd"],
        "late_fee_usd": row["late_fee_usd"],
        "invoice_total_usd": row["invoice_total_usd"],
        "paid_at": fmt_instant(row["paid_at"]),
        "amount_paid_usd": row["amount_paid_usd"],
    })
    return out


def report_out(row):
    out = _common(row)
    out.update({
        "inspection_id": row["inspection_id"],
        "state_code": row["state_code"],
        "form_code": row["form_code"],
        "status": row["status"],
        "requested_at": fmt_instant(row["requested_at"]),
        "due_at": fmt_instant(row["due_at"]),
        "issued_at": fmt_instant(row["issued_at"]),
        "turnaround_hours": row["turnaround_hours"],
        "sla_breached": row["sla_breached"],
        "amendment_count": row["amendment_count"],
        "closing_date": fmt_date(row["closing_date"]),
        "amendment_reason_code": row["amendment_reason_code"],
    })
    return out


def station_out(row):
    out = _common(row)
    out.update({
        "treatment_plan_id": row["treatment_plan_id"],
        "station_index": row["station_index"],
        "grid_ref": row["grid_ref"],
        "status": row["status"],
        "consecutive_activity_count": row["consecutive_activity_count"],
        "last_serviced_at": fmt_instant(row["last_serviced_at"]),
        "next_due_at": fmt_instant(row["next_due_at"]),
        "service_count": row["service_count"],
        "matrix_replacement_count": row["matrix_replacement_count"],
    })
    return out


def service_out(row):
    out = _immutable(row)
    out.update({
        "bait_station_id": row["bait_station_id"],
        "serviced_by_license_number": row["serviced_by_license_number"],
        "serviced_at": fmt_instant(row["serviced_at"]),
        "activity_level": row["activity_level"],
        "matrix_replaced": row["matrix_replaced"],
        "days_since_last_service": row["days_since_last_service"],
        "interval_compliance": row["interval_compliance"],
    })
    return out


def claim_out(row):
    out = _common(row)
    out.update({
        "bond_id": row["bond_id"],
        "verifying_inspection_id": row["verifying_inspection_id"],
        "claim_type": row["claim_type"],
        "claimed_damage_usd": row["claimed_damage_usd"],
        "reported_at": fmt_instant(row["reported_at"]),
        "status": row["status"],
        "exclusion_basis": row["exclusion_basis"],
        "excluded_pre_existing_usd": row["excluded_pre_existing_usd"],
        "eligible_damage_usd": row["eligible_damage_usd"],
        "deductible_usd": row["deductible_usd"],
        "projected_payout_usd": row["projected_payout_usd"],
        "approved_payout_usd": row["approved_payout_usd"],
        "denial_reason_code": row["denial_reason_code"],
        "adjudicated_by_user_id": row["adjudicated_by_user_id"],
    })
    return out
