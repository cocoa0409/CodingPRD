"""Payload factories — one per creatable resource, input fields only.

Factories never set system/computed fields (status, premium_cents, expires_on,
created_by_user_id, ...); those are the server's to write. Optional inputs are
omitted from the payload when not supplied, which is the natural client
behavior for nullable pairings such as a review's `object_id` / `fund_id`
(PRD §3.6).

Uniqueness: museum codes, fund codes, emails, accession numbers, and visitor /
buyer / school names are auto-suffixed with a process-wide counter so repeated
factory calls inside one test never trip uniqueness rules (a duplicate pass,
for example, is keyed on (museum, visitor_name, visit_date)).
"""

import itertools
from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_LOAN_END_DATE,
    DEFAULT_LOAN_START_DATE,
    DEFAULT_MEMBER_PRESALE_OPENS_AT,
    DEFAULT_MONDAY,
    DEFAULT_PUBLIC_SALE_OPENS_AT,
    DEFAULT_RESEARCH_VISIT_END,
    DEFAULT_RESEARCH_VISIT_START,
    DEFAULT_VISIT_DATE,
)
from .types import (
    ActivityType,
    CertificationLevel,
    CoverageType,
    DayOfWeek,
    DisposalMethod,
    FundType,
    ReportKind,
    ReviewKind,
)

Json = Dict[str, Any]

_COUNTER = itertools.count(1)


def _seq() -> int:
    return next(_COUNTER)


def _drop_none(payload: Json) -> Json:
    return {k: v for k, v in payload.items() if v is not None}


# ── Museums & passes ─────────────────────────────────────────────────────────
def create_museum_payload(**overrides: Any) -> Json:
    """Defaults describe an ordinary walk-in museum; pass
    requires_timed_pass=True for a timed-entry museum."""
    n = _seq()
    payload: Json = {
        "museum_code": f"MUS-{n:04d}",
        "display_name": f"Test Museum {n}",
        "requires_timed_pass": False,
        "quarter_hour_pass_quota": 10,
        "daily_pass_quota": 100,
        "screening_rate_per_quarter_hour": 20,
    }
    payload.update(overrides)
    return payload


def create_timed_entry_pass_payload(**overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "visitor_name": f"Visitor {n}",
        "visit_date": DEFAULT_VISIT_DATE,
        "entry_quarter_hour": 1,
    }
    payload.update(overrides)
    return payload


def close_day_payload(closure_date: str) -> Json:
    return {"closure_date": closure_date}


# ── Members ──────────────────────────────────────────────────────────────────
def create_member_payload(**overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "full_name": f"Member {n}",
        "email": f"member-{n}@example.org",
        "membership_term_months": 12,
    }
    payload.update(overrides)
    return payload


# ── Exhibitions & tickets ────────────────────────────────────────────────────
def create_exhibition_payload(revenue_fund_id: str, **overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "title": f"Special Exhibition {n}",
        "fee_cents": 1000,
        "daily_ticket_quota": 5,
        "member_presale_opens_at": DEFAULT_MEMBER_PRESALE_OPENS_AT,
        "public_sale_opens_at": DEFAULT_PUBLIC_SALE_OPENS_AT,
        "revenue_fund_id": revenue_fund_id,
    }
    payload.update(overrides)
    return payload


def purchase_ticket_payload(member_id: Optional[str] = None, **overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "buyer_name": f"Buyer {n}",
        "visit_date": DEFAULT_VISIT_DATE,
    }
    if member_id is not None:
        payload["member_id"] = member_id
    payload.update(overrides)
    return payload


# ── Docents, programs, assignments, reservations ─────────────────────────────
def create_docent_payload(**overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "full_name": f"Docent {n}",
        "certification_level": CertificationLevel.BASIC.value,
        "active": True,
    }
    payload.update(overrides)
    return payload


def create_education_program_payload(**overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "title": f"Education Program {n}",
        "gallery_code": f"G{n}",
        "day_of_week": DayOfWeek.MON.value,
        "start_minute": 600,
        "end_minute": 660,
        "student_capacity": 40,
        "docent_ratio": 10,
        "max_group_size": 50,
        "required_docent_certification": CertificationLevel.BASIC.value,
    }
    payload.update(overrides)
    return payload


def create_docent_assignment_payload(docent_id: str, service_date: str = DEFAULT_MONDAY) -> Json:
    return {"docent_id": docent_id, "service_date": service_date}


def create_school_reservation_payload(
    museum_id: str,
    program_id: str,
    **overrides: Any,
) -> Json:
    n = _seq()
    payload: Json = {
        "museum_id": museum_id,
        "program_id": program_id,
        "school_name": f"School Group {n}",
        "headcount": 10,
        # The default visit date is a Monday, matching the default program's
        # day_of_week so the happy path confirms rather than failing the
        # weekday gate.
        "visit_date": DEFAULT_MONDAY,
    }
    payload.update(overrides)
    return payload


# ── Collection objects & loans ───────────────────────────────────────────────
def create_collection_object_payload(**overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "accession_number": f"2026.{n:04d}",
        "title": f"Collection Object {n}",
        # 50,000,000 cents sits below the courier-required threshold so the
        # default terms are acceptable without a courier.
        "declared_value_cents": 50_000_000,
        "is_cultural_property": False,
    }
    payload.update(overrides)
    return payload


def create_loan_agreement_payload(**overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "borrower_institution": f"Borrowing Institution {n}",
        "loan_start_date": DEFAULT_LOAN_START_DATE,
        "loan_end_date": DEFAULT_LOAN_END_DATE,
        "declared_value_cents": 50_000_000,
        "coverage_type": CoverageType.INSURANCE.value,
        "courier_required": False,
    }
    payload.update(overrides)
    return payload


def counter_loan_payload(expected_loan_version: int, **term_overrides: Any) -> Json:
    """Counter-round payload: the OCC field plus only the term fields being
    amended; None-valued terms are omitted (unprovided fields stay as-is)."""
    payload: Json = {"expected_loan_version": expected_loan_version}
    payload.update({k: v for k, v in term_overrides.items() if v is not None})
    return payload


def create_condition_report_payload(**overrides: Any) -> Json:
    payload: Json = {
        "report_kind": ReportKind.OUTBOUND.value,
        "condition_summary": "No defects observed on inspection.",
        "damage_noted": False,
    }
    payload.update(overrides)
    return payload


def decide_condition_report_payload(outcome: str) -> Json:
    return {"outcome": outcome}


# ── Collection reviews ───────────────────────────────────────────────────────
def create_acquisition_review_payload(fund_id: str, **overrides: Any) -> Json:
    """ACQUISITION pairing: fund_id + estimated_cost_cents +
    proposed_object_title, with object_id absent (PRD §3.6)."""
    n = _seq()
    payload: Json = {
        "review_kind": ReviewKind.ACQUISITION.value,
        "fund_id": fund_id,
        "proposed_object_title": f"Proposed Acquisition {n}",
        "estimated_cost_cents": 1000,
    }
    payload.update(overrides)
    return payload


def create_deaccession_review_payload(object_id: str, **overrides: Any) -> Json:
    """DEACCESSION pairing: object_id + disposal_method, with fund_id absent
    (PRD §3.6)."""
    payload: Json = {
        "review_kind": ReviewKind.DEACCESSION.value,
        "object_id": object_id,
        "disposal_method": DisposalMethod.TRANSFER.value,
    }
    payload.update(overrides)
    return payload


def decide_review_payload(outcome: str, expected_review_version: int) -> Json:
    return {"outcome": outcome, "expected_review_version": expected_review_version}


def execute_review_payload(actual_cost_cents: Optional[int] = None) -> Json:
    return _drop_none({"actual_cost_cents": actual_cost_cents})


# ── Funds & expenditures ─────────────────────────────────────────────────────
def create_fund_payload(**overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "fund_code": f"FUND-{n:04d}",
        "fund_type": FundType.TRUST.value,
        "appropriation_cents": 1_000_000,
    }
    payload.update(overrides)
    return payload


def set_fund_status_payload(status: str) -> Json:
    return {"status": status}


def create_expenditure_payload(**overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "amount_cents": 1000,
        "activity_type": ActivityType.OPERATIONS.value,
        "memo": f"Expenditure memo {n}",
    }
    payload.update(overrides)
    return payload


# ── Research access ──────────────────────────────────────────────────────────
def create_research_access_request_payload(object_id: str, **overrides: Any) -> Json:
    n = _seq()
    payload: Json = {
        "object_id": object_id,
        "scholar_name": f"Scholar {n}",
        "research_topic": f"Research topic {n}",
        "visit_start_date": DEFAULT_RESEARCH_VISIT_START,
        "visit_end_date": DEFAULT_RESEARCH_VISIT_END,
    }
    payload.update(overrides)
    return payload


def decide_research_payload(outcome: str) -> Json:
    return {"outcome": outcome}
