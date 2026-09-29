"""Resource views. Computed fields are derived at read time so the store can
never drift from the rules in §3."""

from core import iso
import domain


def local_view(rec):
    return {
        "id": rec["id"],
        "local_number": rec["local_number"],
        "name": rec["name"],
        "kind": rec["kind"],
        "reciprocity_factor_bp": rec["reciprocity_factor_bp"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def member_view(rec):
    return {
        "id": rec["id"],
        "full_name": rec["full_name"],
        "home_local_id": rec["home_local_id"],
        "classification": rec["classification"],
        "apprentice_period": rec["apprentice_period"],
        "local_hours_in_trade": rec["local_hours_in_trade"],
        "standing": rec["standing"],
        "is_traveler": domain.member_is_traveler(rec),
        "re_registration_eligible_at": iso(rec["re_registration_eligible_at"]),
        "refusal_strike_count": domain.refusal_strike_count(rec["id"]),
        "dispatch_eligible": domain.member_dispatch_eligible(rec),
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def endorsement_view(rec):
    return {
        "id": rec["id"],
        "member_id": rec["member_id"],
        "skill_code": rec["skill_code"],
        "certified_until": iso(rec["certified_until"]),
        "verified": rec["verified"],
        "created_at": iso(rec["created_at"]),
    }


def list_view(rec):
    return {
        "id": rec["id"],
        "group_code": rec["group_code"],
        "priority_rank": rec["priority_rank"],
        "ordering_policy": rec["ordering_policy"],
        "requires_local_hours": rec["requires_local_hours"],
        "accepts_travelers": rec["accepts_travelers"],
        "registered_count": domain.registered_count(rec["id"]),
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def registration_view(rec):
    return {
        "id": rec["id"],
        "member_id": rec["member_id"],
        "list_id": rec["list_id"],
        "predecessor_registration_id": rec["predecessor_registration_id"],
        "claim_position_preservation": rec["claim_position_preservation"],
        "reciprocity_credits": rec["reciprocity_credits"],
        "registered_at": iso(rec["registered_at"]),
        "last_renewed_at": iso(rec["last_renewed_at"]),
        "renewal_due_at": iso(rec["renewal_due_at"]),
        "credited_seniority_hours": rec["credited_seniority_hours"],
        "demotion_count": rec["demotion_count"],
        "priority_flag": rec["priority_flag"],
        "position_number": domain.position_number(rec),
        "status": rec["status"],
        "removal_reason": rec["removal_reason"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def contractor_view(rec):
    return {
        "id": rec["id"],
        "name": rec["name"],
        "agreement_expires_at": iso(rec["agreement_expires_at"]),
        "signatory_status": rec["signatory_status"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def job_request_view(rec):
    return {
        "id": rec["id"],
        "contractor_id": rec["contractor_id"],
        "job_site": rec["job_site"],
        "journeyworkers_requested": rec["journeyworkers_requested"],
        "apprentices_requested": rec["apprentices_requested"],
        "expected_duration_days": rec["expected_duration_days"],
        "report_at": iso(rec["report_at"]),
        "hourly_rate_cents": rec["hourly_rate_cents"],
        "required_skill_code": rec["required_skill_code"],
        "special_skill_slots_requested": rec["special_skill_slots_requested"],
        "named_call_member_ids": rec["named_call_member_ids"],
        "duration_type": rec["duration_type"],
        "named_call_allowance": rec["named_call_allowance"],
        "special_skill_allowance": rec["special_skill_allowance"],
        "accepted_journeyworker_count": domain.accepted_journeyworker_count(rec),
        "accepted_apprentice_count": domain.accepted_apprentice_count(rec),
        "open_journeyworker_slots": domain.open_journeyworker_slots(rec),
        "open_apprentice_slots": domain.open_apprentice_slots(rec),
        "max_apprentices_allowed": domain.max_apprentices_allowed(rec),
        "status": rec["status"],
        "suspended_from_status": rec["suspended_from_status"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def referral_view(rec):
    return {
        "id": rec["id"],
        "job_request_id": rec["job_request_id"],
        "registration_id": rec["registration_id"],
        "member_id": rec["member_id"],
        "slot_kind": rec["slot_kind"],
        "referral_kind": rec["referral_kind"],
        "variant_applied": rec["variant_applied"],
        "out_of_order_override": rec["out_of_order_override"],
        "override_reason": rec["override_reason"],
        "issued_by_user_id": rec["issued_by_user_id"],
        "issued_at": iso(rec["issued_at"]),
        "acceptance_deadline": iso(rec["acceptance_deadline"]),
        "list_position_at_issue": rec["list_position_at_issue"],
        "refusal_good_cause_code": rec["refusal_good_cause_code"],
        "status": rec["status"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def dispatch_view(rec):
    return {
        "id": rec["id"],
        "referral_id": rec["referral_id"],
        "job_request_id": rec["job_request_id"],
        "member_id": rec["member_id"],
        "recall_of_dispatch_id": rec["recall_of_dispatch_id"],
        "start_at": iso(rec["start_at"]),
        "ended_at": iso(rec["ended_at"]),
        "hours_worked": rec["hours_worked"],
        "layoff_reason": rec["layoff_reason"],
        "recall_window_ends_at": iso(rec["recall_window_ends_at"]),
        "status": rec["status"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def grievance_view(rec):
    return {
        "id": rec["id"],
        "referral_id": rec["referral_id"],
        "grievant_member_id": rec["grievant_member_id"],
        "claim_type": rec["claim_type"],
        "narrative": rec["narrative"],
        "filed_at": iso(rec["filed_at"]),
        "decided_by_user_id": rec["decided_by_user_id"],
        "decided_at": iso(rec["decided_at"]),
        "remedy": rec["remedy"],
        "back_pay_variant": rec["back_pay_variant"],
        "back_pay_hours": rec["back_pay_hours"],
        "back_pay_amount_cents": rec["back_pay_amount_cents"],
        "status": rec["status"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def ratio_policy_view(rec):
    return {
        "id": rec["id"],
        "policy_code": rec["policy_code"],
        "first_apprentice_at_jw_count": rec["first_apprentice_at_jw_count"],
        "then_every_n_jw": rec["then_every_n_jw"],
        "effective_from": iso(rec["effective_from"]),
        "status": rec["status"],
        "created_at": iso(rec["created_at"]),
        "updated_at": iso(rec["updated_at"]),
        "version": rec["version"],
    }


def ledger_view(rec):
    return {
        "id": rec["id"],
        "event_code": rec["event_code"],
        "referral_id": rec["referral_id"],
        "member_id": rec["member_id"],
        "recorded_at": iso(rec["recorded_at"]),
        "retention_until": iso(rec["retention_until"]),
        "purge_state": rec["purge_state"],
        "snapshot_json": rec["snapshot_json"],
        "hours_delta": rec["hours_delta"],
        "created_at": iso(rec["created_at"]),
    }
