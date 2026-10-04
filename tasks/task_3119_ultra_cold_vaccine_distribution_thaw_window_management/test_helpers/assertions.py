"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

# Append-only records carry only id and created_at.
APPEND_ONLY_FIELDS = {"created_at"}
FULL_FIELDS = {"created_at", "updated_at", "version"}


def _assert_common(data: dict, fields=FULL_FIELDS):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    if "updated_at" in fields:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
        assert isinstance(data.get("version"), int), "version must be a system-managed integer"


def assert_product_configuration(data: dict):
    _assert_common(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["presentation"] in ("SINGLE_DOSE_VIAL", "MULTI_DOSE_VIAL")
    assert isinstance(data["doses_per_vial"], int)
    assert data["doses_per_carton"] == data["doses_per_vial"] * data["vials_per_carton"]
    assert isinstance(data["min_order_cartons"], int)


def assert_jurisdiction_program(data: dict):
    _assert_common(data)
    assert len(data["jurisdiction_code"]) == 2
    assert data["allocation_basis"] in ("POPULATION_SHARE", "FIXED_QUANTITY")
    assert data["standing_status"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["credit_balance_cartons"] >= 0, "the credit floor is 0"
    assert isinstance(data["released_cartons_to_date"], int)
    assert isinstance(data["lapsed_carton_count"], int)


def assert_allocation_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "RELEASED", "ALLOCATED", "DEPLETED", "EXPIRED", "RECALLED")
    assert data["unallocated_cartons"] == data["released_cartons"] - data["allocated_cartons"]
    assert data["unallocated_cartons"] >= 0


def assert_allocation_window(data: dict):
    _assert_common(data)
    assert data["status"] in ("ANNOUNCED", "OPEN", "CLOSED")
    assert isinstance(data["requested_cartons"], int)
    assert isinstance(data["accepted_cartons"], int)


def assert_allocation_entitlement(data: dict):
    _assert_common(data)
    assert data["acceptance_status"] in ("PENDING", "PARTIALLY_ACCEPTED", "FULFILLED", "LAPSED")
    assert data["available_cartons"] == data["computed_cartons"] - data["held_cartons"]
    assert data["available_cartons"] >= 0
    if data["computed_cartons"] > 0:
        expected = round(data["accepted_cartons"] / data["computed_cartons"], 4)
        assert abs(data["release_rate"] - expected) < 1e-9


def assert_site_order(data: dict):
    _assert_common(data)
    assert data["order_status"] in (
        "DRAFT", "SUBMITTED", "ACCEPTED", "PARTIALLY_ACCEPTED", "REJECTED", "FULFILLED")
    assert data["payment_status"] in ("NOT_DUE", "DUE", "DISPUTED")
    assert data["accepted_doses"] == data["accepted_cartons"] * 1170 or data["accepted_cartons"] == 0
    assert data["materialization_variance_doses"] == data["accepted_doses"] - data["requested_doses"]


def assert_storage_site(data: dict):
    _assert_common(data)
    assert data["storage_capability"] in ("ULTRA_COLD", "REFRIGERATED", "AMBIENT_ONLY")
    assert data["cold_chain_equipment_type"] in ("ULTRA_COLD_FREEZER", "THERMAL_SHIPPER")
    assert isinstance(data["equipment_certified"], bool)
    assert data["inventory_status"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["reported_entry_type"] in ("ULTRA_COLD", "REFRIGERATED")
    assert isinstance(data["usable_doses"], int)
    assert isinstance(data["open_excursion_count"], int)


def assert_site_equipment_verification(data: dict):
    _assert_common(data)
    assert data["equipment_type"] in ("ULTRA_COLD_FREEZER", "THERMAL_SHIPPER", "DATA_LOGGER")
    assert data["outcome"] in ("PASSED", "FAILED")
    assert data["status"] in ("RECORDED", "INVALIDATED")


def assert_dispatch_order(data: dict):
    _assert_common(data)
    assert data["entry_route"] in ("DIRECT_ULTRA_COLD", "THAW_AT_HUB")
    assert data["status"] in ("DRAFT", "PACKED", "IN_TRANSIT", "DELIVERED", "REJECTED_AT_DOCK")
    assert isinstance(data["freeze_required"], bool)


def assert_cold_chain_shipper(data: dict):
    _assert_common(data)
    assert data["packing_status"] in (
        "PREPARING", "SEALED", "IN_TRANSIT", "RECEIVED", "RELEASED", "HELD")
    if data["hold_reason"] is not None:
        assert data["hold_reason"] in (
            "MISSING_LOGGER", "INSUFFICIENT_DRY_ICE", "LATE_PACKING", "LATE_READING")
    assert data["dry_ice_deficit_kg"] >= 0


def assert_temperature_logger_reading(data: dict):
    """Append-only and immutable: no updated_at, no version."""
    _assert_common(data, APPEND_ONLY_FIELDS)
    assert "updated_at" not in data
    assert "version" not in data
    assert data["source"] in ("LOGGER", "MANUAL")
    assert isinstance(data["breach_minutes"], int) and data["breach_minutes"] >= 0


def assert_carton(data: dict):
    _assert_common(data)
    assert data["temperature_state"] in (
        "ULTRA_COLD", "THAWED", "REFRIGERATED", "PUNCTURED", "EXPIRED", "IN_TRANSIT",
        "PALLET_STAGED", "DESTROYED")
    assert data["doses_per_carton"] > 0
    assert isinstance(data["remaining_doses"], int)
    assert isinstance(data["administrative_remaining_doses"], int)
    assert data["administrative_remaining_doses"] >= 0
    assert isinstance(data["cumulative_released_doses"], int)
    assert data["dose_shortfall_doses"] >= 0


def assert_dose_ledger_entry(data: dict):
    """Append-only: id + created_at only; status moves on the parent carton."""
    _assert_common(data, APPEND_ONLY_FIELDS)
    assert "updated_at" not in data
    assert "version" not in data
    assert data["entry_type"] in (
        "RELEASE", "THAW", "TRANSFER_IN", "TRANSFER_OUT", "ADMINISTER", "PUNCTURE",
        "EXPIRE", "WASTE", "DESTROY", "REVERSE")
    assert data["status"] in ("RECORDED", "RECONCILED")


def assert_site_transfer(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DISPATCHED", "RECEIVED", "REJECTED", "CANCELLED")
    assert data["dest_required_entry_type"] in ("ULTRA_COLD", "REFRIGERATED")
    assert data["admissibility"] in ("ADMITTED", "NOT_ADMITTED")
    assert data["cumulative_conflict_minutes"] >= 0


def assert_temperature_excursion(data: dict):
    _assert_common(data)
    assert data["review_status"] in ("REPORTED", "UNDER_REVIEW", "ADJUDICATED")
    assert data["adjudication_status"] in ("PENDING", "USABLE", "NOT_USABLE")
    assert data["quarantine_status"] in ("OPEN", "LIFTED", "RETAINED", "DESTROYED")
    assert data["dose_impact_category"] in ("NONE", "VIAL_LEVEL", "DOSE_LEVEL")
    assert isinstance(data["min_duration_minutes"], int) and data["min_duration_minutes"] >= 0
    assert isinstance(data["exceeds_cumulative_cap"], bool)


def assert_excursion_adjudication(data: dict):
    _assert_common(data)
    assert data["outcome"] in ("USABLE", "NOT_USABLE")
    assert isinstance(data["certified_lost_doses"], int)
    assert isinstance(data["interim_lost_doses"], int)
    assert data["freeze_transitive_doses"] >= 0
    assert is_iso8601_timestamp(data.get("effective_from", ""))


def assert_doses_affected_slice(data: dict):
    _assert_common(data)
    assert data["closure_state"] in ("OPEN", "IN_REVIEW", "CLOSED")
    assert data["status"] in ("PENDING", "CERTIFIED")
    assert isinstance(data["doses_upper_bound"], int)


def assert_wastage_report(data: dict):
    _assert_common(data)
    assert data["dose_accountability_status"] in ("OPEN", "RECONCILED")
    assert data["attributed_cause"] in (
        "TEMPERATURE_EXCURSION", "PUNCTURE_EXPIRY", "THAW_WINDOW_BREACH",
        "REFRIGERATED_EXPIRY", "TRANSFER_REJECTION", "SITE_RETURN")
    assert data["reconciliation_variance_doses"] == \
        data["doses_reported"] - data["certified_doses"]


def assert_order_rejection(data: dict):
    _assert_common(data)
    assert data["reason_code"] in (
        "BELOW_MIN_ORDER", "NO_ENTITLEMENT", "CAPACITY_UNAVAILABLE", "SITE_NOT_READY", "WINDOW_CLOSED")


def assert_entitlement_release(data: dict):
    _assert_common(data)
    assert data["reason_code"] in (
        "WINDOW_LAPSE", "ORDER_REJECTION", "CAPACITY_UNAVAILABLE", "PROGRAM_REALLOCATION")
    assert data["status"] in ("RECORDED", "REALLOCATED")
    expected = "REALLOCATED" if data["reallocated_to_entitlement_id"] is not None else "RECORDED"
    assert data["status"] == expected


def assert_reporting_period(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "SUBMITTED")
    assert isinstance(data["report_version"], int) and data["report_version"] >= 1
    assert data["unaccounted_doses"] >= 0
    assert isinstance(data["wastage_rate_basis_points"], int)


def assert_program_standing(data: dict):
    _assert_common(data)
    assert data["propagation_mode"] in ("IMMEDIATE", "AFTER_CYCLE")
    assert data["risk_tier"] in (0, 1, 2)
    assert data["lapsed_carton_rate"] >= 0


def assert_shipping_window_lapse(data: dict):
    _assert_common(data)
    assert data["reason"] in ("ACCEPTANCE_WINDOW_CLOSED", "SITE_NOT_READY", "NO_ORDER_SUBMITTED")
    assert data["dose_reconciliation_status"] in ("PENDING", "RECONCILED")
    assert isinstance(data["lapsed_cartons"], int)


def assert_adjudication_appeal(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "ACCEPTED", "DENIED")


def assert_carton_storage_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "CONFIRMED", "RELEASED", "LAPSED")
    assert data["entry_type"] in ("ULTRA_COLD", "REFRIGERATED")
    assert data["temp_state"] in ("FROZEN", "THAWED")
    assert data["resolved_conflict_minutes"] >= 0


def assert_carton_family(data: dict):
    _assert_common(data)
    assert isinstance(data["shared_dose_count"], int)


# ── Domain invariants ─────────────────────────────────────────────────────

def assert_entitlement_carton_invariant(ent: dict, lapsed_cartons: int):
    """available + held + lapsed == computed at every step."""
    total = ent["available_cartons"] + ent["held_cartons"] + lapsed_cartons
    assert total == ent["computed_cartons"], (
        f"carton conservation broken: {total} != {ent['computed_cartons']}"
    )


def assert_release_conservation(carton: dict, administered_doses: int = 0):
    """cumulative_released_doses - remaining_doses - administered == 0 when settled."""
    drift = carton["cumulative_released_doses"] - carton["remaining_doses"] - administered_doses
    assert drift == 0, f"released-dose ledger drifted by {drift}"


def assert_program_invariants(data: dict):
    assert data["credit_balance_cartons"] >= 0
    assert data["released_cartons_to_date"] >= 0
    assert data["lapsed_carton_count"] >= 0