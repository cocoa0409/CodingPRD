"""Best-practice publications: the drafting/comment/resolution loop,
chair-only publishing under segregation of duties, OCC on the publication
version, the pinned-standard gate, and committee membership gating
(PRD §3.8, §2.10).
"""

from test_helpers import (
    ApiErrorId,
    assert_member_comment,
    close_comment_period,
    create_comment,
    create_member,
    create_publication,
    create_standard,
    activate_standard,
    make_committee_member_headers,
    make_member_headers,
    open_comment_period,
    open_comment_period_payload,
    publication_payload,
    publish_payload,
    publish_publication,
    resolve_comment,
    resolve_comment_payload,
    revise_publication,
    set_logical_clock,
    setup_publication,
    setup_publication_in_resolution,
    validate_error,
    validate_success,
)


def test_publication_revision_loop(api):
    """PRD §3.8: "Should the draft need another pass, a committee member may
    revise, returning the publication from `RESOLUTION` to `DRAFTING`:
    `draft_number` increments by one, both comment-window fields reset to
    null, and the publication's `version` increments, while comments from
    prior rounds are retained as history."
    PRD §3.8: "The loop between drafting, comment, and resolution may repeat
    as many times as the committee requires."

    Design: Difficulty/non_linear_state_machine/publication_revision_loop
    """
    bundle = setup_publication(api)
    publication = bundle["publication"]

    publication = open_comment_period(api, publication, closes_at="2026-09-20T00:00:00Z")
    set_logical_clock(api, "2026-09-21T00:00:00Z")
    publication = close_comment_period(api, publication)

    publication = revise_publication(api, publication)
    assert publication["status"] == "DRAFTING"
    assert publication["draft_number"] == 2
    assert publication["comment_window_opens_at"] is None
    assert publication["comment_window_closes_at"] is None

    # The loop re-enters MEMBER_COMMENT then RESOLUTION a second time.
    publication = open_comment_period(api, publication, closes_at="2026-09-25T00:00:00Z")
    assert publication["status"] == "MEMBER_COMMENT"
    set_logical_clock(api, "2026-09-26T00:00:00Z")
    publication = close_comment_period(api, publication)
    assert publication["status"] == "RESOLUTION"

    publication = revise_publication(api, publication)
    assert publication["status"] == "DRAFTING"
    assert publication["draft_number"] == 3


def test_publication_publish_stale_version_occ(api):
    """PRD §2.10: "Publishing a best-practice publication requires
    `expected_publication_version`, holding the chair's last observed
    `version` of the publication. Every comment resolution and every
    comment-period transition advances that version, so a mismatch means the
    chair has not seen the latest resolution snapshot; the publish is rejected
    with `ERR_STALE_PUBLICATION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/publication_publish_stale_version_occ
    """
    bundle = setup_publication(api)
    publication = bundle["publication"]
    chair_headers = make_committee_member_headers(bundle["chair"]["id"])

    opened = open_comment_period(api, publication, closes_at="2026-09-20T00:00:00Z")
    stale_version = opened["version"]
    set_logical_clock(api, "2026-09-21T00:00:00Z")
    closed = close_comment_period(api, opened)

    stale = api.publish_publication(
        publication["id"],
        publish_payload(stale_version),
        headers=chair_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_PUBLICATION_VERSION)

    published = publish_publication(
        api, closed, expected_publication_version=closed["version"]
    )
    assert published["status"] == "PUBLISHED"
    assert published["published_at"].startswith("2026-09-21T00:00:00")


def test_member_comment_member_id_from_header_not_payload(api):
    """PRD §3.8: "While the window is open, any `Member` may file a comment
    with a `publication_id` and a `body`; their `member_id` is taken from the
    caller's identity."
    PRD §3.8: "Each new comment starts with `resolution` set to `PENDING` and
    increments the publication's `pending_comment_count`, bumping the
    publication's `version`."

    Design: Corner/entities/member_comment_member_id_from_header_not_payload
    """
    bundle = setup_publication(api)
    open_comment_period(api, bundle["publication"], closes_at="2026-09-20T00:00:00Z")
    commenter = create_member(api)

    resp = api.create_member_comment(
        {"publication_id": bundle["publication"]["id"],
         "body": "Please clarify the escalation matrix."},
        headers=make_member_headers(commenter["id"]),
    )
    comment = validate_success(resp, 201)
    assert_member_comment(comment)
    assert comment["member_id"] == commenter["id"]
    assert comment["resolution"] == "PENDING"


def test_publication_close_before_closes_at_returns_still_open(api):
    """PRD §3.8: "Closing the period is again a committee act, lawful only
    from `MEMBER_COMMENT` (else `ERR_PUBLICATION_STATE_INVALID`) and only once
    the logical clock has reached `comment_window_closes_at`; closing early is
    rejected with `ERR_COMMENT_WINDOW_STILL_OPEN`."

    Design: Corner/state_machines/publication_close_before_closes_at_returns_still_open
    """
    bundle = setup_publication(api)
    publication = open_comment_period(
        api, bundle["publication"], closes_at="2026-09-20T00:00:00Z"
    )
    creator_headers = make_committee_member_headers(bundle["creator"]["id"])

    set_logical_clock(api, "2026-09-19T00:00:00Z")
    early = api.close_comment_period(publication["id"], headers=creator_headers)
    validate_error(early, ApiErrorId.ERR_COMMENT_WINDOW_STILL_OPEN)

    # At exactly closes_at the gate opens (now >= closes_at).  This close
    # succeeding also proves the rejected attempt left the publication in
    # MEMBER_COMMENT — close is lawful only from MEMBER_COMMENT.
    set_logical_clock(api, "2026-09-20T00:00:00Z")
    closed = close_comment_period(api, publication)
    assert closed["status"] == "RESOLUTION"


def test_comment_after_window_close_returns_window_closed(api):
    """PRD §3.8: "Filing is lawful only while the publication is in
    `MEMBER_COMMENT` and the logical clock remains before
    `comment_window_closes_at` — a filing at or after the close is rejected
    with `ERR_COMMENT_WINDOW_CLOSED`."

    Design: Corner/state_machines/comment_after_window_close_returns_window_closed
    """
    bundle = setup_publication(api)
    publication = open_comment_period(
        api, bundle["publication"], closes_at="2026-09-20T00:00:00Z"
    )
    commenter = create_member(api)

    # At exactly closes_at the window is shut (now < closes_at required).
    set_logical_clock(api, "2026-09-20T00:00:00Z")
    late = api.create_member_comment(
        {"publication_id": publication["id"], "body": "Late comment."},
        headers=make_member_headers(commenter["id"]),
    )
    validate_error(late, ApiErrorId.ERR_COMMENT_WINDOW_CLOSED)


def test_self_approval_forbidden_when_chair_created(api):
    """PRD §3.8: "Publishing is the chair's act alone."
    PRD §3.8: "The caller's identity must equal the publication's
    `chair_member_id` — any other committee member is rejected with
    `ERR_NOT_RESOURCE_OWNER` — and segregation of duties forbids the chair
    from publishing a draft they themselves created: when `chair_member_id`
    equals `created_by_member_id` the publish is rejected with
    `ERR_SELF_APPROVAL_FORBIDDEN`."

    Design: Corner/errors/self_approval_forbidden_when_chair_created
    """
    set_logical_clock(api)
    chair = create_member(api)
    publication = create_publication(
        api,
        chair_member_id=chair["id"],
        creator_member_id=chair["id"],
        member_ids=[chair["id"]],
    )
    chair_headers = make_committee_member_headers(chair["id"])

    opened = open_comment_period(api, publication, closes_at="2026-09-20T00:00:00Z")
    set_logical_clock(api, "2026-09-21T00:00:00Z")
    closed = close_comment_period(api, opened)

    resp = api.publish_publication(
        publication["id"],
        publish_payload(closed["version"]),
        headers=chair_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)


def test_publish_with_unresolved_comments_rejected(api):
    """PRD §3.8: "every comment must be resolved, so `pending_comment_count`
    must be zero, else `ERR_UNRESOLVED_COMMENTS`"
    PRD §3.8: "Resolving a comment requires committee membership, the
    publication to be in `RESOLUTION` (else `ERR_PUBLICATION_STATE_INVALID`),
    and the comment to still be `PENDING`"

    Design: Corner/errors/publish_with_unresolved_comments_rejected
    """
    bundle = setup_publication_in_resolution(api, with_pending_comment=True)
    publication = bundle["publication"]
    chair_headers = make_committee_member_headers(bundle["chair"]["id"])

    blocked = api.publish_publication(
        publication["id"],
        publish_payload(publication["version"]),
        headers=chair_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_UNRESOLVED_COMMENTS)

    # The rejection did not mutate the publication: after resolving the one
    # PENDING comment (which bumps the publication version by exactly one per
    # PRD §3.8), the chair publishes against the current version.
    resolve_comment(
        api, bundle["comment"]["id"], member_id=bundle["creator"]["id"]
    )
    published = publish_publication(
        api, publication,
        expected_publication_version=publication["version"] + 1,
    )
    assert published["status"] == "PUBLISHED"


def test_publish_with_superseded_pinned_standard_rejected(api):
    """PRD §3.8: "the pinned standard must still be current — when
    `pinned_standards_reference_id` is set and that standard has become
    `SUPERSEDED`, the publish is rejected with
    `ERR_PINNED_STANDARD_SUPERSEDED`."
    PRD §3.7: "every other `EFFECTIVE` standard sharing the same `topic_code`
    is superseded to `SUPERSEDED`"

    Design: Corner/errors/publish_with_superseded_pinned_standard_rejected
    """
    set_logical_clock(api, "2026-09-15T00:00:00Z")
    standard_v1 = create_standard(api, effective_date="2026-09-10T00:00:00Z")
    activate_standard(api, standard_v1["id"])

    bundle = setup_publication(
        api, pinned_standards_reference_id=standard_v1["id"], set_clock_to=None
    )
    publication = open_comment_period(
        api, bundle["publication"], closes_at="2026-09-20T00:00:00Z"
    )
    set_logical_clock(api, "2026-09-21T00:00:00Z")
    publication = close_comment_period(api, publication)

    # A later standard on the same topic supersedes the pinned one.
    standard_v2 = create_standard(api, effective_date="2026-09-10T00:00:00Z")
    activate_standard(api, standard_v2["id"])

    resp = api.publish_publication(
        publication["id"],
        publish_payload(publication["version"]),
        headers=make_committee_member_headers(bundle["chair"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PINNED_STANDARD_SUPERSEDED)

    # The rejection left the publication in RESOLUTION: revise is lawful only
    # from RESOLUTION and moves it back to DRAFTING.
    revised = revise_publication(api, publication)
    assert revised["status"] == "DRAFTING"


def test_chair_not_on_committee_rejected(api):
    """PRD §3.8: "Both the creator and the chair must sit on the committee:
    the creator's identity — recorded on the publication as
    `created_by_member_id` — must be an element of `member_ids`, and
    `chair_member_id` must be an element of `member_ids` as well, with either
    failure rejected as `ERR_CHAIR_NOT_ON_COMMITTEE`."

    Design: Corner/validations/chair_not_on_committee_rejected
    """
    set_logical_clock(api)
    chair = create_member(api)
    creator = create_member(api)

    resp = api.create_publication(
        publication_payload(chair["id"], [creator["id"]]),
        headers=make_committee_member_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CHAIR_NOT_ON_COMMITTEE)


def test_member_cannot_resolve_comment_forbidden(api):
    """PRD §2.1: "Each operation declares the roles authorized to call it (§4);
    a caller whose role is not on that operation's list is rejected with
    `ERR_FORBIDDEN_ROLE`."
    PRD §4 (endpoint table, POST /gfoa/member-comments/{id}/resolve): "Resolve
    a `PENDING` comment during `RESOLUTION`" — authorized role:
    `CommitteeMember` only.

    Design: Corner/rbac/member_cannot_resolve_comment_forbidden
    """
    bundle = setup_publication_in_resolution(api, with_pending_comment=True)
    comment = bundle["comment"]
    commenter = bundle["commenter"]

    resp = api.resolve_member_comment(
        comment["id"],
        resolve_comment_payload("ACCEPTED"),
        headers=make_member_headers(commenter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    stayed = validate_success(
        api.get_member_comment(
            comment["id"],
            headers=make_committee_member_headers(bundle["creator"]["id"]),
        )
    )
    assert stayed["resolution"] == "PENDING"


def test_publish_requires_chair_not_plain_member(api):
    """PRD §3.8: "Publishing is the chair's act alone. The caller's identity
    must equal the publication's `chair_member_id` — any other committee
    member is rejected with `ERR_NOT_RESOURCE_OWNER`"

    Design: Corner/rbac/publish_requires_chair_not_plain_member
    """
    bundle = setup_publication_in_resolution(api)
    publication = bundle["publication"]

    not_chair = api.publish_publication(
        publication["id"],
        publish_payload(publication["version"]),
        headers=make_committee_member_headers(bundle["creator"]["id"]),
    )
    validate_error(not_chair, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    # The failed publish neither transitioned nor bumped the publication: the
    # chair's publish against the same observed version succeeds.
    published = publish_publication(
        api, publication,
        expected_publication_version=publication["version"],
    )
    assert published["status"] == "PUBLISHED"


def test_committee_outsider_cannot_open_comment_period(api):
    """PRD §3.8: "Opening the member comment period is a committee act — the
    caller's identity must be an element of `member_ids`, else
    `ERR_NOT_RESOURCE_OWNER` — lawful only from `DRAFTING`, else
    `ERR_PUBLICATION_STATE_INVALID`."

    Design: Corner/rbac/committee_outsider_cannot_open_comment_period
    """
    bundle = setup_publication(api)
    outsider = create_member(api)

    resp = api.open_comment_period(
        bundle["publication"]["id"],
        open_comment_period_payload("2026-09-20T00:00:00Z"),
        headers=make_committee_member_headers(outsider["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    # The rejection left the publication DRAFTING: the creator's open (lawful
    # only from DRAFTING) succeeds and moves it to MEMBER_COMMENT.
    opened = open_comment_period(api, bundle["publication"])
    assert opened["status"] == "MEMBER_COMMENT"
