"""Concurrency and layering: the four version pins that guard a seat, an
assessment, a mount assignment and a folio adjustment, plus the deterministic
tie-break the mount selector applies when two animals are indistinguishable."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import assertions
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    folio_adjustment_payload,
    mount_assignment_payload,
    party_member,
    reservation_payload,
    rider_assessment_payload,
)
from test_helpers.fixtures import (
    assign_guide,
    build_activity_slot,
    build_active_guide,
    build_booking,
    build_cabin,
    build_guest,
    build_horse,
    build_in_season,
    build_ready_rider,
    check_in,
    confirm_booking,
    open_slot,
    pay_deposit,
    set_clock_to,
    sign_guest_waiver,
    take_seat,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
)


class TestSlotVersionPin:
    """A slot's version moves under a client that seats two riders in a row."""

    def test_stale_slot_version_is_refused_on_the_second_seat(self, client):
        """The second seat replays the version the client read before the first seat and is refused until it refreshes.

        PRD: "If `expected_slot_version` does not equal the slot's stored `version`, the request is rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412) — the seat itself would otherwise have been a legitimate booking, and the stale pin is the only signal that the client's view is out of date."

        Design: Corner/cross_cutting_complexity_layers/stale_slot_version_is_refused_on_the_second_seat
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_in_season(client)
        cabin = build_cabin(client)
        ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, ability="BEGINNER")
        ben = build_ready_rider(client, "Ben Adult", "1983-07-11", 190, ability="BEGINNER")
        booking = build_booking(
            client,
            season["id"],
            cabin["id"],
            [party_member(ann["id"]), party_member(ben["id"])],
        )
        pay_deposit(client, booking["id"])
        confirm_booking(client, booking["id"])

        # A HIKE needs no mounts, so neither seat can leave the slot MOUNT_SHORT
        # and the slot stays OPEN across both attempts - the version pin is the
        # only thing under test here.
        slot = build_activity_slot(
            client, season["id"], activity_type="HIKE", mount_required=False
        )
        guide = build_active_guide(client, season["id"], "Gus Guide")
        assign_guide(client, slot["id"], guide["id"])
        opened = open_slot(client, slot["id"])
        assert opened["slot_status"] == "OPEN"

        # One read of the slot, then two seats attempted against that one read.
        before = validate_success(client.get_activity_slot(slot["id"], RESERVATIONS_AGENT))
        sv_shared = before["version"]

        first = validate_success(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], ann["id"], sv_shared),
                RESERVATIONS_AGENT,
            ),
            201,
        )
        assertions.assert_activity_reservation(first)
        assert first["reservation_status"] == "CONFIRMED"

        validate_error(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], ben["id"], sv_shared),
                RESERVATIONS_AGENT,
            ),
            ApiErrorId.ERR_STALE_SLOT_VERSION.value,
            412,
        )
        after_refusal = validate_success(client.get_activity_slot(slot["id"], RESERVATIONS_AGENT))
        assertions.assert_slot_counters(after_refusal, confirmed_rider_count=1)
        sv_fresh = after_refusal["version"]
        assert sv_fresh == sv_shared + 1

        second = validate_success(
            client.create_reservation(
                slot["id"],
                reservation_payload(booking["id"], ben["id"], sv_fresh),
                RESERVATIONS_AGENT,
            ),
            201,
        )
        assert second["reservation_status"] == "CONFIRMED"
        settled = validate_success(client.get_activity_slot(slot["id"], RESERVATIONS_AGENT))
        assertions.assert_slot_counters(settled, confirmed_rider_count=2)


class TestGuestVersionPin:
    """Raising an assessment moves the guest row, so a replayed pin is stale."""

    def test_stale_guest_version_is_refused_on_a_second_assessment(self, client):
        """Two assessments raised from one read of the guest: the second is refused, then accepted on a refreshed pin.

        PRD: "A mismatch with the guest's stored `version` is rejected with `ERR_STALE_GUEST_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_guest_version_is_refused_on_a_second_assessment
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        guest = build_guest(client, "Ann Adult", "1985-04-02", 165)
        sign_guest_waiver(client, guest["id"])

        before = validate_success(client.get_guest(guest["id"], RESERVATIONS_AGENT))
        gv_shared = before["version"]
        assert before["current_ability_rank"] == "UNASSESSED"
        assert before["effective_ability_rank"] == "UNASSESSED"

        # PRD: POST /guests/{guestId}/rider-assessments is the
        # HorseProgramDirector's alone.
        first = validate_success(
            client.create_rider_assessment(
                guest["id"],
                rider_assessment_payload("BEGINNER", gv_shared),
                HORSE_PROGRAM_DIRECTOR,
            ),
            201,
        )
        assertions.assert_rider_assessment(first)
        assert first["assessment_status"] == "PENDING"

        validate_error(
            client.create_rider_assessment(
                guest["id"],
                rider_assessment_payload("NOVICE", gv_shared),
                HORSE_PROGRAM_DIRECTOR,
            ),
            ApiErrorId.ERR_STALE_GUEST_VERSION.value,
            412,
        )

        refreshed = validate_success(client.get_guest(guest["id"], RESERVATIONS_AGENT))
        gv_fresh = refreshed["version"]
        assert gv_fresh == gv_shared + 1
        assert refreshed["current_ability_rank"] == "UNASSESSED"

        second = validate_success(
            client.create_rider_assessment(
                guest["id"],
                rider_assessment_payload("NOVICE", gv_fresh),
                HORSE_PROGRAM_DIRECTOR,
            ),
            201,
        )
        assert second["assessment_status"] == "PENDING"

        # A request never evaluated is not superseded by the next request.
        untouched = validate_success(
            client.get_rider_assessment(first["id"], RESERVATIONS_AGENT)
        )
        assert untouched["assessment_status"] == "PENDING"

        items, meta = validate_paginated(
            client.list_rider_assessments(RESERVATIONS_AGENT, params={"guest_id": guest["id"]})
        )
        assert meta["total_count"] == 2
        assert len(items) == 2


class TestHorseVersionPin:
    """Booking an animal onto a ride moves the horse row that the next pin quotes."""

    def test_stale_horse_version_is_refused_on_the_next_mount_assignment(self, client):
        """Comet is named onto two rides on consecutive days from a single read of the horse; the second pin is stale.

        PRD: "A mismatch with the horse's stored `version` is rejected with `ERR_STALE_HORSE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_horse_version_is_refused_on_the_next_mount_assignment
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_in_season(client)
        cabin = build_cabin(client)
        ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, ability="BEGINNER")
        comet = build_horse(client, "Comet")
        booking = build_booking(client, season["id"], cabin["id"], [party_member(ann["id"])])
        pay_deposit(client, booking["id"])
        confirm_booking(client, booking["id"])

        guide = build_active_guide(client, season["id"], "Gus Guide")
        day_one = build_activity_slot(client, season["id"])
        day_two = build_activity_slot(
            client,
            season["id"],
            starts_at="2026-10-13T15:00:00Z",
            ends_at="2026-10-13T17:00:00Z",
        )
        for slot_id in (day_one["id"], day_two["id"]):
            assign_guide(client, slot_id, guide["id"])
            open_slot(client, slot_id)
        seat_one = take_seat(client, day_one["id"], booking["id"], ann["id"])
        seat_two = take_seat(client, day_two["id"], booking["id"], ann["id"])
        assert seat_two["mount_status"] == "PENDING"

        before = validate_success(client.get_horse(comet["id"], HORSE_PROGRAM_DIRECTOR))
        hv_shared = before["version"]
        assertions.assert_horse_load(before, scheduled_load_hours=0.0)

        mounted = validate_success(
            client.assign_mount(
                seat_one["id"],
                mount_assignment_payload(comet["id"], hv_shared),
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        assert mounted["mount_status"] == "ASSIGNED"
        assert mounted["assigned_horse_id"] == comet["id"]

        validate_error(
            client.assign_mount(
                seat_two["id"],
                mount_assignment_payload(comet["id"], hv_shared),
                HORSE_PROGRAM_DIRECTOR,
            ),
            ApiErrorId.ERR_STALE_HORSE_VERSION.value,
            412,
        )
        unmounted = validate_success(
            client.get_reservation(seat_two["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assert unmounted["assigned_horse_id"] is None
        assert unmounted["mount_status"] == "PENDING"

        refreshed = validate_success(client.get_horse(comet["id"], HORSE_PROGRAM_DIRECTOR))
        hv_fresh = refreshed["version"]
        assert hv_fresh == hv_shared + 1
        assertions.assert_horse_load(refreshed, scheduled_load_hours=2.0)

        second = validate_success(
            client.assign_mount(
                seat_two["id"],
                mount_assignment_payload(comet["id"], hv_fresh),
                HORSE_PROGRAM_DIRECTOR,
            )
        )
        assert second["mount_status"] == "ASSIGNED"
        settled = validate_success(client.get_horse(comet["id"], HORSE_PROGRAM_DIRECTOR))
        assertions.assert_horse_load(settled, scheduled_load_hours=4.0)


class TestBookingVersionPin:
    """Each folio adjustment moves the booking, so the next memo needs a fresh pin."""

    def test_stale_booking_version_is_refused_on_the_second_folio_adjustment(self, client):
        """Two adjustments posted against one read of the booking: only the first lands until the client re-reads.

        PRD: "A mismatch with the booking's stored `version` is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_booking_version_is_refused_on_the_second_folio_adjustment
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_in_season(client)
        cabin = build_cabin(client)
        ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, ability="BEGINNER")
        booking = build_booking(client, season["id"], cabin["id"], [party_member(ann["id"])])
        pay_deposit(client, booking["id"])
        confirm_booking(client, booking["id"])
        set_clock_to(client, "2026-10-11T15:00:00Z")
        arrived = check_in(client, booking["id"])
        assert arrived["booking_status"] == "CHECKED_IN"

        before = validate_success(client.get_booking(booking["id"], RANCH_MANAGER))
        bv_shared = before["version"]
        assert before["folio_adjustment_total_cents"] == 0

        first = validate_success(
            client.post_folio_adjustment(
                booking["id"],
                folio_adjustment_payload(5000, "trading post tab", bv_shared),
                RANCH_MANAGER,
            )
        )
        assertions.assert_booking(first)
        assert first["folio_adjustment_total_cents"] == 5000

        validate_error(
            client.post_folio_adjustment(
                booking["id"],
                folio_adjustment_payload(2500, "farrier demonstration", bv_shared),
                RANCH_MANAGER,
            ),
            ApiErrorId.ERR_STALE_BOOKING_VERSION.value,
            412,
        )
        refreshed = validate_success(client.get_booking(booking["id"], RANCH_MANAGER))
        assert refreshed["folio_adjustment_total_cents"] == 5000
        bv_fresh = refreshed["version"]
        assert bv_fresh == bv_shared + 1

        second = validate_success(
            client.post_folio_adjustment(
                booking["id"],
                folio_adjustment_payload(2500, "farrier demonstration", bv_fresh),
                RANCH_MANAGER,
            )
        )
        assert second["folio_adjustment_total_cents"] == 7500
        # PRD: only "when the booking has already reached `CHECKED_OUT`,
        # `final_folio_total_cents` and `folio_balance_cents` are recomputed on
        # the spot", so the folio waterfall is not yet asserted for this
        # CHECKED_IN booking; the adjustment total is the whole of the effect an
        # accepted adjustment has here.
        assert second["booking_status"] == "CHECKED_IN"
        assert second["version"] == bv_fresh + 1


class TestMountSelectorTieBreak:
    """Two indistinguishable animals resolve by registration order, never by id."""

    def test_mount_selector_breaks_a_perfect_tie_by_created_at(self, client):
        """Comet and Dusty are equal on load and on duty days, so the earlier-registered animal wins both draws.

        PRD: "Step two orders the survivors by `scheduled_load_hours` ascending, then by `consecutive_duty_days` ascending, then by `created_at` ascending, and takes the first — so the least-worked animal wins, the freshest breaks the tie, and the earliest-registered breaks the tie after that."

        Design: Corner/cross_cutting_complexity_layers/mount_selector_breaks_a_perfect_tie_by_created_at
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_in_season(client)
        cabin = build_cabin(client)
        ann = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, ability="BEGINNER")
        comet = build_horse(client, "Comet")
        dusty = build_horse(client, "Dusty")
        assertions.assert_horse_load(comet, scheduled_load_hours=0.0, consecutive_duty_days=0)
        assertions.assert_horse_load(dusty, scheduled_load_hours=0.0, consecutive_duty_days=0)

        booking = build_booking(client, season["id"], cabin["id"], [party_member(ann["id"])])
        pay_deposit(client, booking["id"])
        confirm_booking(client, booking["id"])
        slot = build_activity_slot(client, season["id"])
        guide = build_active_guide(client, season["id"], "Gus Guide")
        assign_guide(client, slot["id"], guide["id"])
        open_slot(client, slot["id"])
        seat = take_seat(client, slot["id"], booking["id"], ann["id"])

        first_draw = validate_success(
            client.auto_assign_mount(seat["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assert first_draw["assigned_horse_id"] == comet["id"]
        assert first_draw["mount_status"] == "ASSIGNED"

        released = validate_success(
            client.release_mount(seat["id"], "tack refitted at the barn", HORSE_PROGRAM_DIRECTOR)
        )
        assert released["mount_status"] == "RELEASED"
        assert released["assigned_horse_id"] is None
        assert released["mount_release_count"] == 1
        assertions.assert_horse_load(
            validate_success(client.get_horse(comet["id"], HORSE_PROGRAM_DIRECTOR)),
            scheduled_load_hours=0.0,
        )

        second_draw = validate_success(
            client.auto_assign_mount(seat["id"], HORSE_PROGRAM_DIRECTOR)
        )
        assert second_draw["assigned_horse_id"] == comet["id"]
        assert second_draw["mount_status"] == "ASSIGNED"
        assertions.assert_horse_load(
            validate_success(client.get_horse(dusty["id"], HORSE_PROGRAM_DIRECTOR)),
            scheduled_load_hours=0.0,
        )
