"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_affiliate(data: dict):
    _assert_common(data)
    assert isinstance(data["affiliate_code"], str) and len(data["affiliate_code"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["grant_cycle_open"], bool)
    assert isinstance(data["low_income_priority_quota"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_catalog_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["service_code"], str) and len(data["service_code"]) > 0
    assert isinstance(data["in_scope"], bool)
    assert isinstance(data["telehealth_eligible"], bool)
    assert isinstance(data["full_fee_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_fee_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["tier_code"], str)
    assert isinstance(data["fpl_pct_min_inclusive"], int)
    assert isinstance(data["fpl_pct_max_exclusive"], int)
    assert isinstance(data["discount_pct"], int)
    assert 0 <= data["discount_pct"] <= 100
    assert isinstance(data["nominal_copay_cents"], int)
    assert isinstance(data["requires_documentation"], bool)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["external_ref"], str) and len(data["external_ref"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["is_minor"], bool)
    assert isinstance(data["confidentiality_flag"], bool)
    assert data["status"] == "ACTIVE"


def assert_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert data["income_basis"] in ("DOCUMENTED", "SELF_DECLARED")
    assert isinstance(data["fpl_pct"], int)
    assert isinstance(data["assigned_tier_code"], str)
    assert data["status"] in ("CURRENT", "SUPERSEDED")


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str)
    assert data["provider_type"] in ("PHYSICIAN", "NP", "RN", "COUNSELOR")
    assert data["status"] == "ACTIVE"


def assert_license(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)
    assert data["status"] in ("ACTIVE", "EXPIRED")


def assert_encounter(data: dict):
    _assert_common(data)
    assert isinstance(data["service_code"], str)
    assert isinstance(data["provider_id"], str)
    assert data["channel"] in ("IN_PERSON", "TELEHEALTH")
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert isinstance(data["patient_charge_cents"], int)
    assert data["clinical_status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "CLAIMED", "SETTLED", "WAIVED")


def assert_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["confidential_suppression"], bool)
    assert isinstance(data["billed_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["recouped_cents"], int)
    assert isinstance(data["net_receivable_cents"], int)
    assert isinstance(data["submission_round"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "PAID", "DENIED", "VOID")


def assert_stock_lot(data: dict):
    _assert_common(data)
    assert data["device_code"] in ("IUD_COPPER", "IUD_HORMONAL", "IMPLANT")
    assert isinstance(data["lot_number"], str)
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["on_hand"], int)
    assert isinstance(data["reserved_out"], int)
    assert isinstance(data["expires_on"], str)


def assert_device_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["encounter_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["is_rapid_reinsertion"], bool)
    assert data["status"] in ("RESERVED", "FULFILLED", "RELEASED")


def assert_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["requested_service_code"], str)
    assert isinstance(data["receiving_org"], str)
    assert data["reason_code"] in (
        "OUT_OF_SCOPE_STATE_LAW", "OUT_OF_SCOPE_AFFILIATE", "CAPACITY",
    )
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "COMPLETED", "WITHDRAWN")


def assert_grant_report(data: dict):
    _assert_common(data)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["encounter_count"], int)
    assert isinstance(data["low_income_encounter_count"], int)
    assert isinstance(data["minor_encounter_count"], int)
    assert isinstance(data["device_value_cents"], int)
    assert data["valuation_variant"] in ("FIFO", "WEIGHTED_AVERAGE")
    assert isinstance(data["low_income_quota_met"], bool)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")


def assert_privacy_hold(data: dict):
    _assert_common(data)
    assert isinstance(data["hold_start"], str)
    assert isinstance(data["hold_end"], str)
    assert data["scope"] in ("RECORD_VIEW", "BILLING_CORRESPONDENCE", "ALL")
    assert isinstance(data["authorized_staff_ids"], list)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_claim_receivable_identity(claim: dict):
    """Payer-accounting identity: billed == paid - recouped + net_receivable."""
    assert (
        claim["billed_cents"]
        == claim["paid_cents"] - claim["recouped_cents"] + claim["net_receivable_cents"]
    ), (
        "Claim receivable identity violated: "
        f"billed={claim['billed_cents']} paid={claim['paid_cents']} "
        f"recouped={claim['recouped_cents']} net={claim['net_receivable_cents']}"
    )


def assert_lot_available_units(lot: dict, expected_available: int):
    """Inventory pool invariant: available == on_hand - reserved_out."""
    actual = lot["on_hand"] - lot["reserved_out"]
    assert actual == expected_available, (
        f"Expected {expected_available} available units, got {actual} "
        f"(on_hand={lot['on_hand']}, reserved_out={lot['reserved_out']})"
    )
