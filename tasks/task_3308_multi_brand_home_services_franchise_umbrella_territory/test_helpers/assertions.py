"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccountStatus,
    AgreementLifecycleStatus,
    AssignmentKind,
    AuditKind,
    AuditOutcome,
    AuditStatus,
    CertificationLevel,
    FranchiseeStatus,
    LeadStatus,
    ReferralStatus,
    RemediationStatus,
    StandardsStatus,
    StatementStatus,
    TerritoryStatus,
    Trade,
    TransferStatus,
    WorkOrderPriority,
    WorkOrderStatus,
)


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int), (
            f"version must be an integer, got {data.get('version')!r}"
        )


def assert_brand(data: dict):
    _assert_common(data)
    assert isinstance(data["brand_code"], str) and 3 <= len(data["brand_code"]) <= 12
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["trade"] in [t.value for t in Trade]
    assert 0 <= data["royalty_rate"] <= 1
    assert 0 <= data["national_ad_fund_rate"] <= 1
    assert data["min_certification_level"] in [c.value for c in CertificationLevel]
    assert isinstance(data["audit_cycle_months"], int) and data["audit_cycle_months"] >= 1
    assert isinstance(data["cross_brand_fee_table"], dict)
    assert data["status"] in ("ACTIVE",)


def assert_franchisee(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["principal_name"], str) and data["principal_name"]
    assert data["status"] in [s.value for s in FranchiseeStatus]
    assert isinstance(data["shared_services_enrolled"], bool)
    for counter in ("active_brand_count", "active_agreement_count", "allocated_households"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert isinstance(data["lead_cost_balance_cents"], int)
    assert data["standards_score_basis"] in ("AUDIT_BASED", "TRAILING_WINDOW")


def assert_territory(data: dict):
    _assert_common(data)
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert is_valid_uuid(data["brand_id"])
    assert isinstance(data["household_count"], int) and data["household_count"] > 0
    assert isinstance(data["postal_codes"], list)
    assert isinstance(data["protected"], bool)
    assert isinstance(data["expansion_right_households"], int)
    assert data["expansion_right_households"] >= 0
    assert isinstance(data["allocated_households"], int)
    assert data["status"] in [s.value for s in TerritoryStatus]


def assert_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["agreement_number"], str) and data["agreement_number"]
    assert is_valid_uuid(data["franchisee_id"])
    assert is_valid_uuid(data["brand_id"])
    assert is_valid_uuid(data["territory_id"])
    assert isinstance(data["initial_term_months"], int) and data["initial_term_months"] >= 12
    assert data["certification_level"] in [c.value for c in CertificationLevel]
    assert data["lifecycle_status"] in [s.value for s in AgreementLifecycleStatus]
    assert data["standards_status"] in [s.value for s in StandardsStatus]
    assert 0 <= data["effective_royalty_rate"] <= 1
    assert isinstance(data["cumulative_royalty_cents"], int)
    assert isinstance(data["cumulative_referral_net_cents"], int)
    assert isinstance(data["open_remediation_count"], int) and data["open_remediation_count"] >= 0


def assert_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["referral_code"], str) and data["referral_code"]
    assert is_valid_uuid(data["originating_agreement_id"])
    assert is_valid_uuid(data["receiving_agreement_id"])
    assert isinstance(data["estimated_job_value_cents"], int)
    assert isinstance(data["referral_fee_cents"], int)
    assert 0 <= data["referral_fee_rate"] <= 1
    assert data["status"] in [s.value for s in ReferralStatus]


def assert_lead(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["brand_id"])
    assert data["source"] in ("CALL_CENTER", "WEB", "NATIONAL_ACCOUNT")
    assert data["household_income_band"] in ("BAND_1", "BAND_2", "BAND_3", "BAND_4")
    assert isinstance(data["estimated_value_cents"], int)
    assert isinstance(data["lead_cost_cents"], int)
    assert data["status"] in [s.value for s in LeadStatus]


def assert_national_account(data: dict):
    _assert_common(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert data["account_type"] in ("NATIONAL_ACCOUNT", "PROPERTY_MANAGER")
    assert isinstance(data["contracted_brands"], list) and len(data["contracted_brands"]) >= 1
    assert isinstance(data["service_level_hours"], int) and data["service_level_hours"] >= 1
    assert isinstance(data["breach_tolerance"], int) and data["breach_tolerance"] >= 1
    assert isinstance(data["open_breach_count"], int) and data["open_breach_count"] >= 0
    assert isinstance(data["sla_credit_accrued_cents"], int)
    assert isinstance(data["accumulated_revenue_cents"], int)
    assert data["status"] in [s.value for s in AccountStatus]


def assert_work_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["source"] in (
        "NATIONAL_ACCOUNT", "PROPERTY_MANAGER", "CALL_CENTER_LEAD",
        "CROSS_BRAND_REFERRAL", "DIRECT",
    )
    assert data["priority"] in [p.value for p in WorkOrderPriority]
    assert isinstance(data["service_level_hours"], int) and data["service_level_hours"] >= 1
    assert isinstance(data["parts_cents"], int)
    assert isinstance(data["labor_cents"], int)
    assert isinstance(data["revenue_cents"], int)
    assert data["status"] in [s.value for s in WorkOrderStatus]


def assert_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["audit_kind"] in [k.value for k in AuditKind]
    assert 0 <= data["raw_score"] <= 100
    assert isinstance(data["findings_count"], int) and data["findings_count"] >= 0
    assert 0 <= data["critical_findings_count"] <= data["findings_count"]
    assert 0 <= data["weighted_score"] <= 100
    assert data["outcome"] in [o.value for o in AuditOutcome]
    assert data["audit_status"] in [s.value for s in AuditStatus]
    assert data["remediation_status"] in [s.value for s in RemediationStatus]


def assert_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["royalty_cents"], int) and data["royalty_cents"] >= 0
    assert isinstance(data["ad_fund_cents"], int)
    assert isinstance(data["referral_offset_cents"], int)
    assert isinstance(data["net_remittance_cents"], int)
    assert data["accrual_variant"] in ("DRAFT_PROPORTIONAL", "FINAL_NETTED")
    assert data["status"] in [s.value for s in StatementStatus]


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["territory_id"])
    assert is_valid_uuid(data["franchisee_id"])
    assert is_valid_uuid(data["source_agreement_id"])
    assert data["assignment_kind"] in [k.value for k in AssignmentKind]
    assert isinstance(data["active"], bool)
    assert data["active"] == (data["released_on"] is None)


def assert_transfer_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["territory_id"])
    assert is_valid_uuid(data["applicant_franchisee_id"])
    assert data["transfer_kind"] in ("RESALE", "TRANSFER", "TERRITORY_REALLOCATION")
    assert isinstance(data["purchase_price_cents"], int) and data["purchase_price_cents"] >= 0
    assert isinstance(data["target_territory_ids"], list)
    assert isinstance(data["transfer_fee_cents"], int)
    assert data["status"] in [s.value for s in TransferStatus]


# ---- domain invariant checkers ----

def assert_territory_allocation_invariants(territory: dict):
    """PRD 2.6: allocated_households must equal household_count while the
    territory is in AWARDED, ACTIVE or EXPANSION_REQUESTED, and be zero in
    every other status."""
    holding = ("AWARDED", "ACTIVE", "EXPANSION_REQUESTED")
    if territory["status"] in holding:
        assert territory["allocated_households"] == territory["household_count"], (
            f"allocated_households must equal household_count={territory['household_count']} "
            f"while status is {territory['status']}, got {territory['allocated_households']}"
        )
    else:
        assert territory["allocated_households"] == 0, (
            f"allocated_households must be 0 while status is {territory['status']}, "
            f"got {territory['allocated_households']}"
        )


def assert_referral_pair_opposite(originator: dict, receiver: dict):
    """PRD 2.8 / 3.5: across any pair of agreements in the same referral,
    cumulative_referral_net_cents must stay exactly opposite."""
    origin = originator["cumulative_referral_net_cents"]
    receive = receiver["cumulative_referral_net_cents"]
    assert origin + receive == 0, (
        f"the referral pair must be exactly opposite: originator {origin} + "
        f"receiver {receive} != 0"
    )


def assert_work_order_money(work_order: dict):
    """PRD 3.4: revenue_cents is labor_cents plus parts_cents."""
    assert work_order["revenue_cents"] == work_order["labor_cents"] + work_order["parts_cents"], (
        f"revenue_cents must equal labor_cents + parts_cents: "
        f"{work_order['revenue_cents']} != {work_order['labor_cents']} + "
        f"{work_order['parts_cents']}"
    )


def assert_statement_net_position(statement: dict, referral_offset: int):
    """PRD 3.10: net_remittance_cents is royalty_cents + ad_fund_cents minus
    the referral offset, floored at zero after the subtraction."""
    expected = max(0, statement["royalty_cents"] + statement["ad_fund_cents"] - referral_offset)
    assert statement["net_remittance_cents"] == expected, (
        f"net_remittance_cents must be max(0, royalty + ad_fund - offset) = {expected}, "
        f"got {statement['net_remittance_cents']}"
    )