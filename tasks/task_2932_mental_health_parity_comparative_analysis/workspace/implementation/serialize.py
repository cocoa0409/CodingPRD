"""Resource serializers. Decimals are rendered as JSON numbers."""

from envelope import num
from store import clock_now, format_instant


def _common(row, data):
    data["id"] = row["id"]
    data["created_at"] = row["created_at"]
    data["updated_at"] = row["updated_at"]
    data["version"] = row["version"]
    return data


def administrator(row):
    return _common(row, {
        "legal_name": row["legal_name"],
        "contact_email": row["contact_email"],
        "contractual_production_days": row["contractual_production_days"],
        "outstanding_request_count": row["outstanding_request_count"],
        "late_request_count": row["late_request_count"],
        "breach_count": row["breach_count"],
        "regulator_reportable_late_count": row["regulator_reportable_late_count"],
        "cooperation_score": num(row["cooperation_score"]),
        "regulatory_basis_cooperation_score": num(row["regulatory_basis_cooperation_score"]),
        "cooperation_status": row["cooperation_status"],
    })


def plan_year(row):
    return _common(row, {
        "plan_name": row["plan_name"],
        "plan_year_label": row["plan_year_label"],
        "administrator_id": row["administrator_id"],
        "funding_arrangement": row["funding_arrangement"],
        "covered_participant_count": row["covered_participant_count"],
        "remediation_liability_cap_cents": row["remediation_liability_cap_cents"],
        "status": row["status"],
        "compliance_posture": row["compliance_posture"],
        "open_violation_count": row["open_violation_count"],
        "notified_violation_count": row["notified_violation_count"],
        "failing_parity_test_count": row["failing_parity_test_count"],
        "remediation_liability_cents": row["remediation_liability_cents"],
    })


def classification(row):
    return _common(row, {
        "plan_year_id": row["plan_year_id"],
        "benefit_category": row["benefit_category"],
        "network_tier": row["network_tier"],
        "sub_classification": row["sub_classification"],
        "measurement_period_start": row["measurement_period_start"],
        "measurement_period_end": row["measurement_period_end"],
        "mh_su_benefits_covered": row["mh_su_benefits_covered"],
    })


def treatment_limitation(row):
    return _common(row, {
        "classification_id": row["classification_id"],
        "limitation_type": row["limitation_type"],
        "benefit_side": row["benefit_side"],
        "level_value": num(row["level_value"]),
        "projected_plan_payments_cents": row["projected_plan_payments_cents"],
        "projected_claims_count": row["projected_claims_count"],
        "status": row["status"],
    })


def parity_test(row):
    return _common(row, {
        "classification_id": row["classification_id"],
        "limitation_type": row["limitation_type"],
        "basis": row["basis"],
        "advisory_only": row["advisory_only"],
        "total_ms_payments_cents": row["total_ms_payments_cents"],
        "subject_payments_cents": row["subject_payments_cents"],
        "substantially_all_ratio": num(row["substantially_all_ratio"]),
        "substantially_all_met": row["substantially_all_met"],
        "predominant_level": num(row["predominant_level"]),
        "mh_level_value": num(row["mh_level_value"]),
        "result": row["result"],
        "status": row["status"],
    })


def nqtl_item(row):
    return _common(row, {
        "plan_year_id": row["plan_year_id"],
        "classification_id": row["classification_id"],
        "nqtl_type": row["nqtl_type"],
        "applied_to": row["applied_to"],
        "description": row["description"],
        "stringency_in_operation_index": num(row["stringency_in_operation_index"]),
        "stringency_flag": row["stringency_flag"],
        "determination_recorded_by_user_id": row["determination_recorded_by_user_id"],
        "status": row["status"],
    })


def comparative_analysis(row):
    return _common(row, {
        "nqtl_item_id": row["nqtl_item_id"],
        "supersedes_analysis_id": row["supersedes_analysis_id"],
        "authored_by_user_id": row["authored_by_user_id"],
        "certified_by_user_id": row["certified_by_user_id"],
        "factor_count": row["factor_count"],
        "evidentiary_standard_count": row["evidentiary_standard_count"],
        "stringency_written_finding": row["stringency_written_finding"],
        "stringency_operation_finding": row["stringency_operation_finding"],
        "revision_round": row["revision_round"],
        "status": row["status"],
    })


def vendor_request(row):
    is_overdue = (clock_now() > row["due_at"]
                  and row["fulfillment_status"] != "FULFILLED")
    return _common(row, {
        "administrator_id": row["administrator_id"],
        "plan_year_id": row["plan_year_id"],
        "nqtl_item_id": row["nqtl_item_id"],
        "requested_item_count": row["requested_item_count"],
        "requested_submission_types": list(row["requested_submission_types"]),
        "issued_at": format_instant(row["issued_at"]),
        "due_at": format_instant(row["due_at"]),
        "regulatory_due_at": format_instant(row["regulatory_due_at"]),
        "validated_submission_count": row["validated_submission_count"],
        "is_overdue": is_overdue,
        "fulfillment_status": row["fulfillment_status"],
        "escalation_status": row["escalation_status"],
    })


def data_submission(row):
    return _common(row, {
        "vendor_request_id": row["vendor_request_id"],
        "classification_id": row["classification_id"],
        "submission_type": row["submission_type"],
        "mh_denials": row["mh_denials"],
        "mh_adjudicated_claims": row["mh_adjudicated_claims"],
        "ms_denials": row["ms_denials"],
        "ms_adjudicated_claims": row["ms_adjudicated_claims"],
        "mh_in_network_provider_pct": num(row["mh_in_network_provider_pct"]),
        "ms_in_network_provider_pct": num(row["ms_in_network_provider_pct"]),
        "benchmark_note": row["benchmark_note"],
        "mh_denial_rate": num(row["mh_denial_rate"]),
        "ms_denial_rate": num(row["ms_denial_rate"]),
        "disparity_ratio": num(row["disparity_ratio"]),
        "network_composition_gap": num(row["network_composition_gap"]),
        "as_applied_flag": row["as_applied_flag"],
        "rejection_reason": row["rejection_reason"],
        "status": row["status"],
    })


def corrective_action_plan(row):
    return _common(row, {
        "nqtl_item_id": row["nqtl_item_id"],
        "remedy_type": row["remedy_type"],
        "affected_claims_count": row["affected_claims_count"],
        "average_claim_cents": row["average_claim_cents"],
        "target_completion_date": row["target_completion_date"],
        "reprocessing_liability_cents": row["reprocessing_liability_cents"],
        "approved_by_user_id": row["approved_by_user_id"],
        "status": row["status"],
    })


def regulator_request(row):
    return _common(row, {
        "plan_year_id": row["plan_year_id"],
        "requested_nqtl_types": list(row["requested_nqtl_types"]),
        "request_reference": row["request_reference"],
        "opened_at": format_instant(row["opened_at"]),
        "response_due_at": format_instant(row["response_due_at"]),
        "requested_item_count": row["requested_item_count"],
        "covered_item_count": row["covered_item_count"],
        "completeness_score": num(row["completeness_score"]),
        "response_sufficient": row["response_sufficient"],
        "regulator_round": row["regulator_round"],
        "status": row["status"],
    })


def participant_notice(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "nqtl_item_id": row["nqtl_item_id"],
        "notice_type": row["notice_type"],
        "recipient_count": row["recipient_count"],
        "disclosure_summary": row["disclosure_summary"],
        "issued_at": row["issued_at"],
        "source": row["source"],
    }
