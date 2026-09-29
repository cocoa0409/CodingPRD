"""Endpoint surface breadth: the device-lot receipt round trip, the reschedule action's
slot bookkeeping, the computed outcome read over an unserved zone, an action that is
only conditionally available, and the exclusive household-to-plan link."""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_calendar_date,
    assert_grant_money_balanced,
    assert_instant_equals,
    assert_lot_status_derived,
    assert_lot_units_conserved,
    assert_mutable_record,
)
from test_helpers.constants import (
    AssessmentStatus,
    DeferralReason,
    DeviceType,
    HouseholdStatus,
    InstallStatus,
    LotStatus,
    PlanStatus,
    VisitStatus,
)
from test_helpers.fixtures import (
    arrive,
    book_visit,
    create_active_grant,
    create_assessed_zone,
    create_crew,
    create_escape_plan,
    create_household,
    create_lot,
    create_published_route,
    defer_visit,
    deliver_education,
    funded_program,
    pin_clock,
    read_escape_plan,
    read_grant,
    read_household,
    read_lot,
    read_route,
    read_visit,
    read_zone,
    record_fire_incident,
)
from test_helpers.test_users import ANALYST, COORDINATOR, OFFICER, make_crr_technician_headers


def _served_household(api) -> Dict[str, Any]:
    """One household closed out through the deferred branch at the program epoch."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(api, zone["id"], address_line="12 Birch Row")
    visit = book_visit(api, household["id"], route["id"])
    arrive(api, visit["id"], crew["id"])
    deliver_education(api, visit["id"], crew["id"])
    defer_visit(api, visit["id"], crew["id"], DeferralReason.LANDLORD_APPROVAL_REQUIRED)
    return {
        "zone": zone,
        "crew": crew,
        "route": route,
        "household": read_household(api, household["id"]),
        "visit": visit,
    }


def test_01_a_device_lot_receipt_reads_back_and_lists_identically(api):
    """The receipt opens the three quantity counters, and the same row comes back
    unchanged by id and through the grant-filtered list.

    PRD: "A new lot starts with `on_hand_qty` equal to `received_qty`, `reserved_qty`
    and `consumed_qty` at 0, and `status` `AVAILABLE`."

    Design: Corner/endpoints/device_lot_receipt_read_and_list_round_trip
    """
    pin_clock(api)
    grant = create_active_grant(api)
    lot = create_lot(
        api,
        grant["id"],
        sku="SKU-SM10-A",
        unit_cost_cents=1850,
        received_qty=60,
        expiry_date="2027-06-30",
    )

    assert lot["funding_grant_id"] == grant["id"]
    assert lot["received_qty"] == 60
    assert lot["on_hand_qty"] == 60
    assert lot["reserved_qty"] == 0
    assert lot["consumed_qty"] == 0
    assert lot["status"] == LotStatus.AVAILABLE
    assert_mutable_record(lot, 1)
    assert_lot_units_conserved(lot)
    assert_lot_status_derived(lot)
    assert_calendar_date(lot["expiry_date"], "expiry_date")

    stored = read_lot(api, lot["id"])
    assert stored == lot
    assert stored["sku"] == "SKU-SM10-A"
    assert stored["unit_cost_cents"] == 1850
    assert stored["device_type"] == DeviceType.SMOKE_10YR
    assert stored["expiry_date"] == "2027-06-30"

    rows, meta = validate_paginated(
        api.list_device_lots(OFFICER, params={"funding_grant_id": grant["id"]})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0] == lot

    _, depleted_meta = validate_paginated(
        api.list_device_lots(OFFICER, params={"status": LotStatus.DEPLETED})
    )
    assert depleted_meta["total_count"] == 0

    funder = read_grant(api, grant["id"])
    assert funder["reserved_cents"] == 0
    assert funder["available_cents"] == 500000
    assert_grant_money_balanced(funder)


def test_02_rescheduling_inside_one_route_leaves_the_slot_count_at_one(api):
    """The counter is decremented and re-incremented on the same route, the interval
    moves with the new start, and the household is untouched.

    PRD: "It re-runs the time-demand arithmetic against the new route's zone tier and
    rewrites both `demand_minutes` and `scheduled_end_utc`. ... It leaves `visit_status`
    at `SCHEDULED` and leaves the household's `status` untouched - a reschedule is not a
    new attempt, and `canvass_attempt_count` does not move."

    Design: Corner/endpoints/visit_reschedule_moves_the_slot_and_recomputes_the_interval
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(api, zone["id"], address_line="12 Birch Row")
    visit = book_visit(api, household["id"], route["id"])
    booked_route = read_route(api, route["id"])
    assert booked_route["booked_slot_count"] == 1

    moved = get_success_data(
        api.reschedule_visit(
            visit["id"],
            f.reschedule_payload(route["id"], "2026-08-03T18:00:00Z"),
            COORDINATOR,
        )
    )
    assert_instant_equals(
        moved["scheduled_start_utc"], "2026-08-03T18:00:00Z", "scheduled_start_utc"
    )
    assert_instant_equals(
        moved["scheduled_end_utc"], "2026-08-03T18:35:00Z", "scheduled_end_utc"
    )
    assert moved["demand_minutes"] == 35
    assert moved["occupies_crew_calendar"] is True
    assert moved["visit_status"] == VisitStatus.SCHEDULED
    assert moved["route_id"] == route["id"]
    assert moved["version"] == visit["version"] + 1

    after = read_route(api, route["id"])
    assert after["booked_slot_count"] == 1
    # The route did not actually change, so no route counter and no route version moved.
    assert after["version"] == booked_route["version"]

    stored = read_household(api, household["id"])
    assert stored["status"] == HouseholdStatus.APPOINTMENT_SCHEDULED
    assert stored["canvass_attempt_count"] == 1
    assert stored["version"] == household["version"] + 1


def test_03_an_unserved_zone_reports_null_outcome_metrics_not_zeroes(api):
    """The zone has incidents on both sides of today but no anchor, so no window can be
    placed and nothing is fabricated from the current date.

    PRD: "If a zone's `service_start_date` is null, every outcome figure for that zone
    is null and the zone is excluded from a report's rollup on both sides."

    Design: Corner/endpoints/outcome_summary_of_an_unserved_zone_returns_null_metrics
    """
    pin_clock(api, "2026-09-05T00:00:00Z")
    zone = create_assessed_zone(api)
    record_fire_incident(
        api,
        zone["id"],
        incident_number="INC-2026-0001",
        occurred_at="2026-05-01T03:00:00Z",
        working_alarm_present=False,
        injuries=2,
    )
    record_fire_incident(
        api,
        zone["id"],
        incident_number="INC-2026-0002",
        occurred_at="2026-08-20T21:00:00Z",
        working_alarm_present=True,
        injuries=1,
    )

    summary = get_success_data(api.get_outcome_summary(zone["id"], ANALYST))
    assert summary["zone_id"] == zone["id"]
    for field in (
        "service_start_date",
        "baseline_fire_count",
        "post_fire_count",
        "baseline_fire_rate_per_1000",
        "post_fire_rate_per_1000",
        "rate_delta_pct",
        "baseline_injuries",
        "post_injuries",
        "injury_delta",
    ):
        assert summary[field] is None, f"{field} must be null without a service anchor"
    assert summary["served_household_count"] == 0
    assert summary["retention_eligible_count"] == 0
    assert summary["retention_rate_pct"] is None

    assert read_zone(api, zone["id"])["assessment_status"] == AssessmentStatus.ASSESSED


def test_04_an_installation_before_arrival_is_refused_before_any_ledger_moves(api):
    """The reservation endpoint is only available once the survey is on file, and the
    refusal happens before the selector, the stock gate or the money gate.

    PRD: "The visit must have `install_status` `SURVEYED` and must not be a
    `VIRTUAL_ASSESSMENT` appointment; a remote assessment cannot host a physical
    device."

    Design: Corner/endpoints/installation_attempted_before_arrival_returns_409
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(api, zone["id"], address_line="12 Birch Row")
    visit = book_visit(api, household["id"], route["id"])
    funding = funded_program(
        api,
        lot_overrides={
            "sku": "SKU-SM10-A",
            "unit_cost_cents": 1850,
            "received_qty": 60,
            "expiry_date": "2027-06-30",
        },
    )
    assert visit["install_status"] == InstallStatus.NOT_STARTED

    response = api.create_installation(
        f.installation_payload(
            visit["id"],
            placement_location="HALLWAY_OUTSIDE_SLEEPING",
            storey=1,
        ),
        make_crr_technician_headers(crew["id"]),
    )
    validate_error(response, ApiErrorId.INVALID_VISIT_STATE, 409)

    _, meta = validate_paginated(
        api.list_installations(OFFICER, params={"visit_id": visit["id"]})
    )
    assert meta["total_count"] == 0

    lot = read_lot(api, funding["lot"]["id"])
    assert lot["reserved_qty"] == 0
    assert lot["on_hand_qty"] == 60
    grant = read_grant(api, funding["grant"]["id"])
    assert grant["reserved_cents"] == 0
    assert grant["available_cents"] == 500000

    unchanged = read_visit(api, visit["id"])
    assert unchanged["install_status"] == InstallStatus.NOT_STARTED
    assert unchanged["version"] == 1


def test_05_a_second_escape_plan_supersedes_the_households_live_plan(api):
    """A household holds one live plan at a time, and each create bumps the household's
    own version, so the second create needs a freshly read guard value.

    PRD: "A new plan lands at `status` `DRAFT` with `reissue_count` at 0, and it
    **supersedes** whatever plan the household already had: any existing plan of that
    household in `DRAFT`, `ISSUED`, `VERIFIED` or `LAPSED` moves to the terminal
    `SUPERSEDED`, with that superseded plan's `version` incremented by 1."

    Design: Corner/endpoints/escape_plan_create_supersedes_the_households_live_plan
    """
    ctx = _served_household(api)
    household = ctx["household"]

    first = create_escape_plan(
        api,
        household["id"],
        household["version"],
        secondary_exit_count=1,
        meeting_point_description="Mailbox at the kerb",
    )
    assert first["status"] == PlanStatus.DRAFT

    bumped = read_household(api, household["id"])
    assert bumped["version"] == household["version"] + 1

    second = create_escape_plan(
        api,
        household["id"],
        bumped["version"],
        secondary_exit_count=2,
        meeting_point_description="Corner of Birch Row and 4th",
    )
    assert second["status"] == PlanStatus.DRAFT
    assert second["household_id"] == household["id"]
    assert second["reissue_count"] == 0

    superseded = read_escape_plan(api, first["id"])
    assert superseded["status"] == PlanStatus.SUPERSEDED
    assert superseded["issued_at"] is None
    assert superseded["lapse_reason"] is None
    assert superseded["version"] == first["version"] + 1

    _, all_meta = validate_paginated(
        api.list_escape_plans(COORDINATOR, params={"household_id": household["id"]})
    )
    assert all_meta["total_count"] == 2
    _, superseded_meta = validate_paginated(
        api.list_escape_plans(
            COORDINATOR,
            params={"household_id": household["id"], "status": PlanStatus.SUPERSEDED},
        )
    )
    assert superseded_meta["total_count"] == 1

    assert read_household(api, household["id"])["version"] == bumped["version"] + 1
