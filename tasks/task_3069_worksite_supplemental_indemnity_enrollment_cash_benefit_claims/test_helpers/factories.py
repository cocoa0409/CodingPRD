"""Request payload factories — one per creatable resource, input fields only.

Each factory supplies PRD-sane defaults so a test only overrides the fields that the
scenario cares about. ``_unique`` keeps codes, licenses, and references distinct across
the many scenarios a single test run builds.
"""

import itertools

from .constants import (
    DEFAULT_EFFECTIVE_DATE,
    DEFAULT_HIRE_DATE,
    DEFAULT_PERIOD_END,
    DEFAULT_PERIOD_START,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)
from .types import JsonObject, ResourceId

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return "%s-%04d" % (prefix, next(_counter))


def employer_group_payload(**overrides) -> JsonObject:
    """Group create body; minimums default to the PRD's 0.10 / 3, convention DAILY."""
    payload: JsonObject = {
        "name": _unique("Group"),
        "group_code": _unique("GRP"),
    }
    payload.update(overrides)
    return payload


def benefit_counselor_payload(**overrides) -> JsonObject:
    payload: JsonObject = {
        "license_id": _unique("LIC"),
        "full_name": "Counselor %04d" % next(_counter),
        "home_state": "TX",
    }
    payload.update(overrides)
    return payload


def enrollment_campaign_payload(
    employer_group_id: ResourceId, counselor_id: ResourceId, **overrides
) -> JsonObject:
    payload: JsonObject = {
        "employer_group_id": employer_group_id,
        "counselor_id": counselor_id,
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
        "guaranteed_issue": True,
    }
    payload.update(overrides)
    return payload


def policy_series_payload(**overrides) -> JsonObject:
    payload: JsonObject = {
        "series_code": _unique("SER"),
        "product_line": "ACCIDENT",
    }
    payload.update(overrides)
    return payload


def benefit_item_payload(**overrides) -> JsonObject:
    payload: JsonObject = {
        "event_code": _unique("EVT"),
        "benefit_amount_cents": 1000,
        "max_occurrences_per_year": 1,
        "lifetime_max_cents": 100000,
    }
    payload.update(overrides)
    return payload


def benefit_schedule_payload(
    policy_series_id: ResourceId, benefit_items=None, **overrides
) -> JsonObject:
    payload: JsonObject = {
        "policy_series_id": policy_series_id,
        "schedule_version": 1,
        "effective_date": DEFAULT_EFFECTIVE_DATE,
        "benefit_items": benefit_items if benefit_items is not None else [benefit_item_payload()],
        "monthly_premium_cents": 1000,
        "wellness_benefit_cents": 500,
        "wellness_waiting_months": 0,
        "preexisting_exclusion_months": 0,
    }
    payload.update(overrides)
    return payload


def employee_payload(employer_group_id: ResourceId, **overrides) -> JsonObject:
    payload: JsonObject = {
        "employer_group_id": employer_group_id,
        "employee_ref": _unique("EMP"),
        "full_name": "Employee %04d" % next(_counter),
        "hire_date": DEFAULT_HIRE_DATE,
    }
    payload.update(overrides)
    return payload


def policy_payload(
    campaign_id: ResourceId, employee_id: ResourceId, policy_series_id: ResourceId,
    **overrides,
) -> JsonObject:
    payload: JsonObject = {
        "campaign_id": campaign_id,
        "employee_id": employee_id,
        "policy_series_id": policy_series_id,
        "premium_mode": "POST_TAX",
    }
    payload.update(overrides)
    return payload


def claim_payload(policy_id: ResourceId, event_code: str, **overrides) -> JsonObject:
    payload: JsonObject = {
        "policy_id": policy_id,
        "event_code": event_code,
        "service_date": "2026-09-05T00:00:00Z",
        "diagnosis_code": "D-001",
        "claimed_occurrences": 1,
    }
    payload.update(overrides)
    return payload


def claim_document_payload(claim_id: ResourceId, **overrides) -> JsonObject:
    payload: JsonObject = {
        "claim_id": claim_id,
        "doc_type": "DIAGNOSIS_PROOF",
        "content_ref": _unique("docref"),
    }
    payload.update(overrides)
    return payload


def wellness_benefit_payload(policy_id: ResourceId, **overrides) -> JsonObject:
    payload: JsonObject = {
        "policy_id": policy_id,
        "calendar_year": 2026,
        "service_date": "2026-09-10T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def payroll_cycle_payload(employer_group_id: ResourceId, **overrides) -> JsonObject:
    payload: JsonObject = {
        "employer_group_id": employer_group_id,
        "period_start": DEFAULT_PERIOD_START,
        "period_end": DEFAULT_PERIOD_END,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "employer_group_payload",
    "benefit_counselor_payload",
    "enrollment_campaign_payload",
    "policy_series_payload",
    "benefit_item_payload",
    "benefit_schedule_payload",
    "employee_payload",
    "policy_payload",
    "claim_payload",
    "claim_document_payload",
    "wellness_benefit_payload",
    "payroll_cycle_payload",
]
