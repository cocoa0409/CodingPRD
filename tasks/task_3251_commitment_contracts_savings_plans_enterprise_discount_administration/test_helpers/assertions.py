"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_billing_org(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["currency"], str)
    assert isinstance(data["max_hourly_commitment_cents"], int)
    assert isinstance(data["capacity_quota_units"], int)
    assert isinstance(data["current_period_index"], int)
    assert isinstance(data["unapplied_credit_cents"], int)
    assert isinstance(data["version"], int)


def assert_linked_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["org_id"], str)
    assert isinstance(data["version"], int)


def assert_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["lifecycle_status"] in (
        "NEGOTIATION", "ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED"
    )
    assert data["renewal_status"] in ("NONE", "RENEWAL_REVIEW", "RENEWED", "ABANDONED")
    assert isinstance(data["committed_spend_cents"], int)
    assert isinstance(data["consumed_commitment_cents"], int)
    assert isinstance(data["accrued_trueup_cents"], int)
    assert isinstance(data["version"], int)


def assert_discount_tier(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["threshold_cents"], int)
    assert 0 <= data["rate"] < 1


def assert_pricing_amendment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert 0 <= data["discount_rate"] < 1
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))


def assert_commitment_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["type"] in ("SAVINGS_PLAN", "RESERVED_CAPACITY")
    assert data["status"] in ("ACTIVE", "EXPIRED", "TERMINATED")
    assert isinstance(data["hourly_commitment_cents"], int)
    assert isinstance(data["units"], int)
    assert isinstance(data["version"], int)


def assert_usage_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("INGESTED", "BILLED")
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["period_index"], int)
    # append-only row: must NOT carry updated_at or version
    assert "updated_at" not in data, "usage records must not carry updated_at"
    assert "version" not in data, "usage records must not carry version"


def assert_credit_grant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("ISSUED", "DEPLETING", "EXHAUSTED", "EXPIRED", "REVOKED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["consumed_cents"], int)
    assert isinstance(data["forfeited_cents"], int)
    assert isinstance(data["remaining_cents"], int)
    assert isinstance(data["version"], int)


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("DRAFT", "FINALIZED", "DISPUTED", "SETTLED", "VOIDED")
    assert isinstance(data["period_index"], int)
    assert isinstance(data["total_due_cents"], int)
    assert isinstance(data["version"], int)


def assert_invoice_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["list_cents"], int)
    assert isinstance(data["amendment_discount_cents"], int)
    assert isinstance(data["plan_discount_cents"], int)
    assert isinstance(data["tier_discount_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["net_due_cents"], int)
    # append-only row: must NOT carry updated_at or version
    assert "updated_at" not in data, "invoice lines must not carry updated_at"
    assert "version" not in data, "invoice lines must not carry version"


def assert_trueup_charge(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["type"] in ("SHORTFALL", "EARLY_TERMINATION")
    assert data["status"] in ("ASSESSED", "BILLED", "WAIVED", "SETTLED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["version"], int)


def assert_renewal_forecast(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["variant"] in ("LINEAR", "COHORT_WEIGHTED")
    assert isinstance(data["forecast_cents"], int)
    assert isinstance(data["generated_period_index"], int)
    # append-only row: must NOT carry updated_at or version
    assert "updated_at" not in data, "renewal forecasts must not carry updated_at"
    assert "version" not in data, "renewal forecasts must not carry version"


def assert_credit_conservation(grant: dict):
    """PRD conservation invariant: amount == consumed + remaining + forfeited."""
    total = grant["consumed_cents"] + grant["remaining_cents"] + grant["forfeited_cents"]
    assert grant["amount_cents"] == total, (
        f"credit conservation violated: amount {grant['amount_cents']} != "
        f"consumed {grant['consumed_cents']} + remaining {grant['remaining_cents']} "
        f"+ forfeited {grant['forfeited_cents']}"
    )
