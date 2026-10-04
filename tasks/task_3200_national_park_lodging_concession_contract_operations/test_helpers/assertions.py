"""Domain assertions.

The generic envelope validators come from the shared runner package and are
re-exported here so a test file has a single import site.  The helpers added
on top encode the PRD-specific promises: the three-fractional-digit timestamp
form of PRD 2.2/2.6, the integer-cents rule of PRD 2.7, and per-entity shape
checks over the fields the PRD names.
"""

from prd_bench_local_runner.testing import (  # noqa: F401  (re-exported)
    NON_EXISTENT_UUID,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant


def assert_cents(actual, expected, label="cents"):
    """PRD 2.7: every ``*_cents`` field is a whole number of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "{0} must be an integer number of cents, got {1!r}".format(label, actual)
    )
    assert actual == expected, "{0}: expected {1}, got {2}".format(
        label, expected, actual
    )


def assert_instant(actual, expected, label="instant"):
    """Compare two ISO 8601 instants on value, not on spelling."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        "{0}: expected {1!r}, got {2!r}".format(label, expected, actual)
    )


def assert_common_fields(data, label="resource"):
    """PRD 2.6: id + created_at + updated_at + version, all present."""
    assert is_valid_uuid(data.get("id", "")), "{0}.id must be a UUID".format(label)
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "{0}.created_at must be ISO 8601".format(label)
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "{0}.updated_at must be ISO 8601".format(label)
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "{0}.version must be a positive integer".format(label)
    )


def assert_contract(data):
    assert_common_fields(data, "contract")
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TRANSITION_PENDING", "CLOSED")
    assert data["lsi_annual_schedule_type"] in ("LINEAR", "DECLINING_BALANCE")


def assert_season(data):
    assert_common_fields(data, "season")
    assert data["status"] in ("PLANNED", "OPEN", "CLOSED", "RECONCILED")


def assert_service_line(data):
    assert_common_fields(data, "service_line")
    assert data["line_type"] in ("LODGING", "FOOD", "RETAIL", "TOURS")
    assert data["status"] in ("AUTHORIZED", "SUSPENDED", "TERMINATED")


def assert_room_class(data):
    assert_common_fields(data, "room_class")
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")


def assert_study(data):
    assert_common_fields(data, "study")
    assert data["status"] in ("REGISTERED", "STALE", "ARCHIVED")
    assert_cents(data["weighted_mean_cents"], data["weighted_mean_cents"],
                 "study.weighted_mean_cents")


def assert_filing(data):
    assert_common_fields(data, "rate_filing")
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "SUPERSEDED", "EXPIRED",
    )


def assert_reservation(data):
    assert_common_fields(data, "reservation")
    assert data["status"] in ("REQUESTED", "CONFIRMED", "CANCELLED", "NO_SHOW", "FULFILLED")
    assert data["occupancy_band"] in ("SOLO", "DOUBLE", "FAMILY")
    assert data["occupancy_mode"] in ("BANDED", "ACTUAL_HEADCOUNT")


def assert_receipts_report(data):
    assert_common_fields(data, "receipts_report")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")


def assert_fee_statement(data):
    assert_common_fields(data, "fee_statement")
    assert data["status"] in ("ISSUED", "PAID")
    assert data["reporting_method"] == "PER_LINE_ROUNDED"


def assert_capital_project(data):
    assert_common_fields(data, "capital_project")
    assert data["status"] in ("PROPOSED", "AUTHORIZED", "COMPLETED", "APPROVED", "EXPENDED")


def assert_housing_unit(data):
    assert_common_fields(data, "housing_unit")
    assert data["status"] in ("AVAILABLE", "OFFLINE")


def assert_hire(data):
    assert_common_fields(data, "seasonal_hire")
    assert data["status"] in ("HIRED", "ARRIVED", "DEPARTED", "NO_SHOW", "TERMINATED")


def assert_voucher(data):
    assert_common_fields(data, "transport_voucher")
    assert data["status"] in ("BOOKED", "USED", "VOID")


def assert_incident(data):
    assert_common_fields(data, "environmental_incident")
    assert data["protocol"] in ("WASTE", "WATER", "WILDLIFE")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["status"] in (
        "REPORTED", "UNDER_REVIEW", "CORRECTIVE_PLAN_REQUIRED", "CLOSED",
    )
