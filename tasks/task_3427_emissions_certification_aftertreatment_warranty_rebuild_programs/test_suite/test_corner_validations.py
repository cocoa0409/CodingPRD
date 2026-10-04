"""Corner coverage — validations, part 1 (PRD §2.1 header gate, §2.8
existence gate, §3.1 standard windows and supersession, §3.2 family window
and standard-state gates, §3.4 in-service dating, §3.5 odometer and
telematics monotonicity).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_maintenance_record,
    create_draft_standard,
    create_engine_family_payload,
    create_engine_unit_payload,
    create_maintenance_record_payload,
    create_published_standard,
    create_regulation_standard_payload,
    get_unit,
    ingest_snapshot,
    make_fleet_manager_headers,
    publish_standard,
    set_logical_clock,
    setup_engine_unit,
    setup_family_in_production,
    setup_fleet,
    supersede_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _dt(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant comparison."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_missing_role_header_returns_unauthenticated_400(api, admin_headers):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which that user acts. If either header is missing, or if the role name is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    A create-standard request sent without the X-User-Role header fails 400
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER and no standard is created.

    Design: Corner/validations/missing_role_header_returns_unauthenticated_400
    """
    payload = create_regulation_standard_payload(code="X-1")
    resp = api.create_regulation_standard(
        payload, {"X-User-ID": "pa-admin-1", "Content-Type": "application/json"}
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    rows, meta = validate_paginated(api.list_regulation_standards(admin_headers))
    assert rows == [] and meta["total_count"] == 0, (
        f"no standard may be created by a headerless request, got {rows}"
    )


def test_existence_gate_fires_before_state_gate(api, engineer_headers):
    """PRD §2.8: "Existence: path identifiers first, then foreign-key identifiers in the body, validated left-to-right (`ERR_NOT_FOUND`)."
    PRD §2.8: "When several checks could reject the same request, the server evaluates them in a fixed order and reports only the first failure."

    begin-testing on a never-allocated family id returns 404 ERR_NOT_FOUND
    (existence), which the fixed order evaluates before any state
    precondition.

    Design: Corner/validations/existence_gate_fires_before_state_gate
    """
    resp = api.begin_testing(NON_EXISTENT_UUID, engineer_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_supersede_with_earlier_window_rejected(api, officer_headers):
    """PRD §3.1: "The named successor must resolve to an existing standard (`ERR_NOT_FOUND`, HTTP 404), must itself be `PUBLISHED` (`ERR_STANDARD_NOT_PUBLISHED`, HTTP 409), and must begin strictly later: the successor's `effective_model_year_first` must be strictly greater than the superseded standard's own `effective_model_year_first`, otherwise the request fails with `ERR_SUPERSESSION_WINDOW_INVALID` (HTTP 409). On success the superseded standard records the successor's id in its own `successor_standard_id`."

    A PUBLISHED 2024-2026 standard cannot succeed the PUBLISHED 2027-2030
    standard (2024 is not strictly later than 2027), even though the two
    published windows never overlapped.

    Design: Corner/validations/supersede_with_earlier_window_rejected
    """
    old = create_published_standard(
        code="EPA2024-HD", nox_limit_g_per_bhp_hr=0.40,
        effective_model_year_first=2024, effective_model_year_last=2026,
    )
    new = create_published_standard(
        code="EPA2027-HD",
        effective_model_year_first=2027, effective_model_year_last=2030,
    )

    resp = api.supersede_regulation_standard(
        new["id"], supersede_payload(old["id"]), officer_headers
    )
    validate_error(resp, ApiErrorId.ERR_SUPERSESSION_WINDOW_INVALID)

    new_now = validate_success(api.get_regulation_standard(new["id"], officer_headers))
    assert new_now["status"] == "PUBLISHED"
    assert new_now["successor_standard_id"] is None, (
        f"the rejected supersession records nothing, got {new_now['successor_standard_id']!r}"
    )


def test_publish_overlapping_published_window_rejected(api, officer_headers):
    """PRD §3.1: "Publication is refused with `ERR_STANDARD_WINDOW_OVERLAP` (HTTP 409) when any other already-`PUBLISHED` standard has a model-year window that overlaps this one. Two windows are treated as inclusive integer intervals, and they overlap exactly when each window's first model year is no greater than the other window's last model year — so touching boundaries count as overlapping, and at most one `PUBLISHED` standard can cover any given model year."
    PRD §3.1: "Publication is performed by a `RegulatoryOfficer` and moves the standard from `DRAFT` to `PUBLISHED`, stamping `published_at` with the logical clock."

    Publishing a 2029-2032 candidate fails while 2027-2030 and 2031-2034 are
    PUBLISHED; a non-overlapping 2035-2038 candidate publishes cleanly in the
    same database.

    Design: Corner/validations/publish_overlapping_published_window_rejected
    """
    create_published_standard(
        code="EPA2027-HD",
        effective_model_year_first=2027, effective_model_year_last=2030,
    )
    create_published_standard(
        code="EPA2031-HD", nox_limit_g_per_bhp_hr=0.20, pm_limit_g_per_bhp_hr=0.005,
        effective_model_year_first=2031, effective_model_year_last=2034,
    )
    over = create_draft_standard(
        code="EPA2029-HD", nox_limit_g_per_bhp_hr=0.30, pm_limit_g_per_bhp_hr=0.008,
        effective_model_year_first=2029, effective_model_year_last=2032,
    )
    far = create_draft_standard(
        code="EPA2035-HD", nox_limit_g_per_bhp_hr=0.15, pm_limit_g_per_bhp_hr=0.004,
        effective_model_year_first=2035, effective_model_year_last=2038,
    )

    refused = api.publish_regulation_standard(over["id"], officer_headers)
    validate_error(refused, ApiErrorId.ERR_STANDARD_WINDOW_OVERLAP)

    published = publish_standard(far["id"])
    assert published["status"] == "PUBLISHED"
    assert _dt(published["published_at"]) == _dt("2026-09-01T00:00:00Z"), (
        f"published_at is stamped from the logical clock, got {published['published_at']}"
    )

    over_now = validate_success(api.get_regulation_standard(over["id"], officer_headers))
    assert over_now["status"] == "DRAFT", (
        f"the overlapping candidate must not move, got {over_now['status']}"
    )


def test_family_model_year_outside_standard_window_rejected(api, engineer_headers):
    """PRD §3.2: "the `model_year` must lie inside the standard's effective window, inclusive of both `effective_model_year_first` and `effective_model_year_last` (`ERR_MODEL_YEAR_OUTSIDE_STANDARD_WINDOW`, HTTP 422)"

    A family whose model_year 2031 falls outside the PUBLISHED standard's
    2027-2030 window fails 422 ERR_MODEL_YEAR_OUTSIDE_STANDARD_WINDOW and no
    family is created.

    Design: Corner/validations/family_model_year_outside_standard_window_rejected
    """
    standard = create_published_standard()
    resp = api.create_engine_family(
        create_engine_family_payload(
            regulation_standard_id=standard["id"],
            family_code="Z-EARLY", model_year=2031,
        ),
        engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_MODEL_YEAR_OUTSIDE_STANDARD_WINDOW)

    rows, meta = validate_paginated(api.list_engine_families(engineer_headers))
    assert rows == [] and meta["total_count"] == 0


def test_family_create_against_draft_standard_rejected(api, engineer_headers):
    """PRD §3.2: "Three referential checks apply at creation: the named standard must be `PUBLISHED` (`ERR_STANDARD_NOT_PUBLISHED`), the `model_year` must lie inside the standard's effective window, inclusive of both `effective_model_year_first` and `effective_model_year_last` (`ERR_MODEL_YEAR_OUTSIDE_STANDARD_WINDOW`, HTTP 422), and the `family_code` must be unique among families of the same `model_year` (`ERR_DUPLICATE_FAMILY_CODE`)."

    A DRAFT standard cannot certify anything: family creation against it fails
    409 ERR_STANDARD_NOT_PUBLISHED even though the model year fits the window.

    Design: Corner/validations/family_create_against_draft_standard_rejected
    """
    standard = create_draft_standard()
    resp = api.create_engine_family(
        create_engine_family_payload(
            regulation_standard_id=standard["id"],
            family_code="Z-DRAFT", model_year=2027,
        ),
        engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STANDARD_NOT_PUBLISHED)


def test_unit_in_service_date_in_future_rejected(api, admin_headers):
    """PRD §3.4: "the `in_service_date` must not lie in the future — a date strictly after the logical clock is rejected with `ERR_IN_SERVICE_DATE_IN_FUTURE` (HTTP 422), while a date exactly equal to the clock is accepted."

    With the clock at 2026-11-01, in_service_date 2026-11-02 fails 422
    ERR_IN_SERVICE_DATE_IN_FUTURE, while a date exactly equal to the clock is
    accepted — the boundary is inclusive.

    Design: Corner/validations/unit_in_service_date_in_future_rejected
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    set_logical_clock("2026-11-01T00:00:00Z")

    refused = api.create_engine_unit(
        create_engine_unit_payload(
            engine_family_id=env["family"]["id"], fleet_id=fleet["id"],
            serial_number="UN-F1", in_service_date="2026-11-02T00:00:00Z",
        ),
        admin_headers,
    )
    validate_error(refused, ApiErrorId.ERR_IN_SERVICE_DATE_IN_FUTURE)

    accepted = validate_success(
        api.create_engine_unit(
            create_engine_unit_payload(
                engine_family_id=env["family"]["id"], fleet_id=fleet["id"],
                serial_number="UN-F2", in_service_date="2026-11-01T00:00:00Z",
            ),
            admin_headers,
        ),
        201,
    )
    assert accepted["lifecycle"] == "IN_SERVICE"


def test_maintenance_odometer_above_accumulated_rejected(api):
    """PRD §3.5: "The odometer reading must not exceed the unit's current `accumulated_miles`; a reading beyond the unit's accumulated miles is rejected with `ERR_ODOMETER_EXCEEDS_UNIT` (HTTP 422)."

    A maintenance record claiming service at 99999 miles on a unit whose
    telematics reports 15000 fails 422 ERR_ODOMETER_EXCEEDS_UNIT; a record at
    exactly the accumulated value is accepted — the boundary is inclusive.

    Design: Corner/validations/maintenance_odometer_above_accumulated_rejected
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    unit = setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-101")
    ingest_snapshot(
        unit["id"],
        recorded_at="2026-11-15T00:00:00Z", odometer_miles=15000, engine_hours=400,
        fault_codes=[], def_consumption_gal=40.0, nox_sensor_drift_ppm=2,
    )
    set_logical_clock("2026-12-01T00:00:00Z")

    refused = api.create_maintenance_record(
        unit["id"],
        create_maintenance_record_payload(
            performed_at="2026-11-20T00:00:00Z",
            maintenance_type="OIL_CHANGE", odometer_at_service=99999,
        ),
        make_fleet_manager_headers(fleet["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_ODOMETER_EXCEEDS_UNIT)

    accepted = add_maintenance_record(
        unit["id"], fleet_id=fleet["id"],
        performed_at="2026-11-20T00:00:00Z", maintenance_type="OIL_CHANGE",
        odometer_at_service=15000,
    )
    assert accepted["odometer_at_service"] == 15000


def test_telematics_monotonicity_enforced_on_miles_and_timestamp(api, admin_headers):
    """PRD §3.5: "Monotonicity is enforced in both dimensions: `odometer_miles` must be no less than the unit's `accumulated_miles` and `engine_hours` no less than its `accumulated_hours` (`ERR_NON_MONOTONIC_ODOMETER`, HTTP 409), and `recorded_at` must be strictly after the unit's `last_snapshot_at` — an equal timestamp is not acceptable — (`ERR_NON_MONOTONIC_TELEMATICS`, HTTP 409)."

    A snapshot with odometer below the accumulated value fails
    ERR_NON_MONOTONIC_ODOMETER, and a snapshot whose recorded_at equals the
    previous snapshot's recorded_at fails ERR_NON_MONOTONIC_TELEMATICS; the
    unit's accumulators are untouched by both rejections.

    Design: Corner/validations/telematics_monotonicity_enforced_on_miles_and_timestamp
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    unit = setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-101")
    ingest_snapshot(
        unit["id"],
        recorded_at="2026-11-15T00:00:00Z", odometer_miles=15000, engine_hours=400,
        fault_codes=[], def_consumption_gal=40.0, nox_sensor_drift_ppm=2,
    )

    miles_back = api.create_telematics_snapshot(
        unit["id"],
        {
            "recorded_at": "2026-11-16T00:00:00Z", "odometer_miles": 14000,
            "engine_hours": 401, "fault_codes": [], "def_consumption_gal": 5.0,
            "nox_sensor_drift_ppm": 2,
        },
        admin_headers,
    )
    validate_error(miles_back, ApiErrorId.ERR_NON_MONOTONIC_ODOMETER)

    same_instant = api.create_telematics_snapshot(
        unit["id"],
        {
            "recorded_at": "2026-11-15T00:00:00Z", "odometer_miles": 15100,
            "engine_hours": 401, "fault_codes": [], "def_consumption_gal": 5.0,
            "nox_sensor_drift_ppm": 2,
        },
        admin_headers,
    )
    validate_error(same_instant, ApiErrorId.ERR_NON_MONOTONIC_TELEMATICS)

    unit_now = get_unit(unit["id"])
    assert unit_now["accumulated_miles"] == 15000, (
        f"rejected snapshots must not move the accumulator, got {unit_now['accumulated_miles']}"
    )
    assert _dt(unit_now["last_snapshot_at"]) == _dt("2026-11-15T00:00:00Z")
