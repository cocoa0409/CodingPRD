"""Entity shape assertions and domain invariant checkers."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    ASSIGNMENT_STATUSES,
    COMMITMENT_STATUSES,
    DELIVERY_STATUSES,
    DETERMINATION_STATUSES,
    DUE_PROCESS_STATUSES,
    ESY_ELIGIBILITY_STATUSES,
    FUND_ALLOCATION_STATUSES,
    MAKEUP_SESSION_STATUSES,
    NEGOTIATION_STATUSES,
    PROGRAM_STATUSES,
    PROVIDER_STATUSES,
    RUN_STATUSES,
    SERVICE_LOG_STATUSES,
)

JsonDict = Dict[str, Any]


def _assert_common(resource: JsonDict, name: str) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert "id" in resource, f"{name} is missing id"
    assert is_valid_uuid(resource["id"]), f"{name}.id is not a UUID: {resource['id']}"
    for field in ("created_at", "updated_at"):
        assert field in resource, f"{name} is missing {field}"
        assert is_iso8601_timestamp(
            resource[field]
        ), f"{name}.{field} is not an ISO-8601 instant: {resource[field]}"
    assert isinstance(
        resource.get("version"), int
    ), f"{name}.version is not an integer: {resource.get('version')}"
    assert resource["version"] >= 1, f"{name}.version must start at 1"


def _assert_fields(resource: JsonDict, fields, name: str) -> None:
    for field in fields:
        assert field in resource, f"{name} is missing field {field}"


def assert_student(student: JsonDict) -> None:
    _assert_common(student, "Student")
    _assert_fields(
        student,
        (
            "student_number",
            "first_name",
            "last_name",
            "grade_band",
            "primary_disability",
            "iep_weekly_minutes_total",
            "transportation_required",
            "esy_eligibility_status",
            "pending_award_minutes",
            "outstanding_owed_minutes",
            "delivered_makeup_minutes_total",
            "esy_service_alert",
            "stay_put_active",
        ),
        "Student",
    )
    assert student["esy_eligibility_status"] in ESY_ELIGIBILITY_STATUSES
    assert isinstance(student["pending_award_minutes"], int)
    assert isinstance(student["outstanding_owed_minutes"], int)
    assert isinstance(student["delivered_makeup_minutes_total"], int)
    assert isinstance(student["esy_service_alert"], bool)
    assert isinstance(student["stay_put_active"], bool)


def assert_determination(determination: JsonDict) -> None:
    _assert_common(determination, "EligibilityDetermination")
    _assert_fields(
        determination,
        (
            "student_id",
            "school_year",
            "analysis_variant",
            "skill_probes",
            "status",
            "max_regression_pct",
            "max_recoupment_days",
            "criteria_met_count",
            "data_sufficiency",
            "eligibility_recommendation",
            "objection_round_count",
            "analyzed_by_user_id",
            "finalized_by_user_id",
        ),
        "EligibilityDetermination",
    )
    assert determination["status"] in DETERMINATION_STATUSES
    assert isinstance(determination["skill_probes"], list)
    assert isinstance(determination["criteria_met_count"], int)
    assert isinstance(determination["objection_round_count"], int)


def assert_program(program: JsonDict) -> None:
    _assert_common(program, "EsyProgram")
    _assert_fields(
        program,
        (
            "name",
            "school_year",
            "session_start_date",
            "session_end_date",
            "instructional_weekdays",
            "blackout_dates",
            "cancelled_dates",
            "daily_minutes_cap",
            "instructional_days_count",
            "instructional_week_count",
            "status",
        ),
        "EsyProgram",
    )
    assert program["status"] in PROGRAM_STATUSES
    assert isinstance(program["instructional_weekdays"], list)
    assert isinstance(program["blackout_dates"], list)
    assert isinstance(program["cancelled_dates"], list)
    assert isinstance(program["instructional_days_count"], int)
    assert isinstance(program["instructional_week_count"], int)


def assert_provider(provider: JsonDict) -> None:
    _assert_common(provider, "Provider")
    _assert_fields(
        provider,
        (
            "full_name",
            "role_type",
            "credential_expires_on",
            "rate_cents_per_minute",
            "max_weekly_minutes",
            "assigned_weekly_minutes",
            "status",
        ),
        "Provider",
    )
    assert provider["status"] in PROVIDER_STATUSES
    assert isinstance(provider["rate_cents_per_minute"], int)
    assert isinstance(provider["assigned_weekly_minutes"], int)


def assert_commitment(commitment: JsonDict) -> None:
    _assert_common(commitment, "ServiceCommitment")
    _assert_fields(
        commitment,
        (
            "program_id",
            "student_id",
            "transportation_run_id",
            "service_type",
            "iep_weekly_minutes",
            "staffing_ratio",
            "planned_total_minutes",
            "weekly_minutes_committed",
            "daily_minutes",
            "delivered_minutes",
            "compensable_owed_minutes",
            "status",
        ),
        "ServiceCommitment",
    )
    assert commitment["status"] in COMMITMENT_STATUSES
    for field in (
        "planned_total_minutes",
        "weekly_minutes_committed",
        "daily_minutes",
        "delivered_minutes",
        "compensable_owed_minutes",
    ):
        assert isinstance(commitment[field], int), f"{field} must be an integer"


def assert_assignment(assignment: JsonDict) -> None:
    _assert_common(assignment, "ProviderAssignment")
    _assert_fields(
        assignment,
        (
            "commitment_id",
            "provider_id",
            "weekday",
            "start_time",
            "end_time",
            "effective_from",
            "effective_to",
            "covered_weekly_minutes",
            "covered_total_minutes",
            "base_cost_cents",
            "indirect_cost_cents",
            "total_charge_cents",
            "charged_fund_source",
            "charged_budget_code",
            "status",
            "release_reason",
        ),
        "ProviderAssignment",
    )
    assert assignment["status"] in ASSIGNMENT_STATUSES
    for field in ("base_cost_cents", "indirect_cost_cents", "total_charge_cents"):
        assert isinstance(
            assignment[field], int
        ), f"{field} must be an integer number of cents"
    assert (
        assignment["base_cost_cents"] + assignment["indirect_cost_cents"]
        == assignment["total_charge_cents"]
    ), "total_charge_cents must equal base_cost_cents plus indirect_cost_cents"


def assert_transportation_run(run: JsonDict) -> None:
    _assert_common(run, "TransportationRun")
    _assert_fields(
        run,
        (
            "program_id",
            "route_code",
            "service_date",
            "window_start_time",
            "window_end_time",
            "vehicle_capacity_seats",
            "seats_committed",
            "status",
        ),
        "TransportationRun",
    )
    assert run["status"] in RUN_STATUSES
    assert isinstance(run["seats_committed"], int)
    assert isinstance(run["vehicle_capacity_seats"], int)


def assert_service_log(log: JsonDict) -> None:
    _assert_common(log, "ServiceLog")
    _assert_fields(
        log,
        (
            "commitment_id",
            "provider_id",
            "service_date",
            "outcome",
            "minutes_scheduled",
            "minutes_delivered",
            "miss_reason_code",
            "status",
            "generated_by",
        ),
        "ServiceLog",
    )
    assert log["status"] in SERVICE_LOG_STATUSES
    assert isinstance(log["minutes_scheduled"], int)
    assert isinstance(log["minutes_delivered"], int)
    assert log["minutes_delivered"] <= log["minutes_scheduled"]


def assert_award(award: JsonDict) -> None:
    _assert_common(award, "CompensatoryAward")
    _assert_fields(
        award,
        (
            "student_id",
            "source_program_id",
            "calculation_variant",
            "computed_minutes",
            "proposed_minutes",
            "agreed_minutes",
            "delivered_minutes",
            "scheduled_minutes",
            "remaining_owed_minutes",
            "forfeited_minutes",
            "negotiation_status",
            "delivery_status",
            "dispute_round_count",
            "parent_no_show_count",
            "delivery_deadline_date",
            "severity_factor",
            "verified_missed_log_count",
            "excluded_log_count",
            "authored_by_user_id",
            "resolved_by_user_id",
        ),
        "CompensatoryAward",
    )
    assert award["negotiation_status"] in NEGOTIATION_STATUSES
    assert award["delivery_status"] in DELIVERY_STATUSES
    for field in (
        "computed_minutes",
        "delivered_minutes",
        "scheduled_minutes",
        "remaining_owed_minutes",
        "forfeited_minutes",
        "dispute_round_count",
        "parent_no_show_count",
        "verified_missed_log_count",
        "excluded_log_count",
    ):
        assert isinstance(award[field], int), f"{field} must be an integer"


def assert_makeup_session(session: JsonDict) -> None:
    _assert_common(session, "MakeupSession")
    _assert_fields(
        session,
        (
            "award_id",
            "provider_id",
            "supersedes_session_id",
            "session_date",
            "start_time",
            "end_time",
            "minutes_planned",
            "minutes_delivered",
            "status",
            "charge_cents",
            "charged_fund_source",
            "charged_budget_code",
        ),
        "MakeupSession",
    )
    assert session["status"] in MAKEUP_SESSION_STATUSES
    assert isinstance(session["minutes_planned"], int)
    assert isinstance(session["charge_cents"], int)


def assert_fund_allocation(allocation: JsonDict) -> None:
    _assert_common(allocation, "FundAllocation")
    _assert_fields(
        allocation,
        (
            "program_id",
            "fund_source",
            "budget_code",
            "authorized_amount_cents",
            "encumbered_amount_cents",
            "expended_amount_cents",
            "compensatory_expended_cents",
            "available_cents",
            "status",
        ),
        "FundAllocation",
    )
    assert allocation["status"] in FUND_ALLOCATION_STATUSES
    for field in (
        "authorized_amount_cents",
        "encumbered_amount_cents",
        "expended_amount_cents",
        "compensatory_expended_cents",
        "available_cents",
    ):
        assert isinstance(
            allocation[field], int
        ), f"{field} must be an integer number of cents"
    assert_allocation_available_identity(allocation)


def assert_due_process_record(record: JsonDict) -> None:
    _assert_common(record, "DueProcessRecord")
    _assert_fields(
        record,
        (
            "student_id",
            "record_type",
            "filed_on",
            "allegation_summary",
            "status",
            "stay_put_active",
            "resolution_note",
            "resolved_at",
        ),
        "DueProcessRecord",
    )
    assert record["status"] in DUE_PROCESS_STATUSES
    assert isinstance(record["stay_put_active"], bool)


# ---------------------------------------------------------- domain invariants
def assert_allocation_available_identity(allocation: JsonDict) -> None:
    """available_cents equals authorized less encumbered less expended."""
    expected = (
        allocation["authorized_amount_cents"]
        - allocation["encumbered_amount_cents"]
        - allocation["expended_amount_cents"]
    )
    assert allocation["available_cents"] == expected, (
        "available_cents must equal authorized_amount_cents less "
        f"encumbered_amount_cents less expended_amount_cents: got "
        f"{allocation['available_cents']}, expected {expected}"
    )


def assert_award_remaining_identity(award: JsonDict) -> None:
    """remaining_owed_minutes equals agreed less delivered less forfeited, floored at 0."""
    agreed = award["agreed_minutes"] or 0
    expected = max(
        0, agreed - award["delivered_minutes"] - award["forfeited_minutes"]
    )
    assert award["remaining_owed_minutes"] == expected, (
        "remaining_owed_minutes must equal agreed_minutes less delivered_minutes "
        f"less forfeited_minutes clamped at zero: got "
        f"{award['remaining_owed_minutes']}, expected {expected}"
    )


def assert_version(resource: JsonDict, expected_version: int, label: str = "resource") -> None:
    assert resource["version"] == expected_version, (
        f"{label}.version expected {expected_version}, got {resource['version']}"
    )


def assert_status(resource: JsonDict, expected_status: str, field: str = "status") -> None:
    assert resource[field] == expected_status, (
        f"{field} expected {expected_status!r}, got {resource[field]!r}"
    )


def assert_unchanged(before: JsonDict, after: JsonDict, *fields: str) -> None:
    for field in fields:
        assert before[field] == after[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r} "
            "but the operation should have left it untouched"
        )


def assert_student_ledger(
    student: JsonDict,
    pending_award_minutes: Optional[int] = None,
    outstanding_owed_minutes: Optional[int] = None,
    delivered_makeup_minutes_total: Optional[int] = None,
    esy_service_alert: Optional[bool] = None,
    stay_put_active: Optional[bool] = None,
    esy_eligibility_status: Optional[str] = None,
) -> None:
    checks = {
        "pending_award_minutes": pending_award_minutes,
        "outstanding_owed_minutes": outstanding_owed_minutes,
        "delivered_makeup_minutes_total": delivered_makeup_minutes_total,
        "esy_service_alert": esy_service_alert,
        "stay_put_active": stay_put_active,
        "esy_eligibility_status": esy_eligibility_status,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert student[field] == expected, (
                f"student.{field} expected {expected!r}, got {student[field]!r}"
            )


def assert_commitment_plan(
    commitment: JsonDict,
    planned_total_minutes: int,
    weekly_minutes_committed: int,
    daily_minutes: int,
) -> None:
    assert commitment["planned_total_minutes"] == planned_total_minutes
    assert commitment["weekly_minutes_committed"] == weekly_minutes_committed
    assert commitment["daily_minutes"] == daily_minutes


def assert_pagination_meta(
    meta: JsonDict, total_count: int, has_more: bool, limit: int, offset: int
) -> None:
    assert meta["total_count"] == total_count, (
        f"total_count expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"has_more expected {has_more}, got {meta['has_more']}"
    )
    assert meta["limit"] == limit
    assert meta["offset"] == offset


def assert_ascending(rows, *keys: str) -> None:
    """Rows must be ordered ascending on the given key tuple."""
    extracted = [tuple(row[key] for key in keys) for row in rows]
    assert extracted == sorted(extracted), (
        f"rows are not ordered ascending on {keys}: {extracted}"
    )


def assert_severity_factor(award: JsonDict, expected: float) -> None:
    assert float(award["severity_factor"]) == expected, (
        f"severity_factor expected {expected}, got {award['severity_factor']}"
    )


def assert_regression_pct(determination: JsonDict, expected: float) -> None:
    actual = float(determination["max_regression_pct"])
    assert abs(actual - expected) < 0.05, (
        f"max_regression_pct expected {expected}, got {actual}"
    )
