"""Domain assertions.

These operate on already-unwrapped payloads.  ``validate_success`` in the
framework returns ``body["data"]`` for you, so nothing in this module ever
indexes ``["data"]`` again — the envelope is unwrapped exactly once, there.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing.assertions import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from test_helpers.api_client import as_instant
from test_helpers.constants import (
    ASSOCIATION_ADMIN_PCT,
    RESERVE_PCT_AT_OR_ABOVE_TIER,
    RESERVE_PCT_BELOW_TIER,
    RESERVE_TIER_THRESHOLD_CENTS,
)


# ─── Envelope and identity (PRD §2.2, §2.4) ────────────

def assert_envelope(body: Dict[str, Any], expected_response_type: str) -> None:
    """Check the three envelope invariants on a raw response body."""
    assert "meta" in body, f"response carries no meta object: {body}"
    meta = body["meta"]
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must be a string beginning 'req_', got {request_id!r}"
    )
    timestamp = meta.get("api_request_timestamp")
    assert is_iso8601_timestamp(timestamp), (
        f"api_request_timestamp is not an ISO-8601 UTC instant: {timestamp!r}"
    )
    assert body.get("response_type") == expected_response_type, (
        f"response_type should be {expected_response_type!r}, "
        f"got {body.get('response_type')!r}"
    )
    assert "data" in body, f"response carries no data key: {body}"


def assert_identity(resource: Dict[str, Any], *, versioned: bool = True) -> None:
    """Every resource carries a UUID ``id`` and a millisecond ``created_at``.

    Most also carry ``updated_at`` and ``version``; pass ``versioned=False`` for
    the one immutable resource, a weekly dues payment, which carries neither.
    """
    assert is_valid_uuid(resource.get("id", "")), (
        f"id must be a bare UUID with no prefix, got {resource.get('id')!r}"
    )
    created_at = resource.get("created_at")
    assert_millisecond_instant(created_at, "created_at")
    if versioned:
        assert_millisecond_instant(resource.get("updated_at"), "updated_at")
        assert resource.get("version") == resource.get("version")
        assert isinstance(resource.get("version"), int), (
            f"version must be an integer, got {resource.get('version')!r}"
        )
    else:
        assert "updated_at" not in resource or resource["updated_at"] is None, (
            "an immutable resource must not carry updated_at"
        )
        assert "version" not in resource or resource["version"] is None, (
            "an immutable resource must not carry version"
        )


def assert_millisecond_instant(value: Any, field: str = "timestamp") -> None:
    """An instant spelled with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} is not ISO-8601 UTC: {value!r}"
    assert len(value) == 24 and value[19] == "." and value.endswith("Z"), (
        f"{field} must carry exactly three fractional-second digits, got {value!r}"
    )


def assert_instant_equals(actual: Any, expected: str, field: str = "instant") -> None:
    """Compare instants after both sides are put into canonical spelling."""
    assert as_instant(actual) == as_instant(expected), (
        f"{field} should be {expected!r}, got {actual!r}"
    )


def assert_fields(resource: Dict[str, Any], **expected: Any) -> None:
    """Assert several fields at once, reporting every mismatch together."""
    wrong = {
        key: (resource.get(key), value)
        for key, value in expected.items()
        if resource.get(key) != value
    }
    assert not wrong, "; ".join(
        f"{key}: expected {want!r}, got {got!r}" for key, (got, want) in wrong.items()
    )


# ─── Money and precision (PRD §2.8) ────────────────────

def assert_cents(value: Any, expected: int, field: str = "amount_cents") -> None:
    """A money field is a whole number of cents sent as a JSON integer."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r} "
        f"({type(value).__name__})"
    )
    assert value == expected, f"{field} should be {expected} cents, got {value}"


def assert_points(value: Any, expected: float, field: str = "points") -> None:
    """Points are recorded to one decimal place, so halves are exact."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 1) == round(float(expected), 1), (
        f"{field} should be {expected}, got {value}"
    )
    assert abs(float(value) * 10 - round(float(value) * 10)) < 1e-9, (
        f"{field} carries more than one decimal place: {value!r}"
    )


def expected_reserve_cents(plan_basis_cents: int) -> int:
    """Step 1-2 of the waterfall: the tier is read from the basis itself."""
    pct = (
        RESERVE_PCT_AT_OR_ABOVE_TIER
        if plan_basis_cents >= RESERVE_TIER_THRESHOLD_CENTS
        else RESERVE_PCT_BELOW_TIER
    )
    return int(plan_basis_cents * pct)


def expected_admin_fee_cents(plan_basis_cents: int, reserve_cents: int) -> int:
    """Step 3: three percent of the post-reserve amount, rounded half up."""
    post_reserve = plan_basis_cents - reserve_cents
    scaled = post_reserve * ASSOCIATION_ADMIN_PCT
    return int(scaled + 0.5)


def expected_award_amounts(net_distributable_cents: int, weights: Sequence[float]) -> List[int]:
    """Steps 6-7: floor each place, then hand the remainder out one cent at a
    time in ascending place order beginning at place 1."""
    raw = [int(net_distributable_cents * weight) for weight in weights]
    remainder = net_distributable_cents - sum(raw)
    for index in range(remainder):
        raw[index % len(raw)] += 1
    return raw


# ─── Averages and handicaps (PRD §3.6) ─────────────────

def expected_bowler_handicap(
    basis_average: Optional[int],
    handicap_base: int,
    percentage: float,
    max_handicap_per_game: int,
) -> int:
    """Floor the product first, apply the ceiling second — the order is pinned.

    A null basis average yields 0, and a basis average above ``handicap_base``
    yields 0 rather than a negative handicap.
    """
    if basis_average is None:
        return 0
    difference = max(handicap_base - basis_average, 0)
    floored = int(difference * percentage)
    return min(floored, max_handicap_per_game)


def expected_team_handicap(per_bowler_handicaps: Iterable[int]) -> int:
    """Sum handicaps that are *already* floored per bowler — never floor once at
    the end over unfloored products."""
    return sum(per_bowler_handicaps)


def expected_truncated_average(certified_pins: int, certified_games: int) -> Optional[int]:
    if certified_games <= 0:
        return None
    return certified_pins // certified_games


def expected_blended_average(
    entering_average: Optional[int],
    prior_season_games: int,
    certified_pins: int,
    certified_games: int,
) -> Optional[int]:
    """The BLENDED provisional variant, falling back exactly as the PRD says."""
    if entering_average is None:
        return expected_truncated_average(certified_pins, certified_games)
    total_games = prior_season_games + certified_games
    if total_games <= 0:
        return None
    return (entering_average * prior_season_games + certified_pins) // total_games


# ─── Ordering and listing (PRD §2.3) ───────────────────

def assert_ordered_by(rows: Sequence[Dict[str, Any]], field: str, descending: bool = False) -> None:
    values = [row.get(field) for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows are not ordered by {field} "
        f"{'descending' if descending else 'ascending'}: {values}"
    )


def assert_ids_in_order(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    actual = [row.get("id") for row in rows]
    assert actual == list(expected_ids), (
        f"listing order should be {list(expected_ids)}, got {actual}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any], *, limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert_fields(
        meta, limit=limit, offset=offset, total_count=total_count, has_more=has_more
    )


# ─── Cross-entity invariants (PRD §2.9) ────────────────

def assert_prize_money_invariant(fund: Dict[str, Any]) -> None:
    """``collected_prize_cents`` always equals paid plus undistributed."""
    collected = fund["collected_prize_cents"]
    paid = fund["paid_award_total_cents"]
    undistributed = fund["undistributed_balance_cents"]
    assert collected == paid + undistributed, (
        f"prize money invariant broken: collected {collected} != "
        f"paid {paid} + undistributed {undistributed}"
    )


def assert_membership_axes(
    membership: Dict[str, Any], sanction_status: Any, remittance_status: Any
) -> None:
    """The two membership axes advance together but neither derives the other."""
    expected_sanction = getattr(sanction_status, "value", sanction_status)
    expected_remittance = getattr(remittance_status, "value", remittance_status)
    assert membership.get("sanction_status") == expected_sanction, (
        f"sanction_status should be {expected_sanction!r}, "
        f"got {membership.get('sanction_status')!r}"
    )
    assert membership.get("remittance_status") == expected_remittance, (
        f"remittance_status should be {expected_remittance!r}, "
        f"got {membership.get('remittance_status')!r}"
    )


def assert_version_is(resource: Dict[str, Any], expected: int) -> None:
    assert resource.get("version") == expected, (
        f"version should be {expected}, got {resource.get('version')!r}"
    )


def snapshot(resource: Dict[str, Any], fields: Sequence[str]) -> Dict[str, Any]:
    """Capture named fields so a compensating action can be checked for having
    restored them *exactly*."""
    return {field: resource.get(field) for field in fields}


def assert_restored(
    before: Dict[str, Any], after: Dict[str, Any], context: str = "compensating action"
) -> None:
    differences = {
        key: (value, after.get(key))
        for key, value in before.items()
        if after.get(key) != value
    }
    assert not differences, (
        f"{context} did not restore state exactly: "
        + "; ".join(
            f"{key} was {was!r}, is now {now!r}"
            for key, (was, now) in differences.items()
        )
    )
