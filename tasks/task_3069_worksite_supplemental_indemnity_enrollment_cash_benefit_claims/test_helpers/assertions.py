"""Entity shape and domain invariant assertions.

These helpers assert the standard system-managed fields the PRD's common-resource
section pins (UUID ``id``, ISO 8601 ``created_at``/``updated_at``, integer
``version``) plus per-entity vocabulary checks. They deliberately do not demand
optional or situational fields beyond what the PRD commits to.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CAMPAIGN_CLOSED,
    CAMPAIGN_DRAFT,
    CAMPAIGN_FAILED,
    CAMPAIGN_LOCKED,
    CAMPAIGN_MET,
    CAMPAIGN_OPEN,
    CLAIM_APPEALED,
    CLAIM_APPROVED,
    CLAIM_DENIED,
    CLAIM_PAID,
    CLAIM_SUBMITTED,
    CLAIM_UNDER_REVIEW,
    CLAIM_VOIDED,
    CYCLE_CLOSED,
    CYCLE_FINALIZED,
    CYCLE_OPEN,
    CYCLE_RECONCILED,
    DOC_ACCEPTED,
    DOC_RECEIVED,
    DOC_REJECTED,
    EMPLOYEE_ACTIVE,
    EMPLOYEE_TERMINATED,
    GROUP_ACTIVE,
    GROUP_PROSPECT,
    GROUP_SUSPENDED,
    GROUP_TERMINATED,
    LINE_POSTED,
    LINE_REVERSED,
    POLICY_ACTIVE,
    POLICY_APPLIED,
    POLICY_CANCELLED,
    POLICY_DECLINED,
    POLICY_ISSUED,
    POLICY_LAPSED,
    POLICY_PORTED,
    SCHEDULE_DRAFT,
    SCHEDULE_PUBLISHED,
    SCHEDULE_SUPERSEDED,
    SERIES_ACTIVE,
    SERIES_DRAFT,
    SERIES_RETIRED,
    WELLNESS_APPROVED,
    WELLNESS_DENIED,
    WELLNESS_PAID,
    WELLNESS_SUBMITTED,
    JsonObject,
)


def assert_common_fields(data: JsonObject, entity_name: str = "resource"):
    assert is_valid_uuid(data.get("id", "")), "%s.id must be a UUID, got %r" % (
        entity_name,
        data.get("id"),
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "%s.created_at must be ISO 8601, got %r" % (entity_name, data.get("created_at"))
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "%s.updated_at must be ISO 8601, got %r" % (entity_name, data.get("updated_at"))
    )
    assert isinstance(data.get("version"), int), "%s.version must be an int, got %r" % (
        entity_name,
        data.get("version"),
    )


def assert_employer_group(data: JsonObject):
    assert_common_fields(data, "employer_group")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("group_code"), str) and data["group_code"]
    assert data.get("status") in (
        GROUP_PROSPECT,
        GROUP_ACTIVE,
        GROUP_SUSPENDED,
        GROUP_TERMINATED,
    )
    assert isinstance(data.get("eligible_employee_count"), int)
    assert isinstance(data.get("enrolled_count"), int)


def assert_benefit_counselor(data: JsonObject):
    assert_common_fields(data, "benefit_counselor")
    assert isinstance(data.get("license_id"), str) and data["license_id"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_enrollment_campaign(data: JsonObject):
    assert_common_fields(data, "enrollment_campaign")
    assert data.get("status") in (
        CAMPAIGN_DRAFT,
        CAMPAIGN_OPEN,
        CAMPAIGN_LOCKED,
        CAMPAIGN_MET,
        CAMPAIGN_FAILED,
        CAMPAIGN_CLOSED,
    )
    assert isinstance(data.get("window_start"), str)
    assert isinstance(data.get("window_end"), str)


def assert_policy_series(data: JsonObject):
    assert_common_fields(data, "policy_series")
    assert isinstance(data.get("series_code"), str) and data["series_code"]
    assert data.get("product_line") in ("ACCIDENT", "HOSPITAL", "CRITICAL_ILLNESS")
    assert data.get("status") in (SERIES_DRAFT, SERIES_ACTIVE, SERIES_RETIRED)


def assert_benefit_schedule(data: JsonObject):
    assert_common_fields(data, "benefit_schedule")
    assert data.get("status") in (SCHEDULE_DRAFT, SCHEDULE_PUBLISHED, SCHEDULE_SUPERSEDED)
    assert isinstance(data.get("schedule_version"), int)
    assert isinstance(data.get("benefit_items"), list)


def assert_employee(data: JsonObject):
    assert_common_fields(data, "employee")
    assert data.get("status") in (EMPLOYEE_ACTIVE, EMPLOYEE_TERMINATED)
    assert isinstance(data.get("preexisting_diagnosis_codes"), list)


def assert_policy(data: JsonObject):
    assert_common_fields(data, "policy")
    assert data.get("status") in (
        POLICY_APPLIED,
        POLICY_ISSUED,
        POLICY_ACTIVE,
        POLICY_LAPSED,
        POLICY_PORTED,
        POLICY_DECLINED,
        POLICY_CANCELLED,
    )
    assert data.get("premium_mode") in ("PRE_TAX", "POST_TAX")
    assert isinstance(data.get("lifetime_paid_cents"), int)
    assert isinstance(data.get("paid_occurrences_by_year"), dict)


def assert_claim(data: JsonObject):
    assert_common_fields(data, "claim")
    assert data.get("status") in (
        CLAIM_SUBMITTED,
        CLAIM_UNDER_REVIEW,
        CLAIM_APPROVED,
        CLAIM_PAID,
        CLAIM_DENIED,
        CLAIM_APPEALED,
        CLAIM_VOIDED,
    )
    assert isinstance(data.get("claimed_occurrences"), int)


def assert_claim_document(data: JsonObject):
    assert_common_fields(data, "claim_document")
    assert data.get("status") in (DOC_RECEIVED, DOC_ACCEPTED, DOC_REJECTED)
    assert data.get("doc_type") in (
        "DIAGNOSIS_PROOF",
        "PROCEDURE_PROOF",
        "ITEMIZED_BILL",
        "ATTENDING_PHYSICIAN_STATEMENT",
    )


def assert_wellness_benefit(data: JsonObject):
    assert_common_fields(data, "wellness_benefit")
    assert data.get("status") in (
        WELLNESS_SUBMITTED,
        WELLNESS_APPROVED,
        WELLNESS_PAID,
        WELLNESS_DENIED,
    )
    assert isinstance(data.get("calendar_year"), int)


def assert_payroll_cycle(data: JsonObject):
    assert_common_fields(data, "payroll_cycle")
    assert data.get("status") in (CYCLE_OPEN, CYCLE_FINALIZED, CYCLE_RECONCILED, CYCLE_CLOSED)
    assert isinstance(data.get("total_posted_cents"), int)


def assert_deduction_line(data: JsonObject):
    assert_common_fields(data, "deduction_line")
    assert data.get("status") in (LINE_POSTED, LINE_REVERSED)
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("coverage_days"), int)
    assert data.get("tax_treatment") in ("PRE_TAX", "POST_TAX")


def assert_policy_ledger_invariants(policy: JsonObject):
    """The claims ledger never goes negative and counters are non-negative."""
    assert policy["lifetime_paid_cents"] >= 0, "lifetime_paid_cents must be >= 0"
    for year, by_event in policy["paid_occurrences_by_year"].items():
        for event_code, count in by_event.items():
            assert count >= 0, (
                "paid_occurrences_by_year[%s][%s] must be >= 0" % (year, event_code)
            )


__all__ = [
    "assert_common_fields",
    "assert_employer_group",
    "assert_benefit_counselor",
    "assert_enrollment_campaign",
    "assert_policy_series",
    "assert_benefit_schedule",
    "assert_employee",
    "assert_policy",
    "assert_claim",
    "assert_claim_document",
    "assert_wellness_benefit",
    "assert_payroll_cycle",
    "assert_deduction_line",
    "assert_policy_ledger_invariants",
]
