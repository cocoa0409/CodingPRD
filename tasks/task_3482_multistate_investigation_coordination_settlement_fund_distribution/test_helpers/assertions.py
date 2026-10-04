"""Entity assertions and domain invariant checkers.

Each assert_* checks the fields PRD §2.5 guarantees on every resource
(id, created_at, updated_at, version) plus the entity's own declared fields
and enum memberships. Nullable system fields are type-checked only when
present and non-null, so a fresh resource passes before its milestones.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AllocationBasis,
    AllocationLineStatus,
    AppropriationRule,
    CiaStatus,
    CiaTier,
    ClaimantStatus,
    CommitteeRole,
    DemandStatus,
    DisbursementStatus,
    FindingOutcome,
    FundStatus,
    InvestigationPhase,
    MonitoringPeriodStatus,
    ParticipationStatus,
    ResponseStatus,
    SettlementTermStatus,
    SignOnDecision,
    SignOnStatus,
    UseCode,
)


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an int"


def _assert_optional_ts(data: dict, field: str, label: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{label}.{field} must be null or ISO 8601, got {value!r}"
    )


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def assert_state_office(data: dict):
    _assert_common(data, "StateOffice")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["population"], int)
    assert isinstance(data["harm_measure_cents"], int)
    assert data["appropriation_rule"] in _enum_values(AppropriationRule)


def assert_investigation(data: dict):
    _assert_common(data, "Investigation")
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["target_name"], str) and data["target_name"]
    assert isinstance(data["summary"], str)
    assert data["phase"] in _enum_values(InvestigationPhase)
    _assert_optional_ts(data, "opened_at", "Investigation")
    _assert_optional_ts(data, "settled_at", "Investigation")
    assert data.get("active_settlement_id") is None or isinstance(
        data["active_settlement_id"], str
    )


def assert_participation(data: dict):
    _assert_common(data, "Participation")
    assert is_valid_uuid(data.get("investigation_id", ""))
    assert is_valid_uuid(data.get("state_office_id", ""))
    assert data["status"] in _enum_values(ParticipationStatus)
    assert data["cia_status"] in _enum_values(CiaStatus)
    assert data["committee_role"] in _enum_values(CommitteeRole)
    assert data.get("cia_tier") is None or data["cia_tier"] in _enum_values(CiaTier)
    assert is_iso8601_timestamp(data.get("invited_at", ""))
    _assert_optional_ts(data, "cia_executed_at", "Participation")
    _assert_optional_ts(data, "withdrawn_at", "Participation")


def assert_demand(data: dict):
    _assert_common(data, "Demand")
    assert is_valid_uuid(data.get("participation_id", ""))
    assert isinstance(data["scope_text"], str) and data["scope_text"]
    assert data["status"] in _enum_values(DemandStatus)
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    _assert_optional_ts(data, "consolidated_at", "Demand")
    assert data.get("consolidated_response_id") is None or isinstance(
        data["consolidated_response_id"], str
    )


def assert_consolidated_response(data: dict):
    _assert_common(data, "ConsolidatedResponse")
    assert is_valid_uuid(data.get("investigation_id", ""))
    assert isinstance(data["demand_ids"], list) and len(data["demand_ids"]) >= 1
    assert isinstance(data["coverage_summary"], str)
    assert data["status"] in _enum_values(ResponseStatus)
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    _assert_optional_ts(data, "accepted_at", "ConsolidatedResponse")
    _assert_optional_ts(data, "fulfilled_at", "ConsolidatedResponse")


def assert_sign_on_entry(entry: dict):
    assert is_valid_uuid(entry.get("state_office_id", ""))
    assert isinstance(entry["state_code"], str) and entry["state_code"]
    assert entry["decision"] in _enum_values(SignOnDecision)
    assert entry["status"] in _enum_values(SignOnStatus)
    assert is_iso8601_timestamp(entry.get("decided_at", ""))


def assert_settlement(data: dict):
    _assert_common(data, "Settlement")
    assert is_valid_uuid(data.get("investigation_id", ""))
    assert isinstance(data["monetary_total_cents"], int)
    assert isinstance(data["restitution_reserve_cents"], int)
    assert data["allocation_basis"] in _enum_values(AllocationBasis)
    assert isinstance(data["injunctive_terms"], list) and len(data["injunctive_terms"]) >= 1
    assert data["term_status"] in _enum_values(SettlementTermStatus)
    assert data["fund_status"] in _enum_values(FundStatus)
    assert isinstance(data["negotiation_round"], int)
    assert data.get("counter_total_cents") is None or isinstance(
        data["counter_total_cents"], int
    )
    _assert_optional_ts(data, "sign_on_opened_at", "Settlement")
    _assert_optional_ts(data, "sign_on_deadline", "Settlement")
    _assert_optional_ts(data, "executed_at", "Settlement")
    assert isinstance(data.get("sign_ons", []), list)
    for entry in data.get("sign_ons", []):
        assert_sign_on_entry(entry)
    assert isinstance(data["compliance_hold"], bool)
    assert isinstance(data["deposited_cents"], int)
    assert isinstance(data["released_cents"], int)
    assert isinstance(data["reverted_cents"], int)
    assert isinstance(data["restitution_reserve_balance_cents"], int)
    assert isinstance(data["restitution_computed"], bool)
    assert data.get("restitution_remainder_cents") is None or isinstance(
        data["restitution_remainder_cents"], int
    )
    assert data.get("distributable_cents") is None or isinstance(
        data["distributable_cents"], int
    )
    assert data.get("lead_cost_cents") is None or isinstance(
        data["lead_cost_cents"], int
    )


def assert_allocation_line(data: dict):
    _assert_common(data, "AllocationLine")
    assert is_valid_uuid(data.get("settlement_id", ""))
    assert is_valid_uuid(data.get("state_office_id", ""))
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["basis_value_snapshot"], int)
    assert isinstance(data["weight_bps"], int)
    assert isinstance(data["share_cents"], int)
    assert isinstance(data["lead_bonus_cents"], int)
    assert isinstance(data["gross_share_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["reverted_cents"], int)
    assert isinstance(data["remaining_cents"], int)
    assert data["status"] in _enum_values(AllocationLineStatus)


def assert_disbursement(data: dict):
    _assert_common(data, "Disbursement")
    assert is_valid_uuid(data.get("allocation_line_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["use_code"] in _enum_values(UseCode)
    assert data["status"] in _enum_values(DisbursementStatus)
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    _assert_optional_ts(data, "certified_at", "Disbursement")
    _assert_optional_ts(data, "released_at", "Disbursement")


def assert_claimant(data: dict):
    _assert_common(data, "Claimant")
    assert is_valid_uuid(data.get("settlement_id", ""))
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["contact_ref"], str) and data["contact_ref"]
    assert isinstance(data["claimed_loss_cents"], int) and data["claimed_loss_cents"] > 0
    assert data.get("validated_loss_cents") is None or isinstance(
        data["validated_loss_cents"], int
    )
    assert data.get("estimated_payout_cents") is None or isinstance(
        data["estimated_payout_cents"], int
    )
    assert data.get("payout_cents") is None or isinstance(data["payout_cents"], int)
    assert data["status"] in _enum_values(ClaimantStatus)


def assert_monitoring_period(data: dict):
    _assert_common(data, "MonitoringPeriod")
    assert is_valid_uuid(data.get("settlement_id", ""))
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data.get("findings", []), list)
    for finding in data.get("findings", []):
        assert isinstance(finding["term_index"], int)
        assert finding["outcome"] in _enum_values(FindingOutcome)
        assert is_iso8601_timestamp(finding.get("filed_at", ""))
    assert isinstance(data["breach_count"], int)
    assert data["status"] in _enum_values(MonitoringPeriodStatus)
    _assert_optional_ts(data, "closed_at", "MonitoringPeriod")


# ── Domain invariants (PRD §3.4, §2.6) ────────────────────────────────────
def assert_line_gross_invariant(line: dict):
    """Every allocation line keeps disbursed + reverted + remaining == gross."""
    total = line["disbursed_cents"] + line["reverted_cents"] + line["remaining_cents"]
    assert total == line["gross_share_cents"], (
        f"gross-share invariant broken: {line['disbursed_cents']} + "
        f"{line['reverted_cents']} + {line['remaining_cents']} != "
        f"{line['gross_share_cents']}"
    )


def assert_weights_sum_to_total(lines: list, total_bps: int = 10000):
    """The weights of one settlement's allocation lines sum to exactly 10000."""
    assert sum(line["weight_bps"] for line in lines) == total_bps, (
        f"line weights must sum to {total_bps} bps, got "
        f"{sum(line['weight_bps'] for line in lines)}"
    )
