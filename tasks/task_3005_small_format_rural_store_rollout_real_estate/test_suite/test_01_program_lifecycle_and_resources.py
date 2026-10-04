"""Program lifecycle defaults, event log, pagination, and resource lookups."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_capital_invariant,
    assert_rollout,
    assert_rollout_event,
    build_user_headers,
    create_active_rollout,
    create_existing_store,
    create_rollout,
    create_rollout_payload,
    create_developer,
    create_qualified_trade_area,
    create_trade_area,
    get_success_data,
    read_rollout,
    setup_store_site_control,
    setup_store_with_format,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
REAL_ESTATE = TEST_USERS["real_estate_manager_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]


def test_program_create_applies_defaults_and_envelope(api):
    """PRD §3.1: "A `PROGRAM_ADMIN` creates a rollout program by supplying a
    `name`, a `fiscal_year` label, the `new_build_capital_budget_cents` for the
    program, and optionally a `cannibalization_coefficient` — the sales-transfer
    coefficient used by cannibalization studies, defaulting to 0.40 when
    omitted. The program is born in `DRAFT` status with `committed_capital_cents`
    at 0."
    PRD §2.6: "`available_capital_cents`, which is always exactly
    `new_build_capital_budget_cents` minus `committed_capital_cents`."

    Design: Corner/entities/program_create_applies_defaults_and_envelope
    """
    response = api.create_rollout(create_rollout_payload(), ADMIN)
    # Check the success envelope: meta + response_type on the raw body.
    body = response.json()
    assert "meta" in body and "api_request_id" in body["meta"]
    assert "api_request_timestamp" in body["meta"]
    assert body["response_type"] == "object"

    rollout = validate_success(response, 201)
    assert_rollout(rollout)
    assert rollout["cannibalization_coefficient"] == 0.4
    assert rollout["status"] == "DRAFT"
    assert rollout["committed_capital_cents"] == 0
    assert rollout["available_capital_cents"] == 2000000000
    assert isinstance(rollout["version"], int) and rollout["version"] >= 1
    assert_capital_invariant(rollout)


def test_program_event_immutable_no_version_field(api):
    """PRD §2.4: "The exception is the `RolloutEvent` resource: events are
    append-only facts and carry only `id` and `created_at`; neither `updated_at`
    nor `version` exists on them."
    PRD §2.7: "Sequence numbers run strictly from 1 upward per program, assigned
    in `created_at` order; the first event ever appended to a program — normally
    its first activation — bears `sequence_number` 1."

    Design: Corner/entities/program_event_immutable_no_version_field
    """
    rollout = create_rollout()
    validate_success(api.activate_rollout(rollout["id"], ADMIN))

    resp = api.list_program_events(ADMIN, params={"rollout_program_id": rollout["id"]})
    events, _meta = validate_paginated(resp)
    assert len(events) == 1, f"expected exactly 1 event, got {len(events)}"
    assert_rollout_event(events[0])
    assert events[0]["event_type"] == "PROGRAM_ACTIVATED"
    assert events[0]["sequence_number"] == 1


def test_store_self_referential_existing_link(api):
    """PRD §3.3: "On the registration path the caller supplies `format_type`
    directly — `TRADITIONAL`, `DG_FRESH`, or `DG_MARKET` — and may link the
    record to the legacy store it replaces via `existing_store_id`, a
    self-referential link for which cross-program references are allowed
    (greenfield pipeline stores carry `existing_store_id` null)."
    PRD §2.3: "stores filter by `status`, `format_type`, `trade_area_id`, and
    `existing_store_id`"

    Design: Corner/entities/store_self_referential_existing_link
    """
    rollout = create_active_rollout(name="P")
    ta = create_trade_area(
        rollout["id"], name="T0", drive_time_minutes=12, household_count=1000,
        median_household_income_cents=4000000, grocery_gap_pct=20,
    )
    ex = create_existing_store(rollout["id"], ta["id"], name="X")
    ex2 = create_existing_store(
        rollout["id"], ta["id"], name="X2",
        existing_store_id=ex["id"], open_year_sales_cents=60000000,
    )
    assert ex2["existing_store_id"] == ex["id"]
    assert ex2["status"] == "EXISTING"

    resp = api.list_stores(ADMIN, params={"existing_store_id": ex["id"]})
    stores, _meta = validate_paginated(resp)
    assert len(stores) == 1, f"expected exactly 1 linked store, got {len(stores)}"
    assert stores[0]["id"] == ex2["id"]


def test_trade_area_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items skipped and defaults to 0. All
    list endpoints sort by `created_at` ascending. The `meta` object of every
    list response carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/trade_area_list_pagination_envelope
    """
    rollout = create_active_rollout(name="P")
    for i in (1, 2, 3):
        create_trade_area(rollout["id"], name=f"A{i}", drive_time_minutes=19 + i)

    resp = api.list_trade_areas(ADMIN, params={"limit": 2, "offset": 0})
    areas, meta = validate_paginated(resp)
    assert len(areas) == 2, f"limit=2 should return 2 entries, got {len(areas)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True


def test_get_missing_store_returns_not_found(api):
    """PRD §2.11: "path existence — path resources must exist and chain
    correctly, else `ERR_NOT_FOUND`"

    Design: Corner/entities/get_missing_store_returns_not_found
    """
    rollout = create_rollout(name="P")
    resp = api.get_store(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_deactivate_with_pipeline_store_blocked(api):
    """PRD §3.1: "A store in `SITE_CONTROL`, `UNDER_CONSTRUCTION`, or `DELIVERED`
    blocks deactivation with `ERR_PROGRAM_HAS_ACTIVE_STORES`; stores in
    `PROPOSED`, `KILLED`, `OPEN`, or `EXISTING` do not."

    Design: Corner/state_machines/deactivate_with_pipeline_store_blocked
    """
    rollout = create_active_rollout(name="P")
    # An EXISTING store alone would not block deactivation.
    ta0 = create_trade_area(
        rollout["id"], name="T0", drive_time_minutes=12, household_count=1000,
        median_household_income_cents=4000000, grocery_gap_pct=20,
    )
    create_existing_store(rollout["id"], ta0["id"], name="X")

    # Keep the new area outside the 10-minute overlap window of T0 (dt 12)
    # while staying at/above the 40 qualification threshold: dt 23 gives a
    # standard score of 40.61 and is 11 minutes away, so no overlap applies.
    ta = create_qualified_trade_area(rollout["id"], name="C", drive_time_minutes=23)
    store = setup_store_with_format(rollout["id"], ta["id"])
    _dev, agreement = setup_store_site_control(rollout["id"], store["id"])
    assert agreement["status"] == "EXECUTED"

    resp = api.deactivate_rollout(rollout["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_ACTIVE_STORES)

    # Program stays ACTIVE.
    assert read_rollout(rollout["id"])["status"] == "ACTIVE"


def test_close_blocked_by_undecided_capital_project(api):
    """PRD §3.1: "From either source state, every capital project in the
    program must have reached a decision — `APPROVED`, `REJECTED`, or
    `CANCELLED` — or the close is rejected with `ERR_PROGRAM_CLOSE_BLOCKED`."

    Design: Corner/state_machines/close_blocked_by_undecided_capital_project
    """
    rollout = create_active_rollout(name="P")
    ta = create_trade_area(
        rollout["id"], name="T0", drive_time_minutes=12, household_count=1000,
        median_household_income_cents=4000000, grocery_gap_pct=20,
    )
    existing = create_existing_store(rollout["id"], ta["id"], name="X")
    cp = get_success_data(
        api.create_capital_project(
            {
                "rollout_program_id": rollout["id"],
                "kind": "REMODEL",
                "store_id": existing["id"],
                "remodel_cost_cents": 80000000,
                "projected_uplift_cents": 60000000,
            },
            FINANCE,
        )
    )
    assert cp.get("id"), f"Setup failed creating capital project: {cp}"
    submitted = get_success_data(
        api.submit_capital_project(
            cp["id"], {"rollout_program_id": rollout["id"]}, FINANCE
        )
    )
    assert submitted.get("status") == "SUBMITTED", f"Setup failed: {submitted}"

    resp = api.close_rollout(rollout["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSE_BLOCKED)
    assert read_rollout(rollout["id"])["status"] == "ACTIVE"


def test_error_unauthenticated_unknown_role_header(api):
    """PRD §2.1: "A request whose `X-User-Role` header is missing or whose
    value is not one of these five roles is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_unknown_role_header
    """
    bogus_headers = build_user_headers("somebody", "NO_SUCH_ROLE")
    resp = api.create_rollout(create_rollout_payload(), bogus_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
