"""Corner queue, rbac section: entity-backed capability resolution and
ownership-scoped forum operations."""
from test_helpers import (
    ApiErrorId,
    add_candidate_contest,
    add_filing,
    add_forum,
    create_volunteer,
    fresh_league,
    get_success_data,
    make_contest_payload,
    make_coordinator_headers,
    move_to_questionnaire_phase,
    validate_error,
)


def test_volunteer_lacking_capability_tag_returns_unauthenticated(api):
    """PRD §2.1: "an entity-backed `X-User-ID` that does not reference a
    live record of the role's backing type carrying the required capability
    tag — are rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."  A volunteer
    holding only EDITOR does not exist AS a ChapterCoordinator.

    Design: Corner/rbac/volunteer_lacking_capability_tag_returns_unauthenticated
    """
    ctx = fresh_league(api)  # editor Edna holds EDITOR, not COORDINATOR
    resp = api.create_contest(
        ctx["jurisdiction"]["id"],
        make_contest_payload(),
        make_coordinator_headers(ctx["editor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_non_assigned_moderator_cannot_drive_forum(api):
    """PRD §3.7: "The assigned moderator — and only the assigned moderator,
    anyone else being rejected with `ERR_UNAUTHORIZED_ROLE` — drives the
    forum through its lifecycle".

    Design: Corner/rbac/non_assigned_moderator_cannot_drive_forum
    """
    ctx = fresh_league(api, moderators=("Mod One", "Mod Two"))
    contest = add_candidate_contest(api, ctx)
    add_filing(api, ctx, contest["id"], candidate_name="Ana One",
               filing_reference="F-1")
    add_filing(api, ctx, contest["id"], candidate_name="Bob Two",
               filing_reference="F-2")
    move_to_questionnaire_phase(api, ctx, contest["id"])
    forum = add_forum(api, ctx, contest["id"], ctx["moderators"][0][0]["id"])

    # A fully qualified moderator who is not the assignee.
    resp = api.transition_forum(forum["id"], {"to": "CONFIRMED"},
                                ctx["moderators"][1][1])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    assert resp.status_code == 403
    assert get_success_data(
        api.get_forum(forum["id"], ctx["moderators"][0][1])
    )["status"] == "PLANNED"
