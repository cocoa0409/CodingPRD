"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


DEFAULTS = {
    "TERM_START": "2027-01-01T00:00:00Z",
    "TERM_END": "2031-12-31T00:00:00Z",
    "BASE_ROYALTY_RATE_BPS": 600,
    "ANNUAL_ROYALTY_CAP_CENTS": 900_000_000,
    "VOLUME_THRESHOLD_CENTS": 1_000_000_000,
    "VOLUME_RATE_BPS": 300,
    "AD_FUND_RATE_BPS": 200,
}


def create_brand_payload(**overrides) -> dict:
    defaults = {"brand_code": f"B{_n():04d}", "display_name": "Test Brand"}
    defaults.update(overrides)
    return defaults


def create_market_payload(**overrides) -> dict:
    defaults = {"market_code": f"M{_n():04d}", "name": "Test Market"}
    defaults.update(overrides)
    return defaults


def create_brokerage_payload(home_market_id, **overrides) -> dict:
    defaults = {
        "legal_name": f"Test Brokerage {_n()}",
        "home_market_id": home_market_id,
        "principal_email": "principal@example.test",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(brokerage_id, brand_id, market_id, **overrides) -> dict:
    defaults = {
        "brokerage_id": brokerage_id,
        "brand_id": brand_id,
        "market_id": market_id,
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
        "base_royalty_rate_bps": DEFAULTS["BASE_ROYALTY_RATE_BPS"],
        "annual_royalty_cap_cents": DEFAULTS["ANNUAL_ROYALTY_CAP_CENTS"],
        "volume_incentive_threshold_cents": DEFAULTS["VOLUME_THRESHOLD_CENTS"],
        "volume_incentive_rate_bps": DEFAULTS["VOLUME_RATE_BPS"],
        "ad_fund_rate_bps": DEFAULTS["AD_FUND_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_milestones(count=1, **overrides) -> list:
    milestones = [
        {"name": f"milestone-{i}", "target_date": DEFAULTS["TERM_START"], "sequence": i}
        for i in range(1, count + 1)
    ]
    return overrides.get("milestones", milestones)


def create_conversion_plan_payload(**overrides) -> dict:
    defaults = {"milestones": create_milestones(1)}
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Agent {_n()}",
        "license_no": f"LIC-{_n()}",
        "affiliated_on": DEFAULTS["TERM_START"],
    }
    defaults.update(overrides)
    return defaults


def create_agent_count_report_payload(**overrides) -> dict:
    defaults = {"period_month": "2027-01", "active_agent_count": 1}
    defaults.update(overrides)
    return defaults


def create_gci_report_payload(**overrides) -> dict:
    defaults = {"period_month": "2027-01", "gci_cents": 100_000_000}
    defaults.update(overrides)
    return defaults


def create_default_case_payload(**overrides) -> dict:
    defaults = {"reason_code": "PAYMENT"}
    defaults.update(overrides)
    return defaults


def create_council_payload(brand_id, member_brokerage_ids, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "seat_count": len(member_brokerage_ids),
        "member_brokerage_ids": list(member_brokerage_ids),
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(brand_id, council_id, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "council_id": council_id,
        "title": "Test spend proposal",
        "amount_cents": 1_000,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {"audit_type": "SIGNAGE"}
    defaults.update(overrides)
    return defaults
