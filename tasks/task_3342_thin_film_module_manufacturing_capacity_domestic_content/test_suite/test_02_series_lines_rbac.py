"""Module-series registration rules, production-line registration, and RBAC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_module_series,
    assert_production_line,
    create_module_series_payload,
    create_production_line_payload,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
CO = TEST_USERS["contracts_officer_headers"]


def test_module_series_default_status_active(api):
    """PRD §3.1: "A series is born with `status` `ACTIVE`; when a series becomes
    `DISCONTINUED` it rejects new reservation bookings and activations (§3.4)."

    Design: Corner/entities/module_series_default_status_active
    """
    resp = api.create_module_series(create_module_series_payload(), PM)
    data = validate_success(resp, 201)
    assert_module_series(data)
    assert data["status"] == "ACTIVE"


def test_module_series_bin_fractions_must_sum_one(api):
    """PRD §3.1: "The `bin_profile` is an array of entries each carrying a
    `bin_code`, a `wattage`, and a `fraction`; the fractions must sum to exactly
    1.0 and the bins are ordered by wattage descending — a profile whose
    fractions do not sum to 1.0 is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/module_series_bin_fractions_must_sum_one
    """
    payload = create_module_series_payload(
        series_code="BAD",
        bin_profile=[
            {"bin_code": "B1", "wattage": 480.0, "fraction": 0.7},
            {"bin_code": "B2", "wattage": 470.0, "fraction": 0.4},
        ],
    )
    resp = api.create_module_series(payload, PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_line_initial_state_commissioning(api):
    """PRD §3.2: "A new line enters in `COMMISSIONING` status with
    `ramp_quarter_index` set to 0 and `actual_yield_rate` null (no quarter has
    closed yet)."

    Design: Corner/state_machines/line_initial_state_commissioning
    """
    resp = api.create_production_line(create_production_line_payload(), PM)
    data = validate_success(resp, 201)
    assert_production_line(data)
    assert data["status"] == "COMMISSIONING"
    assert data["ramp_quarter_index"] == 0
    assert data.get("actual_yield_rate") is None


def test_plant_manager_creates_production_line(api):
    """PRD §3.2: "A `PlantManager` registers a production line with a unique
    `line_code` (for example OH-L3 or TX-L1), a `site_country` as an ISO 3166-1
    alpha-2 country code, and an `annual_capacity_mw` nameplate greater than
    zero."

    Design: Corner/rbac/plant_manager_creates_production_line
    """
    resp = api.create_production_line(
        create_production_line_payload(line_code="OH-L3"), PM
    )
    data = validate_success(resp, 201)
    assert data["line_code"] == "OH-L3"


def test_contracts_officer_cannot_create_line(api):
    """PRD §2.1: "A request whose role is not permitted for the endpoint is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.2: "A `PlantManager` registers a production line with a unique
    `line_code` (for example OH-L3 or TX-L1), a `site_country` as an ISO 3166-1
    alpha-2 country code, and an `annual_capacity_mw` nameplate greater than
    zero."

    Design: Corner/rbac/contracts_officer_cannot_create_line
    """
    resp = api.create_production_line(create_production_line_payload(), CO)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
