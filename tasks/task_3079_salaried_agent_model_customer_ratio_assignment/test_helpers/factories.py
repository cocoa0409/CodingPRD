"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import (
    DEFAULT_LOGICAL_CLOCK,
    TEST_DEFAULTS,
)


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def region_payload(**overrides) -> dict:
    payload = {
        "name": f"{TEST_DEFAULTS['REGION_NAME']} {_uid()}",
        "service_area_codes": list(TEST_DEFAULTS["SERVICE_AREA_CODES"]),
        "traditional_commission_pct": TEST_DEFAULTS["TRADITIONAL_COMMISSION_PCT"],
        "target_client_ratio": TEST_DEFAULTS["TARGET_CLIENT_RATIO"],
    }
    payload.update(overrides)
    return payload


def agent_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Ada Lead {_uid()}",
        "agent_kind": "LEAD",
        "home_zip": TEST_DEFAULTS["SERVICE_AREA_CODES"][0],
        "base_salary_cents": TEST_DEFAULTS["AGENT_BASE_SALARY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def client_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Client {_uid()}",
        "email": f"{_uid()}@example.com",
        "service_area_code": TEST_DEFAULTS["SERVICE_AREA_CODES"][0],
        "need_kind": "BUY",
    }
    defaults.update(overrides)
    return defaults


def transaction_payload(**overrides) -> dict:
    payload: dict = {}
    payload.update(overrides)
    return payload


def survey_payload(agent_id: str, **overrides) -> dict:
    payload = {"agent_id": agent_id}
    payload.update(overrides)
    return payload


def listing_agreement_payload(client_id: str, expected_region_version: int, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
        "list_fee_rate_pct": TEST_DEFAULTS["LIST_FEE_RATE_PCT"],
        "service_tier": "FULL_SERVICE",
        "expected_region_version": expected_region_version,
    }
    payload.update(overrides)
    return payload


def tour_payload(client_id: str, scheduled_at: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "scheduled_at": scheduled_at,
        "access_instructions": TEST_DEFAULTS["ACCESS_INSTRUCTIONS"],
    }
    payload.update(overrides)
    return payload


def referral_payload(client_id: str, expected_region_version: int, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "partner_name": f"Cascade Realty {_uid()}",
        "referral_fee_bps": TEST_DEFAULTS["REFERRAL_FEE_BPS"],
        "split_policy": "SPLIT_50_PARTNER",
        "expected_region_version": expected_region_version,
    }
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str = DEFAULT_LOGICAL_CLOCK) -> dict:
    return {"current_utc": current_utc}