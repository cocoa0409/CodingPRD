"""Domain assertions for the Wholesale Auction Arbitration API."""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .constants import instants_equal
from .types import TERMINAL_CASE_STATUSES


def validate_unpaginated(response) -> tuple:
    """Validate an *unpaginated* list route and return (rows, meta).

    PRD 2.3: every list route other than the sale list and the arbitration-case
    list "accepts no `limit` or `offset` and is unpaginated. Those routes return
    every matching row in one response and still populate `meta`: `total_count`
    equals the number of rows returned, `has_more` is false, `limit` is null and
    `offset` is 0."  The runner's generic `validate_paginated` demands an integer
    `limit` greater than zero, so it cannot be used on these routes.
    """
    rows = validate_success(response, 200)
    body = response.json()
    assert body["response_type"] == "array", (
        f"an unpaginated list route must answer response_type 'array', "
        f"got {body['response_type']!r}"
    )
    assert isinstance(rows, list), f"data should be an array, got {type(rows)}"
    return rows, body["meta"]


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant"):
    """Compare instants by value, tolerating fractional-second width."""
    assert instants_equal(actual, expected), (
        f"{label} should be {expected!r} but was {actual!r}"
    )


def assert_iso_utc_millis(value: str, label: str = "timestamp"):
    """Every datetime crossing the API is an ISO 8601 UTC instant."""
    assert isinstance(value, str), f"{label} should be a string, got {type(value)}"
    assert is_iso8601_timestamp(value), f"{label} is not an ISO 8601 instant: {value!r}"


def assert_mutable_common_fields(entity: Dict[str, Any], label: str = "resource"):
    """A mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"{label}.id should be a UUID: {entity['id']!r}"
    assert_iso_utc_millis(entity["created_at"], f"{label}.created_at")
    assert_iso_utc_millis(entity["updated_at"], f"{label}.updated_at")
    assert isinstance(entity["version"], int), f"{label}.version should be an integer"
    assert entity["version"] >= 1, f"{label}.version should start at 1"


def assert_append_only_common_fields(entity: Dict[str, Any], label: str = "record"):
    """An append-only record carries id and created_at and nothing else."""
    assert is_valid_uuid(entity["id"]), f"{label}.id should be a UUID: {entity['id']!r}"
    assert_iso_utc_millis(entity["created_at"], f"{label}.created_at")
    assert "updated_at" not in entity, f"{label} must not carry updated_at"
    assert "version" not in entity, f"{label} must not carry version"


def assert_unpaginated_meta(meta: Dict[str, Any], expected_count: int):
    """Every list route other than the sale list and the case list is unpaginated."""
    assert meta["limit"] is None, f"limit should be null, was {meta['limit']!r}"
    assert meta["offset"] == 0, f"offset should be 0, was {meta['offset']!r}"
    assert meta["has_more"] is False, f"has_more should be false, was {meta['has_more']!r}"
    assert meta["total_count"] == expected_count, (
        f"total_count should be {expected_count}, was {meta['total_count']}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]], label: str = "list"):
    """Every list route sorts ascending by created_at."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"{label} is not in ascending created_at order: {stamps}"


def assert_ledger_batch_balanced(entries: List[Dict[str, Any]], label: str = "ledger"):
    """A settlement ledger batch always sums to zero."""
    total = sum(entry["amount_signed_cents"] for entry in entries)
    assert total == 0, f"{label} signed amounts should sum to zero, summed to {total}"


def assert_party_net_zero(entries: List[Dict[str, Any]], party: str, entry_types: List[str]):
    """A party's net across the supplied entry types is zero."""
    total = sum(
        entry["amount_signed_cents"]
        for entry in entries
        if entry["party"] == party and entry["entry_type"] in entry_types
    )
    assert total == 0, (
        f"{party} net across {entry_types} should be zero, was {total}"
    )


def assert_ledger_rows(
    entries: List[Dict[str, Any]],
    expected: List[Dict[str, Any]],
):
    """Assert the exact (party, entry_type, amount_signed_cents) multiset."""
    actual = sorted(
        (row["party"], row["entry_type"], row["amount_signed_cents"]) for row in entries
    )
    wanted = sorted(
        (row["party"], row["entry_type"], row["amount_signed_cents"]) for row in expected
    )
    assert actual == wanted, f"ledger rows should be {wanted} but were {actual}"


def assert_case_terminal(case: Dict[str, Any], expected_status: str):
    assert case["status"] == expected_status, (
        f"case status should be {expected_status}, was {case['status']}"
    )
    assert expected_status in TERMINAL_CASE_STATUSES, (
        f"{expected_status} is not a terminal case status"
    )


def assert_counters(
    entity: Dict[str, Any], expected: Dict[str, Any], label: str = "entity"
):
    """Assert a set of named counters on one row."""
    for field, value in expected.items():
        assert entity[field] == value, (
            f"{label}.{field} should be {value!r} but was {entity[field]!r}"
        )


def assert_transport_totals(
    decision: Dict[str, Any],
    total: int,
    buyer: int,
    seller: int,
    auction: int,
):
    assert decision["transport_total_cents"] == total, (
        f"transport_total_cents should be {total}, was {decision['transport_total_cents']}"
    )
    assert decision["transport_buyer_share_cents"] == buyer, (
        f"transport_buyer_share_cents should be {buyer}, "
        f"was {decision['transport_buyer_share_cents']}"
    )
    assert decision["transport_seller_share_cents"] == seller, (
        f"transport_seller_share_cents should be {seller}, "
        f"was {decision['transport_seller_share_cents']}"
    )
    assert decision["transport_auction_share_cents"] == auction, (
        f"transport_auction_share_cents should be {auction}, "
        f"was {decision['transport_auction_share_cents']}"
    )


def assert_sweep_report(
    report: Dict[str, Any],
    inspections_expired: int = 0,
    rounds_expired: int = 0,
    seller_response_timeouts: int = 0,
    cases_expired: int = 0,
):
    expected = {
        "inspections_expired": inspections_expired,
        "rounds_expired": rounds_expired,
        "seller_response_timeouts": seller_response_timeouts,
        "cases_expired": cases_expired,
    }
    for field, value in expected.items():
        assert report[field] == value, (
            f"sweep {field} should be {value} but was {report[field]}"
        )


def assert_policy_action(
    action: Dict[str, Any],
    action_type: str,
    from_tier: str,
    to_tier: str,
    rolling_rate_bps: int,
    triggered_by_case_id: Optional[str] = None,
):
    assert action["action_type"] == action_type, (
        f"action_type should be {action_type}, was {action['action_type']}"
    )
    assert action["from_tier"] == from_tier, (
        f"from_tier should be {from_tier}, was {action['from_tier']}"
    )
    assert action["to_tier"] == to_tier, (
        f"to_tier should be {to_tier}, was {action['to_tier']}"
    )
    assert action["rolling_rate_bps_at_action"] == rolling_rate_bps, (
        f"rolling_rate_bps_at_action should be {rolling_rate_bps}, "
        f"was {action['rolling_rate_bps_at_action']}"
    )
    if triggered_by_case_id is not None:
        assert action["triggered_by_case_id"] == triggered_by_case_id, (
            "triggered_by_case_id should be "
            f"{triggered_by_case_id}, was {action['triggered_by_case_id']}"
        )
    assert action["note"] == f"auto tier change at {rolling_rate_bps} bps", (
        "an automatic action's note should read exactly "
        f"'auto tier change at {rolling_rate_bps} bps', was {action['note']!r}"
    )


def assert_money_int(value: Any, label: str = "amount"):
    """Money is always an integer number of whole cents, never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} should be an integer number of cents, was {value!r}"
    )
