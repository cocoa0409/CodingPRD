"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BearingVariant,
    BillingMode,
    BillingTerms,
    CraneStatus,
    FieldStatus,
    GearAssignmentStatus,
    GearStatus,
    GearType,
    InvoiceStatus,
    LiftClass,
    PermitStatus,
    PermitType,
    PersonnelRoleType,
    PersonnelStatus,
    PlanStatus,
    ReviewStatus,
    RiggerLevel,
    StandbyCause,
    StandbyStatus,
    SurveyStatus,
)

_UUID_HINT = "identifiers are bare UUIDs with no type prefix and no embedded entity name"


def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """id + created_at + updated_at + version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID; {_UUID_HINT}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer beginning at 1"
    )


def assert_append_only_fields(data: dict, entity: str = "resource") -> None:
    """id + created_at only - no updated_at, no version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID; {_UUID_HINT}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{entity} is append-only and carries no updated_at"
    assert "version" not in data, f"{entity} is append-only and carries no version"


def _enum_values(enum_cls) -> list:
    return [m.value for m in enum_cls]


def assert_customer(data: dict) -> None:
    assert_common_fields(data, "Customer")
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert data["billing_terms"] in _enum_values(BillingTerms)
    assert isinstance(data["credit_hold"], bool)
    assert isinstance(data["open_receivable_cents"], int)
    assert isinstance(data["invoice_count"], int)


def assert_site(data: dict) -> None:
    assert_common_fields(data, "Site")
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["address_label"], str) and data["address_label"]
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert data["soil_bearing_capacity_psf"] > 0
    assert data["proximity_to_energized_lines_ft"] >= 0
    assert isinstance(data["over_water"], bool)
    assert data["survey_status"] in _enum_values(SurveyStatus)
    assert isinstance(data["mat_inventory_available"], bool)


def assert_crane(data: dict) -> None:
    assert_common_fields(data, "Crane")
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["class_tons"] > 0
    assert data["gross_weight_lb"] > 0
    assert data["counterweight_lb"] >= 0
    assert data["outrigger_pad_area_sqft"] > 0
    assert data["max_line_pull_lb"] > 0
    assert data["rated_max_wind_mph"] > 0
    assert data["mob_demob_cents"] >= 0
    assert data["hourly_rate_cents"] > 0
    assert isinstance(data["out_of_service_flag"], bool)
    assert data["status"] in _enum_values(CraneStatus)
    assert data["reserved_hours_total"] >= 0
    assert data["active_plan_count"] >= 0


def assert_load_chart_entry(data: dict) -> None:
    assert_append_only_fields(data, "LoadChartEntry")
    assert is_valid_uuid(data["crane_id"])
    assert data["configuration"] in ["MAIN_BOOM", "LUFFING_JIB", "FIXED_JIB"]
    assert data["boom_length_ft"] > 0
    assert data["radius_ft"] > 0
    assert data["gross_capacity_lb"] > 0


def assert_personnel(data: dict) -> None:
    assert_common_fields(data, "Personnel")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_type"] in _enum_values(PersonnelRoleType)
    assert isinstance(data["certification_number"], str) and data["certification_number"]
    assert data["rigger_level"] in _enum_values(RiggerLevel)
    assert data["status"] in _enum_values(PersonnelStatus)
    assert data["endorsement_class_tons"] >= 0
    assert data["peak_daily_assigned_hours"] >= 0


def assert_rigging_gear(data: dict) -> None:
    assert_common_fields(data, "RiggingGear")
    assert isinstance(data["gear_tag"], str) and data["gear_tag"]
    assert data["gear_type"] in _enum_values(GearType)
    assert data["rated_wll_lb"] > 0
    assert data["weight_lb"] >= 0
    assert data["inspection_interval_days"] > 0
    assert data["repair_count"] >= 0
    assert data["status"] in _enum_values(GearStatus)
    assert data["committed_assignment_count"] >= 0
    # The derate never lifts the rating above the manufacturer's limit and
    # never falls below seventy hundredths of it (PRD 3.2).
    assert data["effective_wll_lb"] <= data["rated_wll_lb"]
    assert data["effective_wll_lb"] >= int(data["rated_wll_lb"] * 0.70) - 1


def assert_gear_inspection(data: dict) -> None:
    assert_append_only_fields(data, "GearInspection")
    assert is_valid_uuid(data["gear_id"])
    assert data["result"] in ["PASS", "FAIL", "REPAIR_PASS", "RETIRE"]
    assert data["resulting_status"] in _enum_values(GearStatus)
    assert is_iso8601_timestamp(data["inspected_at"])
    assert data["repair_count_after"] >= 0


def assert_lift_plan(data: dict) -> None:
    assert_common_fields(data, "LiftPlan")
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["job_reference"], str) and data["job_reference"]
    assert data["load_weight_lb"] > 0
    assert data["sail_area_sqft"] >= 0
    assert data["plan_status"] in _enum_values(PlanStatus)
    assert data["field_status"] in _enum_values(FieldStatus)
    assert data["lift_class"] in _enum_values(LiftClass)
    assert data["bearing_variant"] in _enum_values(BearingVariant)
    assert isinstance(data["personnel_lift"], bool)
    assert isinstance(data["multi_crane"], bool)
    assert isinstance(data["road_closure_requested"], bool)
    assert isinstance(data["rigging_verified"], bool)
    assert isinstance(data["matting_required"], bool)
    assert isinstance(data["escort_required"], bool)
    assert isinstance(data["permit_required"], bool)
    assert data["utilization_pct"] >= 0
    assert data["net_capacity_lb"] >= 0
    assert data["mat_count"] >= 0
    assert data["standby_hours_billable"] >= 0


def assert_gear_assignment(data: dict) -> None:
    assert_common_fields(data, "GearAssignment")
    assert is_valid_uuid(data["lift_plan_id"])
    assert is_valid_uuid(data["gear_id"])
    assert 1 <= data["leg_count"] <= 4
    assert data["sling_angle_deg"] in [30, 45, 60, 90]
    assert data["status"] in _enum_values(GearAssignmentStatus)
    assert data["leg_tension_lb"] >= 0
    assert data["effective_wll_lb"] >= 0


def assert_engineering_review(data: dict) -> None:
    assert_common_fields(data, "EngineeringReview")
    assert is_valid_uuid(data["lift_plan_id"])
    assert is_valid_uuid(data["author_personnel_id"])
    assert isinstance(data["analysis_notes"], str) and data["analysis_notes"]
    assert 1 <= data["revision_round"] <= 3
    assert data["status"] in _enum_values(ReviewStatus)


def assert_permit(data: dict) -> None:
    assert_common_fields(data, "Permit")
    assert is_valid_uuid(data["lift_plan_id"])
    assert data["permit_type"] in _enum_values(PermitType)
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["escort_required"], bool)
    assert data["required_lead_days"] > 0
    assert data["permit_fee_cents"] > 0
    assert data["cancellation_fee_cents"] >= 0
    assert data["status"] in _enum_values(PermitStatus)


def assert_standby_event(data: dict) -> None:
    assert_common_fields(data, "StandbyEvent")
    assert is_valid_uuid(data["lift_plan_id"])
    assert data["cause"] in _enum_values(StandbyCause)
    assert data["wind_speed_mph"] >= 0
    assert is_iso8601_timestamp(data["started_at"])
    assert data["raw_duration_hours"] >= 0
    assert isinstance(data["forced_wind_hold"], bool)
    assert data["status"] in _enum_values(StandbyStatus)


def assert_invoice(data: dict) -> None:
    assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data["lift_plan_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["billing_mode"] in _enum_values(BillingMode)
    assert data["status"] in _enum_values(InvoiceStatus)
    assert isinstance(data["system_generated"], bool)
    for money_field in (
        "line_regular_cents",
        "line_overtime_cents",
        "line_standby_cents",
        "line_travel_cents",
        "line_mobdemob_cents",
        "line_lump_sum_cents",
        "line_permit_cancellation_cents",
        "subtotal_cents",
        "discount_cents",
        "fuel_surcharge_cents",
        "total_cents",
    ):
        assert isinstance(data[money_field], int), (
            f"Invoice.{money_field} must be an integer count of cents, "
            f"got {data[money_field]!r}"
        )


def assert_invoice_line_sum(data: dict) -> None:
    """Each of the seven lines is rounded to whole cents first, and only then
    are the seven rounded lines added together to give subtotal_cents."""
    expected = (
        data["line_regular_cents"]
        + data["line_overtime_cents"]
        + data["line_standby_cents"]
        + data["line_travel_cents"]
        + data["line_mobdemob_cents"]
        + data["line_lump_sum_cents"]
        + data["line_permit_cancellation_cents"]
    )
    assert data["subtotal_cents"] == expected, (
        f"subtotal_cents {data['subtotal_cents']} must equal the sum of the seven "
        f"rounded lines {expected}"
    )


def assert_invoice_total_identity(data: dict) -> None:
    """total_cents is subtotal_cents, less discount_cents, plus fuel_surcharge_cents."""
    expected = data["subtotal_cents"] - data["discount_cents"] + data["fuel_surcharge_cents"]
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} must equal subtotal - discount + surcharge "
        f"({expected})"
    )


def assert_two_decimals(value, label: str = "value") -> None:
    """Percentages, hour ledgers and bearing figures carry two decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_crane_ledger_consistent(crane: dict) -> None:
    """A crane holding no reserving plan holds no reserved hours (PRD 3.4)."""
    if crane["active_plan_count"] == 0:
        assert crane["reserved_hours_total"] == 0, (
            "a crane with no plan in the reserving set must hold 0.0 reserved hours, "
            f"got {crane['reserved_hours_total']}"
        )
