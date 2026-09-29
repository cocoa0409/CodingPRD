"""Entity-shape assertions, list validators, and reference calculators."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional, Sequence

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant, instants_equal
from .constants import THRESHOLDS
from .types import (
    LOCALIZATION_JOB_OPEN_STATES,
    SEVERITY_RANK_ORDER,
    WRITER_COUNTED_PLAN_ITEM_STATUSES,
)

# ---------------------------------------------------------------------------
# Rounding and arithmetic conventions (§2.7)
# ---------------------------------------------------------------------------


def round_half_up(value: float | Decimal | int, places: int = 2) -> float:
    """Round half up to ``places`` decimals — "a value exactly at the midpoint
    rounds away from zero" (§2.7)."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_cents(value: float | Decimal | int) -> int:
    """Round half up to whole cents (§2.7)."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(value: float | Decimal | int) -> int:
    """Discard any fraction downwards (§2.7)."""
    return int(Decimal(str(value)) // 1)


# ---------------------------------------------------------------------------
# Date helpers (§2.4, §2.10)
# ---------------------------------------------------------------------------


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant into a naive UTC ``datetime``."""
    text = canonical_instant(value)
    assert text is not None
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ")


def shift_date(value: str, days: int) -> str:
    """``value`` plus ``days`` calendar days, as a ``YYYY-MM-DD`` string."""
    return (parse_date(value) + timedelta(days=days)).isoformat()


def date_of_instant(value: str) -> str:
    """Reduce an instant to its UTC calendar date (§2.4)."""
    text = canonical_instant(value)
    assert text is not None
    return text[:10]


def instant_at(day: str, time_part: str = "00:00:00.000") -> str:
    """Build an ISO-8601 UTC instant from a ``YYYY-MM-DD`` day."""
    return f"{day}T{time_part}Z"


def closed_window_days(start: str, end: str) -> int:
    """Days from ``start`` through ``end`` inclusive — closed interval (§3.8)."""
    return (parse_date(end) - parse_date(start)).days + 1


def whole_days_between(start_instant: str, end_instant: str) -> int:
    """Whole days between two instants, fractional day discarded (§3.5)."""
    delta = parse_instant(end_instant) - parse_instant(start_instant)
    return int(delta.total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Envelope and audit-field assertions (§2.2, §2.4)
# ---------------------------------------------------------------------------


def assert_response_envelope(response: requests.Response, expected_response_type: str) -> None:
    """The envelope carries a ``req_``-prefixed id, a 3-digit timestamp and a type."""
    body = response.json()
    assert "meta" in body, f"missing meta: {body}"
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert_instant_format(meta["api_request_timestamp"])
    assert body["response_type"] == expected_response_type, body["response_type"]


def assert_error_envelope(response: requests.Response) -> None:
    """An error body's ``data`` holds exactly ``error_id`` and ``message``, and its
    ``meta`` holds only the two request fields (§2.2)."""
    body = response.json()
    assert body["response_type"] == "error", body
    assert set(body["data"].keys()) == {"error_id", "message"}, body["data"]
    assert set(body["meta"].keys()) == {
        "api_request_id",
        "api_request_timestamp",
    }, body["meta"]


def assert_instant_format(value: str) -> None:
    """ISO-8601 UTC with exactly three fractional digits and a trailing ``Z`` (§2.4)."""
    assert isinstance(value, str), f"not a string: {value!r}"
    assert value.endswith("Z"), f"missing trailing Z: {value!r}"
    assert len(value) == 24, f"expected exactly 3 fractional digits: {value!r}"
    assert value[10] == "T" and value[19] == ".", f"malformed instant: {value!r}"
    assert is_iso8601_timestamp(value), f"not ISO-8601: {value!r}"


def assert_calendar_date_format(value: str) -> None:
    """``YYYY-MM-DD`` with no time component (§2.4)."""
    assert isinstance(value, str), f"not a string: {value!r}"
    assert len(value) == 10, f"not a bare calendar date: {value!r}"
    parse_date(value)


def assert_versioned_audit_fields(data: dict[str, Any], expected_version: int | None = None) -> None:
    """``id``, ``created_at``, ``updated_at`` and ``version`` (§2.4)."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert_instant_format(data["created_at"])
    assert_instant_format(data["updated_at"])
    assert isinstance(data["version"], int), data["version"]
    assert data["version"] >= 1, data["version"]
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_append_only_audit_fields(data: dict[str, Any]) -> None:
    """An append-only record carries only ``id`` and ``created_at`` (§2.4)."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert_instant_format(data["created_at"])
    assert "updated_at" not in data, f"append-only record exposes updated_at: {data}"
    assert "version" not in data, f"append-only record exposes version: {data}"


# ---------------------------------------------------------------------------
# List validators (§2.3)
# ---------------------------------------------------------------------------


def validate_list(response: requests.Response) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Paginated collection read: returns ``(rows, meta)`` and checks the four
    pagination fields are present in ``meta``."""
    rows, meta = validate_paginated(response)
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"paginated meta missing {field}: {meta}"
    return rows, meta


def validate_unpaginated_list(
    response: requests.Response, expected_status: int = 200
) -> list[dict[str, Any]]:
    """Array-typed read whose ``meta`` need not carry pagination fields.

    Use this for list-shaped payloads the PRD does not describe as paginated
    collections, so a missing ``total_count`` is not treated as a failure.
    """
    data = validate_success(response, expected_status=expected_status)
    assert isinstance(data, list), f"expected an array payload, got {type(data)}: {data!r}"
    return data


def assert_pagination_meta(
    meta: dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta["limit"] == limit, meta
    assert meta["offset"] == offset, meta
    assert meta["total_count"] == total_count, meta
    assert meta["has_more"] is has_more, meta


def assert_ids_in_order(rows: Sequence[dict[str, Any]], expected_ids: Sequence[str]) -> None:
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"expected order {list(expected_ids)}, got {[row['id'] for row in rows]}"
    )


def assert_sorted_ascending(rows: Sequence[dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), f"{field} not ascending: {values}"


def assert_sorted_descending(rows: Sequence[dict[str, Any]], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values, reverse=True), f"{field} not descending: {values}"


def assert_created_at_ascending(rows: Sequence[dict[str, Any]]) -> None:
    values = [canonical_instant(row["created_at"]) for row in rows]
    assert values == sorted(values), f"created_at not ascending: {values}"


def assert_created_at_descending(rows: Sequence[dict[str, Any]]) -> None:
    values = [canonical_instant(row["created_at"]) for row in rows]
    assert values == sorted(values, reverse=True), f"created_at not descending: {values}"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------


def assert_release_train(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["product_key"], str)
    assert isinstance(data["version_label"], str)
    for field in ("doc_freeze_date", "ga_date", "support_end_date"):
        assert_calendar_date_format(data[field])
    assert isinstance(data["localization_budget_cap_cents"], int)
    assert data["status"] in {
        "PLANNED", "DOC_FREEZE", "GA", "MAINTENANCE", "END_OF_LIFE",
    }, data["status"]
    assert data["doc_readiness_posture"] in {"OPEN", "RESTRICTED", "FROZEN"}, data
    assert isinstance(data["approved_topic_ratio"], (int, float))
    assert isinstance(data["plan_item_count"], int)
    assert isinstance(data["approved_plan_item_count"], int)
    assert isinstance(data["localization_committed_cents"], int)
    assert isinstance(data["eol_notice_posted"], bool)


def assert_new_release_train_defaults(data: dict[str, Any]) -> None:
    """A newly registered train's opening figures (§3.1)."""
    assert data["status"] == "PLANNED", data["status"]
    assert data["doc_readiness_posture"] == "OPEN", data["doc_readiness_posture"]
    assert float(data["approved_topic_ratio"]) == 1.00, data["approved_topic_ratio"]
    assert data["plan_item_count"] == 0, data
    assert data["approved_plan_item_count"] == 0, data
    assert data["localization_committed_cents"] == 0, data
    assert data["eol_notice_posted"] is False, data
    assert data["version"] == 1, data


def assert_writer(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["person_key"], str)
    assert isinstance(data["full_name"], str)
    assert data["seniority_tier"] in {"ASSOCIATE", "SENIOR", "PRINCIPAL"}, data
    assert isinstance(data["capacity_points"], (int, float))
    assert data["status"] in {"ACTIVE", "ON_LEAVE"}, data
    assert isinstance(data["committed_load_points"], (int, float))
    assert isinstance(data["assignment_count"], int)


def assert_reviewer(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["person_key"], str)
    assert isinstance(data["full_name"], str)
    assert data["discipline"] in {"ENGINEERING", "PRODUCT"}, data
    assert isinstance(data["open_signoff_count"], int)


def assert_plan_item(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["release_train_id"])
    assert isinstance(data["feature_key"], str)
    assert data["ia_placement"] in {
        "NEW_TOPIC", "EXISTING_TOPIC_UPDATE", "CONCEPT_HUB",
    }, data
    assert data["audience_tier"] in {"CRITICAL", "STANDARD", "INTERNAL"}, data
    assert isinstance(data["planned_page_count"], int)
    assert isinstance(data["complexity_points"], int)
    assert data["status"] in {
        "DRAFTED", "ASSIGNED", "IN_AUTHORING", "IN_REVIEW",
        "IN_REVISION", "APPROVED_CONTENT", "PUBLISHED", "CANCELLED",
    }, data
    assert isinstance(data["load_points"], (int, float))
    assert isinstance(data["rework_count"], int)


def assert_topic(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["plan_item_id"])
    assert isinstance(data["slug"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["ia_depth"], int)
    assert data["review_state"] in {
        "NOT_SUBMITTED", "PENDING_SIGNOFF", "CHANGES_REQUESTED", "FULLY_APPROVED",
    }, data
    assert data["publication_state"] in {"UNPUBLISHED", "PUBLISHED", "ARCHIVED"}, data
    assert isinstance(data["current_revision_number"], int)
    assert isinstance(data["last_submitted_revision_number"], int)
    assert isinstance(data["latest_body_word_count"], int)
    assert isinstance(data["open_blocker_violations"], int)
    assert isinstance(data["open_warning_violations"], int)


def assert_new_topic_defaults(data: dict[str, Any]) -> None:
    """A newly created topic's opening figures (§3.3)."""
    assert data["review_state"] == "NOT_SUBMITTED", data
    assert data["publication_state"] == "UNPUBLISHED", data
    assert data["current_revision_number"] == 0, data
    assert data["last_submitted_revision_number"] == 0, data
    assert data["latest_body_word_count"] == 0, data
    assert data["open_blocker_violations"] == 0, data
    assert data["open_warning_violations"] == 0, data
    assert data["health_score"] is None, data


def assert_source_revision(data: dict[str, Any]) -> None:
    assert_append_only_audit_fields(data)
    assert is_valid_uuid(data["topic_id"])
    assert isinstance(data["revision_number"], int)
    assert is_valid_uuid(data["author_writer_id"])
    assert isinstance(data["body_word_count"], int)
    assert isinstance(data["summary"], str)
    assert isinstance(data["blocker_violation_count"], int)
    assert isinstance(data["warning_violation_count"], int)
    assert isinstance(data["violating_term_ids"], list)


def assert_signoff(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["topic_id"])
    assert is_valid_uuid(data["reviewer_id"])
    assert data["discipline"] in {"ENGINEERING", "PRODUCT"}, data
    assert data["state"] in {
        "PENDING", "APPROVED", "CHANGES_REQUESTED", "SUPERSEDED",
    }, data
    assert_instant_format(data["requested_at"])


def assert_doc_set_version(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["release_train_id"])
    assert isinstance(data["version_label"], str)
    assert data["status"] in {"DRAFT", "PUBLISHED", "SUPERSEDED", "ARCHIVED"}, data
    assert isinstance(data["published_topic_count"], int)
    assert isinstance(data["projected_localization_budget_cents"], int)


def assert_change_record(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["release_train_id"])
    assert isinstance(data["internal_summary"], str)
    assert data["severity"] in {
        "BREAKING", "SECURITY", "MAJOR", "MINOR", "PATCH",
    }, data
    assert data["category"] in {
        "FEATURE", "FIX", "PERFORMANCE", "SECURITY_PATCH", "DEPRECATION",
    }, data
    assert isinstance(data["affected_component"], str)
    assert data["state"] in {
        "SUBMITTED", "REWORK_REQUESTED", "EDITORIALLY_APPROVED", "EXCLUDED", "PUBLISHED",
    }, data
    assert isinstance(data["submitted_by_user_id"], str)
    assert isinstance(data["terminology_blocker_count"], int)
    assert isinstance(data["rework_count"], int)


def assert_release_note(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["release_train_id"])
    assert is_valid_uuid(data["doc_set_version_id"])
    assert data["status"] in {"COMPILED", "PUBLISHED", "SUPERSEDED"}, data
    assert_instant_format(data["compiled_at"])
    assert isinstance(data["severity_counts"], dict)
    assert set(data["severity_counts"].keys()) == set(SEVERITY_RANK_ORDER), (
        data["severity_counts"]
    )
    assert isinstance(data["included_change_record_ids"], list)


def assert_locale_profile(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["locale_code"], str)
    assert len(data["locale_code"]) == THRESHOLDS["locale_code_len"], data
    assert data["publication_mode"] in {"SIMULTANEOUS", "DELAYED"}, data
    assert isinstance(data["tm_coverage_pct"], (int, float))
    assert isinstance(data["per_word_rate_cents"], (int, float))
    assert isinstance(data["sla_days"], int)
    assert isinstance(data["parallel_job_limit"], int)
    assert data["status"] in {"ACTIVE", "PAUSED"}, data
    assert isinstance(data["committed_source_words"], int)
    assert isinstance(data["open_job_count"], int)


def assert_localization_job(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["topic_id"])
    assert is_valid_uuid(data["locale_profile_id"])
    assert_calendar_date_format(data["window_start_date"])
    assert_calendar_date_format(data["window_end_date"])
    assert data["state"] in {
        "QUEUED", "TRANSLATED", "REWORK_REQUESTED",
        "SCHEDULED_DELAYED", "PUBLISHED_LOCALIZED", "CANCELLED",
    }, data
    assert isinstance(data["auto_created"], bool)
    assert isinstance(data["source_revision_number"], int)
    assert isinstance(data["reserved_source_words"], int)
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["cost_variant"] in {"PROVISIONAL", "FINAL"}, data


def assert_terminology_term(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert isinstance(data["term"], str)
    assert isinstance(data["preferred_form"], str)
    assert isinstance(data["forbidden_forms"], list)
    assert data["enforcement_severity"] in {"BLOCKER", "WARNING"}, data
    assert data["status"] in {"ACTIVE", "RETIRED"}, data


def assert_deprecation_notice(data: dict[str, Any]) -> None:
    assert_versioned_audit_fields(data)
    assert is_valid_uuid(data["release_train_id"])
    assert isinstance(data["feature_key"], str)
    assert data["severity_tier"] in {"BREAKING", "MAJOR", "MINOR"}, data
    for field in ("announce_date", "deprecated_date", "removal_date", "earliest_removal_date"):
        assert_calendar_date_format(data[field])
    assert is_valid_uuid(data["migration_guide_topic_id"])
    assert isinstance(data["notice_days"], int)
    assert data["status"] in {"DRAFTED", "PUBLISHED", "RETIRED"}, data


def assert_page_feedback(data: dict[str, Any]) -> None:
    assert_append_only_audit_fields(data)
    assert is_valid_uuid(data["topic_id"])
    assert isinstance(data["rating"], int)
    assert THRESHOLDS["rating_min"] <= data["rating"] <= THRESHOLDS["rating_max"], data
    assert data["outcome"] in {
        "RESOLVED_SELF_SERVE", "OPENED_TICKET", "ABANDONED",
    }, data
    assert isinstance(data["locale_code"], str)
    assert isinstance(data["session_key"], str)


def assert_deflection_summary(data: dict[str, Any]) -> None:
    assert_calendar_date_format(data["window_start_date"])
    assert_calendar_date_format(data["window_end_date"])
    assert isinstance(data["sample_count"], int)
    for field in ("mean_rating", "deflection_pct", "ticket_rate_pct"):
        assert data[field] is None or isinstance(data[field], (int, float)), data


# ---------------------------------------------------------------------------
# Reference calculators — §3 formulas, for cross-checking server figures
# ---------------------------------------------------------------------------


def expected_load_points(
    planned_page_count: int,
    complexity_points: int,
    ia_placement: str,
    audience_tier: str,
    seniority_tier: str,
    rework_count: int = 0,
) -> float:
    """The six-step assignment load-point formula of §3.2."""
    size_points = THRESHOLDS["size_points_per_page"] * planned_page_count
    depth_points = min(complexity_points, THRESHOLDS["depth_points_cap"])
    ia_points = THRESHOLDS["ia_points"][ia_placement]
    raw = (
        Decimal(size_points + depth_points + ia_points)
        * Decimal(str(THRESHOLDS["audience_multiplier"][audience_tier]))
        / Decimal(str(THRESHOLDS["seniority_divisor"][seniority_tier]))
    )
    rounded = round_half_up(raw, 2)
    base = max(rounded, THRESHOLDS["load_points_floor"])
    total = Decimal(str(base)) + Decimal(str(THRESHOLDS["rework_load_points_per_unit"])) * rework_count
    return round_half_up(total, 2)


def expected_approved_topic_ratio(plan_item_count: int, approved_plan_item_count: int) -> float:
    """§3.1: ``1.00`` when ``plan_item_count`` is zero, else the rounded quotient."""
    if plan_item_count == 0:
        return THRESHOLDS["vacuous_approved_topic_ratio"]
    return round_half_up(Decimal(approved_plan_item_count) / Decimal(plan_item_count), 2)


def expected_posture(status: str, ratio: float) -> str:
    """§3.1's four-step posture decision."""
    if status in {"MAINTENANCE", "END_OF_LIFE"}:
        return "FROZEN"
    if status == "PLANNED":
        return "OPEN"
    if ratio >= THRESHOLDS["posture_open_ratio"]:
        return "OPEN"
    if ratio >= THRESHOLDS["posture_restricted_ratio"]:
        return "RESTRICTED"
    return "FROZEN"


def expected_eol_notice_text(product_key: str, version_label: str, support_end_date: str) -> str:
    """The exact end-of-life notice the train's last hop writes (§3.1)."""
    return (
        f"End of life: support for {product_key} {version_label} "
        f"ended on {support_end_date}."
    )


def expected_locale_projection_contribution(
    publishable_words: int, tm_coverage_pct: float, per_word_rate_cents: float
) -> int:
    """One locale's already-rounded contribution to the budget projection (§3.6)."""
    tm_words = floor_int(Decimal(publishable_words) * Decimal(str(tm_coverage_pct)) / Decimal(100))
    discounted = floor_int(Decimal(THRESHOLDS["projection_memory_discount_pct"]) * Decimal(tm_words) / Decimal(100))
    effective_words = publishable_words - discounted
    return round_cents(Decimal(effective_words) * Decimal(str(per_word_rate_cents)))


def expected_budget_projection(
    publishable_words: int, locales: Sequence[tuple[float, float]]
) -> int:
    """Round per locale, then sum (§3.6). ``locales`` is ``(tm_coverage_pct, rate)``
    in ``locale_code`` ascending order."""
    return sum(
        expected_locale_projection_contribution(publishable_words, coverage, rate)
        for coverage, rate in locales
    )


def expected_leverage_pct(source_words: int, memory_words: int) -> float:
    """Step two of the quote (§3.8)."""
    if source_words == 0:
        return 0.00
    return round_half_up(Decimal(memory_words) * Decimal(100) / Decimal(source_words), 2)


def expected_quote(
    source_words: int,
    memory_words: int,
    per_word_rate_cents: float,
    window_start_date: str,
    window_end_date: str,
    sla_days: int,
) -> dict[str, Any]:
    """The nine-step quote of §3.8, returning every intermediate figure."""
    leverage_pct = expected_leverage_pct(source_words, memory_words)
    discounted = floor_int(Decimal(THRESHOLDS["memory_discount_pct"]) * Decimal(memory_words) / Decimal(100))
    effective_words = source_words - discounted
    base_cost = round_cents(Decimal(effective_words) * Decimal(str(per_word_rate_cents)))
    window_len = closed_window_days(window_start_date, window_end_date)
    if window_len < sla_days:
        surcharge = round_cents(Decimal(THRESHOLDS["rush_surcharge_pct"]) * Decimal(base_cost) / Decimal(100))
    else:
        surcharge = 0
    subtotal = base_cost + surcharge
    if subtotal >= THRESHOLDS["discount_band_10_min_cents"]:
        discount_pct = THRESHOLDS["discount_pct_band_10"]
    elif subtotal >= THRESHOLDS["discount_band_6_min_cents"]:
        discount_pct = THRESHOLDS["discount_pct_band_6"]
    elif subtotal >= THRESHOLDS["discount_band_3_min_cents"]:
        discount_pct = THRESHOLDS["discount_pct_band_3"]
    else:
        discount_pct = THRESHOLDS["discount_pct_band_0"]
    discount = round_cents(Decimal(discount_pct) * Decimal(subtotal) / Decimal(100))
    return {
        "leverage_pct": leverage_pct,
        "effective_word_count": effective_words,
        "base_cost_cents": base_cost,
        "window_length_days": window_len,
        "rush_surcharge_cents": surcharge,
        "subtotal_cents": subtotal,
        "volume_discount_pct": discount_pct,
        "volume_discount_cents": discount,
        "cost_cents": subtotal - discount,
    }


def expected_provisional_memory_words(reserved_source_words: int, tm_coverage_pct: float) -> int:
    """The provisional variant's memory volume (§3.8)."""
    return floor_int(Decimal(reserved_source_words) * Decimal(str(tm_coverage_pct)) / Decimal(100))


def expected_impact_score(
    severities: Sequence[str], documented_count: int
) -> dict[str, Any]:
    """The six-step customer-impact score of §3.7."""
    included = len(severities)
    raw = sum(THRESHOLDS["severity_weights"][s] for s in severities)
    coverage = (
        round_half_up(Decimal(documented_count) / Decimal(included), 2) if included else 0.00
    )
    score = round_half_up(Decimal(raw) * (Decimal(2) - Decimal(str(coverage))), 2)
    return {
        "raw_impact": raw,
        "coverage_factor": coverage,
        "impact_score": min(score, float(THRESHOLDS["impact_score_cap"])),
        "headline_severity": next(
            (s for s in SEVERITY_RANK_ORDER if s in set(severities)), None
        ),
        "severity_counts": {s: list(severities).count(s) for s in SEVERITY_RANK_ORDER},
    }


def expected_notice_days(announce_date: str, removal_date: str) -> int:
    """Whole days from ``announce_date`` to ``removal_date`` (§3.9)."""
    return (parse_date(removal_date) - parse_date(announce_date)).days


def expected_earliest_removal_date(announce_date: str, severity_tier: str) -> str:
    """``announce_date`` plus the tier's minimum notice period (§3.9)."""
    return shift_date(announce_date, THRESHOLDS["min_notice_days"][severity_tier])


def expected_health_score(
    current_revision_number: int,
    open_blocker_violations: int,
    open_warning_violations: int,
    signoff_latency_days: Optional[int],
    variant: str = "PRE_PUBLICATION",
    sample_count: int = 0,
    mean_rating: Optional[float] = None,
    deflection_pct: Optional[float] = None,
) -> float:
    """The seven-step documentation health score of §3.10."""
    churn = THRESHOLDS["churn_penalty_per_revision"] * max(
        0, current_revision_number - THRESHOLDS["churn_penalty_free_revisions"]
    )
    blocker = THRESHOLDS["blocker_penalty_per_violation"] * open_blocker_violations
    warning = THRESHOLDS["warning_penalty_per_violation"] * open_warning_violations
    if signoff_latency_days is None:
        latency = 0
    else:
        latency = THRESHOLDS["latency_penalty_per_day"] * max(
            0, signoff_latency_days - THRESHOLDS["latency_penalty_grace_days"]
        )
    score = Decimal(100) - Decimal(churn) - Decimal(blocker) - Decimal(warning) - Decimal(latency)

    if variant == "POST_PUBLICATION":
        if sample_count > 0 and mean_rating is not None:
            rating_penalty = round_half_up(
                Decimal(THRESHOLDS["rating_penalty_per_point"])
                * (Decimal(THRESHOLDS["rating_penalty_reference"]) - Decimal(str(mean_rating))),
                2,
            )
            score -= Decimal(str(rating_penalty))
        if deflection_pct is not None:
            deflection_penalty = round_half_up(
                Decimal(str(THRESHOLDS["deflection_penalty_per_pct"]))
                * (Decimal(THRESHOLDS["deflection_penalty_reference"]) - Decimal(str(deflection_pct))),
                2,
            )
            score -= Decimal(str(deflection_penalty))

    return round_half_up(max(score, Decimal(0)), 2)


def expected_deflection_window(clock_date: str) -> tuple[str, str]:
    """The trailing 30-day window, both ends inclusive (§3.10)."""
    return shift_date(clock_date, -THRESHOLDS["deflection_window_days"]), clock_date


def expected_mean_rating(ratings: Sequence[int]) -> Optional[float]:
    if not ratings:
        return None
    return round_half_up(Decimal(sum(ratings)) / Decimal(len(ratings)), 2)


def expected_pct(numerator: int, denominator: int) -> Optional[float]:
    if denominator == 0:
        return None
    return round_half_up(Decimal(numerator) * Decimal(100) / Decimal(denominator), 2)


# ---------------------------------------------------------------------------
# Ledger and cascade assertions (§2.8)
# ---------------------------------------------------------------------------


def assert_committed_load_points(writer: dict[str, Any], expected: float) -> None:
    """§3.2's conserved writer ledger."""
    assert float(writer["committed_load_points"]) == expected, (
        f"expected committed_load_points {expected}, got {writer['committed_load_points']}"
    )


def assert_committed_source_words(locale: dict[str, Any], expected: int) -> None:
    """§3.8's conserved locale word ledger."""
    assert locale["committed_source_words"] == expected, (
        f"expected committed_source_words {expected}, got {locale['committed_source_words']}"
    )


def assert_localization_committed_cents(train: dict[str, Any], expected: int) -> None:
    """§3.8's conserved train spend ledger."""
    assert train["localization_committed_cents"] == expected, (
        f"expected localization_committed_cents {expected}, "
        f"got {train['localization_committed_cents']}"
    )


def assert_version_bumped_by(before: dict[str, Any], after: dict[str, Any], delta: int) -> None:
    """A cascade-touched record's ``version`` rises by exactly ``delta`` (§2.8)."""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version'] + delta}, got {after['version']}"
    )


def assert_updated_at_refreshed(before: dict[str, Any], after: dict[str, Any]) -> None:
    """A cascade-touched record's ``updated_at`` moves forward (§2.8)."""
    assert canonical_instant(after["updated_at"]) >= canonical_instant(before["updated_at"]), (
        f"updated_at went backwards: {before['updated_at']} -> {after['updated_at']}"
    )


_NOT_EXPORTED = {
    "annotations", "date", "datetime", "timedelta", "ROUND_HALF_UP", "Decimal",
    "Any", "Optional", "Sequence", "requests",
    "LOCALIZATION_JOB_OPEN_STATES", "SEVERITY_RANK_ORDER",
    "WRITER_COUNTED_PLAN_ITEM_STATUSES", "THRESHOLDS",
}

__all__ = [
    name for name in dir()
    if not name.startswith("_") and name not in _NOT_EXPORTED
]
