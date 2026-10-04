"""Community events: seating, travel awards, cancellation, waitlist promotion."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    validate_error, validate_success,
)
from test_helpers import factories, fixtures

EVENT = TEST_USERS["event_coordinator_headers"]


def test_event_cancel_waitlist_promotion_cascade(api):
    """PRD section 3.7: "Cancelling a `CONFIRMED` registration decrements
    `registered_count` by 1, decrements `accessibility_seats_used` by 1 when the
    registration had accommodation needs, and returns its `travel_award_cents` to
    `travel_budget_remaining_cents`."
    PRD section 3.7: "takes the one with the smallest `queue_position`, and
    promotes exactly that one to `CONFIRMED`, recomputing its
    `travel_award_cents` under the same minimum-of-three rule and debiting the
    budget; if no waitlisted row fits, nothing happens."

    Design: Difficulty/transitive_cascade/event_cancel_waitlist_promotion_cascade
    """
    fixtures.reset_clock()
    event = fixtures.create_community_event(
        name="Caregiver Summit", starts_at="2026-10-15T10:00:00Z",
        ends_at="2026-10-15T12:00:00Z", capacity=1, accessibility_seat_count=0,
        travel_budget_cents=100000)
    m1 = fixtures.create_member(full_name="Reg One")
    m2 = fixtures.create_member(full_name="Reg Two", branch_of_service="NAVY")
    m3 = fixtures.create_member(full_name="Reg Three", member_type="FAMILY_SUPPORT")

    r1 = validate_success(api.create_event_registration(
        factories.create_event_registration_payload(m1["id"], event["id"], travel_request_cents=20000),
        EVENT), 201)
    assert r1["status"] == "CONFIRMED"
    assert r1["travel_award_cents"] == 20000
    r2 = validate_success(api.create_event_registration(
        factories.create_event_registration_payload(m2["id"], event["id"], travel_request_cents=40000),
        EVENT), 201)
    assert r2["status"] == "WAITLISTED", "capacity 1 was full"
    r3 = validate_success(api.create_event_registration(
        factories.create_event_registration_payload(m3["id"], event["id"], travel_request_cents=10000),
        EVENT), 201)
    assert r3["status"] == "WAITLISTED"

    cancelled = fixtures.transition_event_registration(r1["id"], "CANCEL")
    assert cancelled["status"] == "CANCELLED"

    r2_after = fixtures.get_event_registration(r2["id"])
    assert r2_after["status"] == "CONFIRMED"
    assert r2_after["travel_award_cents"] == 40000, "min(40000, 50000 cap, 100000 remaining)"

    r3_after = fixtures.get_event_registration(r3["id"])
    assert r3_after["status"] == "WAITLISTED"
    assert r3_after["travel_award_cents"] == 0

    event_after = fixtures.get_community_event(event["id"])
    assert event_after["travel_budget_remaining_cents"] == 60000
    assert event_after["registered_count"] == 1


def test_event_schedule_half_open_adjacency(api):
    """PRD section 3.7: "The two conflict when the new event starts before the
    existing one ends and the existing one starts before the new one ends; an
    event starting exactly when another ends does **not** conflict. Any conflict
    rejects the registration with `ERR_EVENT_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/event_schedule_half_open_adjacency
    """
    fixtures.reset_clock()
    e1 = fixtures.create_community_event(
        name="E1 Morning", starts_at="2026-10-15T10:00:00Z",
        ends_at="2026-10-15T12:00:00Z", capacity=5)
    e2 = fixtures.create_community_event(
        name="E2 Afternoon", starts_at="2026-10-15T12:00:00Z",
        ends_at="2026-10-15T14:00:00Z", capacity=5)
    e3 = fixtures.create_community_event(
        name="E3 Overlapper", starts_at="2026-10-15T11:59:59Z",
        ends_at="2026-10-15T13:00:00Z", capacity=5)
    member = fixtures.create_member(full_name="Busy Member")

    r1 = validate_success(api.create_event_registration(
        factories.create_event_registration_payload(member["id"], e1["id"]), EVENT), 201)
    assert r1["status"] == "CONFIRMED"
    r2 = validate_success(api.create_event_registration(
        factories.create_event_registration_payload(member["id"], e2["id"]), EVENT), 201)
    assert r2["status"] == "CONFIRMED", "E2 starts exactly at E1's ends_at; half-open admits adjacency"

    err_resp = api.create_event_registration(
        factories.create_event_registration_payload(member["id"], e3["id"]), EVENT)
    validate_error(err_resp, ApiErrorId.ERR_EVENT_SCHEDULE_CONFLICT)

    assert len(fixtures.list_event_registrations(member_id=member["id"])) == 2


def test_travel_budget_award_cancel_conservation(api):
    """PRD section 3.7: "`travel_award_cents` is the smallest of the
    registration's `travel_request_cents`, a per-registration cap of 50000 cents
    ($500.00), and the event's `travel_budget_remaining_cents`; the granted
    amount is debited from `travel_budget_remaining_cents`."
    PRD section 3.7: "Cancelling a `CONFIRMED` registration decrements
    `registered_count` by 1, decrements `accessibility_seats_used` by 1 when the
    registration had accommodation needs, and returns its `travel_award_cents` to
    `travel_budget_remaining_cents`."

    Design: Difficulty/compensating_invariant/travel_budget_award_cancel_conservation
    """
    fixtures.reset_clock()
    event = fixtures.create_community_event(
        name="Awards Gala", starts_at="2026-10-20T09:00:00Z",
        ends_at="2026-10-20T11:00:00Z", capacity=10, travel_budget_cents=120000)
    m1 = fixtures.create_member(full_name="Gala One")
    m2 = fixtures.create_member(full_name="Gala Two", branch_of_service="NAVY")

    r1 = validate_success(api.create_event_registration(
        factories.create_event_registration_payload(m1["id"], event["id"], travel_request_cents=80000),
        EVENT), 201)
    assert r1["travel_award_cents"] == 50000, "the per-registration cap binds below the 80000 request"
    r2 = validate_success(api.create_event_registration(
        factories.create_event_registration_payload(m2["id"], event["id"], travel_request_cents=30000),
        EVENT), 201)
    assert r2["travel_award_cents"] == 30000

    event_mid = fixtures.get_community_event(event["id"])
    assert event_mid["travel_budget_remaining_cents"] == 40000
    assert event_mid["travel_budget_remaining_cents"] + 50000 + 30000 == 120000

    fixtures.transition_event_registration(r1["id"], "CANCEL")
    event_after = fixtures.get_community_event(event["id"])
    assert event_after["travel_budget_remaining_cents"] == 90000
    assert event_after["travel_budget_remaining_cents"] + 30000 == 120000, "conservation holds"
    assert fixtures.get_event_registration(r2["id"])["travel_award_cents"] == 30000, (
        "the cancel of r1 did not disturb r2")


def test_registration_second_cancel_rejected(api):
    """PRD section 3.7: "Requesting a cancellation from any state other than
    `CONFIRMED` or `WAITLISTED` is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/registration_second_cancel_rejected
    """
    fixtures.reset_clock()
    event = fixtures.create_community_event(
        name="Cancel Twice 5K", starts_at="2026-10-20T09:00:00Z",
        ends_at="2026-10-20T11:00:00Z", capacity=5, travel_budget_cents=50000)
    member = fixtures.create_member(full_name="Cancel Member")
    registration = fixtures.create_event_registration(
        member["id"], event["id"], travel_request_cents=20000)
    fixtures.transition_event_registration(registration["id"], "CANCEL")

    err_resp = api.transition_event_registration(
        registration["id"], factories.registration_transition_payload("CANCEL"), EVENT)
    validate_error(err_resp, ApiErrorId.ERR_INVALID_STATE)

    event_after = fixtures.get_community_event(event["id"])
    assert event_after["travel_budget_remaining_cents"] == 50000, "refunded exactly once"
    assert fixtures.get_event_registration(registration["id"])["status"] == "CANCELLED"


def test_travel_award_capped_by_remaining_budget(api):
    """PRD section 3.7: "`travel_award_cents` is the smallest of the
    registration's `travel_request_cents`, a per-registration cap of 50000 cents
    ($500.00), and the event's `travel_budget_remaining_cents`; the granted
    amount is debited from `travel_budget_remaining_cents`."

    Design: Corner/calculations/travel_award_capped_by_remaining_budget
    """
    fixtures.reset_clock()
    event = fixtures.create_community_event(
        name="Small Budget Picnic", starts_at="2026-10-20T09:00:00Z",
        ends_at="2026-10-20T11:00:00Z", capacity=5, travel_budget_cents=20000)
    member = fixtures.create_member(full_name="Budget Member")

    registration = validate_success(api.create_event_registration(
        factories.create_event_registration_payload(member["id"], event["id"], travel_request_cents=30000),
        EVENT), 201)
    assert registration["travel_award_cents"] == 20000, "remaining budget binds below request and cap"
    assert fixtures.get_community_event(event["id"])["travel_budget_remaining_cents"] == 0


def test_attend_before_event_start_rejected(api):
    """PRD section 3.7: "marking before the event's `starts_at` — measured on
    the logical clock — is rejected with `ERR_EVENT_NOT_STARTED` (HTTP 422),
    while marking at or after the start moves the registration to `ATTENDED`."

    Design: Corner/validations/attend_before_event_start_rejected
    """
    fixtures.reset_clock()
    event = fixtures.create_community_event(
        name="Early Bird 5K", starts_at="2026-10-20T09:00:00Z",
        ends_at="2026-10-20T11:00:00Z", capacity=5)
    member = fixtures.create_member(full_name="Early Member")
    registration = fixtures.create_event_registration(member["id"], event["id"])
    assert registration["status"] == "CONFIRMED"

    fixtures.set_clock("2026-10-20T08:59:59Z")
    err_resp = api.transition_event_registration(
        registration["id"], factories.registration_transition_payload("ATTEND"), EVENT)
    validate_error(err_resp, ApiErrorId.ERR_EVENT_NOT_STARTED)
    assert fixtures.get_event_registration(registration["id"])["status"] == "CONFIRMED"


def test_registration_create_returns_computed_fields_immediately(api):
    """PRD section 2.2: "Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in the
    data field."
    PRD section 3.7: "A confirmation increments `registered_count` by 1,
    increments `accessibility_seats_used` by 1 when the registration carries
    accommodation needs, and immediately grants a **travel award**:
    `travel_award_cents` is the smallest of the registration's
    `travel_request_cents`, a per-registration cap of 50000 cents ($500.00), and
    the event's `travel_budget_remaining_cents`"

    Design: Corner/consistency_model/registration_create_returns_computed_fields_immediately
    """
    fixtures.reset_clock()
    event = fixtures.create_community_event(
        name="Immediate Gala", starts_at="2026-10-20T09:00:00Z",
        ends_at="2026-10-20T11:00:00Z", capacity=5, travel_budget_cents=100000)
    member = fixtures.create_member(full_name="Immediate Member")

    registration = validate_success(api.create_event_registration(
        factories.create_event_registration_payload(member["id"], event["id"], travel_request_cents=25000),
        EVENT), 201)
    assert registration["status"] == "CONFIRMED"
    assert registration["travel_award_cents"] == 25000

    reread = fixtures.get_event_registration(registration["id"])
    assert reread["status"] == "CONFIRMED"
    assert reread["travel_award_cents"] == 25000
    assert fixtures.get_community_event(event["id"])["travel_budget_remaining_cents"] == 75000


def test_registration_create_unknown_event_returns_event_not_found(api):
    """PRD section 2.9: "Request-body foreign keys are likewise resolved in the
    order the endpoint's input list declares them."
    PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/entities/registration_create_unknown_event_returns_event_not_found
    """
    fixtures.reset_clock()
    member = fixtures.create_member(full_name="Event FK Member")
    resp = api.create_event_registration(
        factories.create_event_registration_payload(member["id"], NON_EXISTENT_UUID), EVENT)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND)


def test_registration_transition_unknown_id_returns_registration_not_found(api):
    """PRD section 2.7: "A missing reference yields the matching 404 identifier"

    Design: Corner/entities/registration_transition_unknown_id_returns_registration_not_found
    """
    fixtures.reset_clock()
    resp = api.transition_event_registration(
        NON_EXISTENT_UUID, factories.registration_transition_payload("CANCEL"), EVENT)
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_FOUND)
