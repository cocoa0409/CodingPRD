"""Lifecycle breadth: initial states, bubbled-up zone transitions, the derived
visit projection, the route-closure conditional cascade, non-idempotent publish,
terminal household lockdown, guarded cancel branches and the plan reissue loop."""

from typing import Any, Dict

from test_helpers import ApiErrorId, COORDINATOR, get_success_data, validate_error
from test_helpers import factories as f
from test_helpers.assertions import assert_grant_money_balanced, assert_instant_equals
from test_helpers.constants import (
    AssessmentStatus,
    CancelReason,
    DeferralReason,
    EducationStatus,
    FollowUpOutcome,
    GrantStatus,
    HouseholdStatus,
    InstallStatus,
    IssuedChannel,
    LapseReason,
    PlanStatus,
    RouteStatus,
    VisitStatus,
)
from test_helpers.fixtures import (
    arrive,
    book_visit,
    create_assessed_zone,
    create_crew,
    create_escape_plan,
    create_household,
    create_partner,
    create_published_route,
    create_route,
    defer_visit,
    deliver_education,
    issue_escape_plan,
    pin_clock,
    publish_route,
    read_escape_plan,
    read_household,
    read_route,
    read_visit,
    read_zone,
)
from test_helpers.test_users import OFFICER, make_crr_technician_headers


def _canvass(api, planned_slots: int = 4) -> Dict[str, Any]:
    """An assessed TIER_2 zone with one ADVANCED crew and one published route."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=planned_slots)
    return {"zone": zone, "crew": crew, "route": route}


def test_01_a_new_grant_starts_in_draft_with_an_empty_money_ledger(api):
    """Nothing is reserved or committed yet, so available equals authorized.

    PRD: "A grant is created in `status` `DRAFT` with `reserved_cents`,
    `committed_cents` and `reported_grant_share_cents` all 0 and `available_cents`
    equal to `authorized_cents`."

    Design: Corner/state_machines/grant_create_starts_in_draft_with_an_empty_money_ledger
    """
    pin_clock(api)
    partner = create_partner(api, contact_email="grants@firesafe.example")

    response = api.create_grant(f.grant_payload(partner["id"]), OFFICER)
    grant = get_success_data(response, 201)

    assert grant["status"] == GrantStatus.DRAFT
    assert grant["reserved_cents"] == 0
    assert grant["committed_cents"] == 0
    assert grant["available_cents"] == 500000
    assert grant["reported_grant_share_cents"] == 0
    assert grant["version"] == 1
    assert_grant_money_balanced(grant)


def test_02_a_deferred_close_out_bubbles_the_zone_all_the_way_to_service_complete(api):
    """The zone's only household completing drives TARGETED -> SERVICE_ACTIVE ->
    SERVICE_COMPLETE inside one request, and a deferral still counts as surveyed.

    PRD: "Both branches stamp `completed_at`, increment the visit's `version` by 1,
    re-derive `visit_status`, and drive the household from `APPOINTMENT_SCHEDULED` to
    `VISIT_COMPLETED` - a deferred visit still counts as surveyed."

    Design: Corner/state_machines/zone_bubbles_up_to_service_complete_when_its_only_household_completes
    """
    ctx = _canvass(api)
    household = create_household(api, ctx["zone"]["id"], address_line="9 Birch Road")
    visit = book_visit(api, household["id"], ctx["route"]["id"])
    arrive(api, visit["id"], ctx["crew"]["id"], pre_existing_working_smoke_alarms=0)
    deliver_education(api, visit["id"], ctx["crew"]["id"])

    closed = defer_visit(
        api, visit["id"], ctx["crew"]["id"], DeferralReason.OCCUPANT_DECLINED_INSTALL
    )
    assert closed["install_status"] == InstallStatus.INSTALL_DEFERRED
    assert closed["visit_status"] == VisitStatus.COMPLETED

    after = read_household(api, household["id"])
    assert after["status"] == HouseholdStatus.VISIT_COMPLETED
    assert_instant_equals(
        after["last_visit_completed_at"], "2026-08-01T00:00:00Z", "last_visit_completed_at"
    )

    zone = read_zone(api, ctx["zone"]["id"])
    assert zone["assessment_status"] == AssessmentStatus.SERVICE_COMPLETE
    assert zone["service_start_date"] == "2026-08-01"
    assert zone["surveyed_units"] == 1
    assert zone["surveyed_units_without_alarm"] == 1
    assert zone["served_household_count"] == 1


def test_03_the_visit_projection_walks_scheduled_in_progress_awaiting_education_completed(api):
    """AWAITING_EDUCATION is only reachable when the install axis terminates first.

    PRD: "Third, if `install_status` is `INSTALL_COMPLETE` or `INSTALL_DEFERRED` while
    `education_status` is still `PENDING`, the projection is `AWAITING_EDUCATION`."

    Design: Corner/state_machines/visit_status_projection_reaches_awaiting_education_then_completed
    """
    ctx = _canvass(api)
    household = create_household(api, ctx["zone"]["id"], address_line="9 Birch Road")
    visit = book_visit(api, household["id"], ctx["route"]["id"])
    assert visit["visit_status"] == VisitStatus.SCHEDULED

    arrived = arrive(api, visit["id"], ctx["crew"]["id"], pre_existing_working_smoke_alarms=2)
    assert arrived["visit_status"] == VisitStatus.IN_PROGRESS
    assert arrived["install_status"] == InstallStatus.SURVEYED
    assert arrived["education_status"] == EducationStatus.PENDING
    assert read_route(api, ctx["route"]["id"])["status"] == RouteStatus.IN_PROGRESS

    deferred = defer_visit(
        api, visit["id"], ctx["crew"]["id"], DeferralReason.STOCK_UNAVAILABLE
    )
    assert deferred["visit_status"] == VisitStatus.AWAITING_EDUCATION
    assert read_household(api, household["id"])["status"] == HouseholdStatus.VISIT_COMPLETED

    declined = get_success_data(
        api.record_education(
            visit["id"],
            f.education_declined_payload(),
            make_crr_technician_headers(ctx["crew"]["id"]),
        )
    )
    assert declined["visit_status"] == VisitStatus.COMPLETED
    assert declined["education_status"] == EducationStatus.DECLINED
    # DECLINED "imposes no requirement on topics_covered and ignores whatever was sent".
    assert declined["education_topics"] is None


def test_04_closing_a_route_cancels_only_the_still_open_visit(api):
    """The completed visit is left completely untouched by the closure cascade.

    PRD: "Closure runs a **conditional cascade**: every visit on the route whose
    `visit_status` is `SCHEDULED` or `IN_PROGRESS` is cancelled with `cancel_reason`
    `ROUTE_CLOSED`, while visits already at `COMPLETED` or `CANCELLED` are left
    completely untouched."

    Design: Corner/state_machines/route_close_conditional_cascade_spares_the_completed_visit
    """
    ctx = _canvass(api)
    crew_id = ctx["crew"]["id"]
    household_a = create_household(api, ctx["zone"]["id"], address_line="1 Birch Road")
    household_b = create_household(api, ctx["zone"]["id"], address_line="2 Birch Road")
    visit_a = book_visit(api, household_a["id"], ctx["route"]["id"])
    visit_b = book_visit(
        api,
        household_b["id"],
        ctx["route"]["id"],
        scheduled_start_utc="2026-08-03T16:00:00Z",
    )
    arrive(api, visit_a["id"], crew_id, pre_existing_working_smoke_alarms=2)
    deliver_education(api, visit_a["id"], crew_id)
    defer_visit(api, visit_a["id"], crew_id, DeferralReason.OCCUPANT_DECLINED_INSTALL)

    closed_route = get_success_data(
        api.close_route(ctx["route"]["id"], COORDINATOR, {"closure_note": "Weather stand-down"})
    )
    assert closed_route["status"] == RouteStatus.CLOSED
    assert closed_route["booked_slot_count"] == 1

    cancelled = read_visit(api, visit_b["id"])
    assert cancelled["visit_status"] == VisitStatus.CANCELLED
    assert cancelled["cancel_reason"] == CancelReason.ROUTE_CLOSED
    assert_instant_equals(cancelled["cancelled_at"], "2026-08-01T00:00:00Z", "cancelled_at")

    reopened = read_household(api, household_b["id"])
    assert reopened["status"] == HouseholdStatus.INTAKE_QUEUED
    assert reopened["canvass_attempt_count"] == 1

    spared = read_visit(api, visit_a["id"])
    assert spared["visit_status"] == VisitStatus.COMPLETED
    assert spared["cancel_reason"] is None
    assert read_household(api, household_a["id"])["status"] == HouseholdStatus.VISIT_COMPLETED


def test_05_publishing_an_already_published_route_is_not_idempotent(api):
    """The second publish is a 409 and does not bump the route's version again.

    PRD: "The step advances a route `PLANNED -> PUBLISHED`; attempting it on a route
    that is not `PLANNED` is rejected with `ERR_ROUTE_NOT_OPEN`."

    Design: Corner/state_machines/route_publish_on_an_already_published_route_returns_409
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    route = create_route(api, zone["id"], crew["id"], planned_slots=4)
    published = publish_route(api, route["id"])

    validate_error(
        api.publish_route(route["id"], COORDINATOR), ApiErrorId.ROUTE_NOT_OPEN, 409
    )

    after = read_route(api, route["id"])
    assert after["status"] == RouteStatus.PUBLISHED
    assert after["version"] == published["version"]


def test_06_booking_for_a_refused_household_is_refused(api):
    """REFUSED is terminal, so the household can never be booked again.

    PRD: "the last two are terminal, and a household in either of them can never be
    booked again - an attempt is rejected with `ERR_INVALID_HOUSEHOLD_STATE`."

    Design: Corner/state_machines/booking_a_visit_for_a_refused_household_returns_409
    """
    ctx = _canvass(api)
    household = create_household(api, ctx["zone"]["id"], address_line="9 Birch Road")
    visit = book_visit(api, household["id"], ctx["route"]["id"])
    get_success_data(
        api.cancel_visit(
            visit["id"], f.cancel_payload(CancelReason.OCCUPANT_REFUSED), COORDINATOR
        )
    )

    validate_error(
        api.create_visit(
            f.visit_payload(
                household["id"],
                ctx["route"]["id"],
                scheduled_start_utc="2026-08-03T17:00:00Z",
            ),
            COORDINATOR,
        ),
        ApiErrorId.INVALID_HOUSEHOLD_STATE,
        409,
    )

    after = read_household(api, household["id"])
    assert after["status"] == HouseholdStatus.REFUSED
    assert after["canvass_attempt_count"] == 1
    assert read_route(api, ctx["route"]["id"])["booked_slot_count"] == 0


def test_07_the_first_unreachable_cancellation_returns_the_household_to_the_queue(api):
    """One attempt is not three, so OCCUPANT_UNREACHABLE does not reach NO_CONTACT.

    PRD: "`OCCUPANT_UNREACHABLE` moves the household to the terminal `NO_CONTACT`, but
    **only** once the division has genuinely tried: the household's
    `canvass_attempt_count` must be at least 3. With fewer than three recorded attempts
    the same unreachable cancellation lands the household back in `INTAKE_QUEUED`
    instead."

    Design: Corner/state_machines/first_unreachable_cancel_returns_to_intake_queued_not_no_contact
    """
    ctx = _canvass(api)
    household = create_household(api, ctx["zone"]["id"], address_line="9 Birch Road")
    visit = book_visit(api, household["id"], ctx["route"]["id"])

    cancelled = get_success_data(
        api.cancel_visit(
            visit["id"], f.cancel_payload(CancelReason.OCCUPANT_UNREACHABLE), COORDINATOR
        )
    )
    assert cancelled["visit_status"] == VisitStatus.CANCELLED

    after = read_household(api, household["id"])
    assert after["status"] == HouseholdStatus.INTAKE_QUEUED
    assert after["status"] != HouseholdStatus.NO_CONTACT
    assert after["canvass_attempt_count"] == 1
    assert read_route(api, ctx["route"]["id"])["booked_slot_count"] == 0


def test_08_reissuing_a_lapsed_plan_clears_the_lapse_and_counts_the_reissue(api):
    """An unpractised drill lapses the plan; the re-issue walks LAPSED -> ISSUED.

    PRD: "a re-issue from `LAPSED` additionally increments `reissue_count` by 1 and
    clears both `lapsed_at` and `lapse_reason`, whereas a first issue from `DRAFT`
    touches neither."

    Design: Corner/state_machines/escape_plan_reissue_after_a_lapse_increments_reissue_count
    """
    ctx = _canvass(api)
    household = create_household(
        api,
        ctx["zone"]["id"],
        address_line="9 Birch Road",
        occupant_count=3,
        sleeping_areas_count=2,
        storeys=1,
    )
    visit = book_visit(api, household["id"], ctx["route"]["id"])
    arrive(api, visit["id"], ctx["crew"]["id"], pre_existing_working_smoke_alarms=3)
    deliver_education(api, visit["id"], ctx["crew"]["id"])
    defer_visit(api, visit["id"], ctx["crew"]["id"], DeferralReason.OCCUPANT_DECLINED_INSTALL)

    served = read_household(api, household["id"])
    plan = create_escape_plan(
        api,
        household["id"],
        served["version"],
        secondary_exit_count=2,
        meeting_point_description="Oak tree across the street",
    )
    issue_escape_plan(api, plan["id"], issued_channel=IssuedChannel.IN_PERSON)
    pin_clock(api, "2026-09-05T00:00:00Z")

    contact = get_success_data(
        api.create_follow_up(
            f.follow_up_reached_present_payload(
                household["id"], alarms_present_count=3, plan_practiced=False
            ),
            COORDINATOR,
        ),
        201,
    )
    assert contact["attempt_no"] == 1
    assert contact["days_since_visit"] == 35
    assert contact["outcome"] == FollowUpOutcome.REACHED_ALARM_PRESENT

    lapsed = read_escape_plan(api, plan["id"])
    assert lapsed["status"] == PlanStatus.LAPSED
    assert lapsed["lapse_reason"] == LapseReason.DRILL_NOT_PRACTICED
    after_contact = read_household(api, household["id"])
    assert after_contact["status"] == HouseholdStatus.VISIT_COMPLETED
    assert after_contact["alarm_retention_flag"] is True

    reissued = issue_escape_plan(api, plan["id"], issued_channel=IssuedChannel.EMAIL)
    assert reissued["status"] == PlanStatus.ISSUED
    assert reissued["reissue_count"] == 1
    assert reissued["lapsed_at"] is None
    assert reissued["lapse_reason"] is None
    assert reissued["issued_channel"] == IssuedChannel.EMAIL
