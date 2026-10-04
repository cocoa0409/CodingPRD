"""Book fairs: the clock-driven lifecycle, half-open window semantics,
published-cycle slot capacity, and the derived active_fair_id.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    add_offering,
    create_book_fair,
    create_cycle,
    create_school,
    create_teacher,
    create_title,
    enroll_school,
    publish_cycle,
    read_school,
    set_clock,
    TEST_USERS,
)

CLUB_ADMIN = TEST_USERS["club_admin_headers"]
SCHOOL_ADMIN = TEST_USERS["school_admin_headers"]


def _school(api, name, enroll=True):
    school = create_school(api, name=name, low_income_program=False)
    if enroll:
        enroll_school(api, school["id"])
    return school


def test_fair_activates_and_completes_as_the_clock_crosses_its_window(api):
    """The fair lifecycle and active_fair_id are clock-driven.

    PRD: "Advancing the clock fires every scheduled transition whose boundary
    was crossed: book fairs move from `SCHEDULED` to `ACTIVE` when the clock
    date enters the fair's `[start_date, end_date)` window and from `ACTIVE` to
    `COMPLETED` when the clock date reaches or passes `end_date`; promotions
    move from `ACTIVE` to `EXPIRED` once the clock date is on or after the
    promotion's `ends_on`; and each school's `active_fair_id` is recomputed."
    PRD: "A fair begins `SCHEDULED`, turns `ACTIVE` when the logical clock
    enters its window, and `COMPLETED` when the clock reaches or passes
    `end_date`; both transitions are fired by clock advancement, and each
    recomputes the hosting school's `active_fair_id` — the id of the fair whose
    window contains today's clock date, or null when none — with completion
    clearing or reassigning it to another overlapping fair."

    Design: Difficulty/non_linear_state_machine/book_fair_clock_driven_scheduled_active_completed_cycle
    """
    school = _school(api, "Fair Clock School")
    fair = create_book_fair(api, school["id"], start_date="2026-10-05", end_date="2026-10-09")
    assert fair["status"] == "SCHEDULED"

    # Default clock 2026-09-01: the window has not started.
    assert read_school(api, school["id"])["active_fair_id"] is None

    set_clock(api, "2026-10-06T00:00:00Z")
    mid = validate_success(api.get_book_fair(fair["id"], SCHOOL_ADMIN))
    assert mid["status"] == "ACTIVE"
    assert read_school(api, school["id"])["active_fair_id"] == fair["id"]

    set_clock(api, "2026-10-09T00:00:00Z")
    done = validate_success(api.get_book_fair(fair["id"], SCHOOL_ADMIN))
    assert done["status"] == "COMPLETED", "end_date is exclusive — the fair completes at 10-09"
    assert read_school(api, school["id"])["active_fair_id"] is None


def test_active_fair_id_tracks_the_inclusive_start_of_the_window(api):
    """active_fair_id is set at start_date and cleared at end_date.

    PRD: "both transitions are fired by clock advancement, and each recomputes
    the hosting school's `active_fair_id` — the id of the fair whose window
    contains today's clock date, or null when none — with completion clearing
    or reassigning it to another overlapping fair."
    PRD: "A fair begins `SCHEDULED`, turns `ACTIVE` when the logical clock
    enters its window, and `COMPLETED` when the clock reaches or passes
    `end_date`..."

    Design: Difficulty/non_linear_state_machine/book_fair_clock_driven_scheduled_active_completed_cycle
    """
    school = _school(api, "Active Window School")
    fair = create_book_fair(api, school["id"], start_date="2026-10-05", end_date="2026-10-09")

    set_clock(api, "2026-10-04T23:59:59Z")
    assert read_school(api, school["id"])["active_fair_id"] is None, (
        "the day before start_date is outside the window"
    )

    set_clock(api, "2026-10-05T00:00:00Z")
    assert read_school(api, school["id"])["active_fair_id"] == fair["id"], (
        "start_date is inclusive"
    )

    set_clock(api, "2026-10-09T00:00:00Z")
    assert read_school(api, school["id"])["active_fair_id"] is None, (
        "end_date is exclusive"
    )


def test_half_open_adjacency_allowed_but_interior_overlap_rejected(api):
    """A fair starting exactly when another ends is allowed; overlap is not.

    PRD: "One school may never hold two fairs whose `[start_date, end_date)`
    windows intersect; the windows are half-open, so adjacency — one fair's
    `start_date` equal to another's `end_date` — is allowed, but any true
    intersection is rejected with `ERR_FAIR_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/book_fair_half_open_adjacency_allowed_intersection_rejected
    """
    school = _school(api, "Adjacency School")
    first = create_book_fair(api, school["id"], start_date="2026-10-05", end_date="2026-10-09")

    overlapping = api.create_book_fair(
        {"school_id": school["id"], "start_date": "2026-10-08", "end_date": "2026-10-12"},
        SCHOOL_ADMIN,
    )
    validate_error(overlapping, "ERR_FAIR_OVERLAP", 409)

    adjacent = validate_success(
        api.create_book_fair(
            {"school_id": school["id"], "start_date": "2026-10-09", "end_date": "2026-10-16"},
            SCHOOL_ADMIN,
        ),
        201,
    )
    assert adjacent["status"] == "SCHEDULED"


def test_half_open_adjacency_works_in_both_directions(api):
    """A fair ending exactly when another starts is equally allowed.

    PRD: "the windows are half-open, so adjacency — one fair's `start_date`
    equal to another's `end_date` — is allowed, but any true intersection is
    rejected with `ERR_FAIR_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/book_fair_half_open_adjacency_allowed_intersection_rejected
    """
    school = _school(api, "Reverse Adjacency School")
    create_book_fair(api, school["id"], start_date="2026-10-05", end_date="2026-10-09")

    before = validate_success(
        api.create_book_fair(
            {"school_id": school["id"], "start_date": "2026-10-01", "end_date": "2026-10-05"},
            SCHOOL_ADMIN,
        ),
        201,
    )
    assert before["status"] == "SCHEDULED", "a fair ending at another's start_date is adjacent"

    overlapping = api.create_book_fair(
        {"school_id": school["id"], "start_date": "2026-10-04", "end_date": "2026-10-06"},
        SCHOOL_ADMIN,
    )
    validate_error(overlapping, "ERR_FAIR_OVERLAP", 409)


def test_only_one_published_cycle_per_school_and_band_until_closed(api):
    """The published-cycle slot is month-independent and freed on close.

    PRD: "no other flyer cycle for the same school and grade band may currently
    be `PUBLISHED`; publishing a second is rejected with
    `ERR_CYCLE_ALREADY_PUBLISHED` (HTTP 409)."
    PRD: "At most one `PUBLISHED` cycle exists per school per band at any
    moment."

    Design: Difficulty/resource_temporal_overlap/published_cycle_uniqueness_per_school_band_months_may_repeat
    """
    school = _school(api, "Cycle Slot School")
    title = create_title(api, name="Slot Title", base_price_cents=1000, points_cost=10)

    cycle_oct = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    add_offering(api, cycle_oct["id"], title["id"])
    cycle_nov = create_cycle(api, school["id"], month="2026-11", grade_band="G3_5")
    add_offering(api, cycle_nov["id"], title["id"])

    publish_cycle(api, cycle_oct["id"])
    rejected = api.publish_cycle(cycle_nov["id"], CLUB_ADMIN)
    validate_error(rejected, "ERR_CYCLE_ALREADY_PUBLISHED", 409)

    validate_success(api.close_cycle(cycle_oct["id"], CLUB_ADMIN))
    published = validate_success(api.publish_cycle(cycle_nov["id"], CLUB_ADMIN))
    assert published["status"] == "PUBLISHED", "closing the first cycle frees the slot"


def test_different_band_cycles_publish_independently(api):
    """The slot is per school AND band: another band may publish alongside.

    PRD: "no other flyer cycle for the same school and grade band may currently
    be `PUBLISHED`; publishing a second is rejected with
    `ERR_CYCLE_ALREADY_PUBLISHED` (HTTP 409)."
    PRD: "At most one `PUBLISHED` cycle exists per school per band at any
    moment."

    Design: Difficulty/resource_temporal_overlap/published_cycle_uniqueness_per_school_band_months_may_repeat
    """
    school = _school(api, "Two Band School")
    title_35 = create_title(api, name="G3_5 Title", base_price_cents=1000, points_cost=10,
                            grade_band="G3_5")
    title_k2 = create_title(api, name="K_2 Title", base_price_cents=800, points_cost=8,
                            grade_band="K_2")

    cycle_a = create_cycle(api, school["id"], month="2026-10", grade_band="G3_5")
    add_offering(api, cycle_a["id"], title_35["id"])
    cycle_b = create_cycle(api, school["id"], month="2026-10", grade_band="K_2")
    add_offering(api, cycle_b["id"], title_k2["id"])

    publish_cycle(api, cycle_a["id"])
    published_b = validate_success(api.publish_cycle(cycle_b["id"], CLUB_ADMIN))
    assert published_b["status"] == "PUBLISHED", "a different band holds its own slot"


def test_active_fair_id_is_null_before_start_and_set_inside_window(api):
    """The derived field tracks the logical clock, never the wall clock.

    PRD: "A school is `NORMAL` when it has a program enrollment in `ACTIVE`
    status — or when no enrollment has ever been created for it at all — ..."
    PRD: "both transitions are fired by clock advancement, and each recomputes
    the hosting school's `active_fair_id` — the id of the fair whose window
    contains today's clock date, or null when none — with completion clearing
    or reassigning it to another overlapping fair."
    PRD: "At server startup, before any clock-setting call, the logical clock
    is exactly `2026-09-01T00:00:00Z`; the server never falls back to the wall
    clock."

    Design: Corner/cross_cutting_layers/active_fair_recompute_derived_field
    """
    school = _school(api, "Derived Fair School")
    fair = create_book_fair(api, school["id"], start_date="2026-10-05", end_date="2026-10-09")

    before = read_school(api, school["id"])
    assert before["active_fair_id"] is None, (
        "at the startup clock 2026-09-01 the October fair has not begun"
    )

    set_clock(api, "2026-10-05T00:00:00Z")
    during = read_school(api, school["id"])
    assert during["active_fair_id"] == fair["id"], "the inclusive start activates the fair"
