"""Payload factories — one per resource, carrying only client-supplied fields."""
from .constants import TEST_DEFAULTS


def create_center_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["CENTER_NAME"],
        "code": TEST_DEFAULTS["CENTER_CODE"],
        "total_gla_sqft": TEST_DEFAULTS["TOTAL_GLA_SQFT"],
        "anchor_gla_sqft": TEST_DEFAULTS["ANCHOR_GLA_SQFT"],
    }
    payload.update(overrides)
    return payload


def create_tenant_payload(center_id: str, **overrides) -> dict:
    payload = {
        "center_id": center_id,
        "legal_name": "Bright Shoes LLC",
        "trade_name": "Bright Shoes",
        "category": "INLINE",
        "gla_sqft": TEST_DEFAULTS["TENANT_GLA_SQFT"],
    }
    payload.update(overrides)
    return payload


def create_anchor_tenant_payload(center_id: str, **overrides) -> dict:
    payload = {
        "center_id": center_id,
        "legal_name": "Anchor Dept Store LLC",
        "trade_name": "AnchorMart",
        "category": "ANCHOR",
        "gla_sqft": TEST_DEFAULTS["ANCHOR_TENANT_GLA_SQFT"],
    }
    payload.update(overrides)
    return payload


def create_lease_payload(center_id: str, tenant_id: str, **overrides) -> dict:
    """A NATURAL-breakpoint monthly lease unless the caller says otherwise.

    Pass breakpoint_type="ARTIFICIAL" together with artificial_breakpoint_cents
    to state the breakpoint contractually instead.
    """
    payload = {
        "center_id": center_id,
        "tenant_id": tenant_id,
        "suite_code": "101",
        "leased_sqft": TEST_DEFAULTS["LEASED_SQFT"],
        "annual_base_rent_cents": TEST_DEFAULTS["ANNUAL_BASE_RENT_CENTS"],
        "percentage_rate_bps": TEST_DEFAULTS["PERCENTAGE_RATE_BPS"],
        "breakpoint_type": "NATURAL",
        "billing_mode": "CUMULATIVE_YTD",
        "reporting_frequency": "MONTHLY",
        "reporting_deadline_days": TEST_DEFAULTS["REPORTING_DEADLINE_DAYS"],
        "exclusion_profile": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_lease_year_payload(**overrides) -> dict:
    payload = {
        "year_index": 1,
        "period_start": TEST_DEFAULTS["YEAR_START"],
        "period_end": TEST_DEFAULTS["YEAR_END"],
    }
    payload.update(overrides)
    return payload


def create_sales_report_payload(period_start: str, period_end: str,
                                **overrides) -> dict:
    payload = {"period_start": period_start, "period_end": period_end}
    payload.update(overrides)
    return payload


def submit_sales_report_payload(gross_sales_cents: int, exclusions=None,
                                **overrides) -> dict:
    payload = {"gross_sales_cents": gross_sales_cents}
    if exclusions is not None:
        payload["exclusions"] = exclusions
    payload.update(overrides)
    return payload


def exclusion_line(code: str, claimed_cents: int) -> dict:
    return {"code": code, "claimed_cents": claimed_cents}


def create_co_tenancy_clause_payload(**overrides) -> dict:
    payload = {
        "required_open_anchor_count": 1,
        "required_occupancy_bps": 0,
        "cure_period_days": 0,
        "relief_type": "RENT_REDUCTION",
        "relief_pct_bps": 5000,
        "termination_right_after_days": 180,
    }
    payload.update(overrides)
    return payload


def create_kick_out_clause_payload(**overrides) -> dict:
    payload = {
        "measurement_year_index": 1,
        "threshold_sales_cents": 100_000_000,
        "election_window_days": 30,
    }
    payload.update(overrides)
    return payload


def create_audit_payload(sales_report_id: str, audit_window_start: str,
                         audit_window_end: str, **overrides) -> dict:
    payload = {
        "sales_report_id": sales_report_id,
        "audit_window_start": audit_window_start,
        "audit_window_end": audit_window_end,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "create_center_payload", "create_tenant_payload",
    "create_anchor_tenant_payload", "create_lease_payload",
    "create_lease_year_payload", "create_sales_report_payload",
    "submit_sales_report_payload", "exclusion_line",
    "create_co_tenancy_clause_payload", "create_kick_out_clause_payload",
    "create_audit_payload",
]
