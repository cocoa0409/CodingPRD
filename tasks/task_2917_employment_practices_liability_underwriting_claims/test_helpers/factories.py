"""Request-payload builders.

Every money field is emitted as a JSON number of whole cents and every instant
as an ISO-8601 UTC string with three fractional digits, which is the form the
API declares.  Each builder accepts keyword overrides so a test can move one
field without restating the whole payload.
"""

from typing import Any, Dict, List, Optional

from . import types as T


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(base)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
JURISDICTION_PRESETS: Dict[str, Dict[str, Any]] = {
    "CA": {
        "code": "CA",
        "name": "California",
        "hazard_tier": T.HAZARD_TIER_4,
        "admin_agency_name": "California Civil Rights Department",
        "pre_suit_window_days": 180,
        "wage_hour_multiplier": 1.60,
        "class_action_propensity_pct": 42.00,
        "pre_suit_mediation_required": True,
    },
    "TX": {
        "code": "TX",
        "name": "Texas",
        "hazard_tier": T.HAZARD_TIER_2,
        "admin_agency_name": "Texas Workforce Commission Civil Rights Division",
        "pre_suit_window_days": 120,
        "wage_hour_multiplier": 1.10,
        "class_action_propensity_pct": 18.00,
        "pre_suit_mediation_required": False,
    },
    "NY": {
        "code": "NY",
        "name": "New York",
        "hazard_tier": T.HAZARD_TIER_3,
        "admin_agency_name": "New York State Division of Human Rights",
        "pre_suit_window_days": 90,
        "wage_hour_multiplier": 1.35,
        "class_action_propensity_pct": 30.00,
        "pre_suit_mediation_required": False,
    },
    "AZ": {
        "code": "AZ",
        "name": "Arizona",
        "hazard_tier": T.HAZARD_TIER_1,
        "admin_agency_name": "Arizona Civil Rights Division",
        "pre_suit_window_days": 30,
        "wage_hour_multiplier": 1.00,
        "class_action_propensity_pct": 8.00,
        "pre_suit_mediation_required": False,
    },
}


def jurisdiction(code: str = "CA", **overrides: Any) -> Dict[str, Any]:
    base = JURISDICTION_PRESETS.get(code)
    if base is None:
        base = _merge(JURISDICTION_PRESETS["CA"], {"code": code, "name": f"Jurisdiction {code}"})
    return _merge(base, overrides)


def rate_plan(
    name: str = "EPLI Standard 2026",
    base_rate_per_employee_cents: int = 41750,
    min_premium_cents: int = 750000,
    wage_hour_sublimit_pct: float = 0.25,
    third_party_sublimit_pct: float = 0.40,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "base_rate_per_employee_cents": base_rate_per_employee_cents,
            "min_premium_cents": min_premium_cents,
            "wage_hour_sublimit_pct": wage_hour_sublimit_pct,
            "third_party_sublimit_pct": third_party_sublimit_pct,
        },
        overrides,
    )


def panel_firm(
    name: str = "Harker & Lowe LLP",
    tier: str = T.TIER_REGIONAL,
    jurisdiction_codes: Optional[List[str]] = None,
    partner_rate_cents_per_hour: int = 72000,
    associate_rate_cents_per_hour: int = 42000,
    paralegal_rate_cents_per_hour: int = 18000,
    capacity_open_matters: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "tier": tier,
            "jurisdiction_codes": list(jurisdiction_codes or ["CA"]),
            "partner_rate_cents_per_hour": partner_rate_cents_per_hour,
            "associate_rate_cents_per_hour": associate_rate_cents_per_hour,
            "paralegal_rate_cents_per_hour": paralegal_rate_cents_per_hour,
            "capacity_open_matters": capacity_open_matters,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Applicant and risk-management services
# ---------------------------------------------------------------------------
def applicant(
    legal_name: str = "Northgate Retail Group",
    total_headcount: int = 400,
    prior_year_separations: int = 96,
    jurisdiction_headcounts: Optional[List[Dict[str, Any]]] = None,
    primary_jurisdiction_code: str = "CA",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": legal_name,
            "total_headcount": total_headcount,
            "prior_year_separations": prior_year_separations,
            "jurisdiction_headcounts": list(
                jurisdiction_headcounts
                or [{"code": "CA", "headcount": 262}, {"code": "TX", "headcount": 138}]
            ),
            "primary_jurisdiction_code": primary_jurisdiction_code,
        },
        overrides,
    )


def risk_service(
    service_type: str = T.SERVICE_HOTLINE,
    credit_pct: float = 0.08,
    effective_from: str = "2026-07-01T00:00:00.000Z",
    effective_to: str = "2027-07-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "service_type": service_type,
            "credit_pct": credit_pct,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Underwriting
# ---------------------------------------------------------------------------
def assessment(
    applicant_id: str,
    rate_plan_id: str,
    expected_applicant_version: int,
    requested_aggregate_limit_cents: int = 200000000,
    requested_retention_cents: int = 5000000,
    third_party_coverage_requested: Optional[bool] = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "applicant_id": applicant_id,
        "rate_plan_id": rate_plan_id,
        "requested_aggregate_limit_cents": requested_aggregate_limit_cents,
        "requested_retention_cents": requested_retention_cents,
        "expected_applicant_version": expected_applicant_version,
    }
    if third_party_coverage_requested is not None:
        payload["third_party_coverage_requested"] = third_party_coverage_requested
    return _merge(payload, overrides)


def policy(
    exposure_assessment_id: str,
    effective_from: str = "2026-08-01T00:00:00.000Z",
    effective_to: str = "2027-08-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "exposure_assessment_id": exposure_assessment_id,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
def claim(
    claim_type: str = T.CLAIM_TYPE_DISCRIMINATION,
    claimant_class: str = T.CLAIMANT_EMPLOYEE,
    notice_type: str = T.NOTICE_LAWSUIT,
    first_notice_at: str = "2026-08-01T00:00:00.000Z",
    alleged_damages_cents: int = 40000000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "claim_type": claim_type,
            "claimant_class": claimant_class,
            "notice_type": notice_type,
            "first_notice_at": first_notice_at,
            "alleged_damages_cents": alleged_damages_cents,
        },
        overrides,
    )


def coverage_decision(decision: str = T.DECISION_ACCEPT, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": decision}, overrides)


def group(
    policy_id: str,
    lead_claim_id: str,
    aggregation_basis: str = T.AGGREGATION_COMMON_POLICY_PRACTICE,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "policy_id": policy_id,
            "lead_claim_id": lead_claim_id,
            "aggregation_basis": aggregation_basis,
        },
        overrides,
    )


def group_attach(claim_id: str, expected_related_claim_group_version: int, **overrides: Any):
    return _merge(
        {
            "claim_id": claim_id,
            "expected_related_claim_group_version": expected_related_claim_group_version,
        },
        overrides,
    )


def pre_suit_offer(
    settlement_offer_cents: int = 2000000,
    offer_expires_at: str = "2026-09-01T00:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "offer_expires_at": offer_expires_at,
            "settlement_offer_cents": settlement_offer_cents,
        },
        overrides,
    )


def payment(
    amount_cents: int,
    expected_policy_version: int,
    payment_basis: str = T.PAYMENT_BASIS_SETTLEMENT,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "amount_cents": amount_cents,
            "payment_basis": payment_basis,
            "expected_policy_version": expected_policy_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Defense
# ---------------------------------------------------------------------------
def assignment(
    engagement_from: str = "2026-08-05T00:00:00.000Z",
    engagement_to: str = "2027-02-05T00:00:00.000Z",
    budget_cap_cents: int = 50000000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "engagement_from": engagement_from,
            "engagement_to": engagement_to,
            "budget_cap_cents": budget_cap_cents,
        },
        overrides,
    )


def invoice(
    period_start: str = "2026-08-05T00:00:00.000Z",
    period_end: str = "2026-09-05T00:00:00.000Z",
    partner_hours: Optional[float] = 10.0,
    associate_hours: Optional[float] = 20.0,
    paralegal_hours: Optional[float] = 5.0,
    block_billed_hours: Optional[float] = 0.0,
    expenses_cents: Optional[int] = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"period_start": period_start, "period_end": period_end}
    for key, value in (
        ("partner_hours", partner_hours),
        ("associate_hours", associate_hours),
        ("paralegal_hours", paralegal_hours),
        ("block_billed_hours", block_billed_hours),
        ("expenses_cents", expenses_cents),
    ):
        if value is not None:
            payload[key] = value
    return _merge(payload, overrides)


def invoice_dispute(
    dispute_note: str = "Rate reduction disputed; revised hours submitted.", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"dispute_note": dispute_note}, overrides)
