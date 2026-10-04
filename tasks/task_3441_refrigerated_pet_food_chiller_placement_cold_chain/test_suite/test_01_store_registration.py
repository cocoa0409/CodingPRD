"""Store registration and request-shape corner cases (PRD §2.1, §2.5, §3.1, §3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_chiller,
    assert_store,
    create_site_evaluation_payload,
    create_store,
    create_store_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
)


def test_store_created_returns_201_with_fields(api, platform_admin_headers):
    """PRD §2.5: "`version` (integer): a system-managed integer that increments
    by exactly 1 on every mutation of the resource, including mutations caused
    by cascade side effects originating on another entity."
    PRD §2.4: "At server startup the logical clock reads exactly
    `2026-09-01T00:00:00Z`; until it is explicitly set, every time-dependent
    rule evaluates against that default, and the clock never silently falls
    back to the host's wall clock."

    Design: Corner/entities/store_created_returns_201_with_fields
    """
    payload = create_store_payload(
        name="Corner Store", region="US-SE", demographic_index=50,
        weekly_category_velocity_index=55, competitor_density_index=30,
        available_sqft=60, distance_miles_from_plant=4.5,
    )
    resp = api.create_store(payload, platform_admin_headers)
    data = validate_success(resp, expected_status=201)
    assert_store(data)
    for field, value in payload.items():
        assert data[field] == value, f"field {field} must echo the input: expected {value!r}, got {data[field]!r}"
    assert is_valid_uuid(data["id"])
    assert data["version"] == 1
    assert data["created_at"] == data["updated_at"], "fresh resource: created_at == updated_at"
    assert data["created_at"].startswith("2026-09-01"), (
        f"created_at must reflect the logical-clock startup default, got {data['created_at']}"
    )


def test_get_store_not_found_returns_404(api, platform_admin_headers):
    """PRD §2.7: "Existence. Unresolvable path identifiers or body foreign keys
    yield 404 `ERR_NOT_FOUND`, left to right per §2.6."

    Design: Corner/entities/get_store_not_found_returns_404
    """
    resp = api.get_store(NON_EXISTENT_UUID, platform_admin_headers)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404
    assert err["error_id"] == "ERR_NOT_FOUND"


def test_create_store_missing_required_field_returns_400(api, platform_admin_headers):
    """PRD §2.7: "A malformed body, an undeclared payload field, a missing
    required field, or a scalar range violation (a non-positive
    `quantity_units`, a `temp_c` outside the sensor-plausible range, an
    `end_date` earlier than `start_date`, a future `recorded_at` or
    `produced_at`, an enum value outside its declared set) yields 400
    `ERR_VALIDATION`."

    Design: Corner/entities/create_store_missing_required_field_returns_400
    """
    payload = create_store_payload(name="No Demo")
    del payload["demographic_index"]
    resp = api.create_store(payload, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert resp.status_code == 400


def test_chiller_batch_mints_sequential_serials(api, production_planner_headers):
    """PRD §3.3: "The system mints each unit's `serial_no` as the prefix, a
    hyphen, and a 4-digit zero-padded sequence number — for example `FP-0007`.
    Numbering starts at `serial_start_seq` when the caller supplies it, and
    otherwise at the next free sequence for that prefix."
    PRD §3.3: "Derived unit economics are fixed by model: a `STANDARD` chiller
    holds 240 units of product on a `footprint_sqft` of 8, while a `COMPACT`
    holds 120 units on 5 square feet."

    Design: Corner/entities/chiller_batch_mints_sequential_serials
    """
    resp = api.create_chillers({"model": "COMPACT", "serial_prefix": "SN", "quantity": 2},
                               production_planner_headers)
    data = validate_success(resp, expected_status=201)
    assert len(data) == 2, "batch of 2 must return two chiller rows"
    assert data[0]["serial_no"] == "SN-0001"
    assert data[1]["serial_no"] == "SN-0002"
    for row in data:
        assert_chiller(row)
        assert row["capacity_units"] == 120 and row["footprint_sqft"] == 5
        assert row["status"] == "IN_STOCK"
        assert row["version"] == 1


def test_site_evaluation_spoofed_composite_score_returns_400(api, placement_manager_headers):
    """PRD §2.7: "A malformed body, an undeclared payload field, a missing
    required field, or a scalar range violation (a non-positive
    `quantity_units`, a `temp_c` outside the sensor-plausible range, an
    `end_date` earlier than `start_date`, a future `recorded_at` or
    `produced_at`, an enum value outside its declared set) yields 400
    `ERR_VALIDATION`."

    Design: Corner/entities/site_evaluation_spoofed_composite_score_returns_400
    """
    store = create_store()
    payload = create_site_evaluation_payload()
    payload["composite_score"] = 99.99  # server-computed field: undeclared on input
    resp = api.create_site_evaluation(store["id"], payload, placement_manager_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert resp.status_code == 400
