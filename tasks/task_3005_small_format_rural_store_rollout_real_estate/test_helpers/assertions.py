"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ROLLOUT_STATUSES = ["DRAFT", "ACTIVE", "CLOSED"]
TRADE_AREA_STATUSES = ["SCREENING", "QUALIFIED", "REJECTED"]
STORE_STATUSES = [
    "PROPOSED",
    "SITE_CONTROL",
    "UNDER_CONSTRUCTION",
    "DELIVERED",
    "OPEN",
    "KILLED",
    "EXISTING",
]
FORMAT_TYPES = ["TRADITIONAL", "DG_FRESH", "DG_MARKET"]
AGREEMENT_STATUSES = ["DRAFT", "EXECUTED", "ACTIVE", "DELIVERED", "COMPLETED", "TERMINATED"]
ASSIGNMENT_STATUSES = ["ACTIVE", "SUPERSEDED"]
ROUTE_PLAN_STATUSES = ["ACTIVE", "SUPERSEDED"]
OPENING_PLAN_STATUSES = ["PLANNED", "LOCKED", "EXECUTED", "CANCELLED"]
STUDY_STATUSES = ["DRAFT", "FINAL", "SUPERSEDED"]
RECOMMENDATIONS = ["PROCEED", "MITIGATE", "BLOCKED"]
CAPITAL_PROJECT_KINDS = ["REMODEL", "RELOCATION", "NEW_BUILD"]
CAPITAL_PROJECT_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CANCELLED"]
EVENT_TYPES = [
    "PROGRAM_ACTIVATED",
    "PROGRAM_DEACTIVATED",
    "PROGRAM_CLOSED",
    "TRADE_AREA_QUALIFIED",
    "STORE_OPENED",
]


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_rollout(data: dict):
    _assert_common_fields(data, "Rollout")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["new_build_capital_budget_cents"], int)
    assert data["status"] in ROLLOUT_STATUSES
    assert isinstance(data["committed_capital_cents"], int)
    assert isinstance(data["available_capital_cents"], int)
    assert isinstance(data["event_log_cursor"], int)


def assert_capital_invariant(program: dict):
    """Committed plus available capital always equals the budget."""
    assert (
        program["committed_capital_cents"] + program["available_capital_cents"]
        == program["new_build_capital_budget_cents"]
    ), (
        f"committed {program['committed_capital_cents']} + available "
        f"{program['available_capital_cents']} != budget "
        f"{program['new_build_capital_budget_cents']}"
    )


def assert_trade_area(data: dict):
    _assert_common_fields(data, "TradeArea")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["drive_time_minutes"], int)
    assert isinstance(data["household_count"], int) and data["household_count"] > 0
    assert isinstance(data["median_household_income_cents"], int)
    assert 0 <= data["grocery_gap_pct"] <= 100
    assert data["status"] in TRADE_AREA_STATUSES
    assert isinstance(data["screening_count"], int)


def assert_store(data: dict):
    _assert_common_fields(data, "Store")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in STORE_STATUSES


def assert_developer(data: dict):
    _assert_common_fields(data, "Developer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["active_agreement_count"], int)


def assert_site_agreement(data: dict):
    _assert_common_fields(data, "SiteControlAgreement")
    assert is_iso8601_timestamp(data.get("committed_delivery_date", ""))
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["earnest_money_cents"], int)
    assert data["status"] in AGREEMENT_STATUSES
    assert isinstance(data["late_days"], int)
    assert isinstance(data["penalty_cents"], int)


def assert_distribution_center(data: dict):
    _assert_common_fields(data, "DistributionCenter")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["store_capacity"], int) and data["store_capacity"] > 0
    assert isinstance(data["assigned_store_count"], int)
    assert isinstance(data["remaining_capacity"], int)
    assert data["remaining_capacity"] == data["store_capacity"] - data["assigned_store_count"]


def assert_dc_assignment(data: dict):
    _assert_common_fields(data, "DCAssignment")
    assert data["stem_miles"] > 0
    assert isinstance(data["deliveries_per_week"], int) and data["deliveries_per_week"] >= 1
    assert data["status"] in ASSIGNMENT_STATUSES
    assert isinstance(data["stem_cost_cents_per_week"], int)


def assert_route_plan(data: dict):
    _assert_common_fields(data, "RoutePlan")
    assert isinstance(data["deliveries_per_week"], int) and data["deliveries_per_week"] >= 1
    assert isinstance(data["cases_per_truck"], int)
    assert isinstance(data["weekly_cost_cents"], int)
    assert data["status"] in ROUTE_PLAN_STATUSES


def assert_opening_plan(data: dict):
    _assert_common_fields(data, "OpeningPlan")
    assert is_iso8601_timestamp(data.get("opening_date", ""))
    assert is_iso8601_timestamp(data.get("fixture_kit_ship_date", ""))
    assert is_iso8601_timestamp(data.get("inventory_push_date", ""))
    assert isinstance(data["peak_season"], bool)
    assert isinstance(data["labor_hours"], int)
    assert isinstance(data["labor_cost_cents"], int)
    assert data["status"] in OPENING_PLAN_STATUSES


def assert_cannibalization_study(data: dict):
    _assert_common_fields(data, "CannibalizationStudy")
    assert isinstance(data["overlap_entries"], list)
    assert data["recommendation"] in RECOMMENDATIONS
    assert data["status"] in STUDY_STATUSES


def assert_rollout_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "RolloutEvent.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "RolloutEvent.created_at must be ISO 8601"
    )
    # Append-only: no updated_at, no version.
    assert "updated_at" not in data, "RolloutEvent must not carry updated_at"
    assert "version" not in data, "RolloutEvent must not carry version"
    assert isinstance(data["sequence_number"], int)
    assert data["event_type"] in EVENT_TYPES


def assert_capital_project(data: dict):
    _assert_common_fields(data, "CapitalProject")
    assert data["kind"] in CAPITAL_PROJECT_KINDS
    assert data["status"] in CAPITAL_PROJECT_STATUSES
