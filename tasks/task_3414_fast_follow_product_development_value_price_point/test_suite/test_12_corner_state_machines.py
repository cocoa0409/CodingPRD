"""State-machine corners: cyclic trend re-evaluation, terminal lockdown, the
formula round budget's auto-abandon, product-kill compensation, non-idempotent
acceptance, settlement gating, review-cancellation cascade, the sampling
dimension's EXECUTED gate, and commit side effects.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_footprint_conservation,
    commit_slot,
    create_formula_project,
    create_manufacturer,
    create_product,
    create_quote,
    create_selected_concept,
    create_selected_trend,
    create_trend,
    evaluate_quote,
    read_concept,
    read_cost_quote,
    read_launch_plan,
    read_partner,
    read_planogram_slot,
    reject_formula_sample,
    set_clock,
    set_sampling_status,
    setup_accepted_quote_product,
    setup_compliance_gate_product,
    setup_decided_review_with_slot,
    setup_locked_plan,
    setup_product_with_approved_formula,
    submit_formula_sample,
    transition_line_review,
    transition_product,
    transition_trend,
    validate_error,
    validate_paginated,
)

_SCOUT = TEST_USERS["trend_scout_headers"]
_SOURCING = TEST_USERS["sourcing_lead_headers"]
_MARKETING = TEST_USERS["marketing_lead_headers"]


def test_parked_trend_reevaluation_recomputes_score_and_restamps(api):
    """PRD §3.1: "the same recompute-and-stamp happens whenever a `PARKED`
    signal re-enters `EVALUATING`, so the score always reflects the field
    values at the most recent evaluation."
    Parked at 2026-09-01 and re-evaluated at 2026-09-08: the recomputed score
    is again 70.0 (inputs unchanged) and evaluated_at moves to the new
    logical-clock instant.

    Design: Corner/state_machines/trend_park_and_reevaluate_cycle_recomputes_score
    """
    set_clock()
    trend = create_trend()
    transition_trend(trend["id"], "EVALUATING")

    parked = transition_trend(trend["id"], "PARKED")
    assert parked["status"] == "PARKED"

    set_clock("2026-09-08T00:00:00Z")
    reevaluated = transition_trend(trend["id"], "EVALUATING")

    assert reevaluated["status"] == "EVALUATING"
    assert reevaluated["momentum_score"] == pytest.approx(70.0)
    assert reevaluated["evaluated_at"] == "2026-09-08T00:00:00Z"


def test_archived_trend_rejects_all_further_transitions(api):
    """PRD §2.10: "terminal states are locked — no transition out of a
    terminal state is valid, and any such attempt is rejected with
    `ERR_INVALID_STATE`."
    PRD §3.1: "`SELECTED` and `ARCHIVED` are terminal."
    An ARCHIVED signal rejects EVALUATING and SELECTED alike, and nothing
    changes.

    Design: Corner/state_machines/archived_trend_rejects_all_further_transitions
    """
    set_clock()
    trend = create_trend()
    transition_trend(trend["id"], "ARCHIVED")

    validate_error(
        api.patch_trend_signal(trend["id"], {"status": "EVALUATING"}, _SCOUT),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    validate_error(
        api.patch_trend_signal(trend["id"], {"status": "SELECTED"}, _SCOUT),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    rows, meta = validate_paginated(
        api.list_trend_signals(headers=_SCOUT, params={"status": "ARCHIVED"})
    )
    assert [row["id"] for row in rows] == [trend["id"]]
    assert rows[0]["momentum_score"] is None


def test_formula_project_auto_abandons_at_the_third_rejection(api):
    """PRD §3.4: "Rejecting a sample returns the project to `IN_DEVELOPMENT`
    and increments `round_count` by one — unless the project is already at its
    third round, the maximum, in which case the rejection instead
    auto-transitions the project to `ABANDONED`, and the project can no longer
    supply an approvable formula."
    Rejections move the round count 1 -> 2 -> 3; the third rejection lands in
    ABANDONED, which is terminal.

    Design: Corner/state_machines/formula_project_auto_abandoned_at_max_rounds
    """
    set_clock()
    trend = create_selected_trend()
    concept = create_selected_concept(trend["id"])
    manufacturer = create_manufacturer()
    product = create_product(concept["id"])
    project = create_formula_project(product["id"], manufacturer["id"])
    assert project["round_count"] == 1

    submit_formula_sample(project["id"], manufacturer["id"])
    round_two = reject_formula_sample(project["id"])
    assert round_two["status"] == "IN_DEVELOPMENT"
    assert round_two["round_count"] == 2

    submit_formula_sample(project["id"], manufacturer["id"])
    round_three = reject_formula_sample(project["id"])
    assert round_three["status"] == "IN_DEVELOPMENT"
    assert round_three["round_count"] == 3

    submit_formula_sample(project["id"], manufacturer["id"])
    final = reject_formula_sample(project["id"])
    assert final["status"] == "ABANDONED"

    validate_error(
        api.patch_formula_project(project["id"], {"status": "SAMPLE_REVIEW"}, _SOURCING),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_product_kill_reverts_concept_and_supersedes_quotes(api):
    """PRD §3.3: "A manager may also kill a product from any of `FORMULATION`,
    `SOURCING`, or `COMPLIANCE_GATE`; killing moves the linked concept back to
    `SELECTED` for a later revision and moves every non-terminal quote for the
    product — those in `SUBMITTED`, `UNDER_EVALUATION`, or `ACCEPTED` — to
    `SUPERSEDED`."
    The killed SOURCING product frees its concept for a fresh product and
    supersedes the UNDER_EVALUATION quote atomically.

    Design: Corner/state_machines/product_kill_reverts_concept_and_supersedes_quotes
    """
    ctx = setup_product_with_approved_formula()
    transition_product(ctx["product"]["id"], "SOURCING")
    quote = create_quote(ctx["product"]["id"], ctx["manufacturer"]["id"])
    evaluate_quote(quote["id"])

    killed = transition_product(ctx["product"]["id"], "KILLED")

    assert killed["status"] == "KILLED"
    assert read_concept(ctx["concept"]["id"])["status"] == "SELECTED"
    assert read_cost_quote(quote["id"])["status"] == "SUPERSEDED"
    fresh = create_product(ctx["concept"]["id"])
    assert fresh["status"] == "FORMULATION"
    assert fresh["id"] != ctx["product"]["id"]


def test_quote_double_accept_is_rejected_without_repinning(api):
    """PRD §2.8: "Seventh, state-machine from-state validity, including
    terminal-state lockdown, the from-state rules of the parallel packaging
    and sampling dimensions, and cross-entity state preconditions that have no
    more specific error (else `ERR_INVALID_STATE`)."
    PRD §3.5: "Acceptance stamps `accepted_at`, pins `pinned_formula_version`
    to the approved project's `formula_version`, consumes one quarterly
    production slot, and supersedes every other quote for the same product
    still in `SUBMITTED` or `UNDER_EVALUATION`."
    Repeating ACCEPTED on an already-ACCEPTED quote is a 409; the pin and the
    acceptance stamp are untouched.

    Design: Corner/state_machines/quote_double_accept_rejected_invalid_state
    """
    ctx = setup_accepted_quote_product()
    quote = ctx["quote"]
    assert quote["status"] == "ACCEPTED"
    assert quote["accepted_at"] == "2026-09-01T00:00:00Z"

    validate_error(
        api.patch_cost_quote(quote["id"], {"status": "ACCEPTED"}, _SOURCING),
        ApiErrorId.ERR_INVALID_STATE.value,
    )

    after = read_cost_quote(quote["id"])
    assert after["status"] == "ACCEPTED"
    assert after["pinned_formula_version"] == 1
    assert after["accepted_at"] == "2026-09-01T00:00:00Z"


def test_quote_settle_requires_launched_product(api):
    """PRD §3.5: "Once the product has launched — and only then — a sourcing
    lead may settle an accepted quote, moving it from `ACCEPTED` to `SETTLED`
    and supplying the actuals `actual_qty` and `actual_freight_total_cents`;
    attempting settlement while the product is anywhere short of `LAUNCHED` is
    rejected with `ERR_INVALID_STATE`."
    The product sits in COMPLIANCE_GATE, so settlement is a 409 and
    landed_settled_cents stays null.

    Design: Corner/state_machines/quote_settle_requires_launched_product
    """
    ctx = setup_compliance_gate_product()

    response = api.patch_cost_quote(
        ctx["quote"]["id"],
        {"status": "SETTLED", "actual_qty": 2000, "actual_freight_total_cents": 70000},
        _SOURCING,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    after = read_cost_quote(ctx["quote"]["id"])
    assert after["status"] == "ACCEPTED"
    assert after["landed_settled_cents"] is None


def test_line_review_cancel_releases_slot_and_reverts_plan(api):
    """PRD §3.7: "A review in any of `SCHEDULED`, `SUBMISSION_OPEN`,
    `REVIEWING`, or `DECIDED` may instead be cancelled; cancellation moves the
    review's `PROPOSED` slots to `WITHDRAWN` and its `COMMITTED` slots to
    `RELEASED`, freeing their facings, and each released slot reverts its
    quantity-locked or approved launch plan to `DRAFT` with its locked
    quantity cleared."
    Cancelling the DECIDED review releases its COMMITTED slot and reverts the
    QUANTITY_LOCKED plan to DRAFT with the lock fields cleared.

    Design: Corner/state_machines/line_review_cancel_releases_committed_slot_and_reverts_plan
    """
    ctx = setup_locked_plan()

    cancelled = transition_line_review(ctx["line_review"]["id"], "CANCELLED")

    assert cancelled["status"] == "CANCELLED"
    assert read_planogram_slot(ctx["slot"]["id"])["status"] == "RELEASED"
    plan = read_launch_plan(ctx["plan"]["id"])
    assert plan["status"] == "DRAFT"
    assert plan["qty_locked_units"] is None
    assert plan["landed_locked_cents"] is None
    partner = read_partner(ctx["partner"]["id"])
    assert partner["available_facings"]["EYES"] == 10
    assert_footprint_conservation(partner)


def test_sampling_activate_requires_executed_plan(api):
    """PRD §3.8: "The marketing lead may move `sampling_status` from `NONE` to
    `PLANNED` while the plan is in `QUANTITY_LOCKED`, `APPROVED`, or
    `EXECUTED` — any other plan state is rejected with `ERR_INVALID_STATE` —
    from `PLANNED` to `ACTIVE` only while the plan is `EXECUTED`, and from
    `ACTIVE` to `CLOSED`; once closed, no further distribution events are
    accepted, and any attempted one is rejected with `ERR_INVALID_STATE`."
    While the plan is QUANTITY_LOCKED, PLANNED -> ACTIVE is a 409 and the
    dimension stays PLANNED.

    Design: Corner/state_machines/sampling_activate_requires_executed_plan
    """
    ctx = setup_locked_plan()

    planned = set_sampling_status(ctx["plan"]["id"], "PLANNED")
    assert planned["sampling_status"] == "PLANNED"

    response = api.patch_launch_plan(
        ctx["plan"]["id"], {"sampling_status": "ACTIVE"}, _MARKETING
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    after = read_launch_plan(ctx["plan"]["id"])
    assert after["sampling_status"] == "PLANNED"
    assert after["status"] == "QUANTITY_LOCKED"


def test_slot_commit_stamps_committed_at_and_recomputes_facings(api):
    """PRD §3.7: "A successful commit stamps `committed_at` — the eviction
    ordering key of §3.7's capacity revision rule — and recomputes the
    partner's facing availability."
    PRD §2.5: "...an integer `version` that increments by one on every
    mutation of that resource — including mutations caused by cascades."
    At the 2026-10-21 decision instant the commit stamps committed_at, moves
    the slot to version 2, and the partner's EYES availability moves 10 -> 0
    in the same request's read-back.

    Design: Corner/state_machines/slot_commit_stamps_committed_at_and_recomputes_facings
    """
    ctx = setup_decided_review_with_slot()

    committed = commit_slot(ctx["slot"]["id"])

    assert committed["status"] == "COMMITTED"
    assert committed["committed_at"] == "2026-10-21T00:00:00Z"
    assert committed["version"] == 2
    partner = read_partner(ctx["partner"]["id"])
    assert partner["committed_facings"]["EYES"] == 10
    assert partner["available_facings"]["EYES"] == 0
    assert_footprint_conservation(partner)
