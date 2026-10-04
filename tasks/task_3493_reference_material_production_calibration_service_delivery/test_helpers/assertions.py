"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a dashed UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_program(data: dict):
    _assert_common(data)
    for f in ("program_code", "name"):
        assert isinstance(data[f], str) and data[f]
    for f in ("material_unit_price_cents", "discount_pct_federal",
              "discount_pct_accredited_lab", "discount_pct_general",
              "handling_fee_threshold_cents", "handling_fee_flat_cents",
              "expedite_multiplier_pct", "daily_lab_capacity_minutes"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert data["status"] in [
        "SOURCING", "HOMOGENEITY_TESTING", "VALUE_ASSIGNMENT",
        "CERTIFICATION_PENDING", "CERTIFIED", "IN_DISTRIBUTION",
        "DISTRIBUTION_HOLD", "DEPLETED", "WITHDRAWN",
    ]
    for f in ("total_units_produced", "qc_units_consumed", "units_reserved",
              "units_shipped", "units_available"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["allocation_policy"] in ["FIFO", "PRO_RATA"]


def assert_lot_unit_conservation(lot: dict):
    """units_available == produced - qc - reserved - shipped (PRD §3.2)."""
    assert lot["units_available"] == (
        lot["total_units_produced"]
        - lot["qc_units_consumed"]
        - lot["units_reserved"]
        - lot["units_shipped"]
    ), f"unit ledger broken on lot {lot.get('id')}: {lot}"


def assert_method(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["status"] in ["DATA_SUBMITTED", "ACCEPTED", "REJECTED"]
    assert isinstance(data["method_mean"], (int, float))
    assert isinstance(data["method_std_uncertainty"], (int, float))
    assert isinstance(data.get("analyst_user_id"), str) and data["analyst_user_id"]


def assert_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["status"] in ["DRAFT", "PUBLISHED", "EXPIRED", "SUPERSEDED", "WITHDRAWN"]
    assert data["value_assignment_variant"] in ["WEIGHTED_MEAN", "UNWEIGHTED_MEAN"]
    assert data["coverage_factor"] == 2
    for f in ("certified_value", "characterization_uncertainty",
              "combined_standard_uncertainty", "expanded_uncertainty"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"


def assert_customer(data: dict):
    _assert_common(data)
    assert data["tier"] in ["FEDERAL", "ACCREDITED_LAB", "GENERAL"]
    assert isinstance(data["pt_fail_count"], int)
    assert data["accreditation_standing"] in ["GOOD_STANDING", "PROBATION", "SUSPENDED"]
    assert isinstance(data["credit_hold"], bool)


def assert_sales_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["status"] in ["PLACED", "ALLOCATED", "BACKORDERED", "FULFILLED", "CANCELLED"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["allocated_quantity"], int)
    assert isinstance(data["quoted_unit_price_cents"], int)


def assert_service(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["per_point_fee_cents"], int)


def assert_calibration_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("service_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["status"] in ["RECEIVED", "SCHEDULED", "IN_MEASUREMENT",
                              "MEASUREMENT_HOLD", "COMPLETED", "CANCELLED"]
    assert isinstance(data["quoted_fee_cents"], int)


def assert_traceability_link(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("service_id", ""))
    assert isinstance(data["uncertainty_contribution"], (int, float))


def assert_pt_round(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["round_type"] in ["PROFICIENCY_TEST", "KEY_COMPARISON"]
    assert data["status"] in ["PLANNING", "SAMPLE_DISTRIBUTION", "ANALYSIS_OPEN",
                              "EVALUATION", "CLOSED"]
    assert isinstance(data["evaluated_count"], int)


def assert_participant_result(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("round_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["status"] in ["SUBMITTED", "EVALUATED"]
    assert isinstance(data["measured_value"], (int, float))
    assert isinstance(data["measurement_uncertainty"], (int, float))
