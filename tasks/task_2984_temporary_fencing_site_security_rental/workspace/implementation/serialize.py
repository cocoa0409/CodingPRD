"""Resource representations. Field names come straight from SCAFFOLD 1.1."""

from validation import iso_ms


def _house(row, out):
    out["id"] = row["id"]
    out["created_at"] = iso_ms(row["created_at"])
    out["updated_at"] = iso_ms(row["updated_at"])
    out["version"] = row["version"]
    return out


def municipality_out(row, committed_closure_linear_feet):
    out = {
        "name": row["name"],
        "jurisdiction_code": row["jurisdiction_code"],
        "permit_lead_time_days": row["permit_lead_time_days"],
        "max_concurrent_closure_linear_feet": row["max_concurrent_closure_linear_feet"],
        "permit_review_rounds_allowed": row["permit_review_rounds_allowed"],
        "rental_tax_rate_bp": row["rental_tax_rate_bp"],
        "allows_solid_wind_screen": row["allows_solid_wind_screen"],
        "committed_closure_linear_feet": committed_closure_linear_feet,
    }
    return _house(row, out)


def account_out(row):
    out = {
        "legal_name": row["legal_name"],
        "billing_email": row["billing_email"],
        "credit_limit_cents": row["credit_limit_cents"],
        "open_balance_cents": row["open_balance_cents"],
        "lifetime_credited_cents": row["lifetime_credited_cents"],
        "credit_hold_flag": row["credit_hold_flag"],
    }
    return _house(row, out)


def jobsite_out(row):
    out = {
        "customer_account_id": row["customer_account_id"],
        "municipality_id": row["municipality_id"],
        "site_label": row["site_label"],
        "address_line": row["address_line"],
        "site_condition": row["site_condition"],
        "phase_count": row["phase_count"],
        "requires_sidewalk_closure": row["requires_sidewalk_closure"],
    }
    return _house(row, out)


def product_out(row):
    out = {
        "code": row["code"],
        "category": row["category"],
        "description": row["description"],
        "panel_length_ft": row["panel_length_ft"],
        "unit_monthly_rate_cents": row["unit_monthly_rate_cents"],
        "replacement_cost_cents_per_unit": row["replacement_cost_cents_per_unit"],
        "fleet_age_months": row["fleet_age_months"],
        "wind_load_rating_mph": row["wind_load_rating_mph"],
        "owned_count": row["owned_count"],
        "available_count": row["available_count"],
        "reserved_count": row["reserved_count"],
        "deployed_count": row["deployed_count"],
        "damaged_count": row["damaged_count"],
        "lost_count": row["lost_count"],
    }
    return _house(row, out)


def crew_out(row):
    out = {
        "crew_code": row["crew_code"],
        "depot_code": row["depot_code"],
        "daily_capacity_hours": row["daily_capacity_hours"],
        "certified_for_solid_screen": row["certified_for_solid_screen"],
    }
    return _house(row, out)


def quote_out(row):
    out = {
        "jobsite_id": row["jobsite_id"],
        "contract_type": row["contract_type"],
        "linear_feet": row["linear_feet"],
        "panel_product_code": row["panel_product_code"],
        "wind_screen": row["wind_screen"],
        "term_months": row["term_months"],
        "addon_lines": [dict(line) for line in row["addon_lines"]],
        "accepted_by_name": row["accepted_by_name"],
        "status": row["status"],
        "panel_unit_count": row["panel_unit_count"],
        "tier_rate_cents_per_ft": row["tier_rate_cents_per_ft"],
        "monthly_recurring_cents": row["monthly_recurring_cents"],
        "install_labor_cents": row["install_labor_cents"],
        "permit_handling_fee_cents": row["permit_handling_fee_cents"],
        "one_time_cents": row["one_time_cents"],
        "priced_lines": [dict(line) for line in row["priced_lines"]],
        "issued_at_utc": iso_ms(row["issued_at_utc"]),
        "valid_through_utc": iso_ms(row["valid_through_utc"]),
    }
    return _house(row, out)


def permit_out(row):
    out = {
        "jobsite_id": row["jobsite_id"],
        "closure_linear_feet": row["closure_linear_feet"],
        "closure_start_utc": iso_ms(row["closure_start_utc"]),
        "closure_end_utc": iso_ms(row["closure_end_utc"]),
        "sidewalk_closure_type": row["sidewalk_closure_type"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "submitted_at_utc": iso_ms(row["submitted_at_utc"]),
        "decided_at_utc": iso_ms(row["decided_at_utc"]),
        "reviewer_note": row["reviewer_note"],
        "required_change_summary": row["required_change_summary"],
    }
    return _house(row, out)


def contract_out(row):
    out = {
        "quote_id": row["quote_id"],
        "customer_account_id": row["customer_account_id"],
        "jobsite_id": row["jobsite_id"],
        "pinned_quote_version": row["pinned_quote_version"],
        "contract_type": row["contract_type"],
        "monthly_recurring_cents": row["monthly_recurring_cents"],
        "install_labor_cents": row["install_labor_cents"],
        "one_time_cents": row["one_time_cents"],
        "ordered_linear_feet": row["ordered_linear_feet"],
        "deployed_linear_feet": row["deployed_linear_feet"],
        "fleet_commitments": [dict(entry) for entry in row["fleet_commitments"]],
        "addons_deployed": row["addons_deployed"],
        "lifecycle_status": row["lifecycle_status"],
        "billing_status": row["billing_status"],
        "billing_anchor_utc": iso_ms(row["billing_anchor_utc"]),
        "billed_through_utc": iso_ms(row["billed_through_utc"]),
        "cancellation_fee_cents": row["cancellation_fee_cents"],
        "current_phase": row["current_phase"],
        "terms_acknowledged_by": row["terms_acknowledged_by"],
    }
    return _house(row, out)


def work_order_out(row):
    hours = row["estimated_labor_hours"]
    out = {
        "contract_id": row["contract_id"],
        "crew_id": row["crew_id"],
        "predecessor_work_order_id": row["predecessor_work_order_id"],
        "predecessor_relation": row["predecessor_relation"],
        "work_order_type": row["work_order_type"],
        "ordered_linear_feet": row["ordered_linear_feet"],
        "phase_from": row["phase_from"],
        "phase_to": row["phase_to"],
        "scheduled_start_utc": iso_ms(row["scheduled_start_utc"]),
        "estimated_labor_hours": None if hours is None else float(hours),
        "scheduled_end_utc": iso_ms(row["scheduled_end_utc"]),
        "status": row["status"],
        "completed_linear_feet": row["completed_linear_feet"],
        "reserved_unit_counts": [dict(entry) for entry in row["reserved_unit_counts"]],
        "completed_by_user_id": row["completed_by_user_id"],
        "abort_reason_code": row["abort_reason_code"],
        "cancel_reason_code": row["cancel_reason_code"],
    }
    return _house(row, out)


def invoice_out(row):
    out = {
        "contract_id": row["contract_id"],
        "invoice_kind": row["invoice_kind"],
        "period_start_utc": iso_ms(row["period_start_utc"]),
        "period_end_utc": iso_ms(row["period_end_utc"]),
        "billable_days": row["billable_days"],
        "lines": [dict(line) for line in row["lines"]],
        "subtotal_cents": row["subtotal_cents"],
        "tax_cents": row["tax_cents"],
        "late_fee_cents": row["late_fee_cents"],
        "total_cents": row["total_cents"],
        "amount_paid_cents": row["amount_paid_cents"],
        "status": row["status"],
        "issued_at_utc": iso_ms(row["issued_at_utc"]),
        "due_at_utc": iso_ms(row["due_at_utc"]),
        "issued_by_user_id": row["issued_by_user_id"],
        "void_reason_code": row["void_reason_code"],
    }
    return _house(row, out)


def reconciliation_out(row):
    out = {
        "contract_id": row["contract_id"],
        "work_order_id": row["work_order_id"],
        "deployed_snapshot": [dict(entry) for entry in row["deployed_snapshot"]],
        "unit_returns": [dict(entry) for entry in row["unit_returns"]],
        "theft_police_report_number": row["theft_police_report_number"],
        "assessment_variant": row["assessment_variant"],
        "loss_charge_cents": row["loss_charge_cents"],
        "damage_charge_cents": row["damage_charge_cents"],
        "status": row["status"],
        "finalized_by_user_id": row["finalized_by_user_id"],
        "auditor_note": row["auditor_note"],
    }
    return _house(row, out)
