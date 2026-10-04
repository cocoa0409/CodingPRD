"""Payload factories — one per creatable entity, input fields only.

Each factory returns a complete, valid payload with sensible defaults that
tests override through ``**overrides``.  Only fields the PRD names as part
of the create request appear here; system fields (``id``, ``status``,
``version``, computed columns) are never supplied by the caller.
"""

from .constants import (
    CATEGORY_PREVENTIVE,
    COB_PRIMARY,
    RELATIONSHIP_CHILD,
    TIER_PPO,
)

NPI_COUNTER = {"value": 1234567800}


def fresh_npi():
    """A ten-digit NPI that does not repeat within a test run."""
    NPI_COUNTER["value"] += 1
    return str(NPI_COUNTER["value"])


def instant(year, month, day):
    """A midnight-UTC ISO 8601 instant literal for payload fields."""
    return "{0:04d}-{1:02d}-{2:02d}T00:00:00Z".format(year, month, day)


def create_plan_payload(**overrides):
    """A plan body matching the standard profile used across the suite."""
    defaults = {
        "plan_code": "DD-STD",
        "plan_year_start_month": 1,
        "annual_maximum_cents": 150000,
        "deductible_cents": 0,
        "deductible_applies_preventive": False,
        "preventive_coinsurance_pct": 100,
        "basic_coinsurance_pct": 80,
        "major_coinsurance_pct": 50,
        "basic_waiting_months": 0,
        "major_waiting_months": 0,
        "missing_tooth_clause_active": False,
        "abp_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides):
    defaults = {
        "npi": fresh_npi(),
        "legal_name": "Standard Dental",
        "tier": TIER_PPO,
        "license_state": "CA",
        "contracted_on": instant(2025, 1, 1),
    }
    defaults.update(overrides)
    return defaults


def fee_schedule_entry_payload(**overrides):
    defaults = {
        "cdt_code": "D0120",
        "allowed_cents": 5000,
        "category": CATEGORY_PREVENTIVE,
        "requires_attachment": False,
        "abp_alternative_cdt": "",
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(entries=None, **overrides):
    defaults = {
        "tier": TIER_PPO,
        "effective_from": instant(2026, 1, 1),
        "entries": entries if entries is not None else [fee_schedule_entry_payload()],
    }
    defaults.update(overrides)
    return defaults


def create_subscriber_payload(plan_id, **overrides):
    defaults = {
        "plan_id": plan_id,
        "member_id": "M-STD",
        "full_name": "Stan Standard",
        "date_of_birth": instant(1980, 1, 1),
        "effective_date": instant(2026, 1, 1),
        "cob_priority": COB_PRIMARY,
    }
    defaults.update(overrides)
    return defaults


def create_dependent_payload(**overrides):
    defaults = {
        "full_name": "Kid Standard",
        "date_of_birth": instant(2015, 6, 1),
        "relationship": RELATIONSHIP_CHILD,
    }
    defaults.update(overrides)
    return defaults


def create_limitation_rule_payload(**overrides):
    defaults = {
        "cdt_code": "D0120",
        "rule_kind": "FREQUENCY",
        "window_months": 6,
        "max_occurrences": 2,
        "age_years_min": 0,
        "age_years_max": 0,
    }
    defaults.update(overrides)
    return defaults


def create_predetermination_payload(subscriber_id, provider_id, **overrides):
    defaults = {
        "subscriber_id": subscriber_id,
        "provider_id": provider_id,
        "cdt_code": "D2740",
        "submitted_amount_cents": 9000,
        "planned_service_date": instant(2026, 6, 1),
    }
    defaults.update(overrides)
    return defaults


def claim_line_payload(**overrides):
    defaults = {
        "line_number": 1,
        "cdt_code": "D0120",
        "tooth_number": "",
        "submitted_amount_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(subscriber_id, provider_id, lines=None, **overrides):
    defaults = {
        "subscriber_id": subscriber_id,
        "provider_id": provider_id,
        "service_date": instant(2026, 2, 1),
        "received_date": instant(2026, 2, 2),
        "lines": lines if lines is not None else [claim_line_payload()],
    }
    defaults.update(overrides)
    return defaults


def create_attachment_payload(claim_line_id, **overrides):
    defaults = {
        "claim_line_id": claim_line_id,
        "attachment_kind": "RADIOGRAPH",
        "blob_ref": "blob://xray",
    }
    defaults.update(overrides)
    return defaults
