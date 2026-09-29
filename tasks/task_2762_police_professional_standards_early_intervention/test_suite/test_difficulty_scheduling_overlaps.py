"""Two overlap rules with opposite inclusivity, and the employment dimension above both."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assert_instant, assert_officer_ledgers, assert_two_dp
from test_helpers import factories, fixtures


def three_files_against_three_officers(api, world):
    """Rossi, Sant and Tan each answer their own file, all three carried by Ahn."""
    people = {}
    for key, badge, name, incident in (
        ("rossi", "PN-701", "Officer Rossi", "2026-07-15T20:00:00Z"),
        ("sant", "PN-702", "Officer Sant", "2026-07-16T20:00:00Z"),
        ("tan", "PN-703", "Officer Tan", "2026-07-17T20:00:00Z"),
    ):
        officer = fixtures.create_officer(
            api, world["patrol_unit_id"], badge_number=badge, full_name=name
        )
        complaint = fixtures.file_supervisor_complaint(
            api, world, narrative=f"Neglect of duty, {name}.", incident_datetime=incident
        )
        fixtures.attach_allegation(
            api,
            world,
            complaint["id"],
            subject_officer_id=officer["id"],
            allegation_type="NEGLECT_OF_DUTY",
            offense_class="C",
        )
        investigation = fixtures.open_investigation(api, world, complaint["id"])
        assigned = fixtures.assign_investigation(
            api, world, investigation["id"], investigation["version"], world["inv_a_id"]
        )
        people[key] = {
            "officer_id": officer["id"],
            "c_id": complaint["id"],
            "i_id": investigation["id"],
            "assignment_count": assigned["assignment_count"],
        }
    return people


def book(api, world, investigation_id, officer_id, start, end):
    """Ask for one session in the standing room with notice served at the base clock."""
    return api.schedule_interview_session(
        investigation_id,
        factories.interview_session_payload(
            officer_id,
            world["room1_id"],
            scheduled_start=start,
            scheduled_end=end,
            notice_served_at="2026-08-01T00:00:00Z",
            representation_status="REP_PRESENT",
        ),
        world["inv_a_headers"],
    )


def test_separation_blocks_the_booking_that_relief_from_duty_allows(api, world):
    """One officer's employment row decides whether a different entity may be scheduled.

    PRD: A subject officer whose `employment_status` is `SEPARATED` can no longer be compelled to attend and the request is refused with `ERR_OFFICER_SEPARATED`; an officer who is `ACTIVE`, `SUSPENDED` or `RELIEVED_OF_DUTY` remains interviewable.
    PRD: An officer who is `ACTIVE` or `SUSPENDED` may be moved to `RELIEVED_OF_DUTY`, and that officer remains fully interviewable and remains an eligible subject of discipline — relief from duty is a precaution, not an exit.
    Design: Difficulty/cross_entity_state_dependency/interview_scheduling_and_hold_read_the_subject_officer_employment_dimension
    """
    people = three_files_against_three_officers(api, world)
    assert [entry["assignment_count"] for entry in people.values()] == [1, 1, 1]
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=3
    )

    separated = fixtures.separate_officer(api, people["tan"]["officer_id"], "SEPARATED")
    assert separated["employment_status"] == "SEPARATED"

    refused = book(
        api,
        world,
        people["tan"]["i_id"],
        people["tan"]["officer_id"],
        "2026-08-10T15:00:00Z",
        "2026-08-10T16:00:00Z",
    )

    validate_error(refused, "ERR_OFFICER_SEPARATED", 409)
    assert fixtures.read_investigation(api, people["tan"]["i_id"], world["cmdr_headers"])["status"] == "ASSIGNED"

    relieved = fixtures.separate_officer(api, people["rossi"]["officer_id"], "RELIEVED_OF_DUTY")
    assert relieved["employment_status"] == "RELIEVED_OF_DUTY"

    accepted = get_success_data(
        book(
            api,
            world,
            people["rossi"]["i_id"],
            people["rossi"]["officer_id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T10:00:00Z",
        )
    )

    assert accepted["status"] == "SCHEDULED"
    assert accepted["subject_officer_id"] == people["rossi"]["officer_id"]
    assert fixtures.read_investigation(api, people["rossi"]["i_id"], world["cmdr_headers"])["status"] == "IN_PROGRESS"


def test_a_scheduled_session_becomes_unholdable_when_its_subject_separates(api, world):
    """The session row never changes, yet the hold is refused and the relieved officer's is not.

    PRD: The subject officer must not be `SEPARATED`, otherwise `ERR_OFFICER_SEPARATED`.
    PRD: Any officer who is not already `SEPARATED` may be moved to `SEPARATED`, at which point the officer stops being an eligible investigator candidate and stops being interviewable, while every open investigation already assigned to that officer is left exactly as it was and the caseload ledger is not adjusted.
    Design: Difficulty/cross_entity_state_dependency/interview_scheduling_and_hold_read_the_subject_officer_employment_dimension
    """
    people = three_files_against_three_officers(api, world)
    fixtures.separate_officer(api, people["rossi"]["officer_id"], "RELIEVED_OF_DUTY")
    rossi_session = get_success_data(
        book(
            api,
            world,
            people["rossi"]["i_id"],
            people["rossi"]["officer_id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T10:00:00Z",
        )
    )
    sant_session = get_success_data(
        book(
            api,
            world,
            people["sant"]["i_id"],
            people["sant"]["officer_id"],
            "2026-08-10T13:00:00Z",
            "2026-08-10T14:00:00Z",
        )
    )
    assert sant_session["status"] == "SCHEDULED"

    fixtures.separate_officer(api, people["sant"]["officer_id"], "SEPARATED")
    fixtures.set_clock(api, "2026-08-10T13:00:00Z")

    refused = api.hold_interview_session(
        sant_session["id"],
        factories.hold_payload("Attempted interview of a separated officer."),
        world["inv_a_headers"],
    )

    validate_error(refused, "ERR_OFFICER_SEPARATED", 409)
    stalled = fixtures.read_session(api, sant_session["id"], world["inv_a_headers"])
    assert stalled["status"] == "SCHEDULED"
    assert stalled["held_at"] is None
    assert fixtures.read_investigation(api, people["sant"]["i_id"], world["cmdr_headers"])["interview_held_count"] == 0
    assert_officer_ledgers(
        fixtures.read_officer(api, world["inv_a_id"], world["cmdr_headers"]), open_case_load=3
    )

    held = fixtures.hold_session(
        api, world, rossi_session["id"], interview_summary="Interview of the relieved officer held."
    )

    assert held["status"] == "HELD"
    assert_instant(held["held_at"], "2026-08-10T13:00:00Z")
    assert fixtures.read_investigation(api, people["rossi"]["i_id"], world["cmdr_headers"])["interview_held_count"] == 1


def two_subjects_and_one_anchor_session(api):
    """A joint file against Vance and Webb, with Vance already booked from nine to ten."""
    world = fixtures.seed_reference_data(api, room_capacity=3)
    webb = fixtures.create_officer(
        api, world["patrol_unit_id"], badge_number="PN-801", full_name="Officer Webb"
    )
    complaint = fixtures.file_supervisor_complaint(
        api, world, narrative="Two officers named in one incident."
    )
    fixtures.attach_allegation(
        api, world, complaint["id"], allegation_type="NEGLECT_OF_DUTY", offense_class="C"
    )
    fixtures.attach_allegation(
        api,
        world,
        complaint["id"],
        subject_officer_id=webb["id"],
        allegation_type="NEGLECT_OF_DUTY",
        offense_class="C",
        narrative="Reports missing, Webb.",
    )
    investigation = fixtures.open_investigation(api, world, complaint["id"])
    fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], world["inv_a_id"]
    )
    anchor = get_success_data(
        book(
            api,
            world,
            investigation["id"],
            world["subj_id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T10:00:00Z",
        )
    )
    world.update(
        {
            "webb_id": webb["id"],
            "c_id": complaint["id"],
            "i1_id": investigation["id"],
            "anchor_id": anchor["id"],
            "anchor": anchor,
        }
    )
    return world


def test_a_sixty_minute_gap_conflicts_on_either_side_of_the_existing_session(api):
    """Eleven to twelve and seven to eight both touch the buffered window's endpoints.

    PRD: The candidate window is widened by that buffer at both ends and treated as a **closed** interval: the widened window runs from sixty minutes before the proposed start to sixty minutes after the proposed end, endpoints included.
    PRD: Because both ends are inclusive, a gap of exactly sixty minutes between the end of one session and the start of the next **is** a conflict — the widened window's left endpoint lands precisely on the earlier session's end instant, and touching counts.
    Design: Difficulty/resource_temporal_overlap/officer_rest_buffer_treats_a_sixty_minute_gap_as_overlap_on_both_sides
    """
    world = two_subjects_and_one_anchor_session(api)
    assert world["anchor"]["status"] == "SCHEDULED"

    after = book(
        api,
        world,
        world["i1_id"],
        world["subj_id"],
        "2026-08-10T11:00:00Z",
        "2026-08-10T12:00:00Z",
    )
    validate_error(after, "ERR_OFFICER_REST_BUFFER_CONFLICT", 409)

    before = book(
        api,
        world,
        world["i1_id"],
        world["subj_id"],
        "2026-08-10T07:00:00Z",
        "2026-08-10T08:00:00Z",
    )
    validate_error(before, "ERR_OFFICER_REST_BUFFER_CONFLICT", 409)

    sessions, _ = fixtures.rows(
        api.list_interview_sessions(world["inv_a_headers"], {"investigation_id": world["i1_id"]})
    )
    assert [row["id"] for row in sessions] == [world["anchor_id"]]
    assert sessions[0]["status"] == "SCHEDULED"


def test_a_sixty_one_minute_gap_is_accepted_and_the_buffer_is_per_officer(api):
    """One further minute on either side clears the cushion, and Webb takes the refused window.

    PRD: A gap of sixty-one minutes is accepted.
    PRD: Every other session of the same subject officer whose status is `SCHEDULED` or `POSTPONED` contributes its own closed interval running from its `scheduled_start` to its `scheduled_end`; sessions in `HELD` or `CANCELLED` contribute nothing at all.
    Design: Difficulty/resource_temporal_overlap/officer_rest_buffer_treats_a_sixty_minute_gap_as_overlap_on_both_sides
    """
    world = two_subjects_and_one_anchor_session(api)

    earlier = get_success_data(
        book(
            api,
            world,
            world["i1_id"],
            world["subj_id"],
            "2026-08-10T06:59:00Z",
            "2026-08-10T07:59:00Z",
        )
    )
    later = get_success_data(
        book(
            api,
            world,
            world["i1_id"],
            world["subj_id"],
            "2026-08-10T11:01:00Z",
            "2026-08-10T12:01:00Z",
        )
    )
    webb_session = get_success_data(
        book(
            api,
            world,
            world["i1_id"],
            world["webb_id"],
            "2026-08-10T11:00:00Z",
            "2026-08-10T12:00:00Z",
        )
    )

    assert earlier["status"] == "SCHEDULED"
    assert later["status"] == "SCHEDULED"
    assert webb_session["status"] == "SCHEDULED"
    assert webb_session["subject_officer_id"] == world["webb_id"]
    assert_two_dp(webb_session["notice_hours"], 227, label="notice_hours")

    sessions, _ = fixtures.rows(
        api.list_interview_sessions(world["inv_a_headers"], {"investigation_id": world["i1_id"]})
    )
    assert len(sessions) == 4
    assert {row["id"] for row in sessions} == {
        world["anchor_id"],
        earlier["id"],
        later["id"],
        webb_session["id"],
    }
    assert [row["status"] for row in sessions] == ["SCHEDULED"] * 4


def book_in_room(api, world, room_id, officer_id, start, end):
    """Ask for one session in a named room, always with ample notice."""
    return api.schedule_interview_session(
        world["i1_id"],
        factories.interview_session_payload(
            officer_id,
            room_id,
            scheduled_start=start,
            scheduled_end=end,
            notice_served_at="2026-08-01T00:00:00Z",
            representation_status="REP_PRESENT",
        ),
        world["inv_a_headers"],
    )


def four_subjects_and_a_room_of_capacity_two(api):
    """One joint file against Alder, Blake, Cross and Doerr, and an empty two-seat room."""
    world = fixtures.seed_reference_data(api)
    room = fixtures.create_hearing_room(api, room_name="Interview 4", concurrent_capacity=2)
    complaint = fixtures.file_supervisor_complaint(
        api, world, narrative="Four officers named in one incident."
    )
    people = {}
    for key, badge, name in (
        ("alder", "PN-901", "Officer Alder"),
        ("blake", "PN-902", "Officer Blake"),
        ("cross", "PN-903", "Officer Cross"),
        ("doerr", "PN-904", "Officer Doerr"),
    ):
        officer = fixtures.create_officer(
            api, world["patrol_unit_id"], badge_number=badge, full_name=name
        )
        fixtures.attach_allegation(
            api,
            world,
            complaint["id"],
            subject_officer_id=officer["id"],
            allegation_type="NEGLECT_OF_DUTY",
            offense_class="C",
            narrative=f"Reports missing, {name}.",
        )
        people[key] = officer["id"]
    investigation = fixtures.open_investigation(api, world, complaint["id"])
    fixtures.assign_investigation(
        api, world, investigation["id"], investigation["version"], world["inv_a_id"]
    )
    world.update({"c_id": complaint["id"], "i1_id": investigation["id"], "room4_id": room["id"], **people})
    return world


def two_overlapping_bookings(api, world):
    """Nine to eleven and ten to twelve, which together fill the room at half past ten."""
    alder = get_success_data(
        book_in_room(
            api, world, world["room4_id"], world["alder"], "2026-08-12T09:00:00Z", "2026-08-12T11:00:00Z"
        )
    )
    blake = get_success_data(
        book_in_room(
            api, world, world["room4_id"], world["blake"], "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z"
        )
    )
    return alder, blake


def test_a_third_overlapping_booking_exhausts_a_room_of_capacity_two(api):
    """One overlap is admitted because one is fewer than two; two overlaps are not.

    PRD: The booking is accepted only when that count is **strictly less than** the room's `concurrent_capacity`.
    PRD: A room with capacity 2 already holding one overlapping session accepts the new booking, because 1 is less than 2; the same room holding two overlapping sessions refuses a third with `ERR_ROOM_CAPACITY_EXCEEDED`, because 2 is not less than 2.
    Design: Difficulty/resource_temporal_overlap/room_capacity_counts_half_open_overlaps_and_admits_back_to_back_bookings
    """
    world = four_subjects_and_a_room_of_capacity_two(api)

    alder, blake = two_overlapping_bookings(api, world)

    assert alder["status"] == "SCHEDULED"
    assert alder["hearing_room_id"] == world["room4_id"]
    assert blake["status"] == "SCHEDULED"

    refused = book_in_room(
        api, world, world["room4_id"], world["cross"], "2026-08-12T10:30:00Z", "2026-08-12T11:30:00Z"
    )

    validate_error(refused, "ERR_ROOM_CAPACITY_EXCEEDED", 409)
    booked, _ = fixtures.rows(
        api.list_interview_sessions(world["inv_a_headers"], {"hearing_room_id": world["room4_id"]})
    )
    assert [row["id"] for row in booked] == [alder["id"], blake["id"]]
    cross_sessions, _ = fixtures.rows(
        api.list_interview_sessions(world["inv_a_headers"], {"subject_officer_id": world["cross"]})
    )
    assert cross_sessions == []


def test_bookings_that_only_touch_a_boundary_instant_do_not_count(api):
    """Eleven to twelve overlaps one session, and twelve to thirteen overlaps none.

    PRD: Two half-open intervals intersect when the first begins strictly before the second ends and the second begins strictly before the first ends, which means two bookings that merely share a single boundary instant do not intersect at all: a session ending at eleven and another starting at eleven yield a count of zero.
    Design: Difficulty/resource_temporal_overlap/room_capacity_counts_half_open_overlaps_and_admits_back_to_back_bookings
    """
    world = four_subjects_and_a_room_of_capacity_two(api)
    alder, blake = two_overlapping_bookings(api, world)

    refused = book_in_room(
        api, world, world["room4_id"], world["cross"], "2026-08-12T10:30:00Z", "2026-08-12T11:30:00Z"
    )
    validate_error(refused, "ERR_ROOM_CAPACITY_EXCEEDED", 409)

    cross = get_success_data(
        book_in_room(
            api, world, world["room4_id"], world["cross"], "2026-08-12T11:00:00Z", "2026-08-12T12:00:00Z"
        )
    )
    doerr = get_success_data(
        book_in_room(
            api, world, world["room4_id"], world["doerr"], "2026-08-12T12:00:00Z", "2026-08-12T13:00:00Z"
        )
    )

    assert cross["status"] == "SCHEDULED"
    assert_instant(cross["scheduled_start"], "2026-08-12T11:00:00Z")
    assert doerr["status"] == "SCHEDULED"
    assert_instant(doerr["scheduled_start"], "2026-08-12T12:00:00Z")

    booked, _ = fixtures.rows(
        api.list_interview_sessions(world["inv_a_headers"], {"hearing_room_id": world["room4_id"]})
    )
    assert [row["id"] for row in booked] == [alder["id"], blake["id"], cross["id"], doerr["id"]]
    assert [row["status"] for row in booked] == ["SCHEDULED"] * 4
    assert fixtures.read_investigation(api, world["i1_id"], world["cmdr_headers"])["status"] == "IN_PROGRESS"
    cross_sessions, _ = fixtures.rows(
        api.list_interview_sessions(world["inv_a_headers"], {"subject_officer_id": world["cross"]})
    )
    assert [row["id"] for row in cross_sessions] == [cross["id"]]
