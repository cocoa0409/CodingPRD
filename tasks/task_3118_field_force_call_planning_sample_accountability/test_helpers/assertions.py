"""Entity assertions and domain invariant checkers.

The ``assert_<entity>`` helpers pin only what PRD sections 2.4 and 3 pin:
the uniform system-managed fields and the server-declared field types.  They
never demand a computed value the PRD leaves open.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    CallPlanStatus,
    CallStatus,
    ComplianceStanding,
    CountSessionStatus,
    DisciplinaryTier,
    EligibilityStatus,
    ExcursionSeverity,
    ExcursionStatus,
    ProductStatus,
    QuarantineReason,
    ReconciliationStatus,
    RegionStatus,
    RepresentativeStatus,
    SampleLotStatus,
    SampleReturnStatus,
    SignatureStatus,
    TargetEntryStatus,
    Tier,
    TransferReasonCode,
    TransferStatus,
)


def _assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_region(data):
    _assert_common_fields(data)
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in {s.value for s in RegionStatus}


def assert_territory(data):
    _assert_common_fields(data)
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert data["status"] in {s.value for s in TerritoryStatus}


def assert_representative(data):
    _assert_common_fields(data)
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert data["status"] in {s.value for s in RepresentativeStatus}
    assert data["compliance_standing"] in {s.value for s in ComplianceStanding}


def assert_prescriber(data):
    _assert_common_fields(data)
    assert isinstance(data["npi_number"], str) and data["npi_number"]
    assert data["eligibility_status"] in {s.value for s in EligibilityStatus}


def assert_product(data):
    _assert_common_fields(data)
    assert isinstance(data["ndc_code"], str) and data["ndc_code"]
    assert isinstance(data["controlled"], bool)
    assert isinstance(data["per_visit_max_units"], int)
    assert isinstance(data["annual_max_units_per_prescriber"], int)
    assert data["status"] in {s.value for s in ProductStatus}


def assert_target_list_entry(data):
    _assert_common_fields(data)
    assert data["tier"] in {t.value for t in Tier}
    assert data["status"] in {s.value for s in TargetEntryStatus}
    assert isinstance(data["planned_calls_per_cycle"], int)
    assert isinstance(data["delivered_calls"], int)
    assert isinstance(data["planned_sample_units"], int)
    assert isinstance(data["delivered_sample_units"], int)


def assert_call_plan(data):
    _assert_common_fields(data)
    assert data["status"] in {s.value for s in CallPlanStatus}


def assert_call_visit(data):
    _assert_common_fields(data)
    assert data["call_status"] in {s.value for s in CallStatus}
    assert data["signature_status"] in {s.value for s in SignatureStatus}


def assert_sample_lot(data):
    _assert_common_fields(data)
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["quantity_received"], int)
    assert isinstance(data["quantity_available"], int)
    assert data["status"] in {s.value for s in SampleLotStatus}
    assert data["quarantine_reason"] in {s.value for s in QuarantineReason}


def assert_rep_lot_balance(data):
    _assert_common_fields(data)
    for field in (
        "qty_issued",
        "qty_dispensed",
        "qty_returned",
        "qty_transferred_out",
        "qty_transferred_in",
        "qty_in_transit_out",
        "qty_available_forward",
        "qty_available_confirmed",
    ):
        assert isinstance(data[field], int), "{0} must be an integer".format(field)
        assert data[field] >= 0, "{0} must be non-negative".format(field)


def assert_sample_disbursement(data):
    _assert_common_fields(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["reconciliation_status"] in {
        s.value for s in ReconciliationStatus
    }


def assert_sample_transfer(data):
    _assert_common_fields(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["reason_code"] in {s.value for s in TransferReasonCode}
    assert data["status"] in {s.value for s in TransferStatus}


def assert_count_session(data):
    _assert_common_fields(data)
    assert data["status"] in {s.value for s in CountSessionStatus}
    if data.get("disciplinary_tier") is not None:
        assert data["disciplinary_tier"] in {s.value for s in DisciplinaryTier}


def assert_count_line(data):
    _assert_common_fields(data)
    assert isinstance(data["expected_qty"], int)


def assert_temperature_excursion(data):
    _assert_common_fields(data)
    assert data["severity"] in {s.value for s in ExcursionSeverity}
    assert data["status"] in {s.value for s in ExcursionStatus}


def assert_sample_return(data):
    _assert_common_fields(data)
    assert data["status"] in {s.value for s in SampleReturnStatus}


def assert_rep_balance_invariants(data):
    """The two availability identities of PRD section 2.8 must hold exactly
    on every RepLotBalance row."""
    forward = (
        data["qty_issued"]
        - data["qty_dispensed"]
        - data["qty_returned"]
        - data["qty_transferred_out"]
        - data["qty_in_transit_out"]
        + data["qty_transferred_in"]
    )
    confirmed = (
        data["qty_issued"]
        - data["qty_dispensed"]
        - data["qty_returned"]
        - data["qty_transferred_out"]
        + data["qty_transferred_in"]
    )
    assert data["qty_available_forward"] == forward, (
        "qty_available_forward {0} != issued - dispensed - returned - "
        "transferred_out - in_transit_out + transferred_in = {1}".format(
            data["qty_available_forward"], forward
        )
    )
    assert data["qty_available_confirmed"] == confirmed, (
        "qty_available_confirmed {0} != issued - dispensed - returned - "
        "transferred_out + transferred_in = {1}".format(
            data["qty_available_confirmed"], confirmed
        )
    )


__all__ = [name for name in dir() if name.startswith("assert_")] + [
    "get_success_data"
]
