"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` verifies the shape of one resource payload — the
server-minted identity fields the PRD guarantees plus the caller-visible
business fields.  These helpers deliberately do not over-assert on fields
a PRD-only implementer could reasonably omit; the tests themselves pin the
specific values under examination.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .constants import (
    CLAIM_ADJUDICATED,
    CLAIM_DENIED,
    CLAIM_PAID,
    CLAIM_PENDED_ATTACHMENTS,
    CLAIM_PENDED_REVIEW,
    CLAIM_RECEIVED,
    CLAIM_VOID,
    DENIAL_AGE_LIMIT,
    DENIAL_ATTACHMENT_MISSING,
    DENIAL_FREQUENCY,
    DENIAL_MISSING_TOOTH,
    DENIAL_NO_COVERAGE,
    DENIAL_TIMELY_FILING,
    DENIAL_WAITING_PERIOD,
    LINE_DENIED,
    LINE_PAYABLE,
    LINE_PENDING,
    LINE_PRICED,
    PLAN_ACTIVE,
    PLAN_DRAFT,
    PLAN_RETIRED,
    PLAN_SUSPENDED,
    PREDET_APPROVED,
    PREDET_DENIED,
    PREDET_EXPIRED,
    PREDET_SUBMITTED,
    PREDET_UNDER_REVIEW,
    PREDET_WITHDRAWN,
    SCHEDULE_ACTIVE,
    SCHEDULE_PENDING,
    SCHEDULE_RETIRED,
    SCHEDULE_SUPERSEDED,
)

# Re-export the framework validators so tests can import from one place.
__all__ = [
    "get_success_data",
    "validate_error",
    "validate_paginated",
    "validate_success",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_common_fields",
    "assert_plan",
    "assert_provider",
    "assert_fee_schedule",
    "assert_subscriber",
    "assert_dependent",
    "assert_limitation_rule",
    "assert_predetermination",
    "assert_claim",
    "assert_claim_line",
    "assert_claim_attachment",
    "assert_accumulator",
    "assert_accumulator_invariants",
]

PLAN_STATUSES = {PLAN_DRAFT, PLAN_ACTIVE, PLAN_SUSPENDED, PLAN_RETIRED}
SCHEDULE_STATUSES = {SCHEDULE_PENDING, SCHEDULE_ACTIVE, SCHEDULE_SUPERSEDED, SCHEDULE_RETIRED}
PREDET_STATUSES = {
    PREDET_SUBMITTED,
    PREDET_UNDER_REVIEW,
    PREDET_APPROVED,
    PREDET_DENIED,
    PREDET_WITHDRAWN,
    PREDET_EXPIRED,
}
CLAIM_STATUSES = {
    CLAIM_RECEIVED,
    CLAIM_PENDED_ATTACHMENTS,
    CLAIM_PENDED_REVIEW,
    CLAIM_ADJUDICATED,
    CLAIM_PAID,
    CLAIM_DENIED,
    CLAIM_VOID,
}
LINE_STATUSES = {LINE_PENDING, LINE_PRICED, LINE_PAYABLE, LINE_DENIED}
DENIAL_CODES = {
    None,
    "NULL",
    DENIAL_WAITING_PERIOD,
    DENIAL_FREQUENCY,
    DENIAL_AGE_LIMIT,
    DENIAL_MISSING_TOOTH,
    DENIAL_TIMELY_FILING,
    DENIAL_ATTACHMENT_MISSING,
    DENIAL_NO_COVERAGE,
}


def assert_common_fields(data):
    """The standard server-managed fields every primary resource carries."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601, got %r" % data.get("created_at")
    )
    assert "updated_at" in data, "primary resources carry updated_at"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_plan(data):
    assert_common_fields(data)
    assert data["status"] in PLAN_STATUSES
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["annual_maximum_cents"], int)
    assert isinstance(data["deductible_cents"], int)
    for pct_field in (
        "preventive_coinsurance_pct",
        "basic_coinsurance_pct",
        "major_coinsurance_pct",
    ):
        assert isinstance(data[pct_field], int), pct_field


def assert_provider(data):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert data["tier"] in ("PREMIER", "PPO", "OUT_OF_NETWORK")
    assert isinstance(data["npi"], str) and data["npi"]


def assert_fee_schedule(data):
    assert_common_fields(data)
    assert data["status"] in SCHEDULE_STATUSES
    assert data["tier"] in ("PREMIER", "PPO", "OUT_OF_NETWORK")
    assert is_iso8601_timestamp(data.get("effective_from", ""))


def assert_subscriber(data):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert data["cob_priority"] in ("PRIMARY", "SECONDARY", "NONE")
    assert is_valid_uuid(data.get("plan_id", "")), "subscriber carries plan_id"


def assert_dependent(data):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert data["relationship"] in ("SPOUSE", "CHILD", "DOMESTIC_PARTNER")


def assert_limitation_rule(data):
    assert_common_fields(data)
    assert data["rule_kind"] in (
        "FREQUENCY",
        "AGE_MAX",
        "AGE_MIN",
        "REPLACEMENT_INTERVAL",
        "MISSING_TOOTH",
    )
    assert isinstance(data["cdt_code"], str) and data["cdt_code"]


def assert_predetermination(data):
    assert_common_fields(data)
    assert data["status"] in PREDET_STATUSES
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["cdt_code"], str) and data["cdt_code"]
    assert isinstance(data["submitted_amount_cents"], int)


def assert_claim(data):
    assert_common_fields(data)
    assert data["status"] in CLAIM_STATUSES
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    for total_field in (
        "total_submitted_cents",
        "total_allowed_cents",
        "total_plan_pay_cents",
        "total_patient_pay_cents",
    ):
        assert isinstance(data[total_field], int), total_field


def assert_claim_line(data):
    assert_common_fields(data)
    assert data["status"] in LINE_STATUSES
    assert isinstance(data["line_number"], int) and data["line_number"] >= 1
    assert isinstance(data["submitted_amount_cents"], int)
    assert data.get("denial_code") in DENIAL_CODES


def assert_claim_attachment(data):
    """Attachments are immutable: id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "attachments carry no version field"
    assert "updated_at" not in data, "attachments carry no updated_at field"
    assert data["attachment_kind"] in (
        "RADIOGRAPH",
        "NARRATIVE",
        "PERIO_CHART",
        "PHOTO",
    )
    assert isinstance(data["blob_ref"], str) and data["blob_ref"]


def assert_accumulator(data):
    assert_common_fields(data)
    assert isinstance(data["deductible_met_cents"], int)
    assert isinstance(data["annual_max_used_cents"], int)
    assert isinstance(data["plan_year_key"], str) and "-" in data["plan_year_key"]


def assert_accumulator_invariants(accumulator, plan):
    """The bounds the PRD guarantees hold after every transition."""
    assert 0 <= accumulator["deductible_met_cents"] <= plan["deductible_cents"], (
        "deductible_met_cents out of bounds: %r" % accumulator["deductible_met_cents"]
    )
    assert 0 <= accumulator["annual_max_used_cents"] <= plan["annual_maximum_cents"], (
        "annual_max_used_cents out of bounds: %r" % accumulator["annual_max_used_cents"]
    )
