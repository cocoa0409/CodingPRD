"""Payload factories — one per creatable entity, input fields only.

Each factory returns the request body for the entity's create endpoint. Only
client-supplied fields are included; server-computed fields (statuses,
aggregates, pinned prices) are never sent.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import DEFAULT_ENROLLED_ON

_isbn_counter = itertools.count(9780001000000)
_email_counter = itertools.count(1)


def next_isbn() -> str:
    """A fresh, unique ISBN-13-shaped catalog key."""
    return str(next(_isbn_counter))


def next_email() -> str:
    """A fresh, unique teacher login email."""
    return f"teacher-{next(_email_counter)}@example.com"


def create_school_payload(
    name: str = "Test School",
    address: str = "1 Schoolhouse Ln",
    low_income_program: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"name": name, "address": address}
    if low_income_program is not None:
        payload["low_income_program"] = low_income_program
    payload.update(overrides)
    return payload


def enroll_program_payload(enrolled_on: str = DEFAULT_ENROLLED_ON, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"enrolled_on": enrolled_on}
    payload.update(overrides)
    return payload


def create_teacher_payload(
    school_id: str,
    full_name: str = "Test Teacher",
    email: Optional[str] = None,
    grade_band: str = "G3_5",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "full_name": full_name,
        "email": email if email is not None else next_email(),
        "grade_band": grade_band,
    }
    payload.update(overrides)
    return payload


def create_title_payload(
    isbn: Optional[str] = None,
    name: str = "Test Title",
    format: str = "PAPERBACK",
    grade_band: str = "G3_5",
    base_price_cents: int = 1000,
    points_cost: int = 10,
    rights_holder: str = "Test Publisher",
    royalty_cap_cents: int = 100000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "isbn": isbn if isbn is not None else next_isbn(),
        "name": name,
        "format": format,
        "grade_band": grade_band,
        "base_price_cents": base_price_cents,
        "points_cost": points_cost,
        "rights_holder": rights_holder,
        "royalty_cap_cents": royalty_cap_cents,
    }
    payload.update(overrides)
    return payload


def create_promotion_payload(
    name: str = "Test Promo",
    kind: str = "BONUS_POINTS",
    starts_on: str = "2026-10-01",
    ends_on: str = "2026-11-01",
    grade_band: Optional[str] = None,
    title_id: Optional[str] = None,
    multiplier_bp: Optional[int] = None,
    bonus_points_per_unit: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "kind": kind,
        "starts_on": starts_on,
        "ends_on": ends_on,
    }
    if grade_band is not None:
        payload["grade_band"] = grade_band
    if title_id is not None:
        payload["title_id"] = title_id
    if multiplier_bp is not None:
        payload["multiplier_bp"] = multiplier_bp
    if bonus_points_per_unit is not None:
        payload["bonus_points_per_unit"] = bonus_points_per_unit
    payload.update(overrides)
    return payload


def create_flyer_cycle_payload(
    school_id: str,
    month: str = "2026-10",
    grade_band: str = "G3_5",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "month": month,
        "grade_band": grade_band,
    }
    payload.update(overrides)
    return payload


def create_offering_payload(title_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"title_id": title_id}
    payload.update(overrides)
    return payload


def create_class_order_payload(
    cycle_id: str,
    teacher_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cycle_id": cycle_id, "teacher_id": teacher_id}
    payload.update(overrides)
    return payload


def create_order_line_payload(
    offering_id: str,
    student_name: str = "Test Student",
    submitted_by: str = "TEACHER",
    qty: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "offering_id": offering_id,
        "student_name": student_name,
        "submitted_by": submitted_by,
        "qty": qty,
    }
    payload.update(overrides)
    return payload


def submit_class_order_payload(
    expected_class_order_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_class_order_version": expected_class_order_version}
    payload.update(overrides)
    return payload


def acquire_title_payload(
    royalty_cap_cents: int,
    expected_title_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "royalty_cap_cents": royalty_cap_cents,
        "expected_title_version": expected_title_version,
    }
    payload.update(overrides)
    return payload


def create_book_fair_payload(
    school_id: str,
    start_date: str = "2026-10-05",
    end_date: str = "2026-10-09",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


def create_fair_title_payload(title_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"title_id": title_id}
    payload.update(overrides)
    return payload


def create_donation_request_payload(
    school_id: str,
    teacher_id: str,
    title_id: str,
    qty_requested: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "teacher_id": teacher_id,
        "title_id": title_id,
        "qty_requested": qty_requested,
    }
    payload.update(overrides)
    return payload


def create_redemption_payload(
    teacher_id: str,
    kind: str = "BOOK",
    qty: int = 1,
    title_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"teacher_id": teacher_id, "kind": kind, "qty": qty}
    if title_id is not None:
        payload["title_id"] = title_id
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
