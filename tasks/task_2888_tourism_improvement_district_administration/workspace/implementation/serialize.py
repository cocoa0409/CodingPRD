"""Entity serializers.  Field names follow SCAFFOLD.yaml / PRD section 3 exactly."""
import store


def _dt(rec, field):
    """Echo a caller-supplied instant verbatim; render system stamps canonically."""
    raw = rec.get("_raw", {}).get(field)
    if raw is not None:
        return raw
    return store.iso3(rec.get(field))


def _common(rec, out):
    out["created_at"] = store.iso3(rec["created_at"])
    out["updated_at"] = store.iso3(rec["updated_at"])
    out["version"] = rec["version"]
    return out


def district(rec):
    return _common(rec, {
        "id": rec["id"],
        "name": rec["name"],
        "assessment_method": rec["assessment_method"],
        "included_zones": list(rec["included_zones"]),
        "status": rec["status"],
        "formation_threshold_pct": store.ratio_out(rec["formation_threshold_pct"]),
        "renewal_threshold_pct": store.ratio_out(rec["renewal_threshold_pct"]),
        "renewal_headcount_threshold_pct": store.ratio_out(rec["renewal_headcount_threshold_pct"]),
        "term_years": rec["term_years"],
        "formed_on": _dt(rec, "formed_on"),
        "expiration_date": _dt(rec, "expiration_date"),
        "current_fiscal_year": rec["current_fiscal_year"],
        "transparency_standing": rec["transparency_standing"],
        "dmo_name": rec["dmo_name"],
        "dmo_agreement_status": rec["dmo_agreement_status"],
        "dmo_contract_cents": rec["dmo_contract_cents"],
        "public_lodging_tax_offset_cents": rec["public_lodging_tax_offset_cents"],
        "lodging_tax_match_pool_cents": rec["lodging_tax_match_pool_cents"],
        "lodging_tax_match_committed_cents": rec["lodging_tax_match_committed_cents"],
        "collected_to_date_cents": rec["collected_to_date_cents"],
        "delinquent_charges_cents": rec["delinquent_charges_cents"],
        "assessable_basis_cents": rec["assessable_basis_cents"],
        "assessable_business_count": rec["assessable_business_count"],
    })


def business(rec):
    return _common(rec, {
        "id": rec["id"],
        "district_id": rec["district_id"],
        "legal_name": rec["legal_name"],
        "boundary_zone": rec["boundary_zone"],
        "classification": rec["classification"],
        "room_count": rec["room_count"],
        "prior_year_gross_room_revenue_cents": rec["prior_year_gross_room_revenue_cents"],
        "exempt_status": rec["exempt_status"],
        "status": rec["status"],
        "remittance_frequency": rec["remittance_frequency"],
        "delinquency_strike_count": rec["delinquency_strike_count"],
        "compliance_standing": rec["compliance_standing"],
        "operator_contact_email": rec["operator_contact_email"],
    })


def drive(rec):
    return _common(rec, {
        "id": rec["id"],
        "district_id": rec["district_id"],
        "drive_type": rec["drive_type"],
        "status": rec["status"],
        "opened_on": _dt(rec, "opened_on"),
        "closes_at": _dt(rec, "closes_at"),
        "required_weighted_pct": store.ratio_out(rec["required_weighted_pct"]),
        "required_headcount_pct": store.ratio_out(rec["required_headcount_pct"]),
        "signed_basis_cents": rec["signed_basis_cents"],
        "valid_signature_count": rec["valid_signature_count"],
        "assessable_basis_snapshot_cents": rec["assessable_basis_snapshot_cents"],
        "assessable_count_snapshot": rec["assessable_count_snapshot"],
        "weighted_support_pct": store.ratio_out(rec["weighted_support_pct"]),
        "headcount_support_pct": store.ratio_out(rec["headcount_support_pct"]),
        "short_reason": rec["short_reason"],
        "tallied_at": _dt(rec, "tallied_at"),
    })


def signature(rec):
    return _common(rec, {
        "id": rec["id"],
        "petition_drive_id": rec["petition_drive_id"],
        "lodging_business_id": rec["lodging_business_id"],
        "signed_at": _dt(rec, "signed_at"),
        "weight_basis_revenue_cents": rec["weight_basis_revenue_cents"],
        "status": rec["status"],
        "disqualification_reason": rec["disqualification_reason"],
    })


def period(rec):
    return _common(rec, {
        "id": rec["id"],
        "district_id": rec["district_id"],
        "period_label": rec["period_label"],
        "period_start": _dt(rec, "period_start"),
        "period_end": _dt(rec, "period_end"),
        "due_date": _dt(rec, "due_date"),
        "grace_days": rec["grace_days"],
        "status": rec["status"],
        "statement_count": rec["statement_count"],
        "billed_total_cents": rec["billed_total_cents"],
        "collected_total_cents": rec["collected_total_cents"],
    })


def statement(rec):
    return _common(rec, {
        "id": rec["id"],
        "assessment_period_id": rec["assessment_period_id"],
        "lodging_business_id": rec["lodging_business_id"],
        "zone_at_period_start": rec["zone_at_period_start"],
        "classification_at_period_start": rec["classification_at_period_start"],
        "assessment_method_at_period_start": rec["assessment_method_at_period_start"],
        "reported_room_nights": rec["reported_room_nights"],
        "reported_gross_room_revenue_cents": rec["reported_gross_room_revenue_cents"],
        "audited_room_nights": rec["audited_room_nights"],
        "audited_gross_room_revenue_cents": rec["audited_gross_room_revenue_cents"],
        "provisional_assessment_cents": rec["provisional_assessment_cents"],
        "final_assessment_cents": rec["final_assessment_cents"],
        "effective_assessment_cents": rec["effective_assessment_cents"],
        "granted_adjustment_cents": rec["granted_adjustment_cents"],
        "filing_status": rec["filing_status"],
        "payment_status": rec["payment_status"],
        "delinquency_stage": rec["delinquency_stage"],
        "penalty_cents": rec["penalty_cents"],
        "interest_cents": rec["interest_cents"],
        "principal_paid_cents": rec["principal_paid_cents"],
        "penalty_paid_cents": rec["penalty_paid_cents"],
        "interest_paid_cents": rec["interest_paid_cents"],
        "credit_balance_cents": rec["credit_balance_cents"],
        "total_due_cents": rec["total_due_cents"],
        "amendment_count": rec["amendment_count"],
        "filed_at": _dt(rec, "filed_at"),
        "audited_by_user_id": rec["audited_by_user_id"],
    })


def remittance(rec):
    return _common(rec, {
        "id": rec["id"],
        "assessment_statement_id": rec["assessment_statement_id"],
        "amount_cents": rec["amount_cents"],
        "received_on": _dt(rec, "received_on"),
        "method": rec["method"],
        "applied_to_interest_cents": rec["applied_to_interest_cents"],
        "applied_to_penalty_cents": rec["applied_to_penalty_cents"],
        "applied_to_principal_cents": rec["applied_to_principal_cents"],
        "applied_to_credit_cents": rec["applied_to_credit_cents"],
        "status": rec["status"],
        "reversed_on": _dt(rec, "reversed_on"),
        "reversal_reason": rec["reversal_reason"],
    })


def plan(rec):
    return _common(rec, {
        "id": rec["id"],
        "district_id": rec["district_id"],
        "fiscal_year": rec["fiscal_year"],
        "status": rec["status"],
        "expenditure_lines": [dict(line) for line in rec["expenditure_lines"]],
        "total_budget_cents": rec["total_budget_cents"],
        "administration_cents": rec["administration_cents"],
        "contingency_reserve_cents": rec["contingency_reserve_cents"],
        "sales_and_marketing_cents": rec["sales_and_marketing_cents"],
        "destination_events_cents": rec["destination_events_cents"],
        "capital_improvement_cents": rec["capital_improvement_cents"],
        "assessment_revenue_forecast_cents": rec["assessment_revenue_forecast_cents"],
        "funding_ratio": store.ratio_out(rec["funding_ratio"]),
        "sponsor_user_id": rec["sponsor_user_id"],
        "approver_user_id": rec["approver_user_id"],
        "approved_at": _dt(rec, "approved_at"),
        "revision_count": rec["revision_count"],
        "committed_program_cents": rec["committed_program_cents"],
    })


def program(rec):
    return _common(rec, {
        "id": rec["id"],
        "annual_work_plan_id": rec["annual_work_plan_id"],
        "name": rec["name"],
        "channel": rec["channel"],
        "committed_cents": rec["committed_cents"],
        "lodging_tax_matched_cents": rec["lodging_tax_matched_cents"],
        "booking_window_start": _dt(rec, "booking_window_start"),
        "booking_window_end": _dt(rec, "booking_window_end"),
        "status": rec["status"],
        "spend_frozen": rec["spend_frozen"],
        "verified_room_nights": rec["verified_room_nights"],
        "gross_cost_per_room_night_cents": rec["gross_cost_per_room_night_cents"],
        "efficiency_tier": rec["efficiency_tier"],
        "dmo_cost_share_cents": rec["dmo_cost_share_cents"],
        "net_district_cost_cents": rec["net_district_cost_cents"],
        "net_cost_per_room_night_cents": rec["net_cost_per_room_night_cents"],
        "performance_index": store.ratio_out(rec["performance_index"]),
        "performance_flag": rec["performance_flag"],
        "launched_at": _dt(rec, "launched_at"),
        "closed_at": _dt(rec, "closed_at"),
    })


def claim(rec):
    return _common(rec, {
        "id": rec["id"],
        "marketing_program_id": rec["marketing_program_id"],
        "lodging_business_id": rec["lodging_business_id"],
        "stay_start": _dt(rec, "stay_start"),
        "stay_end": _dt(rec, "stay_end"),
        "room_nights": rec["room_nights"],
        "attribution_method": rec["attribution_method"],
        "status": rec["status"],
        "verified_room_nights": rec["verified_room_nights"],
        "rejection_reason": rec["rejection_reason"],
        "verified_by_user_id": rec["verified_by_user_id"],
    })


def record(rec):
    return _common(rec, {
        "id": rec["id"],
        "district_id": rec["district_id"],
        "record_type": rec["record_type"],
        "fiscal_year": rec["fiscal_year"],
        "scheduled_for": _dt(rec, "scheduled_for"),
        "required_by": _dt(rec, "required_by"),
        "status": rec["status"],
        "noticed_on": _dt(rec, "noticed_on"),
        "completed_on": _dt(rec, "completed_on"),
        "published_on": _dt(rec, "published_on"),
        "document_reference": rec["document_reference"],
        "engaged_by_user_id": rec["engaged_by_user_id"],
    })


def dispute(rec):
    return _common(rec, {
        "id": rec["id"],
        "assessment_statement_id": rec["assessment_statement_id"],
        "lodging_business_id": rec["lodging_business_id"],
        "dispute_note": rec["dispute_note"],
        "dispute_type": rec["dispute_type"],
        "claimed_adjustment_cents": rec["claimed_adjustment_cents"],
        "granted_adjustment_cents": rec["granted_adjustment_cents"],
        "status": rec["status"],
        "appeal_count": rec["appeal_count"],
        "resolved_by_user_id": rec["resolved_by_user_id"],
        "resolution_note": rec["resolution_note"],
        "filed_on": _dt(rec, "filed_on"),
    })
