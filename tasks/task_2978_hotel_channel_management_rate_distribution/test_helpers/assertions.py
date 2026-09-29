"""Shared assertions for the Hotel Channel Distribution API.

Two rules govern this module. Instant comparisons always run through
``canonical_instant`` so that two spellings of one instant compare equal, and
every assertion carries a message naming the field and both values, so a
failure reads as a contract violation rather than as a bare ``assert``.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import PAGINATION_META_FIELDS

# ── Primitive shapes ───────────────────────────────────────────────────────


def assert_uuid(value: Any, field: str = "id") -> None:
    assert isinstance(value, str), f"{field} should be a string, got {value!r}"
    assert is_valid_uuid(value), f"{field} should be a UUID, got {value!r}"


def assert_instant(value: Any, field: str) -> None:
    """An ISO 8601 UTC instant."""
    assert isinstance(value, str), f"{field} should be a string instant, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} should be an ISO 8601 instant, got {value!r}"


def assert_date(value: Any, field: str) -> None:
    """A calendar date in ``YYYY-MM-DD`` form."""
    assert isinstance(value, str), f"{field} should be a string date, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{field} should be a YYYY-MM-DD date, got {value!r}"
    )
    year, month, day = value.split("-")
    assert year.isdigit() and month.isdigit() and day.isdigit(), (
        f"{field} should be a YYYY-MM-DD date, got {value!r}"
    )


def assert_instant_equals(actual: Any, expected: Any, field: str) -> None:
    """Compare two instants on their canonical form, not on their spelling."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field} should be {expected!r}, got {actual!r}"
    )


# ── Common fields ──────────────────────────────────────────────────────────


def assert_common_fields(entity: Mapping[str, Any], entity_name: str = "entity") -> None:
    """The four fields every entity but the freeze window carries."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in entity, f"{entity_name} should carry {field}"
    assert_uuid(entity["id"], f"{entity_name}.id")
    assert_instant(entity["created_at"], f"{entity_name}.created_at")
    assert_instant(entity["updated_at"], f"{entity_name}.updated_at")
    version = entity["version"]
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{entity_name}.version should be an integer, got {version!r}"
    )
    assert version >= 1, f"{entity_name}.version should start at 1, got {version}"


def assert_create_only_fields(entity: Mapping[str, Any], entity_name: str = "entity") -> None:
    """The immutable entity's shape: an id and a creation instant, nothing more."""
    assert_uuid(entity["id"], f"{entity_name}.id")
    assert_instant(entity["created_at"], f"{entity_name}.created_at")
    assert "updated_at" not in entity, f"{entity_name} should carry no updated_at field"
    assert "version" not in entity, f"{entity_name} should carry no version field"


def assert_version(entity: Mapping[str, Any], expected: int, entity_name: str = "entity") -> None:
    assert entity["version"] == expected, (
        f"{entity_name}.version should be {expected}, got {entity['version']}"
    )


def assert_fields(
    entity: Mapping[str, Any], expected: Mapping[str, Any], entity_name: str = "entity"
) -> None:
    """Every named field holds the expected value; unnamed fields are ignored."""
    for field, value in expected.items():
        assert field in entity, f"{entity_name} should carry {field}"
        assert entity[field] == value, (
            f"{entity_name}.{field} should be {value!r}, got {entity[field]!r}"
        )


def assert_field_set(
    entity: Mapping[str, Any], expected_fields: Iterable[str], entity_name: str = "entity"
) -> None:
    """The serialized form holds exactly these fields and no others."""
    expected_set = set(expected_fields)
    actual_set = set(entity.keys())
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)
    assert not missing, f"{entity_name} is missing fields {missing}"
    assert not extra, f"{entity_name} carries unexpected fields {extra}"


def assert_unchanged(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    fields: Sequence[str],
    entity_name: str = "entity",
) -> None:
    """Named fields are byte-identical across two reads of the same row."""
    for field in fields:
        assert before[field] == after[field], (
            f"{entity_name}.{field} should be unchanged at {before[field]!r}, "
            f"got {after[field]!r}"
        )


# ── Pagination ─────────────────────────────────────────────────────────────


def assert_pagination_meta(
    meta: Mapping[str, Any],
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    """The page block of a list response, which lives inside ``meta``."""
    for field in PAGINATION_META_FIELDS:
        assert field in meta, f"list meta should carry {field}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count should be {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit should be {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"meta.offset should be {offset}, got {meta['offset']}"
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more should be {has_more}, got {meta['has_more']}"
        )


def assert_ordered_by_created_at(rows: Sequence[Mapping[str, Any]], label: str = "list") -> None:
    """Ascending creation order, the default order of every list read."""
    instants = [canonical_instant(row["created_at"]) for row in rows]
    assert instants == sorted(instants), (
        f"{label} should be ordered by created_at ascending, got {instants}"
    )


def assert_ids(
    rows: Sequence[Mapping[str, Any]], expected_ids: Sequence[str], label: str = "list"
) -> None:
    """The rows are exactly these identifiers, in this order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"{label} should hold {expected_ids}, got {actual}"


def assert_id_set(
    rows: Sequence[Mapping[str, Any]], expected_ids: Iterable[str], label: str = "list"
) -> None:
    """The rows are exactly these identifiers, in any order."""
    actual = sorted(row["id"] for row in rows)
    expected = sorted(expected_ids)
    assert actual == expected, f"{label} should hold {expected}, got {actual}"


def find_by(rows: Iterable[Mapping[str, Any]], **criteria: Any) -> Dict[str, Any]:
    """The single row matching every criterion; fails when it is not unique."""
    matches = [
        row for row in rows if all(row.get(key) == value for key, value in criteria.items())
    ]
    assert len(matches) == 1, (
        f"expected exactly one row matching {criteria}, found {len(matches)}"
    )
    return dict(matches[0])


def filter_by(rows: Iterable[Mapping[str, Any]], **criteria: Any) -> List[Dict[str, Any]]:
    """Every row matching every criterion, order preserved."""
    return [
        dict(row) for row in rows if all(row.get(key) == value for key, value in criteria.items())
    ]


# ── Inventory pool ─────────────────────────────────────────────────────────


def assert_pool_identity(day: Mapping[str, Any]) -> None:
    """The conservation identity: ceiling equals held plus committed plus pool."""
    ceiling = day["overbooking_ceiling_units"]
    total = day["allocated_units"] + day["committed_units"] + day["shared_pool_units"]
    assert ceiling == total, (
        f"inventory day {day.get('stay_date')}: overbooking_ceiling_units {ceiling} should equal "
        f"allocated_units {day['allocated_units']} + committed_units {day['committed_units']} "
        f"+ shared_pool_units {day['shared_pool_units']} = {total}"
    )


def assert_inventory_day(
    day: Mapping[str, Any],
    capacity: Optional[int] = None,
    ceiling: Optional[int] = None,
    allocated: Optional[int] = None,
    committed: Optional[int] = None,
    shared: Optional[int] = None,
    pooled_state: Optional[str] = None,
) -> None:
    """The five derived numbers and the posture of one night, plus the identity."""
    label = f"inventory day {day.get('stay_date')}"
    if capacity is not None:
        assert day["physical_capacity_units"] == capacity, (
            f"{label}: physical_capacity_units should be {capacity}, "
            f"got {day['physical_capacity_units']}"
        )
    if ceiling is not None:
        assert day["overbooking_ceiling_units"] == ceiling, (
            f"{label}: overbooking_ceiling_units should be {ceiling}, "
            f"got {day['overbooking_ceiling_units']}"
        )
    if allocated is not None:
        assert day["allocated_units"] == allocated, (
            f"{label}: allocated_units should be {allocated}, got {day['allocated_units']}"
        )
    if committed is not None:
        assert day["committed_units"] == committed, (
            f"{label}: committed_units should be {committed}, got {day['committed_units']}"
        )
    if shared is not None:
        assert day["shared_pool_units"] == shared, (
            f"{label}: shared_pool_units should be {shared}, got {day['shared_pool_units']}"
        )
    if pooled_state is not None:
        assert day["pooled_state"] == pooled_state, (
            f"{label}: pooled_state should be {pooled_state}, got {day['pooled_state']}"
        )
    assert_pool_identity(day)


# ── Money ──────────────────────────────────────────────────────────────────


def assert_money_identity(
    gross: int, commission: int, net: int, label: str = "reservation"
) -> None:
    """Gross equals net plus commission, on a reservation or on any rollup."""
    assert gross == net + commission, (
        f"{label}: gross {gross} should equal net {net} + commission {commission} "
        f"= {net + commission}"
    )


def assert_reservation_totals(
    reservation: Mapping[str, Any],
    gross: Optional[int] = None,
    commission: Optional[int] = None,
    net: Optional[int] = None,
    loyalty_credit: Optional[int] = None,
) -> None:
    """The three reservation totals and the terminal loyalty credit."""
    if gross is not None:
        assert reservation["gross_amount_cents"] == gross, (
            f"gross_amount_cents should be {gross}, got {reservation['gross_amount_cents']}"
        )
    if commission is not None:
        assert reservation["commission_amount_cents"] == commission, (
            f"commission_amount_cents should be {commission}, "
            f"got {reservation['commission_amount_cents']}"
        )
    if net is not None:
        assert reservation["net_amount_cents"] == net, (
            f"net_amount_cents should be {net}, got {reservation['net_amount_cents']}"
        )
    if loyalty_credit is not None:
        assert reservation["loyalty_credit_cents"] == loyalty_credit, (
            f"loyalty_credit_cents should be {loyalty_credit}, "
            f"got {reservation['loyalty_credit_cents']}"
        )
    assert_money_identity(
        reservation["gross_amount_cents"],
        reservation["commission_amount_cents"],
        reservation["net_amount_cents"],
    )


def assert_nightly_breakdown(
    reservation: Mapping[str, Any], expected_nights: Sequence[Mapping[str, Any]]
) -> None:
    """One entry per night, ascending by stay date, each field as expected."""
    nights = reservation["nightly_breakdown"]
    assert len(nights) == len(expected_nights), (
        f"nightly_breakdown should hold {len(expected_nights)} nights, got {len(nights)}"
    )
    dates = [night["stay_date"] for night in nights]
    assert dates == sorted(dates), (
        f"nightly_breakdown should be ordered by stay_date ascending, got {dates}"
    )
    for index, (actual, expected) in enumerate(zip(nights, expected_nights)):
        for field, value in expected.items():
            assert actual[field] == value, (
                f"nightly_breakdown[{index}].{field} should be {value!r}, got {actual[field]!r}"
            )


def assert_channel_ledger(channel: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """The channel's lifetime ledger, plus the money identity across it."""
    for field, value in expected.items():
        assert channel[field] == value, (
            f"channel.{field} should be {value}, got {channel[field]}"
        )
    assert_money_identity(
        channel["gross_revenue_cents"],
        channel["commission_accrued_cents"],
        channel["net_revenue_cents"],
        label="channel ledger",
    )


# ── Distribution ───────────────────────────────────────────────────────────


def assert_batch_counters(
    batch: Mapping[str, Any],
    batch_state: Optional[str] = None,
    total_jobs: Optional[int] = None,
    applied_jobs: Optional[int] = None,
    rejected_jobs: Optional[int] = None,
    abandoned_jobs: Optional[int] = None,
) -> None:
    """The derived batch state together with its four child counters."""
    if batch_state is not None:
        assert batch["batch_state"] == batch_state, (
            f"batch_state should be {batch_state}, got {batch['batch_state']}"
        )
    for field, value in (
        ("total_jobs", total_jobs),
        ("applied_jobs", applied_jobs),
        ("rejected_jobs", rejected_jobs),
        ("abandoned_jobs", abandoned_jobs),
    ):
        if value is not None:
            assert batch[field] == value, f"batch.{field} should be {value}, got {batch[field]}"


def assert_sequence_indices_one_based(jobs: Sequence[Mapping[str, Any]]) -> None:
    """Fan-out numbers the children from 1 upward with no gaps."""
    indices = sorted(job["sequence_index"] for job in jobs)
    expected = list(range(1, len(jobs) + 1))
    assert indices == expected, (
        f"sequence_index should be the 1-based run {expected}, got {indices}"
    )


def assert_job(
    job: Mapping[str, Any],
    job_state: Optional[str] = None,
    attempt_count: Optional[int] = None,
    failure_reason: Any = "__unset__",
    payload_rate_cents: Any = "__unset__",
    channel_mapping_id: Optional[str] = None,
) -> None:
    """One distribution job's outcome fields."""
    if job_state is not None:
        assert job["job_state"] == job_state, (
            f"job_state should be {job_state}, got {job['job_state']}"
        )
    if attempt_count is not None:
        assert job["attempt_count"] == attempt_count, (
            f"attempt_count should be {attempt_count}, got {job['attempt_count']}"
        )
    if failure_reason != "__unset__":
        assert job["failure_reason"] == failure_reason, (
            f"failure_reason should be {failure_reason!r}, got {job['failure_reason']!r}"
        )
    if payload_rate_cents != "__unset__":
        assert job["payload_rate_cents"] == payload_rate_cents, (
            f"payload_rate_cents should be {payload_rate_cents!r}, "
            f"got {job['payload_rate_cents']!r}"
        )
    if channel_mapping_id is not None:
        assert job["channel_mapping_id"] == channel_mapping_id, (
            f"channel_mapping_id should be {channel_mapping_id}, got {job['channel_mapping_id']}"
        )


# ── Computed reads ─────────────────────────────────────────────────────────


def assert_quoted_rate(quote: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """Every step of the six-step resolution the quoted-rate read exposes."""
    for field, value in expected.items():
        assert field in quote, f"quoted rate should carry {field}"
        assert quote[field] == value, (
            f"quoted rate {field} should be {value!r}, got {quote[field]!r}"
        )


def assert_performance(performance: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """A channel performance read, plus the money identity across its totals."""
    for field, value in expected.items():
        assert field in performance, f"performance should carry {field}"
        assert performance[field] == value, (
            f"performance {field} should be {value!r}, got {performance[field]!r}"
        )
    assert_money_identity(
        performance["gross_amount_cents"],
        performance["commission_amount_cents"],
        performance["net_amount_cents"],
        label="performance",
    )


def assert_pace(pace: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    for field, value in expected.items():
        assert field in pace, f"pace read should carry {field}"
        assert pace[field] == value, f"pace {field} should be {value!r}, got {pace[field]!r}"


def assert_ranked_channel(entry: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """One channel-mix entry, whose declared fields are exactly five."""
    assert_field_set(
        entry,
        ["rank", "net_adr_cents", "commission_bp", "commission_cost_ratio_bp", "room_nights"],
        entity_name="ranked channel",
    )
    for field, value in expected.items():
        assert entry[field] == value, (
            f"ranked channel {field} should be {value!r}, got {entry[field]!r}"
        )
