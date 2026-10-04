"""Entity assertions and domain invariant checkers.

assert_<entity>(data) validates the full serialized shape of one resource:
PRD-exact field names, the four common properties of PRD §2.5 (id,
created_at, updated_at, version), and enum membership for status fields.
Nullable system fields are checked for type only when present-and-not-null.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    Category,
    ClaimStatus,
    ClaimType,
    ConfigurationStatus,
    DealerStatus,
    FabricGrade,
    InstallStatus,
    LifecycleStatus,
    LogisticsStatus,
    ModuleType,
    OrderStatus,
    PlantCode,
    PunchSeverity,
    PunchStatus,
    WindowStatus,
)


def _assert_common(data: dict, entity: str):
    """PRD §2.5: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def _assert_optional_ts(data: dict, field: str, entity: str):
    if data.get(field) is not None:
        assert is_iso8601_timestamp(data[field]), (
            f"{entity}.{field} must be ISO 8601 when present"
        )


def _assert_optional_date(data: dict, field: str, entity: str):
    value = data.get(field)
    if value is not None:
        assert isinstance(value, str) and len(value) == 10, (
            f"{entity}.{field} must be an ISO YYYY-MM-DD date when present"
        )


def _assert_optional_int(data: dict, field: str, entity: str):
    value = data.get(field)
    if value is not None:
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{entity}.{field} must be an integer when present"
        )


def assert_dealer(data: dict):
    _assert_common(data, "Dealer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["territory_codes"], list) and data["territory_codes"]
    for code in data["territory_codes"]:
        assert isinstance(code, str) and len(code) == 2 and code.isupper()
    assert isinstance(data["service_capability_level"], int)
    assert 1 <= data["service_capability_level"] <= 5
    assert isinstance(data["showroom_compliant"], bool)
    assert data["status"] in [s.value for s in DealerStatus]
    _assert_optional_ts(data, "suspended_at", "Dealer")


def assert_end_user(data: dict):
    _assert_common(data, "EndUser")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["industry"], str) and data["industry"]


def assert_volume_agreement(data: dict):
    _assert_common(data, "VolumeAgreement")
    assert is_valid_uuid(data.get("end_user_id", ""))
    _assert_optional_date(data, "effective_start", "VolumeAgreement")
    _assert_optional_date(data, "effective_end", "VolumeAgreement")
    for tier in ("tier1_discount_pct", "tier2_discount_pct", "tier3_discount_pct"):
        value = data[tier]
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        assert 0 <= value < 1, f"VolumeAgreement.{tier} must be in [0, 1)"
    assert data["status"] in [s.value for s in AgreementStatus]
    assert isinstance(data["cumulative_volume_cents"], int)
    assert data["cumulative_volume_cents"] >= 0
    assert data["current_tier"] in (1, 2, 3)
    _assert_optional_ts(data, "activated_at", "VolumeAgreement")


def assert_product_family(data: dict):
    _assert_common(data, "ProductFamily")
    assert isinstance(data["family_code"], str) and data["family_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in [c.value for c in Category]
    assert isinstance(data["base_lead_time_days"], int)
    assert 1 <= data["base_lead_time_days"] <= 365
    assert data["lifecycle_status"] in [s.value for s in LifecycleStatus]
    _assert_optional_date(data, "last_order_date", "ProductFamily")
    _assert_optional_date(data, "discontinued_at", "ProductFamily")
    _assert_optional_date(data, "parts_support_until", "ProductFamily")


def assert_configuration(data: dict):
    _assert_common(data, "ConfigurationSpec")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["modules"], list) and len(data["modules"]) >= 1
    for entry in data["modules"]:
        assert entry["module_type"] in [m.value for m in ModuleType]
        if entry["fabric_grade"] is not None:
            assert entry["fabric_grade"] in [g.value for g in FabricGrade]
        assert isinstance(entry["qty"], int) and entry["qty"] >= 1
    assert data["status"] in [s.value for s in ConfigurationStatus]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    _assert_optional_int(data, "total_units", "ConfigurationSpec")
    _assert_optional_int(data, "list_total_cents", "ConfigurationSpec")
    _assert_optional_int(data, "max_lead_time_days", "ConfigurationSpec")
    _assert_optional_ts(data, "locked_at", "ConfigurationSpec")


def assert_project_order(data: dict):
    _assert_common(data, "ProjectOrder")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert is_valid_uuid(data.get("volume_agreement_id", ""))
    assert is_valid_uuid(data.get("configuration_id", ""))
    _assert_optional_int(data, "configuration_revision", "ProjectOrder")
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    _assert_optional_date(data, "requested_install_date", "ProjectOrder")
    assert data["status"] in [s.value for s in OrderStatus]
    for field in (
        "pre_discount_total_cents",
        "provisional_tier",
        "provisional_total_cents",
        "final_tier",
        "final_total_cents",
    ):
        _assert_optional_int(data, field, "ProjectOrder")
    _assert_optional_ts(data, "submitted_at", "ProjectOrder")
    _assert_optional_ts(data, "acknowledged_at", "ProjectOrder")
    _assert_optional_ts(data, "cancelled_at", "ProjectOrder")
    if data.get("cancel_reason") is not None:
        assert isinstance(data["cancel_reason"], str)


def assert_installation_phase(data: dict):
    _assert_common(data, "InstallationPhase")
    assert is_valid_uuid(data.get("project_order_id", ""))
    assert isinstance(data["floor_number"], int) and data["floor_number"] >= 1
    assert isinstance(data["phase_sequence"], int) and data["phase_sequence"] >= 1
    assert isinstance(data["building_zone_id"], str) and data["building_zone_id"]
    assert isinstance(data["planned_units"], int) and data["planned_units"] >= 1
    assert data["logistics_status"] in [s.value for s in LogisticsStatus]
    assert data["install_status"] in [s.value for s in InstallStatus]
    if data.get("plant_code") is not None:
        assert data["plant_code"] in [p.value for p in PlantCode]
    _assert_optional_date(data, "production_date", "InstallationPhase")
    _assert_optional_ts(data, "delivered_at", "InstallationPhase")
    _assert_optional_ts(data, "install_started_at", "InstallationPhase")
    _assert_optional_date(data, "actual_install_complete_date", "InstallationPhase")


def assert_install_window(data: dict):
    _assert_common(data, "InstallWindow")
    assert is_valid_uuid(data.get("installation_phase_id", ""))
    assert isinstance(data["building_zone_id"], str) and data["building_zone_id"]
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["union_required"], bool)
    assert isinstance(data["elevator_required"], bool)
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1
    assert data["status"] in [s.value for s in WindowStatus]


def assert_punch_ticket(data: dict):
    _assert_common(data, "PunchTicket")
    assert is_valid_uuid(data.get("installation_phase_id", ""))
    assert data["severity"] in [s.value for s in PunchSeverity]
    assert isinstance(data["description"], str)
    assert isinstance(data["requires_part"], bool)
    if data.get("part_number") is not None:
        assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["status"] in [s.value for s in PunchStatus]
    if data.get("resolution_note") is not None:
        assert isinstance(data["resolution_note"], str)
    assert isinstance(data["escalated"], bool)


def assert_warranty_claim(data: dict):
    _assert_common(data, "WarrantyClaim")
    assert is_valid_uuid(data.get("project_order_id", ""))
    assert is_valid_uuid(data.get("installation_phase_id", ""))
    if data.get("punch_ticket_id") is not None:
        assert is_valid_uuid(data["punch_ticket_id"])
    assert data["claim_type"] in [c.value for c in ClaimType]
    if data.get("part_number") is not None:
        assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["description"], str)
    assert data["status"] in [s.value for s in ClaimStatus]
    _assert_optional_date(data, "filed_date", "WarrantyClaim")
    if data.get("review_note") is not None:
        assert isinstance(data["review_note"], str)
    _assert_optional_ts(data, "reviewed_at", "WarrantyClaim")


def assert_agreement_volume_invariant(agreement: dict, orders: list):
    """PRD §3.2 ledger rule: cumulative_volume_cents equals the sum of
    pre_discount_total_cents over this agreement's orders in ACKNOWLEDGED or
    CLOSED, and current_tier follows the 25000000 / 75000000 boundaries."""
    from .constants import TIER2_MIN_CENTS, TIER3_MIN_CENTS

    counted = [
        o for o in orders if o["status"] in ("ACKNOWLEDGED", "CLOSED")
    ]
    expected = sum(o["pre_discount_total_cents"] for o in counted)
    assert agreement["cumulative_volume_cents"] == expected, (
        f"cumulative_volume_cents {agreement['cumulative_volume_cents']} "
        f"!= sum of ACKNOWLEDGED/CLOSED pre-discount totals {expected}"
    )
    volume = agreement["cumulative_volume_cents"]
    expected_tier = (
        1 if volume < TIER2_MIN_CENTS
        else 2 if volume < TIER3_MIN_CENTS
        else 3
    )
    assert agreement["current_tier"] == expected_tier
