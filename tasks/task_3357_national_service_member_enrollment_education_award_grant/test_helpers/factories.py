"""Payload factories — one per endpoint input shape, input fields only."""
from .constants import (
    CLOCK_AFTER_CLOSE_ISO,
    CLOCK_START_ISO,
    DEFAULT_SERVICE_END,
    DEFAULT_SERVICE_START,
)


def set_clock_payload(to_iso8601=CLOCK_START_ISO):
    return {"to_iso8601": to_iso8601}


def create_organization_payload(
    legal_name="River City Service Corps", ein="12-3456789", org_type="NONPROFIT", **overrides
):
    payload = {"legal_name": legal_name, "ein": ein, "org_type": org_type}
    payload.update(overrides)
    return payload


def create_competition_payload(
    title="FY2026 Service Corps",
    fiscal_year=2026,
    application_open_at=CLOCK_START_ISO,
    application_close_at="2026-10-01T00:00:00Z",
    **overrides,
):
    payload = {
        "title": title,
        "fiscal_year": fiscal_year,
        "application_open_at": application_open_at,
        "application_close_at": application_close_at,
    }
    payload.update(overrides)
    return payload


def slot_request(term_category="FULL_TIME", count=1):
    return {"term_category": term_category, "count": count}


def match_line(category="CASH", amount_cents=1000000):
    return {"category": category, "amount_cents": amount_cents}


def create_application_payload(
    organization_id,
    federal_share_requested_cents=4000000,
    slot_requests=None,
    match_lines=None,
    **overrides,
):
    payload = {
        "organization_id": organization_id,
        "federal_share_requested_cents": federal_share_requested_cents,
        "slot_requests": (
            slot_requests if slot_requests is not None else [slot_request("FULL_TIME", 2)]
        ),
        "match_lines": match_lines if match_lines is not None else [match_line("CASH", 1000000)],
    }
    payload.update(overrides)
    return payload


def award_application_payload(federal_share_awarded_cents=4000000):
    return {"federal_share_awarded_cents": federal_share_awarded_cents}


def reject_application_payload(reason="Insufficient community need"):
    return {"reason": reason}


def request_clarification_payload(question="What is the recruitment plan?"):
    return {"question": question}


def respond_clarification_payload(response="Local college pipeline."):
    return {"response": response}


def suspend_award_payload(reason="Compliance hold"):
    return {"reason": reason}


def create_match_report_payload(reporting_period_label="P1", lines=None):
    return {
        "reporting_period_label": reporting_period_label,
        "lines": lines if lines is not None else [match_line("CASH", 960000)],
    }


def register_member_payload(
    full_name="Alex Rivera",
    date_of_birth="2000-01-01",
    citizenship_status="US_CITIZEN",
    **overrides,
):
    payload = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "citizenship_status": citizenship_status,
    }
    payload.update(overrides)
    return payload


def record_component_result_payload(component="NSOPR", result="CLEAR"):
    return {"component": component, "result": result}


def create_enrollment_payload(
    member_id,
    term_category="FULL_TIME",
    service_start_date=DEFAULT_SERVICE_START,
    service_end_date=DEFAULT_SERVICE_END,
    expected_award_version=1,
    **overrides,
):
    payload = {
        "member_id": member_id,
        "term_category": term_category,
        "service_start_date": service_start_date,
        "service_end_date": service_end_date,
        "expected_award_version": expected_award_version,
    }
    payload.update(overrides)
    return payload


def suspend_enrollment_payload(reason="Conduct investigation"):
    return {"reason": reason}


def exit_enrollment_payload(exit_reason="SUCCESSFUL"):
    return {"exit_reason": exit_reason}


def create_hour_entry_payload(
    service_date="2026-10-16", minutes=480, activity_code="DIRECT_SERVICE", **overrides
):
    payload = {
        "service_date": service_date,
        "minutes": minutes,
        "activity_code": activity_code,
    }
    payload.update(overrides)
    return payload


def reject_hour_entry_payload(reason="Insufficient documentation"):
    return {"reason": reason}


def create_allowance_payment_payload(amount_cents=100000, note=None):
    payload = {"amount_cents": amount_cents}
    if note is not None:
        payload["note"] = note
    return payload


def create_award_use_payload(
    use_type,
    amount_cents,
    expected_education_award_version,
    institution_title_iv=None,
):
    payload = {
        "use_type": use_type,
        "amount_cents": amount_cents,
        "expected_education_award_version": expected_education_award_version,
    }
    if institution_title_iv is not None:
        payload["institution_title_iv"] = institution_title_iv
    return payload


def decide_use_payload(decision="APPROVE", note=None):
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def rescind_use_payload(reason="Duplicate disbursement"):
    return {"reason": reason}


def create_visit_payload(visit_type="SITE_VISIT", scheduled_date="2026-11-02"):
    return {"visit_type": visit_type, "scheduled_date": scheduled_date}


def create_finding_payload(severity="HIGH", description="Member files incomplete"):
    return {"severity": severity, "description": description}


def assign_corrective_action_payload(requirement="Complete the member files", due_days=14):
    return {"requirement": requirement, "due_days": due_days}


def submit_evidence_payload(evidence_note="Files completed 10/17"):
    return {"evidence_note": evidence_note}


def decide_finding_payload(decision="APPROVE", note=None):
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


def create_grievance_payload(description="Disputed conduct finding"):
    return {"description": description}


def resolve_grievance_payload(outcome="DISMISSED"):
    return {"outcome": outcome}


def create_measure_payload(measure_code="MSY_OUTPUT", target_value=10, unit="beneficiaries"):
    return {"measure_code": measure_code, "target_value": target_value, "unit": unit}


def submit_report_payload(
    period_start="2026-10-01", period_end="2026-12-31", actual_value=5
):
    return {
        "period_start": period_start,
        "period_end": period_end,
        "actual_value": actual_value,
    }


def review_measure_payload(decision="ACCEPT", comment=None):
    payload = {"decision": decision}
    if comment is not None:
        payload["comment"] = comment
    return payload
