"""Entity assertions and domain invariant checkers for the ad policy API."""

from typing import List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonicalise_instant
from .constants import (
    ACCOUNT_STATUSES,
    ACTION_ORIGINS,
    ACTION_STATUSES,
    APPEAL_STATUSES,
    CATEGORY_CLASSES,
    CERTIFICATION_STATUSES,
    CHECK_TYPES,
    DESTINATION_RESULTS,
    DESTINATION_STATUSES,
    DISPOSITIONS,
    FRESH_BLOCKING_REASON_CODES,
    LEDGER_REASONS,
    MISMATCH_DETAILS,
    NOTICE_REASON_CODES,
    NOTICE_STATUSES,
    QUEUES,
    REVIEW_STATUSES,
    REVIEWER_STATUSES,
    SCREENING_OUTCOMES,
    SWEEP_COUNTERS,
    TASK_RESOLUTIONS,
    TASK_STATUSES,
    USER_AGENT_VARIANTS,
)


# --- Shared shape helpers ---------------------------------------------------
def assert_identity_fields(data: dict, *, versioned: bool = True) -> None:
    """PRD §2.4: "Every resource carries an `id` that is a UUID string with no
    prefix and a `created_at` timestamp read from the logical clock."
    """
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


def assert_append_only_identity(data: dict) -> None:
    """PRD §2.4: "`ScreeningRun`, `ClassifierDecision`, `DestinationCheck`,
    `PoliticalArchiveEntry` and `ViolationLedgerEntry` are append-only records that
    carry only `id` and `created_at`."
    """
    assert_identity_fields(data, versioned=False)
    assert "updated_at" not in data, "an append-only record carries no updated_at"
    assert "version" not in data, "an append-only record carries no version"


def assert_instant_equals(
    actual: Optional[str], expected: Optional[str], field: str = "instant"
) -> None:
    """Compare two UTC instants by value, ignoring fractional-digit width."""
    if expected is None:
        assert actual is None, f"{field} should be null, got {actual!r}"
        return
    assert actual is not None, f"{field} should be {expected!r}, got null"
    assert canonicalise_instant(actual) == canonicalise_instant(expected), (
        f"{field} should be {expected!r}, got {actual!r}"
    )


def assert_two_decimal_value(value, field: str = "value") -> None:
    """PRD §2.6: "every stored and returned decimal carries exactly two decimal
    places"."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, never a string: {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{field} must carry at most 2 decimal places, got {value!r}"
    )


def assert_money_like(data: dict, fields: Sequence[str]) -> None:
    for field in fields:
        assert_two_decimal_value(data[field], field)


def assert_sorted_ascending(values: Sequence, field: str = "list") -> None:
    assert list(values) == sorted(values), f"{field} must be sorted ascending: {values}"


# --- Policy rules and country variations (PRD §3.1) ------------------------
def assert_policy_rule(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 40
    assert data["code"] == data["code"].upper()
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 160
    assert data["category_class"] in CATEGORY_CLASSES
    assert_two_decimal_value(data["base_severity_weight"], "base_severity_weight")
    assert 0.01 <= data["base_severity_weight"] <= 20.00
    assert isinstance(data["requires_certification"], bool)
    assert isinstance(data["requires_disclaimer"], bool)
    assert_two_decimal_value(
        data["confidence_auto_disapprove_threshold"],
        "confidence_auto_disapprove_threshold",
    )
    assert_two_decimal_value(
        data["confidence_manual_threshold"], "confidence_manual_threshold"
    )
    assert (
        data["confidence_auto_disapprove_threshold"]
        > data["confidence_manual_threshold"]
    ), "the auto threshold must be strictly greater than the manual threshold"
    assert isinstance(data["review_sla_hours"], int)
    assert 1 <= data["review_sla_hours"] <= 336
    assert data["default_queue"] in QUEUES
    assert isinstance(data["country_override_count"], int)
    assert data["country_override_count"] >= 0


def assert_country_override(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["policy_rule_id"])
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["country_code"] == data["country_code"].upper()
    assert data["disposition"] in DISPOSITIONS
    assert isinstance(data["requires_license"], bool)
    assert isinstance(data["requires_disclaimer"], bool)
    assert_two_decimal_value(data["severity_multiplier"], "severity_multiplier")
    assert 0.50 <= data["severity_multiplier"] <= 3.00


# --- Advertisers (PRD §3.2) ----------------------------------------------
def assert_advertiser(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["industry_code"], str) and data["industry_code"]
    assert data["identity_status"] in ("PENDING", "VERIFIED", "FAILED")
    assert data["business_standing_status"] in ("PENDING", "VERIFIED", "FAILED")
    assert data["industry_authorization_status"] in (
        "NOT_REQUIRED",
        "PENDING",
        "GRANTED",
        "DENIED",
    )
    assert data["political_eligibility_status"] in (
        "NOT_REQUESTED",
        "PENDING",
        "ELIGIBLE",
        "INELIGIBLE",
    )
    assert data["account_status"] in ACCOUNT_STATUSES
    assert_money_like(
        data, ("violation_points_raw", "violation_points_decayed", "severity_index")
    )
    assert data["violation_points_raw"] >= 0.00
    assert data["violation_points_decayed"] >= 0.00
    assert isinstance(data["ledger_entry_count"], int)
    assert data["ledger_entry_count"] >= 0


def assert_fresh_advertiser_baseline(data: dict) -> None:
    """PRD §3.2: "A newly onboarded advertiser starts with `identity_status`
    `PENDING`, `business_standing_status` `PENDING`, `industry_authorization_status`
    `NOT_REQUIRED`, `political_eligibility_status` `NOT_REQUESTED`, `account_status`
    `ACTIVE`, `violation_points_raw`, `violation_points_decayed` and `severity_index`
    all 0.00, and `ledger_entry_count` 0."
    """
    assert data["identity_status"] == "PENDING"
    assert data["business_standing_status"] == "PENDING"
    assert data["industry_authorization_status"] == "NOT_REQUIRED"
    assert data["political_eligibility_status"] == "NOT_REQUESTED"
    assert data["account_status"] == "ACTIVE"
    assert data["violation_points_raw"] == pytest.approx(0.00, abs=0.01)
    assert data["violation_points_decayed"] == pytest.approx(0.00, abs=0.01)
    assert data["severity_index"] == pytest.approx(0.00, abs=0.01)
    assert data["ledger_entry_count"] == 0
    assert data["version"] == 1


# --- Reviewers (PRD §3.6) ------------------------------------------------
def assert_reviewer(data: dict) -> None:
    assert_identity_fields(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["queue_specialties"], list) and data["queue_specialties"]
    assert all(queue in QUEUES for queue in data["queue_specialties"])
    assert len(set(data["queue_specialties"])) == len(data["queue_specialties"])
    assert (
        isinstance(data["country_authorizations"], list) and data["country_authorizations"]
    )
    assert len(set(data["country_authorizations"])) == len(
        data["country_authorizations"]
    )
    assert isinstance(data["max_concurrent_claims"], int)
    assert 1 <= data["max_concurrent_claims"] <= 10
    assert isinstance(data["claimed_task_count"], int)
    assert data["claimed_task_count"] >= 0
    assert data["status"] in REVIEWER_STATUSES


# --- Ad creatives (PRD §3.3, §2.11) --------------------------------------
def assert_ad_creative(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["advertiser_id"])
    assert isinstance(data["headline"], str) and data["headline"]
    assert isinstance(data["body_text"], str) and data["body_text"]
    assert isinstance(data["declared_category_codes"], list)
    assert data["declared_category_codes"], "declared_category_codes is never empty"
    assert isinstance(data["target_country_codes"], list)
    assert data["target_country_codes"], "target_country_codes is never empty"
    assert data["landing_page_url"].startswith("https://")
    assert data["display_url"].startswith("https://")
    assert isinstance(data["political_flag"], bool)
    assert data["disclaimer_text"] is None or isinstance(data["disclaimer_text"], str)
    assert data["review_status"] in REVIEW_STATUSES
    assert data["destination_status"] in DESTINATION_STATUSES
    assert_money_like(data, ("risk_score_provisional", "risk_score_final"))
    assert 0.00 <= data["risk_score_provisional"] <= 100.00
    assert 0.00 <= data["risk_score_final"] <= 100.00
    assert isinstance(data["serving_eligible"], bool)
    assert isinstance(data["blocking_reason_codes"], list)
    assert isinstance(data["limited_country_codes"], list)
    assert data["approved_under_certification_id"] is None or is_valid_uuid(
        data["approved_under_certification_id"]
    )
    assert isinstance(data["screening_run_count"], int)
    assert data["screening_run_count"] >= 0


def assert_fresh_creative_baseline(data: dict) -> None:
    """PRD §3.3: "A newly created creative is born in `review_status` `DRAFT` and
    `destination_status` `NOT_CHECKED`, with `risk_score_provisional` and
    `risk_score_final` both 0.00, `limited_country_codes` empty,
    `approved_under_certification_id` null, `screening_run_count` 0,
    `serving_eligible` false and `blocking_reason_codes` exactly
    `[REVIEW_NOT_APPROVED, DESTINATION_NOT_CLEARED]`."
    """
    assert data["review_status"] == "DRAFT"
    assert data["destination_status"] == "NOT_CHECKED"
    assert data["risk_score_provisional"] == pytest.approx(0.00, abs=0.01)
    assert data["risk_score_final"] == pytest.approx(0.00, abs=0.01)
    assert data["limited_country_codes"] == []
    assert data["approved_under_certification_id"] is None
    assert data["screening_run_count"] == 0
    assert data["serving_eligible"] is False
    assert data["blocking_reason_codes"] == FRESH_BLOCKING_REASON_CODES
    assert data["version"] == 1


def assert_serving_gate(
    data: dict, *, eligible: bool, blocking_reason_codes: List[str]
) -> None:
    """PRD §2.11: "`blocking_reason_codes` lists the codes of the conjuncts that
    failed, appended in that fixed order and never sorted afterwards."
    """
    assert data["serving_eligible"] is eligible, (
        f"serving_eligible should be {eligible}, got {data['serving_eligible']}"
    )
    assert data["blocking_reason_codes"] == blocking_reason_codes, (
        f"blocking_reason_codes should be {blocking_reason_codes}, "
        f"got {data['blocking_reason_codes']}"
    )


# --- Screening (PRD §3.4) ------------------------------------------------
def assert_screening_run(data: dict) -> None:
    assert_append_only_identity(data)
    assert is_valid_uuid(data["ad_creative_id"])
    assert isinstance(data["classifier_version"], str) and data["classifier_version"]
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert data["outcome"] in SCREENING_OUTCOMES
    assert isinstance(data["decision_count"], int) and data["decision_count"] >= 1
    assert_two_decimal_value(data["max_confidence"], "max_confidence")
    assert_two_decimal_value(data["provisional_risk_score"], "provisional_risk_score")
    assert isinstance(data["creative_version_at_run"], int)


def assert_classifier_decision(data: dict) -> None:
    assert_append_only_identity(data)
    assert is_valid_uuid(data["screening_run_id"])
    assert is_valid_uuid(data["policy_rule_id"])
    assert_two_decimal_value(data["confidence"], "confidence")
    assert 0.01 <= data["confidence"] <= 1.00
    assert isinstance(data["matched_snippet"], str) and data["matched_snippet"]
    assert data["disposition"] in (
        "AUTO_DISAPPROVE",
        "ROUTE_MANUAL",
        "BELOW_THRESHOLD",
    )
    assert_two_decimal_value(
        data["country_multiplier_applied"], "country_multiplier_applied"
    )
    assert_two_decimal_value(data["assessed_points"], "assessed_points")


# --- Review tasks (PRD §3.6) --------------------------------------------
def assert_review_task(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["ad_creative_id"])
    assert data["primary_policy_rule_id"] is None or is_valid_uuid(
        data["primary_policy_rule_id"]
    )
    assert data["assigned_reviewer_id"] is None or is_valid_uuid(
        data["assigned_reviewer_id"]
    )
    assert data["queue"] in QUEUES
    assert data["status"] in TASK_STATUSES
    assert data["resolution"] in TASK_RESOLUTIONS
    assert_two_decimal_value(data["priority_score"], "priority_score")
    assert 0.00 <= data["priority_score"] <= 100.00
    assert is_iso8601_timestamp(data["sla_deadline_at"])
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0
    assert data["claimed_at"] is None or is_iso8601_timestamp(data["claimed_at"])


def assert_task_unclaimed(data: dict) -> None:
    """PRD §3.6: "release ... clears both `assigned_reviewer_id` and `claimed_at`"."""
    assert data["assigned_reviewer_id"] is None, (
        "an unheld task carries a null assigned_reviewer_id"
    )
    assert data["claimed_at"] is None, "an unheld task carries a null claimed_at"


# --- Certifications (PRD §3.5) ------------------------------------------
def assert_certification(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["advertiser_id"])
    assert is_valid_uuid(data["policy_rule_id"])
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert (
        isinstance(data["issuing_country_code"], str)
        and len(data["issuing_country_code"]) == 2
    )
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_until"])
    assert data["valid_until"] > data["valid_from"]
    assert data["status"] in CERTIFICATION_STATUSES
    assert data["revocation_reason"] is None or isinstance(
        data["revocation_reason"], str
    )


# --- Destination checks (PRD §3.8) --------------------------------------
def assert_destination_check(data: dict) -> None:
    assert_append_only_identity(data)
    assert is_valid_uuid(data["ad_creative_id"])
    assert data["check_type"] in CHECK_TYPES
    assert data["user_agent_variant"] in USER_AGENT_VARIANTS
    assert data["fetched_final_url"].startswith("https://")
    assert (
        isinstance(data["fetched_content_category"], str)
        and data["fetched_content_category"]
    )
    assert isinstance(data["http_status"], int) and 100 <= data["http_status"] <= 599
    assert data["result"] in DESTINATION_RESULTS
    assert data["mismatch_detail"] is None or data["mismatch_detail"] in MISMATCH_DETAILS
    if data["result"] == "CLEARED":
        assert data["mismatch_detail"] is None, (
            "a CLEARED check carries a null mismatch_detail"
        )


# --- Disapproval notices, appeals, ledger and enforcement (PRD §3.9) ----
def assert_disapproval_notice(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["ad_creative_id"])
    assert data["decided_by_reviewer_id"] is None or is_valid_uuid(
        data["decided_by_reviewer_id"]
    )
    assert isinstance(data["reason_codes"], list) and data["reason_codes"]
    assert all(code in NOTICE_REASON_CODES for code in data["reason_codes"])
    assert len(set(data["reason_codes"])) == len(data["reason_codes"])
    assert isinstance(data["policy_rule_codes"], list)
    assert_sorted_ascending(data["policy_rule_codes"], "policy_rule_codes")
    assert isinstance(data["assessment_lines"], list)
    assert_money_like(data, ("assessed_points", "disclosed_points_total"))
    assert data["appeal_window_hours"] in (72, 168)
    assert is_iso8601_timestamp(data["appeal_deadline_at"])
    assert data["status"] in NOTICE_STATUSES
    assert isinstance(data["political_at_issue"], bool)


def assert_assessment_lines(
    data: dict, expected: Sequence[dict]
) -> None:
    """PRD §3.9: "The notice's `assessment_lines` is phase one's lines followed by
    phase two's, in exactly that order, and its `assessed_points` is the sum of the
    `line_points` of every line, capped at 100.00."
    """
    lines = data["assessment_lines"]
    assert len(lines) == len(expected), (
        f"expected {len(expected)} assessment lines, got {len(lines)}: {lines}"
    )
    for index, (actual, wanted) in enumerate(zip(lines, expected)):
        for key, value in wanted.items():
            if isinstance(value, float):
                assert actual[key] == pytest.approx(value, abs=0.01), (
                    f"assessment line {index} field {key} should be {value}, "
                    f"got {actual[key]}"
                )
            else:
                assert actual[key] == value, (
                    f"assessment line {index} field {key} should be {value!r}, "
                    f"got {actual[key]!r}"
                )
    total = round(sum(round(float(line["line_points"]), 2) for line in lines), 2)
    assert data["assessed_points"] == pytest.approx(min(total, 100.00), abs=0.01), (
        "assessed_points is the sum of the already-rounded line_points"
    )


def assert_appeal(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["disapproval_notice_id"])
    assert data["evidence_certification_id"] is None or is_valid_uuid(
        data["evidence_certification_id"]
    )
    assert data["decided_by_reviewer_id"] is None or is_valid_uuid(
        data["decided_by_reviewer_id"]
    )
    assert isinstance(data["justification"], str) and 10 <= len(data["justification"])
    assert data["status"] in APPEAL_STATUSES
    assert data["decided_at"] is None or is_iso8601_timestamp(data["decided_at"])
    assert data["reinstated_review_status"] is None or (
        data["reinstated_review_status"] in REVIEW_STATUSES
    )


def assert_ledger_entry(data: dict) -> None:
    assert_append_only_identity(data)
    assert is_valid_uuid(data["advertiser_id"])
    assert data["source_notice_id"] is None or is_valid_uuid(data["source_notice_id"])
    assert_two_decimal_value(data["delta_points"], "delta_points")
    assert data["delta_points"] != 0, "a ledger entry never carries a zero delta"
    assert data["reason"] in LEDGER_REASONS
    assert_two_decimal_value(data["balance_after"], "balance_after")
    assert isinstance(data["entry_index"], int) and data["entry_index"] >= 1


def assert_ledger_contiguous(entries: Sequence[dict]) -> None:
    """PRD §3.9: "an `entry_index` that is a 1-based per-advertiser insertion
    counter, contiguous, and that defines the chronological replay order."
    """
    assert [entry["entry_index"] for entry in entries] == list(
        range(1, len(entries) + 1)
    ), f"entry_index must be 1-based and contiguous: {entries}"


def assert_enforcement_action(data: dict) -> None:
    assert_identity_fields(data)
    assert is_valid_uuid(data["advertiser_id"])
    assert data["prior_action_id"] is None or is_valid_uuid(data["prior_action_id"])
    assert data["source_notice_id"] is None or is_valid_uuid(data["source_notice_id"])
    assert data["action_type"] in ("WARNING", "RESTRICTION", "SUSPENSION")
    assert data["origin"] in ACTION_ORIGINS
    assert isinstance(data["trigger_reason"], str) and data["trigger_reason"]
    assert_two_decimal_value(data["severity_index_at_issue"], "severity_index_at_issue")
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_until"])
    assert data["status"] in ACTION_STATUSES


def assert_archive_entry(data: dict) -> None:
    assert_append_only_identity(data)
    assert is_valid_uuid(data["ad_creative_id"])
    assert is_valid_uuid(data["advertiser_id"])
    assert isinstance(data["payer_name"], str) and data["payer_name"]
    assert isinstance(data["headline_snapshot"], str) and data["headline_snapshot"]
    assert isinstance(data["target_country_codes_snapshot"], list)
    assert data["target_country_codes_snapshot"]
    assert is_iso8601_timestamp(data["archived_at"])
    assert is_iso8601_timestamp(data["retention_until"])
    assert data["searchable"] is True


# --- The sweep and clock envelopes (PRD §2.8) ---------------------------
def assert_sweep_counts(data: dict, **expected) -> None:
    """PRD §2.8: "The sweep response reports `activated_certifications`,
    `expired_certifications`, `expired_notices`, `expired_review_tasks`,
    `requeued_review_tasks`, `expired_enforcement_actions`,
    `lifted_enforcement_actions`, `released_hold_creatives` and
    `decay_refreshed_advertisers`."
    """
    for counter in SWEEP_COUNTERS:
        assert counter in data, f"the sweep response must report {counter}"
        assert isinstance(data[counter], int), f"{counter} must be an integer"
    for counter, value in expected.items():
        assert data[counter] == value, (
            f"{counter} should be {value}, got {data[counter]}"
        )


# --- Envelope helpers (PRD §2.2) ---------------------------------------
def assert_error_envelope(response) -> None:
    """PRD §2.2: "An error response carries a `meta` object holding only
    `api_request_id` and `api_request_timestamp`, a `response_type` of `"error"`,
    and a `data` object holding exactly `error_id` and `message`."
    """
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}
    assert set(body["data"].keys()) == {"error_id", "message"}
    assert body["meta"]["api_request_id"].startswith("req_")


def assert_object_envelope(response) -> None:
    """PRD §2.2: "`response_type` is `"object"` for a single resource and `"array"`
    for a collection."
    """
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
