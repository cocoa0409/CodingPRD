"""Entity assertions and domain invariant checkers.

Audit timestamps (created_at, updated_at) are ISO 8601 with three fractional
digits; domain date fields render as YYYY-MM-DD (PRD §2.4 — two timestamp
families). Every entity carries id/created_at/updated_at/version.
"""
import re

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import POINTS_BY_SEVERITY

__all__ = [
    "assert_common_fields", "assert_iso_date",
    "assert_management_unit", "assert_determination", "assert_public_comment",
    "assert_permit", "assert_treatment", "assert_closure", "assert_program",
    "assert_volunteer", "assert_assignment", "assert_grazing_offering",
    "assert_bid", "assert_agreement", "assert_citation",
    "assert_population_objective", "assert_posture_snapshot",
    "assert_agreement_balance_invariants", "assert_citation_points_match_severity",
]

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def assert_iso_date(value: str, field: str = "date"):
    """Assert a domain date field renders as YYYY-MM-DD."""
    assert isinstance(value, str) and _ISO_DATE_RE.match(value), (
        f"{field} must be a YYYY-MM-DD date, got {value!r}")


def assert_common_fields(data: dict):
    """System-managed fields present on every resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a dashed UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}")


def _assert_optional_iso_date(data: dict, field: str):
    value = data.get(field)
    assert value is None or (isinstance(value, str) and _ISO_DATE_RE.match(value)), (
        f"{field} must be null or a YYYY-MM-DD date, got {value!r}")


def assert_management_unit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["habitat_type"] in ["WETLAND", "GRASSLAND", "FOREST", "MIXED"]
    assert isinstance(data["acreage"], int) and data["acreage"] > 0
    assert data["access_posture"] in ["OPEN", "RESTRICTED", "CLOSED"]
    assert isinstance(data["committed_visitor_days"], int) and data["committed_visitor_days"] >= 0
    assert isinstance(data["habitat_priority_breeding"], int)
    assert isinstance(data["habitat_priority_annual"], int)


def assert_determination(data: dict):
    assert_common_fields(data)
    assert data["use_type"] in [
        "RESEARCH", "PHOTOGRAPHY", "COMMERCIAL_FILMING", "GUIDED_ACTIVITY", "GRAZING"]
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert_iso_date(data["comment_open_date"], "comment_open_date")
    assert_iso_date(data["comment_close_date"], "comment_close_date")
    assert data["status"] in ["DRAFT", "PUBLIC_COMMENT", "ADJUDICATION", "FINAL"]
    assert data["finding"] is None or data["finding"] in ["COMPATIBLE", "NOT_COMPATIBLE"]
    assert data["rationale"] is None or isinstance(data["rationale"], str)
    assert isinstance(data["unresolved_comment_count"], int) and data["unresolved_comment_count"] >= 0


def assert_public_comment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["determination_id"])
    assert isinstance(data["author_name"], str) and len(data["author_name"]) > 0
    assert isinstance(data["body"], str)
    assert data["status"] in ["SUBMITTED", "ADJUDICATED"]
    assert data["disposition"] is None or data["disposition"] in ["ACCEPTED", "REJECTED", "NOTED"]


def assert_permit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["applicant_ref"], str) and len(data["applicant_ref"]) > 0
    assert is_valid_uuid(data["management_unit_id"])
    assert is_valid_uuid(data["determination_id"])
    assert data["use_type"] in ["RESEARCH", "PHOTOGRAPHY", "COMMERCIAL_FILMING", "GUIDED_ACTIVITY"]
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert_iso_date(data["start_date"], "start_date")
    assert_iso_date(data["end_date"], "end_date")
    assert data["status"] in [
        "SUBMITTED", "REVISION_REQUESTED", "UNDER_REVIEW", "APPROVED",
        "ACTIVE", "SUSPENDED", "COMPLETED", "REVOKED", "EXPIRED"]
    assert isinstance(data["provisional_fee_cents"], int)
    assert data["assessed_fee_cents"] is None or isinstance(data["assessed_fee_cents"], int)
    assert data["revision_note"] is None or isinstance(data["revision_note"], str)
    assert data["suspended_by_closure_id"] is None or is_valid_uuid(data["suspended_by_closure_id"])


def assert_treatment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["management_unit_id"])
    assert data["treatment_type"] in ["WATER_MANIPULATION", "PRESCRIBED_BURN", "INVASIVE_CONTROL"]
    assert_iso_date(data["window_start"], "window_start")
    assert_iso_date(data["window_end"], "window_end")
    assert data["status"] in ["SCHEDULED", "WINDOW_OPEN", "IN_PROGRESS", "COMPLETED", "EXPIRED"]
    assert data.get("notes") is None or isinstance(data["notes"], str)


def assert_closure(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["management_unit_id"])
    assert data["closure_type"] in ["NESTING", "MIGRATION", "HUNT_SAFETY", "SPECIAL_EVENT"]
    assert data["scope"] in ["FULL", "TRAILS_ONLY"]
    assert_iso_date(data["start_date"], "start_date")
    assert_iso_date(data["end_date"], "end_date")
    assert data["status"] in ["SCHEDULED", "ACTIVE", "LIFTED"]


def assert_program(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["management_unit_id"])
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert_iso_date(data["program_date"], "program_date")
    assert isinstance(data["min_volunteers"], int) and data["min_volunteers"] >= 1
    assert isinstance(data["max_volunteers"], int) and data["max_volunteers"] >= data["min_volunteers"]
    assert data["status"] in ["SCHEDULED", "CANCELLED", "COMPLETED"]


def assert_volunteer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["background_status"] in ["PENDING", "CLEARED", "EXPIRED"]
    _assert_optional_iso_date(data, "cleared_on")


def assert_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["volunteer_id"])
    assert is_valid_uuid(data["program_id"])
    assert data["status"] in ["ACTIVE", "RELEASED", "COMPLETED"]


def assert_grazing_offering(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["management_unit_id"])
    assert isinstance(data["description"], str)
    assert isinstance(data["aum_cap"], int) and data["aum_cap"] > 0
    assert_iso_date(data["grazing_window_start"], "grazing_window_start")
    assert_iso_date(data["grazing_window_end"], "grazing_window_end")
    assert_iso_date(data["application_deadline"], "application_deadline")
    assert isinstance(data["min_stewardship_rating"], int) and 1 <= data["min_stewardship_rating"] <= 10
    assert data["status"] in ["OPEN", "AWARDED", "EXPIRED"]


def assert_bid(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["offering_id"])
    assert isinstance(data["cooperator_ref"], str) and len(data["cooperator_ref"]) > 0
    assert isinstance(data["rate_cents_per_aum"], int) and data["rate_cents_per_aum"] > 0
    assert isinstance(data["stewardship_rating"], int) and 1 <= data["stewardship_rating"] <= 10
    assert data["status"] in ["SUBMITTED", "WINNING", "REJECTED"]


def assert_agreement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["management_unit_id"])
    assert is_valid_uuid(data["winning_bid_id"])
    assert isinstance(data["cooperator_ref"], str) and len(data["cooperator_ref"]) > 0
    assert isinstance(data["aum_cap"], int) and data["aum_cap"] > 0
    assert_iso_date(data["grazing_window_start"], "grazing_window_start")
    assert_iso_date(data["grazing_window_end"], "grazing_window_end")
    assert isinstance(data["compliance_points"], int)
    assert isinstance(data["assessed_total_cents"], int) and data["assessed_total_cents"] >= 0
    assert isinstance(data["paid_total_cents"], int) and data["paid_total_cents"] >= 0
    assert isinstance(data["refunded_total_cents"], int) and data["refunded_total_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "COMPLETED"]


def assert_citation(data: dict):
    assert_common_fields(data)
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert isinstance(data["points"], int)
    subjects = [data.get("subject_permit_id"), data.get("subject_agreement_id")]
    supplied = [s for s in subjects if s is not None]
    assert len(supplied) == 1, "exactly one of subject_permit_id / subject_agreement_id"
    if data["subject_permit_id"] is not None:
        assert is_valid_uuid(data["subject_permit_id"])
    if data["subject_agreement_id"] is not None:
        assert is_valid_uuid(data["subject_agreement_id"])
    assert isinstance(data["note"], str)
    assert data["status"] in ["ISSUED", "VOIDED"]


def assert_population_objective(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["management_unit_id"])
    assert isinstance(data["species"], str) and len(data["species"]) > 0
    assert isinstance(data["target_count"], int) and data["target_count"] > 0
    assert data["current_survey_count"] is None or (
        isinstance(data["current_survey_count"], int) and data["current_survey_count"] >= 0)
    assert data["status"] in ["NO_SURVEY", "AT_TARGET", "BELOW_TARGET"]


def assert_posture_snapshot(data: dict):
    """The computed unit snapshot read (PRD §3.1): five derived fields."""
    assert data["access_posture"] in ["OPEN", "RESTRICTED", "CLOSED"]
    assert isinstance(data["committed_visitor_days"], int) and data["committed_visitor_days"] >= 0
    assert isinstance(data["habitat_priority_breeding"], int)
    assert isinstance(data["habitat_priority_annual"], int)
    assert isinstance(data["active_closure_count"], int) and data["active_closure_count"] >= 0


def assert_agreement_balance_invariants(data: dict):
    """Derived ledger invariant (PRD §3.8):
    outstanding == assessed - paid + refunded; balances never go negative."""
    assert data["outstanding_balance_cents"] == (
        data["assessed_total_cents"] - data["paid_total_cents"] + data["refunded_total_cents"]), (
        f"outstanding {data['outstanding_balance_cents']} != assessed "
        f"{data['assessed_total_cents']} - paid {data['paid_total_cents']} "
        f"+ refunded {data['refunded_total_cents']}")
    assert data["outstanding_balance_cents"] >= 0, "balances never go negative"
    assert data["refunded_total_cents"] <= data["paid_total_cents"], (
        "refunds are capped at the refundable balance")


def assert_citation_points_match_severity(data: dict):
    """Citation points are computed from severity, never from input (PRD §3.8)."""
    assert data["points"] == POINTS_BY_SEVERITY[data["severity"]], (
        f"points {data['points']} != computed {POINTS_BY_SEVERITY[data['severity']]} "
        f"for severity {data['severity']}")
