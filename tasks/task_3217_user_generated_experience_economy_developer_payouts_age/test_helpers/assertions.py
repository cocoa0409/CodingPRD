"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VALID_USER_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
VALID_AGE_BANDS = ["CHILD", "TEEN", "ADULT"]
VALID_CHAT_FILTER_LEVELS = ["SAFE", "STANDARD", "ADULT"]
VALID_CHAT_MODES = ["RESTRICTED", "FILTERED", "OPEN"]
VALID_EXPERIENCE_STATUSES = ["DRAFT", "PENDING_REVIEW", "PUBLISHED", "SUSPENDED", "ARCHIVED"]
VALID_AGE_RATINGS = ["ALL", "NINE_PLUS", "THIRTEEN_PLUS", "SEVENTEEN_PLUS"]
VALID_SUBMISSION_STATUSES = [
    "QUEUED", "AUTO_REVIEWED", "HUMAN_REVIEW", "APPROVED", "REJECTED", "ESCALATED",
]
VALID_APPEAL_STATUSES = ["FILED", "UNDER_REVIEW", "UPHELD", "OVERTURNED", "WITHDRAWN"]
VALID_CURRENCY_ORDER_STATUSES = ["PENDING_PAYMENT", "COMPLETED", "FAILED", "REFUNDED"]
VALID_PURCHASE_ORDER_STATUSES = ["PENDING", "COMPLETED", "REFUNDED", "REVERSED"]
VALID_DEVEX_STATUSES = ["SUBMITTED", "APPROVED", "PAID", "REJECTED", "CANCELLED"]
VALID_ITEM_STATUSES = ["DRAFT", "PENDING_MODERATION", "ON_SALE", "OFF_SALE", "MODERATION_REJECTED"]
VALID_ITEM_KINDS = ["HAT", "SHIRT", "PANTS", "GEAR", "LIMITED_HAT", "LIMITED_GEAR"]
VALID_LISTING_STATUSES = ["ACTIVE", "SOLD", "CANCELLED"]
VALID_REPORT_STATUSES = ["OPEN", "TRIAGED", "ACTIONED", "DISMISSED"]
VALID_TERMINATION_STATUSES = ["PENDING_DISPOSITION", "EARNINGS_DISPOSED", "COMPLETE"]
VALID_IDENTITY_STATUSES = ["PENDING", "VERIFIED", "REJECTED", "EXPIRED"]
VALID_TAX_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "REJECTED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def _assert_append_only(data: dict):
    """Append-only rows carry only id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_user(data: dict):
    _assert_common(data)
    assert isinstance(data["username"], str) and 3 <= len(data["username"]) <= 20
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["date_of_birth"], str)
    assert data["status"] in VALID_USER_STATUSES
    assert data["age_band"] in VALID_AGE_BANDS
    assert isinstance(data["account_age_days"], int) and data["account_age_days"] >= 0
    assert isinstance(data["robux_balance"], int) and data["robux_balance"] >= 0
    assert isinstance(data["earned_robux_lifetime"], int) and data["earned_robux_lifetime"] >= 0
    assert isinstance(data["is_devex_eligible"], bool)
    assert data["chat_filter_level"] in VALID_CHAT_FILTER_LEVELS


def assert_identity_verification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("user_id", ""))
    assert data["status"] in VALID_IDENTITY_STATUSES
    assert data["document_type"] in ["PASSPORT", "DRIVERS_LICENSE", "NATIONAL_ID"]
    assert isinstance(data["document_country"], str)


def assert_tax_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("user_id", ""))
    assert data["status"] in VALID_TAX_STATUSES
    assert data["form_type"] in ["W9", "W8BEN", "W8BENE"]


def assert_parental_controls(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_user_id", ""))
    msl = data.get("monthly_spend_limit_robux")
    assert msl is None or (isinstance(msl, int) and msl >= 0)
    assert data["chat_mode"] in VALID_CHAT_MODES
    assert isinstance(data["allowed_age_ratings"], list)
    for r in data["allowed_age_ratings"]:
        assert r in VALID_AGE_RATINGS


def assert_experience(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("creator_user_id", ""))
    assert isinstance(data["title"], str) and 3 <= len(data["title"]) <= 60
    assert data["status"] in VALID_EXPERIENCE_STATUSES
    if data.get("age_rating") is not None:
        assert data["age_rating"] in VALID_AGE_RATINGS
    assert isinstance(data["visit_count_lifetime"], int) and data["visit_count_lifetime"] >= 0
    assert isinstance(data["engagement_payout_pending_robux"], int)
    assert data["engagement_payout_pending_robux"] >= 0


def assert_experience_age_rating(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("experience_id", ""))
    assert data["rating"] in VALID_AGE_RATINGS
    assert data["assigned_by"] in ["AUTOMATED", "HUMAN", "APPEAL_DECISION"]
    assert isinstance(data["is_current"], bool)


def assert_moderation_submission(data: dict):
    _assert_common(data)
    assert data["subject_type"] in ["EXPERIENCE", "ASSET", "TEXT"]
    assert isinstance(data["subject_id"], str)
    assert data["status"] in VALID_SUBMISSION_STATUSES


def assert_moderation_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("submission_id", ""))
    assert data["status"] in VALID_APPEAL_STATUSES
    assert isinstance(data["reason"], str) and 10 <= len(data["reason"]) <= 2000


def assert_currency_purchase_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("buyer_user_id", ""))
    assert isinstance(data["fiat_amount_cents"], int) and data["fiat_amount_cents"] > 0
    assert data["status"] in VALID_CURRENCY_ORDER_STATUSES
    assert isinstance(data["idempotency_key"], str)


def assert_purchase_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("buyer_user_id", ""))
    assert data["item_type"] in ["MARKETPLACE_ITEM", "EXPERIENCE_GAMEPASS", "LIMITED_ITEM_RESALE"]
    assert isinstance(data["item_id"], str)
    assert data["status"] in VALID_PURCHASE_ORDER_STATUSES
    assert isinstance(data["price_robux"], int) and data["price_robux"] >= 0


def assert_devex_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("user_id", ""))
    assert data["status"] in VALID_DEVEX_STATUSES
    assert isinstance(data["requested_robux"], int) and data["requested_robux"] > 0


def assert_marketplace_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("creator_user_id", ""))
    assert data["item_kind"] in VALID_ITEM_KINDS
    assert data["status"] in VALID_ITEM_STATUSES
    assert isinstance(data["price_robux"], int) and data["price_robux"] >= 0
    assert isinstance(data["is_limited"], bool)
    assert isinstance(data["copies_sold"], int) and data["copies_sold"] >= 0


def assert_resale_listing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("item_id", ""))
    assert is_valid_uuid(data.get("seller_user_id", ""))
    assert data["status"] in VALID_LISTING_STATUSES
    assert isinstance(data["ask_price_robux"], int) and data["ask_price_robux"] >= 0


def assert_chat_message(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("experience_id", ""))
    assert is_valid_uuid(data.get("sender_user_id", ""))
    assert isinstance(data["body_raw"], str)
    assert data["filter_applied"] in VALID_CHAT_FILTER_LEVELS
    assert isinstance(data["was_reported"], bool)


def assert_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("message_id", ""))
    assert data["reason_code"] in [
        "HARASSMENT", "SCAM", "INAPPROPRIATE_CONTENT", "PERSONAL_INFO", "OTHER",
    ]
    assert data["status"] in VALID_REPORT_STATUSES


def assert_account_termination(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("user_id", ""))
    assert data["reason_code"] in [
        "FRAUD", "SAFETY_VIOLATION", "LEGAL_REQUEST", "PARENT_REQUEST", "SELF_REQUEST",
    ]
    assert data["status"] in VALID_TERMINATION_STATUSES


def assert_engagement_snapshot(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data.get("experience_id", ""))
    assert isinstance(data["minutes_engaged"], int) and data["minutes_engaged"] >= 0
    assert isinstance(data["payout_robux"], int) and data["payout_robux"] >= 0


def assert_audit_log(data: dict):
    _assert_append_only(data)
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["action"], str)
    assert isinstance(data["subject_type"], str)
    assert isinstance(data["subject_id"], str)
