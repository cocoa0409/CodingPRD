"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ParticipationStatus, MemberType, MemberStatus, PaymentMethod, PayeeStatus,
    WorkStatus, WorkShareStatus, RateScheduleStatus, UsageReportStatus,
    UsageLineStatus, AccrualStatus, MatchRunStatus, ClaimStatus, DisputeStatus,
    StatementStatus, StatementLineType, AuditStatus, CycleRunStatus,
    CycleMethodology,
)


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            f"version must be a positive integer, got {data.get('version')!r}"


def assert_service_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["participation_status"] in {s.value for s in ParticipationStatus}
    assert isinstance(data["accepted_rate_schedule_version"], int)
    assert isinstance(data["audit_credits"], int) and data["audit_credits"] >= 0


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["member_type"] in {t.value for t in MemberType}
    assert data["status"] in {s.value for s in MemberStatus}
    assert isinstance(data.get("is_signatory"), bool)


def assert_payee(data: dict):
    _assert_common(data)
    assert isinstance(data["payee_legal_name"], str) and data["payee_legal_name"]
    assert data["payment_method"] in {m.value for m in PaymentMethod}
    assert data["status"] in {s.value for s in PayeeStatus}
    assert isinstance(data["tax_id"], str) and len(data["tax_id"]) == 9


def assert_work(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in {s.value for s in WorkStatus}
    assert isinstance(data.get("match_run_count", 0), int)


def assert_work_share(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_id", ""))
    assert is_valid_uuid(data.get("claimant_member_id", ""))
    assert 0 < data["share_percent"] <= 100
    assert data["status"] in {s.value for s in WorkShareStatus}


def assert_rate_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["rate_cents_under_5min"], int)
    assert isinstance(data["rate_cents_per_minute_over_5min"], int)
    assert data["status"] in {s.value for s in RateScheduleStatus}


def assert_usage_report(data: dict):
    _assert_common(data)
    assert isinstance(data["reporting_month"], str) and len(data["reporting_month"]) == 7
    assert data["status"] in {s.value for s in UsageReportStatus}
    assert isinstance(data["total_usage_cents"], int)
    assert isinstance(data["matched_usage_cents"], int)
    assert isinstance(data["unmatched_usage_cents"], int)


def assert_usage_line(data: dict):
    _assert_common(data)
    assert isinstance(data["isrc"], str) and len(data["isrc"]) == 12
    assert isinstance(data["track_title"], str)
    assert isinstance(data["plays_count"], int) and data["plays_count"] > 0
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] > 0
    assert isinstance(data["royalties_cents"], int)
    assert data["status"] in {s.value for s in UsageLineStatus}


def assert_accrual(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in {s.value for s in AccrualStatus}
    assert isinstance(data["reporting_month"], str) and len(data["reporting_month"]) == 7


def assert_match_run(data: dict):
    _assert_common(data)
    assert data["status"] == MatchRunStatus.COMPLETED.value
    assert isinstance(data["total_lines_evaluated"], int)
    assert isinstance(data["lines_matched"], int)
    assert isinstance(data["lines_promoted_unmatched"], int)
    assert isinstance(data["match_rate_bps"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert 0 < data["share_percent_claimed"] <= 100
    assert data["status"] in {s.value for s in ClaimStatus}


def assert_dispute(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_ids"], list)
    assert data["status"] in {s.value for s in DisputeStatus}


def assert_statement(data: dict):
    # Statement is in the light family: id + created_at only, no version.
    _assert_common(data, with_version=False)
    assert "version" not in data, "Statement must not carry a version field"
    assert "updated_at" not in data, "Statement must not carry an updated_at field"
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert data["status"] in {s.value for s in StatementStatus}
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["adjustments_cents"], int)
    assert isinstance(data["net_cents"], int)


def assert_statement_line(data: dict):
    # StatementLine is in the light family: id + created_at only, no version.
    _assert_common(data, with_version=False)
    assert "version" not in data, "StatementLine must not carry a version field"
    assert "updated_at" not in data, "StatementLine must not carry an updated_at field"
    assert isinstance(data["allocated_cents"], int)
    assert data["line_type"] in {t.value for t in StatementLineType}


def assert_audit(data: dict):
    _assert_common(data)
    assert isinstance(data["scope_months"], list)
    assert data["status"] in {s.value for s in AuditStatus}


def assert_cycle_run(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_month"], str) and len(data["cycle_month"]) == 7
    assert data["methodology"] in {m.value for m in CycleMethodology}
    assert data["status"] in {s.value for s in CycleRunStatus}
    assert isinstance(data["pool_cents"], int)
    assert isinstance(data["residual_cents"], int)


def assert_distribution_line(data: dict):
    # DistributionLine is in the light family: id + created_at only, no version.
    _assert_common(data, with_version=False)
    assert "version" not in data, "DistributionLine must not carry a version field"
    assert "updated_at" not in data, "DistributionLine must not carry an updated_at field"
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["weight_numerator"], int)
    assert isinstance(data["weight_denominator"], int)
    assert isinstance(data["residual_cents"], int)


def assert_report_partition_invariant(report: dict):
    """matched + unmatched always equals total on an accepted report."""
    assert report["matched_usage_cents"] + report["unmatched_usage_cents"] == report["total_usage_cents"], (
        f"partition invariant violated: {report['matched_usage_cents']} + "
        f"{report['unmatched_usage_cents']} != {report['total_usage_cents']}"
    )


def assert_pool_conservation(cycle_run: dict, distribution_lines: list):
    """pool_cents == sum(allocated + residual over lines) + cycle residual."""
    distributed = sum(l["allocated_cents"] + l["residual_cents"] for l in distribution_lines)
    assert distributed + cycle_run["residual_cents"] == cycle_run["pool_cents"], (
        f"pool conservation violated: {distributed} + {cycle_run['residual_cents']} "
        f"!= {cycle_run['pool_cents']}"
    )
