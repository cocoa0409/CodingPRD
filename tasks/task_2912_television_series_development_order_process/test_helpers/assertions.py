"""Domain assertion helpers.

These wrap the framework's structural assertions with the contract's own vocabulary:
the two slate ledgers, the common resource properties, the feasibility projection
and the pagination envelope.
"""

from typing import Any, Dict, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant

JsonDict = Dict[str, Any]


# ─── Common resource properties ───────────────────────
def assert_common_fields(data: JsonDict) -> None:
    """Every mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_immutable_record_fields(data: JsonDict) -> None:
    """An immutable record carries only id and created_at.

    No updated_at and no version at all — not even a null placeholder.
    """
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert "updated_at" not in data, "an immutable record must not carry updated_at"
    assert "version" not in data, "an immutable record must not carry version"


def assert_created_version_one(data: JsonDict) -> None:
    assert data["version"] == 1, f"a freshly created resource is version 1, got {data['version']}"


# ─── Timestamps ───────────────────────────────────────
def assert_instant(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 UTC instants after canonicalising sub-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_no_instant(actual: Any, label: str = "instant") -> None:
    assert actual is None, f"{label} should still be null, got {actual!r}"


# ─── Money ────────────────────────────────────────────
def assert_money_integer(data: JsonDict, *fields: str) -> None:
    """Money is carried as an integer count of cents, never a string or a float."""
    for field in fields:
        value = data[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be a JSON integer of cents, got {value!r}"
        )


def assert_cents(actual: Any, expected: int, label: str) -> None:
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be a JSON integer of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ─── Slate ledgers ────────────────────────────────────
def assert_slate_dollar_ledger(
    slate: JsonDict,
    *,
    committed: Optional[int] = None,
    reserved: Optional[int] = None,
    writeoff: Optional[int] = None,
    recouped: Optional[int] = None,
    available: Optional[int] = None,
) -> None:
    """Check any subset of the five derived dollar fields, then the invariant."""
    if committed is not None:
        assert_cents(slate["committed_dev_cents"], committed, "committed_dev_cents")
    if reserved is not None:
        assert_cents(
            slate["reserved_holding_cents"], reserved, "reserved_holding_cents"
        )
    if writeoff is not None:
        assert_cents(slate["writeoff_dev_cents"], writeoff, "writeoff_dev_cents")
    if recouped is not None:
        assert_cents(slate["recouped_dev_cents"], recouped, "recouped_dev_cents")
    if available is not None:
        assert_cents(slate["available_dev_cents"], available, "available_dev_cents")
    assert_slate_dollar_invariant(slate)


def assert_slate_dollar_invariant(slate: JsonDict) -> None:
    """available = total - committed - reserved - writeoff + recouped."""
    expected = (
        slate["total_dev_budget_cents"]
        - slate["committed_dev_cents"]
        - slate["reserved_holding_cents"]
        - slate["writeoff_dev_cents"]
        + slate["recouped_dev_cents"]
    )
    assert slate["available_dev_cents"] == expected, (
        "available_dev_cents drifted from the dollar ledger: "
        f"{slate['available_dev_cents']} != {expected}"
    )


def assert_slate_episode_ledger(
    slate: JsonDict,
    *,
    committed: Optional[int] = None,
    reserved: Optional[int] = None,
    available: Optional[int] = None,
    posture: Optional[str] = None,
) -> None:
    if committed is not None:
        assert slate["committed_episode_count"] == committed, (
            f"committed_episode_count: expected {committed}, "
            f"got {slate['committed_episode_count']}"
        )
    if reserved is not None:
        assert slate["reserved_episode_count"] == reserved, (
            f"reserved_episode_count: expected {reserved}, "
            f"got {slate['reserved_episode_count']}"
        )
    if available is not None:
        assert slate["available_episode_count"] == available, (
            f"available_episode_count: expected {available}, "
            f"got {slate['available_episode_count']}"
        )
    if posture is not None:
        assert slate["posture"] == posture, (
            f"posture: expected {posture}, got {slate['posture']}"
        )
    assert_slate_episode_invariant(slate)


def assert_slate_episode_invariant(slate: JsonDict) -> None:
    """capacity = available + committed + reserved."""
    expected = (
        slate["available_episode_count"]
        + slate["committed_episode_count"]
        + slate["reserved_episode_count"]
    )
    assert slate["episode_capacity"] == expected, (
        "episode inventory drifted: "
        f"{slate['episode_capacity']} != {expected}"
    )


# ─── Feasibility projection ───────────────────────────
def assert_feasibility(
    data: JsonDict,
    *,
    basis: Optional[str] = None,
    episode_count: Optional[int] = None,
    per_episode_cost_cents: Optional[int] = None,
    tier_factor_bps: Optional[int] = None,
    license_fee_final_cents: Optional[int] = None,
    deficit_per_episode_cents: Optional[int] = None,
    total_deficit_cents: Optional[int] = None,
    verdict: Optional[str] = None,
) -> None:
    checks = {
        "basis": basis,
        "episode_count": episode_count,
        "per_episode_cost_cents": per_episode_cost_cents,
        "tier_factor_bps": tier_factor_bps,
        "license_fee_final_cents": license_fee_final_cents,
        "deficit_per_episode_cents": deficit_per_episode_cents,
        "total_deficit_cents": total_deficit_cents,
        "verdict": verdict,
    }
    for field, expected in checks.items():
        if expected is None:
            continue
        assert data[field] == expected, (
            f"feasibility {field}: expected {expected}, got {data[field]}"
        )
    # The deficit and total are the arithmetic of the other two fields.
    assert (
        data["deficit_per_episode_cents"]
        == data["per_episode_cost_cents"] - data["license_fee_final_cents"]
    ), "deficit_per_episode_cents must be cost minus final licence fee"
    assert (
        data["total_deficit_cents"]
        == data["deficit_per_episode_cents"] * data["episode_count"]
    ), "total_deficit_cents must be the per-episode deficit times the episode count"


# ─── Scores ───────────────────────────────────────────
def assert_score(actual: Any, expected: float, label: str) -> None:
    """Scores are decimals; compare at the precision the contract rounds them to."""
    assert actual is not None, f"{label} must not be null"
    assert abs(float(actual) - expected) < 1e-9, (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── Pagination ───────────────────────────────────────
def assert_pagination_meta(
    meta: JsonDict,
    *,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit: expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, (
            f"meta.offset: expected {offset}, got {meta['offset']}"
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count: expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more: expected {has_more}, got {meta['has_more']}"
        )


def assert_ids(rows: Sequence[JsonDict], expected_ids: Sequence[str]) -> None:
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"row ids: expected {list(expected_ids)}, got {[r['id'] for r in rows]}"
    )


def assert_created_at_ascending(rows: Sequence[JsonDict]) -> None:
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"


# ─── Envelope ─────────────────────────────────────────
def assert_response_type(response, expected: str) -> None:
    body = response.json()
    assert body["response_type"] == expected, (
        f"response_type: expected {expected}, got {body['response_type']}"
    )


def assert_error_meta_present(response) -> None:
    """An error envelope carries the same meta block as any other response."""
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str), (
        "meta.api_request_id must be present on an error response too"
    )


# ─── Step ladder ──────────────────────────────────────
def find_step(steps: Sequence[JsonDict], step_index: int) -> JsonDict:
    for step in steps:
        if step["step_index"] == step_index:
            return step
    raise AssertionError(f"no step with step_index {step_index} in {steps}")


def assert_step(
    step: JsonDict,
    *,
    status: Optional[str] = None,
    step_type: Optional[str] = None,
    effective_fee_cents: Optional[int] = None,
    option_expires_at: Optional[str] = None,
) -> None:
    if status is not None:
        assert step["status"] == status, (
            f"step {step.get('step_index')} status: expected {status}, got {step['status']}"
        )
    if step_type is not None:
        assert step["step_type"] == step_type
    if effective_fee_cents is not None:
        assert_cents(step["effective_fee_cents"], effective_fee_cents, "effective_fee_cents")
    if option_expires_at is not None:
        assert_instant(step["option_expires_at"], option_expires_at, "option_expires_at")
