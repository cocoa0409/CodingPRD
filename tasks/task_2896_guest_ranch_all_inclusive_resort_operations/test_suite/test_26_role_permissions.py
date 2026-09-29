"""Role permissions: exclusive operations, per-row guest ownership, the assigned
guide rule and the segregation of duties on an incident report."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success
from test_helpers import assertions
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    close_incident_payload,
    create_booking_payload,
    create_cabin_payload,
    create_guest_payload,
    create_horse_payload,
    dispose_payload,
    incident_report_payload,
    party_member,
)
from test_helpers.fixtures import (
    assign_guide,
    attach_mount,
    build_activity_slot,
    build_active_guide,
    build_booking,
    build_cabin,
    build_guest,
    build_horse,
    build_in_season,
    build_open_season,
    build_ready_rider,
    confirm_booking,
    open_slot,
    pay_deposit,
    set_clock_to,
    take_seat,
)
from test_helpers.test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
    SAFETY_OFFICER,
    make_activity_guide_headers,
    make_guest_headers,
    make_safety_officer_headers,
)


class TestExclusiveOperations:
    """A recognised role that the endpoint does not permit is refused outright."""

    def test_each_role_is_refused_another_roles_exclusive_operation(self, client):
        """Three otherwise perfect payloads fail only on the acting role: booking, herd registry and cabin registry.

        PRD: "If the role is recognised but is not among the roles the addressed endpoint permits, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/each_role_is_refused_another_roles_exclusive_operation
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_open_season(client)
        cabin = build_cabin(client)
        ann = build_guest(client, "Ann Adult", "1985-04-02", 165)

        validate_error(
            client.create_booking(
                create_booking_payload(
                    season["id"], cabin["id"], ann["id"], [party_member(ann["id"])]
                ),
                RANCH_MANAGER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            client.create_horse(create_horse_payload(), RESERVATIONS_AGENT),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            client.create_cabin(
                create_cabin_payload("Birch", 4), HORSE_PROGRAM_DIRECTOR
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        _, booking_meta = validate_paginated(client.list_bookings(RESERVATIONS_AGENT))
        assert booking_meta["total_count"] == 0
        _, horse_meta = validate_paginated(client.list_horses(HORSE_PROGRAM_DIRECTOR))
        assert horse_meta["total_count"] == 0
        _, cabin_meta = validate_paginated(client.list_cabins(RANCH_MANAGER))
        assert cabin_meta["total_count"] == 1


class TestGuestOwnership:
    """The Guest role is scoped to the guest's own row, not to the guest list."""

    def test_guest_role_cannot_read_another_guests_record(self, client):
        """Ann reads her own guest record; the same read aimed at Ben's record is refused as a non-owner.

        PRD: "A guest reading their own guest record, signing their own waiver, or reading one of their own activity seats is permitted; addressing another guest's record, another guest's seat, or a seat whose `guest_id` is not their own is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/guest_role_cannot_read_another_guests_record_or_booking
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_open_season(client)
        cabin = build_cabin(client)
        ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
        ben = validate_success(
            client.create_guest(
                create_guest_payload("Ben Adult", "1983-07-11", 190), RANCH_MANAGER
            ),
            201,
        )

        own = validate_success(client.get_guest(ann["id"], make_guest_headers(ann["id"])))
        assertions.assert_guest(own)
        assert own["id"] == ann["id"]
        assert own["full_name"] == "Ann Adult"

        validate_error(
            client.get_guest(ben["id"], make_guest_headers(ann["id"])),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
            403,
        )

        # The row Ann was refused is real: the desk books Ben against it.
        bens_booking = build_booking(
            client, season["id"], cabin["id"], [party_member(ben["id"])]
        )
        assert bens_booking["booking_status"] == "HELD"
        assert bens_booking["lead_guest_id"] == ben["id"]


class TestAssignedGuideRule:
    """Running a slot belongs to the guide who personally holds its assignment."""

    def test_guide_without_a_scheduled_assignment_cannot_run_the_slot(self, client):
        """A second onboarded guide, with no assignment on this slot, is refused the run that its lead performs.

        PRD: "A guide may only act on a slot for which they personally hold a guide assignment whose `assignment_status` is `SCHEDULED`; running a slot, completing a slot, checking a rider in at the trailhead, and filing an incident report against a seat on that slot are all refused with `ERR_NOT_ASSIGNED_GUIDE` (HTTP 403) otherwise."

        Design: Corner/rbac/guide_without_a_scheduled_assignment_cannot_run_the_slot
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_in_season(client)
        lead = build_active_guide(client, season["id"], "Gus Guide", housing_bunk_number=3)
        bystander = build_active_guide(
            client, season["id"], "Hal Helper", housing_bunk_number=4
        )
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
        assign_guide(client, slot["id"], lead["id"])
        opened = open_slot(client, slot["id"])
        assert opened["slot_status"] == "OPEN"
        set_clock_to(client, "2026-10-13T15:00:00Z")

        validate_error(
            client.run_slot(slot["id"], make_activity_guide_headers(bystander["id"])),
            ApiErrorId.ERR_NOT_ASSIGNED_GUIDE.value,
            403,
        )
        still_open = validate_success(client.get_activity_slot(slot["id"], RANCH_MANAGER))
        assert still_open["slot_status"] == "OPEN"

        running = validate_success(
            client.run_slot(slot["id"], make_activity_guide_headers(lead["id"]))
        )
        assert running["slot_status"] == "RUNNING"


class TestSegregationOfDuties:
    """The officer who judged an incident may not also sign it off."""

    def test_one_officer_cannot_both_dispose_and_close_the_same_report(self, client):
        """An incident cleared by one officer is refused closure by that same officer and accepted from a second.

        PRD: "The acting user identity must differ from the `disposed_by_user_id` recorded at disposition — the officer who judged an incident may not also sign it off — and a self-closure is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/one_officer_cannot_both_dispose_and_close_the_same_report
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_in_season(client)
        cabin = build_cabin(client)
        rider = build_ready_rider(client, "Ann Adult", "1985-04-02", 165, ability="BEGINNER")
        comet = build_horse(client, "Comet")
        booking = build_booking(client, season["id"], cabin["id"], [party_member(rider["id"])])
        pay_deposit(client, booking["id"])
        confirmed = confirm_booking(client, booking["id"])
        assert confirmed["booking_status"] == "CONFIRMED"

        slot = build_activity_slot(client, season["id"])
        guide = build_active_guide(client, season["id"], "Gus Guide")
        assign_guide(client, slot["id"], guide["id"])
        open_slot(client, slot["id"])
        seat = take_seat(client, slot["id"], booking["id"], rider["id"])
        # The seat left the mounted slot MOUNT_SHORT, so the OPEN slot dropped to
        # HOLD in that same request; naming Comet clears the defect and the slot
        # is re-opened from HOLD before it can be run.
        attach_mount(client, seat["id"], comet["id"])
        reopened = open_slot(client, slot["id"])
        assert reopened["slot_status"] == "OPEN"

        set_clock_to(client, "2026-10-12T15:00:00Z")
        guide_headers = make_activity_guide_headers(guide["id"])
        validate_success(client.run_slot(slot["id"], guide_headers))
        validate_success(client.check_in_reservation(seat["id"], guide_headers))

        filed = validate_success(
            client.create_incident_report(
                seat["id"],
                incident_report_payload(
                    severity="MINOR",
                    narrative="rider stepped off at the creek and turned an ankle",
                    occurred_at="2026-10-12T15:30:00Z",
                    horse_id=comet["id"],
                ),
                guide_headers,
            ),
            201,
        )
        assertions.assert_incident_report(filed)
        assert filed["incident_status"] == "FILED"

        alice = make_safety_officer_headers("officer-alice")
        bob = make_safety_officer_headers("officer-bob")
        cleared = validate_success(
            client.dispose_incident_report(
                filed["id"], dispose_payload("CLEARED", "no equipment defect found"), alice
            )
        )
        assert cleared["incident_status"] == "CLEARED"
        assert cleared["disposed_by_user_id"] == "officer-alice"

        validate_error(
            client.close_incident_report(filed["id"], close_incident_payload(False), alice),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )
        unchanged = validate_success(client.get_incident_report(filed["id"], SAFETY_OFFICER))
        assert unchanged["incident_status"] == "CLEARED"
        assert unchanged["version"] == cleared["version"]

        closed = validate_success(
            client.close_incident_report(filed["id"], close_incident_payload(False), bob)
        )
        assert closed["incident_status"] == "CLOSED"
        assert closed["disposed_by_user_id"] == "officer-alice"


class TestSharedAndExclusiveHolders:
    """Some operations name two roles; the ones that name only one stay closed."""

    def test_shared_operations_work_for_both_holders_but_exclusives_do_not(self, client):
        """Suspension and cancellation accept either holder, while reinstatement answers only to the manager.

        PRD: "Reinstatement, performed by a `RanchManager` with a `reason`, returns a `SUSPENDED` or `RESTRICTED` guest to `GOOD`, lifts the rank cap the prior standing imposed so that `effective_ability_rank` is recomputed from the assessment record alone, and increments the guest's `version` by 1."

        Design: Corner/rbac/shared_operations_work_for_both_holders_but_exclusives_do_not
        """
        set_clock_to(client, "2026-08-01T00:00:00Z")
        season = build_open_season(client)
        aspen = build_cabin(client, "Aspen", 4)
        birch = build_cabin(client, "Birch", 4)
        ann = build_guest(client, "Ann Adult", "1985-04-02", 165)
        ben = validate_success(
            client.create_guest(
                create_guest_payload("Ben Adult", "1983-07-11", 190), RANCH_MANAGER
            ),
            201,
        )

        booking_a = build_booking(client, season["id"], aspen["id"], [party_member(ann["id"])])
        booking_b = build_booking(client, season["id"], birch["id"], [party_member(ben["id"])])

        cancelled_a = validate_success(
            client.cancel_booking(booking_a["id"], "guest changed plans", RESERVATIONS_AGENT)
        )
        assert cancelled_a["booking_status"] == "CANCELLED"
        cancelled_b = validate_success(
            client.cancel_booking(booking_b["id"], "cabin repurposed", RANCH_MANAGER)
        )
        assert cancelled_b["booking_status"] == "CANCELLED"

        suspended = validate_success(
            client.suspend_guest(
                ann["id"], "SUSPENDED", "unsafe conduct in the corral", SAFETY_OFFICER
            )
        )
        assertions.assert_guest(suspended)
        assert suspended["guest_standing"] == "SUSPENDED"

        validate_error(
            client.reinstate_guest(ann["id"], "conduct review completed", SAFETY_OFFICER),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        still_suspended = validate_success(client.get_guest(ann["id"], RANCH_MANAGER))
        assert still_suspended["guest_standing"] == "SUSPENDED"
        assert still_suspended["version"] == suspended["version"]

        reinstated = validate_success(
            client.reinstate_guest(ann["id"], "conduct review completed", RANCH_MANAGER)
        )
        assert reinstated["guest_standing"] == "GOOD"
        assert reinstated["version"] == suspended["version"] + 1
