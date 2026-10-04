"""The two deep cascades: event completion (grant) and plan abort (release),
plus the wish approval/revert cycle and event terminal lockdown.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    abort_plan,
    api_client,
    approve_plan,
    assert_chapter_fiscal,
    assert_offer_quantities,
    complete_event,
    create_chapter,
    create_draft_plan,
    create_volunteer_pair,
    get_chapter,
    get_donation_offer,
    get_fulfillment_plan,
    get_wish,
    set_clock,
    setup_approved_wish,
    setup_granted_wish,
    setup_scheduled_wish,
    submit_plan,
    validate_error,
    validate_paginated,
)

WISH_COORDINATOR = TEST_USERS["wish_coordinator_headers"]
NATIONAL_DIRECTOR = TEST_USERS["national_director_headers"]

TRAVEL_OFFER_SPECS = [
    {"partner_name": "SkyWay Airlines", "category": "AIRLINE",
     "description": "round-trip ticket", "quantity_total": 5,
     "unit_retail_cents": 50000, "quantity": 2},
    {"partner_name": "SunResort", "category": "RESORT",
     "valuation_method": "PARTNER_DECLARED", "description": "3-night stay",
     "quantity_total": 4, "unit_retail_cents": 50000,
     "partner_declared_unit_cents": 45000, "quantity": 1},
]
# Plan money: cash 10000 + 2 x 50000 (airline) + 1 x 40000 (resort fmv =
# min(45000, 80% of 50000)) = 150000 total.


def _scheduled_travel_wish():
    return setup_scheduled_wish(wish_type="TRAVEL",
                                captured_true_wish="fly to the ocean",
                                cash_cost_cents=10000,
                                offer_specs=TRAVEL_OFFER_SPECS)


def _plan_lines(plan_id):
    items, _ = validate_paginated(
        api_client.list_plan_line_items(plan_id, WISH_COORDINATOR))
    return items


def test_event_complete_terminal_lockdown():
    """PRD section 3.8: "Completing the event is the culmination, performed by
    the `WishCoordinator` while the event is `SCHEDULED` — otherwise
    `ERR_INVALID_EVENT_STATE` (HTTP 409) — and the wish itself is
    `SCHEDULED`."

    Design: Corner/state_machines/event_complete_terminal_lockdown
    """
    ctx = setup_granted_wish(wish_type="RECEIVE_ITEM",
                             captured_true_wish="a treehouse",
                             cash_cost_cents=100000)
    resp = api_client.complete_wish_event(ctx["event"]["id"], WISH_COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_STATE)
    chapter = get_chapter(ctx["chapter"]["id"])
    assert_chapter_fiscal(chapter, granted_wish_count=1,
                          granted_cost_total_cents=100000)


def test_grant_cascade_entity_states():
    """PRD section 3.8: "The event becomes `COMPLETED` and `completed_at` is
    stamped with the logical clock. The wish becomes `GRANTED` with
    `granted_at` stamped. The approved plan becomes `COMPLETED`. Each
    committed line item is consumed to `CONSUMED`"

    Design: Difficulty/transitive_cascade/event_complete_grant_cascade_depth5
    """
    ctx = _scheduled_travel_wish()
    event = complete_event(ctx["event"]["id"])
    assert event["status"] == "COMPLETED"
    assert event["completed_at"] is not None

    wish = get_wish(ctx["wish"]["id"])
    assert wish["status"] == "GRANTED"
    assert wish["granted_at"] is not None
    assert wish["granted_at"].startswith("2026-09-01"), (
        f"granted_at is stamped with the logical clock, got {wish['granted_at']}"
    )
    assert get_fulfillment_plan(ctx["plan"]["id"])["status"] == "COMPLETED"
    statuses = {line["status"] for line in _plan_lines(ctx["plan"]["id"])}
    assert statuses == {"CONSUMED"}, f"both lines must be CONSUMED, got {statuses}"


def test_grant_cascade_quantities_and_chapter_books():
    """PRD section 3.8: "per line the offer's `quantity_reserved` and
    `quantity_total` both fall by the line's quantity — consumption shrinks
    the donation itself, so `quantity_available` does not move"
    PRD section 3.8: "`committed_cost_cents` falls by the plan's total,
    `granted_wish_count` rises by one, `granted_cost_total_cents` rises by the
    plan's `total_cost_cents`, `granted_cash_total_cents` rises by the plan's
    `cash_cost_cents`, both `avg_cost_blended_cents` and `avg_cost_cash_cents`
    are recomputed as described in §2.9"

    Design: Difficulty/transitive_cascade/event_complete_grant_cascade_depth5
    """
    ctx = _scheduled_travel_wish()
    complete_event(ctx["event"]["id"])

    airline = get_donation_offer(ctx["offers"][0]["id"])
    assert_offer_quantities(airline, quantity_total=3, quantity_reserved=0,
                            quantity_available=3)
    resort = get_donation_offer(ctx["offers"][1]["id"])
    assert_offer_quantities(resort, quantity_total=3, quantity_reserved=0,
                            quantity_available=3)

    chapter = get_chapter(ctx["chapter"]["id"])
    assert_chapter_fiscal(
        chapter,
        committed_cost_cents=0,
        granted_wish_count=1,
        granted_cost_total_cents=150000,
        granted_cash_total_cents=10000,
        avg_cost_blended_cents=150000,
        avg_cost_cash_cents=10000,
        posture="OPEN",
    )


def test_abort_from_approved_reverts_wish_to_planning():
    """PRD section 3.6: "From `APPROVED`, aborting runs the deeper cascade:
    the plan moves to `CANCELLED`; its `COMMITTED` lines release to
    `RELEASED`, each returning its reserved quantity to the offer and
    reopening a `FULLY_RESERVED` offer to `AVAILABLE` when availability is
    restored; the chapter's `committed_cost_cents` falls by the plan's total
    with `posture` recomputed and the chapter's `version` incremented; and
    the wish reverts from `PLAN_APPROVED` or `READY_TO_SCHEDULE` back to
    `PLANNING` with a version increment."

    Design: Difficulty/non_linear_state_machine/wish_approval_abort_revert_cycle
    """
    ctx = setup_approved_wish(wish_type="RECEIVE_ITEM",
                              captured_true_wish="a treehouse kit",
                              cash_cost_cents=100000)
    assert ctx["wish"]["status"] == "READY_TO_SCHEDULE"

    aborted = abort_plan(ctx["plan"]["id"], reason="family request")
    assert aborted["status"] == "CANCELLED"
    mid = get_wish(ctx["wish"]["id"])
    assert mid["status"] == "PLANNING", (
        f"aborting the APPROVED plan reverts the wish to PLANNING, got "
        f"{mid['status']}"
    )
    assert get_chapter(ctx["chapter"]["id"])["committed_cost_cents"] == 0


def test_replacement_plan_retraverses_approval_arc():
    """PRD section 3.6: after an abort the wish is PLANNING, so a replacement
    plan can traverse the same approval arc again: "the wish moves
    `DETERMINED` → `PLANNING` — or self-loops within `PLANNING` on a
    replacement — with a wish version increment either way."

    Design: Difficulty/non_linear_state_machine/wish_approval_abort_revert_cycle
    """
    ctx = setup_approved_wish(wish_type="RECEIVE_ITEM",
                              captured_true_wish="a treehouse kit",
                              cash_cost_cents=100000)
    plan1 = ctx["plan"]
    abort_plan(plan1["id"], reason="family request")

    plan2 = create_draft_plan(ctx["wish"]["id"], 120000)
    submit_plan(plan2["id"])
    approved = approve_plan(plan2["id"])
    assert approved["status"] == "APPROVED"

    wish = get_wish(ctx["wish"]["id"])
    assert wish["status"] == "READY_TO_SCHEDULE", (
        "the cycle re-traverses PLANNING -> PLAN_APPROVED -> "
        f"READY_TO_SCHEDULE, got {wish['status']}"
    )
    chapter = get_chapter(ctx["chapter"]["id"])
    assert chapter["committed_cost_cents"] == 120000, (
        "only the live plan counts toward the commitment"
    )
    assert get_fulfillment_plan(plan1["id"])["status"] == "CANCELLED"


def _frozen_two_plan_chapter():
    """Chapter budget 2000000 (freeze threshold 1900000) holding two APPROVED
    950000-cent plans; plan1 carries a 5x12000 retailer line that fully
    reserves its offer."""
    set_clock()
    chapter = create_chapter(name="Sierra Chapter",
                             territory_zip_prefixes=["500"],
                             fiscal_year_budget_cents=2000000,
                             target_avg_cost_per_wish_cents=800000)
    lead, second = create_volunteer_pair(chapter["id"])
    ctx1 = setup_approved_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a shopping spree",
        chapter=chapter, lead=lead, second=second, set_clock_first=False,
        zip_code="50012",
        cash_cost_cents=890000,
        offer_specs=[{"partner_name": "ToyWorld", "category": "RETAILER",
                      "description": "store voucher", "quantity_total": 5,
                      "unit_retail_cents": 12000, "quantity": 5}],
        approver_headers=NATIONAL_DIRECTOR)
    ctx2 = setup_approved_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a new bike",
        chapter=chapter, lead=lead, second=second, set_clock_first=False,
        zip_code="50044", child_full_name="Theo Alvarez",
        child_date_of_birth="2015-06-15", cash_cost_cents=950000,
        offer_specs=None, approver_headers=NATIONAL_DIRECTOR,
        visit_start="2026-09-06T09:00:00Z", visit_end="2026-09-06T11:00:00Z")
    return chapter, ctx1, ctx2


def test_abort_release_reopens_offer_and_cancels_plan():
    """PRD section 3.6: "From `APPROVED`, aborting runs the deeper cascade:
    the plan moves to `CANCELLED`; its `COMMITTED` lines release to
    `RELEASED`, each returning its reserved quantity to the offer and
    reopening a `FULLY_RESERVED` offer to `AVAILABLE` when availability is
    restored"

    Design: Difficulty/transitive_cascade/plan_abort_release_cascade_unfreezes_chapter
    """
    chapter, ctx1, _ = _frozen_two_plan_chapter()
    pre = get_chapter(chapter["id"])
    assert pre["committed_cost_cents"] == 1900000
    assert pre["posture"] == "FROZEN", (
        "committed exactly at floor(95% x 2000000) == 1900000 freezes"
    )
    offer = ctx1["offers"][0]
    assert get_donation_offer(offer["id"])["status"] == "FULLY_RESERVED"

    aborted = abort_plan(ctx1["plan"]["id"], reason="family withdrew")
    assert aborted["status"] == "CANCELLED"

    released = [line for line in _plan_lines(ctx1["plan"]["id"])]
    assert released and all(line["status"] == "RELEASED" for line in released)

    reopened = get_donation_offer(offer["id"])
    assert reopened["status"] == "AVAILABLE"
    assert_offer_quantities(reopened, quantity_total=5, quantity_reserved=0,
                            quantity_available=5)


def test_abort_unfreezes_chapter_and_reverts_wish():
    """PRD section 3.6: "the chapter's `committed_cost_cents` falls by the
    plan's total with `posture` recomputed and the chapter's `version`
    incremented; and the wish reverts from `PLAN_APPROVED` or
    `READY_TO_SCHEDULE` back to `PLANNING` with a version increment."
    PRD section 2.9: "it is `FROZEN` whenever `committed_cost_cents` reaches
    or exceeds the freeze threshold — the chapter's `fiscal_year_budget_cents`
    multiplied by 95 percent and rounded down to whole cents — and `OPEN`
    below it."

    Design: Difficulty/transitive_cascade/plan_abort_release_cascade_unfreezes_chapter
    """
    chapter, ctx1, _ = _frozen_two_plan_chapter()
    abort_plan(ctx1["plan"]["id"], reason="family withdrew")

    after = get_chapter(chapter["id"])
    assert after["committed_cost_cents"] == 950000, (
        f"1900000 - 950000 plan total, got {after['committed_cost_cents']}"
    )
    assert after["posture"] == "OPEN"
    assert get_wish(ctx1["wish"]["id"])["status"] == "PLANNING"
