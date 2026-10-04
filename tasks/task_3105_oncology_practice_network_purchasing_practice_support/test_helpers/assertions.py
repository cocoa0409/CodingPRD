"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def assert_envelope_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_oncology_network(data: dict):
    assert_envelope_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["network_agreement_code"], str) and len(data["network_agreement_code"]) > 0
    assert data["shortage_allocation_method"] in ("PRO_RATA_BASELINE", "PRIORITY_PATHWAY", "EQUAL_SPLIT")
    assert isinstance(data["tier_market_share_boundaries"], list)
    assert isinstance(data["allocation_epoch_index"], int)
    assert isinstance(data["is_commercial_terms_frozen"], bool)


def assert_practice(data: dict):
    assert_envelope_common(data)
    assert is_valid_uuid(data.get("network_id", "")), "network_id must be a valid UUID"
    assert isinstance(data["practice_name"], str) and len(data["practice_name"]) > 0
    assert data["affiliation_status"] in (
        "PROSPECTIVE", "AFFILIATED", "SUSPENDED", "DEPARTING", "DEPARTED")
    assert data["pathway_steering_status"] in ("NOT_ADOPTED", "ACTIVE", "SUSPENDED")
    assert data["tier_level"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["unsettled_balance_cents"], int)
    assert isinstance(data["is_rebate_qualified"], bool)


def assert_practice_invariants(data: dict):
    """Domain invariants that must hold after any operation on a practice."""
    assert data["unsettled_balance_cents"] >= 0
    assert data["trailing_12m_network_purchases_cents"] >= 0
    assert data["denied_claim_count"] >= 0
    assert data["settled_claim_count"] >= 0
    assert data["settled_claim_count"] >= data["denied_claim_count"]
    assert 0.0 <= data["denial_ratio_threshold_pct"] <= 1.0
    assert 0.0 <= data["pathway_adherence_pct"] <= 1.0


def assert_provider(data: dict):
    assert_envelope_common(data)
    assert data["specialty"] in ("MEDICAL_ONCOLOGY", "HEMATOLOGY", "RADIATION_ONCOLOGY")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_drug_product(data: dict):
    assert_envelope_common(data)
    assert len(data["ndc"]) == 11, "ndc must be an 11-digit National Drug Code"
    assert data["therapeutic_class"] in (
        "CYTOTOXIC", "IMMUNOTHERAPY", "SUPPORTIVE_CARE", "ORAL_TARGETED")
    assert data["unit_type"] in ("VIAL", "MG", "TABLET")
    assert isinstance(data["network_base_price_cents"], int)
    assert data["status"] in ("ACTIVE", "SHORTAGE_RESTRICTED", "RECALLED")


def assert_pricing_agreement(data: dict):
    assert_envelope_common(data)
    assert data["tier_level"] in ("TIER_1", "TIER_2", "TIER_3")
    assert 0.0 <= data["discount_pct"] <= 0.35
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "SUPERSEDED", "REJECTED")


def assert_purchase_order(data: dict):
    assert_envelope_common(data)
    assert data["status"] in (
        "SUBMITTED", "CONFIRMED", "BACKORDERED", "SHIPPED", "RECEIVED", "CANCELLED")
    assert isinstance(data["quantity_units"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert data["unit_price_cents"] >= 0
    assert data["extended_cost_cents"] == data["unit_price_cents"] * data["quantity_units"]
    assert data["pricing_tier_applied"] in ("TIER_1", "TIER_2", "TIER_3")


def assert_inventory_lot(data: dict):
    assert_envelope_common(data)
    assert data["status"] in ("AVAILABLE", "QUARANTINED", "EXPIRED", "DEPLETED")
    assert data["quantity_remaining"] >= 0
    assert data["quantity_remaining"] <= data["quantity_received"]
    assert data["wastage_units"] >= 0
    assert data["waste_cost_basis_cents"] >= 0
    assert_cost_precision(data["acquisition_cost_cents_per_unit"], 0)


def assert_patient_treatment(data: dict):
    assert_envelope_common(data)
    assert data["status"] in ("SCHEDULED", "ADMINISTERED", "BILLED", "VOIDED")
    assert isinstance(data["administered_units"], int)
    assert isinstance(data["wastage_units"], int)
    assert data["wastage_units"] >= 0
    assert data["acquisition_cost_basis_cents"] >= data["wastage_cost_basis_cents"]


def assert_payer_claim(data: dict):
    assert_envelope_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ADJUDICATED_PAID", "DENIED", "APPEALED", "VOIDED")
    assert 0 <= data["appeal_round"] <= 2
    assert isinstance(data["billed_amount_cents"], int)


def assert_rebate_qualification(data: dict):
    assert_envelope_common(data)
    assert data["status"] in ("PENDING", "QUALIFIED", "DISQUALIFIED", "PAID", "RECLAIMED")
    assert 0.0 <= data["market_share_pct"] <= 1.0
    assert 0.0 <= data["compliance_score"] <= 1.0
    assert isinstance(data["is_qualified"], bool)
    assert data["rebate_amount_cents"] >= 0
    assert data["holdback_cents"] >= 0


def assert_rebate_program(data: dict):
    assert_envelope_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
    assert 0.0 <= data["rebate_pct"] <= 0.10


def assert_pathway_protocol(data: dict):
    assert_envelope_common(data)
    assert data["indication"] in ("NSCLC", "BREAST", "COLORECTAL", "LYMPHOMA")
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")
    assert isinstance(data["on_pathway_regimen_codes"], list)
    assert isinstance(data["declared_regimen_codes"], list)


def assert_management_agreement(data: dict):
    assert_envelope_common(data)
    assert data["service_line"] in ("REVENUE_CYCLE", "STAFFING", "TECHNOLOGY")
    assert data["fee_basis"] in (
        "PERCENT_OF_NET_COLLECTIONS", "FIXED_MONTHLY", "PER_FTE", "PER_CLAIM")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["accrued_fee_cents"] >= 0


def assert_research_participation(data: dict):
    assert_envelope_common(data)
    assert data["study_phase"] in ("PHASE_I", "PHASE_II", "PHASE_III")
    assert data["site_status"] in (
        "APPLIED", "FEASIBILITY_REVIEW", "ACTIVATED", "SUSPENDED", "DEACTIVATED")
    assert data["enrolled_participant_count"] >= 0


def assert_drug_shortage(data: dict):
    assert_envelope_common(data)
    assert data["status"] in ("REPORTED", "ALLOCATING", "ACTIVE", "RESOLVED")
    assert data["allocation_method"] in (
        "PRO_RATA_BASELINE", "PRIORITY_PATHWAY", "EQUAL_SPLIT")
    assert data["allocated_units"] >= 0
    assert data["unallocated_units"] >= 0


def assert_shortage_allocation(data: dict):
    assert_envelope_common(data)
    assert data["status"] in (
        "GRANTED", "PARTIALLY_COMMITTED", "FULLY_COMMITTED", "EXPIRED", "REVOKED")
    assert data["committed_units"] >= 0
    assert data["committed_units"] <= data["allocated_units"]
    assert data["consumed_authorization_cents"] >= 0
    assert data["consumed_authorization_cents"] <= data["consumption_authorization_cents"]


def assert_shortage_conservation(shortage: dict, grants: list):
    """The conserved quantity NETWORK_SHORTAGE_SUPPLY_UNITS: the units of every
    grant that is not REVOKED, plus the shortage's unallocated units, equals the
    shortage's available supply."""
    live_units = sum(g["allocated_units"] for g in grants if g["status"] != "REVOKED")
    assert live_units + shortage["unallocated_units"] == shortage["supply_available_units"], (
        f"shortage supply not conserved: {live_units} live grant units + "
        f"{shortage['unallocated_units']} unallocated != "
        f"{shortage['supply_available_units']} supply"
    )


def assert_affiliation_contract(data: dict):
    assert_envelope_common(data)
    assert data["contract_type"] in (
        "FULL_AFFILIATION", "MANAGEMENT_SERVICES_ONLY", "PURCHASING_ONLY")
    assert data["status"] in (
        "DRAFT", "ACTIVE", "DEPARTURE_NOTICE", "UNWIND_IN_PROGRESS", "TERMINATED")
    assert data["rebate_holdback_cents"] >= 0


def assert_ratio_reported(value, expected, tol=0.00005):
    """Ratios are reported to four decimal places, rounded half up."""
    assert value == pytest.approx(expected, abs=tol), (
        f"Expected ratio {expected} (4 dp), got {value}")