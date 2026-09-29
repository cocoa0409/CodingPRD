"""Payload builders for the awareness program API.

Every builder returns a plain dict that satisfies the required-field contract of
its endpoint and accepts keyword overrides.  Instants are always full ISO-8601
UTC timestamps; `hire_date` is deliberately the calendar-date form the contract
declares for that one field.
"""

from __future__ import annotations

import itertools
from typing import List, Optional

from .constants import (
    EVENT_CLICK,
    REPORT_VARIANT_CONCURRENT,
    SOURCE_LANDING_PAGE,
    TIER_1,
    WINDOW_SIMULATION_BLACKOUT,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix that keeps emails and module codes unique inside a test."""
    return f"{next(_counter):04d}"


def employee_payload(
    *,
    email: Optional[str] = None,
    full_name: str = "Casey Learner",
    department: str = "ENGINEERING",
    role_code: str = "ENGINEER",
    hire_date: str = "2015-01-15",
    manager_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "email": email or f"person.{unique_suffix()}@corp.example",
        "full_name": full_name,
        "department": department,
        "role_code": role_code,
        "hire_date": hire_date,
    }
    if manager_id is not None:
        payload["manager_id"] = manager_id
    payload.update(overrides)
    return payload


def manager_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Morgan Manager",
        "department": "IT",
        "role_code": "MANAGER",
        "hire_date": "2011-01-01",
    }
    defaults.update(overrides)
    return employee_payload(**defaults)


def module_payload(
    *,
    code: Optional[str] = None,
    title: str = "Awareness Module",
    module_type: str = "ANNUAL",
    **overrides,
) -> dict:
    payload = {
        "code": code or f"MOD-{unique_suffix()}",
        "title": title,
        "module_type": module_type,
    }
    payload.update(overrides)
    return payload


def assignment_payload(
    employee_id: str,
    module_id: str,
    expected_employee_version: int,
    *,
    assignment_reason: str = "ANNUAL",
    **overrides,
) -> dict:
    payload = {
        "employee_id": employee_id,
        "module_id": module_id,
        "assignment_reason": assignment_reason,
        "expected_employee_version": expected_employee_version,
    }
    payload.update(overrides)
    return payload


def template_payload(
    *,
    name: str = "Pretext Template",
    pretext_category: str = "PACKAGE_DELIVERY",
    difficulty_tier: str = TIER_1,
    theme_tags: Optional[List[str]] = None,
    credential_capture_enabled: Optional[bool] = None,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "pretext_category": pretext_category,
        "difficulty_tier": difficulty_tier,
    }
    if theme_tags is not None:
        payload["theme_tags"] = theme_tags
    if credential_capture_enabled is not None:
        payload["credential_capture_enabled"] = credential_capture_enabled
    payload.update(overrides)
    return payload


def campaign_payload(
    template_id: str,
    *,
    name: str = "Awareness Wave",
    difficulty_tier: str = TIER_1,
    target_departments: Optional[List[str]] = None,
    target_tenure_bands: Optional[List[str]] = None,
    target_min_repeat_tier: Optional[int] = None,
    communication_policy_ack: Optional[bool] = True,
    **overrides,
) -> dict:
    payload = {
        "name": name,
        "template_id": template_id,
        "difficulty_tier": difficulty_tier,
    }
    if target_departments is not None:
        payload["target_departments"] = target_departments
    if target_tenure_bands is not None:
        payload["target_tenure_bands"] = target_tenure_bands
    if target_min_repeat_tier is not None:
        payload["target_min_repeat_tier"] = target_min_repeat_tier
    if communication_policy_ack is not None:
        payload["communication_policy_ack"] = communication_policy_ack
    payload.update(overrides)
    return payload


def schedule_payload(scheduled_send_at: str, expected_campaign_version: int) -> dict:
    return {
        "scheduled_send_at": scheduled_send_at,
        "expected_campaign_version": expected_campaign_version,
    }


def interaction_payload(
    occurred_at: str,
    *,
    event_type: str = EVENT_CLICK,
    source: str = SOURCE_LANDING_PAGE,
) -> dict:
    return {"event_type": event_type, "occurred_at": occurred_at, "source": source}


def consequence_payload(
    expected_employee_version: int,
    *,
    reason_code: str = "POLICY_BREACH_INVESTIGATION",
    consequence_type: Optional[str] = None,
    source_assignment_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "reason_code": reason_code,
        "expected_employee_version": expected_employee_version,
    }
    if consequence_type is not None:
        payload["consequence_type"] = consequence_type
    if source_assignment_id is not None:
        payload["source_assignment_id"] = source_assignment_id
    payload.update(overrides)
    return payload


def incident_payload(
    *,
    incident_type: str = "CREDENTIAL_PHISH",
    severity: str = "HIGH",
    department: str = "ENGINEERING",
    occurred_at: str = "2026-07-30T14:00:00Z",
    summary: str = "Credential harvesting lure reached an inbox.",
    root_cause_employee_id: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "incident_type": incident_type,
        "severity": severity,
        "department": department,
        "occurred_at": occurred_at,
        "summary": summary,
    }
    if root_cause_employee_id is not None:
        payload["root_cause_employee_id"] = root_cause_employee_id
    payload.update(overrides)
    return payload


def communication_window_payload(
    start_at: str,
    end_at: str,
    *,
    window_type: str = WINDOW_SIMULATION_BLACKOUT,
    reason: str = "Declared communication window.",
    scope_department: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "window_type": window_type,
        "start_at": start_at,
        "end_at": end_at,
        "reason": reason,
    }
    if scope_department is not None:
        payload["scope_department"] = scope_department
    payload.update(overrides)
    return payload


def effectiveness_params(
    period_start: str,
    period_end: str,
    *,
    variant: str = REPORT_VARIANT_CONCURRENT,
    department: Optional[str] = None,
) -> dict:
    params = {
        "period_start": period_start,
        "period_end": period_end,
        "variant": variant,
    }
    if department is not None:
        params["department"] = department
    return params
