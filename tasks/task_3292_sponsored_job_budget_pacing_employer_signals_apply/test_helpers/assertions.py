"""Entity assertions and domain invariant checkers.

Each `assert_<entity>` validates the response shape the PRD pins for that
resource. `assert_*_invariants` check the conserved quantities that must hold
after any operation.
"""
import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

from .constants import (
    MIN_MULTIPLIER,
    MAX_MULTIPLIER,
    MULTIPLIER_PRECISION,
    RELEVANCE_MAX,
)

COMMON_FIELD_ENTITIES = "id, created_at, updated_at and version"
APPEND_ONLY_ENTITIES = "id and created_at only"


# ─── Common field helpers ─────────────────────────────

def assert_common_fields(data: dict, entity: str = "entity"):
    """Id + created_at + updated_at + version, for the mutable family."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an int"
    assert data["version"] >= 1, f"{entity}.version starts at its creation value"


def assert_append_only_fields(data: dict, entity: str = "entity"):
    """id + created_at only; no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{entity} is append-only: no updated_at"
    assert "version" not in data, f"{entity} is append-only: no version"


# ─── Employer ─────────────────────────────────────────

def assert_employer(data: dict):
    assert_common_fields(data, "Employer")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("domain"), str) and data["domain"]
    assert data.get("ats_provider") in ("WORKDAY", "GREENHOUSE", "LEVER", "TALEO", "NONE")
    assert data.get("status") in ("ACTIVE", "SUSPENDED")
    assert data.get("billing_status") in ("CURRENT", "FROZEN")
    assert isinstance(data.get("quality_score"), int)
    assert 0 <= data["quality_score"] <= 100
    assert isinstance(data.get("response_rate_bps"), int)
    assert 0 <= data["response_rate_bps"] <= 10000
    assert isinstance(data.get("balance_cents"), int)


def assert_employer_invariants(data: dict):
    assert data["quality_score"] >= 0
    assert data["quality_score"] <= 100
    assert data["response_rate_bps"] >= 0
    assert data["response_rate_bps"] <= 10000


# ─── JobSeeker ────────────────────────────────────────

def assert_job_seeker(data: dict):
    assert_common_fields(data, "JobSeeker")
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("status") == "ACTIVE"


# ─── Campaign ─────────────────────────────────────────

def assert_campaign(data: dict):
    assert_common_fields(data, "Campaign")
    assert is_valid_uuid(data.get("employer_id", "")), "Campaign.employer_id must be a UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("pricing_model") in ("CPC", "CPA")
    assert isinstance(data.get("daily_budget_cents"), int)
    assert isinstance(data.get("total_budget_cents"), int)
    assert data.get("status") in ("DRAFT", "ACTIVE", "PACING_HOLD", "PAUSED", "COMPLETED")
    assert isinstance(data.get("spent_cents"), int)
    assert isinstance(data.get("daily_spent_cents"), int)
    assert isinstance(data.get("held_cents"), int)
    assert is_iso8601_timestamp(data.get("day_open_date", "")), (
        "Campaign.day_open_date must be an ISO 8601 UTC timestamp"
    )
    assert_campaign_invariants(data)


def assert_campaign_invariants(data: dict):
    """Conserved quantities that must hold after ANY operation."""
    assert data["spent_cents"] >= 0, "spent_cents cannot be negative"
    assert data["daily_spent_cents"] >= 0, "daily_spent_cents cannot be negative"
    assert data["held_cents"] >= 0, "held_cents cannot be negative"
    assert data["total_budget_cents"] >= 0
    assert data["daily_budget_cents"] >= 0
    assert_cost_precision(data["spent_cents"])
    assert_cost_precision(data["held_cents"])


# ─── SponsoredJob ─────────────────────────────────────

def assert_sponsored_job(data: dict):
    assert_common_fields(data, "SponsoredJob")
    assert is_valid_uuid(data.get("campaign_id", "")), "SponsoredJob.campaign_id must be a UUID"
    assert is_valid_uuid(data.get("job_posting_id", "")), (
        "SponsoredJob.job_posting_id must be a UUID"
    )
    assert isinstance(data.get("cpc_bid_cents"), int)
    assert isinstance(data.get("cpa_bid_cents"), int)
    assert data.get("status") in ("DRAFT", "ELIGIBLE", "PAUSED", "BUDGET_HOLD")
    for f in ("impressions", "clicks", "applications"):
        assert isinstance(data.get(f), int), f"SponsoredJob.{f} must be an int"
        assert data[f] >= 0, f"SponsoredJob.{f} cannot be negative"


def assert_pacing_multiplier(value) -> None:
    """Both multipliers are clamped into the closed interval [0.0, 2.0]."""
    assert isinstance(value, (int, float)), "pacing multiplier must be a number"
    assert MIN_MULTIPLIER <= float(value) <= MAX_MULTIPLIER, (
        f"pacing multiplier {value} outside [0.0, 2.0]"
    )
    assert round(float(value), MULTIPLIER_PRECISION) == pytest.approx(float(value)), (
        f"pacing multiplier {value} not rounded to 3 decimal places"
    )


# ─── JobPosting / JobPostingVersion ───────────────────

def assert_job_posting(data: dict):
    assert_common_fields(data, "JobPosting")
    assert is_valid_uuid(data.get("employer_id", "")), "JobPosting.employer_id must be a UUID"
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("location"), str)
    assert data.get("state") in ("DRAFT", "ACTIVE", "STALE", "EXPIRED", "SUSPENDED")
    assert data.get("current_freshness") in ("FRESH", "STALE", "EXPIRED", None)
    assert data.get("apply_mode") in ("HOSTED", "ATS_REDIRECT")
    assert isinstance(data.get("apply_started_count"), int)
    assert isinstance(data.get("apply_completed_count"), int)


def assert_job_posting_version(data: dict):
    assert_common_fields(data, "JobPostingVersion")
    assert is_valid_uuid(data.get("job_posting_id", "")), (
        "JobPostingVersion.job_posting_id must be a UUID"
    )
    assert isinstance(data.get("content_hash"), str) and data["content_hash"]
    assert is_iso8601_timestamp(data.get("ingested_at", "")), (
        "JobPostingVersion.ingested_at must be an ISO 8601 UTC timestamp"
    )
    assert data.get("freshness") in ("FRESH", "STALE", "EXPIRED")


# ─── Assessment ───────────────────────────────────────

def assert_assessment(data: dict):
    assert_common_fields(data, "Assessment")
    assert is_valid_uuid(data.get("job_posting_id", "")), (
        "Assessment.job_posting_id must be a UUID"
    )
    assert isinstance(data.get("questions"), list)
    assert isinstance(data.get("pass_threshold"), int)
    assert data.get("status") == "PUBLISHED"


# ─── Application ──────────────────────────────────────

def assert_application(data: dict):
    assert_common_fields(data, "Application")
    assert is_valid_uuid(data.get("job_posting_id", "")), (
        "Application.job_posting_id must be a UUID"
    )
    assert is_valid_uuid(data.get("job_seeker_id", "")), (
        "Application.job_seeker_id must be a UUID"
    )
    assert data.get("status") in ("STARTED", "COMPLETED", "RESPONDED", "CLOSED")
    assert is_iso8601_timestamp(data.get("started_at", "")), (
        "Application.started_at must be an ISO 8601 UTC timestamp"
    )
    assert data.get("disposition") in ("NONE", "REVIEWED", "INTERVIEW", "REJECTED", "HIRED")


# ─── Append-only records ──────────────────────────────

def assert_apply_event(data: dict):
    assert_append_only_fields(data, "ApplyEvent")
    assert is_valid_uuid(data.get("application_id", "")), (
        "ApplyEvent.application_id must be a UUID"
    )
    assert data.get("kind") in ("STARTED", "COMPLETED", "INVALID_CLICK")
    assert data.get("source") in ("HOSTED", "REDIRECT", "PIXEL")
    assert is_iso8601_timestamp(data.get("occurred_at", "")), (
        "ApplyEvent.occurred_at must be an ISO 8601 UTC timestamp"
    )


def assert_budget_ledger_entry(data: dict):
    assert_append_only_fields(data, "BudgetLedger")
    assert is_valid_uuid(data.get("campaign_id", "")), (
        "BudgetLedger.campaign_id must be a UUID"
    )
    assert data.get("entry_type") in ("HOLD", "COMMIT", "RELEASE", "REFUND")
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("reference_code"), str) and data["reference_code"]


# ─── SponsorEvent ─────────────────────────────────────

def assert_sponsor_event(data: dict):
    assert_common_fields(data, "SponsorEvent")
    assert is_valid_uuid(data.get("campaign_id", "")), "SponsorEvent.campaign_id must be a UUID"
    assert data.get("event_type") in ("IMPRESSION", "CLICK", "APPLICATION")
    assert isinstance(data.get("billable"), bool)
    assert isinstance(data.get("cost_cents"), int)
    assert data["cost_cents"] >= 0
    assert data.get("status") in ("RECORDED", "BILLED", "REFUNDED")
    assert is_iso8601_timestamp(data.get("occurred_at", "")), (
        "SponsorEvent.occurred_at must be an ISO 8601 UTC timestamp"
    )


# ─── PacingHold ───────────────────────────────────────

def assert_pacing_hold(data: dict):
    assert_common_fields(data, "PacingHold")
    assert is_valid_uuid(data.get("sponsored_job_id", "")), (
        "PacingHold.sponsored_job_id must be a UUID"
    )
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] > 0
    assert data.get("status") in ("ACTIVE", "COMMITTED", "RELEASED")


# ─── JobAlertSubscription ─────────────────────────────

def assert_alert_subscription(data: dict):
    assert_common_fields(data, "JobAlertSubscription")
    assert is_valid_uuid(data.get("job_seeker_id", "")), (
        "JobAlertSubscription.job_seeker_id must be a UUID"
    )
    assert isinstance(data.get("keywords"), str)
    assert isinstance(data.get("location"), str)
    assert isinstance(data.get("notified_posting_ids"), list)
    assert data.get("status") == "ACTIVE"


# ─── Domain invariant helpers ─────────────────────────

def assert_relevance_score_shape(data: dict):
    """A match row's relevance score is an integer within [0, 100]."""
    assert isinstance(data.get("relevance_score"), int), "relevance_score must be an int"
    assert 0 <= data["relevance_score"] <= RELEVANCE_MAX


def assert_ledger_net_equals_spent(entries, spent_cents: int):
    """spent_cents == sum(COMMIT) + sum(REFUND), the ledger being authoritative."""
    net = sum(e["amount_cents"] for e in entries if e["entry_type"] == "COMMIT")
    net += sum(e["amount_cents"] for e in entries if e["entry_type"] == "REFUND")
    assert net == spent_cents, (
        f"ledger net {net} disagrees with campaign spent_cents {spent_cents}"
    )


def assert_held_cents_equals_active_holds(holds, held_cents: int):
    """held_cents == sum of amounts over ACTIVE holds on the campaign."""
    total = sum(h["amount_cents"] for h in holds if h["status"] == "ACTIVE")
    assert total == held_cents, (
        f"ACTIVE hold total {total} disagrees with campaign held_cents {held_cents}"
    )