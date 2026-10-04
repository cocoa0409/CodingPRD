"""Entity -> public JSON dict. Computed fields are derived fresh on every
read (ledger, posture, estimates, open_slots, is_eligible)."""
from logic import (
    cycle_ledger, compute_posture, provisional_estimate, reconciled_cost,
    is_eligible, open_slots,
)


def ser_cycle(r):
    led = cycle_ledger(r)
    return {
        "id": r["id"],
        "name": r["name"],
        "fiscal_year": r["fiscal_year"],
        "total_budget_cents": r["total_budget_cents"],
        "priority_mode": r["priority_mode"],
        "status": r["status"],
        "pool_cents": led["pool_cents"],
        "reserved_cents": led["reserved_cents"],
        "spent_cents": led["spent_cents"],
        "available_cents": led["available_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_run(r):
    return {
        "id": r["id"],
        "funding_cycle_id": r["funding_cycle_id"],
        "status": r["status"],
        "priority_mode_snapshot": r["priority_mode_snapshot"],
        "ranked_application_ids": list(r["ranked_application_ids"]),
        "selected_application_ids": list(r["selected_application_ids"]),
        "applied_at": r["applied_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_sponsor(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "contact_email": r["contact_email"],
        "sponsor_tier": r["sponsor_tier"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_commitment(r):
    return {
        "id": r["id"],
        "sponsor_id": r["sponsor_id"],
        "funding_cycle_id": r["funding_cycle_id"],
        "amount_cents": r["amount_cents"],
        "team_build_event_date": r["team_build_event_date"],
        "status": r["status"],
        "received_at": r["received_at"],
        "allocated_amount_cents": r["allocated_amount_cents"],
        "withdrawn_at": r["withdrawn_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_application(r):
    return {
        "id": r["id"],
        "funding_cycle_id": r["funding_cycle_id"],
        "homeowner_name": r["homeowner_name"],
        "date_of_birth": r["date_of_birth"],
        "household_size": r["household_size"],
        "household_income_cents": r["household_income_cents"],
        "is_veteran": r["is_veteran"],
        "has_disability": r["has_disability"],
        "ownership_doc_provided": r["ownership_doc_provided"],
        "occupancy_doc_provided": r["occupancy_doc_provided"],
        "address": r["address"],
        "status": r["status"],
        "is_older_adult": r["is_older_adult"],
        "priority_score": r["priority_score"],
        "decision_reason": r["decision_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_assessment(r):
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "scheduled_on": r["scheduled_on"],
        "status": r["status"],
        "safety_hazard_max_severity": r["safety_hazard_max_severity"],
        "accessibility_needs_count": r["accessibility_needs_count"],
        "critical_systems_notes": r["critical_systems_notes"],
        "completed_on": r["completed_on"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_scope_item(r):
    # ScopeItem carries only id + created_at (no updated_at / version).
    return {
        "id": r["id"],
        "assessment_id": r["assessment_id"],
        "category": r["category"],
        "required_trade": r["required_trade"],
        "volunteer_performable": r["volunteer_performable"],
        "requires_permit": r["requires_permit"],
        "est_low_cents": r["est_low_cents"],
        "est_high_cents": r["est_high_cents"],
        "description": r["description"],
        "status": r["status"],
        "midpoint_cents": r["midpoint_cents"],
        "created_at": r["created_at"],
    }


def ser_project(r):
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "funding_cycle_id": r["funding_cycle_id"],
        "status": r["status"],
        "cancellation_reason": r["cancellation_reason"],
        "readiness_posture": compute_posture(r),
        # Stored planning basis (PRD 3.4/3.5): set at selection, re-aggregated
        # by scope amendments only; never observes invoices or item completion.
        "provisional_estimate_cents": r.get("provisional_estimate_cents")
            if r.get("provisional_estimate_cents") is not None
            else provisional_estimate(r),
        "envelope_cents": r["envelope_cents"],
        "reserved_balance_cents": r["reserved_balance_cents"],
        "reconciled_cost_cents": reconciled_cost(r),
        "priority_score_snapshot": r["priority_score_snapshot"],
        "completed_on": r["completed_on"],
        "follow_up_completed_on": r["follow_up_completed_on"],
        "warranty_valid_until": r["warranty_valid_until"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_event(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "name": r["name"],
        "event_date": r["event_date"],
        "max_volunteers": r["max_volunteers"],
        "status": r["status"],
        "open_slots": open_slots(r),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_volunteer(r):
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "email": r["email"],
        "skills": list(r["skills"]),
        "team_leader_eligible": r["team_leader_eligible"],
        "waiver_signed_on": r["waiver_signed_on"],
        "safety_training_completed_on": r["safety_training_completed_on"],
        "status": r["status"],
        "is_eligible": is_eligible(r),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_enrollment(r):
    return {
        "id": r["id"],
        "event_id": r["event_id"],
        "volunteer_id": r["volunteer_id"],
        "is_team_leader": r["is_team_leader"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_contractor(r):
    return {
        "id": r["id"],
        "legal_name": r["legal_name"],
        "trade": r["trade"],
        "license_number": r["license_number"],
        "license_expires_on": r["license_expires_on"],
        "insurance_expires_on": r["insurance_expires_on"],
        "max_concurrent_jobs": r["max_concurrent_jobs"],
        "status": r["status"],
        "strike_count": r["strike_count"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_work_order(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "contractor_id": r["contractor_id"],
        "scope_item_ids": list(r["scope_item_ids"]),
        "trade": r["trade"],
        "status": r["status"],
        "quote_cents": r["quote_cents"],
        "invoice_cents": r["invoice_cents"],
        "permit_number": r["permit_number"],
        "visit_start": r["visit_start"],
        "visit_end": r["visit_end"],
        "inspected_on": r["inspected_on"],
        "cancellation_reason": r["cancellation_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_material_order(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "supplier": r["supplier"],
        "lines": r["lines"],
        "status": r["status"],
        "subtotal_cents": r["subtotal_cents"],
        "delivery_fee_cents": r["delivery_fee_cents"],
        "total_cents": r["total_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_warranty_claim(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "description": r["description"],
        "claim_amount_cents": r["claim_amount_cents"],
        "status": r["status"],
        "payout_cents": r["payout_cents"],
        "submitted_on": r["submitted_on"],
        "resolution_note": r["resolution_note"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
