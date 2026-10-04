"""Speech contests: eligibility, judging, ballots and ranking."""
from test_helpers import (
    ApiErrorId,
    close_dues_cycle,
    create_club_contest,
    create_entry,
    create_organizing_club,
    enroll_membership,
    enter_contest,
    get_club,
    get_contest,
    get_entry,
    get_success_data,
    make_district_director_headers,
    record_ballot,
    setup_club_with_paid_members,
    setup_judge_member,
    validate_error,
)
from test_helpers.constants import FIRST_CYCLE_CLOSE_AT, JOIN_DATE


def _setup_contest_with_two_entries() -> tuple:
    """Club + two paid members + a SCHEDULED club contest with two entries, plus a judge."""
    club, memberships = setup_club_with_paid_members(2, prefix="c")
    _, judge_member_id = setup_judge_member(prefix="j")
    contest = create_club_contest(club["id"], judge_member_id)
    entries = [
        create_entry(contest["id"], memberships[index]["member_id"], club["id"], f"Speech {index + 1}")
        for index in range(2)
    ]
    return club, memberships, contest, entries, judge_member_id


def test_ballot_total_uses_the_weighted_blend(api, whq_headers):
    """PRD §3.8: "The ballot's `total_score` is a weighted blend: the content score
    carries half the weight, the delivery score three tenths, and the language score
    the remaining two tenths, and the blended result is rounded to a whole number
    using round half up."

    Design: Corner/calculations/judge_ballot_total_weighted_rounding
    """
    club, memberships, contest, entries, judge_member_id = _setup_contest_with_two_entries()

    response = record_ballot(entries[0]["id"], judge_member_id, content_score=90, delivery_score=80, language_score=70)
    entry = get_success_data(response, 200)
    assert entry["ballot_count"] == 1
    assert entry["judge_score_total"] == 83, "90*0.5 + 80*0.3 + 70*0.2 = 45 + 24 + 14"
    assert entry["status"] == "ENTERED", "three ballots are required to reach JUDGED"


def test_contest_cannot_complete_without_a_judged_entry(api, whq_headers):
    """PRD §3.8: "The candidate set is the contest's entries in status `JUDGED`; a
    contest with no judged entry is refused with `ERR_NO_JUDGED_ENTRIES`, and every
    judged entry must carry at least 3 ballots before the contest may complete."

    Design: Corner/calculations/contest_ranking_candidates_are_judged_entries_only
    """
    club, memberships, contest, entries, judge_member_id = _setup_contest_with_two_entries()
    record_ballot(entries[0]["id"], judge_member_id)
    record_ballot(entries[1]["id"], judge_member_id)

    response = api.complete_contest(contest["id"], make_district_director_headers(judge_member_id))
    validate_error(response, ApiErrorId.ERR_NO_JUDGED_ENTRIES)

    after = get_contest(contest["id"])
    assert after["status"] == "IN_PROGRESS", "the first ballot moved the contest to IN_PROGRESS"
    assert after["winner_entry_id"] is None


def test_second_ballot_from_the_same_judge_is_refused(api, whq_headers):
    """PRD §3.8: "A judge may ballot an entry only once, and a second ballot from the
    same judge is refused with `ERR_DUPLICATE_BALLOT`."

    Design: Corner/validations/duplicate_ballot_by_same_judge_rejected
    """
    club, memberships, contest, entries, judge_member_id = _setup_contest_with_two_entries()
    first = get_success_data(record_ballot(entries[0]["id"], judge_member_id), 200)
    assert first["ballot_count"] == 1

    response = record_ballot(
        entries[0]["id"], judge_member_id, content_score=70, delivery_score=70, language_score=70
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_BALLOT)

    after = get_entry(entries[0]["id"])
    assert after["ballot_count"] == 1, "the refused ballot must not be recorded"
    assert after["judge_score_total"] == 83


def test_judge_holding_a_membership_at_the_entrys_club_is_refused(api, whq_headers):
    """PRD §3.8: "The judge must be independent of the entry: a ballot from the
    competing member, or from anyone who holds a membership at the entry's club, is
    refused with `ERR_JUDGE_CONFLICT`."

    Design: Corner/validations/judge_from_same_club_rejected
    """
    club, memberships = setup_club_with_paid_members(2, prefix="c")
    contest = create_club_contest(club["id"], memberships[1]["member_id"])
    entry = create_entry(contest["id"], memberships[0]["member_id"], club["id"])

    response = record_ballot(entry["id"], memberships[1]["member_id"])
    validate_error(response, ApiErrorId.ERR_JUDGE_CONFLICT)
    assert get_entry(entry["id"])["ballot_count"] == 0


def test_entry_is_refused_once_the_contest_has_started(api, whq_headers):
    """PRD §3.8: "Entries are also accepted only while the contest is still
    `SCHEDULED`; once it has started or finished, a new entry is refused with
    `ERR_CONTEST_NOT_OPEN`."

    Design: Corner/errors/contest_entry_rejected_after_contest_starts
    """
    club, memberships, contest, entries, judge_member_id = _setup_contest_with_two_entries()
    record_ballot(entries[0]["id"], judge_member_id)
    assert get_contest(contest["id"])["status"] == "IN_PROGRESS", (
        "the first ballot recorded anywhere in the contest starts it"
    )

    response = enter_contest(contest["id"], memberships[1]["member_id"], club["id"], "Second Speaker")
    validate_error(response, ApiErrorId.ERR_CONTEST_NOT_OPEN)
    assert get_contest(contest["id"])["entry_count"] == 2, (
        "the two live entries still count; the refused entry adds nothing"
    )


def test_entry_through_a_club_that_left_good_standing_is_refused(api, whq_headers):
    """PRD §3.8: "The claiming club must be in `GOOD` standing, and an entry through a
    club on `PROBATION` or in `NOT_IN_GOOD_STANDING` is refused with
    `ERR_CLUB_NOT_IN_GOOD_STANDING`."

    Design: Difficulty/cross_entity_state_dependency/contest_entry_requires_club_good_standing
    """
    club, membership, member_id, other_club, contest, other_contest = _setup_two_clubs_one_member()
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)
    assert get_club(club["id"])["good_standing"] == "NOT_IN_GOOD_STANDING"

    response = enter_contest(contest["id"], member_id, club["id"], "The Long Road")
    validate_error(response, ApiErrorId.ERR_CLUB_NOT_IN_GOOD_STANDING)


def test_entry_through_a_club_still_in_good_standing_succeeds(api, whq_headers):
    """PRD §3.8: "The claiming club must be in `GOOD` standing, and an entry through a club on `PROBATION` or in `NOT_IN_GOOD_STANDING` is refused with `ERR_CLUB_NOT_IN_GOOD_STANDING`."

    Design: Difficulty/cross_entity_state_dependency/contest_entry_requires_club_good_standing
    """
    club, membership, member_id, other_club, contest, other_contest = _setup_two_clubs_one_member()
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)
    assert get_club(club["id"])["good_standing"] == "NOT_IN_GOOD_STANDING"
    assert get_club(other_club["id"])["good_standing"] == "GOOD", "the second club is untouched"

    entry = get_success_data(enter_contest(other_contest["id"], member_id, other_club["id"]), 201)
    assert entry["status"] == "ENTERED"


def _setup_two_clubs_one_member() -> tuple:
    """One member with a paid membership in two clubs, each running a SCHEDULED contest."""
    club = create_organizing_club()
    other_club = create_organizing_club(
        club_name="Lakeview Speakers", division_code="D", area_code="D-1", venue_name="Lakeview Hall"
    )
    membership = enroll_membership(
        club["id"], full_name="Ada Lovelace", email="ada@example.org", pay_dues=True
    )
    enroll_membership(
        other_club["id"],
        member_id=membership["member_id"],
        join_date=JOIN_DATE,
        first_time_member=False,
        pay_dues=True,
    )
    contest = create_club_contest(club["id"], membership["member_id"])
    other_contest = create_club_contest(
        other_club["id"], membership["member_id"], division_code="D", area_code="D-1"
    )
    return club, membership, membership["member_id"], other_club, contest, other_contest
