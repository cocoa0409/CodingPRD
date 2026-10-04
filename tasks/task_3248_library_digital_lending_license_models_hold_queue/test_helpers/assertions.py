"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            "version must be an integer >= 1"
        )
    else:
        assert "updated_at" not in data, "append-only resource must not carry updated_at"
        assert "version" not in data, "append-only resource must not carry version"


def assert_consortium(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("status") in ("ACTIVE", "SUSPENDED")


def assert_library(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("consortium_id", "")), "consortium_id must be a UUID"
    assert isinstance(data.get("residency_region_codes"), list)
    assert data.get("status") in ("ACTIVE", "SUSPENDED")


def assert_fund(data: dict):
    _assert_common(data)
    assert isinstance(data.get("budget_cents"), int)
    assert isinstance(data.get("committed_cents"), int)
    assert isinstance(data.get("spent_cents"), int)
    assert isinstance(data.get("cpc_accrued_cents"), int)
    assert isinstance(data.get("available_committed_cents"), int)
    assert isinstance(data.get("available_actual_cents"), int)
    assert data.get("status") in ("OPEN", "CLOSED")


def assert_patron(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("library_id", "")), "library_id must be a UUID"
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("card_expires_at", "")), (
        "card_expires_at must be ISO 8601"
    )
    assert isinstance(data.get("active_loan_count"), int)
    assert isinstance(data.get("active_hold_count"), int)


def assert_title(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("consortium_id", "")), "consortium_id must be a UUID"
    assert isinstance(data.get("isbn"), str) and data["isbn"]
    assert data.get("sharing_scope") in ("LOCAL_ONLY", "CONSORTIUM")


def assert_license(data: dict):
    _assert_common(data)
    assert data.get("model") in (
        "OCOU", "METERED_TIME", "METERED_CIRC", "COST_PER_CIRC", "SIMULTANEOUS_USE",
    )
    assert data.get("status") in ("ACTIVE", "EXPIRED", "EXHAUSTED", "RETIRED")


def assert_hold(data: dict):
    _assert_common(data)
    assert data.get("status") in (
        "PLACED", "READY", "SUSPENDED", "FULFILLED", "EXPIRED", "CANCELLED",
    )
    assert is_iso8601_timestamp(data.get("placed_at", "")), "placed_at must be ISO 8601"
    assert isinstance(data.get("optimistic_wait_days"), int)
    assert isinstance(data.get("pessimistic_wait_days"), int)


def assert_loan(data: dict):
    _assert_common(data)
    assert data.get("status") in ("ACTIVE", "RETURNED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("checkout_at", "")), "checkout_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"
    assert isinstance(data.get("renewals_used"), int)


def assert_order(data: dict):
    _assert_common(data)
    assert data.get("status") in (
        "DRAFT", "PROPOSED", "APPROVED", "REJECTED", "FULFILLED", "CANCELLED",
    )
    assert data.get("origin") in ("MANUAL", "AUTO_RATIO")
    assert isinstance(data.get("estimated_cost_cents"), int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data.get("status") in ("DRAFT", "ISSUED", "DISPUTED", "SETTLED")
    assert isinstance(data.get("lines"), list)
    assert isinstance(data.get("total_cents"), int)


def assert_event(data: dict):
    _assert_common(data, with_version=False)
    assert data.get("event_type") in (
        "CHECKOUT", "RENEW", "RETURN", "LOAN_EXPIRED", "HOLD_PLACED", "HOLD_READY",
        "HOLD_FULFILLED", "HOLD_EXPIRED", "HOLD_CANCELLED", "PURCHASE",
    )
    assert is_iso8601_timestamp(data.get("occurred_at", "")), (
        "occurred_at must be ISO 8601"
    )
    assert isinstance(data.get("charge_cents"), int)


def assert_snapshot(data: dict):
    _assert_common(data)
    assert isinstance(data.get("checkouts_by_model"), dict)
    assert isinstance(data.get("cpc_spend_cents"), int)
    assert isinstance(data.get("holds_filled"), int)


def assert_fund_invariants(data: dict):
    """Fund ledger invariants that must hold after any operation."""
    assert data["available_committed_cents"] == (
        data["budget_cents"] - data["committed_cents"]
        - data["spent_cents"] - data["cpc_accrued_cents"]
    ), "committed-variant availability must match the pinned formula"
    assert data["available_actual_cents"] == (
        data["budget_cents"] - data["spent_cents"] - data["cpc_accrued_cents"]
    ), "actual-variant availability must match the pinned formula"
    assert data["available_actual_cents"] >= data["available_committed_cents"], (
        "actuals-only availability is always at least the committed variant"
    )
