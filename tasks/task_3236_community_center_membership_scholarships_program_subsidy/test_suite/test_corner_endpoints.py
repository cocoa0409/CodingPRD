"""Corner probes against endpoint behaviors: draft period idempotency and
server-set reservation buffers."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    BRANCH_DIRECTOR_HEADERS,
    make_member_headers,
)
from test_helpers import fixtures


def test_second_draft_for_the_same_period_is_rejected(api):
    """One draft per membership per period_month; the activation month already
    has one.

    PRD §3.3: "Only one draft may exist per membership per `period_month` — a
    second is `ERR_DUPLICATE_DRAFT`."

    Design: Corner/endpoints/draft_creation_duplicate_period_rejected
    """
    world = fixtures.setup_membership(api)
    membership = world["membership"]

    validate_error(
        api.create_draft_for_membership(membership["id"], BRANCH_DIRECTOR_HEADERS),
        "ERR_DUPLICATE_DRAFT",
    )

    drafts, meta = validate_paginated(
        api.list_membership_drafts(membership["id"], BRANCH_DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 1
    assert drafts[0]["period_month"] == "2026-09"


def test_reservation_create_sets_the_type_specific_buffer(api):
    """buffer_minutes is server-set per type; the client cannot choose it.

    PRD §3.6: "Each type carries a fixed setup-and-teardown `buffer_minutes`
    applied to both ends of the interval: 15 minutes for `PROGRAM`, 30 minutes
    for `RENTAL`, and zero for `MAINTENANCE` and `BLACKOUT`. A reservation is
    born `REQUESTED`."

    Design: Corner/endpoints/reservation_create_sets_type_specific_buffer
    """
    world = fixtures.setup_association_and_branch(api)
    space = fixtures.create_space(api, world["branch"]["id"], name="Gym", kind="GYM", capacity=100, dropin_capacity=20)
    renter = fixtures.create_member(
        api, world["branch"]["id"], full_name="Renter Ron", email="ron@x.com", birth_date="1980-01-01"
    )

    rental = get_success_data(
        api.create_reservation(
            {
                "space_id": space["id"],
                "reservation_type": "RENTAL",
                "start_at": "2026-09-15T09:00:00Z",
                "end_at": "2026-09-15T10:00:00Z",
                "renter_member_id": renter["id"],
            },
            make_member_headers(renter["id"]),
        )
    )
    assert rental["status"] == "REQUESTED"
    assert rental["buffer_minutes"] == 30

    maintenance = get_success_data(
        api.create_reservation(
            {
                "space_id": space["id"],
                "reservation_type": "MAINTENANCE",
                "start_at": "2026-09-16T09:00:00Z",
                "end_at": "2026-09-16T10:00:00Z",
            },
            BRANCH_DIRECTOR_HEADERS,
        )
    )
    assert maintenance["status"] == "REQUESTED"
    assert maintenance["buffer_minutes"] == 0
