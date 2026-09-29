"""Entity -> JSON projections. Derived counters are computed at read time."""

from core import SCORED_ATTRIBUTES, num
import domain


def _audit(row, out, event_record=False):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    if not event_record:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def site(row):
    return _audit(row, {
        "site_code": row["site_code"],
        "name": row["name"],
        "region_code": row["region_code"],
        "registrar_headcount": row["registrar_headcount"],
        "status": row["status"],
        "active_record_count": domain.active_record_count(row["id"]),
        "flagged_record_count": domain.flagged_record_count(row["id"]),
    })


def rule_set(row):
    return _audit(row, {
        "name": row["name"],
        "version_label": row["version_label"],
        "attribute_weights": {k: num(v) for k, v in row["attribute_weights"].items()},
        "auto_link_threshold": num(row["auto_link_threshold"]),
        "review_threshold": num(row["review_threshold"]),
        "conflict_penalty_points": num(row["conflict_penalty_points"]),
        "status": row["status"],
    })


def record(row):
    return _audit(row, {
        "site_id": row["site_id"],
        "origin_search_attempt_id": row["origin_search_attempt_id"],
        "mrn": row["mrn"],
        "last_name": row["last_name"],
        "first_name": row["first_name"],
        "dob": row["dob"],
        "sex": row["sex"],
        "ssn_last4": row["ssn_last4"],
        "address_line": row["address_line"],
        "postal_code": row["postal_code"],
        "phone": row["phone"],
        "biometric_template_hash": row["biometric_template_hash"],
        "insurance_member_id": row["insurance_member_id"],
        "clinical_element_count": row["clinical_element_count"],
        "identity_state": row["identity_state"],
        "integrity_state": row["integrity_state"],
        "survivor_record_id": row["survivor_record_id"],
        "enterprise_id": row["enterprise_id"],
        "subsumed_member_count": domain.subsumed_member_count(row["id"]),
    })


def search_attempt(row):
    return _audit(row, {
        "site_id": row["site_id"],
        "searched_last_name": row["searched_last_name"],
        "searched_first_name": row["searched_first_name"],
        "searched_dob": row["searched_dob"],
        "searched_sex": row["searched_sex"],
        "searched_ssn_last4": row["searched_ssn_last4"],
        "searched_postal_code": row["searched_postal_code"],
        "searched_phone": row["searched_phone"],
        "result_count": row["result_count"],
        "top_score": num(row["top_score"]),
        "top_match_record_mrn": row["top_match_record_mrn"],
        "blocked_creation": row["blocked_creation"],
        "rule_set_version_label": row["rule_set_version_label"],
    }, event_record=True)


def pair(row):
    breakdown = row["attribute_score_breakdown"] or {}
    return _audit(row, {
        "record_a_id": row["record_a_id"],
        "record_b_id": row["record_b_id"],
        "rule_set_id": row["rule_set_id"],
        "detected_at_site_id": row["detected_at_site_id"],
        "score_variant": row["score_variant"],
        "match_score": num(row["match_score"]),
        "raw_score": num(row["raw_score"]),
        "attribute_score_breakdown": {k: num(breakdown.get(k)) for k in SCORED_ATTRIBUTES},
        "conflict_flags": list(row["conflict_flags"]),
        "classification": row["classification"],
        "subject_record_mrn": row["subject_record_mrn"],
        "evidence_points": num(row["evidence_points"]),
        "base_band": row["base_band"],
        "evidence_adjustment": num(row["evidence_adjustment"]),
        "effective_score": num(row["effective_score"]),
        "priority_band": row["priority_band"],
        "queue_state": row["queue_state"],
        "triage_note": row["triage_note"],
        "recommended_by_user_id": row["recommended_by_user_id"],
        "recommendation": row["recommendation"],
        "approved_by_user_id": row["approved_by_user_id"],
    })


def evidence(row):
    return _audit(row, {
        "pair_id": row["pair_id"],
        "evidence_type": row["evidence_type"],
        "outcome": row["outcome"],
        "weight_points": num(row["weight_points"]),
        "note": row["note"],
        "submitted_by_user_id": row["submitted_by_user_id"],
    }, event_record=True)


def merge(row):
    return _audit(row, {
        "pair_id": row["pair_id"],
        "survivor_record_id": row["survivor_record_id"],
        "subsumed_record_id": row["subsumed_record_id"],
        "rationale": row["rationale"],
        "state": row["state"],
        "approved_by_user_id": row["approved_by_user_id"],
        "moved_clinical_element_count": row["moved_clinical_element_count"],
        "subsumed_prior_enterprise_id": row["subsumed_prior_enterprise_id"],
        "recompressed_record_mrns": list(row["recompressed_record_mrns"]),
        "propagation_task_count": row["propagation_task_count"],
        "completed_at": row["completed_at"],
        "reversal_deadline_at": row["reversal_deadline_at"],
        "unmerge_reason": row["unmerge_reason"],
        "unmerged_at": row["unmerged_at"],
    })


def overlay(row):
    return _audit(row, {
        "record_id": row["record_id"],
        "overlay_type": row["overlay_type"],
        "corrected_field_snapshot": dict(row["corrected_field_snapshot"]),
        "prior_field_snapshot": dict(row["prior_field_snapshot"]),
        "affected_clinical_element_count": row["affected_clinical_element_count"],
        "encounter_from_date": row["encounter_from_date"],
        "encounter_to_date": row["encounter_to_date"],
        "state": row["state"],
        "created_by_user_id": row["created_by_user_id"],
        "closure_note": row["closure_note"],
    })


def remediation(row):
    return _audit(row, {
        "source_type": row["source_type"],
        "merge_operation_id": row["merge_operation_id"],
        "overlay_correction_id": row["overlay_correction_id"],
        "record_id": row["record_id"],
        "element_count_subject": row["element_count_subject"],
        "element_count_quarantined": row["element_count_quarantined"],
        "element_count_reassigned": row["element_count_reassigned"],
        "reassigned_to_record_mrn": row["reassigned_to_record_mrn"],
        "state": row["state"],
        "closure_note": row["closure_note"],
    })


def system(row):
    return _audit(row, {
        "system_code": row["system_code"],
        "name": row["name"],
        "propagation_mode": row["propagation_mode"],
        "ack_required": row["ack_required"],
        "max_concurrent_dispatch": row["max_concurrent_dispatch"],
        "status": row["status"],
        "unacked_task_count": domain.unacked_task_count(row["id"]),
    })


def task(row):
    return _audit(row, {
        "merge_operation_id": row["merge_operation_id"],
        "overlay_correction_id": row["overlay_correction_id"],
        "downstream_system_id": row["downstream_system_id"],
        "operation_kind": row["operation_kind"],
        "state": row["state"],
        "attempt_count": row["attempt_count"],
        "dispatch_window_start_at": row["dispatch_window_start_at"],
        "dispatch_window_end_at": row["dispatch_window_end_at"],
        "propagation_deadline_at": row["propagation_deadline_at"],
        "last_error_code": row["last_error_code"],
    })


def investigation(row):
    return _audit(row, {
        "record_id": row["record_id"],
        "pair_id": row["pair_id"],
        "trigger_kind": row["trigger_kind"],
        "opened_by": row["opened_by"],
        "opened_by_user_id": row["opened_by_user_id"],
        "risk_score": num(row["risk_score"]),
        "state": row["state"],
        "note": row["note"],
        "finding_note": row["finding_note"],
        "referral_reference": row["referral_reference"],
    })


def external_match(row):
    return _audit(row, {
        "record_id": row["record_id"],
        "exchange_partner_code": row["exchange_partner_code"],
        "consent_on_file": row["consent_on_file"],
        "external_demographics": dict(row["external_demographics"]),
        "external_score": num(row["external_score"]),
        "state": row["state"],
    })


def metric(row):
    return _audit(row, {
        "site_id": row["site_id"],
        "window_start_date": row["window_start_date"],
        "window_end_date": row["window_end_date"],
        "attribution_variant": row["attribution_variant"],
        "records_created": row["records_created"],
        "confirmed_duplicates": row["confirmed_duplicates"],
        "duplicate_rate_bps": row["duplicate_rate_bps"],
        "sample_size_sufficient": row["sample_size_sufficient"],
        "rule_set_version_label": row["rule_set_version_label"],
    }, event_record=True)
