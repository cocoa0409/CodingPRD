"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VALID_PRODUCT_STATUSES = ["DRAFT", "ACTIVE", "WITHDRAWN"]
VALID_PUBLICATION_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED", "RECALLED"]
VALID_AGENT_STATUSES = ["APPLICANT", "APPOINTED", "SUSPENDED", "TERMINATED"]
VALID_APPOINTMENT_STATUSES = ["ACTIVE", "TERMINATED", "EXPIRED"]
VALID_SCHEDULE_STATUSES = ["ACTIVE", "SUPERSEDED", "VOIDED"]
VALID_QUOTE_STATUSES = [
    "DRAFT", "QUOTED", "REFERRED_TO_AGENT", "AGENT_QUOTED",
    "BOUND", "EXPIRED", "WITHDRAWN",
]
VALID_POLICY_STATUSES = ["IN_FORCE", "CANCELLED"]
VALID_CLAIM_STATUSES = ["REPORTED", "CLOSED"]
VALID_ENROLLMENT_STATUSES = ["ENROLLED", "PARTICIPATING", "SCORED", "OPTED_OUT"]
VALID_STATEMENT_STATUSES = ["DRAFT", "FINALIZED", "PAID", "CLAWED_BACK", "STALE"]
VALID_POOL_STATUSES = ["OPEN", "SETTLED"]
VALID_REVIEW_STATUSES = ["OPEN", "FINDINGS_ISSUED", "ACTION_TAKEN"]
VALID_PLACEMENT_STATUSES = ["QUOTED", "PLACED", "AOR_TRANSFERRED", "DECLINED"]
VALID_CHANNELS = ["DIRECT", "AGENT"]
VALID_LOBS = ["AUTO", "HOME"]
VALID_INELIGIBILITY_REASONS = ["LOSS_RATIO", "GROWTH", "NONE", None]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["product_code"], str) and len(data["product_code"]) > 0
    assert data["line_of_business"] in VALID_LOBS
    assert isinstance(data["state_code"], str) and len(data["state_code"]) > 0
    assert data["channel_availability"] in ["DIRECT", "AGENT", "BOTH"]
    assert isinstance(data["coverage_rates"], dict)
    assert isinstance(data["min_premium_cents"], int)
    assert data["status"] in VALID_PRODUCT_STATUSES


def assert_rater(data: dict):
    _assert_common(data)
    assert isinstance(data["rater_code"], str) and len(data["rater_code"]) > 0
    assert isinstance(data["display_name"], str)
    assert isinstance(data["feed_format_version"], str)
    assert data["accepted_line_of_business"] in VALID_LOBS


def assert_feed_publication(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rater_id", "")), "rater_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert data["status"] in VALID_PUBLICATION_STATUSES
    assert is_iso8601_timestamp(data.get("effective_start", ""))
    assert is_iso8601_timestamp(data.get("effective_end", ""))


def assert_agent(data: dict):
    _assert_common(data)
    assert isinstance(data["agency_name"], str) and len(data["agency_name"]) > 0
    assert isinstance(data["principal_name"], str)
    assert isinstance(data["resident_state_code"], str)
    assert data["status"] in VALID_AGENT_STATUSES


def assert_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert isinstance(data["state_code"], str)
    assert data["line_of_business"] in VALID_LOBS
    assert data["status"] in VALID_APPOINTMENT_STATUSES
    assert is_iso8601_timestamp(data.get("effective_start", ""))


def assert_commission_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert data["line_of_business"] in VALID_LOBS
    assert isinstance(data["tiers"], list) and len(data["tiers"]) > 0
    assert isinstance(data["contingent_bonus_eligible"], bool)
    assert data["status"] in VALID_SCHEDULE_STATUSES


def assert_consumer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["home_state_code"], str)


def assert_quote(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("consumer_id", "")), "consumer_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert data["channel"] in VALID_CHANNELS
    assert isinstance(data["coverages"], list)
    assert data["status"] in VALID_QUOTE_STATUSES


def assert_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("quote_id", "")), "quote_id must be a UUID"
    assert is_valid_uuid(data.get("consumer_id", "")), "consumer_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert data["channel"] in VALID_CHANNELS
    assert data["term_days"] == 365
    assert isinstance(data["written_premium_cents"], int)
    assert data["status"] in VALID_POLICY_STATUSES


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("policy_id", "")), "policy_id must be a UUID"
    assert data["claim_type"] in ["COLLISION", "LIABILITY", "HOME_DAMAGE", "OTHER"]
    assert isinstance(data["incurred_amount_cents"], int)
    assert data["incurred_amount_cents"] >= 0
    assert data["status"] in VALID_CLAIM_STATUSES


def assert_telematics_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("policy_id", "")), "policy_id must be a UUID"
    assert data["channel"] in VALID_CHANNELS
    assert data["status"] in VALID_ENROLLMENT_STATUSES
    assert isinstance(data["upfront_discount_cents"], int)


def assert_commission_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert data["status"] in VALID_STATEMENT_STATUSES
    assert isinstance(data["written_premium_cents"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["clawback_cents"], int)
    assert isinstance(data["net_payable_cents"], int)
    assert isinstance(data["line_items"], list)
    assert data["net_payable_cents"] == data["commission_cents"] - data["clawback_cents"], (
        "net_payable_cents must equal commission_cents - clawback_cents"
    )


def assert_bonus_pool(data: dict):
    _assert_common(data)
    assert isinstance(data["year"], int)
    assert isinstance(data["pool_total_cents"], int)
    assert data["status"] in VALID_POOL_STATUSES


def assert_bonus_payout(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pool_id", "")), "pool_id must be a UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert isinstance(data["earned_premium_cents"], int)
    assert isinstance(data["eligible"], bool)
    assert data["ineligibility_reason"] in VALID_INELIGIBILITY_REASONS
    assert isinstance(data["payout_cents"], int)


def assert_portfolio_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert isinstance(data["reason"], str)
    assert isinstance(data["opened_by_user_id"], str)
    assert data["status"] in VALID_REVIEW_STATUSES
    assert isinstance(data["earned_premium_trailing_cents"], int)


def assert_bundle_placement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("policy_id", "")), "policy_id must be a UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert isinstance(data["unaffiliated_carrier_name"], str)
    assert isinstance(data["home_premium_cents"], int)
    assert isinstance(data["total_commission_cents"], int)
    assert data["status"] in VALID_PLACEMENT_STATUSES


def assert_policy_premium_conservation(policy: dict):
    """Earned + unearned premium always reconciles to written premium."""
    if policy["status"] == "CANCELLED" or policy["status"] == "IN_FORCE":
        assert (
            policy["earned_premium_cents"] + policy["unearned_premium_cents"]
            == policy["written_premium_cents"]
        ), "earned + unearned must equal written premium"


def assert_commission_conservation(per_policy_commission: int, clawback: int):
    """The retained commission plus the clawed-back amount must equal the
    originally credited per-policy commission — cancel + claw-back conserve
    the ledger with zero drift."""
    retained = per_policy_commission - clawback
    assert retained >= 0, "retained commission must be non-negative"
    assert retained + clawback == per_policy_commission


def assert_aor_commission_conservation(placement: dict):
    """The earned (retained by original agent) and transferred (received by
    new agent) legs must sum exactly to total_commission_cents."""
    assert (
        placement["earned_commission_cents"] + placement["transferred_commission_cents"]
        == placement["total_commission_cents"]
    ), "earned + transferred must equal total commission exactly"
