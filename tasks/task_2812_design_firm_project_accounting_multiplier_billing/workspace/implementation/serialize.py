"""Resource serialisers. Derived figures are recomputed here so that every read
returns a live figure (PRD 2.10)."""
import calc
from money import m, r


def _date(v):
    return v.isoformat() if v is not None else None


def _common(row, mutable=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if mutable:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def client_out(row):
    # PRD 2.4: a Client carries only id and created_at -- no updated_at, no version.
    out = _common(row, mutable=False)
    out.update({
        "name": row["name"],
        "is_public_agency": row["is_public_agency"],
        "retainage_pct": r(row["retainage_pct"]),
        "expense_markup_pct": r(row["expense_markup_pct"]),
        "disallowed_categories": list(row["disallowed_categories"]),
        "receipt_required_above": m(row["receipt_required_above"]),
        "review_cycle_days": row["review_cycle_days"],
    })
    return out


def labor_rate_out(row):
    # PRD 2.4: a LaborRate is append-only -- no updated_at, no version.
    out = _common(row, mutable=False)
    out.update({
        "role_code": row["role_code"],
        "raw_cost_rate": m(row["raw_cost_rate"]),
        "effective_from": _date(row["effective_from"]),
        "effective_to": _date(row["effective_to"]),
    })
    return out


def project_out(row):
    out = _common(row)
    out.update({
        "client_id": row["client_id"],
        "name": row["name"],
        "contract_type": row["contract_type"],
        "contract_amount": m(row["contract_amount"]),
        "project_manager_user_id": row["project_manager_user_id"],
        "percent_complete_method": row["percent_complete_method"],
        "target_multiplier": r(row["target_multiplier"]),
        "wip_alert_threshold": m(row["wip_alert_threshold"]),
        "status": row["status"],
        "locked_through_date": _date(row["locked_through_date"]),
        "overhead_adjustment_required": row["overhead_adjustment_required"],
        "billing_posture": calc.project_billing_posture(row),
        "certified_multiplier_ceiling": r(calc.project_certified_multiplier_ceiling(row)),
        "earned_revenue_to_date": m(calc.project_earned_revenue_to_date(row)),
        "unbilled_wip": m(calc.project_unbilled_wip(row)),
        "billed_open": m(calc.project_billed_open(row)),
        "paid_gross_to_date": m(calc.project_paid_gross_to_date(row)),
        "written_off_gross": m(calc.project_written_off_gross(row)),
        "raw_labor_cost_to_date": m(calc.project_raw_labor_cost_to_date(row)),
        "total_charge_value": m(calc.project_total_charge_value(row)),
        "net_multiplier_achieved": r(calc.project_net_multiplier_achieved(row)),
    })
    return out


def phase_out(row):
    project = calc.project_of_phase(row)
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "parent_phase_id": row["parent_phase_id"],
        "wbs_code": row["wbs_code"],
        "fee_basis": row["fee_basis"],
        "fee_percent": r(row["fee_percent"]),
        "lump_sum_fee": m(row["lump_sum_fee"]),
        "phase_fee": m(row["phase_fee"]),
        "budget_labor_cost": m(row["budget_labor_cost"]),
        "consultant_budget": m(row["consultant_budget"]),
        "status": row["status"],
        "assessed_percent_complete": r(row["assessed_percent_complete"]),
        "is_leaf": calc.phase_is_leaf(row),
        "depth": calc.phase_depth(row),
        "actual_labor_cost_to_date": m(calc.phase_actual_labor_cost(row)),
        "effort_based_percent_complete": r(calc.phase_effort_percent_complete(row)),
        "effort_based_earned_value": m(calc.phase_effort_earned_value(row)),
        "assessed_earned_value": m(calc.phase_assessed_earned_value(row)),
        "recognized_earned_value": m(calc.phase_recognized_earned_value(row, project)),
        "consultant_committed_open": m(calc.phase_consultant_committed_open(row)),
    })
    return out


def earned_value_report(row):
    project = calc.project_of_phase(row)
    return {
        "phase_id": row["id"],
        "phase_fee": m(row["phase_fee"]),
        "budget_labor_cost": m(row["budget_labor_cost"]),
        "actual_labor_cost_to_date": m(calc.phase_actual_labor_cost(row)),
        "effort_based_percent_complete": r(calc.phase_effort_percent_complete(row)),
        "effort_based_earned_value": m(calc.phase_effort_earned_value(row)),
        "assessed_percent_complete": r(row["assessed_percent_complete"]),
        "assessed_earned_value": m(calc.phase_assessed_earned_value(row)),
        "selected_method": project["percent_complete_method"] if project else None,
        "recognized_earned_value": m(calc.phase_recognized_earned_value(row, project)),
    }


def wip_aging_report(project):
    buckets = calc.wip_aging(project)
    return {
        "project_id": project["id"],
        "as_of_date": calc.today().isoformat(),
        "bucket_0_30": m(buckets["bucket_0_30"]),
        "bucket_31_60": m(buckets["bucket_31_60"]),
        "bucket_61_90": m(buckets["bucket_61_90"]),
        "bucket_over_90": m(buckets["bucket_over_90"]),
        "total_unbilled": m(buckets["total_unbilled"]),
        "write_off_eligible_amount": m(buckets["write_off_eligible_amount"]),
    }


def billing_multiplier_out(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "multiplier": r(row["multiplier"]),
        "effective_from": _date(row["effective_from"]),
        "effective_to": _date(row["effective_to"]),
        "status": row["status"],
    })
    return out


def time_entry_out(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "phase_id": row["phase_id"],
        "role_code": row["role_code"],
        "hours": m(row["hours"]),
        "work_date": _date(row["work_date"]),
        "submitted_by_user_id": row["submitted_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "status": row["status"],
        "raw_cost": m(row["raw_cost"]),
        "billable_amount": m(row["billable_amount"]),
        "applied_multiplier": r(row["applied_multiplier"]),
        "billed_invoice_id": row["billed_invoice_id"],
    })
    return out


def expense_out(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "phase_id": row["phase_id"],
        "category": row["category"],
        "amount": m(row["amount"]),
        "incurred_on": _date(row["incurred_on"]),
        "receipt_attached": row["receipt_attached"],
        "incurred_by_user_id": row["incurred_by_user_id"],
        "allowability_status": row["allowability_status"],
        "allowability_reason": row["allowability_reason"],
        "billing_status": row["billing_status"],
        "billable_amount": m(row["billable_amount"]),
        "billed_invoice_id": row["billed_invoice_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "review_justification": row["review_justification"],
    })
    return out


def subcontract_out(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "phase_id": row["phase_id"],
        "consultant_name": row["consultant_name"],
        "committed_amount": m(row["committed_amount"]),
        "commitment_start": _date(row["commitment_start"]),
        "commitment_end": _date(row["commitment_end"]),
        "pay_when_paid": row["pay_when_paid"],
        "status": row["status"],
        "approved_to_date": m(calc.subcontract_approved_to_date(row)),
        "released_to_date": m(calc.subcontract_released_to_date(row)),
        "committed_remaining": m(calc.subcontract_committed_remaining(row)),
    })
    return out


def consultant_invoice_out(row):
    out = _common(row)
    out.update({
        "subcontract_id": row["subcontract_id"],
        "amount": m(row["amount"]),
        "invoice_date": _date(row["invoice_date"]),
        "backup_attached": row["backup_attached"],
        "entered_by_user_id": row["entered_by_user_id"],
        "approval_status": row["approval_status"],
        "payment_status": row["payment_status"],
        "billing_status": row["billing_status"],
        "approved_by_user_id": row["approved_by_user_id"],
        "rejection_reason": row["rejection_reason"],
        "applied_markup_pct": r(row["applied_markup_pct"]),
        "markup_amount": m(row["markup_amount"]),
        "billable_amount": m(row["billable_amount"]),
        "client_invoice_id": row["client_invoice_id"],
    })
    return out


def invoice_out(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "period_end": _date(row["period_end"]),
        "status": row["status"],
        "revision_round": row["revision_round"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "labor_billed": m(row["labor_billed"]),
        "consultant_billed": m(row["consultant_billed"]),
        "expense_billed": m(row["expense_billed"]),
        "gross_billed": m(row["gross_billed"]),
        "volume_discount_pct": r(row["volume_discount_pct"]),
        "discount_amount": m(row["discount_amount"]),
        "retainage_amount": m(row["retainage_amount"]),
        "net_due": m(row["net_due"]),
        "backup_missing_count": row["backup_missing_count"],
        "swept_labor_count": row["swept_labor_count"],
        "swept_expense_count": row["swept_expense_count"],
        "swept_consultant_count": row["swept_consultant_count"],
        "client_decision_comment": row["client_decision_comment"],
        "paid_on": _date(row["paid_on"]),
        "void_reason": row["void_reason"],
    })
    return out


def write_off_out(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "invoice_id": row["invoice_id"],
        "target_type": row["target_type"],
        "amount": m(row["amount"]),
        "reason": row["reason"],
        "aging_days": row["aging_days"],
        "required_approver": row["required_approver"],
        "allocated_time_entry_ids": list(row["allocated_time_entry_ids"]),
        "status": row["status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
    })
    return out


def certification_out(row):
    out = _common(row)
    out.update({
        "fiscal_year": row["fiscal_year"],
        "ytd_months": row["ytd_months"],
        "direct_labor_base": m(row["direct_labor_base"]),
        "indirect_cost_pool": m(row["indirect_cost_pool"]),
        "unallowable_costs": m(row["unallowable_costs"]),
        "status": row["status"],
        "provisional_overhead_rate": r(row["provisional_overhead_rate"]),
        "final_overhead_rate": r(row["final_overhead_rate"]),
        "prepared_by_user_id": row["prepared_by_user_id"],
        "certified_by_user_id": row["certified_by_user_id"],
        "certified_multiplier_ceiling": r(row["certified_multiplier_ceiling"]),
        "findings": row["findings"],
    })
    return out
