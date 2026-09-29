"""Entity assertions and domain invariant checkers for the Dog Show Trials API."""

from typing import Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_timestamp, timestamps_equal


# ─── Shared shape helpers ─────────────────────────────────────────────────────

def assert_identity_fields(data: dict) -> None:
    """Every resource carries a UUID `id` and an ISO 8601 UTC `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC instant: {data.get('created_at')!r}"
    )


def assert_versioned_fields(data: dict) -> None:
    """Resources other than a performance run also carry `updated_at` + `version`."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC instant: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "") -> None:
    """Compare two instants, tolerating sub-second width but not a different instant."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert timestamps_equal(actual, expected), (
        f"{label}: expected {canonical_timestamp(expected)}, got {canonical_timestamp(actual)}"
    )


def assert_three_fractional_digits(value: str, label: str = "timestamp") -> None:
    """The PRD formats every instant with exactly three fractional digits."""
    assert isinstance(value, str) and value.endswith("Z"), (
        f"{label} must be a UTC instant ending in Z: {value!r}"
    )
    assert "." in value and len(value.split(".")[-1]) == 4, (
        f"{label} must carry exactly three fractional digits: {value!r}"
    )


def assert_one_decimal_place(value: float, label: str = "value") -> None:
    """Heights, heat indices and run scores carry exactly one decimal place."""
    assert value == pytest.approx(round(float(value), 1), abs=1e-9), (
        f"{label} must carry at most one decimal place: {value!r}"
    )


def assert_cents(value, label: str = "amount") -> None:
    """Money is a whole number of cents in an integer field — never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {type(value).__name__}: {value!r}"
    )


# ─── Entity assertions ────────────────────────────────────────────────────────

def assert_club(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["club_code"], str) and 3 <= len(data["club_code"]) <= 8
    assert data["club_code"].isalnum() and data["club_code"].isupper()
    assert data["region_code"] in ["NE", "SE", "MW", "WC"]
    assert data["sanction_status"] in ["ACTIVE", "PROBATION", "SUSPENDED"]
    assert isinstance(data["annual_event_allowance"], int)
    assert data["annual_event_allowance"] >= 0
    assert isinstance(data["events_approved_count"], int)
    assert data["events_approved_count"] >= 0


def assert_show(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "RETURNED", "APPROVED",
        "IN_PROGRESS", "COMPLETED", "RESULTS_FILED",
    ]
    assert data["show_type"] in ["CONFORMATION", "PERFORMANCE", "COMBINED"]
    assert data["championship_points_scale"] in ["SCALE_A", "SCALE_B"]
    assert isinstance(data["outdoor_venue"], bool)
    for field in (
        "fee_charged_cents", "fee_refunded_cents", "fee_retained_cents",
        "fee_collected_cents", "levy_total_cents", "fee_assessment_delta_cents",
    ):
        assert_cents(data[field], field)
    for field in (
        "revision_count", "armband_high_water", "points_awarded_total",
        "temperature_reading_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must not be negative"
    assert data["current_advisory_level"] in [None, "GREEN", "AMBER", "RED"]
    if data["current_heat_index_c"] is not None:
        assert_one_decimal_place(data["current_heat_index_c"], "current_heat_index_c")


def assert_show_ledger_conserved(show: dict, entries: list) -> None:
    """`fee_collected_cents` is the conserved quantity of the show ledger."""
    assert show["fee_collected_cents"] == show["fee_charged_cents"] - show["fee_refunded_cents"], (
        "fee_collected_cents must equal fee_charged_cents less fee_refunded_cents"
    )
    net_sum = sum(e["net_fee_cents"] for e in entries)
    assert show["fee_collected_cents"] == net_sum, (
        f"fee_collected_cents {show['fee_collected_cents']} must equal the sum of "
        f"net_fee_cents across the show's entries ({net_sum})"
    )
    charged_sum = sum(e["entry_fee_cents"] for e in entries)
    assert show["fee_charged_cents"] == charged_sum, (
        f"fee_charged_cents {show['fee_charged_cents']} must equal the sum of "
        f"entry_fee_cents across the show's entries ({charged_sum})"
    )
    levy_sum = sum(e["levy_cents"] for e in entries)
    assert show["levy_total_cents"] == levy_sum, (
        f"levy_total_cents {show['levy_total_cents']} must equal the sum of the "
        f"per-entry levy_cents values ({levy_sum})"
    )


def assert_judge(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["judge_number"], str) and data["judge_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["home_region_code"] in ["NE", "SE", "MW", "WC"]
    assert isinstance(data["approved_breed_group_codes"], list)
    assert isinstance(data["approved_performance_disciplines"], list)
    assert isinstance(data["max_daily_dog_count"], int) and data["max_daily_dog_count"] >= 1
    assert data["status"] in ["ACTIVE", "PROVISIONAL", "SUSPENDED"]
    assert isinstance(data["confirmed_slot_count"], int)
    assert data["confirmed_slot_count"] >= 0


def assert_panel_slot(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["panel_role"] in [
        "BREED_JUDGE", "GROUP_JUDGE", "BIS_JUDGE", "PERFORMANCE_JUDGE",
    ]
    assert data["slot_status"] in ["PROPOSED", "CONFIRMED", "DECLINED"]
    assert isinstance(data["assigned_class_count"], int)
    assert data["assigned_class_count"] >= 0
    assert isinstance(data["assigned_dog_capacity"], int)
    assert data["assigned_dog_capacity"] >= 0


def assert_show_class(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["class_level"] in ["BREED", "GROUP", "BEST_IN_SHOW", "PERFORMANCE"]
    assert data["status"] in ["OPEN", "CLOSED", "SCHEDULED", "COMPLETED", "ABANDONED"]
    for field in ("entry_count", "present_count", "counted_dog_count", "base_points"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must not be negative"
    assert isinstance(data["final_assessment_done"], bool)
    assert isinstance(data["entry_limit"], int) and data["entry_limit"] >= 1
    assert data["base_points"] <= 5, "base_points is capped at 5"
    if data["points_scale_override"] is not None:
        assert data["points_scale_override"] in ["SCALE_A", "SCALE_B"]


def assert_handler(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["handler_name"], str) and data["handler_name"]
    assert isinstance(data["member_number"], str) and data["member_number"]
    assert data["region_code"] in ["NE", "SE", "MW", "WC"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_dog(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["registration_number"], str) and data["registration_number"]
    assert isinstance(data["call_name"], str) and data["call_name"]
    assert data["sex"] in ["DOG", "BITCH"]
    assert data["measurement_status"] in ["UNMEASURED", "TEMP_CARD", "PERMANENT_CARD"]
    assert isinstance(data["championship_points_total"], int)
    assert data["championship_points_total"] >= 0
    assert isinstance(data["majors_count"], int) and data["majors_count"] >= 0
    assert isinstance(data["qualifying_leg_counts"], dict)
    for discipline in ("AGILITY", "OBEDIENCE", "RALLY"):
        assert discipline in data["qualifying_leg_counts"], (
            f"qualifying_leg_counts must hold a count for {discipline}"
        )
    assert isinstance(data["title_codes"], list)
    for code in data["title_codes"]:
        assert code in ["CH", "AX", "CD", "RN"]
    if data["measured_height_cm"] is not None:
        assert_one_decimal_place(data["measured_height_cm"], "measured_height_cm")


def assert_entry(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["entry_status"] in [
        "RECEIVED", "CONFIRMED", "CHECKED_IN", "JUDGED",
        "ABSENT", "WITHDRAWN", "DISQUALIFIED",
    ]
    assert data["welfare_status"] in ["CLEAR", "SEASON_DECLARED", "HEAT_HOLD"]
    assert data["source"] in ["HANDLER_SUBMITTED", "PROMOTION"]
    for field in ("entry_fee_cents", "levy_cents", "fee_refunded_cents", "net_fee_cents"):
        assert_cents(data[field], field)
    assert data["net_fee_cents"] == data["entry_fee_cents"] - data["fee_refunded_cents"], (
        "net_fee_cents must equal entry_fee_cents less fee_refunded_cents"
    )
    assert isinstance(data["points_awarded"], int) and data["points_awarded"] >= 0
    assert isinstance(data["conflict_deferred"], bool)
    if data["placement"] is not None:
        assert 1 <= data["placement"] <= 4, "placement is between 1 and 4 inclusive"
    if data["armband_number"] is not None:
        assert isinstance(data["armband_number"], int) and data["armband_number"] >= 1
    if data["fee_basis"] is not None:
        assert data["fee_basis"] in ["PROVISIONAL", "FINAL"]


def assert_ring_block(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["block_status"] in ["PLANNED", "PUBLISHED", "SUPERSEDED", "COMPLETED"]
    assert isinstance(data["ring_number"], int) and 1 <= data["ring_number"] <= 12
    for field in (
        "scheduled_dog_count", "deferred_dog_count",
        "conflict_free_minutes", "judging_minutes_estimate",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must not be negative"
    assert data["judging_minutes_estimate"] >= data["conflict_free_minutes"], (
        "judging_minutes_estimate is the conflict-free span plus deferral time"
    )
    assert is_iso8601_timestamp(data["block_start_at"])
    assert is_iso8601_timestamp(data["block_end_at"])


def assert_protest(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "UPHELD", "DISMISSED",
    ]
    assert data["protest_type"] in [
        "MEASUREMENT", "ELIGIBILITY", "JUDGING_CONDUCT", "WELFARE",
    ]
    assert_cents(data["deposit_cents"], "deposit_cents")
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert isinstance(data["deposit_refunded"], bool)
    if data["resolution_code"] is not None:
        assert data["resolution_code"] in [
            "DISQUALIFY_ENTRY", "VACATE_PLACEMENT", "NO_ACTION", "WARNING",
        ]


def assert_registry_filing(data: dict) -> None:
    assert_versioned_fields(data)
    assert data["filing_status"] in ["PENDING", "ACCEPTED", "REJECTED_INCOMPLETE"]
    assert is_iso8601_timestamp(data["filed_at"])
    for field in (
        "championship_points_total_filed", "title_records_count", "amendment_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must not be negative"


def assert_performance_run(data: dict) -> None:
    """A run is append-only: only `id` and `created_at`, no `updated_at`, no `version`."""
    assert_identity_fields(data)
    assert "updated_at" not in data, (
        "a performance run has no updated_at field at all"
    )
    assert "version" not in data, (
        "a performance run has no version field at all"
    )
    assert data["discipline"] in ["AGILITY", "OBEDIENCE", "RALLY"]
    assert data["run_result"] in ["QUALIFIED", "NQ", "ELIMINATED"]
    assert isinstance(data["title_leg_awarded"], bool)
    assert data["title_leg_awarded"] is (data["run_result"] == "QUALIFIED"), (
        "title_leg_awarded is true exactly when the run_result is QUALIFIED"
    )
    for field in ("time_faults", "total_faults", "final_score"):
        assert_one_decimal_place(float(data[field]), field)
    assert float(data["final_score"]) >= 0.0


# ─── Response-shape helpers ───────────────────────────────────────────────────

def assert_request_id_prefix(body: dict) -> None:
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {body['meta']['api_request_id']!r}"
    )


def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int) -> None:
    assert meta["limit"] == limit, f"meta.limit should be {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"meta.offset should be {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"meta.total_count should be {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is (offset + limit < total_count), (
        "has_more is true exactly when rows remain beyond the returned window"
    )


def ids_of(rows: list) -> list:
    return [row["id"] for row in rows]
