"""SCAFFOLD §1.8 rule_id resource_temporal_overlap: two window geometries over one resource."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures  # noqa: E402
from test_helpers.api_errors import *  # noqa: F401,F403,E402
from test_helpers.test_users import make_review_coordinator_headers  # noqa: E402

EXISTING_START = "2026-08-20T09:00:00Z"
EXISTING_END = "2026-08-22T17:00:00Z"
BUFFERED_END = "2026-08-24T17:00:00Z"


def _accepted_cycle(api, code, name, department_code, **program_overrides):
    """Register a program and carry its cycle to SELF_STUDY_ACCEPTED."""
    program = fixtures.create_program(
        api,
        code=code,
        name=name,
        degree_level="UNDERGRADUATE",
        department_code=department_code,
        **program_overrides,
    )
    cycle = fixtures.open_cycle(
        api,
        program["id"],
        cycle_year=2026,
        self_study_due_at="2026-09-01T00:00:00Z",
        required_section_codes=["S1"],
    )
    self_study = fixtures.create_self_study(
        api,
        cycle["id"],
        program["id"],
        narrative=f"{name} self-study",
        section_codes=["S1"],
    )
    fixtures.accept_self_study(api, self_study["id"], program["id"])
    return program, fixtures.read_cycle(api, cycle["id"])


def test_reviewer_window_overlap_uses_travel_buffer_on_both_sides(api):
    """A request two clear days after the raw window still collides with the buffer.

    §3.4's check 22 extends every existing SCHEDULED or COMPLETED window of the
    *same reviewer* by travel_buffer_hours on both sides before testing overlap,
    so a visit over [2026-08-20T09:00Z, 2026-08-22T17:00Z) with a 48 hour buffer
    occupies [2026-08-18T09:00Z, 2026-08-24T17:00Z). A request starting at
    2026-08-24T16:00Z therefore conflicts even though it begins almost two days
    after the raw window_end_at. Sliding the same request one hour later, so that
    it starts exactly on the buffered boundary, is accepted, because the windows
    are half-open and touching windows do not overlap. Nothing but the buffer and
    the half-open geometry separates the two outcomes.

    Design: Difficulty/resource_temporal_overlap/reviewer_window_overlap_uses_travel_buffer_on_both_sides
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    reviewer = fixtures.register_reviewer(
        api,
        full_name="Dr Alice Reyes",
        institution="Northfield University",
        specialty_code="HUM",
        travel_buffer_hours=48,
    )
    reviewer_id = reviewer["id"]
    assert reviewer["travel_buffer_hours"] == 48

    # Three separate programs, so the per-program capacity aggregate of check 23
    # can never fire: no program hosts more than one visit.
    _history, history_cycle = _accepted_cycle(api, "HIST-BA", "History BA", "HIST")
    _philosophy, philosophy_cycle = _accepted_cycle(
        api, "PHIL-BA", "Philosophy BA", "PHIL"
    )
    _classics, classics_cycle = _accepted_cycle(api, "CLAS-BA", "Classics BA", "CLAS")

    existing = fixtures.schedule_visit(
        api,
        history_cycle["id"],
        reviewer_id,
        window_start_at=EXISTING_START,
        window_end_at=EXISTING_END,
    )
    assert existing["state"] == "SCHEDULED"

    # Trigger part 1: outside the raw window, inside the buffered one.
    refused = api.create_reviewer_visit(
        factories.reviewer_visit_payload(
            philosophy_cycle["id"],
            reviewer_id,
            window_start_at="2026-08-24T16:00:00Z",
            window_end_at="2026-08-25T16:00:00Z",
        ),
        coordinator,
    )
    validate_error(refused, ERR_REVIEWER_WINDOW_CONFLICT, 409)

    assert fixtures.read_cycle(api, philosophy_cycle["id"])["state"] == (
        "SELF_STUDY_ACCEPTED"
    )
    _rows, meta = validate_paginated(
        api.list_reviewer_visits(coordinator, params={"cycle_id": philosophy_cycle["id"]})
    )
    assert meta["total_count"] == 0, "the refused booking created nothing"

    # Trigger part 2: one hour later, exactly on the buffered boundary.
    accepted = validate_success(
        api.create_reviewer_visit(
            factories.reviewer_visit_payload(
                classics_cycle["id"],
                reviewer_id,
                window_start_at=BUFFERED_END,
                window_end_at="2026-08-26T17:00:00Z",
            ),
            coordinator,
        ),
        201,
    )
    assert accepted["state"] == "SCHEDULED"
    assertions.assert_iso_date(accepted["span_start_date"], "span_start_date")
    assert accepted["span_start_date"] == "2026-08-24"
    assert accepted["span_end_date"] == "2026-08-26"

    assert fixtures.read_cycle(api, classics_cycle["id"])["state"] == "VISIT_SCHEDULED"
    assert fixtures.read_cycle(api, philosophy_cycle["id"])["state"] == (
        "SELF_STUDY_ACCEPTED"
    )

    # The reviewer holds exactly the two accepted bookings.
    _rows, meta = validate_paginated(
        api.list_reviewer_visits(coordinator, params={"reviewer_id": reviewer_id})
    )
    assert meta["total_count"] == 2, "the refused attempt booked nothing"

    # The incumbent visit is untouched by either attempt.
    incumbent = validate_success(api.get_reviewer_visit(existing["id"], coordinator))
    assert incumbent["state"] == "SCHEDULED"
    assertions.assert_instant_equals(
        incumbent["window_start_at"], EXISTING_START, "window_start_at"
    )
    assertions.assert_instant_equals(
        incumbent["window_end_at"], EXISTING_END, "window_end_at"
    )


def test_host_capacity_counts_inclusive_calendar_days_not_instants(api):
    """The capacity aggregate counts inclusive calendar days, not instant overlap.

    §3.4's check 23 works on a geometry check 22 never uses: each visit occupies
    every UTC calendar day from span_start_date through span_end_date inclusive,
    with no buffer. Four distinct reviewers keep the per-reviewer rule out of the
    way. Days 2026-08-20 and 2026-08-21 each already carry two visits on a
    program whose host_capacity_per_day is 2, and the fourth request straddles
    midnight, so it occupies both saturated days — even though its instant window
    [22:00, 06:00) does not intersect the first visit's [09:00, 17:00) at all.
    ERR_PROGRAM_HOST_CAPACITY_EXCEEDED is the only fault available.

    Design: Difficulty/resource_temporal_overlap/host_capacity_counts_inclusive_calendar_days_not_instants
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program, cycle = _accepted_cycle(
        api, "HIST-BA", "History BA", "HIST", host_capacity_per_day=2
    )
    assert program["host_capacity_per_day"] == 2
    cycle_id = cycle["id"]

    reviewers = [
        fixtures.register_reviewer(
            api,
            full_name=full_name,
            institution=institution,
            specialty_code="HIST",
            travel_buffer_hours=0,
        )
        for full_name, institution in (
            ("Dr Alice Reyes", "Northfield University"),
            ("Dr Bruno Sato", "Lakeside Institute"),
            ("Dr Carla Owusu", "Riverbend College"),
            ("Dr Dmitri Vane", "Highmoor University"),
        )
    ]
    first, second, third, fourth = reviewers

    # Day 20 only.
    visit_one = fixtures.schedule_visit(
        api,
        cycle_id,
        first["id"],
        window_start_at="2026-08-20T09:00:00Z",
        window_end_at="2026-08-20T17:00:00Z",
    )
    # Days 20 and 21: this one straddles midnight.
    visit_two = fixtures.schedule_visit(
        api,
        cycle_id,
        second["id"],
        window_start_at="2026-08-20T13:00:00Z",
        window_end_at="2026-08-21T01:00:00Z",
    )
    # Day 21 only.
    visit_three = fixtures.schedule_visit(
        api,
        cycle_id,
        third["id"],
        window_start_at="2026-08-21T09:00:00Z",
        window_end_at="2026-08-21T17:00:00Z",
    )

    assert visit_one["span_start_date"] == "2026-08-20"
    assert visit_one["span_end_date"] == "2026-08-20"
    assert visit_two["span_start_date"] == "2026-08-20"
    assert visit_two["span_end_date"] == "2026-08-21"
    assert visit_three["span_start_date"] == "2026-08-21"
    assert visit_three["span_end_date"] == "2026-08-21"

    # Trigger: a window that shares no instant with visit one, but both of its
    # saturated calendar days.
    refused = api.create_reviewer_visit(
        factories.reviewer_visit_payload(
            cycle_id,
            fourth["id"],
            window_start_at="2026-08-20T22:00:00Z",
            window_end_at="2026-08-21T06:00:00Z",
        ),
        coordinator,
    )
    error = validate_error(refused, ERR_PROGRAM_HOST_CAPACITY_EXCEEDED, 409)
    assert error["error_id"] != ERR_REVIEWER_WINDOW_CONFLICT, (
        "the fourth reviewer holds no other visit anywhere, so check 22 is inert"
    )

    rows, meta = validate_paginated(
        api.list_reviewer_visits(coordinator, params={"cycle_id": cycle_id})
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3
    assert {row["state"] for row in rows} == {"SCHEDULED"}
    assert {row["id"] for row in rows} == {
        visit_one["id"],
        visit_two["id"],
        visit_three["id"],
    }

    _rows, meta = validate_paginated(
        api.list_reviewer_visits(coordinator, params={"reviewer_id": fourth["id"]})
    )
    assert meta["total_count"] == 0

    # The three accepted bookings used the team self-loop on the cycle.
    assert fixtures.read_cycle(api, cycle_id)["state"] == "VISIT_SCHEDULED"
    assert fixtures.read_program(api, program["id"])["host_capacity_per_day"] == 2
