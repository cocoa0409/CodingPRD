"""Corner probes against role confinement: exclusive operations and ownership."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    ASSOCIATION_ADMIN_HEADERS,
    BOARD_MEMBER_HEADERS,
    BRANCH_DIRECTOR_HEADERS,
    make_member_headers,
)
from test_helpers import factories, fixtures


def test_member_cannot_approve_their_own_application(api):
    """Approval is exclusive to BranchDirector; even the applicant is denied.

    PRD §2.1: "A request whose role is valid but not permitted for the endpoint
    — or where a `Member` attempts to act on a resource they do not own — is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "**`BranchDirector`** — branch executive; adjudicates scholarship
    applications, approves or denies facility reservations, and reinstates
    lapsed memberships."

    Design: Corner/rbac/member_cannot_approve_own_application
    """
    world = fixtures.setup_application_under_review(api)
    response = api.approve_application(
        world["application"]["id"],
        {"expected_membership_version": world["membership"]["version"]},
        make_member_headers(world["member"]["id"]),
    )
    validate_error(response, "ERR_UNAUTHORIZED")

    current = get_success_data(api.get_application(world["application"]["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "UNDER_REVIEW"


def test_board_member_reads_but_cannot_create(api):
    """BoardMember is read-only: creating a branch is denied, listing is allowed.

    PRD §2.1: "**`BoardMember`** — association or branch board volunteer with
    read-only governance visibility; holds no exclusive or mutating operations."

    Design: Corner/rbac/board_member_read_only_cannot_create_branch
    """
    fixtures.set_clock(api)
    association = fixtures.create_association(api)

    response = api.create_branch(
        factories.branch_payload(association["id"]), BOARD_MEMBER_HEADERS
    )
    validate_error(response, "ERR_UNAUTHORIZED")

    rows, meta = validate_paginated(
        api.list_branches(BOARD_MEMBER_HEADERS, {"association_id": association["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_member_cannot_act_on_another_members_membership(api):
    """Ownership binds the Member role to their own resources only.

    PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
    acting `Member` record; ownership checks on any resource that references a
    `Member` compare the resource's foreign-key field (such as
    `primary_member_id`, `applicant_member_id`, or `member_id`) to `X-User-ID`."
    PRD §2.1: "A request whose role is valid but not permitted for the endpoint
    — or where a `Member` attempts to act on a resource they do not own — is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/member_cannot_act_on_other_members_resources
    """
    world = fixtures.setup_branch_with_category(api)
    member_a = fixtures.create_member(api, world["branch"]["id"], full_name="A One", email="a@x.com")
    member_b = fixtures.create_member(api, world["branch"]["id"], full_name="B Two", email="b@x.com")
    membership_b = get_success_data(
        api.create_membership(
            factories.membership_payload(world["branch"]["id"], world["category"]["id"], member_b["id"]),
            make_member_headers(member_b["id"]),
        )
    )

    response = api.hold_membership(
        membership_b["id"], {"hold_until": "2026-11-15"}, make_member_headers(member_a["id"])
    )
    validate_error(response, "ERR_UNAUTHORIZED")

    current = get_success_data(api.get_membership(membership_b["id"], BRANCH_DIRECTOR_HEADERS))
    assert current["status"] == "ACTIVE"


def test_blackout_reservation_is_association_admin_only(api):
    """Creating a BLACKOUT is denied to other roles and allowed to the admin,
    who also sees the zero buffer.

    PRD §3.6: "Creating a `BLACKOUT` reservation is reserved to the
    `AssociationAdmin` role — anyone else attempting it is `ERR_UNAUTHORIZED`."
    PRD §3.6: "Each type carries a fixed setup-and-teardown `buffer_minutes`
    applied to both ends of the interval: 15 minutes for `PROGRAM`, 30 minutes
    for `RENTAL`, and zero for `MAINTENANCE` and `BLACKOUT`."

    Design: Corner/rbac/blackout_reservation_requires_association_admin
    """
    world = fixtures.setup_association_and_branch(api)
    space = fixtures.create_space(api, world["branch"]["id"], name="Gym", kind="GYM", capacity=100, dropin_capacity=20)

    payload = {
        "space_id": space["id"],
        "reservation_type": "BLACKOUT",
        "start_at": "2026-12-24T00:00:00Z",
        "end_at": "2026-12-26T00:00:00Z",
    }
    validate_error(api.create_reservation(payload, BRANCH_DIRECTOR_HEADERS), "ERR_UNAUTHORIZED")

    blackout = get_success_data(api.create_reservation(dict(payload), ASSOCIATION_ADMIN_HEADERS))
    assert blackout["reservation_type"] == "BLACKOUT"
    assert blackout["buffer_minutes"] == 0
    assert blackout["status"] == "REQUESTED"
