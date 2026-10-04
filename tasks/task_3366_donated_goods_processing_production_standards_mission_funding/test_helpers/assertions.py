"""Entity assertions and domain invariant checkers (PRD sections 2.2, 2.5)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_full(data: dict, label: str):
    """Fields carried by full-weight resources (PRD 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an int"


def _assert_common_light(data: dict, label: str):
    """Lightweight resources carry only id and created_at (PRD 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"


def assert_member_org(data: dict):
    _assert_common_full(data, "MemberOrg")
    assert data["brand_license_status"] in ("ACTIVE", "SUSPENDED")
    assert data["costing_method"] in ("STANDARD", "ACTUAL")
    assert data["margin_health"] in ("HEALTHY", "LOW")
    assert isinstance(data["retail_margin_pool_cents"], int)
    assert isinstance(data["reserved_cents"], int)
    assert isinstance(data["contract_revenue_cents"], int)
    assert isinstance(data["diversion_rate_bps"], int)
    assert isinstance(data["diversion_compliant"], bool)


def assert_donation(data: dict):
    _assert_common_full(data, "Donation")
    assert data["status"] in ("RECEIVED", "SORTED")
    assert isinstance(data["item_count_declared"], int)


def assert_donated_item(data: dict):
    _assert_common_full(data, "DonatedItem")
    assert data["status"] in ("SORTED", "ON_FLOOR", "SOLD", "SALVAGED")
    assert data["category"] in ("TEXTILES", "HOUSEWARES", "MEDIA", "FURNITURE", "EWASTE")
    assert data["condition_grade"] in ("A", "B", "C", "UNSALABLE")


def assert_production_standard(data: dict):
    _assert_common_full(data, "ProductionStandard")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert data["category"] in ("TEXTILES", "HOUSEWARES", "MEDIA", "FURNITURE", "EWASTE")


def assert_processing_run(data: dict):
    _assert_common_full(data, "ProcessingRun")
    assert data["status"] in ("OPEN", "CLOSED")


def assert_salvage_lot(data: dict):
    _assert_common_full(data, "SalvageLot")
    assert data["status"] in ("OPEN", "SOLD")
    assert data["channel"] in ("TEXTILE_BALE", "EWASTE", "OUTLET_BIN")


def assert_mission_program(data: dict):
    _assert_common_full(data, "MissionProgram")
    assert data["program_type"] in ("JOB_TRAINING", "PLACEMENT", "SUPPORT")


def assert_funding_allocation(data: dict):
    _assert_common_full(data, "FundingAllocation")
    assert data["status"] in ("PENDING", "APPROVED", "DISBURSED", "CANCELLED")


def assert_workforce_contract(data: dict):
    _assert_common_full(data, "WorkforceContract")
    assert data["status"] in ("ACTIVE", "UNDER_REVIEW", "CLOSED")
    assert data["compliance_posture"] in ("COMPLIANT", "AT_RISK", "BREACH")


def assert_contract_milestone(data: dict):
    _assert_common_full(data, "ContractMilestone")
    assert data["status"] in ("PENDING", "ATTESTED", "MISSED")


def assert_territory(data: dict):
    _assert_common_light(data, "Territory")


def assert_donation_site(data: dict):
    _assert_common_light(data, "DonationSite")
    assert data["site_type"] in ("ADC", "STORE_DROP")


def assert_disposal_ticket(data: dict):
    _assert_common_light(data, "DisposalTicket")
    assert data["material"] in ("MIXED_UNSALABLE", "HAZARD", "FURNITURE")


def assert_org_margin_invariants(org: dict):
    """Ledger invariants that must hold after any operation (PRD 2.8)."""
    available = org["retail_margin_pool_cents"] - org["reserved_cents"]
    assert isinstance(available, int)
    expected_health = (
        "HEALTHY"
        if org["retail_margin_pool_cents"] >= org["reserve_floor_cents"]
        else "LOW"
    )
    assert org["margin_health"] == expected_health, (
        f"margin_health {org['margin_health']} inconsistent with pool "
        f"{org['retail_margin_pool_cents']} vs floor {org['reserve_floor_cents']}"
    )


def assert_org_diversion_invariants(org: dict):
    """Diversion accounting must be internally consistent (PRD 2.9)."""
    diverted = org["total_diverted_lbs"]
    disposed = org["total_disposed_lbs"]
    if diverted + disposed == 0:
        expected_rate = 10000
    else:
        expected_rate = int(diverted * 10000 // (diverted + disposed))
    assert org["diversion_rate_bps"] == expected_rate, (
        f"diversion_rate_bps {org['diversion_rate_bps']} != floor-derived "
        f"{expected_rate} from {diverted}/{disposed}"
    )
    assert org["diversion_compliant"] == (
        org["diversion_rate_bps"] >= org["diversion_floor_bps"]
    )
