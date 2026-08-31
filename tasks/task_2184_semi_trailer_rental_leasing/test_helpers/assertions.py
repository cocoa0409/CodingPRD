"""Entity assertions and domain invariant checkers.

Every primary resource carries id / created_at / updated_at / version, except
the immutable shop-event ledger row, which carries id and created_at only.
"""

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AgreementStatus,
    AgreementUnitStatus,
    CertificateStatus,
    ChargebackStatus,
    CreditTier,
    DamageAssessmentStatus,
    MaintenanceEventType,
    ProductLine,
    PurchaseOptionStatus,
    RateCardStatus,
    RelocationOrderStatus,
    TrailerAvailabilityStatus,
    TrailerServiceStatus,
)

_UUID_RE_LEN = 36


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict, entity_name: str = "resource"):
    """id / created_at / updated_at / version, per the common resource properties."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert len(str(data.get("id", ""))) == _UUID_RE_LEN, (
        f"{entity_name}.id must carry no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_branch(data: dict):
    assert_common_fields(data, "Branch")
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert isinstance(data["name"], str)
    assert data["region"] in ["WEST", "CENTRAL", "EAST"]
    assert isinstance(data["yard_capacity"], int) and data["yard_capacity"] >= 1
    assert isinstance(data["peak_season_start_date"], str)
    assert isinstance(data["peak_season_end_date"], str)
    assert data["peak_season_end_date"] >= data["peak_season_start_date"]
    assert 0.0 <= float(data["lease_reserve_pct"]) <= 1.0
    assert isinstance(data["on_hand_count"], int) and data["on_hand_count"] >= 0
    assert isinstance(data["serviceable_available_count"], int)
    assert data["serviceable_available_count"] >= 0
    assert data["serviceable_available_count"] <= data["on_hand_count"], (
        "serviceable_available_count counts a subset of on_hand_count"
    )


def assert_trailer_type(data: dict):
    assert_common_fields(data, "TrailerType")
    assert data["code"] in ["DRY_VAN_53", "REEFER_53", "FLATBED_48", "CHASSIS_40"]
    assert isinstance(data["description"], str)
    assert data["residual_floor_cents"] >= 0
    assert data["dot_inspection_interval_days"] >= 1
    assert data["pm_interval_miles"] >= 1
    assert data["required_physical_damage_limit_cents"] >= 0


def assert_trailer(data: dict):
    assert_common_fields(data, "Trailer")
    assert isinstance(data["unit_number"], str) and len(data["unit_number"]) > 0
    assert is_valid_uuid(data["trailer_type_id"])
    assert is_valid_uuid(data["home_branch_id"])
    assert is_valid_uuid(data["current_branch_id"])
    assert data["availability_status"] in _values(TrailerAvailabilityStatus)
    assert data["service_status"] in _values(TrailerServiceStatus)
    assert isinstance(data["hub_miles"], int) and data["hub_miles"] >= 0
    assert isinstance(data["last_pm_hub_miles"], int)
    assert isinstance(data["last_dot_inspection_date"], str)
    assert isinstance(data["dot_expires_on"], str)
    assert isinstance(data["last_dot_passed"], bool)
    assert isinstance(data["damage_points"], int) and data["damage_points"] >= 0
    assert data["acquisition_cost_cents"] >= 0
    assert isinstance(data["net_book_value_cents"], int)
    assert data["net_book_value_cents"] >= 0


def assert_customer(data: dict):
    assert_common_fields(data, "Customer")
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["dot_number"], str)
    assert data["credit_tier"] in _values(CreditTier)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_chargeback_cents"], int)
    assert data["outstanding_chargeback_cents"] >= 0


def assert_insurance_certificate(data: dict):
    assert_common_fields(data, "InsuranceCertificate")
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["carrier_name"], str)
    assert isinstance(data["policy_number"], str)
    assert data["physical_damage_limit_cents"] >= 0
    assert data["liability_limit_cents"] >= 0
    assert data["expiry_date"] >= data["effective_date"]
    assert data["status"] in _values(CertificateStatus)


def assert_rate_card(data: dict):
    assert_common_fields(data, "RateCard")
    assert is_valid_uuid(data["branch_id"])
    assert is_valid_uuid(data["trailer_type_id"])
    assert data["product"] in _values(ProductLine)
    assert data["daily_rate_cents"] >= 0
    assert data["monthly_rate_cents"] >= 0
    assert 0.0 <= float(data["peak_uplift_pct"]) <= 2.0
    assert data["mileage_included_per_month"] >= 0
    assert data["excess_mileage_rate_cents_per_mile"] >= 0
    assert data["status"] in _values(RateCardStatus)


def assert_agreement(data: dict):
    assert_common_fields(data, "Agreement")
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["branch_id"])
    assert is_valid_uuid(data["trailer_type_id"])
    assert data["product"] in _values(ProductLine)
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert data["end_date"] > data["start_date"], "the contract window is half-open"
    assert data["status"] in _values(AgreementStatus)
    assert data["purchase_option_status"] in _values(PurchaseOptionStatus)
    assert isinstance(data["allocated_unit_count"], int)
    assert data["allocated_unit_count"] >= 0


def assert_agreement_unit(data: dict):
    assert_common_fields(data, "AgreementUnit")
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["trailer_id"])
    assert data["status"] in _values(AgreementUnitStatus)
    assert isinstance(data["planned_start_date"], str)
    assert isinstance(data["planned_end_date"], str)
    assert data["planned_end_date"] > data["planned_start_date"]


def assert_maintenance_event(data: dict):
    """A shop event is an immutable ledger row: id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "MaintenanceEvent.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "MaintenanceEvent.created_at must be ISO 8601"
    )
    assert "version" not in data, (
        "MaintenanceEvent must not carry a version key"
    )
    assert "updated_at" not in data, (
        "MaintenanceEvent must not carry an updated_at key"
    )
    assert is_valid_uuid(data["trailer_id"])
    assert data["event_type"] in _values(MaintenanceEventType)
    assert isinstance(data["performed_on"], str)
    assert data["hub_miles_at_event"] >= 0
    assert data["cost_cents"] >= 0
    assert isinstance(data["inspector_user_id"], str)


def assert_damage_assessment(data: dict):
    assert_common_fields(data, "DamageAssessment")
    assert is_valid_uuid(data["agreement_unit_id"])
    assert is_valid_uuid(data["trailer_id"])
    assert isinstance(data["assessor_user_id"], str)
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1
    for item in data["line_items"]:
        assert item["severity"] in ["MINOR", "MODERATE", "MAJOR"]
        assert item["quantity"] >= 1
        assert item["unit_cost_cents"] >= 0
    assert data["status"] in _values(DamageAssessmentStatus)


def assert_chargeback(data: dict):
    assert_common_fields(data, "Chargeback")
    assert is_valid_uuid(data["damage_assessment_id"])
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in _values(ChargebackStatus)


def assert_relocation_order(data: dict):
    assert_common_fields(data, "RelocationOrder")
    assert is_valid_uuid(data["trailer_id"])
    assert is_valid_uuid(data["origin_branch_id"])
    assert is_valid_uuid(data["destination_branch_id"])
    assert data["status"] in _values(RelocationOrderStatus)
    assert data["planned_arrive_date"] >= data["planned_depart_date"]
    assert data["planned_miles"] >= 0
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["estimated_cost_cents"] >= 0


# ------------------------------------------------------------------ helpers
def assert_money_is_whole_cents(value, field_name: str = "amount"):
    """Every money field is an integer count of cents; there are no fractional cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be an integer count of cents, got {value!r}"
    )


def assert_fleet_position_identity(branches, trailers, expected_total: int):
    """The sum of on_hand_count over all yards, plus in-transit units, plus units
    out with a customer, equals the count of units that are neither RETIRED nor SOLD."""
    on_hand = sum(b["on_hand_count"] for b in branches)
    in_transit = sum(
        1 for t in trailers if t["availability_status"] == "IN_TRANSIT"
    )
    with_customer = sum(
        1 for t in trailers if t["availability_status"] in ("ON_RENT", "ON_LEASE")
    )
    live = sum(
        1 for t in trailers if t["availability_status"] not in ("RETIRED", "SOLD")
    )
    total = on_hand + in_transit + with_customer
    assert total == live == expected_total, (
        f"fleet position must conserve: on_hand={on_hand} + in_transit={in_transit} "
        f"+ with_customer={with_customer} = {total}, live units = {live}, "
        f"expected {expected_total}"
    )
    return total
