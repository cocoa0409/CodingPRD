"""Domain assertions and invariant checkers.

The generic envelope validators come from the shared runner package and are
re-exported here so a test file has a single import site.  Everything added
on top encodes a promise the PRD makes about this domain: the common
properties of section 2.5, the month-string shapes of section 2.4, the
integer-cents money rule of section 2.6, and the cross-field invariants of
sections 3.1 (money conservation), 3.5 (premium component sum) and 3.7
(invoice outstanding arithmetic).
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

from .constants import (
    APPEAL_STATUSES,
    ARRANGEMENT_STATUSES,
    COLLECTION_STATUSES,
    COVERAGE_KINDS,
    DETERMINATION_STATUSES,
    ELECTION_STATUSES,
    ELECTION_WINDOWS,
    ENROLLED_VIA_WINDOWS,
    ENROLLMENT_PERIOD_STATUSES,
    ENROLLMENT_STATUSES,
    FILING_STATUSES,
    INVOICE_STATUSES,
    IRMAA_TIER_MAX,
    IRMAA_TIER_MIN,
    LIFE_EVENT_TYPES,
    MISINFORM_SOURCES,
    PARTS,
    PAYER_BASES,
    PAYER_ROLES,
    PENALTY_PARTS,
    PENALTY_STATUSES,
    RECORD_STATUSES,
    RELIEF_STATUSES,
    RELIEF_TYPES,
    VERIFICATION_STATUSES,
    WINDOW_TYPES,
    is_month_string,
)

# --- Shape primitives ---------------------------------------------------------


def assert_month_string(value, label="month"):
    """PRD section 2.4: ``*_month`` fields are ``YYYY-MM`` strings."""
    assert is_month_string(value), (
        "{0} must be a YYYY-MM month string, got {1!r}".format(label, value)
    )


def assert_optional_month_string(value, label="month"):
    assert value is None or is_month_string(value), (
        "{0} must be null or a YYYY-MM month string, got {1!r}".format(label, value)
    )


def assert_date_string(value, label="date"):
    """A ``YYYY-MM-DD`` date string (date_of_birth, event_date, due_date)."""
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        "{0} must be a YYYY-MM-DD date string, got {1!r}".format(label, value)
    )


def assert_cents(value, label="amount"):
    """PRD section 2.6: money fields are integer cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        "{0} must be integer cents, got {1!r}".format(label, value)
    )


def assert_common_fields(data):
    """PRD section 2.5: id, created_at, updated_at, version on every resource."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID: {0!r}".format(
        data.get("id")
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601: {0!r}".format(data.get("created_at"))
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601: {0!r}".format(data.get("updated_at"))
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer: {0!r}".format(data.get("version"))
    )


# --- Per-resource assertions ----------------------------------------------------


def assert_beneficiary(data):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert_date_string(data["date_of_birth"], "date_of_birth")
    assert_month_string(data["attainment_month"], "attainment_month")
    assert_month_string(data["iep_start_month"], "iep_start_month")
    assert_month_string(data["iep_end_month"], "iep_end_month")
    assert_cents(data["credit_cents"], "credit_cents")
    assert data["credit_cents"] >= 0


def assert_rate_schedule(data):
    assert_common_fields(data)
    assert isinstance(data["coverage_year"], int)
    assert_cents(data["part_b_standard_cents"], "part_b_standard_cents")
    assert_cents(data["part_d_national_base_cents"], "part_d_national_base_cents")
    brackets = data["irmaa_brackets"]
    assert isinstance(brackets, list) and len(brackets) == 6, (
        "irmaa_brackets must hold exactly six objects"
    )
    for index, bracket in enumerate(brackets):
        assert bracket["tier"] == index, "brackets must be in ascending tier order"
        for key in (
            "single_floor_cents",
            "joint_floor_cents",
            "part_b_surcharge_cents",
            "part_d_surcharge_cents",
        ):
            assert_cents(bracket[key], "irmaa_brackets[{0}].{1}".format(index, key))


def assert_enrollment_period(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert data["window_type"] in WINDOW_TYPES
    assert_month_string(data["window_start_month"], "window_start_month")
    assert_month_string(data["window_end_month"], "window_end_month")
    assert data["status"] in ENROLLMENT_PERIOD_STATUSES
    assert data.get("source_coverage_ref") is None or isinstance(
        data["source_coverage_ref"], str
    )


def assert_coverage_enrollment(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert data["part"] in PARTS
    assert data["enrollment_status"] in ENROLLMENT_STATUSES
    assert data["collection_status"] in COLLECTION_STATUSES
    assert_month_string(data["effective_month"], "effective_month")
    assert_optional_month_string(data.get("end_month"), "end_month")
    assert data["enrolled_via_window"] in ENROLLED_VIA_WINDOWS


def assert_employer_coverage_record(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert isinstance(data["employer_name"], str) and data["employer_name"]
    assert isinstance(data["employer_size"], int) and data["employer_size"] >= 0
    assert_month_string(data["coverage_start_month"], "coverage_start_month")
    assert_optional_month_string(data.get("coverage_end_month"), "coverage_end_month")
    assert_optional_month_string(data.get("employment_end_month"), "employment_end_month")
    assert isinstance(data["is_drug_coverage_creditable"], bool)
    assert data["verification_status"] in VERIFICATION_STATUSES
    assert data["record_status"] in RECORD_STATUSES


def assert_penalty_assessment(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert data["part"] in PENALTY_PARTS
    assert isinstance(data["gap_months"], int) and data["gap_months"] >= 0
    # PRD section 3.4: the period count and percentage are populated for
    # PART_B and are null for PART_D, whose basis lives entirely in gap_months.
    if data["part"] == "PART_B":
        assert isinstance(data["full_12month_periods"], int)
        assert isinstance(data["penalty_pct"], int)
    else:
        assert data.get("full_12month_periods") is None
        assert data.get("penalty_pct") is None
    assert data["status"] in PENALTY_STATUSES


def assert_tax_return_record(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert isinstance(data["tax_year"], int)
    assert_cents(data["magi_cents"], "magi_cents")
    assert data["magi_cents"] >= 0
    assert data["filing_status"] in FILING_STATUSES


def assert_premium_determination(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert isinstance(data["coverage_year"], int)
    assert data["part"] in PENALTY_PARTS
    assert data["status"] in DETERMINATION_STATUSES
    assert isinstance(data["tax_year_used"], int)
    assert IRMAA_TIER_MIN <= data["irmaa_tier"] <= IRMAA_TIER_MAX
    for key in (
        "base_premium_cents",
        "irmaa_surcharge_cents",
        "lep_cents",
        "total_premium_cents",
    ):
        assert_cents(data[key], key)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert_premium_component_sum(data)


def assert_appeal_case(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert is_valid_uuid(data["premium_determination_id"])
    assert data["life_event_type"] in LIFE_EVENT_TYPES
    assert_date_string(data["event_date"], "event_date")
    assert_cents(data["claimed_magi_cents"], "claimed_magi_cents")
    assert data["status"] in APPEAL_STATUSES
    assert data.get("adjudicated_by_user_id") is None or isinstance(
        data["adjudicated_by_user_id"], str
    )


def assert_withholding_arrangement(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert_cents(data["monthly_benefit_cents"], "monthly_benefit_cents")
    assert data["monthly_benefit_cents"] >= 0
    assert data["status"] in ARRANGEMENT_STATUSES


def assert_premium_invoice(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert data["part"] in PENALTY_PARTS
    assert_month_string(data["service_month"], "service_month")
    for key in ("amount_cents", "paid_cents", "applied_cents", "outstanding_cents"):
        assert_cents(data[key], key)
    assert_date_string(data["due_date"], "due_date")
    assert isinstance(data["is_arrears"], bool)
    assert data["status"] in INVOICE_STATUSES
    assert_invoice_outstanding(data)


def assert_payer_coordination_record(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert data["role"] in PAYER_ROLES
    assert data["basis"] in PAYER_BASES
    assert_month_string(data["effective_start_month"], "effective_start_month")
    assert_optional_month_string(
        data.get("effective_end_month"), "effective_end_month"
    )


def assert_plan_election(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert data["election_window"] in ELECTION_WINDOWS
    assert isinstance(data["season_key"], str) and data["season_key"]
    assert data["current_coverage"] in COVERAGE_KINDS
    assert data["target_coverage"] in COVERAGE_KINDS
    assert_month_string(data["effective_month"], "effective_month")
    assert data["status"] in ELECTION_STATUSES


def assert_equitable_relief_case(data):
    assert_common_fields(data)
    assert is_valid_uuid(data["beneficiary_id"])
    assert data["relief_type"] in RELIEF_TYPES
    assert data["part"] in PENALTY_PARTS
    assert_optional_month_string(
        data.get("requested_effective_month"), "requested_effective_month"
    )
    assert data["claimed_misinform_source"] in MISINFORM_SOURCES
    assert isinstance(data["description"], str)
    assert data["status"] in RELIEF_STATUSES


# --- Domain invariants ----------------------------------------------------------


def assert_premium_component_sum(determination):
    """PRD section 3.5: total is the exact integer sum of base, surcharge and
    penalty, with no further rounding."""
    total = determination["total_premium_cents"]
    expected = (
        determination["base_premium_cents"]
        + determination["irmaa_surcharge_cents"]
        + determination["lep_cents"]
    )
    assert total == expected, (
        "total_premium_cents {0} != base {1} + irmaa {2} + lep {3}".format(
            total,
            determination["base_premium_cents"],
            determination["irmaa_surcharge_cents"],
            determination["lep_cents"],
        )
    )


def assert_invoice_outstanding(invoice):
    """PRD section 3.7: outstanding is amount minus paid and is never negative."""
    expected = invoice["amount_cents"] - invoice["paid_cents"]
    assert invoice["outstanding_cents"] == expected, (
        "outstanding_cents {0} != amount {1} - paid {2}".format(
            invoice["outstanding_cents"], invoice["amount_cents"], invoice["paid_cents"]
        )
    )
    assert invoice["outstanding_cents"] >= 0, "outstanding_cents is never negative"


def assert_money_conservation(beneficiary, invoices):
    """PRD section 3.1: sum(paid_cents) == sum(applied_cents) + credit_cents."""
    paid_total = sum(invoice["paid_cents"] for invoice in invoices)
    applied_total = sum(invoice["applied_cents"] for invoice in invoices)
    credit = beneficiary["credit_cents"]
    assert paid_total == applied_total + credit, (
        "money conservation broken: paid {0} != applied {1} + credit {2}".format(
            paid_total, applied_total, credit
        )
    )


def assert_single_governing_election(elections, season_key):
    """PRD section 3.8: exactly one GOVERNING election per (beneficiary, season)."""
    governing = [
        election
        for election in elections
        if election["status"] == "GOVERNING"
        and election["season_key"] == season_key
    ]
    assert len(governing) == 1, (
        "expected exactly one GOVERNING election in season {0}, found {1}".format(
            season_key, len(governing)
        )
    )
