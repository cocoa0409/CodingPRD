"""Two deliberately reachable pairs of rejections, where the ladder of section 2.9
decides which of the two the caller is entitled to see."""

from test_helpers import ApiErrorId, api_client, validate_error
from test_helpers.assertions import assert_instant_equals
from test_helpers.factories import reschedule_ring_block_payload
from test_helpers.fixtures import (
    SS_HEADERS,
    apply_for_show,
    approve_show,
    attach_judge,
    close_entries,
    confirm_entry,
    confirmed_slot,
    enter_dog,
    offer_class,
    open_day,
    plan_ring_block,
    publish_ring_block,
    read_club,
    read_ring_block,
    read_show,
    read_show_version,
    record_reading,
    register_club,
    register_dog,
    register_handler,
    register_judge,
    set_clock,
    submit_show,
)
from test_helpers.test_users import make_club_officer_headers


def _outdoor_show_with_two_published_blocks_in_one_ring():
    """A conformation block and a performance block published back to back in ring 1.

    Ring 1 holds a three-dog breed class from 09:00 to 09:08 and a two-dog
    obedience class from 09:30 to 09:38, so a reschedule of the later block onto
    09:05 collides with the earlier one.
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()
    handler = register_handler()
    judge_one = register_judge()
    judge_two = register_judge(judge_number="J-78", full_name="Vera Lund")

    show = apply_for_show(club, show_type="COMBINED", outdoor_venue=True)
    submit_show(show, club)
    approve_show(show)

    slot_one = confirmed_slot(show, judge_one, panel_role="BREED_JUDGE")
    slot_two = confirmed_slot(show, judge_two, panel_role="PERFORMANCE_JUDGE")

    breed_class = attach_judge(
        offer_class(show, class_level="BREED", class_code="GR-OPEN-D"), slot_one
    )
    performance_class = attach_judge(
        offer_class(
            show, class_level="PERFORMANCE", discipline="OBEDIENCE",
            class_code="OB-NOVICE-A",
        ),
        slot_two,
    )

    dogs = [register_dog(handler, index=i) for i in range(5)]
    for index in range(3):
        confirm_entry(enter_dog(show, breed_class, dogs[index], handler))
    for index in (3, 4):
        confirm_entry(enter_dog(show, performance_class, dogs[index], handler))
    close_entries(breed_class)
    close_entries(performance_class)

    block_one = plan_ring_block(
        show, breed_class, slot_one,
        ring_number=1, block_start_at="2026-09-12T09:00:00Z",
    )
    block_two = plan_ring_block(
        show, performance_class, slot_two,
        ring_number=1, block_start_at="2026-09-12T09:30:00Z",
    )
    publish_ring_block(block_one)
    publish_ring_block(block_two)
    open_day(show)

    return {
        "show": show,
        "block_one": block_one,
        "block_two": block_two,
    }


def test_a_reschedule_that_is_both_heat_blocked_and_overlapping_reports_the_heat_error():
    """The welfare band outranks the temporal band on a doubly invalid reschedule.

    PRD: "The heat restriction applies here exactly as it does to publication, and
    because the welfare band outranks the temporal band, a reschedule that is both
    heat-blocked and overlapping reports `ERR_HEAT_RESTRICTION_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/heat_safety_beats_ring_overlap_on_reschedule
    """
    context = _outdoor_show_with_two_published_blocks_in_one_ring()
    show = context["show"]

    record_reading(show, 29.0, 65)
    pinned_version = read_show_version(show)

    response = api_client.reschedule_ring_block(
        context["block_two"]["id"],
        reschedule_ring_block_payload("2026-09-12T09:05:00Z", pinned_version),
        SS_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_HEAT_RESTRICTION_ACTIVE, 409)


def test_the_rejected_reschedule_leaves_the_published_block_exactly_where_it_was():
    """Nothing about the block moves, and the advisory that blocked it is RED.

    PRD: "an index of 32.0 degrees or higher is `RED`, an index of 26.0 degrees or
    higher but below 32.0 is `AMBER`, and anything below 26.0 is `GREEN`."

    Design: Difficulty/priority_pair_validation_conflict/heat_safety_beats_ring_overlap_on_reschedule
    """
    context = _outdoor_show_with_two_published_blocks_in_one_ring()
    show = context["show"]

    record_reading(show, 29.0, 65)
    api_client.reschedule_ring_block(
        context["block_two"]["id"],
        reschedule_ring_block_payload("2026-09-12T09:05:00Z", read_show_version(show)),
        SS_HEADERS,
    )

    block = read_ring_block(context["block_two"])
    assert_instant_equals(
        block["block_start_at"], "2026-09-12T09:30:00Z", "block_start_at"
    )
    assert_instant_equals(
        block["block_end_at"], "2026-09-12T09:38:00Z", "block_end_at"
    )
    assert block["block_status"] == "PUBLISHED"
    assert read_show(show)["current_advisory_level"] == "RED"


def _club_with_an_exhausted_allowance():
    """Two approved shows against an allowance of two, plus a third left in DRAFT."""
    set_clock("2026-08-10T09:00:00Z")
    club = register_club(annual_event_allowance=2)

    first = apply_for_show(club)
    submit_show(first, club)
    approve_show(first)

    second = apply_for_show(
        club,
        show_name="Winter Classic",
        show_date="2026-11-14",
        entry_open_at="2026-10-05T00:00:00Z",
        entry_close_at="2026-11-01T23:59:59Z",
    )
    submit_show(second, club)
    approve_show(second)

    third = apply_for_show(
        club,
        show_name="Spring Classic",
        show_date="2027-03-20",
        entry_open_at="2027-02-05T00:00:00Z",
        entry_close_at="2027-03-01T23:59:59Z",
    )

    return {"club": club, "first": first, "third": third}


def test_two_approvals_exhaust_an_allowance_of_two_and_block_the_next_submission():
    """The fiscal rung is proved reachable on its own before it is combined.

    PRD: "The club's `events_approved_count` is strictly below its
    `annual_event_allowance` when a show application is submitted, else
    `ERR_CLUB_ALLOWANCE_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/show_state_beats_club_allowance_on_submit
    """
    context = _club_with_an_exhausted_allowance()
    club = context["club"]

    assert read_club(club)["events_approved_count"] == 2

    response = api_client.submit_show(
        context["third"]["id"], make_club_officer_headers(club["id"])
    )
    validate_error(response, ApiErrorId.ERR_CLUB_ALLOWANCE_EXHAUSTED, 409)


def test_resubmitting_an_approved_show_under_the_same_exhausted_allowance_reports_the_state_error():
    """Both rungs are violated at once, and the earlier state rung decides.

    PRD: "the checks below are evaluated in the stated order, and the first
    violated check decides the response. No later check is evaluated once one has
    failed."

    Design: Difficulty/priority_pair_validation_conflict/show_state_beats_club_allowance_on_submit
    """
    context = _club_with_an_exhausted_allowance()
    club = context["club"]

    response = api_client.submit_show(
        context["first"]["id"], make_club_officer_headers(club["id"])
    )
    validate_error(response, ApiErrorId.ERR_SHOW_NOT_IN_DRAFT, 409)


def test_neither_rejected_submission_disturbs_the_two_shows_it_touched():
    """A refused submission is inert: no status moves and no revision is counted.

    PRD: "`revision_count` is never decreased — it is a permanent count of how many
    times the application came back — so a show that has been returned twice and
    approved on the third pass keeps a `revision_count` of 2 forever."

    Design: Difficulty/priority_pair_validation_conflict/show_state_beats_club_allowance_on_submit
    """
    context = _club_with_an_exhausted_allowance()
    club = context["club"]
    officer = make_club_officer_headers(club["id"])

    api_client.submit_show(context["third"]["id"], officer)
    api_client.submit_show(context["first"]["id"], officer)

    assert read_show(context["third"])["status"] == "DRAFT"
    first = read_show(context["first"])
    assert first["status"] == "APPROVED"
    assert first["revision_count"] == 0
