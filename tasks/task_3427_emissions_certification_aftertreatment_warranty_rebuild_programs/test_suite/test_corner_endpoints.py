"""Corner coverage — endpoints (PRD §3.4 computed coverage read, §3.7 claim
adjudication gate, §3.8 work-order creation defaults).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from datetime import datetime

from test_helpers import (
    ADJUDICATOR_USER_ID,
    ApiErrorId,
    adjudicate_claim_payload,
    assert_campaign_work_order,
    assert_coverage_read,
    create_campaign_work_order_payload,
    file_claim,
    ingest_snapshot,
    make_fleet_manager_headers,
    make_service_advisor_headers,
    make_warranty_adjudicator_headers,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_family_in_production,
    setup_fleet,
    setup_full_environment,
    stamp_family_non_conforming,
    validate_error,
    validate_success,
)


def _dt(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant comparison."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_work_order_create_returns_201_with_system_defaults(api):
    """PRD §3.8: "The order records the parent campaign's `campaign_id` and starts in `SCHEDULED`."
    PRD §4: "Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource — including all state transitions and the logical-clock set — return a `200 OK` status code."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including mutations driven by system cascades rather than direct client action."

    A valid schedule call returns 201 with status SCHEDULED, null
    completed_at/verified_at, version 1, and the path's campaign_id bound onto
    the row.

    Design: Corner/endpoints/work_order_create_returns_201_with_system_defaults
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-CD")

    resp = api.create_campaign_work_order(
        campaign["id"],
        create_campaign_work_order_payload(
            engine_unit_id=unit["id"],
            service_center_id=center_id,
            assigned_technician_id=env["technician"]["id"],
            scheduled_start_day="2027-01-04T00:00:00Z",
            bay_days=1,
        ),
        make_service_advisor_headers(center_id),
    )
    work_order = validate_success(resp, 201)
    assert_campaign_work_order(work_order)
    assert work_order["status"] == "SCHEDULED"
    assert work_order["completed_at"] is None and work_order["verified_at"] is None
    assert work_order["version"] == 1
    assert work_order["campaign_id"] == campaign["id"], (
        f"the path's campaign id is bound onto the row, got {work_order['campaign_id']}"
    )


def test_coverage_endpoint_returns_computed_read_shape(api):
    """PRD §3.4: "A computed coverage read is available for any unit: evaluated against the current logical clock, it reports `base_covered` and `base_coverage_end` for the base warranty window, `extended_covered` and `extended_coverage_end` for the extended emissions window, and `extended_applies_to` describing the extended coverage's applicability."
    PRD §3.7: "The base warranty window is open when the logical clock is strictly earlier than the unit's `in_service_date` plus the standard's `base_warranty_years` calendar years, and the unit's `accumulated_miles` is strictly less than the standard's `base_warranty_miles`"
    PRD §3.7: "the extended years term is the smaller of 5 years and the standard's `useful_life_years`"

    With the clock at 2026-12-01 and a unit in service 2026-09-01 carrying
    15000 miles / 400 hours, the read reports base_covered true with
    base_coverage_end 2028-09-01 and extended_covered true with
    extended_coverage_end 2031-09-01 (in_service + min(5, 10) years).

    Design: Corner/endpoints/coverage_endpoint_returns_computed_read_shape
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

    coverage = validate_success(
        api.get_unit_coverage(unit["id"], make_fleet_manager_headers(fleet["id"]))
    )
    assert_coverage_read(coverage)
    assert coverage["base_covered"] is True
    assert _dt(coverage["base_coverage_end"]) == _dt("2028-09-01T00:00:00Z"), (
        f"base window ends at in_service + 2 years, got {coverage['base_coverage_end']}"
    )
    assert coverage["extended_covered"] is True
    assert _dt(coverage["extended_coverage_end"]) == _dt("2031-09-01T00:00:00Z"), (
        "extended window ends at in_service + min(5, 10) years, "
        f"got {coverage['extended_coverage_end']}"
    )
    assert isinstance(coverage["extended_applies_to"], str) and coverage["extended_applies_to"]


def test_adjudicate_only_from_under_review(api):
    """PRD §3.7: "A `WarrantyAdjudicator` starts review, moving the claim from `SUBMITTED` to `UNDER_REVIEW`."
    PRD §3.7: "Adjudication computes the claim's `neglect_score` from the unit's full maintenance and telematics history — every `MaintenanceRecord` and `TelematicsSnapshot` of the unit, regardless of age — before any decision is accepted."
    PRD §2.8: "State gates: the generic `ERR_INVALID_STATE_TRANSITION`, plus the specific state errors"

    adjudicate from SUBMITTED (review never started) is not a defined
    transition: 409 ERR_INVALID_STATE_TRANSITION, and the claim remains
    SUBMITTED with neglect_score unset.

    Design: Corner/endpoints/adjudicate_only_from_under_review
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    set_logical_clock("2026-12-01T00:00:00Z")
    claim = file_claim(
        unit, env["center"],
        failed_component_class="ENGINE_BASE", failure_code="FC-cond",
        claimed_amount_cents=40000,
    )
    assert claim["status"] == "SUBMITTED"

    refused = api.adjudicate_claim(
        claim["id"],
        adjudicate_claim_payload("APPROVE_FULL"),
        make_warranty_adjudicator_headers(ADJUDICATOR_USER_ID),
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    claim_now = validate_success(
        api.get_warranty_claim(claim["id"], make_warranty_adjudicator_headers(ADJUDICATOR_USER_ID))
    )
    assert claim_now["status"] == "SUBMITTED"
    assert claim_now["neglect_score"] is None, (
        f"no decision was accepted, so no score is stamped, got {claim_now['neglect_score']!r}"
    )
