"""Endpoint behaviours: computed reads, one-step lifecycle actions, join-row
writes and the mount auto-assignment selector."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import guide_assignment_payload, party_member
from test_helpers.fixtures import (
    attach_mount,
    build_active_guide,
    build_activity_slot,
    build_booking,
    build_cabin,
    build_horse,
    build_open_season,
    build_ready_rider,
    build_season,
    confirm_booking,
    pay_deposit,
    set_clock_to,
    take_seat,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
)


class TestComputedReads:
    """A read is never a snapshot: derived figures are recomputed on the way out."""

    def test_projected_retention_bonus_moves_with_the_logical_clock(self, client):
        """The same staff row reports a larger pro-rated accrual after the clock advances, with no write in between.

        PRD: "The pro-rated figure is the season's `retention_bonus_cents` multiplied by `days_worked` and divided by `contract_days`, rounded half up to whole cents."

        Design: Corner/endpoints/staff_read_recomputes_the_projected_retention_bonus_from_the_clock
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_open_season(client)
        guide = build_active_guide(client, season["id"])

        day_zero = validate_success(client.get_staff_member(guide["id"], RANCH_MANAGER))
        assertions.assert_staff_member(day_zero)
        assert day_zero["employment_status"] == "ACTIVE"
        assert day_zero["contract_days"] == 106
        assert day_zero["days_worked"] == 0
        assert day_zero["retention_bonus_projected_cents"] == 0

        set_clock_to(client, "2026-10-11T00:00:00Z")

        later = validate_success(client.get_staff_member(guide["id"], RANCH_MANAGER))
        assert later["contract_days"] == 106
        assert later["days_worked"] == 71
        assert later["retention_bonus_projected_cents"] == 80377
        assert later["version"] == day_zero["version"]


class TestLifecycleActionEndpoints:
    """Transition endpoints walk exactly one declared step."""

    def test_season_advance_refuses_to_skip_a_lifecycle_step(self, client):
        """A season in PLANNING cannot jump to IN_SEASON nor fall back to PLANNING, while the single legal step lands.

        PRD: "Any other value, any step out of order, and any repeat of a step already applied is refused with `ERR_INVALID_SEASON_TRANSITION`."

        Design: Corner/endpoints/season_advance_refuses_to_skip_a_lifecycle_step
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_season(client)
        assertions.assert_season(season)
        assert season["season_status"] == "PLANNING"

        validate_error(
            client.advance_season(season["id"], "IN_SEASON", RANCH_MANAGER),
            ApiErrorId.ERR_INVALID_SEASON_TRANSITION.value,
            409,
        )

        opened = validate_success(
            client.advance_season(season["id"], "OPEN", RANCH_MANAGER)
        )
        assert opened["season_status"] == "OPEN"
        assert opened["version"] == season["version"] + 1

        validate_error(
            client.advance_season(season["id"], "PLANNING", RANCH_MANAGER),
            ApiErrorId.ERR_INVALID_SEASON_TRANSITION.value,
            409,
        )

        final = validate_success(client.get_season(season["id"], RANCH_MANAGER))
        assert final["season_status"] == "OPEN"
        assert final["version"] == opened["version"]
        # The annual accounting event belongs to IN_SEASON -> CLOSED, so the
        # rollup counters are still at their creation values.
        assert final["gross_package_revenue_cents"] == 0
        assert final["capital_reserve_cents"] == 0
        assert final["net_surplus_cents"] == 0


class TestJoinRowEndpoints:
    """A guide assignment is a join row, and both ends of it move."""

    def test_guide_assignment_links_a_slot_and_a_staff_member(self, client):
        """An unknown staff member cannot be scheduled, and the accepted link writes the join row, the slot and the guide.

        PRD: "An accepted assignment is created `SCHEDULED` with `credited_hours` at 0, raises the slot's `assigned_guide_count` by 1, triggers a recomputation of the slot's `readiness_posture`, adds the slot's `duration_hours` to the guide's `scheduled_guide_hours`, and increments the slot's `version` by 1."

        Design: Corner/endpoints/guide_assignment_links_a_slot_and_a_staff_member_and_updates_both_sides
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_open_season(client)
        guide = build_active_guide(client, season["id"])
        assert float(guide["scheduled_guide_hours"]) == 0.0

        slot = build_activity_slot(
            client,
            season["id"],
            activity_type="HIKE",
            starts_at="2026-10-13T15:00:00Z",
            ends_at="2026-10-13T17:00:00Z",
            terrain_grade="ROLLING",
            min_ability_rank="UNASSESSED",
            capacity=4,
            rider_surcharge_cents=0,
            mount_required=False,
        )
        assert float(slot["duration_hours"]) == 2.0
        assert slot["assigned_guide_count"] == 0

        validate_error(
            client.create_guide_assignment(
                slot["id"], guide_assignment_payload(NON_EXISTENT_UUID), RANCH_MANAGER
            ),
            ApiErrorId.ERR_STAFF_MEMBER_NOT_FOUND.value,
            404,
        )

        assignment = validate_success(
            client.create_guide_assignment(
                slot["id"], guide_assignment_payload(guide["id"]), RANCH_MANAGER
            ),
            201,
        )
        assertions.assert_guide_assignment(assignment)
        assert assignment["slot_id"] == slot["id"]
        assert assignment["staff_member_id"] == guide["id"]
        assert assignment["assignment_status"] == "SCHEDULED"
        assert float(assignment["credited_hours"]) == 0.0

        slot_after = validate_success(
            client.get_activity_slot(slot["id"], RANCH_MANAGER)
        )
        assertions.assert_slot_counters(
            slot_after, assigned_guide_count=1, required_guide_count=0
        )
        assert slot_after["version"] == slot["version"] + 1
        assertions.assert_readiness_posture(slot_after, "STAFFED_READY")

        guide_after = validate_success(
            client.get_staff_member(guide["id"], RANCH_MANAGER)
        )
        assert float(guide_after["scheduled_guide_hours"]) == 2.0

        rows, meta = validate_paginated(
            client.list_guide_assignments(RANCH_MANAGER, params={"slot_id": slot["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == assignment["id"]


class TestMountAutoAssignment:
    """The fairest-available draw is decided first by the ranking, then by the filter."""

    def test_auto_assign_picks_the_lightest_horse_then_the_only_one_left(self, client):
        """The first draw takes the unworked animal and the second takes the only one that clears the recovery buffer.

        PRD: "Step two orders the survivors by `scheduled_load_hours` ascending, then by `consecutive_duty_days` ascending, then by `created_at` ascending, and takes the first — so the least-worked animal wins, the freshest breaks the tie, and the earliest-registered breaks the tie after that."

        Design: Corner/endpoints/auto_assign_picks_the_lightest_horse_then_the_only_one_left
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_open_season(client)
        cabin = build_cabin(client)
        ann = build_ready_rider(
            client, "Ann Adult", "1985-04-02", 165, ability="INTERMEDIATE"
        )
        ben = build_ready_rider(
            client, "Ben Adult", "1983-07-11", 190, ability="INTERMEDIATE"
        )

        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(ann["id"]), party_member(ben["id"])],
        )
        assert booking["deposit_required_cents"] == 287700
        pay_deposit(client, booking["id"])
        confirm_booking(client, booking["id"])

        comet = build_horse(client, name="Comet")
        dusty = build_horse(client, name="Dusty")

        morning = build_activity_slot(
            client,
            season["id"],
            starts_at="2026-10-12T08:00:00Z",
            ends_at="2026-10-12T10:00:00Z",
        )
        afternoon = build_activity_slot(
            client,
            season["id"],
            starts_at="2026-10-12T15:00:00Z",
            ends_at="2026-10-12T17:00:00Z",
        )

        morning_seat = take_seat(client, morning["id"], booking["id"], ann["id"])
        attach_mount(client, morning_seat["id"], comet["id"])

        seat_ann = take_seat(client, afternoon["id"], booking["id"], ann["id"])
        seat_ben = take_seat(client, afternoon["id"], booking["id"], ben["id"])

        ann_mount = validate_success(
            client.auto_assign_mount(seat_ann["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assertions.assert_activity_reservation(ann_mount)
        assert ann_mount["assigned_horse_id"] == dusty["id"]
        assert ann_mount["mount_status"] == "ASSIGNED"

        ben_mount = validate_success(
            client.auto_assign_mount(seat_ben["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assert ben_mount["assigned_horse_id"] == comet["id"]
        assert ben_mount["mount_status"] == "ASSIGNED"

        comet_after = validate_success(
            client.get_horse(comet["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assertions.assert_horse_load(comet_after, scheduled_load_hours=4.0)
        dusty_after = validate_success(
            client.get_horse(dusty["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assertions.assert_horse_load(dusty_after, scheduled_load_hours=2.0)

        afternoon_after = validate_success(
            client.get_activity_slot(afternoon["id"], RANCH_MANAGER)
        )
        assertions.assert_slot_counters(
            afternoon_after, confirmed_rider_count=2, mount_assigned_count=2
        )
