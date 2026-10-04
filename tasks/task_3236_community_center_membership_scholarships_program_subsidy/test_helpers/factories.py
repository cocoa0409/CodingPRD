"""Request payload builders.

Each builder returns a valid body for one write endpoint, with sensible defaults
that any test can override by keyword. Money amounts are emitted as JSON numbers
- integer counts of cents - never as strings.
"""

from typing import Any, Dict, List, Optional


def association_payload(
    name: str = "Metro YMCA",
    ami_base_cents: int = 5_000_000,
    campaign_year: int = 2026,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "ami_base_cents": ami_base_cents,
        "campaign_year": campaign_year,
    }
    payload.update(overrides)
    return payload


def branch_payload(
    association_id: str,
    code: str = "DT",
    name: str = "Downtown",
    branch_goal_cents: int = 1_000_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "association_id": association_id,
        "code": code,
        "name": name,
        "branch_goal_cents": branch_goal_cents,
    }
    payload.update(overrides)
    return payload


def category_payload(
    branch_id: str,
    name: str = "Adult",
    household_type: str = "ADULT",
    joining_fee_cents: int = 0,
    monthly_dues_cents: int = 8_000,
    max_adults: int = 1,
    max_dependents: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "branch_id": branch_id,
        "name": name,
        "household_type": household_type,
        "joining_fee_cents": joining_fee_cents,
        "monthly_dues_cents": monthly_dues_cents,
        "max_adults": max_adults,
        "max_dependents": max_dependents,
    }
    payload.update(overrides)
    return payload


def member_payload(
    home_branch_id: str,
    full_name: str = "Pat Member",
    email: str = "pat@x.com",
    birth_date: str = "1990-04-01",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "email": email,
        "birth_date": birth_date,
        "home_branch_id": home_branch_id,
    }
    payload.update(overrides)
    return payload


def membership_payload(
    branch_id: str,
    category_id: str,
    primary_member_id: str,
    member_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "branch_id": branch_id,
        "category_id": category_id,
        "primary_member_id": primary_member_id,
        "member_ids": list(member_ids) if member_ids is not None else [primary_member_id],
    }
    payload.update(overrides)
    return payload


def application_payload(
    branch_id: str,
    membership_id: str,
    applicant_member_id: str,
    household_size: int = 1,
    annual_income_cents: int = 1_000_000,
    documentation: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "branch_id": branch_id,
        "membership_id": membership_id,
        "applicant_member_id": applicant_member_id,
        "household_size": household_size,
        "annual_income_cents": annual_income_cents,
        "documentation": list(documentation) if documentation is not None else ["TAX_RETURN"],
    }
    payload.update(overrides)
    return payload


def program_payload(
    branch_id: str,
    name: str = "Swim 101",
    kind: str = "SWIM_LESSON",
    base_fee_cents: int = 5_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "branch_id": branch_id,
        "name": name,
        "kind": kind,
        "base_fee_cents": base_fee_cents,
    }
    payload.update(overrides)
    return payload


def session_payload(
    program_id: str,
    space_id: str,
    start_on: str = "2026-09-20",
    end_on: str = "2026-09-20",
    time_start: str = "09:00",
    time_end: str = "10:00",
    capacity: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "space_id": space_id,
        "start_on": start_on,
        "end_on": end_on,
        "time_start": time_start,
        "time_end": time_end,
        "capacity": capacity,
    }
    payload.update(overrides)
    return payload


def registration_payload(
    session_id: str,
    member_id: str,
    participant_name: str = "Participant One",
    participant_birth_date: str = "1990-01-01",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "member_id": member_id,
        "participant_name": participant_name,
        "participant_birth_date": participant_birth_date,
    }
    payload.update(overrides)
    return payload


def space_payload(
    branch_id: str,
    name: str = "Gym",
    kind: str = "GYM",
    capacity: int = 100,
    dropin_capacity: int = 20,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "branch_id": branch_id,
        "name": name,
        "kind": kind,
        "capacity": capacity,
        "dropin_capacity": dropin_capacity,
    }
    payload.update(overrides)
    return payload


def reservation_payload(
    space_id: str,
    reservation_type: str = "RENTAL",
    start_at: str = "2026-09-15T09:00:00Z",
    end_at: str = "2026-09-15T10:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "space_id": space_id,
        "reservation_type": reservation_type,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def campaign_payload(
    association_id: str,
    name: str = "Annual 2026",
    goal_cents: int = 100_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "association_id": association_id,
        "name": name,
        "goal_cents": goal_cents,
    }
    payload.update(overrides)
    return payload


def donation_payload(
    campaign_id: str,
    branch_id: str,
    amount_cents: int = 10_000,
    designation: str = "GENERAL",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "campaign_id": campaign_id,
        "branch_id": branch_id,
        "amount_cents": amount_cents,
        "designation": designation,
    }
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}
