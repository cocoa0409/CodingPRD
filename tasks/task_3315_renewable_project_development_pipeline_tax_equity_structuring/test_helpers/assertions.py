"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    DebtFacilityStatus,
    InterconnectionRequestStatus,
    LedgerEntryType,
    MilestoneStatus,
    MilestoneType,
    OfftakeStatus,
    ProcurementOrderStatus,
    ProjectStatus,
    QualificationStatus,
    SafeHarborMethod,
    SiteControlStatus,
    StudyPhase,
    StudyStatus,
    SupplyAgreementStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["technology"] in ("WIND", "SOLAR", "HYBRID")
    assert isinstance(data["target_capacity_mw"], (int, float))
    assert data["resource_class"] in ("A", "B", "C")
    assert data["status"] in [s.value for s in ProjectStatus]
    assert isinstance(data["tax_credit_anchored"], bool)
    assert isinstance(data["total_itc_credits_usd"], (int, float))


def assert_site_control_instrument(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert isinstance(data["parcel_id"], str) and data["parcel_id"]
    assert data["instrument_type"] in ("LAND_OPTION", "EASEMENT")
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert data["status"] in [s.value for s in SiteControlStatus]


def assert_interconnection_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert isinstance(data["cluster_id"], str) and data["cluster_id"]
    assert isinstance(data["requested_capacity_mw"], (int, float))
    assert isinstance(data["queue_position"], int)
    assert data["status"] in [s.value for s in InterconnectionRequestStatus]
    assert isinstance(data["upgrade_allocated"], bool)
    assert isinstance(data["last_upgrade_total_usd"], (int, float))


def assert_interconnection_study(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("request_id", "")), "request_id must be a valid UUID"
    assert data["phase"] in [p.value for p in StudyPhase]
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in [s.value for s in StudyStatus]
    assert isinstance(data["rework_count"], int)


def assert_offtake_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert data["buyer_type"] in ("UTILITY", "CORPORATE")
    assert isinstance(data["base_price_usd_mwh"], (int, float))
    assert isinstance(data["escalator_pct"], (int, float))
    assert isinstance(data["term_years"], int)
    assert data["status"] in [s.value for s in OfftakeStatus]
    assert isinstance(data["counter_count"], int)


def assert_supply_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert data["equipment_type"] in ("TURBINE", "MODULE")
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["total_contract_usd"], (int, float))
    assert data["status"] in [s.value for s in SupplyAgreementStatus]
    assert isinstance(data["amendment_count"], int)


def assert_procurement_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supply_agreement_id", "")), (
        "supply_agreement_id must be a valid UUID"
    )
    assert isinstance(data["order_amount_usd"], (int, float))
    assert data["safe_harbor_method"] in [m.value for m in SafeHarborMethod]
    assert isinstance(data["eligible_cost_basis_usd"], (int, float))
    assert isinstance(data["deposit_paid_usd"], (int, float))
    assert isinstance(data["safe_harbor_qualified"], bool)
    assert data["status"] in [s.value for s in ProcurementOrderStatus]


def assert_construction_milestone(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert data["milestone_type"] in [t.value for t in MilestoneType]
    assert isinstance(data["sequence_no"], int)
    assert data["status"] in [s.value for s in MilestoneStatus]


def assert_tax_credit_qualification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert data["status"] in [s.value for s in QualificationStatus]
    assert isinstance(data["lapse_count"], int)


def assert_tax_equity_partnership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert isinstance(data["investor_name"], str) and data["investor_name"]
    assert isinstance(data["commitment_usd"], (int, float))
    assert isinstance(data["target_irr_pct"], (int, float))
    assert data["investor_pre_flip_share_pct"] == 99.00
    assert data["investor_post_flip_share_pct"] == 5.00
    assert isinstance(data["investor_irr_pct"], (int, float))
    assert isinstance(data["contributed_usd"], (int, float))
    assert isinstance(data["retained_cash_usd"], (int, float))


def assert_ledger_entry(data: dict):
    # Append-only: id + created_at only; updated_at and version must not be
    # required here (the resource has neither).
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_valid_uuid(data.get("partnership_id", "")), "partnership_id must be a valid UUID"
    assert data["entry_type"] in [t.value for t in LedgerEntryType]
    assert isinstance(data["amount_usd"], (int, float))
    assert is_iso8601_timestamp(data.get("period_end_date", ""))


def assert_debt_facility(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert isinstance(data["commitment_usd"], (int, float))
    assert isinstance(data["drawn_usd"], (int, float))
    assert isinstance(data["interest_rate_pct"], (int, float))
    assert isinstance(data["projected_cfads_usd"], (int, float))
    assert data["min_dscr"] == 1.30
    assert data["status"] in [s.value for s in DebtFacilityStatus]
