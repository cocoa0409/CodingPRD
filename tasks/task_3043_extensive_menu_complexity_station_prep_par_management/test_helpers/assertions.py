"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name} id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name} created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_name} updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_name} version must be int"


def assert_restaurant(data: dict):
    _assert_common(data, "Restaurant")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["weekly_bakery_budget_cents"], int)
    assert isinstance(data["weekly_bakery_budget_spent_cents"], int)
    assert isinstance(data["current_waitlist_minutes"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_menu_revision(data: dict):
    _assert_common(data, "MenuRevision")
    assert isinstance(data["restaurant_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["review_cycle_count"], int)
    assert data["status"] in (
        "DRAFT", "IN_REVIEW", "APPROVED", "PUBLISHED", "SUPERSEDED")


def assert_recipe(data: dict):
    _assert_common(data, "Recipe")
    assert isinstance(data["menu_revision_id"], str)
    assert data["station_type"] in ("GRILL", "SAUTE", "FRY", "BAKERY", "COLD")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_prep_item(data: dict):
    _assert_common(data, "PrepItem")
    assert isinstance(data["name"], str)
    assert data["station_type"] in ("GRILL", "SAUTE", "FRY", "BAKERY", "COLD")
    assert data["shelf_life_hours"] > 0
    assert data["min_batch_size"] > 0
    assert data["batch_unit"] in ("OZ", "EA", "ML")
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_station(data: dict):
    _assert_common(data, "Station")
    assert data["station_type"] in ("GRILL", "SAUTE", "FRY", "BAKERY", "COLD")
    assert data["rack_slot_capacity"] > 0
    assert data["par_health"] in ("OK", "BELOW_PAR", "CRITICAL")


def assert_station_par(data: dict):
    _assert_common(data, "StationPar")
    assert isinstance(data["station_id"], str)
    assert isinstance(data["prep_item_id"], str)
    assert data["par_quantity"] >= 0
    assert data["adjustment_status"] in ("NONE", "PENDING", "APPROVED", "REJECTED")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_cook(data: dict):
    _assert_common(data, "Cook")
    assert isinstance(data["restaurant_id"], str)
    assert isinstance(data["certified_station_types"], list)
    assert isinstance(data["weekly_scheduled_minutes"], int)
    assert data["status"] in ("ACTIVE", "RETRAINING_REQUIRED", "INACTIVE")


def assert_demand_forecast(data: dict):
    _assert_common(data, "DemandForecast")
    assert isinstance(data["restaurant_id"], str)
    assert data["expected_covers"] > 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "FINALIZED")


def assert_prep_list(data: dict):
    _assert_common(data, "PrepList")
    assert isinstance(data["restaurant_id"], str)
    assert isinstance(data["demand_forecast_id"], str)
    assert isinstance(data["lines"], list)
    assert isinstance(data["total_rounded_quantity"], int)
    assert data["status"] in (
        "DRAFT", "GENERATED", "LOCKED", "IN_PROGRESS", "COMPLETED", "SUPERSEDED")


def assert_prep_batch(data: dict):
    _assert_common(data, "PrepBatch")
    assert isinstance(data["prep_list_id"], str)
    assert isinstance(data["prep_item_id"], str)
    assert isinstance(data["station_id"], str)
    assert data["quantity"] > 0
    assert isinstance(data["consumed_quantity"], int)
    assert isinstance(data["wasted_quantity"], int)
    assert data["status"] in (
        "PLANNED", "PREPPED", "DEPLETED", "EXPIRED", "WASTED", "CANCELLED")


def assert_shift_assignment(data: dict):
    _assert_common(data, "ShiftAssignment")
    assert isinstance(data["cook_id"], str)
    assert isinstance(data["station_id"], str)
    assert data["status"] in (
        "SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_bakery_order(data: dict):
    _assert_common(data, "BakeryOrder")
    assert data["cheesecake_type"] in (
        "ORIGINAL", "CHOCOLATE", "STRAWBERRY", "SEASONAL")
    assert data["whole_cakes_ordered"] > 0
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "CONFIRMED", "PARTIALLY_RECEIVED",
        "RECEIVED", "RECONCILED", "CANCELLED")


def assert_waste_entry(data: dict):
    _assert_common(data, "WasteEntry")
    assert isinstance(data["station_id"], str)
    assert isinstance(data["prep_batch_id"], str)
    assert data["quantity"] > 0
    assert data["reason"] in ("OVER_PREP", "EXPIRED", "QUALITY", "SPILLAGE")
    assert data["status"] in ("RECORDED", "ATTRIBUTED")


def assert_service_ticket(data: dict):
    _assert_common(data, "ServiceTicket")
    assert isinstance(data["restaurant_id"], str)
    assert isinstance(data["items"], list)
    assert data["allergen_review_status"] in (
        "NOT_REQUIRED", "PENDING", "CLEARED")
    assert data["fire_status"] in ("OPEN", "FIRED", "READY", "SERVED", "VOIDED")
    assert isinstance(data["recall_count"], int)


def find_line(prep_list_data: dict, prep_item_id: str) -> dict:
    """Return the computed line for a prep item on a generated list."""
    for line in prep_list_data["lines"]:
        if line.get("prep_item_id") == prep_item_id:
            return line
    raise AssertionError(
        f"No prep-list line found for prep item {prep_item_id}: "
        f"{prep_list_data['lines']}")
