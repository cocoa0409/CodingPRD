"""Volunteer ladder, wish-team composition guards, team supersede cascade,
and the visit membership check.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_wish_team,
    create_approved_wish,
    create_chapter,
    create_volunteer,
    create_volunteer_pair,
    create_volunteer_transition_payload,
    create_wish_team,
    create_wish_team_payload,
    create_wish_visit_payload,
    get_volunteer,
    get_wish,
    get_wish_team,
    get_wish_version,
    make_volunteer_headers,
    schedule_visit,
    set_clock,
    transition_volunteer,
    validate_error,
    validate_paginated,
    validate_success,
)

WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]


def _wish_with_active_pair():
    """Chapter + two ACTIVE volunteers + a CREATED wish. Returns context."""
    set_clock()
    chapter = create_chapter(territory_zip_prefixes=["900"])
    lead, second = create_volunteer_pair(chapter["id"])
    ctx = create_approved_wish(chapter=chapter)
    return {"chapter": chapter, "lead": lead, "second": second,
            "wish": ctx["wish"], "referral": ctx["referral"]}


def test_volunteer_transition_skip_rejected():
    """PRD section 3.1: "the target must be exactly the next rung — asking for
    `ACTIVE` from `APPLIED`, or any other skip or sideways move, is rejected
    with `ERR_INVALID_VOLUNTEER_STATE` (HTTP 409)."

    Design: Corner/state_machines/volunteer_transition_skip_rejected
    """
    chapter = create_chapter()
    volunteer = create_volunteer(chapter["id"])
    resp = api_client.transition_volunteer(
        volunteer["id"], create_volunteer_transition_payload("ACTIVE"),
        WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_VOLUNTEER_STATE)
    assert get_volunteer(volunteer["id"])["status"] == "APPLIED"


def test_team_create_rejects_trained_volunteer():
    """PRD section 3.4: "both must hold `ACTIVE` status, or
    `ERR_VOLUNTEER_NOT_ACTIVE` (HTTP 409) fires"
    The rejected attempt does not advance the wish, so the observed version
    stays valid for a later retry.

    Design: Difficulty/cross_entity_state_dependency/team_create_requires_active_volunteers
    """
    ctx = _wish_with_active_pair()
    chapter, lead, wish = ctx["chapter"], ctx["lead"], ctx["wish"]
    trained = create_volunteer(chapter["id"], full_name="Owen Diaz",
                               email="owen@example.org")
    transition_volunteer(trained["id"], "TRAINED")  # TRAINED, not ACTIVE
    observed = get_wish_version(wish["id"])

    resp = api_client.create_wish_team(
        create_wish_team_payload(wish["id"], lead["id"], trained["id"],
                                 observed),
        WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ACTIVE)
    after = get_wish(wish["id"])
    assert after["status"] == "CREATED"
    assert after["version"] == observed, (
        "the rejected team creation must not bump Wish.version, so the same "
        "expected_wish_version stays valid"
    )


def test_team_create_succeeds_once_both_volunteers_active():
    """PRD section 3.4: "Creating the first team moves the wish `CREATED` →
    `DETERMINATION_PENDING`, opens a team in `ACTIVE` status, and advances the
    wish's `version`."

    Design: Difficulty/cross_entity_state_dependency/team_create_requires_active_volunteers
    """
    ctx = _wish_with_active_pair()
    chapter, lead, wish = ctx["chapter"], ctx["lead"], ctx["wish"]
    trained = create_volunteer(chapter["id"], full_name="Owen Diaz",
                               email="owen@example.org")
    transition_volunteer(trained["id"], "TRAINED")
    observed = get_wish_version(wish["id"])
    blocked = api_client.create_wish_team(
        create_wish_team_payload(wish["id"], lead["id"], trained["id"],
                                 observed),
        WISH_COORDINATOR)
    validate_error(blocked, ApiErrorId.ERR_VOLUNTEER_NOT_ACTIVE)

    transition_volunteer(trained["id"], "ACTIVE")
    team = create_wish_team(wish["id"], lead["id"], trained["id"],
                            expected_wish_version=observed)
    assert_wish_team(team)
    assert team["status"] == "ACTIVE"
    assert get_wish(wish["id"])["status"] == "DETERMINATION_PENDING"


def test_team_duplicate_member_rejected():
    """PRD section 3.4: "the two volunteers must be different people, or
    `ERR_TEAM_DUPLICATE_MEMBER` (HTTP 422) fires"

    Design: Corner/validations/team_duplicate_member_rejected
    """
    ctx = _wish_with_active_pair()
    lead, wish = ctx["lead"], ctx["wish"]
    resp = api_client.create_wish_team(
        create_wish_team_payload(wish["id"], lead["id"], lead["id"],
                                 get_wish_version(wish["id"])),
        WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_TEAM_DUPLICATE_MEMBER)
    assert get_wish(wish["id"])["status"] == "CREATED"


def test_team_chapter_mismatch_rejected():
    """PRD section 3.4: "both must belong to the wish's chapter, meaning each
    volunteer's `chapter_id` equals the wish's `chapter_id`, or
    `ERR_TEAM_CHAPTER_MISMATCH` (HTTP 422) fires."

    Design: Corner/validations/team_chapter_mismatch_rejected
    """
    set_clock()
    chapter_a = create_chapter(name="Chapter A", territory_zip_prefixes=["900"])
    chapter_b = create_chapter(name="Chapter B", territory_zip_prefixes=["800"])
    lead, _ = create_volunteer_pair(chapter_a["id"])
    outsider = create_volunteer(chapter_b["id"], full_name="Sam Reed",
                                email="sam@example.org")
    transition_volunteer(outsider["id"], "TRAINED")
    transition_volunteer(outsider["id"], "ACTIVE")
    ctx = create_approved_wish(chapter=chapter_a)
    wish = ctx["wish"]

    resp = api_client.create_wish_team(
        create_wish_team_payload(wish["id"], lead["id"], outsider["id"],
                                 get_wish_version(wish["id"])),
        WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_TEAM_CHAPTER_MISMATCH)


def test_visit_actor_not_team_member_forbidden():
    """PRD section 3.4: "the acting volunteer must be the team's lead or
    second — the server compares `X-User-ID` to the team's `lead_volunteer_id`
    and `second_volunteer_id`, and anyone else is rejected with
    `ERR_NOT_TEAM_MEMBER` (HTTP 403)"

    Design: Corner/validations/visit_actor_not_team_member_forbidden
    """
    ctx = _wish_with_active_pair()
    chapter, lead, second, wish = (ctx["chapter"], ctx["lead"],
                                   ctx["second"], ctx["wish"])
    outsider = create_volunteer(chapter["id"], full_name="Sam Reed",
                                email="sam@example.org")
    transition_volunteer(outsider["id"], "TRAINED")
    transition_volunteer(outsider["id"], "ACTIVE")
    team = create_wish_team(wish["id"], lead["id"], second["id"])
    visit = schedule_visit(team["id"], lead["id"])

    resp = api_client.conclude_wish_visit(
        visit["id"], {"outcome": "NO_SHOW"},
        make_volunteer_headers(outsider["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_TEAM_MEMBER)
    visits = api_client.list_team_visits(team["id"], WISH_COORDINATOR)
    items, _ = validate_paginated(visits)
    assert items[0]["status"] == "SCHEDULED", (
        "the rejected conclude must leave the visit SCHEDULED"
    )


def test_team_supersede_disbands_and_cancels_scheduled_visits():
    """PRD section 3.4: "Creating another team while the wish is
    `DETERMINATION_PENDING` is a legitimate replacement rather than an error:
    the wish self-loops within `DETERMINATION_PENDING` — the state label is
    unchanged but the wish's `version` advances — the previously `ACTIVE` team
    is disbanded to `DISBANDED` with its own version increment, every
    `SCHEDULED` visit of that disbanded team is cancelled to `CANCELLED` with
    a version increment each, and the new team opens `ACTIVE`."
    PRD section 3.4: "the team must still be `ACTIVE`, or the request fails
    with `ERR_INVALID_TEAM_STATE` (HTTP 409)"

    Design: Corner/state_machines/team_supersede_disbands_and_cancels_scheduled_visits
    """
    ctx = _wish_with_active_pair()
    lead, second, wish = ctx["lead"], ctx["second"], ctx["wish"]
    team1 = create_wish_team(wish["id"], lead["id"], second["id"])
    visit1 = schedule_visit(team1["id"], lead["id"])
    version_before_replace = get_wish_version(wish["id"])

    team2 = create_wish_team(wish["id"], second["id"], lead["id"],
                             expected_wish_version=version_before_replace)
    assert team2["status"] == "ACTIVE"
    assert get_wish_team(team1["id"])["status"] == "DISBANDED"

    visits_resp = api_client.list_team_visits(team1["id"], WISH_COORDINATOR)
    items, _ = validate_paginated(visits_resp)
    cancelled = [v for v in items if v["id"] == visit1["id"]]
    assert cancelled and cancelled[0]["status"] == "CANCELLED", (
        "the superseded team's SCHEDULED visit must be cancelled"
    )

    disbanded_visit = api_client.create_wish_visit(
        create_wish_visit_payload(
            team1["id"], scheduled_start="2026-09-07T09:00:00Z",
            scheduled_end="2026-09-07T11:00:00Z", visit_method="PLAY_BASED"),
        make_volunteer_headers(lead["id"]))
    validate_error(disbanded_visit, ApiErrorId.ERR_INVALID_TEAM_STATE)

    wish = get_wish(wish["id"])
    assert wish["version"] == version_before_replace + 1, (
        f"replacement advances Wish.version by exactly one: "
        f"{version_before_replace} -> {wish['version']}"
    )
    assert wish["status"] == "DETERMINATION_PENDING"
