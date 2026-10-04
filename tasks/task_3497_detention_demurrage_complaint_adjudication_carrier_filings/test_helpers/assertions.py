"""Entity assertions and domain invariant checkers.

PRD §2.5 renders `created_at`/`updated_at` with exactly three fractional
digits; PRD §2.2 does the same for `api_request_timestamp`. Domain
timestamps stamped from the logical clock (filed_at, issued_at, ...) are
asserted by exact value in the tests that pin them, never here.
"""
import re

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_COMMON_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_common_timestamp(value, field):
    """created_at / updated_at / api_request_timestamp carry exactly three
    fractional digits (PRD §2.2, §2.5)."""
    assert isinstance(value, str), f"{field} must be a string"
    assert _COMMON_TS_RE.match(value), (
        f"{field} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def _assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert_common_timestamp(data.get("created_at"), "created_at")
    assert_common_timestamp(data.get("updated_at"), "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_carrier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["org_name"], str) and len(data["org_name"]) > 0
    assert data["org_type"] in ["VOCC", "MTO", "NVOCC", "OFF"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["compliance_score"], int)
    assert 0 <= data["compliance_score"] <= 1000
    assert isinstance(data["cumulative_civil_penalties_cents"], int)
    assert data["cumulative_civil_penalties_cents"] >= 0


def assert_shipper(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["contact_email"], str) and len(data["contact_email"]) > 0
    assert isinstance(data["total_recovery_cents"], int)


def assert_tariff(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("carrier_id", ""))
    assert isinstance(data["tariff_code"], str) and len(data["tariff_code"]) > 0
    assert data["charge_scope"] in ["DETENTION", "DEMURRAGE", "GENERAL"]
    assert isinstance(data["free_time_days"], int) and data["free_time_days"] >= 0
    assert isinstance(data["per_diem_rate_cents"], int) and data["per_diem_rate_cents"] > 0
    assert data["accrual_method"] in ["CALENDAR", "WORKING_DAY"]
    assert data["change_type"] in ["NEW", "INCREASE", "DECREASE"]
    assert isinstance(data["notice_period_days"], int)
    assert is_iso8601_timestamp(data.get("effective_date", ""))
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert data["publication_status"] in ["DRAFT", "PUBLISHED", "SUSPENDED"]


def assert_service_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("carrier_id", ""))
    assert isinstance(data["contract_reference"], str)
    assert is_valid_uuid(data.get("shipper_id", ""))
    assert is_iso8601_timestamp(data.get("agreed_at", ""))
    assert isinstance(data["duration_months"], int) and data["duration_months"] >= 1
    assert isinstance(data["minimum_quantity_commitment"], int)
    assert data["minimum_quantity_commitment"] >= 1
    assert isinstance(data["negotiated_free_time_days"], int)
    assert data["negotiated_free_time_days"] >= 0
    assert isinstance(data["negotiated_per_diem_rate_cents"], int)
    assert data["negotiated_per_diem_rate_cents"] > 0
    assert data["negotiated_accrual_method"] in ["CALENDAR", "WORKING_DAY"]
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert data["contract_status"] in ["EFFECTIVE", "SUSPENDED"]


def assert_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agreement_number"], str)
    assert data["agreement_type"] in [
        "VESSEL_SHARING", "RATE_DISCUSSION", "EQUIPMENT_POOLING", "SPACE_CHARTER",
    ]
    assert isinstance(data["member_carrier_ids"], list)
    assert is_valid_uuid(data.get("filed_by_carrier_id", ""))
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert is_iso8601_timestamp(data.get("waiting_period_ends_at", ""))
    assert data["review_status"] in ["AWAITING_REVIEW", "EFFECTIVE"]
    assert isinstance(data["monitoring_reports"], list)
    assert data["market_concentration_hhi"] is None or isinstance(
        data["market_concentration_hhi"], (int, float))
    assert isinstance(data["competitive_concern_flag"], bool)


def assert_bond_invariant(bond: dict):
    """Per-bond surety invariant: available + drawn == coverage (PRD §3.4)."""
    assert bond["available_cents"] + bond["drawn_cents"] == bond["coverage_cents"], (
        f"bond {bond.get('bond_ref')} violates available+drawn==coverage: {bond}"
    )
    expected = "EXHAUSTED" if bond["drawn_cents"] == bond["coverage_cents"] else "ACTIVE"
    assert bond["bond_status"] == expected, (
        f"bond {bond.get('bond_ref')} status {bond['bond_status']} != {expected}"
    )


def assert_oti_license(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("organization_id", ""))
    assert data["license_type"] in ["NVOCC", "OFF"]
    assert data["license_status"] in ["PENDING_BOND", "ACTIVE", "SUSPENDED"]
    assert isinstance(data["required_bond_cents"], int)
    assert isinstance(data["surety_bonds"], list)
    for bond in data["surety_bonds"]:
        assert_bond_invariant(bond)
    assert data["total_available_coverage_cents"] == sum(
        b["available_cents"] for b in data["surety_bonds"]), (
        "total_available_coverage_cents must equal the sum of per-bond availability"
    )


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("carrier_id", ""))
    assert isinstance(data["invoice_number"], str)
    assert data["charge_basis"] in ["TARIFF", "SERVICE_CONTRACT"]
    assert is_valid_uuid(data.get("billed_party_shipper_id", ""))
    assert isinstance(data["container_number"], str) and len(data["container_number"]) > 0
    assert isinstance(data["port_code"], str) and len(data["port_code"]) > 0
    for field in ("availability_date", "return_date", "last_accrual_date", "issued_at"):
        assert is_iso8601_timestamp(data.get(field, "")), f"{field} must be ISO 8601"
    assert isinstance(data["government_hold_days"], int) and data["government_hold_days"] >= 0
    assert isinstance(data["appointment_unavailable_days"], int)
    assert data["appointment_unavailable_days"] >= 0
    assert isinstance(data["free_time_days"], int)
    assert isinstance(data["per_diem_rate_cents"], int)
    assert data["accrual_method"] in ["CALENDAR", "WORKING_DAY"]
    assert isinstance(data["billable_days"], int) and data["billable_days"] >= 0
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    # Note: amount_cents == billable_days * per_diem_rate_cents holds at issuance,
    # but a timely REDUCE dispute response replaces the charge outright (PRD §3.6),
    # so no blanket identity is asserted here.
    assert data["invoice_status"] in ["ISSUED", "DISPUTED", "PAID", "VOIDED"]


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert data["dispute_reason"] in [
        "LATE_ISSUANCE", "INCORRECT_PARTY", "MISSING_ELEMENTS",
        "CHARGE_EXCEEDS_PUBLISHED", "OTHER",
    ]
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert is_iso8601_timestamp(data.get("response_due_at", ""))
    assert data["resolution"] in ["PENDING", "UPHELD_WAIVED", "UPHELD_REDUCED", "DENIED"]
    assert isinstance(data["response_was_late"], bool)


def assert_complaint(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shipper_id", ""))
    assert is_valid_uuid(data.get("respondent_carrier_id", ""))
    assert isinstance(data["subject_invoice_ids"], list) and len(data["subject_invoice_ids"]) >= 1
    assert isinstance(data["reparations_claimed_cents"], int)
    assert data["reparations_claimed_cents"] > 0
    assert isinstance(data["incentive_principle_score"], int)
    assert 0 <= data["incentive_principle_score"] <= 100
    assert data["complaint_status"] in [
        "DOCKETED", "OMBUDS", "RESOLVED_INFORMAL", "ADJUDICATION_OPEN",
        "ADJUDICATION_DECIDED", "APPEALED", "FINAL", "REVERSED",
    ]
    assert isinstance(data["ombuds_rounds"], int) and data["ombuds_rounds"] >= 0
    assert isinstance(data["reparations_awarded_cents"], int)
    assert data["reparations_awarded_cents"] >= 0


def assert_proceeding(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("target_carrier_id", ""))
    assert data["basis"] in [
        "UNREASONABLE_PRACTICE", "TARIFF_VIOLATION",
        "UNLICENSED_ACTIVITY", "AGREEMENT_VIOLATION",
    ]
    assert data["proceeding_status"] in ["NOTICE_ISSUED", "DETERMINED", "DISMISSED"]
    if data["proceeding_status"] == "DETERMINED" and data.get("determination") == "VIOLATION_FOUND":
        assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] > 0
        assert isinstance(data["score_delta"], int) and data["score_delta"] < 0


def assert_congestion_report(data: dict):
    """Append-only record: id + created_at only, no updated_at / version
    (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert_common_timestamp(data.get("created_at"), "created_at")
    assert "updated_at" not in data, "append-only report must not carry updated_at"
    assert "version" not in data, "append-only report must not carry version"
    assert isinstance(data["port_code"], str) and len(data["port_code"]) > 0
    assert isinstance(data["terminal_code"], str) and len(data["terminal_code"]) > 0
    assert is_iso8601_timestamp(data.get("week_start", ""))
    assert 0 <= data["berth_occupancy_hours"] <= 168
    assert 0 <= data["gate_closures_hours"] <= 168
    assert data["vessel_dwell_hours_avg"] >= 0
