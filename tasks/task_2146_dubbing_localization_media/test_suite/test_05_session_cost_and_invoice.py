"""Running the booth: confirm gating, the per-line rounding of a session's cost,
the budget ceiling and the pinned five-step invoice."""

import pytest

from test_helpers import (
    CASTING,
    PC,
    REVIEWER_1,
    ApiErrorId,
    approve_script,
    assert_invoice_shape,
    assert_order_money_conserved,
    book_session,
    cast_and_confirm,
    run_session_to_completed,
    set_clock,
    setup_canon,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------
# Cross-entity gate: a session may not be confirmed before the script is signed
# --------------------------------------------------------------------------
def _order_in_casting_with_a_scheduled_session(api):
    ctx = setup_canon(15)
    ctx["o_v1"] = validate_success(api.get_localization_order(ctx["o_id"], PC))["version"]
    cast_and_confirm(
        ctx, "ca1_id", "ch1_id", "tal1_id", "o_v1",
        usage_variant="BUYOUT", agreed_rate_cents_per_hour=36000,
    )
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    return ctx


def test_confirming_a_session_before_the_script_is_approved_is_refused(api):
    """PRD §3.7: "Four preconditions apply together: the session must be `SCHEDULED`;
    the owning order's script adaptation must exist and be `APPROVED`, since a missing
    or unapproved adaptation is `ERR_ADAPTATION_NOT_APPROVED`; the session's casting
    assignment must be in `CONFIRMED` or `RECORDED`; and the room must be `ACTIVE`,
    since a room moved to `MAINTENANCE` in the meantime gives
    `ERR_STUDIO_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/session_confirm_gated_on_script_adaptation_approved
    """
    ctx = _order_in_casting_with_a_scheduled_session(api)
    assert validate_success(api.get_script_adaptation(ctx["sa_id"], PC))["status"] == "IN_REVIEW"

    resp = api.confirm_recording_session(ctx["s1_id"], PC)
    validate_error(resp, ApiErrorId.ERR_ADAPTATION_NOT_APPROVED.value)
    assert resp.status_code == 409
    assert validate_success(api.get_recording_session(ctx["s1_id"], PC))["status"] == "SCHEDULED"


def test_the_same_confirm_succeeds_once_the_adaptation_is_approved(api):
    """PRD §3.7: "Four preconditions apply together: the session must be `SCHEDULED`;
    the owning order's script adaptation must exist and be `APPROVED`, since a missing
    or unapproved adaptation is `ERR_ADAPTATION_NOT_APPROVED`; the session's casting
    assignment must be in `CONFIRMED` or `RECORDED`; and the room must be `ACTIVE`,
    since a room moved to `MAINTENANCE` in the meantime gives
    `ERR_STUDIO_UNAVAILABLE`."
    PRD §3.4: "`APPROVED` is terminal for the adaptation, and it is the precondition
    that unlocks booth confirmation in §3.6."

    Design: Difficulty/cross_entity_state_dependency/session_confirm_gated_on_script_adaptation_approved
    """
    ctx = _order_in_casting_with_a_scheduled_session(api)
    approve_script(ctx, reviewer_user=REVIEWER_1)
    assert validate_success(api.get_script_adaptation(ctx["sa_id"], PC))["status"] == "APPROVED"

    confirmed = validate_success(api.confirm_recording_session(ctx["s1_id"], PC))
    assert confirmed["status"] == "CONFIRMED"


# --------------------------------------------------------------------------
# Session cost: four separately-rounded line items
# --------------------------------------------------------------------------
def _union_25_minute_session(api):
    ctx = setup_canon(
        21,
        studio={"hourly_rate_cents": 21501},
        talent1={"full_name": "Anna Vogel", "base_rate_cents_per_hour": 19506,
                 "union_status": "UNION"},
        ca1={"agreed_rate_cents_per_hour": 19506},
    )
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T09:25:00Z")
    return ctx


def test_each_cost_line_is_rounded_before_the_lines_are_summed(api):
    """PRD §2.9: "**where a formula is described as a sum of separately-named line
    items, each line item is rounded to a whole cent independently, from its own
    unrounded raw value, and only then are the rounded line items summed.**"
    PRD §3.7: "As §2.9 requires, each of those four line items is rounded half up to a
    whole cent independently, from its own unrounded raw value, *before* any addition
    happens."
    PRD §3.7: "The billable block count is the session's `duration_minutes` divided by
    thirty and rounded *up* to a whole number, and the billable minutes are that block
    count multiplied by thirty — a room is therefore always billed in whole
    half-hours, so a twenty-five-minute session is billed as thirty minutes of room
    time."

    Design: Difficulty/combinatorial_formula/session_cost_rounds_each_line_item_before_summing
    """
    ctx = _union_25_minute_session(api)
    completed = run_session_to_completed(ctx, "s1_id", "2026-09-10T09:00:00Z")
    assert completed["duration_minutes"] == 25
    assert completed["status"] == "COMPLETED"
    assert completed["session_cost_cents"] == 19895, (
        "rounding each of the studio (10750.5), talent (8127.5) and union uplift "
        "(1015.9375) lines first gives 19895; summing raw then rounding gives 19894"
    )


def test_the_restamped_cost_is_what_the_order_accrues(api):
    """PRD §3.7: "A surviving completion moves the session's `duration_minutes` out of
    the performer's `held_minutes` and into their `recorded_minutes` while leaving the
    room's `booked_minutes` unchanged, adds the restamped `session_cost_cents` to both
    the order's `committed_cents` and its `gross_accrued_cents`, and increments the
    session's `version` by 1."
    PRD §2.9: "A forward action — a recording session moving from `IN_PROGRESS` to
    `COMPLETED` — adds that session's cost to both `committed_cents` and
    `gross_accrued_cents` and leaves `released_cents` untouched."

    Design: Difficulty/combinatorial_formula/session_cost_rounds_each_line_item_before_summing
    """
    ctx = _union_25_minute_session(api)
    run_session_to_completed(ctx, "s1_id", "2026-09-10T09:00:00Z")
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["committed_cents"] == 19895
    assert order["gross_accrued_cents"] == 19895
    assert order["released_cents"] == 0
    assert_order_money_conserved(order)
    talent = validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))
    assert talent["recorded_minutes"] == 25
    assert talent["held_minutes"] == 0


# --------------------------------------------------------------------------
# Budget ceiling boundary
# --------------------------------------------------------------------------
def test_a_completion_landing_exactly_on_the_budget_cap_is_permitted(api):
    """PRD §3.7: "It then restamps `session_cost_cents` from live data and checks the
    budget: the order's `committed_cents` plus that restamped cost must be at most
    `budget_cap_cents`, with equality allowed, and a completion that would push past
    the ceiling is refused with `ERR_BUDGET_EXCEEDED` at HTTP 402 with nothing
    written."
    PRD §3.5: "When one of the assignment's sessions whose `is_retake` is false
    reaches `COMPLETED`, the assignment advances `CONFIRMED → RECORDED`, its
    `recorded_minutes` is recomputed, and its `version` increments by 1."

    Design: Difficulty/boundary_precision_check/budget_cap_exact_equality_permits_completion
    """
    ctx = setup_canon(21, order={"budget_cap_cents": 120000})
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    completed = run_session_to_completed(ctx, "s1_id", "2026-09-10T09:00:00Z")
    assert completed["status"] == "COMPLETED"
    assert completed["session_cost_cents"] == 120000

    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["committed_cents"] == 120000
    assert order["gross_accrued_cents"] == 120000
    assert order["released_cents"] == 0
    assignment = validate_success(api.get_casting_assignment(ctx["ca1_id"], CASTING))
    assert assignment["casting_status"] == "RECORDED"


def test_a_completion_one_cent_past_the_budget_cap_is_refused(api):
    """PRD §3.7: "It then restamps `session_cost_cents` from live data and checks the
    budget: the order's `committed_cents` plus that restamped cost must be at most
    `budget_cap_cents`, with equality allowed, and a completion that would push past
    the ceiling is refused with `ERR_BUDGET_EXCEEDED` at HTTP 402 with nothing
    written."

    Design: Difficulty/boundary_precision_check/budget_cap_exact_equality_permits_completion
    """
    ctx = setup_canon(21, order={"budget_cap_cents": 119999})
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    validate_success(api.confirm_recording_session(ctx["s1_id"], PC))
    set_clock("2026-09-10T09:00:00Z")
    validate_success(api.start_recording_session(ctx["s1_id"], PC))

    resp = api.complete_recording_session(ctx["s1_id"], PC)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
    assert resp.status_code == 402
    assert validate_success(api.get_recording_session(ctx["s1_id"], PC))["status"] == "IN_PROGRESS"
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["committed_cents"] == 0
    assert order["gross_accrued_cents"] == 0


# --------------------------------------------------------------------------
# Precedence: the order-locked state check outranks the fiscal ceiling
# --------------------------------------------------------------------------
def _cancelled_order_with_a_running_session(api):
    ctx = setup_canon(21, order={"budget_cap_cents": 100000})
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    validate_success(api.confirm_recording_session(ctx["s1_id"], PC))
    set_clock("2026-09-10T09:00:00Z")
    validate_success(api.start_recording_session(ctx["s1_id"], PC))
    validate_success(
        api.cancel_order(ctx["o_id"], {"reason": "Client pulled the title"}, PC)
    )
    return ctx


def test_order_locked_pre_empts_the_budget_ceiling_on_completion(api):
    """PRD §2.6 ladder step 10: "On order-scoped mutations — creating a script
    adaptation and every script-adaptation action, creating a casting assignment and
    every casting-assignment action, creating a recording session and every
    recording-session action, creating a mix job, and creating a talent payment — the
    owning `LocalizationOrder` is not in `DELIVERED`, `RECALLED` or `CANCELLED`;
    otherwise `ERR_ORDER_LOCKED` (409)."
    PRD §2.6 ladder step 43: "On `POST /recording-sessions/{sessionId}/complete`: the
    order's `committed_cents` plus the restamped `session_cost_cents` is at most
    `budget_cap_cents`, with equality allowed; otherwise `ERR_BUDGET_EXCEEDED` (402)."
    PRD §2.6: "Checks are evaluated strictly in ascending priority order, and **the
    first failing check determines the entire response — no later check runs and no
    later error code can surface**."

    Design: Difficulty/priority_pair_validation_conflict/order_locked_outranks_budget_exceeded
    """
    ctx = _cancelled_order_with_a_running_session(api)
    resp = api.complete_recording_session(ctx["s1_id"], PC)
    error = validate_error(resp, ApiErrorId.ERR_ORDER_LOCKED.value)
    assert resp.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_BUDGET_EXCEEDED.value, (
        "the fiscal check sits far below the order-locked state check"
    )


def test_a_completion_blocked_by_order_lockdown_writes_no_money(api):
    """PRD §3.3: "Once an order has reached `DELIVERED`, `RECALLED` or `CANCELLED`, it
    is closed to child mutation. Opening a script workstream on it, acting on its
    adaptation, creating or acting on a casting assignment, creating or acting on a
    recording session, opening a mix job, or accruing a talent payment against it are
    all refused with `ERR_ORDER_LOCKED`."
    PRD §2.9: "After every single request, the invariant `gross_accrued_cents` equals
    `committed_cents` plus `released_cents` must hold."

    Design: Difficulty/priority_pair_validation_conflict/order_locked_outranks_budget_exceeded
    """
    ctx = _cancelled_order_with_a_running_session(api)
    resp = api.complete_recording_session(ctx["s1_id"], PC)
    validate_error(resp, ApiErrorId.ERR_ORDER_LOCKED.value)
    assert validate_success(api.get_recording_session(ctx["s1_id"], PC))["status"] == "IN_PROGRESS"
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["committed_cents"] == 0
    assert order["gross_accrued_cents"] == 0
    assert_order_money_conserved(order)


# --------------------------------------------------------------------------
# The invoice: five pinned steps
# --------------------------------------------------------------------------
def test_invoice_reports_every_pinned_step_for_an_expedited_order(api):
    """PRD §3.11: "Step two computes `rush_surcharge_cents` as the bare subtotal from
    step one multiplied by the surcharge percentage of the order's `priority_tier` —
    zero for a `STANDARD` order, one tenth for an `EXPEDITED` order and twenty-two
    hundredths for a `RUSH` order — rounded half up to a whole cent."
    PRD §3.11: "Step five computes `volume_discount_cents` as
    `pre_discount_total_cents` multiplied by `volume_discount_pct`, rounded half up to
    a whole cent, and `invoice_total_cents` as `pre_discount_total_cents` minus
    `volume_discount_cents`."

    Design: Difficulty/combinatorial_formula/invoice_discount_tier_keyed_on_post_surcharge_total
    """
    ctx = setup_canon(36)
    data = validate_success(api.get_order_invoice(ctx["o_id"], PC))
    assert_invoice_shape(data)
    assert data["recorded_subtotal_cents"] == 190000
    assert data["rush_surcharge_cents"] == 19000
    assert data["pre_discount_total_cents"] == 209000
    assert data["volume_discount_pct"] == pytest.approx(0.05, abs=1e-9)
    assert data["volume_discount_cents"] == 10450
    assert data["invoice_total_cents"] == 198550


def test_the_discount_tier_is_keyed_on_the_post_surcharge_total(api):
    """PRD §3.11: "Step four selects `volume_discount_pct` from that post-surcharge,
    pre-discount total: eight hundredths when the total is at least five hundred
    thousand cents, otherwise five hundredths when the total is at least two hundred
    thousand cents, otherwise zero."
    PRD §3.11: "The tier is keyed on the post-surcharge total from step three, never
    on the bare subtotal from step one — an order whose bare subtotal falls short of a
    tier but whose surcharge carries it over the line does earn that tier's discount."

    Design: Difficulty/combinatorial_formula/invoice_discount_tier_keyed_on_post_surcharge_total
    """
    ctx = setup_canon(36)
    data = validate_success(api.get_order_invoice(ctx["o_id"], PC))
    assert data["recorded_subtotal_cents"] == 190000, (
        "the bare subtotal sits below the two-hundred-thousand-cent tier"
    )
    assert data["pre_discount_total_cents"] == 209000
    assert data["volume_discount_pct"] == pytest.approx(0.05, abs=1e-9), (
        "the surcharge carries the total over the line, so the tier applies"
    )
    assert data["invoice_total_cents"] == 198550
    assert data["invoice_total_cents"] != 209000


def test_invoice_of_an_order_with_no_completed_session_is_all_zero(api):
    """PRD §3.11: "Step one computes `recorded_subtotal_cents` as the sum of
    `session_cost_cents` over the order's sessions whose status is `COMPLETED`."
    PRD §3.11: "Sessions in `WAITLISTED`, `SCHEDULED`, `CONFIRMED`, `IN_PROGRESS`,
    `CANCELLED` or `NO_SHOW` are excluded entirely, while retake sessions *are*
    included at their already-credited cost."

    Design: Corner/calculations/invoice_of_an_order_with_no_completed_sessions_is_all_zero
    """
    # A RUSH order carries the 0.94 tier weight, so the canonical sync measurement
    # must be tightened for the adaptation to clear the specification fidelity floor.
    ctx = setup_canon(21, order={"priority_tier": "RUSH"}, measured=19000)
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    data = validate_success(api.get_order_invoice(ctx["o_id"], PC))
    assert_invoice_shape(data)
    assert data["recorded_subtotal_cents"] == 0
    assert data["rush_surcharge_cents"] == 0
    assert data["pre_discount_total_cents"] == 0
    assert data["volume_discount_pct"] == pytest.approx(0.0, abs=1e-9)
    assert data["volume_discount_cents"] == 0
    assert data["invoice_total_cents"] == 0


def test_a_rush_order_takes_the_higher_surcharge_before_the_discount_band(api):
    """PRD §3.11: "Step two computes `rush_surcharge_cents` as the bare subtotal from
    step one multiplied by the surcharge percentage of the order's `priority_tier` —
    zero for a `STANDARD` order, one tenth for an `EXPEDITED` order and twenty-two
    hundredths for a `RUSH` order — rounded half up to a whole cent."
    PRD §3.11: "Step four selects `volume_discount_pct` from that post-surcharge,
    pre-discount total: eight hundredths when the total is at least five hundred
    thousand cents, otherwise five hundredths when the total is at least two hundred
    thousand cents, otherwise zero."

    Design: Corner/calculations/rush_tier_surcharge_and_second_discount_band_apply
    """
    # A RUSH order carries the 0.94 tier weight, so the canonical sync measurement
    # must be tightened for the adaptation to clear the specification fidelity floor.
    ctx = setup_canon(36, order={"priority_tier": "RUSH"}, measured=19000)
    data = validate_success(api.get_order_invoice(ctx["o_id"], PC))
    assert_invoice_shape(data)
    assert data["recorded_subtotal_cents"] == 190000
    assert data["rush_surcharge_cents"] == 41800
    assert data["pre_discount_total_cents"] == 231800
    assert data["volume_discount_pct"] == pytest.approx(0.05, abs=1e-9)
    assert data["volume_discount_cents"] == 11590
    assert data["invoice_total_cents"] == 220210


# --------------------------------------------------------------------------
# The no-show fork and the cancellation cascade
# --------------------------------------------------------------------------
def test_a_no_show_returns_the_minutes_and_books_no_money(api):
    """PRD §3.7: "The **no-show branch** advances `CONFIRMED → NO_SHOW`, is likewise
    permitted only once the logical clock has reached or passed `start_utc`, and does
    five things: it subtracts the session's `duration_minutes` from the room's
    `booked_minutes`, subtracts the same `duration_minutes` from the performer's
    `held_minutes`, books no money at all so that the order's `committed_cents` and
    `gross_accrued_cents` are both untouched, leaves the casting assignment's
    `casting_status` exactly where it was, and runs the waitlist promotion selector on
    that room, promoting at most one `WAITLISTED` row."

    Design: Corner/state_machines/no_show_returns_minutes_without_booking_money
    """
    ctx = setup_canon(21)
    book_session(ctx, "s1_id", "ca1_id", "2026-09-10T09:00:00Z", "2026-09-10T11:00:00Z")
    validate_success(api.confirm_recording_session(ctx["s1_id"], PC))
    set_clock("2026-09-10T09:00:00Z")

    data = validate_success(api.no_show_recording_session(ctx["s1_id"], PC))
    assert data["status"] == "NO_SHOW"
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 0
    talent = validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))
    assert talent["held_minutes"] == 0
    assert talent["recorded_minutes"] == 0
    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["committed_cents"] == 0
    assert order["gross_accrued_cents"] == 0
    assignment = validate_success(api.get_casting_assignment(ctx["ca1_id"], CASTING))
    assert assignment["casting_status"] == "CONFIRMED"


def test_cancelling_an_order_releases_only_its_live_sessions(api):
    """PRD §3.11: "The order moves to `CANCELLED`, which is terminal —
    `DRAFT → CANCELLED`, `SCRIPT_IN_PROGRESS → CANCELLED`, `CASTING → CANCELLED`,
    `RECORDING → CANCELLED`, `MIXING → CANCELLED` and `QC → CANCELLED` are all
    declared edges — and the cancel releases everything the order was holding: every
    one of its recording sessions in `WAITLISTED`, `SCHEDULED` or `CONFIRMED` is moved
    to `CANCELLED`, each returning its `duration_minutes` to the relevant room's
    `booked_minutes` and to the relevant performer's `held_minutes`; the whole of the
    order's `committed_cents` is moved into its `released_cents` with
    `gross_accrued_cents` untouched; and the order's `version` increments by 1."

    Design: Corner/state_machines/order_cancel_cascades_down_to_live_sessions_only
    """
    ctx = setup_canon(29)
    set_clock("2026-09-10T09:00:00Z")
    validate_success(api.start_recording_session(ctx["s1_id"], PC))
    validate_success(api.complete_recording_session(ctx["s1_id"], PC))

    cancelled = validate_success(
        api.cancel_order(ctx["o_id"], {"reason": "Rights lapsed"}, PC)
    )
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_recording_session(ctx["s2_id"], PC))["status"] == "CANCELLED"
    assert validate_success(api.get_recording_session(ctx["s1_id"], PC))["status"] == "COMPLETED"
    assert validate_success(api.get_studio(ctx["st_id"], PC))["booked_minutes"] == 120
    assert validate_success(api.get_voice_talent(ctx["tal2_id"], CASTING))["held_minutes"] == 0
    assert validate_success(api.get_voice_talent(ctx["tal1_id"], CASTING))["recorded_minutes"] == 120

    order = validate_success(api.get_localization_order(ctx["o_id"], PC))
    assert order["committed_cents"] == 0
    assert order["released_cents"] == 120000
    assert order["gross_accrued_cents"] == 120000
    assert_order_money_conserved(order)
