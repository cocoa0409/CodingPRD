"""Payload factories - one per creatable resource, input fields only.

Each factory returns the request body for its create call. Only fields the
caller supplies appear; system-computed fields are never sent.
"""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def supplier_account_payload(**overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/supplier-accounts."""
    defaults: Dict[str, Any] = {
        "account_name": "Test Supplier Co",
        "region": TEST_DEFAULTS["REGION"],
    }
    defaults.update(overrides)
    return defaults


def subscription_contract_payload(**overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/supplier-accounts/{id}/subscription-contracts."""
    defaults: Dict[str, Any] = {
        "tier": "TIER_CATEGORY",
        "report_credit_allowance": TEST_DEFAULTS["REPORT_CREDIT_ALLOWANCE"],
        "activation_budget_cents": TEST_DEFAULTS["ACTIVATION_BUDGET_CENTS"],
        "redistribution_allowed": True,
        "modeled_derivation_allowed": True,
    }
    defaults.update(overrides)
    return defaults


def category_scope_payload(**overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/subscription-contracts/{id}/category-scopes."""
    defaults: Dict[str, Any] = {
        "category_code": TEST_DEFAULTS["CATEGORY_CODE"],
        "brand_codes": list(TEST_DEFAULTS["BRAND_CODES"]),
    }
    defaults.update(overrides)
    return defaults


def household_payload(ref: str, **overrides) -> Dict[str, Any]:
    """One household entry for the bulk ingest call."""
    defaults: Dict[str, Any] = {
        "household_ref": ref,
        "category_codes": [TEST_DEFAULTS["CATEGORY_CODE"]],
    }
    defaults.update(overrides)
    return defaults


def insight_report_payload(contract_id: str, **overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/insight-reports."""
    defaults: Dict[str, Any] = {
        "contract_id": contract_id,
        "report_type": "CATEGORY",
        "category_code": TEST_DEFAULTS["CATEGORY_CODE"],
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def segment_payload(contract_id: str, **overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/audience-segments."""
    defaults: Dict[str, Any] = {
        "contract_id": contract_id,
        "segment_name": "Test Segment",
        "category_code": TEST_DEFAULTS["CATEGORY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def activation_payload(expected_segment_version: int, **overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/audience-segments/{id}/activations."""
    defaults: Dict[str, Any] = {
        "expected_segment_version": expected_segment_version,
        "channels": ["COUPON"],
    }
    defaults.update(overrides)
    return defaults


def study_payload(**overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/incrementality-studies."""
    defaults: Dict[str, Any] = {
        "brand_code": "ACME",
        "category_code": TEST_DEFAULTS["CATEGORY_CODE"],
        "window_start": "2026-09-01",
        "window_end": "2026-09-10",
    }
    defaults.update(overrides)
    return defaults


def grant_payload(supplier_account_id: str, **overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/clean-room-grants."""
    defaults: Dict[str, Any] = {
        "supplier_account_id": supplier_account_id,
        "valid_from": "2026-09-01T00:00:00Z",
        "valid_until": "2026-12-01T00:00:00Z",
        "query_budget_total": TEST_DEFAULTS["QUERY_BUDGET_TOTAL"],
    }
    defaults.update(overrides)
    return defaults


def query_payload(**overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/clean-room-grants/{id}/queries."""
    defaults: Dict[str, Any] = {
        "dataset_joins": ["SALES"],
        "estimated_rows": 1000,
    }
    defaults.update(overrides)
    return defaults


def cycle_payload(**overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/line-review-cycles."""
    defaults: Dict[str, Any] = {
        "category_code": TEST_DEFAULTS["CATEGORY_CODE"],
        "window_start": "2026-09-20",
        "window_end": "2026-09-25",
    }
    defaults.update(overrides)
    return defaults


def deliverable_payload(contract_id: str, insight_report_id: str, **overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/line-review-cycles/{id}/deliverables."""
    defaults: Dict[str, Any] = {
        "contract_id": contract_id,
        "insight_report_id": insight_report_id,
        "due_at": "2026-09-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def forecast_payload(contract_id: str, **overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/new-item-forecasts."""
    defaults: Dict[str, Any] = {
        "contract_id": contract_id,
        "product_ref": "NEW-1",
        "analogs": [
            {"analog_ref": "A1", "similarity_score": 1.0, "observed_week4_units": 100},
        ],
        "variant": "SIMPLE_AVERAGE",
    }
    defaults.update(overrides)
    return defaults


def amend_payload(expected_contract_version: int, **overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/subscription-contracts/{id}/amend."""
    defaults: Dict[str, Any] = {"expected_contract_version": expected_contract_version}
    defaults.update(overrides)
    return defaults


def deny_grant_payload(**overrides) -> Dict[str, Any]:
    """Body for POST /shopper-insights/clean-room-grants/{id}/deny."""
    defaults: Dict[str, Any] = {"reason": "Insufficient privacy justification."}
    defaults.update(overrides)
    return defaults
