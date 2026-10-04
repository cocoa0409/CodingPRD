"""Entity assertions and domain invariant checkers.

``assert_<entity>(data)`` checks the fields the PRD promises on each resource:
system-managed properties (``id``, ``created_at``, ``updated_at``,
``version``), declared fields, and enum membership of every status field.
``validate_created`` is the creation-endpoint companion to the framework's
``validate_success``: resource creation answers HTTP 201, never the bare 200
default, so the expected status is always explicit at the call site.
"""

from typing import Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .types import (
    AllocationStatus,
    CampaignStatus,
    Channel,
    CommitmentStatus,
    CompositionStatus,
    ConfidentialityTier,
    CoverageTier,
    IpReviewStatus,
    LicenseStatus,
    MarketingStatus,
    ProgramStatus,
    QualCycleStatus,
    StandingTier,
    SuspensionReason,
    TankStatus,
    UsageReportStatus,
)


def _assert_common_fields(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def _enum_values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def validate_created(response) -> dict:
    """Validate a resource-creation response, which answers HTTP 201."""
    return validate_success(response, expected_status=201)


def assert_device_maker(data: dict) -> None:
    _assert_common_fields(data, "DeviceMaker")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region"], str) and len(data["region"]) > 0
    assert data["standing_tier"] in _enum_values(StandingTier)
    assert data["ip_review_status"] in _enum_values(IpReviewStatus)


def assert_program(data: dict) -> None:
    _assert_common_fields(data, "Program")
    assert is_valid_uuid(data.get("device_maker_id", "")), "Program.device_maker_id must be a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["primary_market"] in ("CONSUMER_ELECTRONICS", "AUTOMOTIVE", "PHARMA_PACKAGING", "ARCHITECTURAL")
    assert data["confidentiality_tier"] in _enum_values(ConfidentialityTier)
    assert data["status"] in _enum_values(ProgramStatus)
    assert "nda_reference" in data, "Program must expose nda_reference (null until NDA executed)"
    assert "design_freeze_date" in data, "Program must expose design_freeze_date (null until qualification)"


def assert_composition(data: dict) -> None:
    _assert_common_fields(data, "Composition")
    assert is_valid_uuid(data.get("program_id", "")), "Composition.program_id must be a UUID"
    assert isinstance(data["composition_code"], str) and len(data["composition_code"]) > 0
    assert isinstance(data["complexity_multiplier"], (int, float))
    assert 1.0 <= data["complexity_multiplier"] <= 2.5
    assert data["status"] in _enum_values(CompositionStatus)


def assert_qual_cycle(data: dict) -> None:
    _assert_common_fields(data, "QualCycle")
    assert is_valid_uuid(data.get("composition_id", "")), "QualCycle.composition_id must be a UUID"
    assert isinstance(data["test_plan_ref"], str) and len(data["test_plan_ref"]) > 0
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert data["status"] in _enum_values(QualCycleStatus)
    assert "result_recorded_at" in data, "QualCycle must expose result_recorded_at"


def assert_tank(data: dict) -> None:
    _assert_common_fields(data, "Tank")
    assert is_valid_uuid(data.get("commitment_id", "")), "Tank.commitment_id must be a UUID"
    assert isinstance(data["capacity_units_per_day"], int) and data["capacity_units_per_day"] > 0
    assert data["status"] in _enum_values(TankStatus)
    assert is_iso8601_timestamp(data.get("construction_ready_date", "")), (
        "Tank.construction_ready_date must be ISO 8601"
    )


def assert_campaign(data: dict) -> None:
    _assert_common_fields(data, "Campaign")
    assert is_valid_uuid(data.get("tank_id", "")), "Campaign.tank_id must be a UUID"
    assert is_valid_uuid(data.get("composition_id", "")), "Campaign.composition_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_date", "")), "Campaign.start_date must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_date", "")), "Campaign.end_date must be ISO 8601"
    assert isinstance(data["planned_units"], int) and data["planned_units"] > 0
    assert data["status"] in _enum_values(CampaignStatus)
    assert isinstance(data["expected_good_units"], int) and data["expected_good_units"] >= 0
    assert isinstance(data["unallocated_units"], int)
    assert isinstance(data["cumulative_good_units"], int) and data["cumulative_good_units"] >= 0
    assert isinstance(data["cumulative_scrap_units"], int) and data["cumulative_scrap_units"] >= 0
    assert "realized_yield" in data, "Campaign must expose realized_yield (null until first record)"
    assert isinstance(data["provisional_unit_cost_cents"], int) and data["provisional_unit_cost_cents"] > 0
    assert "final_unit_cost_cents" in data, "Campaign must expose final_unit_cost_cents"


def assert_commitment(data: dict) -> None:
    _assert_common_fields(data, "Commitment")
    assert is_valid_uuid(data.get("program_id", "")), "Commitment.program_id must be a UUID"
    assert is_valid_uuid(data.get("device_maker_id", "")), "Commitment.device_maker_id must be a UUID"
    assert isinstance(data["committed_units"], int) and data["committed_units"] > 0
    assert isinstance(data["required_units"], int) and data["required_units"] > 0
    assert isinstance(data["prepayment_cents"], int) and data["prepayment_cents"] >= 0
    assert data["status"] in _enum_values(CommitmentStatus)
    assert "coverage_tier" in data, "Commitment must expose coverage_tier (null until SECURED)"
    if data["coverage_tier"] is not None:
        assert data["coverage_tier"] in _enum_values(CoverageTier)
    assert "effective_units" in data, "Commitment must expose effective_units (null until SECURED)"
    assert isinstance(data["fulfilled_units"], int) and data["fulfilled_units"] >= 0
    assert isinstance(data["supply_coverage"], (int, float))
    assert isinstance(data["prepayment_applied_cents"], int) and data["prepayment_applied_cents"] >= 0
    assert isinstance(data["prepayment_remaining_cents"], int) and data["prepayment_remaining_cents"] >= 0
    assert isinstance(data["prepayment_refunded_cents"], int) and data["prepayment_refunded_cents"] >= 0
    assert "breach_deadline" in data, "Commitment must expose breach_deadline"
    assert "countersigned_by" in data, "Commitment must expose countersigned_by"
    assert "signed_at" in data, "Commitment must expose signed_at"


def assert_allocation(data: dict) -> None:
    _assert_common_fields(data, "Allocation")
    assert is_valid_uuid(data.get("commitment_id", "")), "Allocation.commitment_id must be a UUID"
    assert is_valid_uuid(data.get("campaign_id", "")), "Allocation.campaign_id must be a UUID"
    assert isinstance(data["units"], int) and data["units"] > 0
    assert data["status"] in _enum_values(AllocationStatus)


def assert_license(data: dict) -> None:
    _assert_common_fields(data, "License")
    assert is_valid_uuid(data.get("device_maker_id", "")), "License.device_maker_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "License.program_id must be a UUID"
    assert data["market"] in ("CONSUMER_ELECTRONICS", "AUTOMOTIVE", "PHARMA_PACKAGING", "ARCHITECTURAL")
    assert is_iso8601_timestamp(data.get("effective_date", "")), "License.effective_date must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expiry_date", "")), "License.expiry_date must be ISO 8601"
    assert data["license_status"] in _enum_values(LicenseStatus)
    assert data["marketing_status"] in _enum_values(MarketingStatus)
    assert data["suspension_reason"] in _enum_values(SuspensionReason)
    assert isinstance(data["cumulative_royalty_cents"], int) and data["cumulative_royalty_cents"] >= 0


def assert_usage_report(data: dict) -> None:
    _assert_common_fields(data, "UsageReport")
    assert is_valid_uuid(data.get("license_id", "")), "UsageReport.license_id must be a UUID"
    assert is_iso8601_timestamp(data.get("period_start", "")), "UsageReport.period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "UsageReport.period_end must be ISO 8601"
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    for line in data["lines"]:
        assert line["channel"] in _enum_values(Channel)
        assert isinstance(line["units"], int) and line["units"] > 0
        assert isinstance(line["net_revenue_cents"], int) and line["net_revenue_cents"] >= 0
    assert data["status"] in _enum_values(UsageReportStatus)
    assert isinstance(data["royalty_rate_applied"], (int, float))
    assert isinstance(data["provisional_royalty_cents"], int) and data["provisional_royalty_cents"] >= 0
    assert "final_royalty_cents" in data, "UsageReport must expose final_royalty_cents"


# ── Domain invariants ────────────────────────────────────────────────────────

def assert_campaign_supply_conservation(campaign: dict, allocations: Iterable[dict]) -> None:
    """unallocated_units plus live allocation units equals expected_good_units.

    The allocatable supply pool is fixed at creation; allocating decrements
    ``unallocated_units`` and releasing restores it, so the conserved total
    never drifts across a forward/compensating pair.
    """
    live_units = sum(
        alloc["units"]
        for alloc in allocations
        if alloc.get("status") in (AllocationStatus.RESERVED.value, AllocationStatus.FULFILLED.value)
    )
    assert campaign["unallocated_units"] + live_units == campaign["expected_good_units"], (
        f"supply conservation broken: unallocated {campaign['unallocated_units']} "
        f"+ live {live_units} != expected_good_units {campaign['expected_good_units']}"
    )


def assert_prepayment_ledger_conserved(commitment: dict) -> None:
    """applied + remaining + refunded always equals the original prepayment.

    The prepayment is a three-bucket ledger: cents only ever move remaining ->
    applied or remaining -> refunded, so the sum is invariant across apply and
    release.
    """
    total = (
        commitment["prepayment_applied_cents"]
        + commitment["prepayment_remaining_cents"]
        + commitment["prepayment_refunded_cents"]
    )
    assert total == commitment["prepayment_cents"], (
        f"prepayment ledger broken: {total} != prepayment_cents "
        f"{commitment['prepayment_cents']}"
    )


def assert_standing_demoted_one_step(before: str, after: str) -> None:
    """The breach-watch cascade demotes exactly one rung and never restores."""
    ladder = [StandingTier.STRATEGIC.value, StandingTier.STANDARD.value, StandingTier.PROBATION.value]
    assert before in ladder and after in ladder
    expected = ladder[min(ladder.index(before) + 1, len(ladder) - 1)]
    assert after == expected, f"expected demotion {before} -> {expected}, got {after}"


def assert_optional_instant(value: Optional[str], field: str) -> None:
    """A nullable timestamp field is either null or ISO 8601."""
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} must be ISO 8601 when set"
