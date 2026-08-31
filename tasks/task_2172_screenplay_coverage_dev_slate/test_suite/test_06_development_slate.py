"""The development slate: two independent axes, turnaround and reversion."""

from test_helpers import (
    ADMIN,
    BA_APPROVER,
    EXEC_ALPHA,
    ApiErrorId,
    assert_development_project,
    assert_instant_equals,
    create_engagement,
    create_project,
    create_writer,
    exercise_option,
    fetch_engagement,
    fetch_option,
    fetch_project,
    fetch_property,
    fetch_writer,
    milestones_for_engagement,
    place_in_turnaround,
    project_version,
    seat_committee,
    set_clock,
    setup_clear_property_with_active_option,
    setup_development_pipeline,
    setup_owned_draft_delivered_project,
    validate_error,
    validate_paginated,
    validate_success,
)


# ==========================================================================
# Two axes evolving independently
# ==========================================================================


def _writing_project_on_an_unexercised_option():
    set_clock("2026-09-01T00:00:00Z")
    return setup_development_pipeline(
        genre="DRAMA", title="Riverkeeper", exercise=False, attach=True
    )


def test_exercising_the_option_moves_only_the_rights_axis(api):
    """PRD 3.6: "A project carries `rights_status` and `development_status` as
    parallel state machines, and neither drives the other except where explicitly
    stated."
    PRD 3.5: "On success `exercise_notice_at` is stamped from the logical clock,
    `net_purchase_due_cents` is recomputed, and the linked project's rights axis flips
    `OPTIONED → OWNED`."

    Design: Difficulty/non_linear_state_machine/development_project_parallel_axes_rights_moves_alone
    """
    ctx = _writing_project_on_an_unexercised_option()
    before = fetch_project(ctx["project"]["id"])
    assert before["rights_status"] == "OPTIONED"
    assert before["development_status"] == "WRITING"

    resp = api.exercise_option(ctx["option"]["id"], BA_APPROVER)
    option = validate_success(resp, 200)
    assert option["status"] == "EXERCISED"

    project = fetch_project(ctx["project"]["id"])
    assert_development_project(project)
    assert project["rights_status"] == "OWNED"
    assert project["development_status"] == "WRITING", (
        "the development axis must not move when the rights axis does"
    )


def test_rights_axis_move_leaves_the_engagement_and_greenlight_flag_alone(api):
    """PRD 3.6: "The `greenlight_ready` flag is a convenience derived from both axes
    at once: it is true exactly when `rights_status` is `OWNED` and
    `development_status` is either `DRAFT_DELIVERED` or `POLISH_DELIVERED`, and false
    otherwise."
    PRD 3.5: "On success `option_end_at` is set to `option_start_at` advanced by
    `initial_period_months` calendar months under the clamping rule of Section 2.5,
    the four pricing fields are computed, and the property's `encumbrance_count`
    increments by one."

    Design: Difficulty/non_linear_state_machine/development_project_parallel_axes_rights_moves_alone
    """
    ctx = _writing_project_on_an_unexercised_option()
    exercise_option(ctx["option"]["id"])

    assert fetch_engagement(ctx["engagement"]["id"])["status"] == "ATTACHED"
    project = fetch_project(ctx["project"]["id"])
    assert project["greenlight_ready"] is False, (
        "OWNED plus WRITING is not a greenlight-ready posture"
    )
    assert fetch_option(ctx["option"]["id"])["net_purchase_due_cents"] == 98_500_000
    assert fetch_property(ctx["property"]["id"])["encumbrance_count"] == 1


# ==========================================================================
# Turnaround
# ==========================================================================


def test_place_in_turnaround_cascades_down_to_milestones_and_the_writer(api):
    """PRD 3.8: "Link one: `turnaround_start_at` is stamped from the logical clock,
    and `turnaround_eligible_at` is that instant advanced by eighteen calendar months
    under the day-of-month clamping rule of Section 2.5."
    PRD 3.8: "Link two, caused by the project entering turnaround: every engagement on
    the project in `PROPOSED`, `ATTACHED` or `ACTIVE` status becomes `TERMINATED`."
    PRD 3.8: "Link three, caused by those terminations: each of their milestone
    payments in `SCHEDULED`, `DUE` or `APPROVED` status becomes `VOIDED`, and each
    affected writer's `committed_fee_cents` and `active_engagement_count` are reduced
    accordingly."

    Design: Corner/state_machines/place_in_turnaround_cascades_down_to_milestones_and_writer
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(genre="DRAMA", title="Shelved", attach=True)
    assert fetch_writer(ctx["writer"]["id"])["committed_fee_cents"] == 10_000_003

    resp = api.place_in_turnaround(
        ctx["project"]["id"], {"reason": "Slate re-prioritised."}, EXEC_ALPHA
    )
    data = validate_success(resp, 200)

    assert data["development_status"] == "TURNAROUND"
    assert data["rights_status"] == "OPTIONED", "the rights axis is untouched"
    assert_instant_equals(
        data["turnaround_start_at"], "2026-09-01T00:00:00Z", "turnaround_start_at"
    )
    assert_instant_equals(
        data["turnaround_eligible_at"], "2028-03-01T00:00:00Z", "turnaround_eligible_at"
    )
    assert data["committed_writer_fee_cents"] == 0

    assert fetch_engagement(ctx["engagement"]["id"])["status"] == "TERMINATED"
    rows = milestones_for_engagement(ctx["engagement"]["id"])
    assert len(rows) == 3
    assert all(row["status"] == "VOIDED" for row in rows)

    writer = fetch_writer(ctx["writer"]["id"])
    assert writer["committed_fee_cents"] == 0
    assert writer["active_engagement_count"] == 0


def test_state_check_on_engagement_create_outranks_the_budget_check(api):
    """PRD 2.6: "The ladder below is evaluated strictly top to bottom; a check never
    masks one above it, and a check never fires before one above it has passed."
    PRD 2.6: "**Fiscal constraints**, last of all: the project writer-budget headroom
    test, failing with `ERR_BUDGET_EXCEEDED` (409) on both engagement creation and
    engagement attachment; and the guild minimum test, failing with
    `ERR_GUILD_MINIMUM_VIOLATION` (422) on engagement creation."
    PRD 3.7: "A project whose `development_status` is `GREENLIT`, `TURNAROUND` or
    `DEAD` cannot take a new proposal at all; that attempt is `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/turnaround_state_check_beats_budget_check_on_engagement_create
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(
        genre="HORROR", title="Basement Nine", with_writer=False
    )
    place_in_turnaround(ctx["project"]["id"], reason="Cast attachment collapsed.")
    writer = create_writer()

    resp = api.create_writer_engagement(
        {
            "project_id": ctx["project"]["id"],
            "writer_id": writer["id"],
            "engagement_type": "ORIGINAL_DRAFT",
            "total_fee_cents": 300_000_000,
            "start_date": "2026-09-05",
            "end_date": "2027-01-05",
            "expected_project_version": project_version(ctx["project"]["id"]),
        },
        EXEC_ALPHA,
    )
    error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert error["error_id"] != ApiErrorId.ERR_BUDGET_EXCEEDED.value, (
        "the parent-state rung is reported ahead of the fiscal rung"
    )


def test_engagement_refused_on_a_turnaround_project_writes_nothing(api):
    """PRD 2.6: "When a request violates more than one rule, the service reports the
    highest-precedence violation and stops."
    PRD 3.7: "The budget headroom test: the project's `committed_writer_fee_cents`
    plus the proposed `total_fee_cents` must be at or below the project's
    `writer_budget_cap_cents` — the bound is inclusive, so a proposal landing exactly
    on the cap is admissible — and a proposal that would breach it is refused with
    `ERR_BUDGET_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/turnaround_state_check_beats_budget_check_on_engagement_create
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(
        genre="HORROR", title="Basement Nine", with_writer=False
    )
    place_in_turnaround(ctx["project"]["id"], reason="Cast attachment collapsed.")
    writer = create_writer()

    resp = api.create_writer_engagement(
        {
            "project_id": ctx["project"]["id"],
            "writer_id": writer["id"],
            "engagement_type": "ORIGINAL_DRAFT",
            "total_fee_cents": 300_000_000,
            "start_date": "2026-09-05",
            "end_date": "2027-01-05",
            "expected_project_version": project_version(ctx["project"]["id"]),
        },
        EXEC_ALPHA,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    _, meta = validate_paginated(
        api.list_writer_engagements(EXEC_ALPHA, {"project_id": ctx["project"]["id"]})
    )
    assert meta["total_count"] == 0
    assert fetch_writer(writer["id"])["committed_fee_cents"] == 0
    project = fetch_project(ctx["project"]["id"])
    assert project["committed_writer_fee_cents"] == 0
    assert project["development_status"] == "TURNAROUND"
    assert project["writer_budget_cap_cents"] == 240_000_000


# ==========================================================================
# Reversion
# ==========================================================================


def _project_in_turnaround(clock: str, initial_period_months: int, genre: str, title: str):
    set_clock(clock)
    ctx = setup_clear_property_with_active_option(
        genre=genre,
        title=title,
        option_overrides={
            "initial_period_months": initial_period_months,
            "option_start_at": clock,
        },
    )
    project = create_project(
        ctx["property"]["id"], ctx["option"]["id"], budget_cents=2_000_000_000,
        slate_year=2029,
    )
    exercise_option(ctx["option"]["id"])
    place_in_turnaround(project["id"], reason="No director.")
    return {"property": ctx["property"], "option": ctx["option"], "project": project}


def test_reversion_notice_at_exact_maturity_reverts_rights_and_clouds_the_chain(api):
    """PRD 3.8: "The reversion clock is eighteen months long and its lower bound is
    inclusive: a reversion notice is admissible when the logical clock reads
    `turnaround_eligible_at` exactly, as well as any time after."
    PRD 3.8: "Serving it takes the project `TURNAROUND → DEAD` on the development axis
    and `OWNED → REVERTED` on the rights axis, moves the option agreement `EXERCISED →
    REVERTED`, decrements the property's `encumbrance_count` by one, and — because a
    reversion clouds the chain of title until it is re-papered — drops the property's
    `rights_chain_status` from `CLEAR` back to `PARTIAL` when it was `CLEAR`, leaving
    it alone when it was anything else."

    Design: Corner/state_machines/reversion_notice_at_exact_maturity_reverts_rights_and_clouds_chain
    """
    ctx = _project_in_turnaround(
        "2026-09-01T00:00:00Z", 24, "SCIFI", "Reverted Rights"
    )
    set_clock("2028-03-01T00:00:00Z")

    resp = api.serve_reversion_notice(ctx["project"]["id"], BA_APPROVER)
    data = validate_success(resp, 200)

    assert_instant_equals(
        data["turnaround_eligible_at"], "2028-03-01T00:00:00Z", "turnaround_eligible_at"
    )
    assert data["rights_status"] == "REVERTED"
    assert data["development_status"] == "DEAD"
    assert fetch_option(ctx["option"]["id"])["status"] == "REVERTED"

    stored_property = fetch_property(ctx["property"]["id"])
    assert stored_property["encumbrance_count"] == 0
    assert stored_property["rights_chain_status"] == "PARTIAL"


def test_reversion_notice_one_day_early_returns_turnaround_not_mature(api):
    """PRD 3.8: "Business affairs serves that notice, and it is refused with
    `ERR_TURNAROUND_NOT_MATURE` while the clock is still short of the eligibility
    instant."
    PRD 2.5: "In both, advancing an instant by a whole number of calendar months means
    moving to the same day-of-month in the target month, preserving the time-of-day
    component exactly; when the target month has no such day-of-month, the result
    clamps to the last valid day of that month."

    Design: Corner/validations/reversion_notice_one_day_early_returns_turnaround_not_mature
    """
    ctx = _project_in_turnaround(
        "2026-08-31T00:00:00Z", 24, "THRILLER", "Clamped Month"
    )
    set_clock("2028-02-28T00:00:00Z")

    resp = api.serve_reversion_notice(ctx["project"]["id"], BA_APPROVER)
    validate_error(resp, ApiErrorId.ERR_TURNAROUND_NOT_MATURE, 409)

    project = fetch_project(ctx["project"]["id"])
    assert_instant_equals(
        project["turnaround_start_at"], "2026-08-31T00:00:00Z", "turnaround_start_at"
    )
    assert_instant_equals(
        project["turnaround_eligible_at"],
        "2028-02-29T00:00:00Z",
        "turnaround_eligible_at",
    )
    assert project["development_status"] == "TURNAROUND"
    assert project["rights_status"] == "OWNED"
    assert fetch_option(ctx["option"]["id"])["status"] == "EXERCISED"

    stored_property = fetch_property(ctx["property"]["id"])
    assert stored_property["encumbrance_count"] == 1
    assert stored_property["rights_chain_status"] == "CLEAR"


# ==========================================================================
# Stale-version protection on the two superseding project creates
# ==========================================================================


def test_stale_project_version_on_engagement_create_returns_stale_version(api):
    """PRD 2.7: "`POST /writer-engagements` requires `expected_project_version`,
    matching the current `version` of the `DevelopmentProject` named by `project_id`."
    PRD 2.7: "If that value does not equal the parent's current `version`, the request
    is rejected with `ERR_STALE_VERSION` and HTTP 412, and nothing is created or
    superseded."

    Design: Corner/cross_cutting_layers/occ_stale_project_version_on_engagement_create_returns_412
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_clear_property_with_active_option(
        genre="DRAMA", title="Stale Project View"
    )
    project = create_project(
        ctx["property"]["id"], ctx["option"]["id"], budget_cents=2_000_000_000
    )
    observed_version = project["version"]
    first_writer = create_writer(name="W1 Ferrante")
    second_writer = create_writer(name="W2 Okonjo")
    first = create_engagement(
        project["id"], first_writer["id"], expected_project_version=observed_version
    )

    resp = api.create_writer_engagement(
        {
            "project_id": project["id"],
            "writer_id": second_writer["id"],
            "engagement_type": "ORIGINAL_DRAFT",
            "total_fee_cents": 9_000_000,
            "start_date": "2026-09-05",
            "end_date": "2027-01-05",
            "expected_project_version": observed_version,
        },
        EXEC_ALPHA,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    stored = fetch_engagement(first["id"])
    assert stored["status"] == "PROPOSED", "the rejected create supersedes nothing"
    assert stored["termination_reason"] is None
    _, meta = validate_paginated(
        api.list_writer_engagements(EXEC_ALPHA, {"project_id": project["id"]})
    )
    assert meta["total_count"] == 1
    assert fetch_writer(second_writer["id"])["committed_fee_cents"] == 0


def test_stale_project_version_on_greenlight_create_returns_stale_version(api):
    """PRD 2.7: "`POST /greenlight-reviews` requires `expected_project_version`,
    matching the current `version` of the `DevelopmentProject` named by `project_id`."
    PRD 3.9: "Convening is a superseding create: every other review on the same
    project still in `OPEN` or `VOTING` becomes `WITHDRAWN` with `withdrawal_reason`
    set to `SUPERSEDED_BY_NEW_REVIEW`, and the project's `version` increments by one."

    Design: Corner/cross_cutting_layers/occ_stale_project_version_on_greenlight_create_returns_412
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_owned_draft_delivered_project(genre="DRAMA", title="Double Convene")
    seat_committee(
        (
            {"display_name": "M1 Chair", "vote_weight_bps": 4000, "veto_power": False},
            {"display_name": "M2 Marketing", "vote_weight_bps": 3000, "veto_power": False},
            {"display_name": "M3 Finance", "vote_weight_bps": 3000, "veto_power": False},
        )
    )
    observed_version = project_version(ctx["project"]["id"])
    first_review = validate_success(
        api.create_greenlight_review(
            {
                "project_id": ctx["project"]["id"],
                "session_date": "2026-10-01",
                "expected_project_version": observed_version,
            },
            ADMIN,
        ),
        201,
    )

    resp = api.create_greenlight_review(
        {
            "project_id": ctx["project"]["id"],
            "session_date": "2026-10-08",
            "expected_project_version": observed_version,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    stored = validate_success(
        api.get_greenlight_review(first_review["id"], ADMIN)
    )
    assert stored["status"] == "OPEN", "the rejected convene withdraws nothing"
    assert stored["withdrawal_reason"] is None
    _, meta = validate_paginated(
        api.list_greenlight_reviews(ADMIN, {"project_id": ctx["project"]["id"]})
    )
    assert meta["total_count"] == 1
