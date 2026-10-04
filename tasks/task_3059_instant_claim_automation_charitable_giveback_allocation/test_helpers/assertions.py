"""Entity assertions and domain invariant checkers.

Assertion helpers deliberately check only the fields the PRD commits to
returning for each resource; computed fields are asserted in the specific
tests that the design indices pin them for.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def _assert_append_only_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )


def assert_rate_filing(data: dict):
    _assert_common_fields(data, "RateFiling")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")
    assert data["filing_mode"] in ("ABSOLUTE_CENTS", "PCT_OF_PREMIUM")
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["max_flat_fee_pct"], (int, float))


def assert_fee_config(data: dict):
    _assert_common_fields(data, "FeeConfig")
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["filing_id"], str)


def assert_treaty(data: dict):
    _assert_common_fields(data, "ReinsuranceTreaty")
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert 0 < data["quota_share_pct"] < 1


def assert_cause(data: dict):
    _assert_common_fields(data, "Cause")
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_cohort(data: dict):
    _assert_common_fields(data, "Cohort")
    assert data["status"] in ("OPEN", "CLOSED", "DONATED", "EXPIRED")
    for field in (
        "premium_pool_cents",
        "fee_retained_cents",
        "reinsurance_ceded_cents",
        "claims_pot_cents",
        "retained_claims_actual_cents",
        "retained_claims_reserved_cents",
        "giveback_actual_cents",
        "giveback_projected_cents",
    ):
        assert isinstance(data[field], int), f"Cohort.{field} must be integer cents"


def assert_policyholder(data: dict):
    _assert_common_fields(data, "Policyholder")
    assert data["status"] in ("ACTIVE", "DEBARRED")
    assert isinstance(data["fraud_strike_count"], int)
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_quote(data: dict):
    _assert_common_fields(data, "Quote")
    assert data["status"] in ("OPEN", "BOUND", "EXPIRED")
    assert data["coverage_amount_cents"] > 0
    assert data["premium_cents"] > 0


def assert_application(data: dict):
    _assert_common_fields(data, "PolicyApplication")
    assert data["status"] in ("UNDER_REVIEW", "APPROVED", "DECLINED")
    assert isinstance(data["behavioral_signal_count"], int)


def assert_policy(data: dict):
    _assert_common_fields(data, "Policy")
    assert data["status"] in ("ACTIVE", "LAPSED", "CANCELLED")
    assert data["annual_premium_cents"] > 0
    assert isinstance(data["premium_paid_cents"], int)
    assert isinstance(data["premium_outstanding_cents"], int)
    assert data["premium_outstanding_cents"] >= 0
    assert isinstance(data["fraud_flag"], bool)


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert data["status"] in (
        "FNOL_SUBMITTED",
        "AUTO_APPROVED",
        "ESCALATED",
        "PAID",
        "DENIED",
        "APPEALED",
    )
    assert data["claimed_amount_cents"] > 0
    assert 0 <= data["fraud_score"] <= 1
    assert isinstance(data["appeal_count"], int)


def assert_claim_payment(data: dict):
    """Append-only: id + created_at only; no updated_at/version per PRD §2.4."""
    _assert_append_only_fields(data, "ClaimPayment")
    assert data["status"] in ("SETTLED", "VOIDED")
    assert isinstance(data["amount_cents"], int)


def assert_ledger_entry(data: dict):
    """Append-only: id + created_at only; no updated_at/version per PRD §2.4."""
    _assert_append_only_fields(data, "PolicyLedgerEntry")
    assert data["kind"] in (
        "PREMIUM_CHARGE",
        "FEE_RETAINED",
        "REINSURANCE_CEDED",
        "CLAIM_PAYOUT",
        "CLAIM_PAYOUT_REVERSAL",
    )
    assert isinstance(data["amount_cents"], int)


def assert_appeal(data: dict):
    _assert_common_fields(data, "Appeal")
    assert data["status"] in ("PENDING", "UPHELD", "OVERTURNED")


def assert_cohort_ledger_invariants(cohort: dict):
    """Premium waterfall conservation on the cohort aggregates."""
    assert cohort["claims_pot_cents"] == (
        cohort["premium_pool_cents"]
        - cohort["fee_retained_cents"]
        - cohort["reinsurance_ceded_cents"]
    ), "claims pot must equal pool minus fee minus ceded"
    assert cohort["giveback_actual_cents"] == max(
        0, cohort["claims_pot_cents"] - cohort["retained_claims_actual_cents"]
    )
    assert cohort["giveback_projected_cents"] == max(
        0, cohort["claims_pot_cents"] - cohort["retained_claims_reserved_cents"]
    )
