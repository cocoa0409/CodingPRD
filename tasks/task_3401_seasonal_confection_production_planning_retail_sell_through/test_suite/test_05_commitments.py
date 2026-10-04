"""Retailer commitments: creation contract, collection-window gate, shelf
cap, revise-with-supersede OCC, role/ownership denial, and the
state-before-temporal priority pair on submit.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_AT_COMMITMENT_CLOSE,
    CommitmentStatus,
    ProgramAdvanceTarget,
    SeasonalProgramStatus,
    TEST_USERS,
    advance_program_to,
    api_client,
    assert_retailer_commitment,
    confirm_commitment,
    create_commitment_payload,
    create_draft_commitment,
    create_retailer,
    create_submitted_commitment,
    get_commitment,
    make_retailer_headers,
    revise_commitment_payload,
    set_clock,
    setup_open_program,
    submit_commitment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["category_manager_headers"]


def test_commitment_create_with_allocated_units_and_version_input_ignored(api):
    """PRD §3.4: "A new commitment is a `DRAFT` with `allocated_units` 0,
    `reorder_units` 0, `reorder_used` false, `revision` 1, a null
    `supersedes_commitment_id`, and `version` 1."

    Design: Corner/entities/commitment_create_with_allocated_units_and_version_input_ignored
    """
    world = setup_open_program()
    retailer = world["retailer"]
    payload = create_commitment_payload(
        program_id=world["program"]["id"], retailer_id=retailer["id"],
        product_id=world["product"]["id"], committed_units=5,
        allocated_units=999, version=99,
    )
    resp = api_client.create_commitment(payload, make_retailer_headers(retailer["id"]))
    data = validate_success(resp, 201)
    assert_retailer_commitment(data)
    assert data["allocated_units"] == 0, "client-supplied system field is ignored"
    assert data["version"] == 1
    assert data["revision"] == 1
    assert data["status"] == CommitmentStatus.DRAFT.value
    assert data["reorder_used"] is False
    assert data["supersedes_commitment_id"] is None


def test_commitment_confirm_from_draft_returns_invalid_state(api):
    """PRD §3.4: "Confirmation is the house's move: a `CategoryManager`
    confirms a `SUBMITTED` commitment, moving it to `CONFIRMED`". PRD §2.8
    priority 7: "the target resource is in a state from which the requested
    transition is defined" (`ERR_INVALID_STATE`).

    Design: Corner/state_machines/commitment_confirm_from_draft_returns_invalid_state
    """
    world = setup_open_program()
    draft = create_draft_commitment(
        world["program"], world["retailer"], world["product"], committed_units=5,
    )
    resp = api_client.confirm_commitment(draft["id"], CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_commitment(draft["id"])
    assert after["status"] == CommitmentStatus.DRAFT.value
    assert after["version"] == draft["version"]


def test_commitments_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1,
    and must not exceed 100. The `offset` parameter defaults to 0." and "The
    `meta` object of a list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more`, where `total_count` is the number
    of resources matching the filters and `has_more` indicates whether
    resources remain beyond the returned page."

    Design: Corner/entities/commitments_list_paginates_with_total_count_and_has_more
    """
    world = setup_open_program()
    gold = world["retailer"]
    silver = create_retailer(tier="SILVER", everyday_baseline_weekly_units=800)
    for _ in range(3):
        create_draft_commitment(
            world["program"], gold, world["product"], committed_units=5,
        )
    create_draft_commitment(
        world["program"], silver, world["product"], committed_units=5,
    )

    page1, meta1 = validate_paginated(api_client.list_commitments(
        ADMIN, params={"retailer_id": gold["id"], "limit": 2, "offset": 0},
    ))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api_client.list_commitments(
        ADMIN, params={"retailer_id": gold["id"], "limit": 2, "offset": 2},
    ))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    silver_rows, silver_meta = validate_paginated(api_client.list_commitments(
        ADMIN, params={"retailer_id": silver["id"]},
    ))
    assert len(silver_rows) == 1
    assert silver_meta["total_count"] == 1

    all_rows, all_meta = validate_paginated(api_client.list_commitments(ADMIN))
    assert len(all_rows) == 4
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0


def test_submit_at_exact_close_instant_returns_window_closed(api):
    """PRD §3.4: "the logical clock must sit inside the half-open collection
    interval — at or after `commitment_open_on` and strictly before
    `commitment_close_on` — or the submit is rejected with
    `ERR_COMMITMENT_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/submit_at_exact_close_instant_returns_window_closed
    """
    world = setup_open_program()
    draft = create_draft_commitment(
        world["program"], world["retailer"], world["product"], committed_units=5,
    )
    # Exactly commitment_close_on: the half-open window excludes this instant,
    # and the program itself is still OPEN_FOR_COMMITMENTS.
    set_clock(CLOCK_AT_COMMITMENT_CLOSE)
    resp = api_client.submit_commitment(
        draft["id"], make_retailer_headers(world["retailer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_WINDOW_CLOSED)
    assert get_commitment(draft["id"])["status"] == CommitmentStatus.DRAFT.value


def test_shelf_cap_confirm_allows_exact_cap_and_rejects_one_over(api):
    """PRD §3.4: "the sum of `committed_units` over all of the retailer's
    commitments in `SUBMITTED`, `CONFIRMED`, `ALLOCATED`, `SHORTED`,
    `FULFILLING`, or `FULFILLED` status — this commitment included — must not
    exceed the account's `max_seasonal_units`, or the confirm is rejected with
    `ERR_SHELF_CAP_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/shelf_cap_confirm_allows_exact_cap_and_rejects_one_over
    """
    world = setup_open_program()
    retailer = create_retailer(
        tier="SILVER", max_seasonal_units=100, everyday_baseline_weekly_units=500,
    )
    c1 = create_submitted_commitment(world["program"], retailer, world["product"], 60)
    c2 = create_submitted_commitment(world["program"], retailer, world["product"], 40)

    # The cap sums SUBMITTED commitments too, so the 1-unit commitment is only
    # created after c1 and c2 are confirmed (60 + 40 == 100 <= 100: the cap is
    # inclusive); had it existed earlier, confirming c1 would already total 101.
    assert confirm_commitment(c1)["status"] == CommitmentStatus.CONFIRMED.value
    assert confirm_commitment(c2)["status"] == CommitmentStatus.CONFIRMED.value

    c3 = create_submitted_commitment(world["program"], retailer, world["product"], 1)
    resp = api_client.confirm_commitment(c3["id"], CM)
    validate_error(resp, ApiErrorId.ERR_SHELF_CAP_EXCEEDED)
    assert get_commitment(c3["id"])["status"] == CommitmentStatus.SUBMITTED.value


def test_commitment_for_everyday_product_returns_product_program_mismatch(api):
    """PRD §3.4: "Creating a `RetailerCommitment` names ... a `product_id`
    that must be a `SEASONAL` product belonging to that program
    (`ERR_PRODUCT_PROGRAM_MISMATCH`)"."

    Design: Corner/errors/commitment_for_everyday_product_returns_product_program_mismatch
    """
    world = setup_open_program(with_everyday_product=True)
    retailer = world["retailer"]
    resp = api_client.create_commitment(
        create_commitment_payload(
            program_id=world["program"]["id"], retailer_id=retailer["id"],
            product_id=world["everyday_product"]["id"], committed_units=5,
        ),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_PROGRAM_MISMATCH)
    rows, _meta = validate_paginated(api_client.list_commitments(
        ADMIN, params={"retailer_id": retailer["id"]},
    ))
    assert rows == []


def test_commitment_revise_supersedes_and_second_revise_is_stale(api):
    """PRD §3.4: "the old `SUBMITTED` commitment becomes `SUPERSEDED` and its
    `version` increments, and a brand-new commitment is created in the same
    breath — same program, retailer, and product, the new `committed_units`,
    ... `revision` one higher than the old row, `supersedes_commitment_id`
    pointing at the old commitment, status `SUBMITTED`, and `version` 1;
    because a new resource is created, revision returns the successor with
    HTTP 201." PRD §2.7: "if the commitment's `version` has advanced since the
    caller last read it — for example because a prior revision already
    superseded it — the revise is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/commitment_revise_supersedes_and_second_revise_is_stale
    """
    world = setup_open_program()
    retailer = world["retailer"]
    submitted = create_submitted_commitment(
        world["program"], retailer, world["product"], committed_units=5,
    )

    successor = validate_success(api_client.revise_commitment(
        submitted["id"],
        revise_commitment_payload(
            committed_units=25,
            expected_commitment_version=submitted["version"],
        ),
        make_retailer_headers(retailer["id"]),
    ), 201)
    assert successor["revision"] == submitted["revision"] + 1
    assert successor["status"] == CommitmentStatus.SUBMITTED.value
    assert successor["committed_units"] == 25
    assert successor["supersedes_commitment_id"] == submitted["id"]
    assert successor["version"] == 1

    old = get_commitment(submitted["id"])
    assert old["status"] == CommitmentStatus.SUPERSEDED.value
    assert old["version"] == submitted["version"] + 1

    replay = api_client.revise_commitment(
        submitted["id"],
        revise_commitment_payload(
            committed_units=30,
            expected_commitment_version=submitted["version"],
        ),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)

    successors, _meta = validate_paginated(api_client.list_commitments(
        ADMIN, params={"supersedes_commitment_id": submitted["id"]},
    ))
    assert len(successors) == 1
    assert successors[0]["id"] == successor["id"]


def test_retailer_cannot_confirm_own_commitment_returns_unauthorized(api):
    """PRD §2.1: "If the role is declared but is not among the roles
    authorized for the target endpoint (see Section 4), the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)." PRD §4: confirm is
    authorized for `CategoryManager` only.

    Design: Corner/rbac/retailer_cannot_confirm_own_commitment_returns_unauthorized
    """
    world = setup_open_program()
    retailer = world["retailer"]
    submitted = create_submitted_commitment(
        world["program"], retailer, world["product"], committed_units=5,
    )
    resp = api_client.confirm_commitment(
        submitted["id"], make_retailer_headers(retailer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_commitment(submitted["id"])["status"] == CommitmentStatus.SUBMITTED.value


def test_retailer_cannot_submit_another_retailers_commitment(api):
    """PRD §2.1: "When `X-User-Role` is `Retailer`, `X-User-ID` is the `id` of
    the acting `RetailerAccount`; ownership checks on any resource that
    references a `RetailerAccount` compare the resource's `retailer_id` field
    to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`
    (HTTP 403)."

    Design: Corner/rbac/retailer_cannot_submit_another_retailers_commitment
    """
    world = setup_open_program()
    gold = world["retailer"]
    silver = create_retailer(tier="SILVER", everyday_baseline_weekly_units=800)
    draft = create_draft_commitment(
        world["program"], gold, world["product"], committed_units=5,
    )
    # SILVER's X-User-ID against GOLD's commitment: role allowed, owner not.
    resp = api_client.submit_commitment(
        draft["id"], make_retailer_headers(silver["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert get_commitment(draft["id"])["status"] == CommitmentStatus.DRAFT.value


def _setup_locked_with_draft():
    """Program OPEN -> commitment left DRAFT -> program LOCKED at close; the
    clock is then parked past commitment_close_on so the submit violates both
    the state rule and the temporal rule."""
    world = setup_open_program()
    draft = create_draft_commitment(
        world["program"], world["retailer"], world["product"], committed_units=10,
    )
    set_clock(CLOCK_AT_COMMITMENT_CLOSE)
    advance_program_to(world["program"]["id"], ProgramAdvanceTarget.LOCKED.value)
    set_clock("2027-02-20T00:00:00Z")
    return world, draft


def test_submit_on_locked_program_surfaces_program_not_open(api):
    """PRD §3.4: "Submission is guarded three ways, in the priority order of
    Section 2.8: ... the program must be `OPEN_FOR_COMMITMENTS`
    (`ERR_PROGRAM_NOT_OPEN`); and the logical clock must sit inside the
    half-open collection interval". PRD §2.8: "A request that violates several
    rules at once receives exactly one error, and the winner is determined by
    a fixed priority order; a lower priority number wins."

    Design: Difficulty/priority_pair_validation_conflict/submit_on_locked_program_state_beats_window_closed_temporal
    """
    world, draft = _setup_locked_with_draft()
    resp = api_client.submit_commitment(
        draft["id"], make_retailer_headers(world["retailer"]["id"]),
    )
    # Dual failure (LOCKED program AND closed window): state priority 7 wins
    # over temporal priority 9.
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)


def test_submit_on_locked_program_never_reports_window_closed(api):
    """PRD §2.8 priority 7 lists state-machine preconditions
    (`ERR_PROGRAM_NOT_OPEN` among them) ahead of priority 9 temporal windows
    (`ERR_COMMITMENT_WINDOW_CLOSED` among them): "7. **State-machine
    preconditions** ... 9. **Temporal windows**".

    Design: Difficulty/priority_pair_validation_conflict/submit_on_locked_program_state_beats_window_closed_temporal
    """
    world, draft = _setup_locked_with_draft()
    resp = api_client.submit_commitment(
        draft["id"], make_retailer_headers(world["retailer"]["id"]),
    )
    error = validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)
    assert error["error_id"] != ApiErrorId.ERR_COMMITMENT_WINDOW_CLOSED.value
    assert get_commitment(draft["id"])["status"] == CommitmentStatus.DRAFT.value
