"""Entity assertions for the Scan-Go Checkout API resources."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )


def assert_club(data: dict):
    _assert_common(data, "Club")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["open_minute"], int)
    assert isinstance(data["early_shopping_start_minute"], int)
    assert data["exit_verification_mode"] in ["RECEIPT_CODE", "CV_ARCH", "BOTH"]
    assert isinstance(data["scan_go_enabled"], bool)
    assert isinstance(data["allow_offline_payment"], bool)
    assert data["connectivity_posture"] in ["ONLINE", "DEGRADED", "OFFLINE_FALLBACK"]


def assert_member(data: dict):
    _assert_common(data, "Member")
    assert data["tier"] in ["CLUB", "PLUS"]
    assert isinstance(data["birth_year"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert data["tender_status"] in ["OK", "DECLINED"]
    assert data["cash_rewards_pending_cents"] >= 0
    assert data["cash_rewards_posted_cents"] >= 0
    assert data["unscanned_strikes"] >= 0


def assert_catalog_item(data: dict):
    _assert_common(data, "CatalogItem")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["pricing_mode"] in ["UNIT", "WEIGHTED"]
    assert data["restricted_class"] in ["NONE", "ALCOHOL", "TOBACCO", "PHARMACY"]
    assert data["status"] in ["ACTIVE", "DELISTED"]


def assert_scan_session(data: dict):
    _assert_common(data, "ScanSession")
    assert data["status"] in [
        "OPEN", "REVIEW_HOLD", "OFFLINE_PAUSED", "PAID", "EXIT_PENDING",
        "FLAGGED", "EXITED", "ABANDONED", "VOIDED",
    ]
    assert data["provisional_total_cents"] >= 0
    assert data["scanned_item_count"] >= 0


def assert_scan_line(data: dict):
    _assert_common(data, "ScanLine")
    assert data["pricing_mode_snapshot"] in ["UNIT", "WEIGHTED"]
    assert data["restricted_class_snapshot"] in ["NONE", "ALCOHOL", "TOBACCO", "PHARMACY"]
    assert data["status"] in ["SCANNED", "INTERCEPTED", "CLEARED", "REMOVED"]
    assert isinstance(data["scan_seq"], int) and data["scan_seq"] >= 1
    assert data["line_total_cents"] >= 0


def assert_intercept(data: dict):
    _assert_common(data, "RestrictedIntercept")
    assert data["restricted_class"] in ["ALCOHOL", "TOBACCO", "PHARMACY"]
    assert data["status"] in ["PENDING", "APPROVED", "DENIED", "EXPIRED"]


def assert_exit_verification(data: dict):
    _assert_common(data, "ExitVerification")
    assert data["method"] in ["RECEIPT_CODE", "CV_ARCH"]
    assert data["status"] in ["PENDING", "VERIFIED", "MISMATCH", "CONFIRMED", "EXPIRED"]
    assert isinstance(data["expected_item_count"], int)


def assert_lp_case(data: dict):
    _assert_common(data, "LossPreventionCase")
    assert data["source"] in ["CV_MISMATCH", "RECEIPT_EXPIRY"]
    assert data["tier"] in ["REVIEW", "SEVERE"]
    assert data["status"] in ["OPEN", "ACKNOWLEDGED", "ESCALATED", "RESOLVED"]


def assert_curbside_order(data: dict):
    _assert_common(data, "CurbsideOrder")
    assert data["status"] in [
        "PLACED", "STAGING", "STAGED", "PICKED_UP", "CANCELLED", "EXPIRED",
    ]
    assert isinstance(data["item_count"], int) and data["item_count"] >= 1
