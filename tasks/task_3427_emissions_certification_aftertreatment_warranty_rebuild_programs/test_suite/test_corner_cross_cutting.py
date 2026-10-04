"""Corner coverage — cross-cutting layers (PRD §2.3 pagination with filters,
§2.7 optimistic concurrency, §3.5 ingest reconciliation, §2.4 lazy expiry
boundary).

The runner restarts the server before every test, so each test builds its own
environment from an empty database through PRD-declared endpoints only.
"""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    add_spec_version,
    create_aftertreatment_spec_payload,
    create_family,
    create_published_standard,
    create_reman_order_payload,
    file_claim,
    get_family,
    get_unit,
    ingest_snapshot,
    make_fleet_manager_headers,
    make_service_advisor_headers,
    occ_spec_payload,
    set_logical_clock,
    setup_campaign_in_progress,
    setup_engine_unit,
    setup_family_in_production,
    setup_fleet,
    setup_full_environment,
    stamp_family_non_conforming,
    start_claim_review,
    validate_error,
    validate_paginated,
    validate_success,
)


def _dt(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp for instant comparison."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def test_occ_spec_create_stale_family_version_rejected(api, engineer_headers):
    """PRD §2.7: "Creating a new aftertreatment spec version against an engine family requires the request to carry `expected_engine_family_version`, a non-optional field holding the family `version` the client last observed. ... If the supplied value does not equal the parent entity's current `version` — because another writer has advanced the parent since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the client from silently superseding a spec it never saw or quoting against unit state it never observed."
    PRD §3.3: "In the same request the family's previous spec, if one exists in `DRAFT` or `ACTIVE` status, is moved to `SUPERSEDED`, and the family's own `version` increments by one — which is precisely the increment a stale writer is protected against."

    The second spec create carrying the pre-supersede family version (1) is
    refused 412 ERR_STALE_VERSION; re-reading the family (version 2) and
    resubmitting succeeds with spec_version 2.

    Design: Corner/cross_cutting_layers/occ_spec_create_stale_family_version_rejected
    """
    standard = create_published_standard()
    family = create_family(standard["id"])
    stale_version = family["version"]
    add_spec_version(family, calibrate=False, activate=False)  # family advances to v2

    refused = api.create_aftertreatment_spec(
        family["id"],
        create_aftertreatment_spec_payload(
            expected_engine_family_version=stale_version,
            scr_catalyst_part="SCR-901", dpf_part="DPF-451",
        ),
        engineer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION)

    family_now = get_family(family["id"])
    assert family_now["version"] == stale_version + 1 == 2, (
        f"the first spec create incremented the family version, got {family_now['version']}"
    )

    created = validate_success(
        api.create_aftertreatment_spec(
            family["id"], occ_spec_payload(family_now, scr_catalyst_part="SCR-901",
                                           dpf_part="DPF-451"),
            engineer_headers,
        ),
        201,
    )
    assert created["spec_version"] == 2, (
        f"the resubmission with the fresh version succeeds, got spec_version {created['spec_version']}"
    )


def test_occ_reman_create_stale_unit_version_rejected(api):
    """PRD §2.7: "Creating a remanufacture order likewise requires the non-optional `expected_engine_unit_version` field, holding the engine unit's last observed `version`. If the supplied value does not equal the parent entity's current `version` — because another writer has advanced the parent since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)"
    PRD §3.9: "its creation increments the unit's `version` by one — telematics ingestion and campaign cascades can legitimately advance that same version between quote and order, which is exactly the staleness the OCC field guards."

    A telematics ingest advances the unit from version 1 to 2 between quote
    and order placement; the reman create carrying the pre-ingest version is
    refused 412 ERR_STALE_VERSION and succeeds with the re-read version.

    Design: Corner/cross_cutting_layers/occ_reman_create_stale_unit_version_rejected
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    stale_version = unit["version"]
    ingest_snapshot(
        unit["id"],
        recorded_at="2026-11-15T00:00:00Z", odometer_miles=3000, engine_hours=80,
        fault_codes=[], def_consumption_gal=8.0, nox_sensor_drift_ppm=1,
    )
    set_logical_clock("2026-12-01T00:00:00Z")
    advisor = make_service_advisor_headers(env["center"]["id"])

    refused = api.create_reman_order(
        create_reman_order_payload(
            engine_unit_id=unit["id"],
            service_center_id=env["center"]["id"],
            expected_engine_unit_version=stale_version,
        ),
        advisor,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_VERSION)

    unit_now = get_unit(unit["id"])
    assert unit_now["version"] == stale_version + 1 == 2, (
        f"the ingest advanced the unit version, got {unit_now['version']}"
    )

    created = validate_success(
        api.create_reman_order(
            create_reman_order_payload(
                engine_unit_id=unit["id"],
                service_center_id=env["center"]["id"],
                expected_engine_unit_version=unit_now["version"],
            ),
            advisor,
        ),
        201,
    )
    assert created["status"] == "QUOTED"


def test_claims_list_filter_sort_pagination_interaction(api, adjudicator_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; when it is not provided it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD §3.7: "The claims list endpoint supports filtering by `engine_unit_id`, `service_center_id`, and `status`."

    Three claims (two SUBMITTED, one UNDER_REVIEW): status=SUBMITTED&limit=1
    pages through exactly the two matching rows with total_count 2, and the
    unfiltered list returns all 3 with the default limit 10.

    Design: Corner/cross_cutting_layers/claims_list_filter_sort_pagination_interaction
    """
    env = setup_full_environment()
    unit = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    set_logical_clock("2026-12-01T00:00:00Z")
    claim_a = file_claim(
        unit, env["center"], failed_component_class="ENGINE_BASE",
        failure_code="FC-a", claimed_amount_cents=10000,
    )
    claim_b = file_claim(
        unit, env["center"], failed_component_class="NOX_SENSOR",
        failure_code="FC-b", claimed_amount_cents=20000,
    )
    claim_c = file_claim(
        unit, env["center"], failed_component_class="DOSING_SYSTEM",
        failure_code="FC-c", claimed_amount_cents=30000,
    )
    start_claim_review(claim_c["id"])

    page1, meta1 = validate_paginated(
        api.list_warranty_claims(
            adjudicator_headers, params={"status": "SUBMITTED", "limit": 1, "offset": 0}
        )
    )
    assert len(page1) == 1 and meta1["total_count"] == 2 and meta1["has_more"] is True
    page2, meta2 = validate_paginated(
        api.list_warranty_claims(
            adjudicator_headers, params={"status": "SUBMITTED", "limit": 1, "offset": 1}
        )
    )
    assert len(page2) == 1 and meta2["total_count"] == 2 and meta2["has_more"] is False
    paged_ids = {page1[0]["id"], page2[0]["id"]}
    assert paged_ids == {claim_a["id"], claim_b["id"]}, (
        f"the two pages cover exactly the SUBMITTED claims, got {paged_ids}"
    )

    everything, meta_all = validate_paginated(api.list_warranty_claims(adjudicator_headers))
    assert len(everything) == 3 and meta_all["total_count"] == 3
    assert meta_all["limit"] == 10 and meta_all["offset"] == 0, (
        f"defaults are limit 10 / offset 0, got {meta_all}"
    )

    narrowed, meta_n = validate_paginated(
        api.list_warranty_claims(
            adjudicator_headers,
            params={"engine_unit_id": unit["id"], "status": "UNDER_REVIEW"},
        )
    )
    assert [row["id"] for row in narrowed] == [claim_c["id"]], (
        f"only claim C is UNDER_REVIEW, got {[row['id'] for row in narrowed]}"
    )
    assert meta_n["total_count"] == 1


def test_telematics_ingest_bumps_unit_version_and_accumulators(api, admin_headers):
    """PRD §3.5: "On acceptance the unit's accumulated miles and hours advance to the snapshot's readings, `last_snapshot_at` becomes the snapshot's `recorded_at`, and the unit's `version` increments."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including mutations driven by system cascades rather than direct client action."

    An accepted snapshot reconciles the denormalized accumulators immediately:
    miles 0 -> 3000, hours 0 -> 80, last_snapshot_at set, and version
    increments from 1 to 2 on the same read-after-write.

    Design: Corner/cross_cutting_layers/telematics_ingest_bumps_unit_version_and_accumulators
    """
    env = setup_family_in_production()
    fleet = setup_fleet()
    unit = setup_engine_unit(env["family"]["id"], fleet["id"], serial_number="UN-101")
    assert unit["version"] == 1

    validate_success(
        api.create_telematics_snapshot(
            unit["id"],
            {
                "recorded_at": "2026-11-15T00:00:00Z", "odometer_miles": 3000,
                "engine_hours": 80, "fault_codes": [], "def_consumption_gal": 8.0,
                "nox_sensor_drift_ppm": 1,
            },
            admin_headers,
        ),
        201,
    )

    unit_now = get_unit(unit["id"])
    assert unit_now["accumulated_miles"] == 3000
    assert unit_now["accumulated_hours"] == 80
    assert unit_now["version"] == 2, (
        f"1 at create + 1 for the ingest mutation, got {unit_now['version']}"
    )
    assert _dt(unit_now["last_snapshot_at"]) == _dt("2026-11-15T00:00:00Z")


def test_technician_expiry_exact_instant_still_active_then_expired(api, admin_headers):
    """PRD §2.4: "A `Technician` whose `certification_expires_at` lies strictly before the logical clock is reported as `EXPIRED` the next time the technician is read or used; at the exact instant of `certification_expires_at` the technician is still `CERT_ACTIVE`, because the comparison is strictly-greater."
    PRD §3.8: "the assigned technician must belong to the named center, must be `CERT_ACTIVE` at the current logical clock, must be `emissions_endorsed`, and — for any work order occupying 3 or more bay days — must hold `LEVEL_2` or `LEVEL_3` certification, with any shortfall rejected as `ERR_TECHNICIAN_NOT_QUALIFIED` (HTTP 409)"

    With expiry 2028-08-31T00:00:00Z, a work-order assignment at exactly that
    instant succeeds, and the same assignment one second later fails
    ERR_TECHNICIAN_NOT_QUALIFIED.

    Design: Corner/cross_cutting_layers/technician_expiry_exact_instant_still_active_then_expired
    """
    env = setup_full_environment()
    center_id = env["center"]["id"]
    tech_id = env["technician"]["id"]
    assert _dt(env["technician"]["certification_expires_at"]) == _dt("2028-08-31T00:00:00Z")
    unit_a = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-101")
    unit_b = setup_engine_unit(env["family"]["id"], env["fleet"]["id"], serial_number="UN-102")
    stamp_family_non_conforming(env["family"]["id"], test_period_label="2027-MY-Q1")
    campaign = setup_campaign_in_progress(env["family"]["id"], campaign_code="CMP-CF")

    set_logical_clock("2028-08-31T00:00:00Z")
    at_instant = validate_success(
        api.create_campaign_work_order(
            campaign["id"],
            {
                "engine_unit_id": unit_a["id"],
                "service_center_id": center_id,
                "assigned_technician_id": tech_id,
                "scheduled_start_day": "2028-09-05T00:00:00Z",
                "bay_days": 1,
            },
            make_service_advisor_headers(center_id),
        ),
        201,
    )
    assert at_instant["status"] == "SCHEDULED", (
        "at the exact expiry instant the technician is still CERT_ACTIVE"
    )

    set_logical_clock("2028-08-31T00:00:01Z")
    one_second_later = api.create_campaign_work_order(
        campaign["id"],
        {
            "engine_unit_id": unit_b["id"],
            "service_center_id": center_id,
            "assigned_technician_id": tech_id,
            "scheduled_start_day": "2028-09-05T00:00:00Z",
            "bay_days": 1,
        },
        make_service_advisor_headers(center_id),
    )
    validate_error(one_second_later, ApiErrorId.ERR_TECHNICIAN_NOT_QUALIFIED)
