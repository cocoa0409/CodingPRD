"""Resource serializers.  Every datetime leaves through iso3()."""

from envelope import iso3


def _common(row, body):
    body["id"] = row["id"]
    out = {"id": row["id"]}
    for key, value in body.items():
        if key == "id":
            continue
        out[key] = value
    out["created_at"] = iso3(row["created_at"])
    out["updated_at"] = iso3(row["updated_at"])
    out["version"] = row["version"]
    return out


def state_rule(row):
    return _common(row, {
        "state_code": row["state_code"],
        "chart_review_sample_pct": row["chart_review_sample_pct"],
        "review_deadline_hours": row["review_deadline_hours"],
        "collaborating_physician_required": row["collaborating_physician_required"],
        "min_independent_practice_age_months":
            row["min_independent_practice_age_months"],
        "controlled_rx_allowed": row["controlled_rx_allowed"],
        "max_supervised_clinicians_per_physician":
            row["max_supervised_clinicians_per_physician"],
    })


def protocol(row):
    return _common(row, {
        "complaint_code": row["complaint_code"],
        "min_age_months": row["min_age_months"],
        "max_age_months": row["max_age_months"],
        "base_price_cents": row["base_price_cents"],
        "acuity_tier": row["acuity_tier"],
        "red_flag_codes": list(row["red_flag_codes"]),
        "max_temp_c": row["max_temp_c"],
        "max_heart_rate_bpm": row["max_heart_rate_bpm"],
        "min_spo2_pct": row["min_spo2_pct"],
        "requires_cosign": row["requires_cosign"],
        "allowed_state_codes": list(row["allowed_state_codes"]),
    })


def clinic(row):
    return _common(row, {
        "name": row["name"],
        "state_code": row["state_code"],
        "min_clinicians_required": row["min_clinicians_required"],
        "appointment_slots_per_hour": row["appointment_slots_per_hour"],
        "walk_in_queue_capacity": row["walk_in_queue_capacity"],
        "on_duty_clinician_count": row["on_duty_clinician_count"],
        "open_status": row["open_status"],
        "waiting_count": row["waiting_count"],
        "posted_wait_minutes": row["posted_wait_minutes"],
        "last_realized_wait_minutes": row["last_realized_wait_minutes"],
    })


def physician(row):
    return _common(row, {
        "full_name": row["full_name"],
        "licensed_state_codes": list(row["licensed_state_codes"]),
        "max_supervised_clinicians": row["max_supervised_clinicians"],
        "status": row["status"],
        "current_supervised_count": row["current_supervised_count"],
    })


def clinician(row):
    return _common(row, {
        "full_name": row["full_name"],
        "credential": row["credential"],
        "license_state_code": row["license_state_code"],
        "home_clinic_id": row["home_clinic_id"],
        "supervising_physician_id": row["supervising_physician_id"],
        "float_eligible": row["float_eligible"],
        "scope_hold": row["scope_hold"],
        "active_assignment_count": row["active_assignment_count"],
    })


def patient(row):
    return _common(row, {
        "full_name": row["full_name"],
        "date_of_birth": row["date_of_birth"],
        "payer_name": row["payer_name"],
        "member_id": row["member_id"],
        "pcp_name": row["pcp_name"],
        "pcp_direct_address": row["pcp_direct_address"],
        "pcp_accepts_electronic_summary": row["pcp_accepts_electronic_summary"],
        "pcp_consent_on_file": row["pcp_consent_on_file"],
        "active_therapy_classes": list(row["active_therapy_classes"]),
        "active_therapy_class_count": row["active_therapy_class_count"],
        "outstanding_balance_cents": row["outstanding_balance_cents"],
    })


def assignment(row):
    return _common(row, {
        "clinic_id": row["clinic_id"],
        "clinician_id": row["clinician_id"],
        "covers_assignment_id": row["covers_assignment_id"],
        "pinned_supervising_physician_id": row["pinned_supervising_physician_id"],
        "role_kind": row["role_kind"],
        "starts_at": iso3(row["starts_at"]),
        "ends_at": iso3(row["ends_at"]),
        "status": row["status"],
        "cancel_reason": row.get("cancel_reason"),
    })


def queue_entry(row):
    return _common(row, {
        "clinic_id": row["clinic_id"],
        "patient_id": row["patient_id"],
        "kind": row["kind"],
        "complaint_code": row["complaint_code"],
        "acuity_tier": row["acuity_tier"],
        "scheduled_at": iso3(row["scheduled_at"]),
        "arrived_at": iso3(row["arrived_at"]),
        "called_at": iso3(row["called_at"]),
        "priority_score": row["priority_score"],
        "realized_wait_minutes": row["realized_wait_minutes"],
        "status": row["status"],
    })


def visit(row):
    return _common(row, {
        "clinic_id": row["clinic_id"],
        "patient_id": row["patient_id"],
        "queue_entry_id": row["queue_entry_id"],
        "protocol_id": row["protocol_id"],
        "clinician_id": row["clinician_id"],
        "complaint_code": row["complaint_code"],
        "patient_age_months_at_visit": row["patient_age_months_at_visit"],
        "clinical_status": row["clinical_status"],
        "billing_status": row["billing_status"],
        "self_pay": row["self_pay"],
        "coverage_status": row["coverage_status"],
        "copay_cents": row["copay_cents"],
        "coinsurance_pct": row["coinsurance_pct"],
        "quoted_price_cents": row["quoted_price_cents"],
        "final_price_cents": row["final_price_cents"],
        "patient_responsibility_cents": row["patient_responsibility_cents"],
        "payer_responsibility_cents": row["payer_responsibility_cents"],
        "services_rendered": list(row["services_rendered"]),
        "referral_required": row["referral_required"],
    })


def assessment(row):
    return _common(row, {
        "visit_id": row["visit_id"],
        "protocol_id": row["protocol_id"],
        "cosigned_by_physician_id": row["cosigned_by_physician_id"],
        "temp_c": row["temp_c"],
        "heart_rate_bpm": row["heart_rate_bpm"],
        "spo2_pct": row["spo2_pct"],
        "red_flag_codes": list(row["red_flag_codes"]),
        "referral_destination": row["referral_destination"],
        "referral_reason_code": row["referral_reason_code"],
        "cosigned_at": iso3(row["cosigned_at"]),
        "status": row["status"],
    })


def prescription(row):
    return _common(row, {
        "visit_id": row["visit_id"],
        "patient_id": row["patient_id"],
        "prescriber_clinician_id": row["prescriber_clinician_id"],
        "supersedes_prescription_id": row["supersedes_prescription_id"],
        "drug_name": row["drug_name"],
        "therapy_class": row["therapy_class"],
        "days_supply": row["days_supply"],
        "pharmacy_npi": row["pharmacy_npi"],
        "routed_at": iso3(row["routed_at"]),
        "status": row["status"],
        "cancel_reason": row.get("cancel_reason"),
    })


def chart_review(row):
    return _common(row, {
        "visit_id": row["visit_id"],
        "assessment_id": row["assessment_id"],
        "reviewer_physician_id": row["reviewer_physician_id"],
        "sampled_reason": row["sampled_reason"],
        "due_at": iso3(row["due_at"]),
        "changes_requested_count": row["changes_requested_count"],
        "outcome": row["outcome"],
        "status": row["status"],
    })


def visit_summary(row):
    return _common(row, {
        "visit_id": row["visit_id"],
        "destination_kind": row["destination_kind"],
        "destination_address": row["destination_address"],
        "includes_referral": row["includes_referral"],
        "attempt_count": row["attempt_count"],
        "last_error_code": row["last_error_code"],
        "sent_at": iso3(row["sent_at"]),
        "status": row["status"],
    })
