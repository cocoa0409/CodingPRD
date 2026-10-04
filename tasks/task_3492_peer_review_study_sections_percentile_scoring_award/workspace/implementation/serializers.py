"""Entity -> JSON views. Derived counters are recomputed from base data."""
from services import (
    active_assignment_count,
    live_assignment_count,
    section_assigned_count,
)
from util import render_dt, render_ts


def _base(e):
    return {
        "id": e["id"],
        "created_at": render_ts(e["created_at"]),
        "updated_at": render_ts(e["updated_at"]),
        "version": e["version"],
    }


def foa_json(e):
    out = _base(e)
    out.update(
        {
            "pa_number": e["pa_number"],
            "title": e["title"],
            "activity_code": e["activity_code"],
            "research_strategy_page_limit": e["research_strategy_page_limit"],
            "min_direct_cents_per_year": e["min_direct_cents_per_year"],
            "max_direct_cents_per_year": e["max_direct_cents_per_year"],
            "max_years": e["max_years"],
            "open_date": render_dt(e["open_date"]),
            "receipt_deadline": render_dt(e["receipt_deadline"]),
            "status": e["status"],
        }
    )
    return out


def institute_json(e):
    out = _base(e)
    out.update(
        {
            "name": e["name"],
            "appropriation_cents": e["appropriation_cents"],
            "reserve_cents": e["reserve_cents"],
            "indirect_cost_rate": e["indirect_cost_rate"],
            "select_pay_cap_pct": e["select_pay_cap_pct"],
            "select_pay_extension_percentile": e["select_pay_extension_percentile"],
            "committed_cents": e["committed_cents"],
            "disbursed_cents": e["disbursed_cents"],
            "select_pay_spent_cents": e["select_pay_spent_cents"],
            "current_payline_percentile": e["current_payline_percentile"],
        }
    )
    return out


def institution_json(e):
    out = _base(e)
    out.update(
        {
            "name": e["name"],
            "human_subjects_certification_expiry": render_dt(
                e["human_subjects_certification_expiry"]
            ),
            "animal_welfare_assurance_expiry": render_dt(
                e["animal_welfare_assurance_expiry"]
            ),
        }
    )
    return out


def applicant_json(e):
    out = _base(e)
    out.update(
        {
            "full_name": e["full_name"],
            "email": e["email"],
            "career_stage": e["career_stage"],
        }
    )
    return out


def application_json(e):
    out = _base(e)
    out.update(
        {
            "foa_id": e["foa_id"],
            "applicant_id": e["applicant_id"],
            "institution_id": e["institution_id"],
            "title": e["title"],
            "research_strategy_page_count": e["research_strategy_page_count"],
            "direct_cents_per_year": list(e["direct_cents_per_year"]),
            "requested_years": e["requested_years"],
            "human_subjects_involved": e["human_subjects_involved"],
            "vertebrate_animals_involved": e["vertebrate_animals_involved"],
            "requested_study_section_id": e["requested_study_section_id"],
            "requested_institute_id": e["requested_institute_id"],
            "excluded_reviewer_ids": list(e["excluded_reviewer_ids"]),
            "study_section_id": e["study_section_id"],
            "institute_id": e["institute_id"],
            "live_assignment_count": live_assignment_count(e["id"]),
            "impact_score": e["impact_score"],
            "approach_mean": e["approach_mean"],
            "significance_mean": e["significance_mean"],
            "innovation_mean": e["innovation_mean"],
            "percentile_raw": e["percentile_raw"],
            "percentile_normalized": e["percentile_normalized"],
            "status": e["status"],
        }
    )
    return out


def section_json(e):
    out = _base(e)
    out.update(
        {
            "name": e["name"],
            "meeting_date": render_dt(e["meeting_date"]),
            "application_quota": e["application_quota"],
            "assigned_application_count": section_assigned_count(e["id"]),
            "status": e["status"],
        }
    )
    return out


def reviewer_json(e):
    out = _base(e)
    out.update(
        {
            "full_name": e["full_name"],
            "institution_id": e["institution_id"],
            "expertise_keywords": list(e["expertise_keywords"]),
            "declared_conflicts": list(e["declared_conflicts"]),
            "active_assignment_count": active_assignment_count(e["id"]),
            "status": e["status"],
        }
    )
    return out


def assignment_json(e):
    out = _base(e)
    out.update(
        {
            "application_id": e["application_id"],
            "reviewer_id": e["reviewer_id"],
            "role": e["role"],
            "significance_score": e["significance_score"],
            "innovation_score": e["innovation_score"],
            "approach_score": e["approach_score"],
            "investigator_score": e["investigator_score"],
            "environment_score": e["environment_score"],
            "overall_impact_score": e["overall_impact_score"],
            "status": e["status"],
        }
    )
    return out


def council_review_json(e):
    out = _base(e)
    out.update(
        {
            "application_id": e["application_id"],
            "recommendation": e["recommendation"],
            "priority_alignment_score": e["priority_alignment_score"],
            "portfolio_balance_note": e["portfolio_balance_note"],
            "recorded_by": e["recorded_by"],
        }
    )
    return out


def jit_json(e):
    out = _base(e)
    out.update(
        {
            "application_id": e["application_id"],
            "required_items": list(e["required_items"]),
            "submitted_items": list(e["submitted_items"]),
            "due_date": render_dt(e["due_date"]),
            "budget_cut_pct": e["budget_cut_pct"],
            "status": e["status"],
        }
    )
    return out


def award_json(e):
    out = _base(e)
    out.update(
        {
            "application_id": e["application_id"],
            "institute_id": e["institute_id"],
            "institution_id": e["institution_id"],
            "start_date": render_dt(e["start_date"]),
            "end_date": render_dt(e["end_date"]),
            "period_total_cents": list(e["period_total_cents"]),
            "total_awarded_cents": e["total_awarded_cents"],
            "disbursed_cents": e["disbursed_cents"],
            "disbursed_per_period_cents": list(e["disbursed_per_period_cents"]),
            "carried_out_per_period_cents": list(e["carried_out_per_period_cents"]),
            "current_period": e["current_period"],
            "terms_and_conditions": list(e["terms_and_conditions"]),
            "originating_transfer_id": e["originating_transfer_id"],
            "status": e["status"],
        }
    )
    return out


def report_json(e):
    out = _base(e)
    out.update(
        {
            "award_id": e["award_id"],
            "period_year": e["period_year"],
            "actual_expenditure_cents": e["actual_expenditure_cents"],
            "publications_count": e["publications_count"],
            "submitted_late": e["submitted_late"],
            "status": e["status"],
        }
    )
    return out


def modification_json(e):
    out = _base(e)
    out.update(
        {
            "award_id": e["award_id"],
            "type": e["type"],
            "amount_cents": e["amount_cents"],
            "from_period": e["from_period"],
            "new_end_date": render_dt(e["new_end_date"]),
            "reason": e["reason"],
            "auto_approved": e["auto_approved"],
            "status": e["status"],
        }
    )
    return out


def transfer_json(e):
    out = _base(e)
    out.update(
        {
            "award_id": e["award_id"],
            "to_institution_id": e["to_institution_id"],
            "effective_date": render_dt(e["effective_date"]),
            "proration_variant": e["proration_variant"],
            "relinquished_amount_cents": e["relinquished_amount_cents"],
            "status": e["status"],
        }
    )
    return out
