"""Cross-entity state gates and per-resource window overlap.

Every test in this file turns on a rule held by a *different* row than the one
being written: the referral's consent dimension gating evaluation-case creation
(PRD §3.4), the named provider's own status gating service-line staffing
(PRD §3.8), the parent screening event's status gating appointment booking
(PRD §3.2), and the two window-overlap rules that measure a new window against
windows already committed at the same site or by the same evaluator
(PRD §3.2, PRD §3.5).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_domain_assessment,
    assert_fields_absent,
    assert_instant,
    assert_provider_minute_ledger,
    assert_screening_event,
    assert_screening_slot,
    assert_service_line,
    assert_subset,
)
from test_helpers.constants import (
    expected_assigned_minutes,
    expected_travel_overhead,
    ts,
)
from test_helpers.test_users import TEST_USERS

COORDINATOR = TEST_USERS["coordinator_headers"]
PLACEMENT = TEST_USERS["placement_headers"]

EVENT_WINDOW_START = "2026-08-20T09:00:00Z"
EVENT_WINDOW_END = "2026-08-20T12:00:00Z"


# --------------------------------------------------------------- local setup helpers
def _cases_for_referral(api, referral_id):
    """Every evaluation case the API reports against one referral."""
    return validate_paginated(
        api.list_evaluation_cases(COORDINATOR, {"referral_id": referral_id, "limit": 100})
    )


def _events_for_site(api, site_id):
    """Every screening event the API reports at one community site."""
    return validate_paginated(
        api.list_screening_events(COORDINATOR, {"site_id": site_id, "limit": 100})
    )


def _draft_plan_with_proposed_slp_line(api, weekly_minutes=150, ceiling=400):
    """A DRAFT community-preschool plan holding one PROPOSED SLP DIRECT line.

    The line's own lifecycle, the plan's status and the provider's discipline all
    permit staffing, so the only rule left to bite is the provider's status.
    """
    site = fx.register_site(api)
    context = fx.setup_draft_plan(
        api, setting="COMMUNITY_PRESCHOOL", community_site_id=site["id"]
    )
    context["site"] = site
    context["line"] = fx.add_line(
        api,
        context["plan"]["id"],
        discipline="SLP",
        weekly_minutes=weekly_minutes,
        delivery_model="DIRECT",
    )
    context["slp"] = fx.register_provider(
        api, discipline="SLP", max_weekly_service_minutes=ceiling
    )
    context["weekly_minutes"] = weekly_minutes
    return context


def _scheduled_event(api, children=1):
    """A SCHEDULED three-hour event with thirty-minute appointments, plus children."""
    site = fx.register_site(api)
    event = fx.create_screening_event(
        api,
        site["id"],
        window_start_utc=ts(EVENT_WINDOW_START),
        window_end_utc=ts(EVENT_WINDOW_END),
        slot_capacity=4,
        slot_length_minutes=30,
    )
    return site, event, [fx.register_child(api) for _ in range(children)]


def _case_with_district_centre_assessment(api):
    """An evaluation case whose first assessment sits at the district centre.

    The evaluator is an ECSE_TEACHER, which may assess COMMUNICATION, COGNITIVE
    and ADAPTIVE, and is never the case's own chair.
    """
    site = fx.register_site(api)
    chair = fx.register_chair(api)
    evaluator = fx.register_provider(api, discipline="ECSE_TEACHER")
    context = fx.setup_case(api, chair=chair, assessment_protocol="STANDARDIZED")
    first = fx.schedule_assessment(
        api,
        context["case"]["id"],
        evaluator["id"],
        domain="COMMUNICATION",
        method="STANDARDIZED",
        window_start_utc=ts("2026-08-20T09:00:00Z"),
    )
    context["site"] = site
    context["evaluator"] = evaluator
    context["first"] = first
    return context


# =====================================================================================
# Opening an evaluation case reads the referral's consent dimension, not its intake one
# =====================================================================================
def test_opening_a_case_while_consent_is_only_requested_reports_consent_not_granted(api):
    """A referral mid-notice is refused on the consent dimension, not on intake state.

    PRD §3.3 pins the intake dimension after issuance: "A successful issuance moves
    both dimensions of the referral in the same request: `intake_status` advances
    `RECEIVED → CONSENT_PENDING` and `consent_status` advances
    `NOT_REQUESTED → REQUESTED`."

    PRD §3.4 then pins which of the two dimensions the case endpoint reads: "Opening
    an evaluation case against a referral whose `consent_status` is `NOT_REQUESTED`,
    `REQUESTED`, `REFUSED` or `REVOKED` is refused with `ERR_CONSENT_NOT_GRANTED` —
    not with a state error — regardless of what the intake dimension currently reads."

    Design: Difficulty/cross_entity_state_dependency/case_creation_reads_the_referral_consent_dimension_not_its_intake_dimension
    """
    child = fx.register_child(api)
    referral = fx.create_referral(api, child["id"])
    fx.issue_evaluation_notice(api, referral["id"])
    chair = fx.register_chair(api)

    issued = fx.read_referral(api, referral["id"])
    assert_subset(issued, {"intake_status": "CONSENT_PENDING", "consent_status": "REQUESTED"})

    response = api.open_evaluation_case(
        referral["id"], f.evaluation_case_payload(chair["id"]), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value)

    unchanged = fx.read_referral(api, referral["id"])
    assert_subset(
        unchanged,
        {
            "intake_status": "CONSENT_PENDING",
            "consent_status": "REQUESTED",
            "version": issued["version"],
        },
    )
    rows, meta = _cases_for_referral(api, referral["id"])
    assert meta["total_count"] == 0, f"refused creation must persist nothing: {rows}"


def test_opening_a_case_once_consent_is_granted_is_accepted(api):
    """With the consent dimension at `GRANTED` the same request is honoured.

    PRD §3.4: "Opening an evaluation case against a referral whose `consent_status`
    is `NOT_REQUESTED`, `REQUESTED`, `REFUSED` or `REVOKED` is refused with
    `ERR_CONSENT_NOT_GRANTED` — not with a state error — regardless of what the
    intake dimension currently reads."

    PRD §3.4 on the accepted shape: "A new case is written at `PLANNED` with
    `revision_round` at 0 and `required_domain_count` fixed by the system at 5 — the
    five developmental domains the team must cover."

    Design: Difficulty/cross_entity_state_dependency/case_creation_reads_the_referral_consent_dimension_not_its_intake_dimension
    """
    context = fx.setup_referral_with_granted_consent(api)
    referral = context["referral"]
    chair = fx.register_chair(api)

    granted = fx.read_referral(api, referral["id"])
    assert_subset(
        granted, {"intake_status": "EVALUATION_AUTHORIZED", "consent_status": "GRANTED"}
    )

    case = validate_success(
        api.open_evaluation_case(
            referral["id"], f.evaluation_case_payload(chair["id"]), COORDINATOR
        ),
        201,
    )
    assert_subset(
        case,
        {
            "referral_id": referral["id"],
            "child_id": context["child"]["id"],
            "chair_provider_id": chair["id"],
            "status": "PLANNED",
            "revision_round": 0,
            "required_domain_count": 5,
            "version": 1,
        },
    )


def test_a_superseded_referral_still_holding_granted_consent_reports_invalid_referral_state(api):
    """The one state pair the consent dimension cannot explain is intake `SUPERSEDED`.

    PRD §3.3: "every earlier referral of that same child whose `intake_status` is
    `RECEIVED`, `CONSENT_PENDING` or `EVALUATION_AUTHORIZED` is moved to
    `SUPERSEDED`, with `superseded_by_referral_id` set to the new referral's
    identifier and its `version` incremented", and "Displacing one from
    `EVALUATION_AUTHORIZED` additionally cancels that referral's evaluation case,
    provided that case has not already reached `ELIGIBILITY_DETERMINED` or
    `CANCELLED`".

    PRD §3.4: "the single state pair the consent dimension cannot explain is a
    referral whose consent is `GRANTED` but whose `intake_status` has since become
    `SUPERSEDED` by a newer referral for the same child, which alone yields
    `ERR_INVALID_REFERRAL_STATE` on that endpoint".

    Design: Difficulty/cross_entity_state_dependency/case_creation_reads_the_referral_consent_dimension_not_its_intake_dimension
    """
    context = fx.setup_referral_with_granted_consent(api)
    child_id = context["child"]["id"]
    referral = context["referral"]
    chair = fx.register_chair(api)
    first_case = fx.open_case(api, referral["id"], chair["id"])

    newer = fx.create_referral(api, child_id)

    displaced = fx.read_referral(api, referral["id"])
    assert_subset(
        displaced,
        {
            "intake_status": "SUPERSEDED",
            "consent_status": "GRANTED",
            "superseded_by_referral_id": newer["id"],
        },
    )
    assert fx.read_case(api, first_case["id"])["status"] == "CANCELLED", (
        "displacing from EVALUATION_AUTHORIZED cancels that referral's case"
    )

    response = api.open_evaluation_case(
        referral["id"], f.evaluation_case_payload(chair["id"]), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REFERRAL_STATE.value)

    rows, meta = _cases_for_referral(api, referral["id"])
    assert meta["total_count"] == 1, f"no second case may be written: {rows}"


# =====================================================================================
# Staffing an otherwise valid line is gated on the named provider's own status
# =====================================================================================
def test_staffing_a_line_with_an_on_leave_provider_is_refused_and_writes_nothing(api):
    """The line, the plan and the discipline all agree; only the provider is ON_LEAVE.

    PRD §3.1: "A `DistrictAdmin` may later amend a provider's `status`, `languages`,
    `max_weekly_service_minutes`, `max_evaluation_caseload` or
    `max_weekly_interpreter_assignments` — this is how a provider is placed
    `ON_LEAVE`", and "A provider whose `status` is `ON_LEAVE` or `INACTIVE` may not be
    given a new chair assignment, a new domain assessment, a new service line, or a
    new interpreter assignment; each such attempt is refused with
    `ERR_PROVIDER_NOT_ACTIVE`."

    PRD §3.8: "The named provider's `status` must be `ACTIVE`, else
    `ERR_PROVIDER_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/staffing_a_valid_line_fails_on_the_providers_own_status_and_recovers
    """
    context = _draft_plan_with_proposed_slp_line(api)
    line = context["line"]
    on_leave = fx.patch_provider(api, context["slp"]["id"], status="ON_LEAVE")
    assert on_leave["status"] == "ON_LEAVE", "the amendment must land before staffing"

    response = api.staff_service_line(
        line["id"],
        f.staffing_payload(context["slp"]["id"], on_leave["version"]),
        PLACEMENT,
    )
    validate_error(response, ApiErrorId.ERR_PROVIDER_NOT_ACTIVE.value)

    untouched = fx.read_line(api, line["id"])
    assert_service_line(untouched, expected_version=line["version"])
    assert untouched["status"] == "PROPOSED", "a refused staffing leaves the line alone"
    assert_fields_absent(untouched, "provider_id", "delivery_site_id")
    assert_provider_minute_ledger(
        fx.read_provider(api, context["slp"]["id"]), 0, 0, 0, "OPEN"
    )
    assert fx.read_plan(api, context["plan"]["id"])["assigned_weekly_minutes"] == 150, (
        "the plan total already counts the PROPOSED line and is untouched by the refusal"
    )


def test_staffing_the_same_line_succeeds_once_the_provider_is_active_again(api):
    """Returning the provider to ACTIVE clears the only failing gate.

    PRD §3.8: "The named provider's `status` must be `ACTIVE`, else
    `ERR_PROVIDER_NOT_ACTIVE`."

    PRD §3.8 on the accepted write: "A successful staffing moves the line
    `PROPOSED → STAFFED` or `UNSTAFFED → STAFFED`, sets `provider_id` to the named
    provider and `delivery_site_id` to the supplied or defaulted location, recomputes
    that provider's `direct_weekly_service_minutes`, `travel_overhead_minutes` and
    `assigned_weekly_service_minutes`, re-derives the provider's
    `service_capacity_posture`, recomputes the parent plan's `assigned_weekly_minutes`,
    and increments both the provider's `version` and the line's `version`."

    PRD §3.8 on the defaulted location: "When `delivery_site_id` is omitted it
    defaults to the parent plan's own `community_site_id`".

    Design: Difficulty/cross_entity_state_dependency/staffing_a_valid_line_fails_on_the_providers_own_status_and_recovers
    """
    context = _draft_plan_with_proposed_slp_line(api)
    line = context["line"]
    provider_id = context["slp"]["id"]
    on_leave = fx.patch_provider(api, provider_id, status="ON_LEAVE")
    validate_error(
        api.staff_service_line(
            line["id"], f.staffing_payload(provider_id, on_leave["version"]), PLACEMENT
        ),
        ApiErrorId.ERR_PROVIDER_NOT_ACTIVE.value,
    )

    reinstated = fx.patch_provider(api, provider_id, status="ACTIVE")
    staffed = validate_success(
        api.staff_service_line(
            line["id"], f.staffing_payload(provider_id, reinstated["version"]), PLACEMENT
        ),
        200,
    )

    assert_subset(
        staffed,
        {
            "status": "STAFFED",
            "provider_id": provider_id,
            "delivery_site_id": context["site"]["id"],
            "version": line["version"] + 1,
        },
    )
    after = fx.read_provider(api, provider_id)
    assert_provider_minute_ledger(
        after,
        150,
        expected_travel_overhead(150, 1),
        expected_assigned_minutes(150, 1),
        "OPEN",
    )
    assert after["version"] == reinstated["version"] + 1, (
        "a successful staffing increments the provider's version exactly once"
    )
    assert fx.read_plan(api, context["plan"]["id"])["assigned_weekly_minutes"] == 150


# =====================================================================================
# Booking an appointment is gated on the parent event's status being OPEN
# =====================================================================================
def test_booking_into_a_scheduled_event_is_refused_before_it_opens(api):
    """A well-formed appointment inside the window still fails while the event is SCHEDULED.

    PRD §3.2: "A new event opens at `SCHEDULED` and advances through the coordinator's
    status endpoint, which takes a single `target_status` input", and "only an `OPEN`
    event accepts bookings".

    PRD §3.2: "Booking into an event that is not `OPEN` is `ERR_INVALID_EVENT_STATE`."

    Design: Difficulty/cross_entity_state_dependency/slot_booking_is_gated_on_the_parent_events_status_open_only
    """
    site, event, children = _scheduled_event(api)
    assert_screening_event(event, expected_version=1)
    assert event["status"] == "SCHEDULED", "a new event opens at SCHEDULED"
    assert event["effective_slot_capacity"] == 4, (
        "min(declared 4, floor(180 / 30) = 6) is 4"
    )

    response = api.book_screening_slot(
        event["id"],
        f.slot_booking_payload(
            children[0]["id"], event["version"], slot_start_utc=ts("2026-08-20T09:30:00Z")
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_EVENT_STATE.value)

    unchanged = fx.read_event(api, event["id"])
    assert_subset(
        unchanged,
        {"status": "SCHEDULED", "booked_slot_count": 0, "version": event["version"]},
    )
    rows, meta = validate_paginated(
        api.list_screening_slots(COORDINATOR, {"screening_event_id": event["id"]})
    )
    assert meta["total_count"] == 0, f"no appointment may be written: {rows}"


def test_booking_into_an_open_event_is_accepted_and_derives_the_slot_end(api):
    """Once the event reaches OPEN the identical request is honoured.

    PRD §3.2: "`SCHEDULED → OPEN` requires the host site still to be `ACTIVE` with
    `screening_host_approved` true and requires the logical clock to be earlier than
    `window_end_utc`; only an `OPEN` event accepts bookings."

    PRD §3.2: "The appointment's `slot_end_utc` is derived, never supplied: it is
    `slot_start_utc` advanced by the parent event's `slot_length_minutes`.", and "A
    successful booking creates the appointment at `BOOKED`, recomputes the parent
    event's `booked_slot_count`, and increments the parent event's `version`."

    Design: Difficulty/cross_entity_state_dependency/slot_booking_is_gated_on_the_parent_events_status_open_only
    """
    site, event, children = _scheduled_event(api)
    opened = fx.advance_event(api, event["id"], "OPEN")
    assert opened["status"] == "OPEN"

    slot = validate_success(
        api.book_screening_slot(
            event["id"],
            f.slot_booking_payload(
                children[0]["id"], opened["version"], slot_start_utc=ts("2026-08-20T09:30:00Z")
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_screening_slot(slot, expected_version=1)
    assert_subset(
        slot,
        {
            "screening_event_id": event["id"],
            "child_id": children[0]["id"],
            "status": "BOOKED",
        },
    )
    assert_instant(slot["slot_start_utc"], ts("2026-08-20T09:30:00Z"), "slot.slot_start_utc")
    assert_instant(slot["slot_end_utc"], ts("2026-08-20T10:00:00Z"), "slot.slot_end_utc")

    after = fx.read_event(api, event["id"])
    assert_subset(after, {"booked_slot_count": 1, "version": opened["version"] + 1})


def test_booking_into_a_closed_event_is_refused_and_leaves_the_booked_count(api):
    """Closing the event withdraws the booking permission it had while OPEN.

    PRD §3.2: "`OPEN → CLOSED` has no precondition beyond the from-state, and once an
    event is `CLOSED` further booking attempts are refused with
    `ERR_INVALID_EVENT_STATE`."

    PRD §3.2: "A successful booking creates the appointment at `BOOKED`, recomputes the
    parent event's `booked_slot_count`, and increments the parent event's `version`."

    Design: Difficulty/cross_entity_state_dependency/slot_booking_is_gated_on_the_parent_events_status_open_only
    """
    site, event, children = _scheduled_event(api, children=2)
    opened = fx.advance_event(api, event["id"], "OPEN")
    fx.book_slot(
        api, opened, children[0]["id"], slot_start_utc=ts("2026-08-20T09:30:00Z")
    )
    closed = fx.advance_event(api, event["id"], "CLOSED")
    assert_subset(closed, {"status": "CLOSED", "booked_slot_count": 1})

    response = api.book_screening_slot(
        event["id"],
        f.slot_booking_payload(
            children[1]["id"], closed["version"], slot_start_utc=ts("2026-08-20T10:30:00Z")
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_EVENT_STATE.value)

    after = fx.read_event(api, event["id"])
    assert_subset(
        after,
        {"status": "CLOSED", "booked_slot_count": 1, "version": closed["version"]},
    )
    rows, meta = validate_paginated(
        api.list_screening_slots(COORDINATOR, {"screening_event_id": event["id"]})
    )
    assert meta["total_count"] == 1, f"only the appointment booked while OPEN exists: {rows}"


# =====================================================================================
# Screening event windows collide per site, half-open, with no buffer
# =====================================================================================
def test_a_straddling_window_at_the_same_site_is_refused(api):
    """A window that starts inside a committed window collides on both halves of the test.

    PRD §3.2: "A new event's window must not overlap the window of any other
    non-cancelled event at the same site, where two windows conflict exactly when the
    new start falls before the existing end **and** the existing start falls before the
    new end. No buffer is applied, so exact adjacency — a new event starting at the
    precise instant an existing one ends — is permitted, and cancelled events are
    ignored entirely. A conflict is `ERR_SITE_EVENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/screening_event_windows_overlap_per_site_half_open_with_no_buffer
    """
    site = fx.register_site(api)
    existing = fx.create_screening_event(
        api,
        site["id"],
        window_start_utc=ts("2026-08-20T09:00:00Z"),
        window_end_utc=ts("2026-08-20T12:00:00Z"),
        slot_capacity=4,
        slot_length_minutes=30,
    )

    response = api.create_screening_event(
        f.screening_event_payload(
            site["id"],
            window_start_utc=ts("2026-08-20T11:00:00Z"),
            window_end_utc=ts("2026-08-20T13:00:00Z"),
            slot_capacity=4,
            slot_length_minutes=30,
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_SITE_EVENT_OVERLAP.value)

    rows, meta = _events_for_site(api, site["id"])
    assert meta["total_count"] == 1, f"the refused event must not be written: {rows}"
    assert rows[0]["id"] == existing["id"]


def test_an_exactly_adjacent_window_at_the_same_site_is_permitted(api):
    """Starting at the precise instant the committed window ends is not a conflict.

    PRD §3.2: "No buffer is applied, so exact adjacency — a new event starting at the
    precise instant an existing one ends — is permitted, and cancelled events are
    ignored entirely. A conflict is `ERR_SITE_EVENT_OVERLAP`."

    PRD §3.2 on the derived capacity: "On creation the system computes
    `effective_slot_capacity` as the lesser of the declared `slot_capacity` and the
    number of whole appointments the window can physically hold — that is, the whole
    number of minutes between `window_start_utc` and `window_end_utc` divided by
    `slot_length_minutes` and truncated downward, never rounded up."

    Design: Difficulty/resource_temporal_overlap/screening_event_windows_overlap_per_site_half_open_with_no_buffer
    """
    site = fx.register_site(api)
    fx.create_screening_event(
        api,
        site["id"],
        window_start_utc=ts("2026-08-20T09:00:00Z"),
        window_end_utc=ts("2026-08-20T12:00:00Z"),
        slot_capacity=4,
        slot_length_minutes=30,
    )

    adjacent = validate_success(
        api.create_screening_event(
            f.screening_event_payload(
                site["id"],
                window_start_utc=ts("2026-08-20T12:00:00Z"),
                window_end_utc=ts("2026-08-20T14:00:00Z"),
                slot_capacity=4,
                slot_length_minutes=30,
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_screening_event(adjacent, expected_version=1)
    assert_subset(
        adjacent,
        {
            "site_id": site["id"],
            "status": "SCHEDULED",
            "effective_slot_capacity": 4,
            "booked_slot_count": 0,
        },
    )
    assert_instant(
        adjacent["window_start_utc"], ts("2026-08-20T12:00:00Z"), "event.window_start_utc"
    )

    rows, meta = _events_for_site(api, site["id"])
    assert meta["total_count"] == 2, f"both windows coexist at this site: {rows}"


def test_the_same_straddling_window_is_permitted_at_a_different_site(api):
    """The overlap test is scoped to one site, so a second site is unaffected.

    PRD §3.2: "Sites cannot be double-booked. A new event's window must not overlap the
    window of any other non-cancelled event at the same site, where two windows
    conflict exactly when the new start falls before the existing end **and** the
    existing start falls before the new end."

    Design: Difficulty/resource_temporal_overlap/screening_event_windows_overlap_per_site_half_open_with_no_buffer
    """
    first_site = fx.register_site(api)
    second_site = fx.register_site(api)
    fx.create_screening_event(
        api,
        first_site["id"],
        window_start_utc=ts("2026-08-20T09:00:00Z"),
        window_end_utc=ts("2026-08-20T12:00:00Z"),
        slot_capacity=4,
        slot_length_minutes=30,
    )
    validate_error(
        api.create_screening_event(
            f.screening_event_payload(
                first_site["id"],
                window_start_utc=ts("2026-08-20T11:00:00Z"),
                window_end_utc=ts("2026-08-20T13:00:00Z"),
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_SITE_EVENT_OVERLAP.value,
    )

    elsewhere = validate_success(
        api.create_screening_event(
            f.screening_event_payload(
                second_site["id"],
                window_start_utc=ts("2026-08-20T11:00:00Z"),
                window_end_utc=ts("2026-08-20T13:00:00Z"),
            ),
            COORDINATOR,
        ),
        201,
    )
    assert elsewhere["site_id"] == second_site["id"]

    first_rows, first_meta = _events_for_site(api, first_site["id"])
    assert first_meta["total_count"] == 1, f"the first site keeps one event: {first_rows}"
    second_rows, second_meta = _events_for_site(api, second_site["id"])
    assert second_meta["total_count"] == 1, f"the second site holds its own: {second_rows}"


def test_a_cancelled_event_releases_its_window_for_reuse(api):
    """Cancelled events are ignored entirely, so their window becomes bookable again.

    PRD §3.2: "No buffer is applied, so exact adjacency — a new event starting at the
    precise instant an existing one ends — is permitted, and cancelled events are
    ignored entirely. A conflict is `ERR_SITE_EVENT_OVERLAP`."

    PRD §3.2: "Cancellation is reachable from `SCHEDULED`, from `OPEN` and from
    `CLOSED`, in each case with no precondition beyond the from-state. Cancelling from
    `SCHEDULED` simply sets the event to `CANCELLED`."

    Design: Difficulty/resource_temporal_overlap/screening_event_windows_overlap_per_site_half_open_with_no_buffer
    """
    site = fx.register_site(api)
    doomed = fx.create_screening_event(
        api,
        site["id"],
        window_start_utc=ts("2026-08-20T09:00:00Z"),
        window_end_utc=ts("2026-08-20T12:00:00Z"),
        slot_capacity=4,
        slot_length_minutes=30,
    )
    validate_error(
        api.create_screening_event(
            f.screening_event_payload(
                site["id"],
                window_start_utc=ts("2026-08-20T10:00:00Z"),
                window_end_utc=ts("2026-08-20T11:00:00Z"),
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_SITE_EVENT_OVERLAP.value,
    )

    cancelled = fx.advance_event(api, doomed["id"], "CANCELLED")
    assert cancelled["status"] == "CANCELLED"

    replacement = validate_success(
        api.create_screening_event(
            f.screening_event_payload(
                site["id"],
                window_start_utc=ts("2026-08-20T09:00:00Z"),
                window_end_utc=ts("2026-08-20T12:00:00Z"),
                slot_capacity=4,
                slot_length_minutes=30,
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_instant(
        replacement["window_start_utc"], ts("2026-08-20T09:00:00Z"), "event.window_start_utc"
    )
    assert replacement["id"] != doomed["id"]

    rows, meta = _events_for_site(api, site["id"])
    assert meta["total_count"] == 2, (
        f"the cancelled event stays on file beside its replacement: {rows}"
    )


# =====================================================================================
# Evaluator assessment windows carry a travel buffer only when locations differ
# =====================================================================================
def test_back_to_back_windows_at_the_district_centre_are_permitted(api):
    """Two assessments in the same building may abut with no gap at all.

    PRD §3.5: "An `assessment_site_id` may be supplied to say where the assessment
    takes place; leaving it absent means the district assessment centre."

    PRD §3.5: "A new assessment window conflicts with an existing `SCHEDULED` or
    `COMPLETED` assessment of the **same** evaluator when the new start falls before
    the existing end plus a buffer **and** the existing start falls before the new end
    plus the same buffer. That buffer is zero when both assessments are at the same
    location, so genuinely back-to-back appointments in one building are legal".

    PRD §3.5: "The first assessment scheduled on a case moves the case
    `PLANNED → IN_PROGRESS`."

    Design: Difficulty/resource_temporal_overlap/evaluator_assessment_windows_need_a_travel_buffer_only_across_sites
    """
    context = _case_with_district_centre_assessment(api)
    case_id = context["case"]["id"]
    assert_fields_absent(context["first"], "assessment_site_id")

    adjacent = validate_success(
        api.schedule_domain_assessment(
            case_id,
            f.domain_assessment_payload(
                context["evaluator"]["id"],
                domain="COGNITIVE",
                method="STANDARDIZED",
                window_start_utc=ts("2026-08-20T10:00:00Z"),
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_domain_assessment(adjacent, expected_version=1)
    assert_subset(
        adjacent,
        {
            "evaluation_case_id": case_id,
            "evaluator_provider_id": context["evaluator"]["id"],
            "domain": "COGNITIVE",
            "status": "SCHEDULED",
        },
    )
    assert_fields_absent(adjacent, "assessment_site_id")
    assert_instant(
        adjacent["window_start_utc"], ts("2026-08-20T10:00:00Z"), "assessment.window_start_utc"
    )
    assert fx.read_case(api, case_id)["status"] == "IN_PROGRESS"

    rows, meta = validate_paginated(
        api.list_domain_assessments(
            COORDINATOR, {"evaluator_provider_id": context["evaluator"]["id"]}
        )
    )
    assert meta["total_count"] == 2, f"both windows belong to one evaluator: {rows}"


def test_a_window_at_another_site_inside_the_travel_buffer_is_refused(api):
    """The identical adjacency becomes a conflict once the locations differ.

    PRD §3.5: "That buffer is zero when both assessments are at the same location, so
    genuinely back-to-back appointments in one building are legal; it is 30 minutes
    whenever the two are at different locations, where an absent `assessment_site_id`
    normalises to the district assessment centre for the purposes of that comparison. A
    conflict is refused with `ERR_EVALUATOR_WINDOW_CONFLICT`, and `INVALIDATED`
    assessments are ignored entirely by the comparison."

    Design: Difficulty/resource_temporal_overlap/evaluator_assessment_windows_need_a_travel_buffer_only_across_sites
    """
    context = _case_with_district_centre_assessment(api)
    case_id = context["case"]["id"]

    response = api.schedule_domain_assessment(
        case_id,
        f.domain_assessment_payload(
            context["evaluator"]["id"],
            domain="COGNITIVE",
            method="STANDARDIZED",
            window_start_utc=ts("2026-08-20T10:00:00Z"),
            assessment_site_id=context["site"]["id"],
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_EVALUATOR_WINDOW_CONFLICT.value)

    rows, meta = validate_paginated(
        api.list_domain_assessments(COORDINATOR, {"evaluation_case_id": case_id})
    )
    assert meta["total_count"] == 1, f"the refused window must not be written: {rows}"
    assert rows[0]["id"] == context["first"]["id"]


def test_a_window_at_another_site_exactly_a_buffer_later_is_permitted(api):
    """Thirty minutes of travel time is enough, and the boundary itself does not conflict.

    PRD §3.5: "A new assessment window conflicts with an existing `SCHEDULED` or
    `COMPLETED` assessment of the **same** evaluator when the new start falls before
    the existing end plus a buffer **and** the existing start falls before the new end
    plus the same buffer.", and "it is 30 minutes whenever the two are at different
    locations, where an absent `assessment_site_id` normalises to the district
    assessment centre for the purposes of that comparison."

    Design: Difficulty/resource_temporal_overlap/evaluator_assessment_windows_need_a_travel_buffer_only_across_sites
    """
    context = _case_with_district_centre_assessment(api)
    case_id = context["case"]["id"]
    evaluator_id = context["evaluator"]["id"]
    site_id = context["site"]["id"]

    validate_error(
        api.schedule_domain_assessment(
            case_id,
            f.domain_assessment_payload(
                evaluator_id,
                domain="COGNITIVE",
                method="STANDARDIZED",
                window_start_utc=ts("2026-08-20T10:00:00Z"),
                assessment_site_id=site_id,
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_EVALUATOR_WINDOW_CONFLICT.value,
    )

    across_town = validate_success(
        api.schedule_domain_assessment(
            case_id,
            f.domain_assessment_payload(
                evaluator_id,
                domain="COGNITIVE",
                method="STANDARDIZED",
                window_start_utc=ts("2026-08-20T10:30:00Z"),
                assessment_site_id=site_id,
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_subset(
        across_town,
        {
            "domain": "COGNITIVE",
            "status": "SCHEDULED",
            "assessment_site_id": site_id,
            "version": 1,
        },
    )
    assert_instant(
        across_town["window_start_utc"],
        ts("2026-08-20T10:30:00Z"),
        "assessment.window_start_utc",
    )

    rows, meta = validate_paginated(
        api.list_domain_assessments(COORDINATOR, {"evaluation_case_id": case_id})
    )
    assert meta["total_count"] == 2, (
        f"only the district-centre window and the accepted one exist: {rows}"
    )
