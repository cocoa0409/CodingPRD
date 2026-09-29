"""Payload factories — one per write surface, client-supplied fields only.

All monetary amounts are integer cents (numeric JSON, never strings); all
percentages are numeric with at most two decimal places.
"""

import copy
from typing import Any, Dict, List, Optional

from .constants import DEFAULT_TIER_BANDS, TEST_DEFAULTS


# ─── Members ──────────────────────────────────────────────────────────────────

def member_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": TEST_DEFAULTS["MEMBER_NAME"],
        "fte_count": TEST_DEFAULTS["FTE_COUNT"],
        "carnegie_class": TEST_DEFAULTS["CARNEGIE_CLASS"],
        "budget_ceiling_cents": TEST_DEFAULTS["BUDGET_CEILING_CENTS"],
    }
    payload.update(overrides)
    return payload


# ─── Vendors ──────────────────────────────────────────────────────────────────

def vendor_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": TEST_DEFAULTS["VENDOR_NAME"],
        "archival_agency_code": "PORTICO",
        "vpat_on_file": True,
    }
    payload.update(overrides)
    return payload


def minimal_vendor_payload(**overrides) -> Dict[str, Any]:
    """Only the one required field, so the declared defaults are observable."""
    payload = {"name": TEST_DEFAULTS["SECOND_VENDOR_NAME"]}
    payload.update(overrides)
    return payload


# ─── Products ─────────────────────────────────────────────────────────────────

def product_payload(vendor_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "vendor_id": vendor_id,
        "name": TEST_DEFAULTS["PRODUCT_NAME"],
        "base_list_price_cents": TEST_DEFAULTS["BASE_LIST_PRICE_CENTS"],
        "title_count": TEST_DEFAULTS["TITLE_COUNT"],
        "inflation_cap_pct": TEST_DEFAULTS["INFLATION_CAP_PCT"],
        "cancellation_notice_days": TEST_DEFAULTS["CANCELLATION_NOTICE_DAYS"],
        "perpetual_access_mode_offered": "FULL_ARCHIVE",
        "ill_mode_offered": "SECURE_ELECTRONIC",
        "text_mining_offered": True,
        "tier_bands": copy.deepcopy(DEFAULT_TIER_BANDS),
    }
    payload.update(overrides)
    return payload


def single_band_product_payload(vendor_id: str, **overrides) -> Dict[str, Any]:
    """A product whose tier schedule is the single mandatory opening band."""
    payload = product_payload(
        vendor_id,
        tier_bands=[{"min_participants": 1, "discount_pct": 0}],
    )
    payload.update(overrides)
    return payload


# ─── Trials ───────────────────────────────────────────────────────────────────

def criteria(*pairs) -> List[Dict[str, Any]]:
    """Build an ordered criteria list from ``(code, weight_pct)`` pairs."""
    return [{"code": code, "weight_pct": weight} for code, weight in pairs]


SINGLE_CRITERION = [{"code": "CONTENT_FIT", "weight_pct": 100}]
TWO_CRITERIA_60_40 = [
    {"code": "CONTENT_FIT", "weight_pct": 60},
    {"code": "INTERFACE", "weight_pct": 40},
]


def trial_payload(member_id: str, start_date: str = "2026-08-01",
                  end_date: str = "2026-08-31",
                  trial_criteria: Optional[List[Dict[str, Any]]] = None,
                  **overrides) -> Dict[str, Any]:
    payload = {
        "member_id": member_id,
        "start_date": start_date,
        "end_date": end_date,
        "criteria": copy.deepcopy(trial_criteria if trial_criteria is not None
                                  else SINGLE_CRITERION),
    }
    payload.update(overrides)
    return payload


def feedback_payload(stakeholder_group: str, criterion_code: str, score: int,
                     **overrides) -> Dict[str, Any]:
    payload = {
        "stakeholder_group": stakeholder_group,
        "criterion_code": criterion_code,
        "score": score,
    }
    payload.update(overrides)
    return payload


# ─── Negotiations ─────────────────────────────────────────────────────────────

def negotiation_payload(product_id: str, trial_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "product_id": product_id,
        "trial_id": trial_id,
        "target_term_start": TEST_DEFAULTS["TARGET_TERM_START"],
        "target_term_end": TEST_DEFAULTS["TARGET_TERM_END"],
        "requested_ill_mode": "SECURE_ELECTRONIC",
        "requested_text_mining": True,
        "requested_accessibility_conformance": "WCAG_2_1_AA",
        "requested_perpetual_access": "FULL_ARCHIVE",
    }
    payload.update(overrides)
    return payload


def accept_response_payload(accepted_price_cents: int = TEST_DEFAULTS["AGREED_PRICE_CENTS"],
                            **overrides) -> Dict[str, Any]:
    payload = {
        "disposition": "ACCEPT",
        "accepted_price_cents": accepted_price_cents,
        "granted_ill_mode": "SECURE_ELECTRONIC",
        "granted_text_mining": True,
        "granted_accessibility_conformance": "WCAG_2_1_AA",
        "granted_perpetual_access": "FULL_ARCHIVE",
    }
    payload.update(overrides)
    return payload


def counter_response_payload(counter_price_cents: int = 9900000,
                             **overrides) -> Dict[str, Any]:
    payload = {
        "disposition": "COUNTER",
        "counter_price_cents": counter_price_cents,
        "granted_ill_mode": "PRINT_ONLY",
        "granted_text_mining": False,
        "granted_accessibility_conformance": "VPAT_PARTIAL",
        "granted_perpetual_access": "POST_CANCELLATION_SUBSET",
    }
    payload.update(overrides)
    return payload


def revise_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "requested_ill_mode": "PRINT_ONLY",
        "requested_text_mining": False,
        "requested_accessibility_conformance": "VPAT_PARTIAL",
        "requested_perpetual_access": "POST_CANCELLATION_SUBSET",
    }
    payload.update(overrides)
    return payload


def sign_payload(activation_start_date: str = TEST_DEFAULTS["ACTIVATION_START_DATE"],
                 **overrides) -> Dict[str, Any]:
    payload = {"activation_start_date": activation_start_date}
    payload.update(overrides)
    return payload


# ─── Commitments ──────────────────────────────────────────────────────────────

def commitment_payload(member_id: str, **overrides) -> Dict[str, Any]:
    payload = {"member_id": member_id}
    payload.update(overrides)
    return payload


# ─── Authentication configuration ─────────────────────────────────────────────

def auth_config_payload(auth_method: str = "IP_RANGE",
                        auth_realm_code: str = TEST_DEFAULTS["AUTH_REALM_CODE"],
                        ip_ranges: Optional[List[str]] = None,
                        **overrides) -> Dict[str, Any]:
    payload = {
        "auth_method": auth_method,
        "auth_realm_code": auth_realm_code,
        "ip_ranges": list(ip_ranges if ip_ranges is not None
                          else TEST_DEFAULTS["IP_RANGES"]),
    }
    payload.update(overrides)
    return payload


def probe_payload(probe_result: str = "PASS", **overrides) -> Dict[str, Any]:
    payload = {"probe_result": probe_result}
    payload.update(overrides)
    return payload


# ─── Access incidents ─────────────────────────────────────────────────────────

def incident_payload(member_id: str, symptom_code: str = "OFF_CAMPUS_DENIED",
                     off_campus: bool = True, **overrides) -> Dict[str, Any]:
    payload = {
        "member_id": member_id,
        "symptom_code": symptom_code,
        "off_campus": off_campus,
    }
    payload.update(overrides)
    return payload


def diagnose_payload(root_cause_code: str = "PROXY_MISCONFIGURED",
                     **overrides) -> Dict[str, Any]:
    payload = {"root_cause_code": root_cause_code}
    payload.update(overrides)
    return payload


def resolve_payload(remedy_code: str = "PROXY_FIXED", **overrides) -> Dict[str, Any]:
    payload = {"remedy_code": remedy_code}
    payload.update(overrides)
    return payload


# ─── Usage reports ────────────────────────────────────────────────────────────

def usage_report_payload(member_id: str, period_month: str,
                         full_text_requests: int = 1200, searches: int = 4000,
                         denials: int = 10, **overrides) -> Dict[str, Any]:
    payload = {
        "member_id": member_id,
        "period_month": period_month,
        "full_text_requests": full_text_requests,
        "searches": searches,
        "denials": denials,
    }
    payload.update(overrides)
    return payload


# ─── Renewal decisions ────────────────────────────────────────────────────────

def renewal_decision_payload(expected_subscription_version: int,
                             recommended_action: str = "RENEW",
                             vendor_requested_increase_pct: float = 0.00,
                             **overrides) -> Dict[str, Any]:
    payload = {
        "recommended_action": recommended_action,
        "vendor_requested_increase_pct": vendor_requested_increase_pct,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload


def ballot_payload(member_id: str, ballot: str = "YES", **overrides) -> Dict[str, Any]:
    payload = {"member_id": member_id, "ballot": ballot}
    payload.update(overrides)
    return payload


def decide_payload(resolved_action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resolved_action": resolved_action}
    payload.update(overrides)
    return payload


# ─── Archival deposit checks ──────────────────────────────────────────────────

def archival_check_payload(expected_subscription_version: int,
                           agency_code: str = "PORTICO",
                           deposited_title_count: int = 380,
                           **overrides) -> Dict[str, Any]:
    payload = {
        "agency_code": agency_code,
        "deposited_title_count": deposited_title_count,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload


def attest_payload(attested_title_count: int, **overrides) -> Dict[str, Any]:
    payload = {"attested_title_count": attested_title_count}
    payload.update(overrides)
    return payload


# ─── Logical clock ────────────────────────────────────────────────────────────

def clock_payload(to_iso8601: str, **overrides) -> Dict[str, Any]:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
