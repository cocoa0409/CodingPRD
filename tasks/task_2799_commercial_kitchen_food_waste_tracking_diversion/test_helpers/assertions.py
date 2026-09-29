"""Shape assertions for every resource and the platform's two conservation identities."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: Dict[str, Any], versioned: bool = True) -> None:
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']}"
    assert is_iso8601_timestamp(data["created_at"]), f"created_at malformed: {data['created_at']}"
    if versioned:
        assert is_iso8601_timestamp(data["updated_at"]), f"updated_at malformed: {data['updated_at']}"
        assert isinstance(data["version"], int) and data["version"] >= 1


def assert_timestamp_has_three_fractional_digits(value: str) -> None:
    """Every timestamp the service emits is ISO 8601 UTC with exactly three fractional digits."""
    assert value.endswith("Z"), f"timestamp does not end in Z: {value}"
    assert "." in value, f"timestamp carries no fractional digits: {value}"
    fraction = value.split(".")[1][:-1]
    assert len(fraction) == 3, f"timestamp does not carry exactly three fractional digits: {value}"


def assert_decimal_places(value: float, places: int) -> None:
    assert value is not None
    quantised = round(float(value), places)
    assert abs(float(value) - quantised) < 1e-9, f"{value} is not rounded to {places} decimal places"


def assert_site(data: Dict[str, Any]) -> None:
    _assert_common(data)
    for field in ("name", "site_code", "region_code", "coaching_posture"):
        assert isinstance(data[field], str)
    for field in (
        "total_captured_weight_grams",
        "valued_waste_cost_cents",
        "diverted_weight_grams_settled",
        "open_alert_count",
    ):
        assert isinstance(data[field], int), f"{field} is not an integer"
    assert data["coaching_posture"] in ("MONITORING", "INTERVENTION", "ESCALATED")
    assert_decimal_places(data["target_intensity_kg_per_1k_meals"], 3)
    if data["diversion_rate_pct"] is not None:
        assert_decimal_places(data["diversion_rate_pct"], 2)


def assert_tracking_station(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert data["station_kind"] in ("PREP", "HOT_LINE", "DISH_RETURN")
    assert data["status"] in ("ACTIVE", "MAINTENANCE", "RETIRED")
    assert isinstance(data["tare_grams"], int) and data["tare_grams"] >= 0
    assert isinstance(data["capture_lock_seconds"], int)
    assert 0 <= data["capture_lock_seconds"] <= 600
    assert is_iso8601_timestamp(data["calibration_due_at"])


def assert_food_type(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["category"] in ("PRODUCE", "PROTEIN", "PREPARED", "BAKERY", "DAIRY")
    assert isinstance(data["default_cost_per_kg_cents"], int) and data["default_cost_per_kg_cents"] > 0
    for flag in ("donation_eligible", "animal_feed_eligible", "compostable"):
        assert isinstance(data[flag], bool), f"{flag} is not a boolean"
    assert isinstance(data["donation_shelf_life_hours"], int) and data["donation_shelf_life_hours"] >= 0


def assert_recipe(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PUBLISHED")
    assert isinstance(data["ingredients"], list) and len(data["ingredients"]) >= 1
    assert isinstance(data["total_ingredient_cost_cents"], int)
    assert isinstance(data["cost_per_kg_cents"], int)
    assert_decimal_places(data["usable_yield_kg"], 3)
    if data["status"] == "DRAFT":
        assert data["published_cost_per_kg_cents"] is None
        assert data["published_at"] is None
    else:
        assert isinstance(data["published_cost_per_kg_cents"], int)
        assert is_iso8601_timestamp(data["published_at"])


def assert_shift(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert data["shift_code"] in ("AM", "PM", "NIGHT")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["meals_served"], int) and data["meals_served"] >= 0
    assert isinstance(data["shift_waste_grams"], int)
    if data["waste_intensity_kg_per_1k_meals"] is not None:
        assert_decimal_places(data["waste_intensity_kg_per_1k_meals"], 3)
    if data["pre_consumer_share_pct"] is not None:
        assert_decimal_places(data["pre_consumer_share_pct"], 4)
    if data["capture_compliance_pct"] is not None:
        assert_decimal_places(data["capture_compliance_pct"], 4)
    if data["status"] == "OPEN":
        assert data["closed_at"] is None
        assert data["leaderboard_score"] is None
    else:
        assert is_iso8601_timestamp(data["closed_at"])
        assert_decimal_places(data["leaderboard_score"], 1)
        assert 0.0 <= data["leaderboard_score"] <= 100.0


def assert_waste_entry(data: Dict[str, Any]) -> None:
    _assert_common(data)
    for field in ("site_id", "station_id", "shift_id", "food_type_id"):
        assert is_valid_uuid(data[field]), f"{field} is not a UUID"
    assert data["status"] in ("RECORDED", "FLAGGED", "VOIDED", "SUPERSEDED")
    assert data["stream"] in ("PRE_CONSUMER", "POST_CONSUMER")
    assert data["loss_reason"] in (
        "OVERPRODUCTION",
        "SPOILAGE",
        "TRIM",
        "EXPIRATION",
        "PLATE_WASTE",
        "CONTAMINATION",
    )
    assert isinstance(data["weight_grams"], int)
    assert 0 < data["weight_grams"] <= 200000
    assert is_iso8601_timestamp(data["captured_at"])
    assert is_iso8601_timestamp(data["capture_window_end"])
    for field in ("catalog_cost_basis_cents", "provisional_cost_cents", "effective_cost_cents"):
        assert isinstance(data[field], int), f"{field} is not an integer"
    assert_gram_conservation(data)


def assert_baseline_period(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert data["status"] in ("OPEN", "SUBMITTED", "CERTIFIED")
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0
    assert isinstance(data["baseline_entry_count"], int)
    assert isinstance(data["baseline_waste_grams"], int)
    assert isinstance(data["baseline_cost_cents"], int)
    assert isinstance(data["baseline_meals_served"], int)
    if data["baseline_waste_kg"] is not None:
        assert_decimal_places(data["baseline_waste_kg"], 3)
    if data["baseline_intensity_kg_per_1k_meals"] is not None:
        assert_decimal_places(data["baseline_intensity_kg_per_1k_meals"], 3)


def assert_reduction_target(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["baseline_period_id"])
    assert data["basis"] in ("ABSOLUTE", "INTENSITY")
    assert data["status"] in ("PROPOSED", "ACTIVE", "ACHIEVED", "MISSED", "SUPERSEDED")
    assert data["attainment_state"] in ("BEHIND", "ACHIEVED_PENDING")
    assert_decimal_places(data["target_reduction_pct"], 2)
    assert_decimal_places(data["min_diversion_rate_pct"], 2)
    assert isinstance(data["performance_waste_grams"], int)
    assert isinstance(data["performance_meals_served"], int)
    for field in ("absolute_reduction_pct", "intensity_reduction_pct", "effective_reduction_pct"):
        if data[field] is not None:
            assert_decimal_places(data[field], 2)


def assert_hauler(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in ("PENDING", "APPROVED")
    assert isinstance(data["channels"], list) and len(data["channels"]) >= 1
    for channel in data["channels"]:
        assert channel in ("DONATION", "ANIMAL_FEED", "COMPOST", "LANDFILL")
    assert isinstance(data["rate_cents_per_tonne"], int) and data["rate_cents_per_tonne"] > 0
    assert isinstance(data["stop_fee_cents"], int) and data["stop_fee_cents"] >= 0
    assert isinstance(data["max_concurrent_pickups"], int) and data["max_concurrent_pickups"] >= 1


def assert_consignment(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["hauler_id"])
    assert data["channel"] in ("DONATION", "ANIMAL_FEED", "COMPOST", "LANDFILL")
    assert data["logistics_status"] in ("DRAFT", "STAGED", "DISPATCHED", "COMPLETED", "CANCELLED")
    assert data["settlement_status"] in ("UNBILLED", "TICKET_SUBMITTED", "SETTLED", "DISPUTED")
    assert isinstance(data["staged_weight_grams"], int)
    assert isinstance(data["line_count"], int)
    assert isinstance(data["container_tare_grams"], int)
    assert is_iso8601_timestamp(data["pickup_window_start"])
    assert is_iso8601_timestamp(data["pickup_window_end"])


def assert_consignment_line(data: Dict[str, Any]) -> None:
    """A line is an immutable event record: it has neither ``updated_at`` nor ``version``."""
    _assert_common(data, versioned=False)
    assert is_valid_uuid(data["consignment_id"])
    assert is_valid_uuid(data["waste_entry_id"])
    assert isinstance(data["allocated_weight_grams"], int) and data["allocated_weight_grams"] >= 1
    assert "updated_at" not in data, "an allocation line must not carry updated_at"
    assert "version" not in data, "an allocation line must not carry version"


def assert_hauler_ticket(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["consignment_id"])
    assert is_valid_uuid(data["hauler_id"])
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "DISPUTED")
    for field in (
        "gross_weight_grams",
        "net_weight_grams",
        "base_haul_fee_cents",
        "fuel_surcharge_cents",
        "settlement_subtotal_cents",
        "variance_credit_cents",
        "settlement_total_cents",
    ):
        assert isinstance(data[field], int), f"{field} is not an integer"
    assert_decimal_places(data["billable_tonnes"], 4)
    assert data["fuel_surcharge_pct"] in (0.00, 0.06, 0.09)
    if data["variance_pct"] is not None:
        assert_decimal_places(data["variance_pct"], 2)


def assert_coaching_alert(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert is_valid_uuid(data["shift_id"])
    assert data["alert_type"] in ("INTENSITY_BREACH", "OVERPRODUCTION_SPIKE")
    assert data["severity"] in ("MEDIUM", "HIGH")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED", "AUTO_RESOLVED", "EXPIRED")
    assert isinstance(data["message"], str) and data["message"]
    if data["observed_intensity"] is not None:
        assert_decimal_places(data["observed_intensity"], 3)


def assert_data_quality_finding(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data["site_id"])
    assert data["finding_type"] in ("MISSED_CAPTURE", "DUPLICATE_ENTRY", "WEIGHT_OUTLIER")
    assert data["status"] in ("OPEN", "CONFIRMED", "DISMISSED")
    assert is_iso8601_timestamp(data["detected_at"])
    assert isinstance(data["detail"], str) and data["detail"]


def assert_corporate_rollup(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PUBLISHED")
    assert isinstance(data["site_ids"], list) and len(data["site_ids"]) >= 1
    assert data["in_scope_site_count"] == len(data["site_ids"])
    for field in (
        "total_captured_weight_grams",
        "total_valued_cost_cents",
        "total_diverted_weight_grams",
        "sites_on_track_count",
    ):
        assert isinstance(data[field], int), f"{field} is not an integer"
    assert data["goal_attainment_state"] in ("ALL_ON_TRACK", "NONE_ON_TRACK", "PARTIAL")
    if data["diversion_rate_pct"] is not None:
        assert_decimal_places(data["diversion_rate_pct"], 2)


# --- the platform's two conservation identities -------------------------------
def assert_gram_conservation(entry: Dict[str, Any]) -> None:
    """For every capture, ``weight_grams`` equals routed plus unrouted grams."""
    assert entry["weight_grams"] == entry["routed_weight_grams"] + entry["unrouted_weight_grams"], (
        f"gram conservation broken on entry {entry['id']}: "
        f"{entry['weight_grams']} != {entry['routed_weight_grams']} + {entry['unrouted_weight_grams']}"
    )


def assert_site_cost_ledger(site: Dict[str, Any], entries: List[Dict[str, Any]]) -> None:
    """A site's valued cost equals the summed effective cost of its RECORDED-or-FLAGGED captures."""
    expected = sum(e["effective_cost_cents"] for e in entries if e["status"] in ("RECORDED", "FLAGGED"))
    assert site["valued_waste_cost_cents"] == expected, (
        f"site cost ledger drifted: {site['valued_waste_cost_cents']} != {expected}"
    )


def assert_effective_cost_selection(entry: Dict[str, Any]) -> None:
    """``effective_cost_cents`` is the final figure when non-null and the provisional one otherwise."""
    expected = entry["final_cost_cents"] if entry["final_cost_cents"] is not None else entry["provisional_cost_cents"]
    assert entry["effective_cost_cents"] == expected


def assert_coaching_posture_ladder(site: Dict[str, Any]) -> None:
    """The posture is derived purely from the open alert count."""
    count = site["open_alert_count"]
    expected = "MONITORING" if count == 0 else ("ESCALATED" if count >= 3 else "INTERVENTION")
    assert site["coaching_posture"] == expected, (
        f"posture {site['coaching_posture']} does not match open_alert_count {count}"
    )


def assert_version_bumped_by(previous: Dict[str, Any], current: Dict[str, Any], amount: int = 1) -> None:
    assert current["version"] == previous["version"] + amount, (
        f"version moved from {previous['version']} to {current['version']}, expected +{amount}"
    )


def assert_settlement_breakdown(
    ticket: Dict[str, Any],
    net_weight_grams: int,
    billable_tonnes: float,
    base_haul_fee_cents: int,
    fuel_surcharge_pct: float,
    fuel_surcharge_cents: int,
    settlement_subtotal_cents: int,
    variance_pct: Optional[float],
    variance_credit_cents: int,
    settlement_total_cents: int,
) -> None:
    """Assert the whole seven-step pricing pass in one call."""
    assert ticket["net_weight_grams"] == net_weight_grams
    assert ticket["billable_tonnes"] == billable_tonnes
    assert ticket["base_haul_fee_cents"] == base_haul_fee_cents
    assert ticket["fuel_surcharge_pct"] == fuel_surcharge_pct
    assert ticket["fuel_surcharge_cents"] == fuel_surcharge_cents
    assert ticket["settlement_subtotal_cents"] == settlement_subtotal_cents
    assert ticket["variance_pct"] == variance_pct
    assert ticket["variance_credit_cents"] == variance_credit_cents
    assert ticket["settlement_total_cents"] == settlement_total_cents
