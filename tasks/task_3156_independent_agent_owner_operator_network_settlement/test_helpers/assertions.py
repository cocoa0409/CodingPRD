"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import PINNED_MAINTENANCE_RESERVE_CENTS


def assert_common_fields(data: dict):
    """Every primary resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_agent(data: dict):
    assert_common_fields(data)
    assert isinstance(data["agent_code"], str) and data["agent_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["home_state"], str) and len(data["home_state"]) == 2
    assert isinstance(data["commission_rate_pct"], (int, float))
    assert 0.0 <= data["commission_rate_pct"] <= 1.0
    assert isinstance(data["territory_codes"], list)
    assert isinstance(data["customer_ownership_days"], int)
    assert data["status"] in [
        "PENDING_ENROLLMENT", "ACTIVE", "SUSPENDED", "TERMINATED",
    ]
    assert isinstance(data["settlement_hold"], bool)
    assert isinstance(data["active_customer_count"], int)
    assert isinstance(data["awarded_load_count"], int)


def assert_capacity_owner(data: dict):
    assert_common_fields(data)
    assert isinstance(data["owner_code"], str) and data["owner_code"]
    assert isinstance(data["revenue_split_pct"], (int, float))
    assert 0.0 <= data["revenue_split_pct"] <= 1.0
    assert isinstance(data["oa_enrolled"], bool)
    assert isinstance(data["escrow_balance_cents"], int)
    assert isinstance(data["maintenance_balance_cents"], int)
    assert isinstance(data["safety_score"], (int, float))
    assert data["status"] in [
        "PENDING_QUALIFICATION", "QUALIFIED", "OUT_OF_SERVICE", "DECERTIFIED",
    ]
    assert data["qualification_posture"] in [
        "QUALIFIED_CLEAR", "QUALIFICATION_RESTRICTED", "QUALIFICATION_FROZEN",
    ]


def assert_capacity_owner_invariants(data: dict):
    """Invariants that must hold after any operation on a BCO."""
    assert data["escrow_balance_cents"] >= 0, "escrow balance has a zero floor"
    assert data["maintenance_balance_cents"] >= 0, "maintenance balance has a zero floor"
    assert data["safety_score"] >= 0, "safety score floors at 0"
    assert data["safety_score"] <= 100, "safety score caps at the base of 100"


def assert_equipment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["capacity_owner_id"])
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert data["equipment_type"] in [
        "TRACTOR", "STRAIGHT_TRUCK", "VAN_TRAILER", "REEFER_TRAILER", "FLATBED_TRAILER",
    ]
    assert 1980 <= data["model_year"] <= 2030
    assert data["status"] in [
        "IN_SERVICE", "PENDING_INSPECTION", "OUT_OF_SERVICE", "RETIRED",
    ]
    assert data["inspection_status"] in ["CURRENT", "DUE", "OVERDUE", "RETIRED"]


def assert_compliance_document(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["capacity_owner_id"])
    assert data["document_type"] in [
        "CDL", "MEDICAL_CARD", "MVR_REPORT", "DRUG_TEST",
        "OA_ENROLLMENT", "LIABILITY_INSURANCE",
    ]
    assert data["status"] in ["VALID", "EXPIRING_SOON", "EXPIRED", "REJECTED"]


def assert_customer_account(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["agent_id"])
    assert isinstance(data["customer_ref"], str) and data["customer_ref"]
    assert data["exclusivity_status"] in ["OWNED_EXCLUSIVE", "OPEN_SHARED", "RELEASED"]
    if data.get("released_reason") is not None:
        assert data["released_reason"] in [
            "NON_SOLICITATION_BREACH", "AGENT_TERMINATED", "CUSTOMER_REQUEST",
        ]


def assert_load(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["agent_id"])
    assert data["status"] in [
        "POSTED", "AWARDED", "COVERED", "IN_TRANSIT", "DELIVERED", "SETTLED", "CANCELLED",
    ]
    assert isinstance(data["board_required"], bool)
    assert data["linehaul_revenue_cents"] > 0
    assert data["fuel_surcharge_cents"] >= 0
    assert data["accessorial_revenue_cents"] >= 0
    assert data["dispatched_miles"] > 0
    assert len(data["origin_state"]) == 2 and len(data["destination_state"]) == 2


def assert_load_offer(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["load_id"])
    assert is_valid_uuid(data["capacity_owner_id"])
    assert data["offered_pay_cents"] > 0
    assert isinstance(data["owner_pay_ceiling_cents"], int)
    assert data["status"] in ["OPEN", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN"]


def assert_trip(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["load_id"])
    assert is_valid_uuid(data["capacity_owner_id"])
    assert is_valid_uuid(data["equipment_id"])
    assert data["status"] in [
        "DISPATCH_PENDING", "EN_ROUTE", "DELIVERED", "COMPLETED", "ABORTED",
    ]
    if data["status"] in ("DELIVERED", "COMPLETED"):
        assert is_iso8601_timestamp(data["delivered_at"])
        assert isinstance(data["on_time"], bool)


def assert_settlement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["trip_id"])
    assert data["settlement_method"] in ["PROVISIONAL", "FINAL"]
    assert data["status"] in [
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "SETTLED", "VOID",
    ]


def assert_settlement_conservation(data: dict):
    """The conserved quantity: the three shares must equal the union base exactly."""
    assert data["settled_total_cents"] == (
        data["agent_share_cents"]
        + data["owner_operator_share_cents"]
        + data["company_share_cents"]
    ), "settled_total_cents must equal the sum of the three shares"
    assert data["settled_total_cents"] == (
        data["linehaul_revenue_allocated_cents"]
        + data["fuel_surcharge_allocated_cents"]
        + data["accessorial_allocated_cents"]
    ), "settled_total_cents must equal linehaul + fuel surcharge + accessorial exactly"


def assert_escrow_transaction(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["capacity_owner_id"])
    assert data["transaction_type"] in [
        "ADVANCE", "ADVANCE_REPAYMENT", "ESCROW_DEPOSIT", "ESCROW_RELEASE",
        "MAINTENANCE_DEPOSIT", "MAINTENANCE_WITHDRAWAL",
        "OA_PREMIUM_DEDUCTION", "INSURANCE_PREMIUM_DEDUCTION",
    ]
    assert data["amount_cents"] > 0, "amount_cents is always a positive magnitude"
    assert data["status"] in ["POSTED", "REVERSED"]


def assert_maintenance_reserve(trip_or_settlement: dict, actual_miles: int):
    """The reserve is ceil(miles / 1000) * 1200."""
    expected = -(-actual_miles // 1000) * 1200
    assert trip_or_settlement["maintenance_reserve_cents"] == expected
    assert expected == PINNED_MAINTENANCE_RESERVE_CENTS or actual_miles != 1237