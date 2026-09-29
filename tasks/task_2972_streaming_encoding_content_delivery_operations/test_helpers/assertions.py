"""Domain assertions for the Streaming Encoding & Delivery Operations API.

Three groups live here:

* envelope and list helpers.  PRD §2.3 pages list endpoints with `page` and
  `page_size` and carries "the four pagination fields `page`, `page_size`,
  `total_count` and `has_more`" in `meta`, so this module supplies its own
  ``validate_paginated`` for that contract alongside ``validate_unpaginated``
  for the object-shaped responses (the sweep counters, an entitlement decision)
  that carry no pagination block at all.
* numeric helpers honouring the scales of PRD §2.8: two decimals for money,
  bandwidth and scores, four decimals for `rebuffer_ratio`, `error_rate` and
  `cost_per_gb_usd`.
* per-resource shape assertions honouring the §2.4 split between the ten
  versioned resources and the three immutable ones.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .api_client import canonical_instant, instants_equal, parse_instant
from .constants import (
    AVAILABILITY_STATES,
    JOB_STATES,
    LADDER_STATES,
    PACKAGE_STATES,
    PACKAGING_STATES,
    POLICY_STATES,
    QC_STATES,
    RESERVATION_STATES,
    SWEEP_COUNTER_FIELDS,
    VENDOR_STATES,
    WINDOW_STATES,
)

# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def assert_envelope(response: requests.Response, expected_response_type: str) -> dict:
    """Assert the §2.2 envelope: `meta`, `response_type` and `data`."""
    body = response.json()
    assert "meta" in body, f"missing meta: {body}"
    assert "response_type" in body, f"missing response_type: {body}"
    assert "data" in body, f"missing data: {body}"
    assert body["response_type"] == expected_response_type, (
        f"expected response_type {expected_response_type!r}, "
        f"got {body['response_type']!r}"
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), f"meta.api_request_id: {meta}"
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_timestamp_3ms(meta.get("api_request_timestamp"))
    return body


def assert_timestamp_3ms(value: Any) -> None:
    """Assert an "ISO 8601 UTC timestamp with three fractional digits" (§2.2, §2.4)."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    body, _, frac = value.partition(".")
    assert frac, f"timestamp {value!r} carries no fractional digits"
    digits = frac.rstrip("Z")
    assert len(digits) == 3, f"timestamp {value!r} must carry exactly three fractional digits"
    assert value.endswith("Z"), f"timestamp {value!r} must be UTC and end with 'Z'"
    assert body, f"timestamp {value!r} is malformed"


def validate_paginated(response: requests.Response) -> Tuple[List[dict], Dict[str, Any]]:
    """Validate a §2.3 paged list response and return (rows, meta).

    PRD §2.3: "For list responses the `meta` block carries the four pagination
    fields `page`, `page_size`, `total_count` and `has_more`".
    """
    body = assert_envelope(response, "array")
    assert response.status_code == 200, (
        f"expected 200 for a list, got {response.status_code}: {response.text}"
    )
    rows = body["data"]
    assert isinstance(rows, list), f"list data must be an array, got {type(rows)}"
    meta = body["meta"]
    assert isinstance(meta.get("page"), int), f"meta.page must be an int: {meta}"
    assert meta["page"] >= 1, f"meta.page is 1-based: {meta}"
    assert isinstance(meta.get("page_size"), int), f"meta.page_size must be an int: {meta}"
    assert 1 <= meta["page_size"] <= 100, f"meta.page_size out of range: {meta}"
    assert isinstance(meta.get("total_count"), int), f"meta.total_count must be an int: {meta}"
    assert meta["total_count"] >= 0, f"meta.total_count must be non-negative: {meta}"
    assert isinstance(meta.get("has_more"), bool), f"meta.has_more must be a bool: {meta}"
    assert len(rows) <= meta["page_size"], (
        f"page carries {len(rows)} rows, more than page_size {meta['page_size']}"
    )
    return rows, meta


def validate_unpaginated(response: requests.Response, expected_status: int = 200) -> Any:
    """Validate a 2xx response whose `data` carries no pagination block.

    Used for the object-shaped reads and computed responses -- the sweep's
    counter object and a playback entitlement decision -- where §2.2 says the
    `meta` block carries only `api_request_id` and `api_request_timestamp`.
    """
    body = assert_envelope(response, "object")
    assert response.status_code == expected_status, (
        f"expected {expected_status}, got {response.status_code}: {response.text}"
    )
    return body["data"]


def assert_list_ids(rows: Sequence[dict], expected_ids: Sequence[str]) -> None:
    """Assert a list returned exactly these ids in exactly this order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), f"expected ids {list(expected_ids)}, got {actual}"


def assert_ordered_by(
    rows: Sequence[dict], field: str, descending: bool = False
) -> None:
    """Assert rows are ordered by one field (§2.3 default and its overrides)."""
    values = [row[field] for row in rows]
    if values and isinstance(values[0], str) and _looks_like_instant(values[0]):
        values = [canonical_instant(v) for v in values]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows are not ordered by {field} "
        f"{'descending' if descending else 'ascending'}: {values}"
    )


def _looks_like_instant(value: str) -> bool:
    return len(value) >= 19 and value[4] == "-" and "T" in value


def assert_instant_equals(actual: Any, expected: str, name: str = "instant") -> None:
    """Compare two instants at millisecond resolution (§2.8)."""
    assert isinstance(actual, str), f"{name}: expected an instant string, got {actual!r}"
    assert instants_equal(actual, expected), (
        f"{name}: expected instant {canonical_instant(expected)}, got {actual!r}"
    )


def assert_instant_before(earlier: str, later: str) -> None:
    assert parse_instant(earlier) < parse_instant(later), (
        f"{earlier!r} is not strictly before {later!r}"
    )


# ---------------------------------------------------------------------------
# Numeric helpers (§2.8)
# ---------------------------------------------------------------------------


def _q(value: Any, places: int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def assert_money(actual: Any, expected: float, field: str = "amount") -> None:
    """Assert a money or bandwidth or score value at two decimal places (§2.8)."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be a JSON number, got {actual!r}"
    )
    assert _q(actual, 2) == _q(expected, 2), f"{field}: expected {expected}, got {actual}"


def assert_score(actual: Any, expected: float, field: str = "score") -> None:
    """Score-shaped values are two decimals rounded half up (§2.8)."""
    assert_money(actual, expected, field)


def assert_ratio_4dp(actual: Any, expected: float, field: str = "ratio") -> None:
    """`rebuffer_ratio`, `error_rate` and `cost_per_gb_usd` carry four decimals (§2.8)."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be a JSON number, got {actual!r}"
    )
    assert _q(actual, 4) == _q(expected, 4), f"{field}: expected {expected}, got {actual}"


def assert_two_decimal_scale(actual: Any, field: str = "amount") -> None:
    """Assert a number carries no more than two decimal places (§2.8)."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{field} must be a JSON number, got {actual!r}"
    )
    exponent = -Decimal(str(actual)).as_tuple().exponent
    assert exponent <= 2, f"{field} {actual} carries more than two decimal places"


def assert_money_list(actual: Any, expected: Sequence[float], field: str) -> None:
    """Assert an array of money values element by element and in order."""
    assert isinstance(actual, list), f"{field} must be an array, got {actual!r}"
    assert len(actual) == len(expected), (
        f"{field}: expected {len(expected)} entries {list(expected)}, got {actual}"
    )
    for index, (got, want) in enumerate(zip(actual, expected)):
        assert_money(got, want, f"{field}[{index}]")


# ---------------------------------------------------------------------------
# Identity and versioning (§2.4)
# ---------------------------------------------------------------------------


def assert_identity_fields(resource: dict, name: str = "resource") -> None:
    """Assert the bare-UUID `id` and the `created_at` instant of §2.4."""
    assert is_valid_uuid(resource.get("id", "")), (
        f"{name}.id must be a UUID string with no type prefix, got {resource.get('id')!r}"
    )
    assert_timestamp_3ms(resource.get("created_at"))


def assert_versioned_resource(resource: dict, name: str = "resource") -> None:
    """Assert the full §2.4 identity set: id, created_at, updated_at, version."""
    assert_identity_fields(resource, name)
    assert_timestamp_3ms(resource.get("updated_at"))
    assert isinstance(resource.get("version"), int), (
        f"{name}.version must be an integer, got {resource.get('version')!r}"
    )
    assert resource["version"] >= 1, f"{name}.version starts at 1, got {resource['version']}"


def assert_immutable_resource(resource: dict, name: str = "resource") -> None:
    """Assert a §2.4 immutable resource carries only `id` and `created_at`.

    "Three resources are deliberately immutable and therefore carry only `id`
    and `created_at`, with **no** `updated_at` and **no** `version` field at
    all".
    """
    assert_identity_fields(resource, name)
    assert "updated_at" not in resource, f"{name} must carry no updated_at: {resource}"
    assert "version" not in resource, f"{name} must carry no version field: {resource}"


def assert_version_is(resource: dict, expected: int, name: str = "resource") -> None:
    assert resource.get("version") == expected, (
        f"{name}.version: expected {expected}, got {resource.get('version')}"
    )


# ---------------------------------------------------------------------------
# Per-resource shape assertions
# ---------------------------------------------------------------------------


def assert_title_shape(title: dict) -> None:
    assert_versioned_resource(title, "Title")
    for field in ("external_ref", "title_name", "content_type", "studio_code"):
        assert isinstance(title.get(field), str), f"Title.{field} must be a string: {title}"
    assert title["availability_state"] in AVAILABILITY_STATES, title
    assert title["packaging_state"] in PACKAGING_STATES, title
    assert_two_decimal_scale(title["encode_budget_usd"], "Title.encode_budget_usd")
    assert_two_decimal_scale(
        title["encode_budget_remaining_usd"], "Title.encode_budget_remaining_usd"
    )
    assert_two_decimal_scale(
        title["readiness_score_provisional"], "Title.readiness_score_provisional"
    )
    assert_two_decimal_scale(
        title["readiness_score_certified"], "Title.readiness_score_certified"
    )
    assert isinstance(title["locked_ladder_count"], int), title
    assert title["readiness_score_certified"] <= title["readiness_score_provisional"], (
        "the certified score is always at or below the provisional score: "
        f"{title['readiness_score_certified']} > {title['readiness_score_provisional']}"
    )


def assert_asset_shape(asset: dict) -> None:
    assert_versioned_resource(asset, "MezzanineAsset")
    assert asset["qc_state"] in QC_STATES, asset
    assert isinstance(asset["qc_attempt_count"], int), asset
    assert_two_decimal_scale(
        asset["latest_severity_index"], "MezzanineAsset.latest_severity_index"
    )
    assert isinstance(asset["caption_languages"], list), asset


def assert_qc_report_shape(report: dict) -> None:
    assert_immutable_resource(report, "QualityControlReport")
    assert isinstance(report["attempt_number"], int), report
    assert report["verdict"] in ("PASS", "WARN", "FAIL"), report
    assert_timestamp_3ms(report["evaluated_at"])


def assert_ladder_shape(ladder: dict) -> None:
    assert_versioned_resource(ladder, "EncodingLadder")
    assert ladder["state"] in LADDER_STATES, ladder
    assert isinstance(ladder["rungs"], list), ladder
    assert ladder["rung_count"] == len(ladder["rungs"]), ladder
    assert ladder["peak_bitrate_kbps"] == max(r["bitrate_kbps"] for r in ladder["rungs"]), ladder
    assert ladder["peak_height_px"] == max(r["height_px"] for r in ladder["rungs"]), ladder
    assert_two_decimal_scale(
        ladder["device_compat_score"], "EncodingLadder.device_compat_score"
    )


def assert_device_profile_shape(profile: dict) -> None:
    assert_versioned_resource(profile, "DeviceProfile")
    assert profile["state"] in ("ACTIVE", "RETIRED"), profile
    assert isinstance(profile["supported_codecs"], list), profile
    assert_two_decimal_scale(profile["market_share_pct"], "DeviceProfile.market_share_pct")


def assert_package_shape(package: dict) -> None:
    assert_versioned_resource(package, "DrmPackage")
    assert package["state"] in PACKAGE_STATES, package
    assert package["hdcp_floor"] in ("NONE", "TYPE_0", "TYPE_1"), package
    assert package["stale_reason"] in ("NONE", "LADDER_SUPERSEDED", "CODEC_STANDARD_CHANGE"), package
    assert isinstance(package["entitlement_rule_count"], int), package


def assert_entitlement_rule_shape(rule: dict) -> None:
    assert_immutable_resource(rule, "EntitlementRule")
    assert isinstance(rule["priority"], int), rule
    assert rule["hdcp_level"] in ("NONE", "TYPE_0", "TYPE_1"), rule


def assert_window_shape(window: dict) -> None:
    assert_versioned_resource(window, "AvailabilityWindow")
    assert window["state"] in WINDOW_STATES, window
    assert_timestamp_3ms(window["window_start_at"])
    assert_timestamp_3ms(window["window_end_at"])
    assert_instant_before(window["window_start_at"], window["window_end_at"])


def assert_vendor_shape(vendor: dict) -> None:
    assert_versioned_resource(vendor, "CdnVendor")
    assert vendor["state"] in VENDOR_STATES, vendor
    assert isinstance(vendor["regions"], list), vendor
    assert_two_decimal_scale(vendor["committed_gbps"], "CdnVendor.committed_gbps")
    assert_two_decimal_scale(vendor["reserved_gbps"], "CdnVendor.reserved_gbps")
    assert isinstance(vendor["breach_window_count"], int), vendor


def assert_policy_shape(policy: dict) -> None:
    assert_versioned_resource(policy, "RoutingPolicy")
    assert policy["state"] in POLICY_STATES, policy
    assert isinstance(policy["excluded_vendor_ids"], list), policy
    assert isinstance(policy["resteer_count"], int), policy
    assert_two_decimal_scale(
        policy["projected_egress_cost_usd"], "RoutingPolicy.projected_egress_cost_usd"
    )


def assert_metric_window_shape(window: dict) -> None:
    assert_immutable_resource(window, "PlaybackMetricWindow")
    assert isinstance(window["breach_flag"], bool), window
    assert isinstance(window["play_attempts"], int), window


def assert_reservation_shape(reservation: dict) -> None:
    assert_versioned_resource(reservation, "LiveEventReservation")
    assert reservation["state"] in RESERVATION_STATES, reservation
    assert_two_decimal_scale(
        reservation["reserved_gbps"], "LiveEventReservation.reserved_gbps"
    )
    assert_two_decimal_scale(
        reservation["released_gbps"], "LiveEventReservation.released_gbps"
    )
    assert isinstance(reservation["buffer_minutes"], int), reservation


def assert_job_shape(job: dict) -> None:
    assert_versioned_resource(job, "ReprocessJob")
    assert job["state"] in JOB_STATES, job
    assert isinstance(job["per_rung_cost_usd"], list), job
    assert_two_decimal_scale(job["cost_estimate_usd"], "ReprocessJob.cost_estimate_usd")
    assert_two_decimal_scale(job["committed_usd"], "ReprocessJob.committed_usd")
    assert_two_decimal_scale(job["priority_rank"], "ReprocessJob.priority_rank")


# ---------------------------------------------------------------------------
# Sweep counters (§2.5)
# ---------------------------------------------------------------------------


def assert_sweep_counters(counters: dict, **expected: int) -> None:
    """Assert the sweep's nine integer counters; unnamed counters must be zero.

    PRD §2.5: "The sweep returns a per-phase count object with exactly nine
    integer fields".
    """
    for field in SWEEP_COUNTER_FIELDS:
        assert field in counters, f"sweep response is missing {field}: {counters}"
        assert isinstance(counters[field], int), f"{field} must be an integer: {counters}"
    unknown = set(expected) - set(SWEEP_COUNTER_FIELDS)
    assert not unknown, f"not sweep counters: {sorted(unknown)}"
    for field in SWEEP_COUNTER_FIELDS:
        want = expected.get(field, 0)
        assert counters[field] == want, (
            f"sweep counter {field}: expected {want}, got {counters[field]} "
            f"(full counters: {counters})"
        )


def assert_all_sweep_counters_zero(counters: dict) -> None:
    """The sweep "is idempotent for a fixed clock value" (§2.5)."""
    assert_sweep_counters(counters)


# ---------------------------------------------------------------------------
# Conserved quantities (§2.9)
# ---------------------------------------------------------------------------


def assert_bandwidth_conserved(
    vendor_reserved: Iterable[float], expected_total: float
) -> None:
    """Sum of `reserved_gbps` across vendors equals the global held total (§2.9)."""
    total = sum(_q(value, 2) for value in vendor_reserved)
    assert total == _q(expected_total, 2), (
        f"global held bandwidth: expected {expected_total}, got {total}"
    )


def assert_budget_invariant(title: dict, committed_usd: Iterable[float]) -> None:
    """`encode_budget_remaining_usd` plus every job's `committed_usd` equals
    `encode_budget_usd` (§2.9)."""
    committed = list(committed_usd)
    total = _q(title["encode_budget_remaining_usd"], 2) + sum(
        _q(value, 2) for value in committed
    )
    assert total == _q(title["encode_budget_usd"], 2), (
        f"money invariant broken: remaining {title['encode_budget_remaining_usd']} "
        f"plus committed {committed} != budget {title['encode_budget_usd']}"
    )


__all__ = [name for name in dir() if name.startswith("assert_") or name.startswith("validate_")]
