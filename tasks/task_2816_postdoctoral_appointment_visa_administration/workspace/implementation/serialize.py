"""Resource serializers: every field declared for the entity plus the four
system-managed properties of PRD section 2.4."""
from store import iso_date, iso_ts, money_out, number_out


def _common(record):
    return {
        "id": record["id"],
        "created_at": iso_ts(record["created_at"]),
        "updated_at": iso_ts(record["updated_at"]),
        "version": record["version"],
    }


def postdoc_out(record):
    data = _common(record)
    data.update({
        "full_name": record["full_name"],
        "email": record["email"],
        "citizenship_country": record["citizenship_country"],
        "requires_sponsorship": record["requires_sponsorship"],
        "phd_award_date": iso_date(record["phd_award_date"]),
        "prior_external_months_in_rank": record["prior_external_months_in_rank"],
        "o1_endorsement_on_file": record["o1_endorsement_on_file"],
        "j1_two_year_bar_flag": record["j1_two_year_bar_flag"],
        "restricted_party_flag": record["restricted_party_flag"],
        "total_months_in_rank": record["total_months_in_rank"],
        "status": record["status"],
    })
    return data


def mentor_out(record):
    data = _common(record)
    data.update({
        "full_name": record["full_name"],
        "department": record["department"],
        "mentor_training_valid_through": iso_date(record["mentor_training_valid_through"]),
        "max_concurrent_postdocs": record["max_concurrent_postdocs"],
        "active_postdoc_count": record["active_postdoc_count"],
    })
    return data


def funding_source_out(record):
    data = _common(record)
    data.update({
        "sponsor_name": record["sponsor_name"],
        "funding_type": record["funding_type"],
        "salary_floor_policy": record["salary_floor_policy"],
        "award_start_date": iso_date(record["award_start_date"]),
        "award_end_date": iso_date(record["award_end_date"]),
        "annual_budget_usd": money_out(record["annual_budget_usd"]),
        "requires_mentoring_plan": record["requires_mentoring_plan"],
        "requires_idp": record["requires_idp"],
        "verification_status": record["verification_status"],
        "verified_at": iso_ts(record["verified_at"]),
        "verified_by_user_id": record["verified_by_user_id"],
        "encumbered_usd": money_out(record["encumbered_usd"]),
        "available_balance_usd": money_out(record["available_balance_usd"]),
    })
    return data


def laboratory_out(record):
    data = _common(record)
    data.update({
        "name": record["name"],
        "biosafety_level": record["biosafety_level"],
        "bench_capacity": record["bench_capacity"],
        "decontamination_buffer_days": record["decontamination_buffer_days"],
        "status": record["status"],
    })
    return data


def appointment_out(record):
    data = _common(record)
    data.update({
        "postdoc_id": record["postdoc_id"],
        "mentor_id": record["mentor_id"],
        "funding_source_id": record["funding_source_id"],
        "predecessor_appointment_id": record["predecessor_appointment_id"],
        "title_classification": record["title_classification"],
        "employment_class": record["employment_class"],
        "term_start_date": iso_date(record["term_start_date"]),
        "term_end_date": iso_date(record["term_end_date"]),
        "annual_salary_usd": money_out(record["annual_salary_usd"]),
        "appointment_status": record["appointment_status"],
        "compliance_status": record["compliance_status"],
        "prepared_by_user_id": record["prepared_by_user_id"],
        "term_months": record["term_months"],
        "months_in_rank_at_start": record["months_in_rank_at_start"],
        "cumulative_months_in_rank_at_end": record["cumulative_months_in_rank_at_end"],
        "salary_floor_usd": money_out(record["salary_floor_usd"]),
        "salary_exception_floor_usd": money_out(record["salary_exception_floor_usd"]),
        "salary_exception_approved_by_user_id": record["salary_exception_approved_by_user_id"],
        "benefits_package": record["benefits_package"],
        "fringe_rate": number_out(record["fringe_rate"]),
        "encumbrance_usd": money_out(record["encumbrance_usd"]),
        "withdraw_reason": record["withdraw_reason"],
        "reinstated_count": record["reinstated_count"],
    })
    return data


def visa_case_out(record):
    data = _common(record)
    data.update({
        "appointment_id": record["appointment_id"],
        "visa_category": record["visa_category"],
        "processing_track": record["processing_track"],
        "status": record["status"],
        "filed_at": iso_ts(record["filed_at"]),
        "rfe_round_count": record["rfe_round_count"],
        "projection_variant": record["projection_variant"],
        "projected_decision_date": iso_date(record["projected_decision_date"]),
        "earliest_lawful_start_date": iso_date(record["earliest_lawful_start_date"]),
        "decided_at": iso_ts(record["decided_at"]),
    })
    return data


def development_document_out(record):
    data = _common(record)
    data.update({
        "appointment_id": record["appointment_id"],
        "doc_type": record["doc_type"],
        "status": record["status"],
        "content_summary": record["content_summary"],
        "postdoc_acknowledged": record["postdoc_acknowledged"],
        "revision_round": record["revision_round"],
        "submitted_by_user_id": record["submitted_by_user_id"],
        "approved_at": iso_ts(record["approved_at"]),
    })
    return data


def export_control_review_out(record):
    data = _common(record)
    data.update({
        "appointment_id": record["appointment_id"],
        "cycle_index": record["cycle_index"],
        "status": record["status"],
        "restricted_party_hit": record["restricted_party_hit"],
        "controlled_technology_flag": record["controlled_technology_flag"],
        "screening_tier": record["screening_tier"],
        "risk_score": number_out(record["risk_score"]),
        "deemed_export_license_required": record["deemed_export_license_required"],
        "reviewer_user_id": record["reviewer_user_id"],
        "decided_at": iso_ts(record["decided_at"]),
    })
    return data


def lab_access_grant_out(record):
    data = _common(record)
    data.update({
        "appointment_id": record["appointment_id"],
        "laboratory_id": record["laboratory_id"],
        "bench_seats": record["bench_seats"],
        "access_start_date": iso_date(record["access_start_date"]),
        "access_end_date": iso_date(record["access_end_date"]),
        "status": record["status"],
        "suspension_reason": record["suspension_reason"],
        "requested_by_user_id": record["requested_by_user_id"],
    })
    return data


def reappointment_review_out(record):
    data = _common(record)
    data.update({
        "appointment_id": record["appointment_id"],
        "review_cycle": record["review_cycle"],
        "status": record["status"],
        "mentor_recommendation_note": record["mentor_recommendation_note"],
        "recommended_by_user_id": record["recommended_by_user_id"],
        "finalized_by_user_id": record["finalized_by_user_id"],
        "service_months_at_review": record["service_months_at_review"],
        "notice_days_required": record["notice_days_required"],
        "notice_deadline_date": iso_date(record["notice_deadline_date"]),
        "notice_issued_at": iso_ts(record["notice_issued_at"]),
        "notice_timely": record["notice_timely"],
        "term_extension_days": record["term_extension_days"],
        "pre_notice_term_end_date": iso_date(record["pre_notice_term_end_date"]),
        "grievance_window_end": iso_ts(record["grievance_window_end"]),
    })
    return data


def grievance_out(record):
    data = _common(record)
    data.update({
        "reappointment_review_id": record["reappointment_review_id"],
        "category": record["category"],
        "narrative": record["narrative"],
        "status": record["status"],
        "filed_at": iso_ts(record["filed_at"]),
        "filed_by_user_id": record["filed_by_user_id"],
        "resolution_note": record["resolution_note"],
        "resolved_by_user_id": record["resolved_by_user_id"],
    })
    return data


def exit_record_out(record):
    data = _common(record)
    data.update({
        "appointment_id": record["appointment_id"],
        "exit_reason": record["exit_reason"],
        "status": record["status"],
        "initiated_at": iso_ts(record["initiated_at"]),
        "ip_disclosure_count": record["ip_disclosure_count"],
        "ip_assignment_signed_at": iso_ts(record["ip_assignment_signed_at"]),
        "lab_access_cleared": record["lab_access_cleared"],
        "final_months_posted": record["final_months_posted"],
    })
    return data
