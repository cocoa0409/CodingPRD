"""Determination visits: conclude guards, NO_SHOW semantics, age-appropriate
methods, and the half-open overlap rule for a team's schedule.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    conclude_visit_completed,
    conclude_visit_no_show,
    create_approved_wish,
    create_chapter,
    create_conclude_completed_payload,
    create_volunteer_pair,
    create_wish_team,
    create_wish_visit_payload,
    get_wish,
    get_wish_team,
    make_volunteer_headers,
    schedule_visit,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]


def _team_ctx():
    """A wish in DETERMINATION_PENDING with an ACTIVE team (lead + second);
    the canonical child is 125 months (PLAY_BASED/DRAWING band)."""
    set_clock()
    chapter = create_chapter(territory_zip_prefixes=["900"])
    lead, second = create_volunteer_pair(chapter["id"])
    ctx = create_approved_wish(chapter=chapter)
    team = create_wish_team(ctx["wish"]["id"], lead["id"], second["id"])
    return {"chapter": chapter, "lead": lead, "second": second,
            "wish": ctx["wish"], "team": team}


def test_visit_conclude_guards_and_terminal_lockdown():
    """PRD section 3.4: "A completion requires the member to record
    `captured_true_wish` — the child's true-wish narrative — and
    `captured_wish_type`, one of `TRAVEL`, `MEET_PERSON`, `RECEIVE_ITEM`, or
    `BE_SOMETHING`; a completion missing either field is malformed
    (`ERR_INVALID_REQUEST`)."
    PRD section 3.4: "examined in this order: the team must be `ACTIVE`
    (`ERR_INVALID_TEAM_STATE`), the visit must be `SCHEDULED`
    (`ERR_INVALID_VISIT_STATE`, HTTP 409), and the actor must be a member of
    the team (`ERR_NOT_TEAM_MEMBER`)." After a COMPLETED conclude the team is
    COMPLETED, so a second conclude trips the team guard first.

    Design: Corner/state_machines/visit_conclude_guards_and_terminal_lockdown
    """
    ctx = _team_ctx()
    lead, team = ctx["lead"], ctx["team"]
    visit = schedule_visit(team["id"], lead["id"])

    missing = api_client.conclude_wish_visit(
        visit["id"], {"outcome": "COMPLETED", "captured_true_wish": "a treehouse"},
        make_volunteer_headers(lead["id"]))
    validate_error(missing, ApiErrorId.ERR_INVALID_REQUEST)

    concluded = conclude_visit_completed(visit["id"], lead["id"],
                                         captured_true_wish="a treehouse",
                                         captured_wish_type="RECEIVE_ITEM")
    assert concluded["status"] == "COMPLETED"
    assert get_wish(ctx["wish"]["id"])["status"] == "DETERMINED"
    assert get_wish(ctx["wish"]["id"])["wish_type"] == "RECEIVE_ITEM"
    assert get_wish_team(team["id"])["status"] == "COMPLETED"

    again = api_client.conclude_wish_visit(
        visit["id"], {"outcome": "NO_SHOW"}, make_volunteer_headers(lead["id"]))
    validate_error(again, ApiErrorId.ERR_INVALID_TEAM_STATE)


def test_visit_no_show_keeps_wish_and_team_active():
    """PRD section 3.4: "A `NO_SHOW` outcome changes only the visit, which
    moves to `NO_SHOW` with a version increment; the team stays `ACTIVE` and
    the wish stays `DETERMINATION_PENDING`, ready for another attempt."

    Design: Corner/state_machines/visit_no_show_keeps_wish_and_team_active
    """
    ctx = _team_ctx()
    lead, second, team, wish = (ctx["lead"], ctx["second"],
                                ctx["team"], ctx["wish"])
    visit1 = schedule_visit(team["id"], lead["id"])
    conclude_visit_no_show(visit1["id"], lead["id"])

    assert get_wish_team(team["id"])["status"] == "ACTIVE"
    assert get_wish(wish["id"])["status"] == "DETERMINATION_PENDING"

    visit2 = schedule_visit(team["id"], second["id"],
                            scheduled_start="2026-09-06T09:00:00Z",
                            scheduled_end="2026-09-06T11:00:00Z",
                            visit_method="DRAWING")
    conclude_visit_completed(visit2["id"], second["id"],
                             captured_true_wish="a treehouse",
                             captured_wish_type="RECEIVE_ITEM")
    determined = get_wish(wish["id"])
    assert determined["status"] == "DETERMINED"
    assert determined["wish_type"] == "RECEIVE_ITEM"
    assert determined["determined_at"] is not None
    assert determined["determined_at"].startswith("2026-09-01"), (
        "determined_at is stamped with the logical clock; got "
        f"{determined['determined_at']}"
    )


def test_visit_method_age_band_enforcement():
    """PRD section 3.4: "A child under 72 months — under six years — may only
    be visited `PLAY_BASED`; from 72 months up to but not including 156
    months, either `PLAY_BASED` or `DRAWING` is acceptable; at 156 months and
    above, only `INTERVIEW` remains. Any other pairing of method and age fails
    with `ERR_AGE_INAPPROPRIATE_METHOD` (HTTP 422)."
    The canonical child is 125 months at the visit start, so INTERVIEW is
    rejected while DRAWING is accepted.

    Design: Corner/calculations/visit_method_age_band_enforcement
    """
    ctx = _team_ctx()
    lead, team = ctx["lead"], ctx["team"]

    interview = api_client.create_wish_visit(
        create_wish_visit_payload(team["id"], visit_method="INTERVIEW"),
        make_volunteer_headers(lead["id"]))
    validate_error(interview, ApiErrorId.ERR_AGE_INAPPROPRIATE_METHOD)

    drawing = schedule_visit(team["id"], lead["id"], visit_method="DRAWING")
    assert drawing["status"] == "SCHEDULED"


def test_team_visit_adjacent_windows_allowed():
    """PRD section 3.4: "Visit windows are half-open intervals, start inclusive
    and end exclusive: a new visit conflicts with an existing `SCHEDULED` visit
    of the same team only when the new start falls before the existing end and
    the existing start falls before the new end. Touching boundaries — one
    visit ending exactly when the other begins — count as adjacency, not
    conflict."

    Design: Difficulty/resource_temporal_overlap/team_visit_half_open_interval_overlap
    """
    ctx = _team_ctx()
    lead, second, team = ctx["lead"], ctx["second"], ctx["team"]
    visit_a = schedule_visit(team["id"], lead["id"],
                             scheduled_start="2026-09-05T09:00:00Z",
                             scheduled_end="2026-09-05T11:00:00Z",
                             visit_method="PLAY_BASED")
    # B starts exactly at A's end: adjacency under half-open semantics.
    visit_b = schedule_visit(team["id"], second["id"],
                             scheduled_start="2026-09-05T11:00:00Z",
                             scheduled_end="2026-09-05T12:00:00Z",
                             visit_method="DRAWING")
    assert visit_a["status"] == "SCHEDULED"
    assert visit_b["status"] == "SCHEDULED"


def test_team_visit_straddling_window_rejected():
    """PRD section 3.4: "A true overlap is rejected with
    `ERR_TEAM_SCHEDULE_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/team_visit_half_open_interval_overlap
    """
    ctx = _team_ctx()
    lead, second, team = ctx["lead"], ctx["second"], ctx["team"]
    schedule_visit(team["id"], lead["id"],
                   scheduled_start="2026-09-05T09:00:00Z",
                   scheduled_end="2026-09-05T11:00:00Z",
                   visit_method="PLAY_BASED")
    schedule_visit(team["id"], second["id"],
                   scheduled_start="2026-09-05T11:00:00Z",
                   scheduled_end="2026-09-05T12:00:00Z",
                   visit_method="DRAWING")
    straddle = api_client.create_wish_visit(
        create_wish_visit_payload(
            team["id"], scheduled_start="2026-09-05T10:30:00Z",
            scheduled_end="2026-09-05T11:30:00Z", visit_method="PLAY_BASED"),
        make_volunteer_headers(lead["id"]))
    validate_error(straddle, ApiErrorId.ERR_TEAM_SCHEDULE_OVERLAP)

    visits_resp = api_client.list_team_visits(team["id"], WISH_COORDINATOR)
    items, meta = validate_paginated(visits_resp)
    assert meta["total_count"] == 2, (
        f"only the two non-overlapping visits may exist, got {meta['total_count']}"
    )
