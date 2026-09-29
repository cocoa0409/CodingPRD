"""Cross-cutting layers: the two optimistic-concurrency guards, the lot selector's
per-candidate money clause, and the immediate consistency of the four-hop completion
cascade."""

from test_helpers import factories as f
from test_helpers import get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    AssessmentStatus,
    DeferralReason,
    DeviceType,
    HouseholdStatus,
    InstallStatus,
    InstallationStatus,
    LotStatus,
    PlanStatus,
    ReportStatus,
    VisitStatus,
)
from test_helpers.fixtures import (
    arrive,
    assess_zone,
    book_visit,
    compile_report,
    create_active_grant,
    create_assessed_zone,
    create_crew,
    create_escape_plan,
    create_household,
    create_lot,
    create_partner,
    create_published_route,
    create_zone,
    defer_visit,
    deliver_education,
    pin_clock,
    read_escape_plan,
    read_grant,
    read_household,
    read_installation,
    read_lot,
    read_report,
    read_visit,
    read_zone,
    reserve_installation,
)
from test_helpers.test_users import ANALYST, COORDINATOR, make_crr_technician_headers

SMOKE_ONLY = {
    "allowed_device_types": [DeviceType.SMOKE_10YR],
    "unit_rate_cents_by_type": {DeviceType.SMOKE_10YR: 2195},
}


def test_01_a_version_consumed_by_the_analysts_own_assessment_is_stale(api):
    """The first accepted run bumps the zone, so replaying the version the analyst read
    before it is 412 - and the refusal itself must not move the counter.

    PRD: "If that value does not equal the zone's current `version`, the request is
    rejected with `ERR_STALE_ZONE_VERSION` (HTTP 412). The rationale is specific: a
    second assessment submitted with a current version *would* succeed and would simply
    move `current_assessment_id` forward..."

    Design: Corner/cross_cutting_complexity_layers/stale_zone_version_from_an_unrelated_cascade_returns_412
    """
    pin_clock(api)
    zone = create_zone(api)
    first_version = zone["version"]
    first = assess_zone(api, zone["id"], first_version)

    after_first = read_zone(api, zone["id"])
    assert after_first["version"] == first_version + 1
    assert after_first["current_assessment_id"] == first["id"]

    # Household intake touches no zone counter (PRD SS3.3 names none, and SS2.11 does not
    # bump a row a cascade merely evaluates), so the zone version stays put here.
    create_household(api, zone["id"], address_line="12 Birch Row")
    assert read_zone(api, zone["id"])["version"] == after_first["version"]

    validate_error(
        api.create_assessment(
            zone["id"], f.assessment_payload(first_version), ANALYST
        ),
        ApiErrorId.STALE_ZONE_VERSION,
        412,
    )

    refused = read_zone(api, zone["id"])
    assert refused["version"] == after_first["version"]
    assert refused["current_assessment_id"] == first["id"]

    second = assess_zone(api, zone["id"], refused["version"])
    settled = read_zone(api, zone["id"])
    assert settled["current_assessment_id"] == second["id"]
    assert settled["version"] == refused["version"] + 1
    assert settled["assessment_status"] == AssessmentStatus.ASSESSED

    rows, meta = validate_paginated(api.list_assessments(zone["id"], ANALYST))
    assert meta["total_count"] == 2
    assert [row["sequence_no"] for row in rows] == [1, 2]


def test_02_replaying_a_household_version_cannot_half_apply_a_supersede(api):
    """The guard value is consumed by the client's own first create, so the replay is
    412 and the first plan must still be DRAFT rather than SUPERSEDED.

    PRD: "If that value does not equal the household's current `version`, the request is
    rejected with `ERR_STALE_HOUSEHOLD_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_household_version_on_escape_plan_create_returns_412
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(api, zone["id"], address_line="12 Birch Row")
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"])
    deliver_education(
        api,
        visit["id"],
        crew["id"],
        topics_covered=["ESCAPE_ROUTES"],
        escape_plan_walkthrough=True,
    )
    defer_visit(api, visit["id"], crew["id"], DeferralReason.LANDLORD_APPROVAL_REQUIRED)

    served = read_household(api, household["id"])
    assert served["status"] == HouseholdStatus.VISIT_COMPLETED
    guard = served["version"]

    first = create_escape_plan(
        api,
        household["id"],
        guard,
        secondary_exit_count=1,
        meeting_point_description="Mailbox at the kerb",
    )

    validate_error(
        api.create_escape_plan(
            f.escape_plan_payload(
                household["id"],
                guard,
                secondary_exit_count=2,
                meeting_point_description="Corner of Birch Row and 4th",
            ),
            COORDINATOR,
        ),
        ApiErrorId.STALE_HOUSEHOLD_VERSION,
        412,
    )

    survivor = read_escape_plan(api, first["id"])
    assert survivor["status"] == PlanStatus.DRAFT
    assert survivor["version"] == first["version"]
    assert read_household(api, household["id"])["version"] == guard + 1

    rows, meta = validate_paginated(
        api.list_escape_plans(COORDINATOR, params={"household_id": household["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_03_the_money_clause_filters_candidates_one_at_a_time(api):
    """Two equal-expiry lots rank on price, so the cheap lot wins twice; its grant's
    residual then falls under its own unit cost and the third device routes to the dear
    lot instead of failing on funds.

    PRD: "A lot is a candidate only if all eight of the following hold: ... and the
    grant's `available_cents` is at least the lot's `unit_cost_cents`. The surviving
    candidates are then ranked first-in-first-out on shelf life and then on price:
    ascending `expiry_date` first, and among lots sharing an expiry date, ascending
    `unit_cost_cents`."

    Design: Corner/cross_cutting_complexity_layers/selector_skips_a_lot_whose_grant_can_no_longer_afford_it
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(
        api,
        zone["id"],
        address_line="12 Birch Row",
        occupant_count=4,
        sleeping_areas_count=2,
        storeys=2,
    )
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"])

    thin_partner = create_partner(api, contact_email="grants@firesafe.example")
    deep_partner = create_partner(
        api,
        org_name="Metro Utility Co",
        org_type="UTILITY",
        contact_email="safety@metroutility.example",
    )
    thin = create_active_grant(
        api, thin_partner["id"], grant_code="G-THIN-A", authorized_cents=4000, **SMOKE_ONLY
    )
    deep = create_active_grant(
        api, deep_partner["id"], grant_code="G-DEEP-B", authorized_cents=500000, **SMOKE_ONLY
    )
    cheap = create_lot(
        api,
        thin["id"],
        sku="SKU-SM10-CHEAP",
        unit_cost_cents=1850,
        received_qty=10,
        expiry_date="2027-06-30",
    )
    dear = create_lot(
        api,
        deep["id"],
        sku="SKU-SM10-DEAR",
        unit_cost_cents=2400,
        received_qty=10,
        expiry_date="2027-06-30",
    )

    first = reserve_installation(
        api, visit["id"], crew["id"], placement_location="HALLWAY_OUTSIDE_SLEEPING", storey=1
    )
    second = reserve_installation(
        api, visit["id"], crew["id"], placement_location="SLEEPING_AREA", storey=1
    )
    third = reserve_installation(
        api, visit["id"], crew["id"], placement_location="SLEEPING_AREA", storey=2
    )

    assert first["device_lot_id"] == cheap["id"]
    assert first["reserved_cost_cents"] == 1850
    assert second["device_lot_id"] == cheap["id"]
    assert second["reserved_cost_cents"] == 1850
    assert third["device_lot_id"] == dear["id"]
    assert third["reserved_cost_cents"] == 2400
    for row in (first, second, third):
        assert row["status"] == InstallationStatus.RESERVED
        # The unit rate drives reimbursement, so the lot's real price never enters it.
        assert row["reimbursable_cents"] == 1921

    thin_after = read_grant(api, thin["id"])
    assert thin_after["reserved_cents"] == 3842
    assert thin_after["available_cents"] == 158
    deep_after = read_grant(api, deep["id"])
    assert deep_after["reserved_cents"] == 1921
    assert deep_after["available_cents"] == 498079

    cheap_after = read_lot(api, cheap["id"])
    assert cheap_after["reserved_qty"] == 2
    assert cheap_after["on_hand_qty"] == 10
    assert cheap_after["status"] == LotStatus.AVAILABLE
    assert read_lot(api, dear["id"])["reserved_qty"] == 1


def test_04_the_completion_cascade_is_fully_settled_by_the_time_it_answers(api):
    """No retry and no second mutation: the response body already carries the new visit
    state, and the very next reads show all four hops plus the household and zone moved.

    PRD: "Committing a device at visit completion runs: the installation moves out of
    `RESERVED`; that commit moves quantities on its device lot; that lot movement moves
    money on the lot's funding grant; and that money movement re-runs the cost
    calculations on every one of that grant's reports still in `DRAFT` whose period
    covers the installation's install date."

    Design: Corner/consistency_model/every_cascaded_counter_is_readable_in_the_same_response
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(api, zone["id"], address_line="12 Birch Row")
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"], pre_existing_working_smoke_alarms=1)

    partner = create_partner(api, contact_email="grants@firesafe.example")
    grant = create_active_grant(api, partner["id"], **SMOKE_ONLY)
    lot = create_lot(
        api,
        grant["id"],
        sku="SKU-SM10-A",
        unit_cost_cents=1850,
        received_qty=60,
        expiry_date="2027-06-30",
    )
    installation = reserve_installation(
        api,
        visit["id"],
        crew["id"],
        placement_location="HALLWAY_OUTSIDE_SLEEPING",
        storey=1,
        device_lot_id=lot["id"],
    )
    report = compile_report(api, grant["id"])
    assert report["status"] == ReportStatus.DRAFT
    deliver_education(
        api, visit["id"], crew["id"], topics_covered=["ALARM_TESTING", "ESCAPE_ROUTES"]
    )

    closed = get_success_data(
        api.complete_visit(
            visit["id"],
            f.complete_payload(occupant_signature_name="R. Okafor"),
            make_crr_technician_headers(crew["id"]),
        )
    )
    assert closed["visit_status"] == VisitStatus.COMPLETED
    assert closed["install_status"] == InstallStatus.INSTALL_COMPLETE
    assert_instant_equals(closed["completed_at"], "2026-08-01T00:00:00Z", "completed_at")

    committed = read_installation(api, installation["id"])
    assert committed["status"] == InstallationStatus.INSTALLED
    assert_instant_equals(committed["installed_at"], "2026-08-01T00:00:00Z", "installed_at")

    settled_lot = read_lot(api, lot["id"])
    assert settled_lot["reserved_qty"] == 0
    assert settled_lot["consumed_qty"] == 1
    assert settled_lot["on_hand_qty"] == 59

    settled_grant = read_grant(api, grant["id"])
    assert settled_grant["reserved_cents"] == 0
    assert settled_grant["committed_cents"] == 1921
    assert settled_grant["available_cents"] == 498079

    settled_report = read_report(api, report["id"])
    assert settled_report["status"] == ReportStatus.DRAFT
    assert settled_report["installation_count"] == 1
    assert settled_report["reimbursable_total_cents"] == 1921
    assert settled_report["grant_share_cents"] == 1729

    settled_household = read_household(api, household["id"])
    assert settled_household["status"] == HouseholdStatus.VISIT_COMPLETED

    settled_zone = read_zone(api, zone["id"])
    assert settled_zone["served_household_count"] == 1
    # The zone's only household reached VISIT_COMPLETED, so the forward step of
    # PRD 3.1 fires in the same request on top of TARGETED -> SERVICE_ACTIVE:
    # "it fires when the zone holds at least one household and every household
    # in the zone sits in VISIT_COMPLETED, REFUSED or NO_CONTACT."
    assert settled_zone["assessment_status"] == AssessmentStatus.SERVICE_COMPLETE
    assert settled_zone["service_start_date"] == "2026-08-01"

    # Nothing converges on a second read: every payload repeats byte for byte.
    assert read_visit(api, visit["id"]) == read_visit(api, visit["id"])
    assert read_installation(api, installation["id"]) == committed
    assert read_lot(api, lot["id"]) == settled_lot
    assert read_grant(api, grant["id"]) == settled_grant
    assert read_report(api, report["id"]) == settled_report
    assert read_household(api, household["id"]) == settled_household
    assert read_zone(api, zone["id"]) == settled_zone
