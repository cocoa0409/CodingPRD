"""Payload factories - one per resource, carrying only client-supplied fields.

Every literal here satisfies the PRD's format rules: `tier_code` is 3-32
uppercase/digit/underscore characters, `update_policy_url` starts with
`https://`, monetary amounts are JSON numbers of whole cents and every instant
is a full ISO 8601 UTC instant rather than a date-only literal.
"""
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS

# --------------------------------------------------------------------------
# Program configuration
# --------------------------------------------------------------------------
def create_program_tier_payload(**overrides) -> Dict[str, Any]:
    """A SELF_ATTESTATION tier by default."""
    payload = {
        "tier_code": "TIER_1",
        "required_route": "SELF_ATTESTATION",
        "label_validity_days": TEST_DEFAULTS["TIER_VALIDITY_DAYS"],
        "min_overall_score": TEST_DEFAULTS["MIN_OVERALL_SCORE"],
        "unverified_weight_factor": TEST_DEFAULTS["UNVERIFIED_WEIGHT_FACTOR"],
        "issuance_base_fee_cents": TEST_DEFAULTS["ISSUANCE_BASE_FEE_CENTS"],
        "max_deficiency_rounds": TEST_DEFAULTS["MAX_DEFICIENCY_ROUNDS"],
    }
    payload.update(overrides)
    return payload


def create_third_party_tier_payload(**overrides) -> Dict[str, Any]:
    """A THIRD_PARTY_TEST tier."""
    defaults = {
        "tier_code": "TIER_2",
        "required_route": "THIRD_PARTY_TEST",
        "label_validity_days": 730,
        "min_overall_score": 80.80,
        "unverified_weight_factor": 0.60,
        "issuance_base_fee_cents": 145000,
        "max_deficiency_rounds": 1,
    }
    defaults.update(overrides)
    return create_program_tier_payload(**defaults)


def create_device_category_payload(program_tier_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "category_code": "SMART_SPEAKER",
        "display_name": "Smart Speaker",
        "eligibility_status": "ELIGIBLE",
        "program_tier_id": program_tier_id,
        "min_support_period_days": TEST_DEFAULTS["MIN_SUPPORT_PERIOD_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_excluded_category_payload(program_tier_id: str, **overrides) -> Dict[str, Any]:
    defaults = {
        "category_code": "MEDICAL_IMPLANT",
        "display_name": "Regulated Medical Implant",
        "eligibility_status": "EXCLUDED",
        "exclusion_reason": "Regulated as a medical device outside the program's scope",
        "min_support_period_days": 730,
    }
    defaults.update(overrides)
    return create_device_category_payload(program_tier_id, **defaults)


# The five-criterion catalogue the design fixtures use: one lab-required and one
# self-declared criterion in AUTHENTICATION, one lab-required criterion in
# SOFTWARE_UPDATE, and one self-declared criterion in each remaining area.
STANDARD_CRITERIA: List[Dict[str, Any]] = [
    {
        "criterion_code": "AUTH-1",
        "practice_area": "AUTHENTICATION",
        "weight": 60,
        "requires_lab_verification": True,
        "criterion_text": "Unique per-device credentials or forced change at first use",
    },
    {
        "criterion_code": "AUTH-2",
        "practice_area": "AUTHENTICATION",
        "weight": 40,
        "requires_lab_verification": False,
        "criterion_text": "Brute-force resistant authentication with lockout",
    },
    {
        "criterion_code": "UPD-1",
        "practice_area": "SOFTWARE_UPDATE",
        "weight": 100,
        "requires_lab_verification": True,
        "criterion_text": "Signed automatic security updates for the declared support period",
    },
    {
        "criterion_code": "DATA-1",
        "practice_area": "DATA_PROTECTION",
        "weight": 100,
        "requires_lab_verification": False,
        "criterion_text": "Personal data encrypted in transit and at rest",
    },
    {
        "criterion_code": "VDP-1",
        "practice_area": "VULN_DISCLOSURE",
        "weight": 100,
        "requires_lab_verification": False,
        "criterion_text": "Published vulnerability disclosure policy with monitored contact",
    },
]


def create_security_criteria_payload(criteria: Optional[List[Dict]] = None) -> Dict[str, Any]:
    return {"criteria": [dict(c) for c in (criteria if criteria is not None else STANDARD_CRITERIA)]}


def criterion_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "criterion_code": "AUTH-9",
        "practice_area": "AUTHENTICATION",
        "weight": 50,
        "requires_lab_verification": False,
        "criterion_text": "Additional authentication practice",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Participants
# --------------------------------------------------------------------------
def create_manufacturer_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": "Northwind Devices LLC",
        "contact_email": "compliance@northwind.example",
        "enterprise_class": "SMALL",
        "annual_us_revenue_cents": TEST_DEFAULTS["SMALL_REVENUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_large_manufacturer_payload(**overrides) -> Dict[str, Any]:
    defaults = {
        "legal_name": "Orion Consumer Electronics Inc",
        "contact_email": "legal@orion.example",
        "enterprise_class": "LARGE",
        "annual_us_revenue_cents": TEST_DEFAULTS["LARGE_REVENUE_CENTS"],
    }
    defaults.update(overrides)
    return create_manufacturer_payload(**defaults)


def create_test_lab_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "lab_name": "Cascade Security Labs",
        "accreditation_status": "ACCREDITED",
        "total_bench_hours": TEST_DEFAULTS["TOTAL_BENCH_HOURS"],
        "concurrent_bench_capacity": TEST_DEFAULTS["CONCURRENT_BENCH_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_retailer_payload(**overrides) -> Dict[str, Any]:
    payload = {"retailer_name": "Beacon Electronics Retail"}
    payload.update(overrides)
    return payload


def education_ack_payload(**overrides) -> Dict[str, Any]:
    payload = {"education_program_version": "EDU-2026.1"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Products and spec changes
# --------------------------------------------------------------------------
def create_product_payload(manufacturer_id: str, device_category_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "manufacturer_id": manufacturer_id,
        "device_category_id": device_category_id,
        "model_name": "Northwind Speaker S1",
        "sku": "NW-SPK-S1",
        "firmware_version": "1.0.0",
        "declared_support_period_end": TEST_DEFAULTS["SUPPORT_PERIOD_END"],
        "update_policy_disclosed": True,
        "retail_units_shipped": 12000,
    }
    payload.update(overrides)
    return payload


def spec_change_payload(expected_product_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "expected_product_version": expected_product_version,
        "change_summary": "Firmware 1.1.0 hardens the authentication subsystem",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Assessments, responses and decisions
# --------------------------------------------------------------------------
def open_assessment_payload(expected_product_version: int, **overrides) -> Dict[str, Any]:
    payload = {"expected_product_version": expected_product_version}
    payload.update(overrides)
    return payload


def response_item(criterion_id: str, self_declared_conformant: bool = True, **overrides) -> Dict[str, Any]:
    item = {
        "criterion_id": criterion_id,
        "self_declared_conformant": self_declared_conformant,
        "evidence_ref": "EV-0001",
    }
    item.update(overrides)
    return item


def criterion_responses_payload(responses: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"responses": [dict(r) for r in responses]}


def decide_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload = {
        "decision": decision,
        "reviewer_note": f"Conformity review decision recorded as {decision}.",
    }
    payload.update(overrides)
    return payload


def resubmit_payload(responses: Optional[List[Dict]] = None, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "resubmission_note": "Revised evidence supplied for the deficient criteria.",
    }
    if responses is not None:
        payload["responses"] = [dict(r) for r in responses]
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Test engagements
# --------------------------------------------------------------------------
def create_test_engagement_payload(assessment_id: str, test_lab_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "assessment_id": assessment_id,
        "test_lab_id": test_lab_id,
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-03T00:00:00Z",
        "bench_hours": 48,
    }
    payload.update(overrides)
    return payload


def report_payload(failed_criterion_codes: Optional[List[str]] = None, **overrides) -> Dict[str, Any]:
    payload = {
        "failed_criterion_codes": list(failed_criterion_codes or []),
        "report_reference": "RPT-0001",
    }
    payload.update(overrides)
    return payload


def cancel_engagement_payload(**overrides) -> Dict[str, Any]:
    payload = {"cancellation_reason": "Sponsor withdrew the bench booking"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Label grants, registry entries, publication and renewal
# --------------------------------------------------------------------------
def create_label_grant_payload(product_id: str, assessment_id: str, **overrides) -> Dict[str, Any]:
    payload = {"product_id": product_id, "assessment_id": assessment_id}
    payload.update(overrides)
    return payload


def registry_entry_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "update_policy_url": "https://northwind.example/updates/spk-s1",
        "update_cadence": "AUTOMATIC",
        "vuln_disclosure_contact": "security@northwind.example",
    }
    payload.update(overrides)
    return payload


def publication_payload(publication_decision: str = "PUBLISHED", **overrides) -> Dict[str, Any]:
    payload = {
        "publication_decision": publication_decision,
        "publication_note": "Registry content reviewed.",
    }
    payload.update(overrides)
    return payload


def renewal_payload(assessment_id: str, expected_label_grant_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "assessment_id": assessment_id,
        "expected_label_grant_version": expected_label_grant_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Retailer display authorizations
# --------------------------------------------------------------------------
def create_display_authorization_payload(
    retailer_id: str, label_grant_id: str, display_from: str, display_until: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "retailer_id": retailer_id,
        "label_grant_id": label_grant_id,
        "channel": "IN_STORE",
        "display_from": display_from,
        "display_until": display_until,
    }
    payload.update(overrides)
    return payload


def withdraw_authorization_payload(**overrides) -> Dict[str, Any]:
    payload = {"withdrawal_reason": "Seasonal endcap retired"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Misuse enforcement
# --------------------------------------------------------------------------
def violation_line(retail_listing_ref: str, channel: str, unit_count: int) -> Dict[str, Any]:
    return {
        "retail_listing_ref": retail_listing_ref,
        "channel": channel,
        "unit_count": unit_count,
    }


def create_enforcement_case_payload(
    subject_manufacturer_id: str,
    reported_scannable_code: str,
    violation_type: str = "EXPIRED_LABEL_DISPLAY",
    violation_line_items: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subject_manufacturer_id": subject_manufacturer_id,
        "reported_scannable_code": reported_scannable_code,
        "violation_type": violation_type,
        "violation_line_items": [dict(l) for l in (violation_line_items or [
            violation_line("LST-ONLINE-01", "ONLINE", 7),
            violation_line("LST-STORE-01", "IN_STORE", 3),
        ])],
    }
    payload.update(overrides)
    return payload


def notice_payload(**overrides) -> Dict[str, Any]:
    payload = {"notice_reference": "NOT-2026-0001"}
    payload.update(overrides)
    return payload


def lab_referral_payload(test_lab_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "test_lab_id": test_lab_id,
        "referral_note": "Device shipped to the lab for evidentiary testing",
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(outcome: str, **overrides) -> Dict[str, Any]:
    payload = {
        "outcome": outcome,
        "adjudication_note": f"Case adjudicated {outcome} on the evidence of record.",
    }
    payload.update(overrides)
    return payload


def vacate_payload(**overrides) -> Dict[str, Any]:
    payload = {"vacate_reason": "Adjudication vacated on appeal"}
    payload.update(overrides)
    return payload


def penalty_payment_payload(**overrides) -> Dict[str, Any]:
    payload = {"payment_reference": "PAY-2026-0001"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Recognition surveys
# --------------------------------------------------------------------------
def create_recognition_survey_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "survey_period_label": "2026-H1",
        "survey_period_end": "2026-06-30T00:00:00Z",
        "respondents_count": 1000,
        "recognized_count": 400,
    }
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
