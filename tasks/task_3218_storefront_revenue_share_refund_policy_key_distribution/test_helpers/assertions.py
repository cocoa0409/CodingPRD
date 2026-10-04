"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_developer_account(data: dict):
    _assert_common(data)
    assert isinstance(data.get("company_name"), str) and data["company_name"]
    assert isinstance(data.get("contact_email"), str) and data["contact_email"]
    assert isinstance(data.get("onboarding_fee_paid"), bool)
    assert isinstance(data.get("bank_details_submitted"), bool)
    assert data.get("status") in {"PENDING", "ACTIVE", "SUSPENDED", "TERMINATED"}


def assert_title(data: dict):
    _assert_common(data)
    assert isinstance(data.get("developer_account_id"), str)
    assert isinstance(data.get("title_name"), str) and data["title_name"]
    assert isinstance(data.get("base_price_usd_cents"), int) and data["base_price_usd_cents"] > 0
    assert isinstance(data.get("early_access"), bool)
    assert data.get("status") in {
        "DRAFT", "PENDING_REVIEW", "APPROVED", "RELEASE_SCHEDULED", "RELEASED", "DELISTED"
    }
    assert isinstance(data.get("current_tier"), int) and data["current_tier"] in (1, 2, 3)
    assert isinstance(data.get("lifetime_recognized_revenue_usd_cents"), int)
    assert isinstance(data.get("lifetime_refund_events"), int)
    assert isinstance(data.get("refund_abuse_flag"), bool)
    assert isinstance(data.get("review_bomb_flag"), bool)


def assert_store_page_review(data: dict):
    _assert_common(data)
    assert isinstance(data.get("title_id"), str)
    assert isinstance(data.get("submission_seq"), int) and data["submission_seq"] >= 1
    assert data.get("status") in {"SUBMITTED", "APPROVED", "REJECTED"}


def assert_region_price_override(data: dict):
    _assert_common(data)
    assert isinstance(data.get("title_id"), str)
    assert data.get("currency") in {"EUR", "GBP", "JPY", "BRL"}
    assert isinstance(data.get("price_cents"), int) and data["price_cents"] > 0
    assert data.get("status") in {"ACTIVE", "WITHDRAWN"}


def assert_key_batch(data: dict):
    _assert_common(data)
    assert isinstance(data.get("title_id"), str)
    assert isinstance(data.get("requested_quantity"), int) and 1 <= data["requested_quantity"] <= 10000
    assert isinstance(data.get("free_keys_in_batch"), int)
    assert 0 <= data["free_keys_in_batch"] <= data["requested_quantity"]
    assert data.get("status") in {"REQUESTED", "APPROVED", "REJECTED"}
    assert isinstance(data.get("free_key_allowance_at_request"), int)


def assert_activation_key(data: dict):
    _assert_common(data)
    assert isinstance(data.get("batch_id"), str)
    assert isinstance(data.get("key_code"), str) and data["key_code"]
    assert isinstance(data.get("is_free"), bool)
    assert data.get("status") in {"UNUSED", "REDEEMED", "REVOKED"}


def assert_user_account(data: dict):
    _assert_common(data)
    assert isinstance(data.get("email"), str) and data["email"]
    assert data.get("status") in {"ACTIVE", "RESTRICTED", "BANNED"}
    assert isinstance(data.get("refund_restricted"), bool)


def assert_purchase(data: dict):
    _assert_common(data)
    assert isinstance(data.get("user_account_id"), str)
    assert isinstance(data.get("title_id"), str)
    assert data.get("currency") in {"USD", "EUR", "GBP", "JPY", "BRL"}
    assert isinstance(data.get("gross_price_cents"), int)
    assert isinstance(data.get("platform_fee_cents"), int)
    assert isinstance(data.get("developer_share_cents"), int)
    assert isinstance(data.get("usd_recognized_cents"), int)
    assert data.get("status") in {"COMPLETED", "REFUNDED", "PARTIALLY_REFUNDED"}
    assert isinstance(data.get("playtime_minutes"), int)
    assert isinstance(data.get("refunded_cents"), int)


def assert_refund_request(data: dict):
    _assert_common(data)
    assert isinstance(data.get("purchase_id"), str)
    assert isinstance(data.get("user_account_id"), str)
    assert isinstance(data.get("reason"), str)
    assert data.get("status") in {"REQUESTED", "APPROVED", "DENIED"}


def assert_review(data: dict):
    _assert_common(data)
    assert isinstance(data.get("title_id"), str)
    assert isinstance(data.get("user_account_id"), str)
    assert isinstance(data.get("is_positive"), bool)
    assert isinstance(data.get("body"), str) and 1 <= len(data["body"]) <= 8000
    assert data.get("status") in {"PUBLISHED", "REMOVED"}
    assert isinstance(data.get("off_topic"), bool)


def assert_review_bomb_window(data: dict):
    _assert_common(data)
    assert isinstance(data.get("title_id"), str)
    assert data.get("status") in {"ACTIVE", "CLOSED"}
    assert isinstance(data.get("trigger_review_count"), int)


def assert_workshop_item(data: dict):
    _assert_common(data)
    assert isinstance(data.get("title_id"), str)
    assert isinstance(data.get("creator_account_id"), str)
    assert isinstance(data.get("item_name"), str) and data["item_name"]
    assert isinstance(data.get("price_cents"), int) and data["price_cents"] > 0
    assert isinstance(data.get("creator_share_bps"), int) and 1 <= data["creator_share_bps"] <= 5000
    assert data.get("status") in {"PENDING", "PUBLISHED", "REMOVED"}


def assert_workshop_sale(data: dict):
    _assert_common(data)
    assert isinstance(data.get("workshop_item_id"), str)
    assert isinstance(data.get("buyer_account_id"), str)
    assert isinstance(data.get("gross_cents"), int)
    assert isinstance(data.get("creator_share_cents"), int)
    assert isinstance(data.get("platform_share_cents"), int)


def assert_purchase_split_invariants(purchase: dict):
    """Per-purchase money conservation: fee + share reconstructs the gross exactly."""
    assert purchase["platform_fee_cents"] + purchase["developer_share_cents"] == purchase["gross_price_cents"], (
        f"split must conserve gross: {purchase['platform_fee_cents']} + "
        f"{purchase['developer_share_cents']} != {purchase['gross_price_cents']}"
    )


def assert_workshop_split_invariants(sale: dict):
    """Workshop split: creator + platform reconstruct the gross exactly."""
    assert sale["creator_share_cents"] + sale["platform_share_cents"] == sale["gross_cents"], (
        f"workshop split must conserve gross: {sale['creator_share_cents']} + "
        f"{sale['platform_share_cents']} != {sale['gross_cents']}"
    )
