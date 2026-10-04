"""Payload factories — one per entity, carrying only input fields (PRD §3)."""
from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_APPLICANT_USER_ID,
    DEFAULT_LEARNER_BIRTH_DATE,
    DEFAULT_LIST_PRICE_CENTS,
    DEFAULT_PARENT_USER_ID,
    DEFAULT_SAMPLE_MINUTES,
    DEFAULT_SAMPLE_URL,
    DEFAULT_SECTION_END_UTC,
    DEFAULT_SECTION_START_UTC,
    DEFAULT_TEACHER_DISPLAY_NAME,
    DEFAULT_TEACHER_EMAIL,
    DEFAULT_TIMEZONE,
)


def create_teacher_application_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "applicant_user_id": DEFAULT_APPLICANT_USER_ID,
        "applicant_email": DEFAULT_TEACHER_EMAIL,
        "display_name": DEFAULT_TEACHER_DISPLAY_NAME,
        "teaching_sample_url": DEFAULT_SAMPLE_URL,
        "teaching_sample_minutes": DEFAULT_SAMPLE_MINUTES,
    }
    payload.update(overrides)
    return payload


def submit_application_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "teaching_sample_url": DEFAULT_SAMPLE_URL,
        "teaching_sample_minutes": DEFAULT_SAMPLE_MINUTES,
    }
    payload.update(overrides)
    return payload


def submit_sample_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "teaching_sample_url": DEFAULT_SAMPLE_URL,
        "teaching_sample_minutes": DEFAULT_SAMPLE_MINUTES,
    }
    payload.update(overrides)
    return payload


def review_application_payload(stage: str, verdict: str, reason_code: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"stage": stage, "verdict": verdict}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return payload


def create_class_listing_payload(teacher_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "teacher_id": teacher_id,
        "title": "Algebra Club",
        "format": "ONE_TIME",
        "min_age": 8,
        "max_age": 12,
        "max_learners": 6,
        "list_price_cents": DEFAULT_LIST_PRICE_CENTS,
    }
    payload.update(overrides)
    return payload


def policy_review_payload(decision: str, reason_code: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return payload


def create_section_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "timezone": DEFAULT_TIMEZONE,
        "start_utc": DEFAULT_SECTION_START_UTC,
        "end_utc": DEFAULT_SECTION_END_UTC,
        "min_learners": 1,
        "capacity": 6,
    }
    payload.update(overrides)
    return payload


def create_learner_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "display_name": "Learner One",
        "birth_date": DEFAULT_LEARNER_BIRTH_DATE,
        "parent_user_id": DEFAULT_PARENT_USER_ID,
    }
    payload.update(overrides)
    return payload


def subscription_payload(subscription_tier: str) -> Dict[str, Any]:
    return {"subscription_tier": subscription_tier}


def create_enrollment_payload(learner_id: str, coupon_code: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"learner_id": learner_id}
    if coupon_code is not None:
        payload["coupon_code"] = coupon_code
    return payload


def create_payout_payload(period_start: str, period_end: str, expected_teacher_version: int) -> Dict[str, Any]:
    return {
        "period_start": period_start,
        "period_end": period_end,
        "expected_teacher_version": expected_teacher_version,
    }


def payout_transition_payload(action: str) -> Dict[str, Any]:
    return {"action": action}


def create_report_payload(teacher_id: str, class_listing_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "teacher_id": teacher_id,
        "class_listing_id": class_listing_id,
        "reported_by_user_id": DEFAULT_PARENT_USER_ID,
        "severity": "LOW",
        "category": "TECHNICAL",
    }
    payload.update(overrides)
    return payload


def report_disposition_payload(action: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    return payload


def suspend_teacher_payload(reason: str = "policy violation") -> Dict[str, Any]:
    return {"reason": reason}
