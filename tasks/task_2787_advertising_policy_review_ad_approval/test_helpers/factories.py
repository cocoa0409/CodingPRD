"""Payload factories - one per write endpoint, carrying only caller-supplied input.

PRD §2.6: "Numeric values are JSON numbers, never strings." Every numeric field
below is therefore emitted as an int or a float.
"""

from typing import Dict, List, Optional, Sequence

DEFAULTS = {
    "RULE_TITLE": "Test policy rule",
    "ADVERTISER_LEGAL_NAME": "Test Advertiser Ltd",
    "ADVERTISER_COUNTRY": "US",
    "INDUSTRY_CODE": "RETAIL",
    "REVIEWER_NAME": "Test Reviewer",
    "HEADLINE": "Test headline",
    "BODY_TEXT": "Test body copy for the creative under review.",
    "LANDING_PAGE_URL": "https://brand.example.com/offer",
    "DISPLAY_URL": "https://brand.example.com",
    "CLASSIFIER_VERSION": "clf-2026.08",
    "MATCHED_SNIPPET": "matched phrase",
    "LICENSE_NUMBER": "LIC-0001",
    "JUSTIFICATION": "The creative complies with the policy for the reasons attached.",
}


# --- Policy rules and country variations (PRD §3.1) -------------------------
def create_policy_rule_payload(
    code: str,
    category_class: str = "RESTRICTED",
    base_severity_weight: float = 6.00,
    **overrides,
) -> Dict:
    payload = {
        "code": code,
        "title": DEFAULTS["RULE_TITLE"],
        "category_class": category_class,
        "base_severity_weight": base_severity_weight,
    }
    payload.update(overrides)
    return payload


def create_country_override_payload(
    country_code: str, disposition: str = "RESTRICTED_CERT_REQUIRED", **overrides
) -> Dict:
    payload = {"country_code": country_code, "disposition": disposition}
    payload.update(overrides)
    return payload


# --- Advertisers, verifications and enforcement (PRD §3.2, §3.9) ------------
def create_advertiser_payload(**overrides) -> Dict:
    payload = {
        "legal_name": DEFAULTS["ADVERTISER_LEGAL_NAME"],
        "country_code": DEFAULTS["ADVERTISER_COUNTRY"],
        "industry_code": DEFAULTS["INDUSTRY_CODE"],
    }
    payload.update(overrides)
    return payload


def record_verification_payload(
    dimension: str, outcome: str, evidence_ref: Optional[str] = None
) -> Dict:
    payload = {"dimension": dimension, "outcome": outcome}
    if evidence_ref is not None:
        payload["evidence_ref"] = evidence_ref
    return payload


def create_enforcement_action_payload(
    action_type: str,
    expected_advertiser_version: int,
    trigger_reason: str = "Manual policy enforcement",
    **overrides,
) -> Dict:
    payload = {
        "action_type": action_type,
        "trigger_reason": trigger_reason,
        "expected_advertiser_version": expected_advertiser_version,
    }
    payload.update(overrides)
    return payload


# --- Reviewers (PRD §3.6) --------------------------------------------------
def create_reviewer_payload(
    queue_specialties: Optional[Sequence[str]] = None,
    country_authorizations: Optional[Sequence[str]] = None,
    **overrides,
) -> Dict:
    payload = {
        "display_name": DEFAULTS["REVIEWER_NAME"],
        "queue_specialties": list(queue_specialties or ["STANDARD"]),
        "country_authorizations": list(country_authorizations or ["US"]),
    }
    payload.update(overrides)
    return payload


def update_reviewer_payload(**fields) -> Dict:
    return dict(fields)


# --- Ad creatives (PRD §3.3) ----------------------------------------------
def create_ad_creative_payload(
    advertiser_id: str,
    declared_category_codes: Optional[Sequence[str]] = None,
    target_country_codes: Optional[Sequence[str]] = None,
    **overrides,
) -> Dict:
    payload = {
        "advertiser_id": advertiser_id,
        "headline": DEFAULTS["HEADLINE"],
        "body_text": DEFAULTS["BODY_TEXT"],
        "declared_category_codes": list(declared_category_codes or []),
        "target_country_codes": list(target_country_codes or ["US"]),
        "landing_page_url": DEFAULTS["LANDING_PAGE_URL"],
        "display_url": DEFAULTS["DISPLAY_URL"],
    }
    payload.update(overrides)
    return payload


def revise_ad_creative_payload(**fields) -> Dict:
    return dict(fields)


# --- Screening runs (PRD §3.4) --------------------------------------------
def classifier_decision_payload(
    policy_rule_id: str, confidence: float, matched_snippet: Optional[str] = None
) -> Dict:
    return {
        "policy_rule_id": policy_rule_id,
        "confidence": confidence,
        "matched_snippet": matched_snippet or DEFAULTS["MATCHED_SNIPPET"],
    }


def create_screening_run_payload(
    decisions: List[Dict],
    expected_ad_creative_version: int,
    classifier_version: Optional[str] = None,
    **overrides,
) -> Dict:
    payload = {
        "classifier_version": classifier_version or DEFAULTS["CLASSIFIER_VERSION"],
        "decisions": list(decisions),
        "expected_ad_creative_version": expected_ad_creative_version,
    }
    payload.update(overrides)
    return payload


# --- Destination checks (PRD §3.8) ---------------------------------------
def create_destination_check_payload(
    fetched_final_url: str,
    check_type: str = "INITIAL",
    user_agent_variant: str = "CRAWLER",
    fetched_content_category: str = "GENERAL",
    http_status: int = 200,
    **overrides,
) -> Dict:
    payload = {
        "check_type": check_type,
        "user_agent_variant": user_agent_variant,
        "fetched_final_url": fetched_final_url,
        "fetched_content_category": fetched_content_category,
        "http_status": http_status,
    }
    payload.update(overrides)
    return payload


# --- Certifications (PRD §3.5) -------------------------------------------
def create_certification_payload(
    advertiser_id: str,
    policy_rule_id: str,
    valid_from: str,
    valid_until: str,
    issuing_country_code: str = "US",
    license_number: Optional[str] = None,
    **overrides,
) -> Dict:
    payload = {
        "advertiser_id": advertiser_id,
        "policy_rule_id": policy_rule_id,
        "license_number": license_number or DEFAULTS["LICENSE_NUMBER"],
        "issuing_country_code": issuing_country_code,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    payload.update(overrides)
    return payload


def revoke_certification_payload(revocation_reason: str = "License withdrawn") -> Dict:
    return {"revocation_reason": revocation_reason}


# --- Review task decisions (PRD §3.7) ------------------------------------
def decide_review_task_payload(
    resolution: str,
    reason_codes: Optional[Sequence[str]] = None,
    limited_country_codes: Optional[Sequence[str]] = None,
    note: Optional[str] = None,
    **overrides,
) -> Dict:
    payload: Dict = {"resolution": resolution}
    if reason_codes is not None:
        payload["reason_codes"] = list(reason_codes)
    if limited_country_codes is not None:
        payload["limited_country_codes"] = list(limited_country_codes)
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


# --- Appeals (PRD §3.9) --------------------------------------------------
def create_appeal_payload(
    disapproval_notice_id: str,
    justification: Optional[str] = None,
    evidence_certification_id: Optional[str] = None,
    **overrides,
) -> Dict:
    payload = {
        "disapproval_notice_id": disapproval_notice_id,
        "justification": justification or DEFAULTS["JUSTIFICATION"],
    }
    if evidence_certification_id is not None:
        payload["evidence_certification_id"] = evidence_certification_id
    payload.update(overrides)
    return payload


def decide_appeal_payload(outcome: str, note: Optional[str] = None) -> Dict:
    payload = {"outcome": outcome}
    if note is not None:
        payload["note"] = note
    return payload


# --- The logical clock (PRD §2.8) ----------------------------------------
def set_clock_payload(to_iso8601: str) -> Dict:
    return {"to_iso8601": to_iso8601}
