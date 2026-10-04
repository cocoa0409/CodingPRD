"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_project(data):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["market_application"] in (
        "ENERGY_ARBITRAGE",
        "FREQUENCY_REGULATION",
        "CAPACITY_FIRMING",
    )
    assert data["duty_cycle_profile"] in (
        "ONE_CYCLE_DAILY",
        "TWO_CYCLES_DAILY",
        "CONTINUOUS",
    )
    assert data["sizing_status"] in ("VALID", "INVALID")


def assert_esa(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["status"] in ("DRAFT", "EXECUTED", "COMPLETED", "TERMINATED")
    for field in ("accrued_ld_cents", "waived_ld_cents", "net_ld_due_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_milestone(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data["esa_id"])
    assert data["kind"] in ("DELIVERY", "COMMISSIONING")
    assert data["status"] in ("SCHEDULED", "ACHIEVED", "MISSED", "CANCELLED")
    assert isinstance(data["days_late"], int)
    assert isinstance(data["ld_applied_cents"], int)
    assert isinstance(data["ld_waived_cents"], int)


def assert_permit(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["permit_type"] in (
        "THERMAL_RUNAWAY_PLAN",
        "FIRE_CODE",
        "LOCAL_APPROVAL",
    )
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_performance_test(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["test_type"] in ("CAPACITY_TEST", "RTE_TEST")
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED", "CANCELLED")
    assert data["measurement_basis"] in ("NAMEPLATE", "POI")


def assert_augmentation(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["origin"] in ("MANUAL", "AUTO")
    assert data["status"] in ("PLANNED", "EXECUTED", "CANCELLED")


def assert_service_agreement(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data["credit_pool_cents"], int)
    assert isinstance(data["credit_drawn_cents"], int)


def assert_spare_part_order(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data["service_agreement_id"])
    assert data["status"] in (
        "ORDERED",
        "SHIPPED",
        "DELIVERED",
        "INSTALLED",
        "CANCELLED",
    )
    assert isinstance(data["covered_by_credit"], bool)
    assert isinstance(data["part_cost_cents"], int)


def assert_warranty_claim(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data["esa_id"])
    assert data["defect_type"] in (
        "CELL_DEFECT",
        "CAPACITY_SHORTFALL",
        "RTE_SHORTFALL",
        "BMS_FAULT",
    )
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "APPROVED",
        "REJECTED",
        "FULFILLED",
    )


def assert_bid_session(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data["project_id"])
    assert data["market"] in ("DAY_AHEAD", "REAL_TIME")
    assert data["status"] in ("OPEN", "CLEARED", "SETTLED", "CANCELLED")
    assert isinstance(data["revenue_cents"], int)


def assert_ld_ledger_invariant(esa):
    """PRD §3.3: net_ld_due_cents == accrued_ld_cents - waived_ld_cents."""
    assert (
        esa["net_ld_due_cents"] == esa["accrued_ld_cents"] - esa["waived_ld_cents"]
    ), (
        "LD ledger invariant violated: net {net} != accrued {acc} - waived {w}".format(
            net=esa["net_ld_due_cents"],
            acc=esa["accrued_ld_cents"],
            w=esa["waived_ld_cents"],
        )
    )


def assert_credit_pool_invariant(ltsa):
    """PRD §3.6: pool equals drawn plus what remains available."""
    available = ltsa["credit_pool_cents"] - ltsa["credit_drawn_cents"]
    assert available >= 0, (
        "credit pool violated: drawn {d} exceeds pool {p}".format(
            d=ltsa["credit_drawn_cents"], p=ltsa["credit_pool_cents"]
        )
    )
