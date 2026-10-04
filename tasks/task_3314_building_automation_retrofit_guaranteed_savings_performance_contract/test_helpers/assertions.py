"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, versioned: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_contract(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "AUDIT", "SCOPED", "EXECUTED", "CONSTRUCTION",
        "PERFORMANCE", "CLOSED", "TERMINATED",
    ]
    assert isinstance(data["guaranteed_annual_savings_cents"], int)
    assert isinstance(data["contract_value_cents"], int)
    assert isinstance(data["guarantee_shortfall_reserve_cents"], int)
    assert isinstance(data["cumulative_verified_savings_cents"], int)


def assert_baseline(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "LOCKED", "RESTATED", "REJECTED",
    ]
    assert isinstance(data["annual_energy_kwh"], int)
    assert isinstance(data["rate_schedule"], list)
    assert isinstance(data["version_tag"], int)


def assert_bundle(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "PROPOSED", "APPROVED", "ACTIVE", "COMPLETE", "WITHDRAWN",
    ]
    assert isinstance(data["subsidy_pool_cents"], int)


def assert_measure(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PROPOSED", "INCLUDED", "INSTALLED", "VERIFIED", "EXCLUDED",
    ]
    assert isinstance(data["installed_cost_cents"], int)
    assert isinstance(data["annual_savings_cents"], int)
    assert isinstance(data["subsidy_draw_cents"], int)


def assert_facility(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "FUNDING", "PAID_OFF", "CANCELLED",
    ]
    assert data["facility_type"] in ["LEASE", "BOND", "THIRD_PARTY"]
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["drawn_cents"], int)


def assert_draw(data: dict):
    _assert_common(data, versioned=False)
    assert "version" not in data, "draws must not carry version"
    assert "updated_at" not in data, "draws must not carry updated_at"
    assert data["status"] in ["REQUESTED", "APPROVED", "RELEASED", "REJECTED"]
    assert isinstance(data["amount_cents"], int)


def assert_phase(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PLANNED", "MOBILIZED", "IN_PROGRESS", "COMPLETE", "SUSPENDED",
    ]
    assert isinstance(data["disruption_budget_hours"], int)
    assert isinstance(data["consumed_disruption_hours"], int)


def assert_disruption(data: dict):
    _assert_common(data, versioned=False)
    assert "version" not in data, "disruption logs must not carry version"
    assert "updated_at" not in data, "disruption logs must not carry updated_at"
    assert isinstance(data["hours"], int)


def assert_report(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "ATTESTED", "RECONCILED", "DISPUTED",
    ]
    assert isinstance(data["period_year"], int)
    assert isinstance(data["actual_energy_kwh"], int)


def assert_adjustment(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED"]
    assert data["reason"] in [
        "FACILITY_EXPANSION", "FACILITY_REDUCTION", "OCCUPANCY_CHANGE",
        "EQUIPMENT_CHANGE", "RATE_CHANGE",
    ]
    assert isinstance(data["kwh_delta"], int)


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "ESCALATED", "RESOLVED", "WITHDRAWN"]
    assert data["filed_by_role"] in ["ESCO", "OWNER"]
    assert isinstance(data["claimed_savings_cents"], int)


def assert_contract_ledger_invariants(contract: dict):
    """Domain invariants that must hold on the contract ledger."""
    assert contract["guarantee_shortfall_reserve_cents"] >= 0, \
        "shortfall reserve is floored at zero"
    assert contract["cumulative_verified_savings_cents"] >= 0
