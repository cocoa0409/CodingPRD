"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` checks the common system-managed fields (PRD section
2.11: UUID id, ISO 8601 created_at/updated_at, integer version >= 1) plus the
presence, type, and enum membership of every entity field the PRD declares.
None of these functions pin business values; fixtures and tests own those.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ConnectivityPosture,
    CropType,
    GranteeType,
    GrantStatus,
    LicenseStatus,
    LicenseType,
    DeliveryStatus,
    ClaimStatus,
    FeatureCode,
    FieldStatus,
    LifecycleStatus,
    ModemStatus,
    OrgStatus,
    DealerStatus,
    PackageStatus,
    PlanStatus,
    PartnerStatus,
    PrescriptionStatus,
    ProrationMethod,
    PlanTier,
    TicketStatus,
    TicketType,
    TechnicianKind,
    DiagnosticDetailLevel,
    SessionStatus,
    SessionCloseReason,
    UsagePosture,
)


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


def _assert_common(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID: %r" % data.get("id")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601: %r" % data.get("created_at")
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601: %r" % data.get("updated_at")
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer >= 1: %r" % data.get("version")
    )


def _assert_nullable_timestamp(data, field):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        "%s must be null or ISO 8601: %r" % (field, value)
    )


def assert_organization(data):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["right_to_repair_enabled"], bool)
    assert isinstance(data["independent_session_max_minutes"], int)
    assert data["status"] in _enum_values(OrgStatus)


def assert_dealer(data):
    _assert_common(data)
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["service_tier"] in ("STANDARD", "PREMIUM")
    assert data["status"] in _enum_values(DealerStatus)
    assert isinstance(data["warranty_reserve_cents"], int)
    assert isinstance(data["warranty_paid_cents"], int)


def assert_machine(data):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert is_valid_uuid(data["selling_dealer_id"])
    assert isinstance(data["manufacture_date"], str) and data["manufacture_date"]
    assert isinstance(data["modem_imei"], str) and data["modem_imei"]
    assert data["modem_status"] in _enum_values(ModemStatus)
    assert isinstance(data["provisioning_attempts"], int)
    assert data["provisioning_attempts"] >= 0
    assert data["modem_firmware_version"] is None or isinstance(
        data["modem_firmware_version"], str
    )
    assert data["lifecycle_status"] in _enum_values(LifecycleStatus)
    assert data["connectivity_posture"] in _enum_values(ConnectivityPosture)
    assert isinstance(data["active_license_count"], int)
    assert data["active_license_count"] >= 0
    assert data["activating_dealer_id"] is None or isinstance(
        data["activating_dealer_id"], str
    )
    _assert_nullable_timestamp(data, "activated_at")


def assert_data_plan(data):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["machine_id"])
    assert data["tier"] in _enum_values(PlanTier)
    assert data["proration_method"] in _enum_values(ProrationMethod)
    assert data["status"] in _enum_values(PlanStatus)
    assert isinstance(data["monthly_price_cents"], int)
    assert isinstance(data["used_mb"], (int, float))
    assert data["usage_posture"] in _enum_values(UsagePosture)
    assert data["cycle_anchor_day"] is None or isinstance(data["cycle_anchor_day"], int)
    assert data["cycle_start_date"] is None or isinstance(data["cycle_start_date"], str)
    assert data["last_proration_charge_cents"] is None or isinstance(
        data["last_proration_charge_cents"], int
    )


def assert_field_boundary(data):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["season_year"], int)
    assert isinstance(data["area_hectares"], (int, float))
    assert data["status"] in _enum_values(FieldStatus)


def assert_prescription(data):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["field_boundary_id"])
    assert is_valid_uuid(data["machine_id"])
    assert data["crop_type"] in _enum_values(CropType)
    assert isinstance(data["zones"], list) and len(data["zones"]) >= 1
    for zone in data["zones"]:
        assert isinstance(zone["zone_id"], str) and zone["zone_id"]
        assert isinstance(zone["rate_l_per_ha"], (int, float))
        assert isinstance(zone["area_ha"], (int, float))
    _assert_nullable_timestamp(data, "valid_from")
    _assert_nullable_timestamp(data, "valid_until")
    assert data["status"] in _enum_values(PrescriptionStatus)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["total_product_liters"] is None or isinstance(
        data["total_product_liters"], (int, float)
    )
    assert data["weighted_avg_rate_l_per_ha"] is None or isinstance(
        data["weighted_avg_rate_l_per_ha"], (int, float)
    )
    assert data["superseded_by_id"] is None or is_valid_uuid(data["superseded_by_id"])
    assert data["applied_total_liters"] is None or isinstance(
        data["applied_total_liters"], (int, float)
    )
    assert data["applied_coverage_ha"] is None or isinstance(
        data["applied_coverage_ha"], (int, float)
    )
    _assert_nullable_timestamp(data, "applied_at")


def assert_data_share_grant(data):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert data["grantee_type"] in _enum_values(GranteeType)
    assert isinstance(data["grantee_ref_id"], str) and data["grantee_ref_id"]
    assert isinstance(data["scopes"], list) and len(data["scopes"]) >= 1
    for scope in data["scopes"]:
        assert scope in ("TELEMATICS", "AGRONOMIC", "DIAGNOSTICS")
    _assert_nullable_timestamp(data, "valid_from")
    _assert_nullable_timestamp(data, "valid_until")
    assert data["status"] in _enum_values(GrantStatus)


def assert_consent_ticket(data):
    _assert_common(data)
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["machine_id"])
    assert data["ticket_type"] in _enum_values(TicketType)
    assert isinstance(data["requester_ref_id"], str) and data["requester_ref_id"]
    assert data["status"] in _enum_values(TicketStatus)
    _assert_nullable_timestamp(data, "expires_at")
    _assert_nullable_timestamp(data, "granted_at")
    assert data["bound_session_id"] is None or is_valid_uuid(data["bound_session_id"])
    assert data["bound_delivery_id"] is None or is_valid_uuid(data["bound_delivery_id"])


def assert_diagnostic_session(data):
    _assert_common(data)
    assert is_valid_uuid(data["machine_id"])
    assert is_valid_uuid(data["organization_id"])
    assert data["dealer_id"] is None or is_valid_uuid(data["dealer_id"])
    assert is_valid_uuid(data["consent_ticket_id"])
    assert data["technician_kind"] in _enum_values(TechnicianKind)
    assert data["diagnostic_detail_level"] in _enum_values(DiagnosticDetailLevel)
    assert data["status"] in _enum_values(SessionStatus)
    _assert_nullable_timestamp(data, "opened_at")
    _assert_nullable_timestamp(data, "closed_at")
    assert data["closed_reason"] is None or data["closed_reason"] in _enum_values(
        SessionCloseReason
    )
    assert data["fault_found"] is None or isinstance(data["fault_found"], bool)


def assert_software_package(data):
    _assert_common(data)
    assert isinstance(data["package_code"], str) and data["package_code"]
    assert isinstance(data["target_model_code"], str) and data["target_model_code"]
    assert isinstance(data["firmware_version"], str) and data["firmware_version"]
    assert isinstance(data["size_mb"], int)
    assert isinstance(data["mandatory"], bool)
    assert data["status"] in _enum_values(PackageStatus)


def assert_update_delivery(data):
    _assert_common(data)
    assert is_valid_uuid(data["machine_id"])
    assert is_valid_uuid(data["package_id"])
    assert is_valid_uuid(data["consent_ticket_id"])
    assert data["status"] in _enum_values(DeliveryStatus)
    assert isinstance(data["download_attempts"], int) and data["download_attempts"] >= 0
    assert data["failure_reason"] is None or isinstance(data["failure_reason"], str)
    _assert_nullable_timestamp(data, "installed_at")


def assert_feature_license(data):
    _assert_common(data)
    assert is_valid_uuid(data["machine_id"])
    assert data["feature_code"] in _enum_values(FeatureCode)
    assert data["license_type"] in _enum_values(LicenseType)
    assert data["term_months"] is None or isinstance(data["term_months"], int)
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in _enum_values(LicenseStatus)
    _assert_nullable_timestamp(data, "activated_at")
    _assert_nullable_timestamp(data, "expires_at")


def assert_warranty_claim(data):
    _assert_common(data)
    assert is_valid_uuid(data["machine_id"])
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["dealer_id"])
    assert isinstance(data["claim_amount_cents"], int) and data["claim_amount_cents"] > 0
    assert isinstance(data["parts_amount_cents"], int) and data["parts_amount_cents"] >= 0
    assert data["parts_amount_cents"] <= data["claim_amount_cents"]
    assert isinstance(data["description"], str)
    assert data["status"] in _enum_values(ClaimStatus)
    assert data["coverage_pct_applied"] is None or isinstance(
        data["coverage_pct_applied"], (int, float)
    )
    assert data["payout_cents"] is None or isinstance(data["payout_cents"], int)
    _assert_nullable_timestamp(data, "decided_at")
    _assert_nullable_timestamp(data, "settled_at")


def assert_integration_partner(data):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert (
        isinstance(data["api_quota_calls_per_day"], int)
        and data["api_quota_calls_per_day"] > 0
    )
    assert data["status"] in _enum_values(PartnerStatus)
    assert data["certification_expires_on"] is None or isinstance(
        data["certification_expires_on"], str
    )
    assert isinstance(data["calls_today"], int) and data["calls_today"] >= 0
    assert data["calls_window_date"] is None or isinstance(data["calls_window_date"], str)


def assert_uptime_prediction(data):
    for field in ("optimistic_score", "conservative_score"):
        assert isinstance(data[field], (int, float)), "%s must be numeric" % field
    assert isinstance(data["window_hours"], int)
    assert isinstance(data["filled_hours"], int) and data["filled_hours"] >= 0
    assert isinstance(data["bridged_hours"], int) and data["bridged_hours"] >= 0
    assert data["parts_recommendation"] in ("OVERHAUL_KIT", "SERVICE_KIT", "NONE")
    # The optimistic variant bridges gaps, so it is never below conservative.
    assert data["optimistic_score"] >= data["conservative_score"]


# --- Domain invariants ---------------------------------------------------------


def assert_dealer_warranty_totals(dealer, claims):
    """PRD section 3.8: the dealer read always reflects the sum of claim
    amounts over claims in SUBMITTED or APPROVED, and the paid total equals
    the sum of payouts over the dealer's SETTLED claims."""
    open_statuses = (ClaimStatus.SUBMITTED.value, ClaimStatus.APPROVED.value)
    expected_reserve = sum(
        c["claim_amount_cents"] for c in claims if c["status"] in open_statuses
    )
    expected_paid = sum(
        c["payout_cents"] or 0
        for c in claims
        if c["status"] == ClaimStatus.SETTLED.value
    )
    assert dealer["warranty_reserve_cents"] == expected_reserve, (
        "warranty_reserve_cents %r != sum of open claim amounts %r"
        % (dealer["warranty_reserve_cents"], expected_reserve)
    )
    assert dealer["warranty_paid_cents"] == expected_paid, (
        "warranty_paid_cents %r != sum of settled payouts %r"
        % (dealer["warranty_paid_cents"], expected_paid)
    )


def assert_machine_license_count(machine, licenses):
    """PRD section 3.7: active_license_count counts exactly the machine's
    licenses in PURCHASED, ACTIVATED or SUSPENDED; EXPIRED and REVOKED drop
    out."""
    counted = (LicenseStatus.PURCHASED.value, LicenseStatus.ACTIVATED.value,
               LicenseStatus.SUSPENDED.value)
    expected = sum(1 for lic in licenses if lic["status"] in counted)
    assert machine["active_license_count"] == expected, (
        "active_license_count %r != count of non-terminal licenses %r"
        % (machine["active_license_count"], expected)
    )
