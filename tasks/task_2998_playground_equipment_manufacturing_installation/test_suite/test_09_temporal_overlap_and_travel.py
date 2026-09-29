"""Overlapping intervals in space and in time.

Two families of interval arithmetic live here, and they use different
conventions on purpose: a component's use zone is a closed centimetre interval
inside a half-open play-area interval, while an installer's booking window is a
closed interval of calendar days that must also leave a clear travel day behind
it.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    validate_error,
    validate_success,
)
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["design_consultant_headers"]
ADMIN = TEST_USERS["manufacturer_admin_headers"]

# The deck sits at 700 with a 183 cm half-extent, so its closed use zone is
# 517..883.  The climber sits at 900 with a 213 cm half-extent, so its closed
# use zone is 687..1113 and the two intervals meet between 687 and 883.
DECK_ANCHOR_CM = 700
DECK_ZONE_START_CM = 517
DECK_ZONE_END_CM = 883
CLIMBER_ANCHOR_CM = 900
CLIMBER_ZONE_START_CM = 687
CLIMBER_ZONE_END_CM = 1113


def _setup_validated_deck() -> dict:
    """One CONSULTATION project, one toddler area 0..2000, one VALIDATED deck."""
    scenario = fx.setup_project_with_toddler_area(
        project_overrides={"client_name": "Juniper Yard", "budget_cents": 900000}
    )
    scenario["deck_placement"] = fx.create_validated_placement(
        scenario["area"]["id"],
        scenario["deck"]["id"],
        color_choice="SKY_BLUE",
        x_start_cm=DECK_ANCHOR_CM,
        quantity=1,
    )
    return scenario


def _create_climber(scenario: dict, attached_to_placement_id: str | None = None) -> dict:
    """Anchor the climber at 900, optionally bolted to the deck placement."""
    payload = f.placement_payload(
        scenario["climber"]["id"],
        color_choice="CRIMSON",
        x_start_cm=CLIMBER_ANCHOR_CM,
        quantity=1,
    )
    if attached_to_placement_id is not None:
        payload["attached_to_placement_id"] = attached_to_placement_id
    response = api_client.create_placement(scenario["area"]["id"], payload, CONSULTANT)
    return validate_success(response, 201)


class TestUseZoneOverlapExemption:
    """A free-standing climber and a deck-bolted climber on identical geometry."""

    def test_free_standing_climber_overlapping_a_validated_deck_is_refused(self):
        """A climber whose closed zone meets the deck's cannot validate unattached.

        PRD: "two closed use-zone intervals overlap when the first's start is at or before the second's end *and* the second's start is at or before the first's end"

        Design: Difficulty/resource_temporal_overlap/placement_use_zone_overlap_exempted_only_for_attached_pair
        """
        scenario = _setup_validated_deck()
        deck_placement = scenario["deck_placement"]
        assert deck_placement["use_zone_start_cm"] == DECK_ZONE_START_CM, (
            f"expected {DECK_ZONE_START_CM}, got {deck_placement['use_zone_start_cm']} "
            "for the deck's use_zone_start_cm"
        )
        assert deck_placement["use_zone_end_cm"] == DECK_ZONE_END_CM, (
            f"expected {DECK_ZONE_END_CM}, got {deck_placement['use_zone_end_cm']} "
            "for the deck's use_zone_end_cm"
        )

        climber = _create_climber(scenario)
        a.assert_placement(climber)
        assert climber["use_zone_start_cm"] == CLIMBER_ZONE_START_CM, (
            f"expected {CLIMBER_ZONE_START_CM}, got {climber['use_zone_start_cm']} "
            "for the free-standing climber's use_zone_start_cm"
        )
        assert climber["use_zone_end_cm"] == CLIMBER_ZONE_END_CM, (
            f"expected {CLIMBER_ZONE_END_CM}, got {climber['use_zone_end_cm']} "
            "for the free-standing climber's use_zone_end_cm"
        )
        assert climber["attached_to_placement_id"] is None, (
            "expected None, got "
            f"{climber['attached_to_placement_id']} for a free-standing climber"
        )

        response = api_client.validate_placement(climber["id"], CONSULTANT)
        validate_error(response, ApiErrorId.ERR_USE_ZONE_OVERLAP.value, 409)

        refreshed = fx.get_placement(climber["id"])
        assert refreshed["status"] == "DRAFT", (
            f"expected DRAFT, got {refreshed['status']} after the refused validation"
        )

    def test_deck_attached_climber_validates_on_the_same_overlapping_geometry(self):
        """The attachment relationship, not the geometry, admits the climber.

        PRD: "Any overlap with another `VALIDATED` placement in the same area is refused with `ERR_USE_ZONE_OVERLAP` (HTTP 409), with exactly one exemption: a pair is exempt when one of the two is the other's attachment parent, because a slide bolted to its deck must by construction overlap that deck's zone."

        Design: Difficulty/resource_temporal_overlap/placement_use_zone_overlap_exempted_only_for_attached_pair
        """
        scenario = _setup_validated_deck()
        deck_id = scenario["deck_placement"]["id"]

        climber = _create_climber(scenario, attached_to_placement_id=deck_id)
        assert climber["attached_to_placement_id"] == deck_id, (
            f"expected {deck_id}, got {climber['attached_to_placement_id']} "
            "for attached_to_placement_id"
        )
        assert climber["use_zone_start_cm"] == CLIMBER_ZONE_START_CM, (
            f"expected {CLIMBER_ZONE_START_CM}, got {climber['use_zone_start_cm']} "
            "for the attached climber's use_zone_start_cm"
        )
        assert climber["use_zone_end_cm"] == CLIMBER_ZONE_END_CM, (
            f"expected {CLIMBER_ZONE_END_CM}, got {climber['use_zone_end_cm']} "
            "for the attached climber's use_zone_end_cm"
        )

        response = api_client.validate_placement(climber["id"], CONSULTANT)
        validated = validate_success(response, 200)
        assert validated["status"] == "VALIDATED", (
            f"expected VALIDATED, got {validated['status']} for the deck-attached climber"
        )
        assert validated["attached_to_placement_id"] == deck_id, (
            f"expected {deck_id}, got {validated['attached_to_placement_id']} "
            "after validating the attached climber"
        )

    def test_two_climbers_on_one_interval_are_separated_only_by_attachment(self):
        """Byte-identical zones, opposite outcomes, and the loser stays in DRAFT.

        PRD: "Two spatial checks then run, and both are deliberately restricted to placements already in `VALIDATED` status"

        Design: Difficulty/resource_temporal_overlap/placement_use_zone_overlap_exempted_only_for_attached_pair
        """
        scenario = _setup_validated_deck()
        deck_id = scenario["deck_placement"]["id"]

        free_climber = _create_climber(scenario)
        refused = api_client.validate_placement(free_climber["id"], CONSULTANT)
        validate_error(refused, ApiErrorId.ERR_USE_ZONE_OVERLAP.value, 409)

        attached_climber = _create_climber(scenario, attached_to_placement_id=deck_id)
        assert (
            attached_climber["use_zone_start_cm"],
            attached_climber["use_zone_end_cm"],
        ) == (
            free_climber["use_zone_start_cm"],
            free_climber["use_zone_end_cm"],
        ), (
            "the two climbers must occupy an identical interval: expected "
            f"({free_climber['use_zone_start_cm']}, {free_climber['use_zone_end_cm']}), "
            f"got ({attached_climber['use_zone_start_cm']}, "
            f"{attached_climber['use_zone_end_cm']})"
        )

        accepted = validate_success(
            api_client.validate_placement(attached_climber["id"], CONSULTANT), 200
        )
        assert accepted["status"] == "VALIDATED", (
            f"expected VALIDATED, got {accepted['status']} for the attached climber"
        )

        loser = fx.get_placement(free_climber["id"])
        assert loser["status"] == "DRAFT", (
            f"expected DRAFT, got {loser['status']} for the still-unattached climber"
        )

    def test_area_derived_numbers_reflect_the_draft_and_validated_set(self):
        """After the pair is resolved the area reports 122 cm and a 28 cm duty.

        PRD: "Both numbers are recomputed on every placement creation, every validation, every removal and every retrofit under the area."

        Design: Difficulty/resource_temporal_overlap/placement_use_zone_overlap_exempted_only_for_attached_pair
        """
        scenario = _setup_validated_deck()
        deck_id = scenario["deck_placement"]["id"]

        free_climber = _create_climber(scenario)
        validate_error(
            api_client.validate_placement(free_climber["id"], CONSULTANT),
            ApiErrorId.ERR_USE_ZONE_OVERLAP.value,
            409,
        )
        attached_climber = _create_climber(scenario, attached_to_placement_id=deck_id)
        validate_success(
            api_client.validate_placement(attached_climber["id"], CONSULTANT), 200
        )

        area = fx.get_play_area(scenario["area"]["id"])
        a.assert_play_area(area)
        assert area["critical_fall_height_cm"] == 122, (
            f"expected 122, got {area['critical_fall_height_cm']} "
            "for critical_fall_height_cm"
        )
        assert area["required_surfacing_depth_cm"] == 28, (
            f"expected 28, got {area['required_surfacing_depth_cm']} "
            "for required_surfacing_depth_cm"
        )


# The live booking runs 2026-08-06..2026-08-08 with a crew of 4, so it books
# 12 crew-days and the next admissible start is 2026-08-10.
JOB_A_START = "2026-08-06"
JOB_A_END = "2026-08-08"
JOB_A_CREW = 4
JOB_A_CREW_DAYS = 12


def _setup_installer_with_one_booking() -> dict:
    """An ORDERED project whose installer already holds 2026-08-06..08."""
    return fx.setup_job_scheduled(
        job_overrides={
            "scheduled_start_date": JOB_A_START,
            "scheduled_end_date": JOB_A_END,
            "crew_size": JOB_A_CREW,
        }
    )


def _attempt_booking(
    scenario: dict,
    scheduled_start_date: str,
    scheduled_end_date: str,
    crew_size: int,
):
    """Fire a second phased booking on the same order without unwrapping it."""
    payload = f.job_payload(
        scenario["order"]["id"],
        scenario["installer"]["id"],
        scheduled_start_date=scheduled_start_date,
        scheduled_end_date=scheduled_end_date,
        crew_size=crew_size,
    )
    return api_client.create_installation_job(payload, CONSULTANT)


def _committed_crew_days(scenario: dict) -> int:
    return fx.get_installer(scenario["installer"]["id"])["committed_crew_days"]


class TestInstallerTravelBuffer:
    """Four calendar probes around a live 2026-08-06..08 booking."""

    def test_intersecting_window_is_refused_as_a_booking_conflict(self):
        """2026-08-07..09 intersects the closed window 2026-08-06..08.

        PRD: "the requested closed date interval must not intersect any of those other bookings"

        Design: Difficulty/resource_temporal_overlap/installer_booking_requires_one_clear_travel_day_between_jobs
        """
        scenario = _setup_installer_with_one_booking()
        job_a = fx.get_job(scenario["job"]["id"])
        a.assert_installation_job(job_a)
        a.assert_booked_crew_days(job_a)
        assert job_a["booked_crew_days"] == JOB_A_CREW_DAYS, (
            f"expected {JOB_A_CREW_DAYS}, got {job_a['booked_crew_days']} "
            "for the live booking's booked_crew_days"
        )
        assert _committed_crew_days(scenario) == JOB_A_CREW_DAYS, (
            f"expected {JOB_A_CREW_DAYS} committed crew days before any second booking, "
            f"got {_committed_crew_days(scenario)}"
        )

        response = _attempt_booking(scenario, "2026-08-07", "2026-08-09", 2)
        validate_error(response, ApiErrorId.ERR_INSTALLER_BOOKING_CONFLICT.value, 409)

        assert _committed_crew_days(scenario) == JOB_A_CREW_DAYS, (
            f"expected {JOB_A_CREW_DAYS} committed crew days after a refused booking, "
            f"got {_committed_crew_days(scenario)}"
        )

    def test_first_non_intersecting_window_still_fails_the_travel_buffer(self):
        """2026-08-09..10 touches nothing yet leaves no fully clear day.

        PRD: "the new window's first day must fall on or after the earlier booking's last day plus one day plus the one-day buffer — so a booking that ends on the tenth of a month admits a next booking starting no earlier than the twelfth"

        Design: Difficulty/resource_temporal_overlap/installer_booking_requires_one_clear_travel_day_between_jobs
        """
        scenario = _setup_installer_with_one_booking()

        response = _attempt_booking(scenario, "2026-08-09", "2026-08-10", 2)
        validate_error(response, ApiErrorId.ERR_INSTALLER_BOOKING_CONFLICT.value, 409)

        assert _committed_crew_days(scenario) == JOB_A_CREW_DAYS, (
            f"expected {JOB_A_CREW_DAYS} committed crew days after a refused booking, "
            f"got {_committed_crew_days(scenario)}"
        )

    def test_first_admissible_window_starts_the_second_day_after_the_last(self):
        """2026-08-10..11 is the earliest legal start, and 2026-08-09 was not.

        PRD: "the new window's first day must fall on or after the earlier booking's last day plus one day plus the one-day buffer — so a booking that ends on the tenth of a month admits a next booking starting no earlier than the twelfth"

        Design: Difficulty/resource_temporal_overlap/installer_booking_requires_one_clear_travel_day_between_jobs
        """
        scenario = _setup_installer_with_one_booking()

        rejected = _attempt_booking(scenario, "2026-08-09", "2026-08-10", 2)
        validate_error(rejected, ApiErrorId.ERR_INSTALLER_BOOKING_CONFLICT.value, 409)

        accepted = _attempt_booking(scenario, "2026-08-10", "2026-08-11", 2)
        job_b = validate_success(accepted, 201)
        a.assert_installation_job(job_b)
        assert job_b["status"] == "SCHEDULED", (
            f"expected SCHEDULED, got {job_b['status']} for the boundary-day booking"
        )
        assert job_b["booked_crew_days"] == 4, (
            f"expected 4, got {job_b['booked_crew_days']} "
            "for a crew of 2 over two inclusive days"
        )
        a.assert_booked_crew_days(job_b)

        assert _committed_crew_days(scenario) == 16, (
            f"expected 16 committed crew days once the boundary booking is live, "
            f"got {_committed_crew_days(scenario)}"
        )

    def test_booking_conflict_outranks_crew_capacity(self):
        """A window that breaks both rules reports the conflict, not the capacity.

        PRD: "Either an intersection or an insufficient gap is refused with
        `ERR_INSTALLER_BOOKING_CONFLICT` (HTTP 409). Fourth, `crew_size` must not
        exceed the installer's `crew_capacity_per_day`, or the booking is refused
        with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 422)."
        PRD: "**Business constraints,** in this order: the rework ceiling
        (`ERR_REWORK_LIMIT_EXCEEDED`), use-zone overlap inside an area
        (`ERR_USE_ZONE_OVERLAP`), use-zone containment inside the area's axis
        interval (`ERR_USE_ZONE_OUT_OF_BOUNDS`), attachment direction
        (`ERR_INVALID_ATTACHMENT_TARGET`), installer booking conflicts
        (`ERR_INSTALLER_BOOKING_CONFLICT`), crew capacity
        (`ERR_CREW_CAPACITY_EXCEEDED`)"

        Design: Difficulty/resource_temporal_overlap/installer_booking_requires_one_clear_travel_day_between_jobs
        """
        scenario = _setup_installer_with_one_booking()

        response = _attempt_booking(scenario, "2026-08-09", "2026-08-09", 7)
        validate_error(response, ApiErrorId.ERR_INSTALLER_BOOKING_CONFLICT.value, 409)

        assert _committed_crew_days(scenario) == JOB_A_CREW_DAYS, (
            f"expected {JOB_A_CREW_DAYS} committed crew days after a refused booking, "
            f"got {_committed_crew_days(scenario)}"
        )

    def test_crew_capacity_fires_once_the_travel_buffer_is_clear(self):
        """2026-08-13 clears every window, so only the crew ceiling is left.

        PRD: "Fourth, `crew_size` must not exceed the installer's `crew_capacity_per_day`, or the booking is refused with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/installer_booking_requires_one_clear_travel_day_between_jobs
        """
        scenario = _setup_installer_with_one_booking()
        installer = fx.get_installer(scenario["installer"]["id"])
        assert installer["crew_capacity_per_day"] == 6, (
            f"expected a crew ceiling of 6, got {installer['crew_capacity_per_day']}"
        )

        job_b = fx.book_second_job(scenario, "2026-08-10", "2026-08-11", crew_size=2)
        assert job_b["status"] == "SCHEDULED", (
            f"expected SCHEDULED, got {job_b['status']} for the second booking"
        )

        response = _attempt_booking(scenario, "2026-08-13", "2026-08-13", 7)
        validate_error(response, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED.value, 422)

        assert _committed_crew_days(scenario) == 16, (
            "expected 16 committed crew days after the capacity refusal, got "
            f"{_committed_crew_days(scenario)}"
        )
        listed, _meta = a.assert_paginated_list(
            api_client.list_installation_jobs(
                ADMIN, params={"order_id": scenario["order"]["id"]}
            ),
            2,
        )
        assert len(listed) == 2, (
            f"expected exactly two bookings on the order, got {len(listed)}"
        )
