"""Payload factories — one per resource, carrying only client-supplied fields."""

from .constants import TEST_DEFAULTS


def bargaining_unit_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["UNIT_NAME"],
        "local_number": TEST_DEFAULTS["LOCAL_NUMBER"],
        "contract_effective_date": TEST_DEFAULTS["CONTRACT_EFFECTIVE_DATE"],
        "contract_expiry_date": TEST_DEFAULTS["CONTRACT_EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def contract_clause_payload(**overrides) -> dict:
    payload = {
        "clause_number": "ART-12",
        "title": "Just Cause Discipline",
        "category": "DISCIPLINE",
    }
    payload.update(overrides)
    return payload


def employee_payload(bargaining_unit_id, **overrides) -> dict:
    payload = {
        "bargaining_unit_id": bargaining_unit_id,
        "full_name": "Ray Ortiz",
        "employee_number": "EMP-1",
        "hire_date": "2018-01-08T00:00:00Z",
        "seniority_date": "2018-01-08T00:00:00Z",
        "hourly_rate_cents": TEST_DEFAULTS["GRIEVANT_RATE_CENTS"],
        "classification": "PRODUCTION",
    }
    payload.update(overrides)
    return payload


def grievance_payload(bargaining_unit_id, grievant_id, respondent_supervisor_id,
                      clause_id, **overrides) -> dict:
    payload = {
        "bargaining_unit_id": bargaining_unit_id,
        "grievant_id": grievant_id,
        "respondent_supervisor_id": respondent_supervisor_id,
        "clause_id": clause_id,
        "statement": "Suspension without just cause",
        "incident_date": "2026-07-10T00:00:00Z",
        "discovery_date": "2026-07-12T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def grievance_step_payload(meeting_scheduled_at, **overrides) -> dict:
    payload = {"meeting_scheduled_at": meeting_scheduled_at}
    payload.update(overrides)
    return payload


def step_response_payload(disposition="DENIED", **overrides) -> dict:
    payload = {
        "disposition": disposition,
        "response_summary": f"Employer answer: {disposition}",
    }
    payload.update(overrides)
    return payload


def precedent_case_payload(clause_id, **overrides) -> dict:
    payload = {
        "clause_id": clause_id,
        "citation": "12 LA 445 (Kaplan 2023)",
        "decided_on": "2023-06-01T00:00:00Z",
        "outcome": "SUSTAINED",
        "monetary_value_cents": 200_000,
        "binding_scope": "UNIT_WIDE",
        "arbitrator_name": "M. Kaplan",
    }
    payload.update(overrides)
    return payload


def settlement_offer_payload(offering_party="EMPLOYER", monetary_cents=40_000,
                             **overrides) -> dict:
    payload = {
        "offering_party": offering_party,
        "monetary_cents": monetary_cents,
    }
    payload.update(overrides)
    return payload


def offer_response_payload(decision="ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def arbitrator_payload(full_name="Ruth Alvarez", per_diem_cents=250_000, **overrides) -> dict:
    payload = {
        "full_name": full_name,
        "panel_memberships": ["AAA"],
        "per_diem_cents": per_diem_cents,
        "cancellation_fee_cents": 40_000,
        "earliest_available_at": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def arbitration_demand_payload(expected_grievance_version, panel_source="AAA",
                               panel_size=3, **overrides) -> dict:
    payload = {
        "panel_source": panel_source,
        "panel_size": panel_size,
        "expected_grievance_version": expected_grievance_version,
    }
    payload.update(overrides)
    return payload


def hearing_payload(hearing_start_at, hearing_end_at, **overrides) -> dict:
    payload = {
        "hearing_start_at": hearing_start_at,
        "hearing_end_at": hearing_end_at,
    }
    payload.update(overrides)
    return payload


def prep_filing_payload(filing_type, **overrides) -> dict:
    payload = {"filing_type": filing_type}
    payload.update(overrides)
    return payload


def witness_assignment_payload(employee_id, slot_start_at, slot_end_at,
                               witness_type="FACT", called_by="UNION", **overrides) -> dict:
    payload = {
        "employee_id": employee_id,
        "witness_type": witness_type,
        "called_by": called_by,
        "slot_start_at": slot_start_at,
        "slot_end_at": slot_end_at,
    }
    payload.update(overrides)
    return payload


def award_payload(outcome="DENIED", **overrides) -> dict:
    payload = {"outcome": outcome}
    if outcome == "DENIED":
        payload["sustained_fraction_bps"] = 0
    elif outcome == "SUSTAINED":
        payload["sustained_fraction_bps"] = 10_000
    payload.update(overrides)
    return payload


def cost_entry_payload(category="FILING", amount_cents=12_500,
                       bearing_party="UNION", **overrides) -> dict:
    payload = {
        "category": category,
        "amount_cents": amount_cents,
        "bearing_party": bearing_party,
    }
    payload.update(overrides)
    return payload
