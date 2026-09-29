"""Per-entity serializers.

PRD 2.4: ShelterProgram, Youth, Admission, GuardianNotification, SafetyScreening,
ReunificationCase, MediationSession, TlpPlacement, EducationEnrollment,
GovernanceProposal and GovernanceVote carry id, created_at, updated_at and version.
OutreachContact, SavingsLedgerEntry and LifeSkillsCompletion are immutable event
records that "carry only id and created_at; they have no updated_at field and no
version field at all, and neither field appears in their responses."
"""

import calc
import cascade
import store

I = store.iso


def _audit(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = I(rec["created_at"])
    out["updated_at"] = I(rec["updated_at"])
    out["version"] = rec["version"]
    return out


def _event(rec, out):
    out["id"] = rec["id"]
    out["created_at"] = I(rec["created_at"])
    return out


def program(rec):
    return _audit(
        rec,
        {
            "name": rec["name"],
            "program_type": rec["program_type"],
            "licensed_bed_capacity": rec["licensed_bed_capacity"],
            "min_age_years": rec["min_age_years"],
            "max_age_years": rec["max_age_years"],
            "max_stay_nights": rec["max_stay_nights"],
            "max_placement_days": rec["max_placement_days"],
            "savings_match_rate_bp": rec["savings_match_rate_bp"],
            "required_savings_rate_bp": rec["required_savings_rate_bp"],
            "occupied_beds": rec["occupied_beds"],
            "waitlisted_count": rec["waitlisted_count"],
            "overdue_notification_count": rec["overdue_notification_count"],
            "utilization_bp": rec["utilization_bp"],
            "posture": rec["posture"],
        },
    )


def youth(rec):
    return _audit(
        rec,
        {
            "legal_first_name": rec["legal_first_name"],
            "legal_last_name": rec["legal_last_name"],
            "date_of_birth": rec["date_of_birth"].isoformat(),
            "unaccompanied": rec["unaccompanied"],
            # PRD 2.5: age_years "is not stored as a client input at all but computed
            # against the logical clock on every read".
            "age_years": calc.age_years(rec),
            "status": rec["status"],
            "risk_posture": rec["risk_posture"],
            "trafficking_risk_score": rec["trafficking_risk_score"],
            "trafficking_risk_tier": rec["trafficking_risk_tier"],
            "engagement_contact_count": rec["engagement_contact_count"],
            "basic_needs_provision_count": rec["basic_needs_provision_count"],
            "cumulative_shelter_nights": rec["cumulative_shelter_nights"],
            "lifetime_savings_deposited_cents": rec["lifetime_savings_deposited_cents"],
            "governance_vote_eligible": rec["governance_vote_eligible"],
            "intake_worker_user_id": rec["intake_worker_user_id"],
        },
    )


def outreach_contact(rec):
    return _event(
        rec,
        {
            "youth_id": rec["youth_id"],
            "contacted_at": I(rec["contacted_at"]),
            "engagement_stage": rec["engagement_stage"],
            "basic_needs_provided": list(rec["basic_needs_provided"]),
            "indicator_flags": list(rec["indicator_flags"]),
            "worker_user_id": rec["worker_user_id"],
        },
    )


def admission(rec):
    return _audit(
        rec,
        {
            "youth_id": rec["youth_id"],
            "program_id": rec["program_id"],
            "status": rec["status"],
            "requested_at": I(rec["requested_at"]),
            "admitted_at": I(rec["admitted_at"]),
            "planned_discharge_at": I(rec["planned_discharge_at"]),
            "discharged_at": I(rec["discharged_at"]),
            "priority_score": rec["priority_score"],
            "projected_billable_nights": rec["projected_billable_nights"],
            "final_billable_nights": rec["final_billable_nights"],
            "extension_count": rec["extension_count"],
            "capacity_blocked": rec["capacity_blocked"],
            "exit_destination": rec["exit_destination"],
            "outcome_positive": rec["outcome_positive"],
            "admitting_user_id": rec["admitting_user_id"],
        },
    )


def notification(rec):
    return _audit(
        rec,
        {
            "admission_id": rec["admission_id"],
            "status": rec["status"],
            "due_at": I(rec["due_at"]),
            "attempt_count": rec["attempt_count"],
            "last_attempt_at": I(rec["last_attempt_at"]),
            "attempt_channel": rec["attempt_channel"],
            "waiver_reason": rec["waiver_reason"],
            "runaway_report_filed_at": I(rec["runaway_report_filed_at"]),
            "resolved_at": I(rec["resolved_at"]),
            "resolving_user_id": rec["resolving_user_id"],
        },
    )


def screening(rec):
    return _audit(
        rec,
        {
            "youth_id": rec["youth_id"],
            "screened_at": I(rec["screened_at"]),
            "indicator_codes": list(rec["indicator_codes"]),
            "score": rec["score"],
            "tier": rec["tier"],
            "status": rec["status"],
            "specialized_response_code": rec["specialized_response_code"],
            "screener_user_id": rec["screener_user_id"],
            "disposition_user_id": rec["disposition_user_id"],
        },
    )


def case(rec):
    return _audit(
        rec,
        {
            "youth_id": rec["youth_id"],
            "guardian_household_label": rec["guardian_household_label"],
            "status": rec["status"],
            "opened_at": I(rec["opened_at"]),
            "mediation_round": rec["mediation_round"],
            "max_mediation_rounds": rec["max_mediation_rounds"],
            "safety_assessment_result": rec["safety_assessment_result"],
            "aftercare_plan_due_at": I(rec["aftercare_plan_due_at"]),
            "aftercare_contacts_completed": rec["aftercare_contacts_completed"],
            "decision_user_id": rec["decision_user_id"],
            "closed_at": I(rec["closed_at"]),
        },
    )


def session(rec):
    return _audit(
        rec,
        {
            "case_id": rec["case_id"],
            "scheduled_start_at": I(rec["scheduled_start_at"]),
            "scheduled_end_at": I(rec["scheduled_end_at"]),
            "round_number": rec["round_number"],
            "outcome": rec["outcome"],
            "held_at": I(rec["held_at"]),
            "scheduler_user_id": rec["scheduler_user_id"],
            "recorded_by_user_id": rec["recorded_by_user_id"],
        },
    )


def placement(rec):
    # Every derived figure of a placement is recomputed on every read (PRD 3.7);
    # a read is not a mutation, so the version is untouched.
    cascade.apply_placement_derived(rec)
    return _audit(
        rec,
        {
            "youth_id": rec["youth_id"],
            "program_id": rec["program_id"],
            "tenancy_status": rec["tenancy_status"],
            "compliance_status": rec["compliance_status"],
            "placed_at": I(rec["placed_at"]),
            "documented_monthly_income_cents": rec["documented_monthly_income_cents"],
            "days_elapsed": rec["days_elapsed"],
            "base_allowance_days": rec["base_allowance_days"],
            "earned_bonus_days": rec["earned_bonus_days"],
            "allowance_days": rec["allowance_days"],
            "consumed_ratio_bp": rec["consumed_ratio_bp"],
            "life_skills_credit_hours": rec["life_skills_credit_hours"],
            "required_savings_cents": rec["required_savings_cents"],
            "savings_balance_cents": rec["savings_balance_cents"],
            "match_awarded_cents": rec["match_awarded_cents"],
            "consecutive_probation_reviews": rec["consecutive_probation_reviews"],
            "exited_at": I(rec["exited_at"]),
            "exit_reason": rec["exit_reason"],
            "coordinator_user_id": rec["coordinator_user_id"],
        },
    )


def savings_entry(rec):
    return _event(
        rec,
        {
            "placement_id": rec["placement_id"],
            "entry_type": rec["entry_type"],
            "amount_cents": rec["amount_cents"],
            "signed_amount_cents": rec["signed_amount_cents"],
            "match_component_cents": rec["match_component_cents"],
            "balance_after_cents": rec["balance_after_cents"],
            "posted_at": I(rec["posted_at"]),
            "source_note": rec["source_note"],
            "recorded_by_user_id": rec["recorded_by_user_id"],
        },
    )


def life_skills(rec):
    return _event(
        rec,
        {
            "placement_id": rec["placement_id"],
            "module_code": rec["module_code"],
            "credit_hours": rec["credit_hours"],
            "completed_at": I(rec["completed_at"]),
            "verified_by_user_id": rec["verified_by_user_id"],
        },
    )


def enrollment(rec):
    return _audit(
        rec,
        {
            "youth_id": rec["youth_id"],
            "school_name": rec["school_name"],
            "enrollment_type": rec["enrollment_type"],
            "status": rec["status"],
            "records_waived": rec["records_waived"],
            "enrolled_at": I(rec["enrolled_at"]),
            "verified_at": I(rec["verified_at"]),
            "liaison_user_id": rec["liaison_user_id"],
        },
    )


def proposal(rec):
    return _audit(
        rec,
        {
            "program_id": rec["program_id"],
            "title": rec["title"],
            "category": rec["category"],
            "status": rec["status"],
            "voting_closes_at": I(rec["voting_closes_at"]),
            "support_vote_count": rec["support_vote_count"],
            "oppose_vote_count": rec["oppose_vote_count"],
            "eligible_electorate_size": rec["eligible_electorate_size"],
            "support_ratio_bp": rec["support_ratio_bp"],
            "adopted_at": I(rec["adopted_at"]),
            "decided_by_user_id": rec["decided_by_user_id"],
        },
    )


def vote(rec):
    return _audit(
        rec,
        {
            "proposal_id": rec["proposal_id"],
            "youth_id": rec["youth_id"],
            "stance": rec["stance"],
            "status": rec["status"],
            "cast_at": I(rec["cast_at"]),
            "retracted_at": I(rec["retracted_at"]),
        },
    )
