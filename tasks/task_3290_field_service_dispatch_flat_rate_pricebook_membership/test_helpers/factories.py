"""Payload factories — one per entity, input fields only."""
from . import constants as C


def create_branch_payload(**overrides) -> dict:
    payload = {
        "name": "Austin",
        "postal_code": C.POSTAL_CODE_AUSTIN,
        "daily_dispatch_capacity_hours": C.DEFAULT_BRANCH_CAPACITY_HOURS,
    }
    payload.update(overrides)
    return payload


def hire_technician_payload(**overrides) -> dict:
    payload = {
        "name": "Dana",
        "postal_code": C.POSTAL_CODE_AUSTIN,
        "skill_codes": [C.TECHNICIAN_SKILL_HVAC],
        "shift_segments": [
            {"start_utc": "2026-09-10T08:00:00Z", "end_utc": "2026-09-20T18:00:00Z"}
        ],
        "daily_capacity_hours": 40,
    }
    payload.update(overrides)
    return payload


def create_membership_plan_payload(**overrides) -> dict:
    payload = {
        "name": C.DEFAULT_PLAN_NAME,
        "annual_price_cents": C.DEFAULT_PLAN_PRICE_CENTS,
        "included_service_visit_count": C.DEFAULT_PLAN_VISIT_COUNT,
        "maintenance_visit_interval_days": C.DEFAULT_PLAN_INTERVAL_DAYS,
        "included_labor_discount_pct": C.DEFAULT_PLAN_LABOR_DISCOUNT_PCT,
        "status": "PUBLISHED",
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(**overrides) -> dict:
    payload = {"name": "Fall Tune-Up", "channel": "SEARCH", "spend_cents": 50000}
    payload.update(overrides)
    return payload


def create_pricebook_task_payload(**overrides) -> dict:
    payload = {
        "code": "HVAC-TUNE",
        "category": "HVAC",
        "display_name": "System Tune",
        "required_skill_code": C.TECHNICIAN_SKILL_HVAC,
        "estimated_hours": 1.0,
        "flat_rate_cents": 5000,
        "status": "PUBLISHED",
    }
    payload.update(overrides)
    return payload


def create_call_record_payload(**overrides) -> dict:
    payload = {
        "cs_user_id": "cs-77",
        "duration_seconds": 420,
        "recording_uri": "s3://calls/1188.wav",
        "started_at_utc": "2026-09-02T14:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(**overrides) -> dict:
    payload = {
        "customer_name": "Ada",
        "postal_code": C.POSTAL_CODE_AUSTIN,
        "window_start_utc": "2026-09-10T09:00:00Z",
        "window_end_utc": "2026-09-10T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def add_line_payload(**overrides) -> dict:
    payload = {"pricebook_task_code": "HVAC-TUNE"}
    payload.update(overrides)
    return payload


def sell_membership_payload(**overrides) -> dict:
    payload = {
        "homeowner_name": "Ada",
        "homeowner_postal_code": C.POSTAL_CODE_AUSTIN,
        "term_months": C.DEFAULT_TERM_MONTHS,
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def schedule_visit_payload(sequence_number: int, scheduled_date: str, **overrides) -> dict:
    payload = {"sequence_number": sequence_number, "scheduled_date": scheduled_date}
    payload.update(overrides)
    return payload


def completion_payload(description: str = C.LONG_COMPLETION_DESCRIPTION, **overrides) -> dict:
    payload = {"completion_description": description}
    payload.update(overrides)
    return payload


def override_request_payload(requested_price_cents: int, **overrides) -> dict:
    payload = {"requested_price_cents": requested_price_cents}
    payload.update(overrides)
    return payload


def decide_payload(decision: str, expected_appointment_version: int, **overrides) -> dict:
    payload = {
        "decision": decision,
        "expected_appointment_version": expected_appointment_version,
    }
    payload.update(overrides)
    return payload


def reprice_payload(expected_pricebook_task_version: int, **overrides) -> dict:
    payload = {"expected_pricebook_task_version": expected_pricebook_task_version}
    payload.update(overrides)
    return payload


def dispatch_payload(appointment_id: str, **overrides) -> dict:
    payload = {"appointment_id": appointment_id}
    payload.update(overrides)
    return payload


def incentive_statement_params(period_year: int = 2026, period_month: int = 9) -> dict:
    return {"period_year": period_year, "period_month": period_month}