"""Domain assertions for the Executive Protection & Travel Risk Management API."""

import re
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import is_valid_uuid

INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

LIST_ONLY_META_FIELDS = ("limit", "offset", "total_count", "has_more")


def round_half_up(value, places=2):
    """Round half-up to ``places`` decimals, the rounding mode the service uses."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_half_up_cents(value):
    """Round half-up to a whole cent."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def assert_instant_format(value, field="timestamp"):
    """An instant is rendered with exactly three fractional digits and a Z."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert INSTANT_RE.match(value), (
        f"{field} must be an ISO-8601 UTC instant with exactly three fractional "
        f"digits and a trailing Z, got {value!r}"
    )


def assert_identifier(value, field="id"):
    """Identifiers are UUID strings with no type prefix of any kind."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_valid_uuid(value), f"{field} must be a bare UUID, got {value!r}"
    assert ":" not in value and "_" not in value, (
        f"{field} must carry no type prefix, got {value!r}"
    )


def assert_common_fields(entity, expected_version=None):
    """A mutable entity carries id, created_at, updated_at and version."""
    assert_identifier(entity.get("id"))
    assert_instant_format(entity.get("created_at"), "created_at")
    assert_instant_format(entity.get("updated_at"), "updated_at")
    assert isinstance(entity.get("version"), int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1 on creation"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_fields(entity):
    """An append-only row carries only id and created_at of the common fields."""
    assert_identifier(entity.get("id"))
    assert_instant_format(entity.get("created_at"), "created_at")
    assert "updated_at" not in entity, (
        "an append-only row must omit updated_at, not carry it as null"
    )
    assert "version" not in entity, (
        "an append-only row must omit version, not carry it as null"
    )


def assert_field_absent(entity, field):
    assert field not in entity, f"{field} must be absent from this representation"


def assert_single_resource_meta(response):
    """A single-resource response omits the four list-only meta fields."""
    meta = response.json()["meta"]
    for field in LIST_ONLY_META_FIELDS:
        assert field not in meta, (
            f"a single-resource response must omit meta.{field}"
        )


def assert_error_meta_shape(response):
    """An error response's meta carries only the request id and timestamp."""
    meta = response.json()["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must contain only api_request_id and api_request_timestamp, "
        f"got {sorted(meta.keys())}"
    )


def assert_envelope_meta(response):
    """Every response carries a req_-prefixed request id and an instant."""
    meta = response.json()["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta.get("api_request_timestamp"), "api_request_timestamp")


def assert_decimal_value(actual, expected, field="value"):
    """Compare a two-decimal-place figure against its expected value."""
    assert actual is not None, f"{field} must be present"
    assert round_half_up(actual, 2) == round_half_up(expected, 2), (
        f"expected {field} {expected}, got {actual}"
    )


def assert_cents(actual, expected, field="cents figure"):
    """Cents are whole integers, never strings and never fractional."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"expected {field} {expected}, got {actual}"


def assert_trip_states(trip, approval_state=None, readiness_state=None):
    if approval_state is not None:
        assert trip["approval_state"] == approval_state, (
            f"expected approval_state {approval_state}, got {trip['approval_state']}"
        )
    if readiness_state is not None:
        assert trip["readiness_state"] == readiness_state, (
            f"expected readiness_state {readiness_state}, "
            f"got {trip['readiness_state']}"
        )


def assert_budget_ledger(executive, committed=None, spent=None, remaining=None):
    """The money ledger identity: annual = committed + spent + remaining."""
    annual = executive["annual_security_budget_cents"]
    if committed is not None:
        assert_cents(
            executive["committed_budget_cents"], committed, "committed_budget_cents"
        )
    if spent is not None:
        assert_cents(executive["spent_budget_cents"], spent, "spent_budget_cents")
    if remaining is not None:
        assert_cents(
            executive["remaining_budget_cents"], remaining, "remaining_budget_cents"
        )
    assert (
        executive["committed_budget_cents"]
        + executive["spent_budget_cents"]
        + executive["remaining_budget_cents"]
        == annual
    ), (
        "remaining_budget_cents must equal the annual budget less committed "
        "and spent"
    )


def assert_staff_hours(staff, committed=None, released=None):
    if committed is not None:
        assert staff["committed_detail_hours"] == committed, (
            f"expected committed_detail_hours {committed}, "
            f"got {staff['committed_detail_hours']}"
        )
    if released is not None:
        assert staff["released_detail_hours"] == released, (
            f"expected released_detail_hours {released}, "
            f"got {staff['released_detail_hours']}"
        )


def assert_vendor_hours(vendor, committed):
    assert vendor["committed_engagement_hours"] == committed, (
        f"expected committed_engagement_hours {committed}, "
        f"got {vendor['committed_engagement_hours']}"
    )


def assert_items_in_canonical_order(items, canonical_order):
    """A derived item array is emitted in the canonical order, filtered."""
    ranks = [canonical_order.index(item) for item in items]
    assert ranks == sorted(ranks), (
        f"items must appear in canonical order {canonical_order}, got {items}"
    )


def assert_list_ordering(rows, key, descending=False):
    values = [row[key] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows must be ordered by {key} "
        f"{'descending' if descending else 'ascending'}, got {values}"
    )
