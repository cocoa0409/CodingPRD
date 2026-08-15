"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_iso8601(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp (accepting trailing Z and optional
    fractional digits) into an aware datetime for value comparison.

    PRD pins the *values* of computed timestamps (e.g. `sla_expires_at` is
    "creation plus 72 hours", `due_at` is "confirmed_at plus 5 days") but states
    a fractional-digit format only for `api_request_timestamp` (§2.2) and
    `created_at`/`updated_at` (§2.4) — so tests must compare computed timestamps
    by instant, not by exact string."""
    assert is_iso8601_timestamp(ts), f"not a valid ISO 8601 timestamp: {ts!r}"
    s = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["cardholder_name"], str) and data["cardholder_name"]
    assert isinstance(data["home_country"], str) and data["home_country"]
    assert data["account_status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["open_alert_count"], int)
    assert isinstance(data["rolling_90d_loss_cents"], int)
    assert data["risk_tier"] in ["LOW", "MEDIUM", "HIGH"]


def assert_card(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["pan_token"], str) and data["pan_token"]
    assert data["product_type"] in ["DEBIT", "CREDIT"]
    assert data["network"] in ["VISA", "MASTERCARD"]
    assert data["card_status"] in ["ACTIVE", "SOFT_BLOCKED", "HARD_CLOSED", "REPLACED"]
    assert data["fraud_flag"] in ["CLEAN", "WATCH", "COMPROMISED"]
    assert data.get("block_reason") in [
        None, "ANALYST_REVIEW", "CONFIRMED_FRAUD", "CUSTOMER_REQUEST", "COMPROMISE_EVENT",
    ]


def assert_rule_set(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["scope"] in ["GLOBAL", "DEBIT_CARD", "CREDIT_CARD"]
    assert isinstance(data["base_score"], int)
    assert isinstance(data["review_threshold"], int)
    assert isinstance(data["decline_threshold"], int)
    assert data["review_threshold"] < data["decline_threshold"]
    assert isinstance(data["amount_tiers"], list) and len(data["amount_tiers"]) >= 1
    for key in ("CHIP", "CONTACTLESS", "CNP", "ATM"):
        assert key in data["channel_weights"], f"channel_weights missing {key}"
    assert isinstance(data["cross_border_weight"], int)
    assert isinstance(data["watch_weight"], int)
    assert isinstance(data["compromised_weight"], int)
    assert data["ruleset_status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_auth_transaction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["card_id"], str) and data["card_id"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["channel"] in ["CHIP", "CONTACTLESS", "CNP", "ATM"]
    assert is_iso8601_timestamp(data.get("scored_at", "")), "scored_at must be ISO 8601"
    assert data["decision"] in ["APPROVE", "REVIEW", "DECLINE"]
    assert data["decision_reason"] in ["RULE_SCORE", "CARD_BLOCKED"]
    assert data["final_disposition"] in ["UNDISPOSED", "CONFIRMED_FRAUD", "CONFIRMED_LEGIT"]


def assert_fraud_alert(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["card_id"], str) and data["card_id"]
    assert data["source"] in ["SCORING_REVIEW", "MANUAL"]
    assert data["alert_status"] in [
        "OPEN", "IN_REVIEW", "CONTACT_PENDING",
        "RESOLVED_FRAUD", "RESOLVED_LEGIT", "EXPIRED",
    ]
    assert isinstance(data["band_points"], int)
    assert isinstance(data["priority"], int)
    assert isinstance(data["reopen_count"], int)
    assert data.get("resolution") in [None, "FRAUD", "LEGIT"]
    assert isinstance(data["fraud_credit_cents"], int)
    assert is_iso8601_timestamp(data.get("sla_expires_at", "")), "sla_expires_at must be ISO 8601"


def assert_verification_contact(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["alert_id"], str) and data["alert_id"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert data["channel"] in ["VOICE", "SMS", "EMAIL", "IN_APP"]
    assert data["contact_status"] in ["PENDING", "COMPLETED"]
    assert data.get("outcome") in [None, "CONFIRMED_FRAUD", "CONFIRMED_LEGIT", "UNREACHABLE"]
    assert is_iso8601_timestamp(data.get("contacted_at", "")), "contacted_at must be ISO 8601"


def assert_compromised_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["network_source"] in ["CAMS", "ADC"]
    assert isinstance(data["event_reference"], str) and data["event_reference"]
    assert data["event_status"] in ["RECEIVED", "CONFIRMED", "CLOSED"]
    assert isinstance(data["affected_card_count"], int)


def assert_reissue_decision(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["event_id"], str) and data["event_id"]
    assert isinstance(data["card_id"], str) and data["card_id"]
    assert data["decision"] in ["PENDING", "APPROVED", "DECLINED", "AUTO_APPROVED"]
    assert isinstance(data["exposure_cents"], int)
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"


def assert_travel_notice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["card_id"], str) and data["card_id"]
    assert isinstance(data["region_country"], str) and data["region_country"]
    assert data["notice_status"] in ["ACTIVE", "CANCELLED", "EXPIRED"]


def assert_chargeback_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["auth_transaction_id"], str) and data["auth_transaction_id"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["provisional_credit_cents"], int)
    assert data["cb_status"] in [
        "FILED", "PROVISIONAL_CREDIT_POSTED", "REPRESENTMENT_FILED",
        "RESOLVED_WON", "RESOLVED_LOST", "WITHDRAWN",
    ]


def assert_loss_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["transaction_ids"], list) and len(data["transaction_ids"]) >= 1
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["tolerance_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert isinstance(data["written_off_cents"], int)
    assert data["loss_status"] in [
        "ESTIMATED", "BOOKED", "FINALIZED",
        "PARTIALLY_RECOVERED", "FULLY_RECOVERED", "WRITTEN_OFF",
    ]


def assert_recovery_filing(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["loss_entry_id"], str) and data["loss_entry_id"]
    assert isinstance(data["network_reference"], str) and data["network_reference"]
    assert isinstance(data["claimed_cents"], int)
    assert data["filing_status"] in ["FILED", "ACCEPTED", "REJECTED", "PAID", "REVERSED"]


def assert_fraud_ring(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["signal_type"] == "COMMON_MERCHANT"
    assert isinstance(data["merchant_id"], str) and data["merchant_id"]
    assert data["ring_status"] in ["SUSPECTED", "CONFIRMED", "DISMISSED"]
    assert isinstance(data["member_count"], int)


def assert_ring_membership(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["ring_id"], str) and data["ring_id"]
    assert isinstance(data["account_id"], str) and data["account_id"]
    assert isinstance(data["evidence_txn_count"], int)


def assert_loss_outstanding_invariant(loss: dict):
    """INV-LOSS: outstanding = final - paid(PAID filings) - written_off, and never negative
    once finalized."""
    assert loss["outstanding_cents"] >= 0, "outstanding_cents must never go negative"
    if loss["loss_status"] in ("FINALIZED", "PARTIALLY_RECOVERED"):
        assert loss["outstanding_cents"] > 0, "non-terminal finalized loss must retain positive outstanding"
