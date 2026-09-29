"""Entity assertions and domain invariant checkers for the maintenance API."""

from typing import Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonicalise_instant
from .constants import (
    BULLETIN_SEVERITIES,
    CAUSE_CATEGORIES,
    COMPONENT_TYPES,
    CRITICALITIES,
    INJURY_SEVERITIES,
    OPERATIONAL_POSTURES,
    PARK_AREAS,
    RIDE_CLASSES,
    SEVERITY_CLASSES,
)

_DATE_LENGTH = len("YYYY-MM-DD")


# --- Shared shape helpers ---------------------------------------------------
def assert_identity_fields(data: dict, *, versioned: bool = True) -> None:
    """PRD §2.5 identity block: `id` + `created_at`, plus `updated_at`/`version`
    on every row except a checklist line."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')}"
    assert "_" not in str(data.get("id", "")), "id must carry no type prefix"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')}"
    if versioned:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601: {data.get('updated_at')}"
        assert isinstance(data.get("version"), int), "version must be an integer"
        assert data["version"] >= 1, "version starts at 1"


def assert_is_date(value: str, field: str = "date") -> None:
    assert isinstance(value, str) and len(value) == _DATE_LENGTH, (
        f"{field} must be a plain YYYY-MM-DD calendar date, got {value!r}"
    )
    assert value[4] == "-" and value[7] == "-", f"{field} must be YYYY-MM-DD"


def assert_instant_equals(actual: Optional[str], expected: Optional[str],
                          field: str = "instant") -> None:
    """Compare two UTC instants by value, ignoring fractional-digit width."""
    if expected is None:
        assert actual is None, f"{field} should be null, got {actual!r}"
        return
    assert actual is not None, f"{field} should be {expected!r}, got null"
    assert canonicalise_instant(actual) == canonicalise_instant(expected), (
        f"{field} should be {expected!r}, got {actual!r}"
    )


def assert_two_decimal_value(value, field: str = "value") -> None:
    """PRD §2.10: capacity and score figures carry exactly 2 decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{field} must carry at most 2 decimal places, got {value!r}"
    )


def assert_whole_cents(value, field: str = "cents") -> None:
    """PRD §2.10: "Money is whole cents throughout"."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of whole cents, got {value!r}"
    )


# --- Attraction -------------------------------------------------------------
def assert_attraction(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["park_area"] in PARK_AREAS
    assert isinstance(data["manufacturer"], str) and data["manufacturer"]
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["ride_class"] in RIDE_CLASSES
    assert isinstance(data["theoretical_hourly_capacity"], int)
    assert data["theoretical_hourly_capacity"] >= 1
    assert isinstance(data["min_operators_required"], int)
    assert data["min_operators_required"] >= 1
    assert_whole_cents(data["parts_budget_cents"], "parts_budget_cents")
    assert isinstance(data["mean_repair_minutes"], int)
    assert data["mean_repair_minutes"] >= 1
    assert data["operational_posture"] in OPERATIONAL_POSTURES
    assert isinstance(data["cumulative_cycles"], int) and data["cumulative_cycles"] >= 0
    assert_whole_cents(
        data["parts_budget_committed_cents"], "parts_budget_committed_cents"
    )
    assert isinstance(data["ytd_downtime_minutes"], int)
    assert isinstance(data["certified_operator_count"], int)
    assert isinstance(data["regulatory_hold"], bool)
    if data["active_template_id"] is not None:
        assert is_valid_uuid(data["active_template_id"])
    if data["last_signed_off_service_date"] is not None:
        assert_is_date(
            data["last_signed_off_service_date"], "last_signed_off_service_date"
        )


def assert_fresh_attraction_baseline(data: dict) -> None:
    """PRD §3.1: "`operational_posture` initialises to `CLOSED_PENDING_INSPECTION`;
    `cumulative_cycles`, `parts_budget_committed_cents`, `ytd_downtime_minutes` and
    `certified_operator_count` all initialise to 0; `regulatory_hold` initialises to
    false; and `active_template_id` and `last_signed_off_service_date` both begin as
    null."
    """
    assert data["operational_posture"] == "CLOSED_PENDING_INSPECTION"
    assert data["cumulative_cycles"] == 0
    assert data["parts_budget_committed_cents"] == 0
    assert data["ytd_downtime_minutes"] == 0
    assert data["certified_operator_count"] == 0
    assert data["regulatory_hold"] is False
    assert data["active_template_id"] is None
    assert data["last_signed_off_service_date"] is None
    assert data["version"] == 1


# --- Component --------------------------------------------------------------
def assert_component(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["attraction_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["component_type"] in COMPONENT_TYPES
    assert data["criticality"] in CRITICALITIES
    assert isinstance(data["ndt_interval_cycles"], int)
    assert data["ndt_interval_cycles"] >= 1
    assert isinstance(data["ndt_interval_days"], int)
    assert data["ndt_interval_days"] >= 1
    assert data["ndt_status"] in ("CURRENT", "DUE", "OVERDUE")
    assert data["condition_flag"] in ("OK", "SUSPECT", "FAILED")
    assert isinstance(data["last_ndt_cycles"], int)


def assert_component_install_baseline(data: dict, clock_instant: str,
                                      cumulative_cycles: int = 0) -> None:
    """PRD §3.1: "`last_ndt_at` is set to the current logical clock instant,
    `last_ndt_cycles` is set to the attraction's `cumulative_cycles` as observed at
    that moment, `ndt_status` starts at `CURRENT`, `condition_flag` starts at `OK`,
    and `last_ndt_method` starts as null because no test has been run yet."
    """
    assert_instant_equals(data["last_ndt_at"], clock_instant, "last_ndt_at")
    assert data["last_ndt_cycles"] == cumulative_cycles
    assert data["ndt_status"] == "CURRENT"
    assert data["condition_flag"] == "OK"
    assert data["last_ndt_method"] is None


# --- Inspection template and checklist line ---------------------------------
def assert_inspection_template(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["attraction_id"])
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert_is_date(data["effective_from_date"], "effective_from_date")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0


def assert_checklist_item(data: dict) -> None:
    """PRD §2.5: a checklist line "carries only `id` and `created_at`. It has no
    `updated_at`, no `version`, and no update endpoint."
    """
    assert_identity_fields(data, versioned=False)
    assert "updated_at" not in data, "a checklist line has no updated_at"
    assert "version" not in data, "a checklist line has no version"
    assert is_valid_uuid(data["template_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["description"], str) and data["description"]
    assert data["severity_class"] in SEVERITY_CLASSES
    assert isinstance(data["requires_photo"], bool)


# --- Daily inspection and item result ---------------------------------------
def assert_daily_inspection(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["attraction_id"])
    assert_is_date(data["service_date"], "service_date")
    assert is_valid_uuid(data["template_id"])
    assert isinstance(data["template_revision"], int)
    assert data["status"] in (
        "IN_PROGRESS",
        "BLOCKED",
        "PENDING_SIGN_OFF",
        "REJECTED",
        "SIGNED_OFF",
    )
    for counter in (
        "pending_item_count",
        "blocking_item_count",
        "essential_fail_count",
        "rework_round",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, counter
    assert isinstance(data["recorded_by_user_ids"], list)
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_inspection_counters(
    data: dict,
    *,
    pending: Optional[int] = None,
    blocking: Optional[int] = None,
    essential_fail: Optional[int] = None,
    status: Optional[str] = None,
    rework_round: Optional[int] = None,
) -> None:
    """Assert the three PRD-declared inspection counters (and optionally status)."""
    if pending is not None:
        assert data["pending_item_count"] == pending, (
            f"pending_item_count should be {pending}, got {data['pending_item_count']}"
        )
    if blocking is not None:
        assert data["blocking_item_count"] == blocking, (
            f"blocking_item_count should be {blocking}, "
            f"got {data['blocking_item_count']}"
        )
    if essential_fail is not None:
        assert data["essential_fail_count"] == essential_fail, (
            f"essential_fail_count should be {essential_fail}, "
            f"got {data['essential_fail_count']}"
        )
    if status is not None:
        assert data["status"] == status, (
            f"inspection status should be {status}, got {data['status']}"
        )
    if rework_round is not None:
        assert data["rework_round"] == rework_round, (
            f"rework_round should be {rework_round}, got {data['rework_round']}"
        )


def assert_item_result(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["inspection_id"])
    assert is_valid_uuid(data["checklist_item_id"])
    assert data["severity_class"] in SEVERITY_CLASSES
    assert data["outcome"] in ("PENDING", "PASS", "FAIL", "NA")
    if data["outcome"] == "PENDING":
        assert data["recorded_by_user_id"] is None, (
            "a PENDING result row carries a null recorded_by_user_id"
        )
        assert data["recorded_at"] is None, (
            "a PENDING result row carries a null recorded_at"
        )


# --- Bulletins and fleet actions --------------------------------------------
def assert_bulletin(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["bulletin_ref"], str) and data["bulletin_ref"]
    assert data["severity"] in BULLETIN_SEVERITIES
    assert_is_date(data["issued_date"], "issued_date")
    assert_is_date(data["compliance_deadline_date"], "compliance_deadline_date")
    assert data["status"] in ("ISSUED", "ACKNOWLEDGED", "COMPLETED", "SUPERSEDED")
    assert isinstance(data["action_total_count"], int)
    assert isinstance(data["action_verified_count"], int)


def assert_bulletin_action(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["bulletin_id"])
    assert is_valid_uuid(data["attraction_id"])
    assert data["status"] in (
        "PENDING",
        "IN_WORK",
        "VERIFIED",
        "DEFERRED",
        "CANCELLED",
    )
    assert isinstance(data["required_part_received"], bool)


def assert_bulletin_risk_shape(data: dict) -> None:
    """PRD §3.6: "The response reports the `bulletin_id`, an
    `evaluated_action_count` giving the size of that set, a `deferred_action_count`,
    the `escalation_factor`, and the three score figures `fleet_aggregate_score`,
    `per_unit_max_score` and `divergence`."
    """
    assert is_valid_uuid(data["bulletin_id"])
    assert isinstance(data["evaluated_action_count"], int)
    assert isinstance(data["deferred_action_count"], int)
    for field in (
        "escalation_factor",
        "fleet_aggregate_score",
        "per_unit_max_score",
        "divergence",
    ):
        assert_two_decimal_value(data[field], field)


# --- Downtime ---------------------------------------------------------------
def assert_downtime_event(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["attraction_id"])
    assert_is_date(data["service_date"], "service_date")
    assert is_iso8601_timestamp(data["started_at"])
    assert data["cause_category"] in CAUSE_CATEGORIES
    assert data["status"] in (
        "OPEN",
        "DIAGNOSED",
        "AWAITING_PARTS",
        "RESOLVED",
        "CLOSED",
        "VOIDED",
    )
    assert isinstance(data["auto_opened"], bool)


def assert_capacity_impact_shape(data: dict) -> None:
    """PRD §3.4: "The response echoes the `attraction_id`, the `window_start_date`
    and `window_end_date` actually used, an `event_count`, and three figures:
    `settled_guest_slots_lost`, `provisional_guest_slots_lost` and
    `divergence_guest_slots`."
    """
    assert is_valid_uuid(data["attraction_id"])
    assert_is_date(data["window_start_date"], "window_start_date")
    assert_is_date(data["window_end_date"], "window_end_date")
    assert isinstance(data["event_count"], int)
    for field in (
        "settled_guest_slots_lost",
        "provisional_guest_slots_lost",
        "divergence_guest_slots",
    ):
        assert_two_decimal_value(data[field], field)


# --- Part requisitions ------------------------------------------------------
def assert_part_requisition(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["attraction_id"])
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert_whole_cents(data["unit_cost_cents"], "unit_cost_cents")
    assert_whole_cents(data["total_cost_cents"], "total_cost_cents")
    assert data["total_cost_cents"] == data["quantity"] * data["unit_cost_cents"], (
        "total_cost_cents is the quantity multiplied by the unit_cost_cents"
    )
    assert_is_date(data["needed_by_date"], "needed_by_date")
    assert data["status"] in (
        "REQUESTED",
        "RESERVED",
        "BACKORDERED",
        "RECEIVED",
        "CANCELLED",
    )


# --- Certifications ---------------------------------------------------------
def assert_operator_certification(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["attraction_id"])
    assert isinstance(data["operator_user_id"], str) and data["operator_user_id"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert 0 <= data["restraint_verification_score"] <= 100
    assert 0 <= data["dispatch_procedure_score"] <= 100
    assert data["status"] in ("TRAINEE", "CERTIFIED", "SUSPENDED", "EXPIRED")


def assert_dispatch_readiness_shape(data: dict) -> None:
    """PRD §3.7: "The response reports the `attraction_id`, the attraction's current
    `operational_posture`, its `certified_operator_count`, a `mean_restraint_score`,
    an `essential_fail_count`, and the `dispatch_readiness_index` itself."
    """
    assert is_valid_uuid(data["attraction_id"])
    assert data["operational_posture"] in OPERATIONAL_POSTURES
    assert isinstance(data["certified_operator_count"], int)
    assert isinstance(data["essential_fail_count"], int)
    assert_two_decimal_value(data["mean_restraint_score"], "mean_restraint_score")
    assert_two_decimal_value(
        data["dispatch_readiness_index"], "dispatch_readiness_index"
    )
    assert data["dispatch_readiness_index"] >= 0.0, (
        "the index is floored at 0.00 so it is never negative"
    )


# --- Incidents --------------------------------------------------------------
def assert_incident(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["attraction_id"])
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["injury_severity"] in INJURY_SEVERITIES
    assert isinstance(data["guest_count_affected"], int)
    assert data["guest_count_affected"] >= 0
    assert isinstance(data["narrative"], str) and data["narrative"]
    assert data["status"] in (
        "REPORTED",
        "RIDE_HELD",
        "UNDER_INVESTIGATION",
        "REGULATOR_NOTIFIED",
        "INTERNAL_REVIEW_CLOSED",
        "CLEARED_TO_OPERATE",
    )
    assert isinstance(data["notified_late"], bool)
    assert isinstance(data["suspended_certification_count"], int)


# --- Shop bays and overhaul work orders -------------------------------------
def assert_shop_bay(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["concurrent_slot_capacity"], int)
    assert data["concurrent_slot_capacity"] >= 1
    assert isinstance(data["booked_order_count"], int)
    assert data["booked_order_count"] >= 0


def assert_work_order(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["attraction_id"])
    assert is_valid_uuid(data["component_id"])
    assert is_valid_uuid(data["shop_bay_id"])
    assert_is_date(data["window_start_date"], "window_start_date")
    assert_is_date(data["window_end_date"], "window_end_date")
    assert data["window_end_date"] >= data["window_start_date"]
    assert data["status"] in (
        "SCHEDULED",
        "TEARDOWN",
        "INSPECTION",
        "REBUILD",
        "RECOMMISSIONED",
    )
    assert isinstance(data["expedite_requested"], bool)
    assert isinstance(data["off_season"], bool)
    for field in (
        "parts_subtotal_cents",
        "base_total_cents",
        "off_season_discount_cents",
        "discounted_base_cents",
        "expedite_fee_cents",
        "estimated_total_cents",
    ):
        assert_whole_cents(data[field], field)


def assert_work_order_cost_chain(data: dict) -> None:
    """PRD §3.9: "`discounted_base_cents` is `base_total_cents` less
    `off_season_discount_cents`." and "`estimated_total_cents` is
    `discounted_base_cents` plus `expedite_fee_cents`."
    """
    assert (
        data["discounted_base_cents"]
        == data["base_total_cents"] - data["off_season_discount_cents"]
    )
    assert (
        data["estimated_total_cents"]
        == data["discounted_base_cents"] + data["expedite_fee_cents"]
    )


# --- Envelope helpers -------------------------------------------------------
def assert_error_envelope(response) -> None:
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    """
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert body["meta"]["api_request_id"].startswith("req_")


def assert_object_envelope(response) -> None:
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    """
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
