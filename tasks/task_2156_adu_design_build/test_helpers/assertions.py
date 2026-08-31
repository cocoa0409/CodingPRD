"""Entity assertions and domain invariant checkers for the ADU design-build API."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

DATE_LEN = len("YYYY-MM-DD")


def _assert_common(data: dict, entity: str):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}")


def _assert_immutable_record(data: dict, entity: str):
    """Immutable records carry only id + created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} is immutable and must not carry updated_at"
    assert "version" not in data, f"{entity} is immutable and must not carry version"


def assert_business_date(value, field: str):
    assert isinstance(value, str) and len(value) == DATE_LEN, (
        f"{field} must be a YYYY-MM-DD calendar date, got {value!r}")
    datetime.strptime(value, "%Y-%m-%d")


def assert_no_type_prefix(identifier: str):
    """Identifiers are UUID strings with no type prefix of any kind (PRD §2.4)."""
    assert is_valid_uuid(identifier), f"identifier must be a bare UUID, got {identifier!r}"
    assert "_" not in identifier and ":" not in identifier, (
        f"identifier must carry no type prefix, got {identifier!r}")


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and optional millis."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_jurisdiction(data: dict):
    _assert_common(data, "Jurisdiction")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 8
    assert data["code"] == data["code"].upper()
    assert data["local_max_detached_sqft"] >= 150
    assert data["local_rear_setback_ft"] >= 0
    assert data["local_side_setback_ft"] >= 0
    assert data["local_max_height_ft"] > 0
    assert data["correction_response_days"] >= 1
    for money in ("plan_check_base_fee_cents", "plan_check_rate_per_sqft_cents",
                  "impact_fee_per_sqft_cents", "utility_capacity_fee_cents"):
        assert isinstance(data[money], int) and data[money] >= 0, f"{money} must be whole cents >= 0"
    assert isinstance(data["separate_meter_required"], bool)
    assert isinstance(data["str_prohibited"], bool)
    assert data["str_min_lease_days"] >= 1


def assert_inspector(data: dict):
    _assert_common(data, "Inspector")
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["certifications"], list) and len(data["certifications"]) >= 1
    for cert in data["certifications"]:
        assert cert in ("STRUCTURAL", "ELECTRICAL", "PLUMBING", "ENVELOPE", "FINAL")
    assert 1 <= data["daily_capacity"] <= 12
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_property(data: dict):
    _assert_common(data, "Property")
    assert is_valid_uuid(data["jurisdiction_id"])
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert data["lot_sqft"] > 0
    assert data["existing_dwelling_sqft"] > 0
    assert isinstance(data["occupied"], bool)
    assert isinstance(data["in_str_overlay"], bool)
    assert data["electrical_service_amps"] in (100, 125, 150, 200, 400)
    assert data["existing_water_meter_size_in"] in (0.625, 0.75, 1.0, 1.5)
    assert data["pre_adu_value_cents"] > 0
    assert data["existing_mortgage_balance_cents"] >= 0


def assert_adu_project(data: dict):
    _assert_common(data, "AduProject")
    assert is_valid_uuid(data["property_id"])
    assert data["unit_type"] in ("DETACHED_NEW", "ATTACHED", "CONVERSION", "JADU")
    assert 150 <= data["proposed_sqft"] <= 1200
    assert 0 < data["proposed_height_ft"] <= 35
    assert data["rear_setback_ft"] >= 0 and data["side_setback_ft"] >= 0
    assert 0 <= data["bedrooms"] <= 4
    assert data["contract_base_price_cents"] > 0
    assert data["status"] in ("INTAKE", "FEASIBILITY_CLEARED", "PERMITTING", "DESIGN_REVISION",
                             "PERMITTED", "UNDER_CONSTRUCTION", "FINALED")
    assert data["financing_state"] in ("UNFUNDED", "PRE_QUALIFIED", "COMMITTED", "SHORTFALL")
    assert data["approved_pathway"] in (None, "STATUTORY_MINISTERIAL", "LOCAL_ORDINANCE")
    for field in ("max_allowed_sqft", "contract_price_current_cents",
                  "approved_change_order_count", "total_permit_fee_cents"):
        assert isinstance(data[field], int), f"AduProject.{field} must be an integer"
    assert isinstance(data["approved_change_days"], int)


def assert_feasibility_screening(data: dict):
    _assert_immutable_record(data, "FeasibilityScreening")
    assert is_valid_uuid(data["adu_project_id"])
    assert data["pathway"] in ("STATUTORY_MINISTERIAL", "LOCAL_ORDINANCE")
    assert isinstance(data["max_allowed_sqft"], int)
    assert data["required_service_amps"] in (100, 125, 200)
    for flag in ("zoning_ok", "setback_ok", "height_ok", "utility_capacity_ok"):
        assert isinstance(data[flag], bool), f"FeasibilityScreening.{flag} must be a boolean"
    assert data["verdict"] in ("PASS", "PASS_WITH_CONDITIONS", "FAIL")
    assert isinstance(data["deficiency_codes"], list)
    for code in data["deficiency_codes"]:
        assert code in ("ZONING", "SETBACK", "HEIGHT", "UTILITY_CAPACITY")
    assert data["deficiency_codes"] == sorted(data["deficiency_codes"]), (
        "deficiency_codes must be sorted ascending in ASCII order")
    assert_screening_verdict_consistent(data)


def assert_screening_verdict_consistent(data: dict):
    """The verdict follows a strict precedence over the four checks (PRD §3.2)."""
    if not (data["zoning_ok"] and data["setback_ok"] and data["height_ok"]):
        expected = "FAIL"
    elif not data["utility_capacity_ok"]:
        expected = "PASS_WITH_CONDITIONS"
    else:
        expected = "PASS"
    assert data["verdict"] == expected, (
        f"Expected verdict {expected} from the four checks, got {data['verdict']}")


def assert_utility_connection(data: dict):
    _assert_common(data, "UtilityConnection")
    assert is_valid_uuid(data["adu_project_id"])
    assert data["service_type"] in ("WATER", "SEWER", "ELECTRIC")
    assert data["status"] in ("PENDING_DECISION", "SEPARATE_APPROVED", "SHARED_APPROVED", "ENERGIZED")
    assert data["decision"] in (None, "SEPARATE", "SHARED")
    assert 0 <= data["separation_score"] <= 100, "separation_score is clamped into 0..100"
    assert isinstance(data["separation_cost_cents"], int) and data["separation_cost_cents"] >= 0
    if data["energized_on_date"] is not None:
        assert_business_date(data["energized_on_date"], "energized_on_date")


def assert_permit_submittal(data: dict):
    _assert_common(data, "PermitSubmittal")
    assert is_valid_uuid(data["adu_project_id"])
    assert data["design_sheet_count"] >= 1
    assert isinstance(data["title24_compliant"], bool)
    assert data["design_revision"] >= 1
    assert data["status"] in ("PREPARED", "UNDER_PLAN_CHECK", "CORRECTIONS_REQUIRED",
                             "APPROVED", "EXPIRED")
    assert data["cycle_number"] >= 0
    for field in ("submitted_on_date", "correction_deadline_date", "approved_on_date"):
        if data[field] is not None:
            assert_business_date(data[field], field)
    assert_permit_fee_components_sum(data)


def assert_permit_fee_components_sum(data: dict):
    """total_permit_fee_cents is the sum of the four already-rounded components."""
    for field in ("plan_check_component_cents", "impact_component_cents",
                  "school_component_cents", "utility_component_cents", "total_permit_fee_cents"):
        assert isinstance(data[field], int), f"PermitSubmittal.{field} must be whole cents"
    total = (data["plan_check_component_cents"] + data["impact_component_cents"]
             + data["school_component_cents"] + data["utility_component_cents"])
    assert data["total_permit_fee_cents"] == total, (
        f"total_permit_fee_cents {data['total_permit_fee_cents']} must equal the sum of the "
        f"four rounded components ({total})")


def assert_correction_item(data: dict):
    _assert_common(data, "CorrectionItem")
    assert is_valid_uuid(data["permit_submittal_id"])
    assert data["discipline"] in ("STRUCTURAL", "ENERGY", "FIRE", "PLANNING", "UTILITY")
    assert data["severity"] in ("BLOCKING", "ADVISORY")
    assert isinstance(data["description"], str) and data["description"]
    assert data["status"] in ("OPEN", "RESOLVED")
    if data["resolved_on_date"] is not None:
        assert_business_date(data["resolved_on_date"], "resolved_on_date")


def assert_financing_scenario(data: dict):
    _assert_common(data, "FinancingScenario")
    assert is_valid_uuid(data["adu_project_id"])
    assert data["product_type"] in ("HELOC", "CASH_OUT_REFI", "RENOVATION_LOAN", "CONSTRUCTION_LOAN")
    assert data["appraisal_approach"] in ("SALES_COMPARISON", "INCOME_CAPITALIZATION")
    assert data["comparable_adjustment_cents"] >= 0
    assert data["projected_monthly_rent_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "COMMITTED")
    for field in ("as_completed_value_cents", "max_loan_cents", "available_cents",
                  "required_funds_cents", "funding_gap_cents"):
        assert isinstance(data[field], int), f"FinancingScenario.{field} must be whole cents"
    assert data["funding_gap_cents"] >= 0, "funding_gap_cents is floored at 0"
    assert isinstance(data["appraisal_shortfall"], bool)


def assert_change_order(data: dict):
    _assert_common(data, "ChangeOrder")
    assert is_valid_uuid(data["adu_project_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["scope_items"], list)
    assert isinstance(data["cost_delta_cents"], int)
    assert -30 <= data["schedule_delta_days"] <= 120
    assert data["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED",
                              "APPROVED", "REJECTED", "VOIDED")
    assert isinstance(data["builder_fee_cents"], int)
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]


def assert_construction_phase(data: dict):
    _assert_common(data, "ConstructionPhase")
    assert is_valid_uuid(data["adu_project_id"])
    assert data["phase_code"] in ("SITE_PREP", "FOUNDATION", "FRAMING", "ROUGH_MEP",
                                 "UTILITY_TIE_IN", "INSULATION_DRYWALL", "FINISHES")
    assert data["disruption_class"] in ("NON_INVASIVE", "INVASIVE", "UTILITY_SHUTOFF")
    assert data["sequence_index"] >= 0
    assert data["status"] in ("PLANNED", "SCHEDULED", "BLOCKED", "IN_PROGRESS", "COMPLETE")
    for field in ("window_start_date", "window_end_date", "started_on_date", "completed_on_date"):
        if data[field] is not None:
            assert_business_date(data[field], field)
    if data["window_start_date"] and data["window_end_date"]:
        assert data["window_start_date"] <= data["window_end_date"], (
            "window_end_date must be the same as or later than window_start_date")


def assert_inspection_appointment(data: dict):
    _assert_common(data, "InspectionAppointment")
    assert is_valid_uuid(data["adu_project_id"])
    assert is_valid_uuid(data["construction_phase_id"])
    assert is_valid_uuid(data["inspector_id"])
    assert data["inspection_type"] in ("FOUNDATION", "FRAMING", "ROUGH_MEP", "INSULATION", "FINAL")
    assert_business_date(data["slot_date"], "slot_date")
    start = parse_instant(data["slot_start"])
    end = parse_instant(data["slot_end"])
    assert end > start, "slot_end must be strictly later than slot_start"
    assert start.strftime("%Y-%m-%d") == data["slot_date"], (
        "slot_date must equal the UTC date part of slot_start")
    assert data["status"] in ("SCHEDULED", "PARTIAL", "PASSED", "FAILED", "CANCELLED")


def assert_occupancy_certificate(data: dict):
    _assert_immutable_record(data, "OccupancyCertificate")
    assert is_valid_uuid(data["adu_project_id"])
    assert isinstance(data["certificate_number"], str) and "-" in data["certificate_number"]
    assert_business_date(data["issued_on_date"], "issued_on_date")
    parse_instant(data["final_inspection_passed_at"])
    assert data["rental_classification"] in ("LONG_TERM_ONLY", "SHORT_TERM_PERMITTED",
                                             "RENTAL_PROHIBITED")
    assert isinstance(data["min_lease_days"], int) and data["min_lease_days"] >= 1
    assert isinstance(data["rental_ready"], bool)
    assert isinstance(data["blocking_reasons"], list)
    for reason in data["blocking_reasons"]:
        assert reason in ("JADU_OWNER_OCCUPANCY_REQUIRED", "OPEN_CHANGE_ORDERS",
                          "STR_OVERLAY_RESTRICTED")
    assert data["blocking_reasons"] == sorted(data["blocking_reasons"]), (
        "blocking_reasons must be sorted ascending in ASCII order")
    if data["rental_classification"] == "RENTAL_PROHIBITED":
        assert data["rental_ready"] is False
    assert data["rental_ready"] == (data["rental_classification"] != "RENTAL_PROHIBITED"
                                   and len(data["blocking_reasons"]) == 0)


# ---------------------------------------------------------------------------
# Domain invariants spanning entities
# ---------------------------------------------------------------------------

def assert_contract_ledger_consistent(project: dict, change_orders: list):
    """contract_price_current_cents == base + sum(cost_delta + builder_fee) over
    APPROVED change orders, with approved_change_days and count in step."""
    approved = [co for co in change_orders if co["status"] == "APPROVED"]
    expected_price = project["contract_base_price_cents"] + sum(
        co["cost_delta_cents"] + co["builder_fee_cents"] for co in approved)
    assert project["contract_price_current_cents"] == expected_price, (
        f"contract_price_current_cents {project['contract_price_current_cents']} != "
        f"base plus approved deltas and fees ({expected_price})")
    expected_days = sum(co["schedule_delta_days"] for co in approved)
    assert project["approved_change_days"] == expected_days, (
        f"approved_change_days {project['approved_change_days']} != {expected_days}")
    assert project["approved_change_order_count"] == len(approved), (
        f"approved_change_order_count {project['approved_change_order_count']} != {len(approved)}")


def assert_availability(payload: dict, inspector_id: str, slot_date: str,
                        daily_capacity: int, booked_count: int):
    """The availability read reports the inspector, the date, the capacity, the
    booked count and the slots left over."""
    assert payload["inspector_id"] == inspector_id
    assert payload["slot_date"] == slot_date
    assert payload["daily_capacity"] == daily_capacity, (
        f"daily_capacity {payload['daily_capacity']} != {daily_capacity}")
    assert payload["booked_count"] == booked_count, (
        f"booked_count {payload['booked_count']} != {booked_count}")
    assert payload["remaining_slots"] == daily_capacity - booked_count, (
        f"remaining_slots {payload['remaining_slots']} != {daily_capacity - booked_count}")
