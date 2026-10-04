"""The two temporal guards, on different resources and with different interval shapes.

The bay guard is half-open, so a booking that ends exactly when another begins
is admitted. The pet guard is closed and buffered by fifteen minutes across
distinct bays, so touching buffered windows pass while a one-minute intrusion
does not. Both claims need the pair-side of the boundary built, not just the
rejected side.
"""

from test_helpers import (
    build_center,
    create_bay,
    create_booking,
    create_pet,
    validate_error,
)
from test_helpers import ApiErrorId
from test_helpers.test_users import TEST_USERS

GROOMER = TEST_USERS["grooming_staff_headers"]


def test_booking_starting_one_second_before_the_held_window_ends_is_refused(api):
    """An overlap of one second is a conflict; adjacency is not.

    PRD §2.11: "The bay guard treats a booking's window as a half-open interval
    running from `starts_at` up to but not including `ends_at`, and rejects any
    candidate window that overlaps an existing non-terminal booking on the same
    bay with `ERR_BAY_SLOT_CONFLICT`."
    PRD §2.11: "Because the interval is half-open and adjacency is permitted, a
    booking that ends exactly when another begins does not conflict, while an
    overlap of even one second does."

    Design: Difficulty/resource_temporal_overlap/bay_half_open_occupancy_rejects_one_second_overlap
    """
    world = build_center(api, pet=("Ash", "CANINE", "Whippet", 12.5))
    second = create_pet(api, world["member"]["id"], name="Fern", breed="Whippet", weight_kg=11.0)
    bay = create_bay(api, world["store"]["id"], "GROOMING")
    create_booking(
        api,
        world["store"]["id"],
        bay["id"],
        world["pet"]["id"],
        world["pet"]["version"],
        starts_at="2026-06-09T09:00:00Z",
        ends_at="2026-06-09T10:00:00Z",
    )

    from test_helpers import factories

    resp = api.create_booking(
        world["store"]["id"],
        factories.booking_payload(
            bay_id=bay["id"],
            pet_id=second["id"],
            service_type="GROOMING",
            starts_at="2026-06-09T09:59:59Z",
            ends_at="2026-06-09T11:00:00Z",
            expected_pet_version=second["version"],
        ),
        GROOMER,
    )
    validate_error(resp, ApiErrorId.BAY_SLOT_CONFLICT.value)


def test_booking_starting_exactly_when_the_held_window_ends_is_admitted(api):
    """Adjacency is permitted under the half-open comparison.

    PRD §2.11: "Because the interval is half-open and adjacency is permitted, a
    booking that ends exactly when another begins does not conflict, while an
    overlap of even one second does."
    PRD §2.11: "Terminal bookings — those in `COMPLETED`, `CANCELLED` or
    `NO_SHOW` — occupy nothing and are ignored."

    Design: Difficulty/resource_temporal_overlap/bay_half_open_occupancy_rejects_one_second_overlap
    """
    world = build_center(api, pet=("Ash", "CANINE", "Whippet", 12.5))
    second = create_pet(api, world["member"]["id"], name="Fern", breed="Whippet", weight_kg=11.0)
    bay = create_bay(api, world["store"]["id"], "GROOMING")
    create_booking(
        api,
        world["store"]["id"],
        bay["id"],
        world["pet"]["id"],
        world["pet"]["version"],
        starts_at="2026-06-09T09:00:00Z",
        ends_at="2026-06-09T10:00:00Z",
    )
    adjacent = create_booking(
        api,
        world["store"]["id"],
        bay["id"],
        second["id"],
        second["version"],
        starts_at="2026-06-09T10:00:00Z",
        ends_at="2026-06-09T11:00:00Z",
    )
    assert adjacent["starts_at"] == "2026-06-09T10:00:00Z"
    assert adjacent["status"] == "REQUESTED"


def test_pet_buffered_window_that_intrudes_by_one_minute_is_refused(api):
    """A fifteen-minute buffer on each end makes a 09:05 start collide.

    PRD §2.11: "A candidate window is buffered by 15 minutes at each end, and the
    guard rejects a booking whose buffered window overlaps the buffered window of
    any non-terminal booking held by the same pet in a different bay, with
    `ERR_PET_DOUBLE_BOOKED`."
    PRD §2.11: "The same-bay case is handled entirely by the bay guard, so the pet
    guard is restricted to distinct bays."
    PRD §2.11: "Touching buffered windows pass; a one-minute overlap fails."

    Design: Difficulty/resource_temporal_overlap/closed_buffered_interval_on_a_different_resource_entity
    """
    world = build_center(api, pet=("Cleo", "FELINE", "Bengal", 4.9))
    store_id = world["store"]["id"]
    pet = world["pet"]
    grooming = create_bay(api, store_id, "GROOMING")
    vaccination = create_bay(api, store_id, "VACCINATION")
    create_booking(
        api,
        store_id,
        grooming["id"],
        pet["id"],
        pet["version"],
        service_type="GROOMING",
        starts_at="2026-06-10T09:00:00Z",
        ends_at="2026-06-10T10:00:00Z",
    )

    from test_helpers import factories

    resp = api.create_booking(
        store_id,
        factories.booking_payload(
            bay_id=vaccination["id"],
            pet_id=pet["id"],
            service_type="VACCINATION",
            starts_at="2026-06-10T09:05:00Z",
            ends_at="2026-06-10T10:00:00Z",
            expected_pet_version=pet["version"],
        ),
        GROOMER,
    )
    validate_error(resp, ApiErrorId.PET_DOUBLE_BOOKED.value)


def test_pet_buffered_windows_that_touch_exactly_are_admitted(api):
    """A 10:15 start touches the held window's buffered end and is admitted.

    PRD §2.11: "Touching buffered windows pass; a one-minute overlap fails."
    PRD §2.11: "A candidate window is buffered by 15 minutes at each end"
    PRD §2.11: "The bay guard treats a booking's window as a half-open interval
    running from `starts_at` up to but not including `ends_at`, and rejects any
    candidate window that overlaps an existing non-terminal booking on the same
    bay with `ERR_BAY_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/closed_buffered_interval_on_a_different_resource_entity
    """
    world = build_center(api, pet=("Cleo", "FELINE", "Bengal", 4.9))
    store_id = world["store"]["id"]
    pet = world["pet"]
    grooming = create_bay(api, store_id, "GROOMING")
    vaccination = create_bay(api, store_id, "VACCINATION")
    create_booking(
        api,
        store_id,
        grooming["id"],
        pet["id"],
        pet["version"],
        service_type="GROOMING",
        starts_at="2026-06-10T09:00:00Z",
        ends_at="2026-06-10T10:00:00Z",
    )
    touching = create_booking(
        api,
        store_id,
        vaccination["id"],
        pet["id"],
        pet["version"],
        service_type="VACCINATION",
        starts_at="2026-06-10T10:15:00Z",
        ends_at="2026-06-10T10:30:00Z",
    )
    # The held booking's buffered window runs 08:45 to 10:15, so a candidate
    # starting exactly at 10:15 touches rather than overlaps.
    assert touching["starts_at"] == "2026-06-10T10:15:00Z"
    assert touching["status"] == "REQUESTED"