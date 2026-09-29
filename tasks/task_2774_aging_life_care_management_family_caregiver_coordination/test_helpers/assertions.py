"""Entity assertions, timestamp canonicalisation and domain invariant checkers."""
import re
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import DOMAIN_KEYS

_MILLIS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ------------------------------------------------- timestamp canonicalisation -
def canonical_timestamp(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to whole-second `...THH:MM:SSZ` form.

    Fractional-second width differs harmlessly between a written instant
    (`2026-08-02T09:00:00Z`) and the same instant read back with the three
    fractional digits the PRD renders (`2026-08-02T09:00:00.000Z`). Comparisons
    go through this normaliser so they test the instant, not its formatting.
    """
    assert isinstance(value, str), f"Expected a timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[: 10 + text[10:].index("+")]
    if "." in text:
        text = text[: text.index(".")]
    return f"{text}Z"


def assert_timestamps_equal(actual: str, expected: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 UTC instants name the same second."""
    assert canonical_timestamp(actual) == canonical_timestamp(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_millisecond_timestamp(value: str, label: str = "timestamp") -> None:
    """Assert an ISO 8601 UTC timestamp rendered with exactly three fractional
    digits, the form the PRD pins for `created_at` and `updated_at`."""
    assert isinstance(value, str) and _MILLIS_RE.match(value), (
        f"{label} must be an ISO 8601 UTC timestamp with exactly three "
        f"fractional-second digits, got {value!r}"
    )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Assert the response envelope's `meta` carries a `req_`-prefixed request id
    and a millisecond-precision UTC timestamp."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id must be a string"
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_millisecond_timestamp(
        meta.get("api_request_timestamp", ""), "meta.api_request_timestamp"
    )


# ------------------------------------------------------- housekeeping fields --
def assert_common_fields(data: Dict[str, Any], label: str = "record") -> None:
    """Every record carries a prefix-free UUID `id`, millisecond `created_at`
    and `updated_at`, and an integer `version` that begins at 1."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID carrying no type prefix, got {data.get('id')!r}"
    )
    assert_millisecond_timestamp(data.get("created_at", ""), f"{label}.created_at")
    assert_millisecond_timestamp(data.get("updated_at", ""), f"{label}.updated_at")
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version begins at 1, got {data['version']}"


def assert_nullable_timestamp(
    value: Optional[str], label: str = "timestamp"
) -> None:
    if value is not None:
        assert is_iso8601_timestamp(value), f"{label} must be ISO 8601 UTC, got {value!r}"


# ------------------------------------------------------------- per-entity ----
def assert_client(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "client")
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert data["residence_setting"] in (
        "PRIVATE_HOME",
        "ASSISTED_LIVING",
        "SKILLED_NURSING",
        "HOSPITAL",
    )
    assert data["status"] in (
        "PROSPECT",
        "ASSESSMENT_IN_PROGRESS",
        "ACTIVE_CARE",
        "SUSPENDED_NONPAYMENT",
        "DISCHARGED",
    )
    assert data["capacity_status"] in (
        "PRESUMED_CAPABLE",
        "DIMINISHED_DOCUMENTED",
        "ADJUDICATED_INCAPACITATED",
    )
    assert data["risk_posture"] in ("ROUTINE", "ELEVATED", "CRISIS")
    assert isinstance(data["acuity_score"], int) and 0 <= data["acuity_score"] <= 100
    assert data["billing_increment_min"] in (6, 15)
    assert isinstance(data["travel_billing_pct"], int)
    assert 0 <= data["travel_billing_pct"] <= 100
    assert isinstance(data["retainer_floor_cents"], int)
    assert data["retainer_floor_cents"] >= 0
    assert isinstance(data["authorized_concurrent_caregivers"], int)
    assert data["authorized_concurrent_caregivers"] >= 1
    for money_field in (
        "retainer_deposits_total_cents",
        "retainer_balance_cents",
        "unbilled_accrual_cents",
    ):
        assert_integer_cents(data[money_field], f"client.{money_field}")
    assert isinstance(data["authorized_coverage_hours"], (int, float))
    assert data["protective_escalation_status"] in (
        "NONE",
        "PENDING",
        "ACCEPTED",
        "DECLINED",
    )
    if data["capacity_status"] == "PRESUMED_CAPABLE":
        assert data["capacity_basis"] is None, (
            "capacity_basis is null while capacity_status is PRESUMED_CAPABLE"
        )


def assert_care_manager(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "care_manager")
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert data["credential"] in ("CMC", "CCM", "CMAC", "C_ASWCM")
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["is_supervisor"], bool)
    assert isinstance(data["active"], bool)


def assert_vendor(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "vendor")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 160
    assert data["vendor_type"] in ("HOME_CARE", "MEDICAL", "LEGAL", "HOUSING")
    assert isinstance(data["has_referral_relationship"], bool)
    assert isinstance(data["referral_fee_pct"], (int, float))
    assert 0 <= data["referral_fee_pct"] <= 100
    assert data["standing"] in ("APPROVED", "PROBATION", "BARRED")
    if data["has_referral_relationship"]:
        assert data["referral_fee_pct"] > 0, (
            "a referral relationship requires referral_fee_pct greater than zero"
        )


def assert_family_contact(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "family_contact")
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert data["contact_role"] in (
        "POA_HEALTHCARE",
        "POA_FINANCIAL",
        "GUARDIAN",
        "RESPONSIBLE_PARTY",
        "INTERESTED_FAMILY",
    )
    assert isinstance(data["is_surrogate_decision_maker"], bool)
    assert isinstance(data["is_long_distance"], bool)
    assert isinstance(data["reporting_cadence_days"], int)
    assert 1 <= data["reporting_cadence_days"] <= 180
    assert_nullable_timestamp(data["last_report_sent_at"], "last_report_sent_at")
    assert isinstance(data["reports_sent_count"], int) and data["reports_sent_count"] >= 0
    assert data["report_status"] in ("NOT_APPLICABLE", "CURRENT", "DUE", "OVERDUE")
    assert isinstance(data["days_overdue"], int) and data["days_overdue"] >= 0


def assert_assessment(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "assessment")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["care_manager_id"])
    assert isinstance(data["domain_scores"], dict)
    assert sorted(data["domain_scores"].keys()) == sorted(DOMAIN_KEYS), (
        f"domain_scores must carry exactly the six declared keys, got "
        f"{sorted(data['domain_scores'].keys())}"
    )
    for key, value in data["domain_scores"].items():
        assert isinstance(value, int) and 0 <= value <= 5, (
            f"domain_scores.{key} must be an integer 0..5, got {value!r}"
        )
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "REVISION_REQUESTED",
        "ACCEPTED",
        "WITHDRAWN",
    )
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    for acuity_field in ("screening_acuity", "comprehensive_acuity"):
        value = data[acuity_field]
        if value is not None:
            assert isinstance(value, int) and 0 <= value <= 100, (
                f"{acuity_field} must be an integer 0..100, got {value!r}"
            )
    assert_nullable_timestamp(data["accepted_at"], "accepted_at")


def assert_care_plan(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "care_plan")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["source_assessment_id"])
    assert isinstance(data["goals"], list) and 1 <= len(data["goals"]) <= 12
    for goal in data["goals"]:
        assert isinstance(goal, str) and len(goal) > 0
    assert isinstance(data["review_interval_days"], int)
    assert 30 <= data["review_interval_days"] <= 365
    assert isinstance(data["pinned_assessment_version"], int)
    assert data["status"] in (
        "DRAFT",
        "PENDING_FAMILY_APPROVAL",
        "ACTIVE",
        "REJECTED",
        "SUPERSEDED",
        "WITHDRAWN",
    )
    assert isinstance(data["rejection_rounds"], int) and data["rejection_rounds"] >= 0
    assert isinstance(data["coverage_gap_flag"], bool)
    assert_nullable_timestamp(data["activated_at"], "activated_at")


def assert_service_authorization(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "service_authorization")
    assert is_valid_uuid(data["care_plan_id"])
    assert is_valid_uuid(data["vendor_id"])
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["concurrent_caregivers"], int)
    assert 1 <= data["concurrent_caregivers"] <= 10
    assert isinstance(data["hourly_cost_cents"], int) and data["hourly_cost_cents"] > 0
    assert isinstance(data["coverage_hours"], (int, float))
    for money_field in (
        "base_cost_cents",
        "coordination_fee_cents",
        "total_projected_cost_cents",
    ):
        assert_integer_cents(data[money_field], f"service_authorization.{money_field}")
    assert data["auth_status"] in (
        "PROPOSED",
        "AUTHORIZED",
        "ACTIVE",
        "SUSPENDED",
        "TERMINATED",
    )
    assert data["coi_status"] in (
        "NOT_REQUIRED",
        "PENDING_DISCLOSURE",
        "DISCLOSED",
        "ACKNOWLEDGED",
    )
    assert data["suspension_reason"] in (
        "NONE",
        "NONPAYMENT",
        "VENDOR_STANDING",
        "FAMILY_REQUEST",
    )
    assert data["termination_reason"] in (
        "NONE",
        "CARE_MANAGER_REQUEST",
        "DECISION_RESCINDED",
        "PLAN_SUPERSEDED",
        "VENDOR_STANDING",
        "CLIENT_DISCHARGED",
    )
    assert (
        data["total_projected_cost_cents"]
        == data["base_cost_cents"] + data["coordination_fee_cents"]
    ), "total_projected_cost_cents is base_cost_cents plus coordination_fee_cents"


def assert_family_conference(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "family_conference")
    assert is_valid_uuid(data["client_id"])
    assert isinstance(data["invited_contact_ids"], list)
    assert 1 <= len(data["invited_contact_ids"]) <= 12
    assert len(set(data["invited_contact_ids"])) == len(data["invited_contact_ids"])
    assert isinstance(data["attended_contact_ids"], list)
    assert set(data["attended_contact_ids"]).issubset(set(data["invited_contact_ids"])), (
        "attended_contact_ids must be a subset of invited_contact_ids"
    )
    assert data["status"] in (
        "SCHEDULED",
        "CONVENED",
        "DOCUMENTED",
        "RESCHEDULED",
        "CANCELLED",
    )
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert isinstance(data["quorum_met"], bool)
    assert isinstance(data["surrogate_present"], bool)
    assert_nullable_timestamp(data["convened_at"], "convened_at")


def assert_conference_decision(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "conference_decision")
    assert is_valid_uuid(data["family_conference_id"])
    assert is_valid_uuid(data["decided_by_contact_id"])
    assert data["decision_type"] in (
        "VENDOR_ENGAGEMENT",
        "PLACEMENT_CHANGE",
        "CARE_LEVEL_CHANGE",
        "ESCALATE_GUARDIANSHIP_PETITION",
        "ESCALATE_APS_REPORT",
    )
    assert isinstance(data["decision_text"], str)
    assert 1 <= len(data["decision_text"]) <= 2000
    assert data["status"] in (
        "RECORDED",
        "RATIFIED",
        "ESCALATED",
        "ESCALATION_ACCEPTED",
        "ESCALATION_DECLINED",
        "RESCINDED",
    )
    assert_nullable_timestamp(data["ratified_at"], "ratified_at")
    assert_nullable_timestamp(data["escalated_at"], "escalated_at")


def assert_crisis_episode(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "crisis_episode")
    assert is_valid_uuid(data["client_id"])
    assert data["trigger_type"] in (
        "HOSPITAL_ADMISSION",
        "FALL",
        "CAREGIVER_NO_SHOW",
        "ACUTE_BEHAVIORAL",
        "ELDER_ABUSE_SUSPICION",
    )
    assert_millisecond_timestamp(data["opened_at"], "crisis_episode.opened_at")
    assert_nullable_timestamp(data["stabilized_at"], "stabilized_at")
    assert_nullable_timestamp(data["discharge_at"], "discharge_at")
    assert_nullable_timestamp(data["closed_at"], "closed_at")
    assert data["status"] in ("OPEN", "STABILIZED", "TRANSITION_OVERSIGHT", "CLOSED")
    assert isinstance(data["readmission_count"], int)
    assert data["readmission_count"] >= 0


def assert_time_entry(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "time_entry")
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["care_manager_id"])
    assert data["service_type"] in (
        "ASSESSMENT",
        "CARE_COORDINATION",
        "CRISIS_RESPONSE",
        "TRAVEL",
        "CONFERENCE",
    )
    assert isinstance(data["service_location_id"], str)
    assert 1 <= len(data["service_location_id"]) <= 40
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["service_date"]), (
        f"service_date must be a YYYY-MM-DD calendar date, got {data['service_date']!r}"
    )
    assert isinstance(data["raw_minutes"], int) and data["raw_minutes"] >= 0
    assert isinstance(data["rounded_minutes"], int)
    assert data["rounded_minutes"] >= data["raw_minutes"], (
        "rounded_minutes rounds raw_minutes up to the client's billing increment"
    )
    assert isinstance(data["rate_multiplier"], (int, float))
    assert isinstance(data["after_hours_factor"], (int, float))
    assert_integer_cents(data["billable_amount_cents"], "time_entry.billable_amount_cents")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "REJECTED",
        "INVOICED",
        "VOIDED",
    )


def assert_invoice(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "invoice")
    assert is_valid_uuid(data["client_id"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["period_start"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", data["period_end"])
    assert data["period_end"] >= data["period_start"]
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["line_entry_ids"], list)
    for money_field in (
        "line_subtotal_cents",
        "admin_fee_cents",
        "total_due_cents",
        "retainer_applied_cents",
        "balance_due_cents",
        "amount_paid_cents",
    ):
        assert_integer_cents(data[money_field], f"invoice.{money_field}")
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOIDED")
    assert_nullable_timestamp(data["issued_at"], "issued_at")
    assert (
        data["total_due_cents"] == data["line_subtotal_cents"] + data["admin_fee_cents"]
    ), "total_due_cents is line_subtotal_cents plus admin_fee_cents"
    assert (
        data["balance_due_cents"]
        == data["total_due_cents"] - data["retainer_applied_cents"]
    ), "balance_due_cents is total_due_cents less retainer_applied_cents"


# ----------------------------------------------------- domain invariants ------
def assert_integer_cents(value: Any, label: str = "amount") -> None:
    """Assert a monetary amount is an integer number of cents — never a decimal
    string, never a fractional cent."""
    assert not isinstance(value, str), (
        f"{label} must be an integer number of cents, not a string, got {value!r}"
    )
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {type(value).__name__} {value!r}"
    )


def assert_retainer_money_conserved(client: Dict[str, Any], drawn_cents: int) -> None:
    """The client's remaining retainer balance plus the retainer drawn by ISSUED
    or PAID invoices always equals every deposit ever accepted."""
    assert (
        client["retainer_balance_cents"] + drawn_cents
        == client["retainer_deposits_total_cents"]
    ), (
        f"retainer not conserved: balance {client['retainer_balance_cents']} + drawn "
        f"{drawn_cents} != deposits {client['retainer_deposits_total_cents']}"
    )


def assert_coverage_hours(client: Dict[str, Any], expected_hours: float) -> None:
    assert client["authorized_coverage_hours"] == expected_hours, (
        f"expected authorized_coverage_hours {expected_hours}, got "
        f"{client['authorized_coverage_hours']}"
    )


def assert_version_advanced(new_version: int, old_version: int, label: str = "record") -> None:
    """Every mutation, including one suffered as a cascade, advances `version`."""
    assert new_version > old_version, (
        f"{label}.version must advance past {old_version}, got {new_version}"
    )


def assert_version_increment(
    new_version: int, old_version: int, expected_delta: int = 1, label: str = "record"
) -> None:
    assert new_version == old_version + expected_delta, (
        f"{label}.version expected {old_version + expected_delta}, got {new_version}"
    )


def assert_ascending_created_at(records: List[Dict[str, Any]]) -> None:
    stamps = [canonical_timestamp(r["created_at"]) for r in records]
    assert stamps == sorted(stamps), f"records must be oldest first, got {stamps}"


def assert_descending_created_at(records: List[Dict[str, Any]]) -> None:
    stamps = [canonical_timestamp(r["created_at"]) for r in records]
    assert stamps == sorted(stamps, reverse=True), (
        f"the client roster must be newest first, got {stamps}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_limit: int,
    expected_offset: int,
    expected_total: int,
    expected_has_more: bool,
) -> None:
    assert meta["limit"] == expected_limit, (
        f"meta.limit expected {expected_limit}, got {meta['limit']}"
    )
    assert meta["offset"] == expected_offset, (
        f"meta.offset expected {expected_offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == expected_total, (
        f"meta.total_count expected {expected_total}, got {meta['total_count']}"
    )
    assert meta["has_more"] is expected_has_more, (
        f"meta.has_more expected {expected_has_more}, got {meta['has_more']}"
    )


def screening_acuity(scores: Dict[str, int]) -> int:
    """The unweighted arithmetic mean of the six domains, scaled by 20."""
    total = sum(scores[key] for key in DOMAIN_KEYS)
    return _round_half_up(total / 6 * 20)


def comprehensive_acuity(scores: Dict[str, int]) -> int:
    """The priority-weighted sum of the six domains, scaled by 20."""
    weighted = (
        scores["safety"] * 0.30
        + scores["cognition"] * 0.25
        + scores["adl"] * 0.20
        + scores["medical_complexity"] * 0.15
        + scores["social_support"] * 0.05
        + scores["finances"] * 0.05
    )
    return _round_half_up(weighted * 20)


def _round_half_up(value: float) -> int:
    from decimal import Decimal, ROUND_HALF_UP

    return int(Decimal(repr(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
