"""Difficulty queue: resource_temporal_overlap.

Jurisdiction forums use half-open [start, end) overlap; one moderator's
forums use a >= 24h end-to-start buffer.  Different resources, different
geometry.
"""
from test_helpers import (
    ApiErrorId,
    add_candidate_contest,
    add_forum,
    fresh_league,
    get_success_data,
    make_forum_payload,
    make_jurisdiction_payload,
    move_to_questionnaire_phase,
    validate_error,
    validate_success,
)


def _two_contests_in_phase(api, ctx):
    c1 = add_candidate_contest(api, ctx, office_name="Mayor")
    c2 = add_candidate_contest(api, ctx, office_name="Clerk")
    move_to_questionnaire_phase(api, ctx, c1["id"])
    move_to_questionnaire_phase(api, ctx, c2["id"])
    return c1, c2


def test_forum_overlap_half_open_interval_and_adjacency(api):
    """PRD §3.7: "Within one jurisdiction, the new forum's half-open
    interval — inclusive of `scheduled_start`, exclusive of `scheduled_end`
    — may not overlap any other forum of that jurisdiction in `PLANNED` or
    `CONFIRMED` status, though two forums may legitimately abut, one ending
    at exactly the moment the other begins (`ERR_FORUM_TIME_OVERLAP`)."

    Design: Difficulty/resource_temporal_overlap/jurisdiction_forum_overlap_half_open_adjacency
    """
    ctx = fresh_league(api, moderators=("Mod One", "Mod Two", "Mod Three"))
    c1, c2 = _two_contests_in_phase(api, ctx)
    m1, m2, m3 = (ctx["moderators"][i][0]["id"] for i in range(3))

    f1 = add_forum(api, ctx, c1["id"], m1,
                   start="2026-10-10T10:00:00Z", end="2026-10-10T12:00:00Z")
    assert f1["status"] == "PLANNED"

    # Adjacent (start == prior end): allowed under half-open semantics.
    f2 = add_forum(api, ctx, c2["id"], m2,
                   start="2026-10-10T12:00:00Z", end="2026-10-10T14:00:00Z")
    assert f2["status"] == "PLANNED"

    # 11:30-13:00 intersects both existing intervals in this jurisdiction.
    resp = api.create_forum(
        c2["id"],
        make_forum_payload(scheduled_start="2026-10-10T11:30:00Z",
                           scheduled_end="2026-10-10T13:00:00Z",
                           moderator_volunteer_id=m3),
        ctx["coordinator_h"],
    )
    validate_error(resp, ApiErrorId.ERR_FORUM_TIME_OVERLAP)
    assert resp.status_code == 422


def test_overlap_rule_is_scoped_to_one_jurisdiction(api):
    """PRD §3.7: "Within one jurisdiction, the new forum's half-open
    interval — inclusive of `scheduled_start`, exclusive of `scheduled_end`
    — may not overlap any other forum of that jurisdiction in `PLANNED` or
    `CONFIRMED` status" — the same interval in a different jurisdiction is
    outside the rule's scope.

    Design: Difficulty/resource_temporal_overlap/jurisdiction_forum_overlap_half_open_adjacency
    """
    ctx = fresh_league(api, moderators=("Mod One", "Mod Two"))
    jur2 = get_success_data(
        api.create_jurisdiction(
            ctx["cycle"]["id"],
            make_jurisdiction_payload(jurisdiction_name="Shelbyville",
                                      fips_code="06002"),
            ctx["admin_h"],
        )
    )
    c1 = add_candidate_contest(api, ctx, office_name="Mayor")
    move_to_questionnaire_phase(api, ctx, c1["id"])
    c3 = get_success_data(
        api.create_contest(
            jur2["id"],
            {"kind": "CANDIDATE_RACE", "office_name": "Mayor",
             "filing_deadline": "2026-09-15T17:00:00Z"},
            ctx["coordinator_h"],
        )
    )
    move_to_questionnaire_phase(api, ctx, c3["id"])

    add_forum(api, ctx, c1["id"], ctx["moderators"][0][0]["id"],
              start="2026-10-10T10:00:00Z", end="2026-10-10T12:00:00Z")
    # Same clock interval, different jurisdiction and different moderator.
    f2 = add_forum(api, ctx, c3["id"], ctx["moderators"][1][0]["id"],
                   start="2026-10-10T10:00:00Z", end="2026-10-10T12:00:00Z")
    assert f2["status"] == "PLANNED"


def test_moderator_buffer_twenty_two_hours_fails_twenty_four_passes(api):
    """PRD §3.7: "between any two forums of the same moderator in `PLANNED`
    or `CONFIRMED` status, the gap measured from the earlier forum's end to
    the later forum's start must be at least 24 hours, with a gap of exactly
    24 hours allowed (`ERR_MODERATOR_BUFFER_VIOLATION`)."

    Design: Difficulty/resource_temporal_overlap/moderator_twenty_four_hour_buffer_gap
    """
    ctx = fresh_league(api, moderators=("Mod One",))
    contest = add_candidate_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    mod_id = ctx["moderators"][0][0]["id"]
    add_forum(api, ctx, contest["id"], mod_id,
              start="2026-10-10T10:00:00Z", end="2026-10-10T12:00:00Z")

    # 22-hour gap: 2026-10-11T10:00 is 22h after the first forum's end.
    resp = api.create_forum(
        contest["id"],
        make_forum_payload(scheduled_start="2026-10-11T10:00:00Z",
                           scheduled_end="2026-10-11T12:00:00Z",
                           moderator_volunteer_id=mod_id),
        ctx["coordinator_h"],
    )
    validate_error(resp, ApiErrorId.ERR_MODERATOR_BUFFER_VIOLATION)
    assert resp.status_code == 422

    # Exactly 24 hours: allowed (the comparison is >=, not strict-greater).
    f3 = add_forum(api, ctx, contest["id"], mod_id,
                   start="2026-10-11T12:00:00Z", end="2026-10-11T13:00:00Z")
    assert f3["status"] == "PLANNED"


def test_buffer_rule_only_binds_the_same_moderator(api):
    """PRD §3.7: "between any two forums of the same moderator in `PLANNED`
    or `CONFIRMED` status, the gap measured from the earlier forum's end to
    the later forum's start must be at least 24 hours, with a gap of exactly
    24 hours allowed (`ERR_MODERATOR_BUFFER_VIOLATION`)."  A different
    moderator's forum 22 hours later is outside the rule.

    Design: Difficulty/resource_temporal_overlap/moderator_twenty_four_hour_buffer_gap
    """
    ctx = fresh_league(api, moderators=("Mod One", "Mod Two"))
    contest = add_candidate_contest(api, ctx)
    move_to_questionnaire_phase(api, ctx, contest["id"])
    add_forum(api, ctx, contest["id"], ctx["moderators"][0][0]["id"],
              start="2026-10-10T10:00:00Z", end="2026-10-10T12:00:00Z")
    f2 = add_forum(api, ctx, contest["id"], ctx["moderators"][1][0]["id"],
                   start="2026-10-11T10:00:00Z", end="2026-10-11T12:00:00Z")
    assert f2["status"] == "PLANNED"
