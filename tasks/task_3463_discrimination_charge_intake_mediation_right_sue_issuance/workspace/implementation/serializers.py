"""Entity serializers.

Each serializer enumerates its fields explicitly (internal bookkeeping keys
such as ``_seq`` never leak). Computed-on-read fields are derived here; lazy
state transitions are applied by the caller before serialization (some carry
side effects, so serializers stay pure).
"""

from datetime import datetime

from helpers import iso_date, iso_ts, today


def _ts(value):
    if value is None:
        return None
    return iso_ts(value)


def _dt_input(value):
    """Client-supplied full datetimes echo back at millisecond precision."""
    if value is None:
        return None
    return iso_ts(value)


def _d(value):
    if value is None:
        return None
    return iso_date(value)


def serialize_complainant(row):
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_employer(row):
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "state_code": row["state_code"],
        "employee_count_current": row["employee_count_current"],
        "size_band": row["size_band"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_deferral_agency(row):
    return {
        "id": row["id"],
        "state_code": row["state_code"],
        "agency_name": row["agency_name"],
        "filing_deadline_days": row["filing_deadline_days"],
        "work_sharing_policy": row["work_sharing_policy"],
        "covers_age": row["covers_age"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def charge_days_elapsed(charge):
    """Whole days between received_date and the current logical clock."""
    received = charge["received_date"]
    if isinstance(received, datetime):
        received = received.date()
    return (today() - received).days


def serialize_charge(row):
    return {
        "id": row["id"],
        "complainant_id": row["complainant_id"],
        "employer_id": row["employer_id"],
        "deferral_agency_id": row["deferral_agency_id"],
        "basis_codes": list(row["basis_codes"]),
        "covered_bases": list(row["covered_bases"]),
        "incident_date": _d(row["incident_date"]),
        "harm_description": row["harm_description"],
        "employee_count_at_incident": row["employee_count_at_incident"],
        "received_date": _d(row["received_date"]),
        "case_status": row["case_status"],
        "disclosure_hold": row["disclosure_hold"],
        "jurisdiction_outcome": row["jurisdiction_outcome"],
        "filing_deadline_date": _d(row["filing_deadline_date"]),
        "investigation_owner": row["investigation_owner"],
        "dual_filed": row["dual_filed"],
        "investigation_case_id": row["investigation_case_id"],
        "priority_escalated": row["priority_escalated"],
        "settled_amount_cents": row["settled_amount_cents"],
        "settled_via": row["settled_via"],
        "settled_at": _ts(row["settled_at"]),
        "systemic_case_id": row["systemic_case_id"],
        "days_elapsed_since_filing": charge_days_elapsed(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_mediation_case(row):
    return {
        "id": row["id"],
        "charge_id": row["charge_id"],
        "round_number": row["round_number"],
        "complainant_response": row["complainant_response"],
        "respondent_response": row["respondent_response"],
        "status": row["status"],
        "settlement_amount_cents": row["settlement_amount_cents"],
        "concluded_at": _ts(row["concluded_at"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_mediation_session(row):
    return {
        "id": row["id"],
        "mediation_case_id": row["mediation_case_id"],
        "mediator_user_id": row["mediator_user_id"],
        "scheduled_start": _dt_input(row["scheduled_start"]),
        "scheduled_end": _dt_input(row["scheduled_end"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_investigation_case(row):
    return {
        "id": row["id"],
        "charge_id": row["charge_id"],
        "assigned_investigator_id": row["assigned_investigator_id"],
        "status": row["status"],
        "open_request_count": row["open_request_count"],
        "overdue_request_count": row["overdue_request_count"],
        "priority_score": row["priority_score"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_evidence_request(row):
    return {
        "id": row["id"],
        "investigation_case_id": row["investigation_case_id"],
        "request_type": row["request_type"],
        "issued_date": _d(row["issued_date"]),
        "due_date": _d(row["due_date"]),
        "status": row["status"],
        "response_text": row["response_text"],
        "responded_late": row["responded_late"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_witness_interview(row):
    return {
        "id": row["id"],
        "investigation_case_id": row["investigation_case_id"],
        "investigator_user_id": row["investigator_user_id"],
        "witness_name": row["witness_name"],
        "interview_start": _dt_input(row["interview_start"]),
        "interview_end": _dt_input(row["interview_end"]),
        "summary": row["summary"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_determination(row):
    return {
        "id": row["id"],
        "investigation_case_id": row["investigation_case_id"],
        "outcome": row["outcome"],
        "rationale": row["rationale"],
        "back_pay_cents": row["back_pay_cents"],
        "front_pay_cents": row["front_pay_cents"],
        "compensatory_damages_cents": row["compensatory_damages_cents"],
        "punitive_damages_cents": row["punitive_damages_cents"],
        "harm_start_date": _d(row["harm_start_date"]),
        "status": row["status"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "return_reason": row["return_reason"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_conciliation_process(row):
    return {
        "id": row["id"],
        "charge_id": row["charge_id"],
        "origin_determination_id": row["origin_determination_id"],
        "status": row["status"],
        "current_offer_cents": row["current_offer_cents"],
        "last_offer_by": row["last_offer_by"],
        "rounds_count": row["rounds_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_remedy_package(row):
    return {
        "id": row["id"],
        "conciliation_process_id": row["conciliation_process_id"],
        "valuation_variant": row["valuation_variant"],
        "back_pay_cents": row["back_pay_cents"],
        "front_pay_cents": row["front_pay_cents"],
        "compensatory_damages_cents": row["compensatory_damages_cents"],
        "punitive_damages_cents": row["punitive_damages_cents"],
        "harm_start_date": _d(row["harm_start_date"]),
        "band_used": row["band_used"],
        "projection_date": _d(row["projection_date"]),
        "interest_days": row["interest_days"],
        "back_pay_interest_cents": row["back_pay_interest_cents"],
        "front_pay_interest_cents": row["front_pay_interest_cents"],
        "capped_nonpecuniary_cents": row["capped_nonpecuniary_cents"],
        "total_cents": row["total_cents"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_right_to_sue_notice(row):
    return {
        "id": row["id"],
        "charge_id": row["charge_id"],
        "issuance_basis": row["issuance_basis"],
        "requested_by_role": row["requested_by_role"],
        "issued_date": _d(row["issued_date"]),
        "court_filing_deadline": _d(row["court_filing_deadline"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_systemic_case(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "basis_focus": list(row["basis_focus"]),
        "commissioner_user_id": row["commissioner_user_id"],
        "status": row["status"],
        "linked_charge_count": row["linked_charge_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def serialize_disclosure_record(row):
    # Append-only audit row: no updated_at, no version (PRD section 2.5).
    return {
        "id": row["id"],
        "charge_id": row["charge_id"],
        "accessor_role": row["accessor_role"],
        "accessor_user_id": row["accessor_user_id"],
        "legal_basis": row["legal_basis"],
        "target_description": row["target_description"],
        "disclosed_at": _ts(row["disclosed_at"]),
        "created_at": row["created_at"],
    }
