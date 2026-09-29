"""Payload factories — one per record type, input fields only.

Money is always an integer number of cents in a `_cents` field and is sent as a
JSON number, never a string. Instants are full ISO 8601 UTC instants; plain
dates are `YYYY-MM-DD` strings, exactly as the PRD types them.
"""

from .constants import (
    ACUTE_FORMULA,
    CYCLE_CALENDAR,
    NORTH_HSA,
    SOUTH_HSA,
)


def health_service_area_payload(**overrides) -> dict:
    payload = dict(NORTH_HSA)
    payload.update(overrides)
    return payload


def south_health_service_area_payload(**overrides) -> dict:
    payload = dict(SOUTH_HSA)
    payload.update(overrides)
    return payload


def state_plan_formula_payload(**overrides) -> dict:
    payload = dict(ACUTE_FORMULA)
    payload.update(overrides)
    return payload


def hearing_room_payload(**overrides) -> dict:
    payload = {"name": "Board Room A", "seating_capacity": 120}
    payload.update(overrides)
    return payload


def applicant_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Northside Hospital",
        "organization_type": "HOSPITAL",
        "contact_email": "filings@northside.example",
    }
    payload.update(overrides)
    return payload


def lakeview_applicant_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Lakeview Medical",
        "organization_type": "HOSPITAL",
        "contact_email": "filings@lakeview.example",
    }
    payload.update(overrides)
    return payload


def batching_cycle_payload(hsa_id, formula_id, **overrides) -> dict:
    payload = {
        "hsa_id": hsa_id,
        "formula_id": formula_id,
        "service_type": "ACUTE_CARE_BEDS",
    }
    payload.update(CYCLE_CALENDAR)
    payload.update(overrides)
    return payload


def letter_of_intent_payload(applicant_id, hsa_id, batching_cycle_id, **overrides):
    payload = {
        "applicant_id": applicant_id,
        "hsa_id": hsa_id,
        "batching_cycle_id": batching_cycle_id,
        "service_type": "ACUTE_CARE_BEDS",
        "project_description": "12-bed acute care expansion",
        "capital_cost_cents": 800_000_000,
        "bed_delta": 12,
    }
    payload.update(overrides)
    return payload


def application_payload(loi_id, **overrides) -> dict:
    payload = {
        "loi_id": loi_id,
        "requested_bed_count": 12,
        "projected_capital_cost_cents": 800_000_000,
        "narrative": "Northside 12-bed acute care application",
        "partial_award_acceptable": False,
    }
    payload.update(overrides)
    return payload


def deficiency_notice_payload(**overrides) -> dict:
    payload = {
        "deficiency_items": [
            "Audited financial statements missing",
            "Site control documentation missing",
        ],
        "cure_deadline_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def cure_payload(**overrides) -> dict:
    payload = {"cure_response": "Audited statements attached"}
    payload.update(overrides)
    return payload


def public_comment_payload(**overrides) -> dict:
    payload = {
        "commenter_display_name": "Concerned Neighbour",
        "stance": "OPPOSE",
        "body": "The proposed wing duplicates capacity two miles away.",
    }
    payload.update(overrides)
    return payload


def intervention_payload(application_id, affected_party_applicant_id, **overrides):
    payload = {
        "application_id": application_id,
        "affected_party_applicant_id": affected_party_applicant_id,
        "grounds": "Our service area overlaps the proposed project materially",
    }
    payload.update(overrides)
    return payload


def public_hearing_payload(batching_cycle_id, hearing_room_id, **overrides) -> dict:
    payload = {
        "batching_cycle_id": batching_cycle_id,
        "hearing_room_id": hearing_room_id,
        "scheduled_start_at": "2026-08-26T09:00:00Z",
        "scheduled_end_at": "2026-08-26T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def score_sheet_payload(application_id, expected_application_version, scores=None,
                        **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "need_conformity_score": 88,
        "financial_feasibility_score": 75,
        "cost_containment_score": 70,
        "access_underserved_score": 90,
        "quality_record_score": 60,
        "expected_application_version": expected_application_version,
    }
    if scores:
        payload.update(scores)
    payload.update(overrides)
    return payload


def certificate_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "approved_expenditure_limit_cents": 1_000_000_000,
        "implementation_milestone_date": "2027-06-30",
        "expenditure_basis": "CASH",
        "conditions": ["Quarterly progress reporting"],
        "required_completion_pct_at_milestone": 25,
    }
    payload.update(overrides)
    return payload


def progress_report_payload(certificate_id, expected_certificate_version,
                            **overrides) -> dict:
    payload = {
        "certificate_id": certificate_id,
        "period_end_date": "2026-12-31",
        "disbursed_cents": 200_000_000,
        "obligated_cents": 50_000_000,
        "physical_completion_pct": 10.00,
        "condition_attestations": ["Quarterly progress reporting"],
        "expected_certificate_version": expected_certificate_version,
    }
    payload.update(overrides)
    return payload


def appeal_payload(application_id, appellant_applicant_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "appellant_applicant_id": appellant_applicant_id,
        "grounds": "The comparative ranking misweighted the need finding",
    }
    payload.update(overrides)
    return payload
