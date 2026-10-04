"""Payload factories — one per resource, input fields only.

Each factory emits the smallest body the contract accepts: required fields are
always present, optional fields appear only when a caller supplies them (or an
explicit override), so a test that wants to exercise a server-side default
simply omits the argument. ``**overrides`` is applied last and can therefore
introduce a value outside the declared vocabulary or an extra field.
"""

from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


def _finish(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload.update(overrides)
    return payload


# ── Clock ──────────────────────────────────────────────────────────────────

def clock_payload(current_utc: str = TEST_DEFAULTS["CLOCK"]) -> Dict[str, Any]:
    return {"current_utc": current_utc}


def transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _finish({"action": action}, overrides)


# ── Client ─────────────────────────────────────────────────────────────────

def client_payload(
    legal_name: str = "Test Client",
    industry_code: str = "TECH",
    jurisdiction_country: str = "US",
    is_public_interest_entity: Optional[bool] = None,
    parent_client_id: Optional[str] = None,
    naf_annual_cap_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "industry_code": industry_code,
        "jurisdiction_country": jurisdiction_country,
    }
    if is_public_interest_entity is not None:
        payload["is_public_interest_entity"] = is_public_interest_entity
    if parent_client_id is not None:
        payload["parent_client_id"] = parent_client_id
    if naf_annual_cap_cents is not None:
        payload["naf_annual_cap_cents"] = naf_annual_cap_cents
    return _finish(payload, overrides)


# ── Engagement ─────────────────────────────────────────────────────────────

def engagement_payload(
    client_id: str,
    engagement_type: str = "STATUTORY_AUDIT",
    fiscal_year_end: str = TEST_DEFAULTS["ENGAGEMENT_FISCAL_YEAR_END"],
    is_multinational: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "engagement_type": engagement_type,
        "fiscal_year_end": fiscal_year_end,
    }
    if is_multinational is not None:
        payload["is_multinational"] = is_multinational
    return _finish(payload, overrides)


# ── Client acceptance and integrity evidence ───────────────────────────────

def acceptance_payload(
    client_id: str,
    engagement_id: str,
    industry_expertise_required: str = "TECH",
    proposed_by: str = TEST_DEFAULTS["PROPOSED_BY"],
    industry_expertise_confirmed: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "engagement_id": engagement_id,
        "proposed_by": proposed_by,
        "industry_expertise_required": industry_expertise_required,
    }
    if industry_expertise_confirmed is not None:
        payload["industry_expertise_confirmed"] = industry_expertise_confirmed
    return _finish(payload, overrides)


def integrity_payload(
    source_type: str = "LITIGATION",
    severity: str = "MEDIUM",
    score_impact: int = 10,
    assessed_on: str = TEST_DEFAULTS["CLOCK"],
    resolved: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "source_type": source_type,
        "severity": severity,
        "score_impact": score_impact,
        "assessed_on": assessed_on,
    }
    if resolved is not None:
        payload["resolved"] = resolved
    return _finish(payload, overrides)


def decision_payload(decision: str, decision_notes: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision_notes is not None:
        payload["decision_notes"] = decision_notes
    return _finish(payload, overrides)


# ── Affiliate ──────────────────────────────────────────────────────────────

def affiliate_payload(
    firm_name: str = "Deloitte & Touche LLP",
    country_code: str = "US",
    network_tier: str = "MEMBER_FIRM",
    independence_framework: str = "SEC_RESTRICTED",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "firm_name": firm_name,
        "country_code": country_code,
        "network_tier": network_tier,
        "independence_framework": independence_framework,
    }
    return _finish(payload, overrides)


# ── Professional ───────────────────────────────────────────────────────────

def professional_payload(
    full_name: str = "Test Professional",
    grade: str = "PARTNER",
    home_affiliate_id: str = "",
    rotation_role_class: str = "LEAD_PARTNER",
    max_workload_points: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "grade": grade,
        "home_affiliate_id": home_affiliate_id,
        "rotation_role_class": rotation_role_class,
    }
    if max_workload_points is not None:
        payload["max_workload_points"] = max_workload_points
    return _finish(payload, overrides)


# ── Engagement role assignment ─────────────────────────────────────────────

def assignment_payload(
    engagement_id: str,
    professional_id: str,
    role: str,
    started_on: str,
    scheduled_end_on: str,
    expected_engagement_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "engagement_id": engagement_id,
        "professional_id": professional_id,
        "role": role,
        "started_on": started_on,
        "scheduled_end_on": scheduled_end_on,
        "expected_engagement_version": expected_engagement_version,
    }
    return _finish(payload, overrides)


# ── Independence finding ───────────────────────────────────────────────────

def finding_payload(
    professional_id: str,
    engagement_id: str,
    expected_engagement_version: int,
    origin: str = "DECLARATION",
    origin_ref_id: str = "decl-1",
    finding_type: str = "FINANCIAL_INTEREST",
    severity: str = "HIGH",
    discovered_on: str = TEST_DEFAULTS["CLOCK"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "professional_id": professional_id,
        "engagement_id": engagement_id,
        "origin": origin,
        "origin_ref_id": origin_ref_id,
        "finding_type": finding_type,
        "severity": severity,
        "discovered_on": discovered_on,
        "expected_engagement_version": expected_engagement_version,
    }
    return _finish(payload, overrides)


# ── Independence threat ────────────────────────────────────────────────────

def financial_interest_payload(
    professional_id: str,
    client_id: str,
    instrument_type: str = "EQUITY",
    value_cents: int = 0,
    effective_on: str = TEST_DEFAULTS["CLOCK"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "professional_id": professional_id,
        "client_id": client_id,
        "threat_type": "FINANCIAL_INTEREST",
        "instrument_type": instrument_type,
        "value_cents": value_cents,
        "effective_on": effective_on,
    }
    return _finish(payload, overrides)


def employment_relationship_payload(
    professional_id: str,
    client_id: str,
    relationship_type: str = "FORMER_FIRM_PROFESSIONAL_JOINED_CLIENT",
    effective_on: str = TEST_DEFAULTS["CLOCK"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "professional_id": professional_id,
        "client_id": client_id,
        "threat_type": "EMPLOYMENT_RELATIONSHIP",
        "relationship_type": relationship_type,
        "value_cents": 0,
        "effective_on": effective_on,
    }
    return _finish(payload, overrides)


# ── Non-audit service ──────────────────────────────────────────────────────

def service_payload(
    client_id: str,
    service_category: str = "TAX_ADVISORY",
    fee_cents: int = 100000,
    engagement_id: Optional[str] = None,
    committee_resolution_ref: Optional[str] = None,
    approval_expires_on: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "service_category": service_category,
        "fee_cents": fee_cents,
    }
    if engagement_id is not None:
        payload["engagement_id"] = engagement_id
    if committee_resolution_ref is not None:
        payload["committee_resolution_ref"] = committee_resolution_ref
    if approval_expires_on is not None:
        payload["approval_expires_on"] = approval_expires_on
    return _finish(payload, overrides)


# ── Affiliate attestation ──────────────────────────────────────────────────

def attestation_payload(
    affiliate_id: str,
    engagement_id: str,
    breach_count: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "affiliate_id": affiliate_id,
        "engagement_id": engagement_id,
    }
    if breach_count is not None:
        payload["breach_count"] = breach_count
    return _finish(payload, overrides)


# ── Quality review ─────────────────────────────────────────────────────────

def review_payload(
    engagement_id: str,
    reviewer_id: str,
    review_type: str = "ENGAGEMENT_QUALITY_REVIEW",
    received_on: str = TEST_DEFAULTS["CLOCK"],
    due_on: str = "2026-11-01T00:00:00Z",
    inspection_body: Optional[str] = None,
    deficiency_count: Optional[int] = None,
    remediation_plan_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "engagement_id": engagement_id,
        "reviewer_id": reviewer_id,
        "review_type": review_type,
        "received_on": received_on,
        "due_on": due_on,
    }
    if inspection_body is not None:
        payload["inspection_body"] = inspection_body
    if deficiency_count is not None:
        payload["deficiency_count"] = deficiency_count
    if remediation_plan_ref is not None:
        payload["remediation_plan_ref"] = remediation_plan_ref
    return _finish(payload, overrides)
