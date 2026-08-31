"""Payload factories - one per entity, input fields only."""

from .constants import OBS_END, OBS_START

DEFAULTS = {
    "CLIENT_NAME": "Northwind",
    "REPORT_TYPE": "SOC_2_TYPE_2",
    "CATEGORIES": ["SECURITY"],
    "BOUNDARY_NARRATIVE": "The examined platform boundary.",
    "COMPONENT_NAME": "Core API",
    "CONTROL_TITLE": "Change approvals",
    "CRITERION_TITLE": "Control environment",
    "SERVICES_PROVIDED": "Managed hosting and backup",
}


def create_engagement_payload(**overrides) -> dict:
    payload = {
        "client_name": DEFAULTS["CLIENT_NAME"],
        "report_type": DEFAULTS["REPORT_TYPE"],
        "observation_period_start": OBS_START,
        "observation_period_end": OBS_END,
        "required_criteria_categories": list(DEFAULTS["CATEGORIES"]),
    }
    payload.update(overrides)
    return payload


def create_trust_criterion_payload(**overrides) -> dict:
    payload = {
        "criterion_code": "CC1.1",
        "category": "SECURITY",
        "title": DEFAULTS["CRITERION_TITLE"],
        "min_primary_controls": 1,
        "applies_to_report_types": ["SOC_2_TYPE_2"],
    }
    payload.update(overrides)
    return payload


def create_system_description_payload(engagement_id, expected_engagement_version, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "version_label": "v1",
        "boundary_narrative": DEFAULTS["BOUNDARY_NARRATIVE"],
        "expected_engagement_version": expected_engagement_version,
    }
    payload.update(overrides)
    return payload


def create_boundary_component_payload(system_description_id, **overrides) -> dict:
    payload = {
        "system_description_id": system_description_id,
        "component_type": "SOFTWARE",
        "name": DEFAULTS["COMPONENT_NAME"],
    }
    payload.update(overrides)
    return payload


def create_control_payload(engagement_id, control_ref, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "control_ref": control_ref,
        "title": DEFAULTS["CONTROL_TITLE"],
        "frequency": "MONTHLY",
    }
    payload.update(overrides)
    return payload


def create_criteria_mapping_payload(control_id, trust_criterion_id, **overrides) -> dict:
    payload = {
        "control_id": control_id,
        "trust_criterion_id": trust_criterion_id,
        "mapping_type": "PRIMARY",
    }
    payload.update(overrides)
    return payload


def create_evidence_request_payload(control_id, period_index=0, **overrides) -> dict:
    payload = {
        "control_id": control_id,
        "period_index": period_index,
        "period_start": OBS_START,
        "period_end": OBS_END,
    }
    payload.update(overrides)
    return payload


def create_gap_payload(engagement_id, **overrides) -> dict:
    payload = {"engagement_id": engagement_id, "severity": "MODERATE"}
    payload.update(overrides)
    return payload


def create_subservice_organization_payload(engagement_id, name, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "name": name,
        "services_provided": DEFAULTS["SERVICES_PROVIDED"],
        "coverage_start": OBS_START,
        "coverage_end": OBS_END,
    }
    payload.update(overrides)
    return payload


def create_cuec_payload(engagement_id, trust_criterion_id, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "trust_criterion_id": trust_criterion_id,
        "statement": "User entities must review their own access reports quarterly.",
        "deflection_topic": "user-access",
    }
    payload.update(overrides)
    return payload


def create_report_distribution_payload(engagement_id, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "recipient_name": "Acme Corp",
        "recipient_email": "soc@acme.example",
    }
    payload.update(overrides)
    return payload


def create_bridge_letter_payload(engagement_id, coverage_start, as_of_date, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "coverage_start": coverage_start,
        "as_of_date": as_of_date,
    }
    payload.update(overrides)
    return payload


def create_customer_questionnaire_payload(engagement_id, report_distribution_id, **overrides) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "report_distribution_id": report_distribution_id,
        "customer_name": "Acme Corp Security",
        "criteria_item_count": 4,
        "post_period_item_count": 3,
        "cuec_item_count": 5,
    }
    payload.update(overrides)
    return payload


def create_audit_sample_payload(control_id, expected_control_version, **overrides) -> dict:
    payload = {
        "control_id": control_id,
        "period_start": OBS_START,
        "period_end": OBS_END,
        "expected_control_version": expected_control_version,
    }
    payload.update(overrides)
    return payload
