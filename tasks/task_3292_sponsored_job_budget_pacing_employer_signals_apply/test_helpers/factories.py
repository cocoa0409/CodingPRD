"""Payload factories — one per creatable resource, client-supplied fields only.

Each factory returns a fresh dict so callers may mutate it freely; `overrides`
replace individual defaults without leaking into other calls.
"""
from .constants import TEST_DEFAULTS

DEFAULT_SEEKER_LOCATION = TEST_DEFAULTS["SEEKER_LOCATION"]
DEFAULT_POSTING_LOCATION = TEST_DEFAULTS["POSTING_LOCATION"]


def employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Employer Co",
        "domain": "test-employer.example",
        "ats_provider": "NONE",
    }
    defaults.update(overrides)
    return defaults


def job_seeker_payload(**overrides) -> dict:
    defaults = {
        "email": "seeker@test.example",
        "full_name": "Test Seeker",
        "location": DEFAULT_SEEKER_LOCATION,
    }
    defaults.update(overrides)
    return defaults


def campaign_payload(employer_id: str, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "name": "Test Campaign",
        "pricing_model": "CPC",
        "daily_budget_cents": TEST_DEFAULTS["DAILY_BUDGET_CENTS"],
        "total_budget_cents": TEST_DEFAULTS["TOTAL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def sponsored_job_payload(campaign_id: str, posting_id: str, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "job_posting_id": posting_id,
        "cpc_bid_cents": TEST_DEFAULTS["CPC_BID_CENTS"],
        "cpa_bid_cents": TEST_DEFAULTS["CPA_BID_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def job_posting_payload(employer_id: str, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "title": "Test Job Title",
        "location": DEFAULT_POSTING_LOCATION,
        "description_text": "A job description body for testing.",
        "apply_mode": "HOSTED",
    }
    defaults.update(overrides)
    return defaults


def ats_redirect_posting_payload(employer_id: str, url: str = "https://ats.example/apply/1",
                                 **overrides) -> dict:
    """A posting in ATS_REDIRECT mode with a valid absolute https destination."""
    defaults = job_posting_payload(
        employer_id,
        apply_mode="ATS_REDIRECT",
        apply_redirect_url=url,
    )
    defaults.update(overrides)
    return defaults


def posting_version_payload(external_posting_id: str, **overrides) -> dict:
    defaults = {"external_posting_id": external_posting_id}
    defaults.update(overrides)
    return defaults


def assessment_payload(posting_id: str, **overrides) -> dict:
    defaults = {
        "job_posting_id": posting_id,
        "questions": [
            {"prompt": "Are you authorized to work in this country?",
             "kind": "BOOLEAN", "required": True},
            {"prompt": "How many years of relevant experience do you have?",
             "kind": "NUMERIC", "required": True},
        ],
        "pass_threshold": 1,
    }
    defaults.update(overrides)
    return defaults


def application_payload(posting_id: str, seeker_id: str, **overrides) -> dict:
    defaults = {
        "job_posting_id": posting_id,
        "job_seeker_id": seeker_id,
    }
    defaults.update(overrides)
    return defaults


def disposition_payload(disposition: str = "REVIEWED") -> dict:
    return {"disposition": disposition}


def event_payload(campaign_id: str, sponsored_job_id: str, expected_campaign_version: int,
                  event_type: str = "CLICK", **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "sponsored_job_id": sponsored_job_id,
        "event_type": event_type,
        "device_fingerprint": "fp-default-1",
        "ip_hash": "ip-default-1",
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults


def hold_payload(amount_cents: int = 100) -> dict:
    return {"amount_cents": amount_cents}


def refund_payload(campaign_version: int, reason: str = "invalid click") -> dict:
    return {"reason": reason, "expected_campaign_version": campaign_version}


def alert_subscription_payload(seeker_id: str, **overrides) -> dict:
    defaults = {
        "job_seeker_id": seeker_id,
        "keywords": "engineer",
        "location": DEFAULT_SEEKER_LOCATION,
    }
    defaults.update(overrides)
    return defaults


def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}