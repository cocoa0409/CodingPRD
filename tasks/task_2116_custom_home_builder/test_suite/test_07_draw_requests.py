"""Draw requests: assembling the bill, the lender window, the cap and the compensating void."""

from test_helpers import (
    ApiErrorId,
    assert_draw_funding_arithmetic,
    assert_draw_request,
    assert_instant_equals,
    assert_money_equals,
    assert_money_not_equals,
    assert_project_ledger_invariants,
    create_draw_request_payload,
    list_lien_waivers,
    open_draw,
    post_and_approve_cost_entry,
    project_version,
    read_cost_entry,
    read_draw_request,
    read_project,
    set_clock,
    setup_job,
    setup_returned_draw_now_over_the_cap,
    setup_submitted_draw,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]

THREE_AUGUST_LINES = [
    {"amount": 10000.10, "incurred_at": "2026-08-10T00:00:00.000Z"},
    {"amount": 15000.10, "incurred_at": "2026-08-15T00:00:00.000Z"},
    {"amount": 20000.10, "incurred_at": "2026-08-20T00:00:00.000Z"},
]


def test_draw_retainage_is_rounded_per_line_and_then_summed(api):
    """PRD §3.6: "`retainage_amount` is **not** computed by applying the lender's rate to that
    sum; instead, each eligible entry's `amount` is multiplied by the lender's `retainage_pct`
    and rounded half up to two decimals **on that line**, and the already-rounded per-line
    figures are then added together. Summing the amounts first and applying the rate once
    produces a different number of cents and is explicitly not the rule."
    PRD §3.6: "`net_funding_amount` is `requested_amount` minus `retainage_amount`, rounded half
    up to two decimals. `included_cost_entry_count` records how many entries the draw pulled
    in."

    Design: Difficulty/combinatorial_formula/draw_retainage_rounded_per_line_then_summed
    """
    ctx = setup_submitted_draw(lines=THREE_AUGUST_LINES)
    draw = ctx["draw"]

    assert_draw_request(draw)
    assert_money_equals(draw["retainage_amount"], 2250.03, "retainage_amount")
    assert_money_not_equals(
        draw["retainage_amount"], 2250.02, "retainage_amount (sum-then-round)"
    )
    assert_money_equals(draw["net_funding_amount"], 42750.27, "net_funding_amount")
    assert_draw_funding_arithmetic(draw)


def test_draw_submission_records_the_requested_total_and_line_count(api):
    """PRD §3.6: "`requested_amount` is the sum of the eligible entries' `amount` values,
    rounded half up to two decimals."
    PRD §2.6: "`pending_draw_amount` is the sum of `requested_amount` across the project's draw
    requests whose status is `LENDER_REVIEW` or `CONDITIONALLY_APPROVED`. `funded_to_date` is
    the sum of `net_funding_amount` across the project's draw requests whose status is `FUNDED`,
    and `retainage_held` is the sum of `retainage_amount` across those same `FUNDED` draws."

    Design: Difficulty/combinatorial_formula/draw_retainage_rounded_per_line_then_summed
    """
    ctx = setup_submitted_draw(lines=THREE_AUGUST_LINES)
    draw = ctx["draw"]

    assert draw["status"] == "LENDER_REVIEW"
    assert draw["included_cost_entry_count"] == 3
    assert_money_equals(draw["requested_amount"], 45000.30, "requested_amount")

    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["pending_draw_amount"], 45000.30, "pending_draw_amount")
    assert_project_ledger_invariants(project)


def test_resubmitting_a_returned_draw_reports_the_state_refusal(api):
    """PRD §2.10: "Checks are evaluated in the following strict order, and the first check that
    fails ends the request; no later check may mask an earlier one."
    PRD §3.6: "The project must be `UNDER_CONSTRUCTION` or `SUBSTANTIAL_COMPLETION`; a
    submission from a draw whose status is not `DRAFT` is refused with `ERR_DRAW_NOT_IN_DRAFT`."
    PRD §2.10: "**Lender cumulative cap.** Cumulative draw exposure after this submission must
    not exceed the lender's cap as defined in §3.6, or `ERR_DRAW_EXCEEDS_LENDER_CAP` (422)."

    Design: Difficulty/priority_pair_validation_conflict/draw_state_error_precedes_lender_cap_error
    """
    ctx = setup_returned_draw_now_over_the_cap()

    response = api.submit_draw_request(ctx["draw"]["id"], ctx["controller_b_headers"])

    validate_error(response, ApiErrorId.ERR_DRAW_NOT_IN_DRAFT, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_DRAW_EXCEEDS_LENDER_CAP.value


def test_refused_resubmission_leaves_the_returned_draw_and_its_costs_untouched(api):
    """PRD §3.6: "**Returning** advances `LENDER_REVIEW → RETURNED`, stamps `returned_at` and
    stores the `condition_note`, sends every cost entry the draw was holding back from
    `INCLUDED_IN_DRAW` to `APPROVED`, voids every lien waiver on the draw sitting in
    `REQUESTED`, `RECEIVED`, or `REJECTED`, and recomputes the project's `pending_draw_amount`."

    Design: Difficulty/priority_pair_validation_conflict/draw_state_error_precedes_lender_cap_error
    """
    ctx = setup_returned_draw_now_over_the_cap()

    response = api.submit_draw_request(ctx["draw"]["id"], ctx["controller_b_headers"])
    validate_error(response, ApiErrorId.ERR_DRAW_NOT_IN_DRAFT, 409)

    assert read_draw_request(ctx["draw"]["id"])["status"] == "RETURNED"
    for entry in ctx["cost_entries"] + [ctx["late_cost_entry"]]:
        assert read_cost_entry(entry["id"])["status"] == "APPROVED"

    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["pending_draw_amount"], 0.00, "pending_draw_amount")


def test_draw_submission_with_no_cost_inside_the_period_is_refused(api):
    """PRD §3.6: "The eligible set is assembled first: every cost entry on the project whose
    status is `APPROVED` and whose `incurred_at` falls inside the billing period with **both
    ends inclusive**, ordered by `incurred_at` ascending with `created_at` ascending as the
    tie-break. Entries that are `PENDING`, `REJECTED`, already `INCLUDED_IN_DRAW`, or already
    `PAID` are excluded. If the eligible set is empty, the submission is refused with
    `ERR_DRAW_NO_ELIGIBLE_COSTS`."

    Design: Difficulty/boundary_precision_check/draw_submit_with_empty_eligible_cost_set_is_rejected
    """
    ctx = setup_job()
    post_and_approve_cost_entry(
        ctx, amount=10000.10, incurred_at="2026-08-10T00:00:00.000Z"
    )
    draw = open_draw(
        ctx,
        period_start="2026-09-01T00:00:00.000Z",
        period_end="2026-09-30T00:00:00.000Z",
    )

    response = api.submit_draw_request(draw["id"], ctx["controller_b_headers"])
    validate_error(response, ApiErrorId.ERR_DRAW_NO_ELIGIBLE_COSTS, 422)


def test_refused_empty_draw_stays_in_draft_with_nothing_requested(api):
    """PRD §3.6: "The new draw lands in `DRAFT` on its funding axis and `PENDING` on its waiver
    axis, with `requested_amount`, `retainage_amount`, `net_funding_amount`,
    `included_cost_entry_count`, `required_waiver_count`, and `verified_waiver_count` all at
    zero"
    PRD §2.6: "`pending_draw_amount` is the sum of `requested_amount` across the project's draw
    requests whose status is `LENDER_REVIEW` or `CONDITIONALLY_APPROVED`."

    Design: Difficulty/boundary_precision_check/draw_submit_with_empty_eligible_cost_set_is_rejected
    """
    ctx = setup_job()
    entry = post_and_approve_cost_entry(
        ctx, amount=10000.10, incurred_at="2026-08-10T00:00:00.000Z"
    )
    draw = open_draw(
        ctx,
        period_start="2026-09-01T00:00:00.000Z",
        period_end="2026-09-30T00:00:00.000Z",
    )
    validate_error(
        api.submit_draw_request(draw["id"], ctx["controller_b_headers"]),
        ApiErrorId.ERR_DRAW_NO_ELIGIBLE_COSTS,
        422,
    )

    stored = read_draw_request(draw["id"])
    assert stored["status"] == "DRAFT"
    assert_money_equals(stored["requested_amount"], 0, "requested_amount")
    assert read_cost_entry(entry["id"])["status"] == "APPROVED"
    assert_money_equals(
        read_project(ctx["project"]["id"])["pending_draw_amount"],
        0.00,
        "pending_draw_amount",
    )


def test_voiding_a_submitted_draw_restores_the_projects_cash_position(api):
    """PRD §3.6: "Withdrawing a draw in `LENDER_REVIEW` advances `LENDER_REVIEW → VOIDED` and
    performs the same compensation a lender return does: every `INCLUDED_IN_DRAW` cost entry
    goes back to `APPROVED`, every lien waiver in `REQUESTED`, `RECEIVED`, or `REJECTED` is
    voided, and `pending_draw_amount` is restored to its pre-submission value."
    PRD §2.6: "`eligible_cost_pool` is the narrower sum over cost entries whose status is
    `APPROVED` or `INCLUDED_IN_DRAW` only — it is the pool of money not yet paid out, and it is
    the quantity the draw machinery conserves."

    Design: Difficulty/compensating_invariant/draw_void_restores_eligible_cost_pool_and_pending_draw
    """
    ctx = setup_submitted_draw(lines=THREE_AUGUST_LINES)

    voided = validate_success(
        api.void_draw_request(
            ctx["draw"]["id"],
            {"void_reason": "Rebilling under a corrected period"},
            ctx["controller_b_headers"],
        ),
        200,
    )

    assert voided["status"] == "VOIDED"
    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["pending_draw_amount"], 0.00, "pending_draw_amount")
    assert_money_equals(project["eligible_cost_pool"], 45000.30, "eligible_cost_pool")
    assert_money_equals(project["cost_to_date"], 45000.30, "cost_to_date")
    assert_money_equals(project["funded_to_date"], 0.00, "funded_to_date")
    assert_money_equals(project["retainage_held"], 0.00, "retainage_held")
    assert_project_ledger_invariants(project)


def test_voiding_a_submitted_draw_releases_its_costs_and_kills_its_waivers(api):
    """PRD §3.5: "When a lender returns the draw or a controller withdraws it, each of those
    entries reverts `INCLUDED_IN_DRAW → APPROVED` with `draw_request_id` cleared back to null,
    and again neither `eligible_cost_pool` nor `cost_to_date` moves."
    PRD §3.7: "Waivers are killed en masse when the draw beneath them fails: whenever the
    parent draw reaches `RETURNED` or `VOIDED`, every one of its waivers sitting in `REQUESTED`,
    `RECEIVED`, or `REJECTED` advances to `VOIDED` — `REQUESTED → VOIDED`, `RECEIVED → VOIDED`,
    `REJECTED → VOIDED` alike — with `voided_at` stamped at the logical clock now."

    Design: Difficulty/compensating_invariant/draw_void_restores_eligible_cost_pool_and_pending_draw
    """
    ctx = setup_submitted_draw(lines=THREE_AUGUST_LINES)
    waivers_before = list_lien_waivers(ctx["draw"]["id"])
    assert waivers_before, "the framing trade requires a waiver, so one must exist"

    validate_success(
        api.void_draw_request(
            ctx["draw"]["id"],
            {"void_reason": "Rebilling under a corrected period"},
            ctx["controller_b_headers"],
        ),
        200,
    )

    for entry in ctx["cost_entries"]:
        stored = read_cost_entry(entry["id"])
        assert stored["status"] == "APPROVED"
        assert stored["draw_request_id"] is None

    for waiver in list_lien_waivers(ctx["draw"]["id"]):
        assert waiver["status"] == "VOIDED"


def test_draw_pulls_only_the_costs_inside_the_closed_billing_period(api):
    """PRD §3.6: "The eligible set is assembled first: every cost entry on the project whose
    status is `APPROVED` and whose `incurred_at` falls inside the billing period with **both
    ends inclusive**, ordered by `incurred_at` ascending with `created_at` ascending as the
    tie-break."
    PRD §3.6: "The draw's `waiver_compliance` is set to `COMPLETE` immediately when
    `required_waiver_count` is zero — a draw made entirely of owner-direct purchases needs no
    releases — and otherwise to `PENDING`."

    Design: Corner/calculations/draw_funding_excludes_cost_entries_outside_the_closed_period
    """
    ctx = setup_submitted_draw(
        lines=[
            {"amount": 10000.10, "incurred_at": "2026-08-10T00:00:00.000Z"},
            {"amount": 20000.10, "incurred_at": "2026-08-31T00:00:00.000Z"},
            {"amount": 15000.10, "incurred_at": "2026-09-05T00:00:00.000Z"},
        ],
        frame_waiver_required=False,
    )
    inside_one, inside_two, outside = ctx["cost_entries"]
    draw = ctx["draw"]

    assert draw["included_cost_entry_count"] == 2
    assert_money_equals(draw["requested_amount"], 30000.20, "requested_amount")
    assert_money_equals(draw["retainage_amount"], 1500.02, "retainage_amount")
    assert_money_equals(draw["net_funding_amount"], 28500.18, "net_funding_amount")
    assert draw["required_waiver_count"] == 0
    assert draw["waiver_compliance"] == "COMPLETE"

    assert read_cost_entry(inside_one["id"])["status"] == "INCLUDED_IN_DRAW"
    assert read_cost_entry(inside_two["id"])["status"] == "INCLUDED_IN_DRAW"
    stored_outside = read_cost_entry(outside["id"])
    assert stored_outside["status"] == "APPROVED"
    assert stored_outside["draw_request_id"] is None


def test_draw_cannot_be_opened_on_an_owner_financed_project(api):
    """PRD §3.6: "Only a `Controller` may open one, and only on a project that actually has a
    lender — a project whose `lender_id` is null refuses both the opening and the submission of
    a draw with `ERR_PROJECT_HAS_NO_LENDER`."

    Design: Corner/validations/draw_create_on_project_without_lender_returns_no_lender
    """
    ctx = setup_job(with_lender=False)
    post_and_approve_cost_entry(
        ctx, amount=10000.10, incurred_at="2026-08-10T00:00:00.000Z"
    )

    response = api.create_draw_request(
        create_draw_request_payload(
            ctx["project"]["id"], project_version(ctx["project"]["id"])
        ),
        ctx["controller_a_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_HAS_NO_LENDER, 422)

    rows, meta = validate_paginated(
        api.list_draw_requests(ADMIN, params={"project_id": ctx["project"]["id"]})
    )
    assert meta["total_count"] == 0


def test_draw_over_the_lender_cumulative_cap_is_refused(api):
    """PRD §3.6: "The cumulative-exposure gate compares the project's total draw exposure after
    this submission against the lender's ceiling: the ceiling is the lender's
    `max_cumulative_draw_pct` multiplied by the project's `contract_sum_current`, rounded half up
    to two decimals, and the exposure is the project's `funded_to_date` plus its
    `pending_draw_amount` plus this draw's freshly computed `requested_amount`, rounded half up
    to two decimals. The submission is refused with `ERR_DRAW_EXCEEDS_LENDER_CAP` only when the
    exposure is **strictly greater than** the ceiling; an exposure exactly equal to the ceiling
    is allowed through."

    Design: Corner/validations/draw_exceeding_lender_cap_from_draft_returns_cap_error
    """
    ctx = setup_job(
        base_contract_amount=50000.00,
        address="9 Alder Court",
        allowance_category="LIGHTING",
        allowance_amount=4000.00,
        frame_waiver_required=False,
    )
    entries = [
        post_and_approve_cost_entry(ctx, **line) for line in THREE_AUGUST_LINES
    ]
    draw = open_draw(ctx)

    response = api.submit_draw_request(draw["id"], ctx["controller_b_headers"])
    validate_error(response, ApiErrorId.ERR_DRAW_EXCEEDS_LENDER_CAP, 422)

    assert read_draw_request(draw["id"])["status"] == "DRAFT"
    for entry in entries:
        assert read_cost_entry(entry["id"])["status"] == "APPROVED"
    project = read_project(ctx["project"]["id"])
    assert_money_equals(project["pending_draw_amount"], 0.00, "pending_draw_amount")
    assert_money_equals(project["eligible_cost_pool"], 45000.30, "eligible_cost_pool")


def test_lender_decision_after_the_review_window_is_refused(api):
    """PRD §3.6: "`submitted_by_staff_id` and `submitted_at` are stamped, and
    `lender_decision_due_at` is computed as `submitted_at` advanced by the lender's
    `review_window_days` whole days."
    PRD §3.6: "Both outcomes require the acting lender to own the project and require the
    logical clock now to be at or before `lender_decision_due_at`; a decision arriving strictly
    after that instant is refused with `ERR_LENDER_DECISION_WINDOW_EXPIRED`, while a decision
    arriving exactly at it is still in time."

    Design: Corner/validations/lender_decision_after_review_window_returns_window_expired
    """
    ctx = setup_submitted_draw(
        lines=[{"amount": 10000.10, "incurred_at": "2026-08-01T00:00:00.000Z"}],
        frame_waiver_required=False,
    )
    assert_instant_equals(
        ctx["draw"]["lender_decision_due_at"],
        "2026-08-11T00:00:00.000Z",
        "lender_decision_due_at",
    )

    set_clock("2026-08-12T00:00:00.000Z")
    response = api.lender_decision(
        ctx["draw"]["id"], {"decision": "CONDITIONALLY_APPROVE"}, ctx["lender_headers"]
    )
    validate_error(response, ApiErrorId.ERR_LENDER_DECISION_WINDOW_EXPIRED, 409)

    stored = read_draw_request(ctx["draw"]["id"])
    assert stored["status"] == "LENDER_REVIEW"
    assert stored["conditionally_approved_at"] is None


def test_draw_opened_on_a_stale_project_version_is_refused(api):
    """PRD §2.8: "Opening a draw request against a project requires the request to carry
    `expected_project_version`, a non-optional field holding the `version` of the target
    `Project` as the controller last observed it. If that value does not equal the project's
    current `version`, the creation is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_project_version_on_draw_create_returns_412
    """
    ctx = setup_job()
    post_and_approve_cost_entry(
        ctx, amount=10000.10, incurred_at="2026-08-10T00:00:00.000Z"
    )
    stale_version = project_version(ctx["project"]["id"])
    first_draw = open_draw(ctx, expected_project_version=stale_version)

    response = api.create_draw_request(
        create_draw_request_payload(ctx["project"]["id"], stale_version),
        ctx["controller_b_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_PROJECT_VERSION, 412)

    stored = read_draw_request(first_draw["id"])
    assert stored["status"] == "DRAFT"
    assert stored["voided_at"] is None
    rows, meta = validate_paginated(
        api.list_draw_requests(ADMIN, params={"project_id": ctx["project"]["id"]})
    )
    assert meta["total_count"] == 1


def test_opening_a_draw_supersedes_the_previous_draft(api):
    """PRD §3.6: "Opening a draw supersedes any draw already sitting in `DRAFT` on the same
    project: that older draft advances `DRAFT → VOIDED` with `voided_at` stamped and
    `void_reason` set to the literal `SUPERSEDED_BY_NEWER_DRAFT`, and because a draft draw holds
    no cost entries, no cost disposition changes."

    Design: Corner/cross_cutting_complexity_layers/fresh_draft_draw_supersedes_the_previous_draft_draw
    """
    ctx = setup_job()
    entry = post_and_approve_cost_entry(
        ctx, amount=10000.10, incurred_at="2026-08-10T00:00:00.000Z"
    )
    first_draw = open_draw(ctx)

    response = api.create_draw_request(
        create_draw_request_payload(
            ctx["project"]["id"], project_version(ctx["project"]["id"])
        ),
        ctx["controller_b_headers"],
    )
    second_draw = validate_success(response, 201)

    superseded = read_draw_request(first_draw["id"])
    assert superseded["status"] == "VOIDED"
    assert superseded["void_reason"] == "SUPERSEDED_BY_NEWER_DRAFT"
    assert_instant_equals(
        superseded["voided_at"], "2026-08-01T00:00:00.000Z", "voided_at"
    )
    assert second_draw["status"] == "DRAFT"
    assert read_cost_entry(entry["id"])["status"] == "APPROVED"
    assert_money_equals(
        read_project(ctx["project"]["id"])["pending_draw_amount"],
        0.00,
        "pending_draw_amount",
    )
