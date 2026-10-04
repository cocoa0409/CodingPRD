"""Corner coverage — entities, continued (PRD §2.5 append-only records,
§3.3 spec supersession, §3.4 unit registration, §3.6 technician windows,
§3.8 campaign announce cascade).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from datetime import datetime

from test_helpers import (
    add_spec_version,
    assert_engine_unit,
    assert_maintenance_record,
    create_engine_unit_payload,
    create_family,
    create_maintenance_record_payload,
    create_published_standard,
    create_service_center,
    create_technician_payload,
    declare_campaign,
    get_family,
    make_fleet_manager_headers,
    occ_spec_payload,
    set_logical_clock,
    setup_engine_unit,
    setup_family_in_production,
    setup_fleet,
    setup_full_environment,
    stamp_family_non_conforming,
    validate_paginated,
    validate_success,
)


def _dt(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant comparison."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_technician_create_stamps_certification_window_defaults(api, admin_headers):
    """PRD §3.6: "On certification, `certified_at` is stamped from the logical clock and `certification_expires_at` is set exactly 730 days later; the technician's `cert_status` begins as `CERT_ACTIVE`."
    PRD §4: "Operations that create a new resource return a `201 Created` status code"

    A technician created at clock 2026-09-01T00:00:00Z gets certified_at equal
    to the clock, certification_expires_at exactly 730 days later
    (2028-08-31T00:00:00Z, spanning the 2028 leap day), and cert_status
    CERT_ACTIVE.

    Design: Corner/entities/technician_create_stamps_certification_window_defaults
    """
    center = create_service_center(name="Desert Ridge Diesel", region="SW", bay_capacity_per_day=2)
    resp = api.create_technician(
        center["id"],
        create_technician_payload(
            full_name="Tess Adey",
            badge_id="T-01",
            certification_level="LEVEL_2",
            emissions_endorsed=True,
        ),
        admin_headers,
    )
    tech = validate_success(resp, 201)
    assert _dt(tech["certified_at"]) == _dt("2026-09-01T00:00:00Z"), (
        f"certified_at is stamped from the logical clock, got {tech['certified_at']}"
    )
    assert _dt(tech["certification_expires_at"]) == _dt("2028-08-31T00:00:00Z"), (
        "certification_expires_at is exactly 730 days after certification, "
        f"got {tech['certification_expires_at']}"
    )
    assert tech["cert_status"] == "CERT_ACTIVE", (
        f"a fresh technician is CERT_ACTIVE, got {tech['cert_status']}"
    )
    assert tech["service_center_id"] == center["id"]


def test_engine_unit_model_year_copied_from_family(api, admin_headers):
    """PRD §3.4: "The unit's `model_year` is copied from its family at registration; any client-supplied value for it is ignored. A new unit starts with `lifecycle` `IN_SERVICE`, `campaign_compliance` `CLEAR`, `accumulated_miles` and `accumulated_hours` at 0, `predictive_service_due` false, and `last_snapshot_at` unset."

    The unit's model_year is copied from its family (2027); a client-supplied
    model_year of 2099 is ignored and cannot diverge the stored value from the
    family's.

    Design: Corner/entities/engine_unit_model_year_copied_from_family
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    set_logical_clock("2026-11-15T00:00:00Z")

    resp = api.create_engine_unit(
        create_engine_unit_payload(
            engine_family_id=env["family"]["id"],
            fleet_id=fleet["id"],
            serial_number="UN-102",
            model_year=2099,
        ),
        admin_headers,
    )
    unit = validate_success(resp, 201)
    assert_engine_unit(unit)
    assert unit["model_year"] == env["family"]["model_year"] == 2027, (
        f"model_year is copied from the family, got {unit['model_year']}"
    )
    assert unit["lifecycle"] == "IN_SERVICE"
    assert unit["campaign_compliance"] == "CLEAR"
    assert unit["accumulated_miles"] == 0 and unit["accumulated_hours"] == 0
    assert unit["predictive_service_due"] is False
    assert unit["last_snapshot_at"] is None
    assert unit["version"] == 1


def test_spec_create_supersedes_prior_and_increments_version(api, engineer_headers):
    """PRD §3.3: "The new spec receives a `spec_version` one greater than the family's current maximum — 1 for the family's first spec — starts in `DRAFT` status with `calibration_status` `UNCALIBRATED`, and has both `target_def_dosing_g_per_kwh` and `last_deviation_pct` unset. In the same request the family's previous spec, if one exists in `DRAFT` or `ACTIVE` status, is moved to `SUPERSEDED`, and the family's own `version` increments by one — which is precisely the increment a stale writer is protected against."

    A second spec create with the family's current version (2 after the first
    create bumped it from 1) yields spec_version 2, leaves the family at
    version 3, and flips the first ACTIVE spec to SUPERSEDED.

    Design: Corner/entities/spec_create_supersedes_prior_and_increments_version
    """
    standard = create_published_standard()
    family = create_family(standard["id"])
    spec1 = add_spec_version(family)  # created, calibrated, activated
    assert spec1["spec_version"] == 1 and spec1["status"] == "ACTIVE"

    family_now = get_family(family["id"])
    assert family_now["version"] == 2, (
        "the first spec create incremented the family version from 1 to 2, "
        f"got {family_now['version']}"
    )

    resp = api.create_aftertreatment_spec(
        family["id"],
        occ_spec_payload(
            family_now,
            scr_catalyst_part="SCR-901",
            dpf_part="DPF-451",
            doser_part="DSR-12",
            nox_sensor_count=2,
        ),
        engineer_headers,
    )
    spec2 = validate_success(resp, 201)
    assert spec2["spec_version"] == 2, (
        "spec_version is one greater than the family's current maximum, "
        f"got {spec2['spec_version']}"
    )
    assert spec2["status"] == "DRAFT" and spec2["calibration_status"] == "UNCALIBRATED"
    assert spec2["target_def_dosing_g_per_kwh"] is None
    assert spec2["last_deviation_pct"] is None

    spec1_now = validate_success(api.get_aftertreatment_spec(spec1["id"], engineer_headers))
    assert spec1_now["status"] == "SUPERSEDED", (
        f"the prior ACTIVE spec is superseded in the same request, got {spec1_now['status']}"
    )
    family_after = get_family(family["id"])
    assert family_after["version"] == 3, (
        f"the second spec create increments the family version to 3, got {family_after['version']}"
    )


def test_maintenance_record_is_immutable_append_only(api):
    """PRD §2.5: "Three resources are append-only records and carry only `id` and `created_at`: `MaintenanceRecord`, `TelematicsSnapshot`, and `InUseComplianceResult`. For these three resources both `updated_at` and `version` are absent entirely — they are never modified after creation."
    PRD §3.5: "A maintenance record is appended within a unit's scope by the fleet's own `FleetManager` or by a `PlatformAdmin`"

    The create response has id and created_at but no version and no updated_at,
    and the record is retrievable through the unit's maintenance list.

    Design: Corner/entities/maintenance_record_is_immutable_append_only
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    fleet_headers = make_fleet_manager_headers(env["fleet"]["id"])

    resp = api.create_maintenance_record(
        unit["id"],
        create_maintenance_record_payload(
            performed_at="2026-11-10T00:00:00Z",
            maintenance_type="OIL_CHANGE",
            odometer_at_service=0,
        ),
        fleet_headers,
    )
    record = validate_success(resp, 201)
    assert_maintenance_record(record)
    assert "version" not in record, "append-only record must not carry version"
    assert "updated_at" not in record, "append-only record must not carry updated_at"

    rows, _meta = validate_paginated(api.list_maintenance_records(unit["id"], fleet_headers))
    assert len(rows) == 1 and rows[0]["maintenance_type"] == "OIL_CHANGE", (
        f"the unit's maintenance list returns the appended record, got {rows}"
    )


def test_campaign_announce_computes_notified_unit_count(api, officer_headers):
    """PRD §3.8: "Second, every engine unit of the family whose `lifecycle` is `IN_SERVICE` and whose `campaign_compliance` is not already `CAMPAIGN_OPEN` transitions to `CAMPAIGN_OPEN`, each such unit's `version` incrementing — this is the fleet notification, and it re-opens units that a prior campaign had left `REMEDIED`. Third, the campaign stamps `announced_at` from the logical clock and records `notified_unit_count` as the number of units flagged."

    notified_unit_count is never client-supplied: announcing over exactly two
    IN_SERVICE units stamps 2, both units read CAMPAIGN_OPEN, and announced_at
    equals the logical clock.

    Design: Corner/entities/campaign_announce_computes_notified_unit_count
    """
    env = setup_full_environment()
    unit_a = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    unit_b = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-102")
    set_logical_clock("2026-12-15T00:00:00Z")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = declare_campaign(
        env["family"]["id"],
        campaign_code="CMP-C1",
        campaign_type="RECALL",
        defect_summary="SCR washcoat",
        remedy_description="Replace catalyst",
        remedy_bay_days=1,
    )

    resp = api.announce_campaign(campaign["id"], officer_headers)
    announced = validate_success(resp, 200)
    assert announced["status"] == "ANNOUNCED"
    assert announced["notified_unit_count"] == 2, (
        f"two in-service units are flagged, got {announced['notified_unit_count']}"
    )
    assert _dt(announced["announced_at"]) == _dt("2026-12-15T00:00:00Z"), (
        f"announced_at is stamped from the logical clock, got {announced['announced_at']}"
    )

    units, _meta = validate_paginated(
        api.list_family_engine_units(env["family"]["id"], officer_headers)
    )
    compliance = {u["id"]: u["campaign_compliance"] for u in units}
    assert compliance[unit_a["id"]] == "CAMPAIGN_OPEN"
    assert compliance[unit_b["id"]] == "CAMPAIGN_OPEN"
