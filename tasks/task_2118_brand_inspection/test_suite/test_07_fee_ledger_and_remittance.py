"""Assessment, delinquency, standing, unwinding and the remittance waterfall."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_arrears_consistent,
    assert_fee_remittance,
    assert_instant_equals,
    commission_inspector,
    make_field_inspector_headers,
    make_livestock_owner_headers,
    open_district,
    read_order,
    read_owner,
    read_owner_statement,
    read_remittance,
    run_delinquency_sweep,
    schedule_order_payload,
    setup_arrears_boundary_pair,
    setup_order_in_field,
    setup_owner_with_assessed_fee,
    setup_three_open_fees_for_waterfall,
    setup_two_dimension_scenario,
    setup_two_order_arrears_scenario,
    setup_void_assessment_scenario,
    tender_remittance,
    top_up_remittance_payload,
    TEST_USERS,
    validate_error,
    validate_success,
)

BOARD_ADMIN = TEST_USERS["board_admin_headers"]
FEE_ADMIN = TEST_USERS["fee_administrator_headers"]


# ─── The two arrears flavours ─────────────────────────────────────────────────

def test_statement_reports_posted_and_projected_arrears_side_by_side(api):
    """PRD §3.9: "`posted_arrears_cents` is the summed `assessed_fee_cents` of that
    owner's orders whose `fee_status` is exactly `DELINQUENT` — money that has already
    passed its due date under a sweep."
    PRD §3.9: "`projected_arrears_cents` is the summed `assessed_fee_cents` of that
    owner's orders whose `fee_status` is `ASSESSED` or `DELINQUENT` — everything
    outstanding, whether or not it has come due."
    PRD §3.9: "The sweep reports what it did: `delinquent_order_count`,
    `graced_registration_count`, `lapsed_registration_count`, `suspended_owner_count`,
    and the `swept_at` instant it ran at."

    Design: Difficulty/dual_variant_calc/owner_posted_vs_projected_arrears_diverge
    """
    scenario = setup_two_order_arrears_scenario()

    sweep = run_delinquency_sweep()
    assert sweep["delinquent_order_count"] == 1

    first = read_order(scenario["order_1"]["id"])
    second = read_order(scenario["order_2"]["id"])
    assert first["assessed_fee_cents"] == 7450 and first["fee_status"] == "DELINQUENT"
    assert second["assessed_fee_cents"] == 2500 and second["fee_status"] == "ASSESSED"

    statement = read_owner_statement(scenario["owner"]["id"])
    assert statement["posted_arrears_cents"] == 7450
    assert statement["projected_arrears_cents"] == 9950
    assert statement["standing"] == "GOOD"

    owner = read_owner(scenario["owner"]["id"])
    assert owner["posted_arrears_cents"] == 7450
    assert owner["projected_arrears_cents"] == 9950
    assert_arrears_consistent(owner)


def test_sweep_moves_only_the_past_due_fee_into_posted_arrears(api):
    """PRD §3.9: "A fee assessed this morning contributes its full amount to the
    projected figure and nothing at all to the posted one, so for an owner with a single
    freshly assessed order the two figures differ by exactly that order's
    `assessed_fee_cents`."
    PRD §3.9: "It first moves every order whose `fee_status` is `ASSESSED` and whose
    `fee_due_on` has been reached — meaning `fee_due_on` is at or before the logical
    clock — to `DELINQUENT`, processing them by `fee_due_on` ascending and then
    `created_at` ascending."

    Design: Difficulty/dual_variant_calc/owner_posted_vs_projected_arrears_diverge
    """
    scenario = setup_two_order_arrears_scenario()

    before = read_owner_statement(scenario["owner"]["id"])
    assert before["posted_arrears_cents"] == 0, (
        "nothing is posted until a sweep has moved a fee past its due date"
    )
    assert before["projected_arrears_cents"] == 9950

    run_delinquency_sweep()

    after = read_owner_statement(scenario["owner"]["id"])
    assert after["posted_arrears_cents"] == 7450
    assert after["projected_arrears_cents"] == 9950
    assert read_order(scenario["order_2"]["id"])["fee_status"] == "ASSESSED", (
        "the fee that has not come due is untouched by the sweep"
    )


# ─── The two independent state dimensions ─────────────────────────────────────

def test_fee_dimension_walks_to_waived_while_the_schedule_stays_completed(api):
    """PRD §3.5: "An inspection order carries two state dimensions on the same row, and
    they evolve independently of one another."
    PRD §3.9: "Waiving moves the fee dimension from `ASSESSED` or `DELINQUENT` to
    `WAIVED`."
    PRD §3.9: "It first moves every order whose `fee_status` is `ASSESSED` and whose
    `fee_due_on` has been reached — meaning `fee_due_on` is at or before the logical
    clock — to `DELINQUENT`, processing them by `fee_due_on` ascending and then
    `created_at` ascending."

    Design: Difficulty/non_linear_state_machine/inspection_order_schedule_and_fee_dimensions_advance_independently
    """
    scenario = setup_two_dimension_scenario()
    assert scenario["order_1"]["schedule_status"] == "COMPLETED"
    assert scenario["order_1"]["fee_status"] == "ASSESSED"

    run_delinquency_sweep()
    swept = read_order(scenario["order_1"]["id"])
    assert swept["schedule_status"] == "COMPLETED"
    assert swept["fee_status"] == "DELINQUENT"

    waived = validate_success(
        api.waive_fee(scenario["order_1"]["id"], FEE_ADMIN), 200
    )
    assert waived["schedule_status"] == "COMPLETED", (
        "waiving the fee never moves the scheduling dimension"
    )
    assert waived["fee_status"] == "WAIVED"


def test_schedule_dimension_advances_while_the_fee_stays_unassessed(api):
    """PRD §3.5: "Neither dimension constrains the other's declared transitions except
    where a workflow explicitly says so, and a state check evaluates only the dimension
    the requested operation acts on."
    PRD §3.9: "The fee dimension of an inspection order begins at `UNASSESSED` and leaves
    that state exactly once, at the moment the inspector completes the field work."

    Design: Difficulty/non_linear_state_machine/inspection_order_schedule_and_fee_dimensions_advance_independently
    """
    scenario = setup_two_dimension_scenario()

    run_delinquency_sweep()
    validate_success(api.waive_fee(scenario["order_1"]["id"], FEE_ADMIN), 200)

    unbilled = read_order(scenario["order_2"]["id"])
    assert unbilled["schedule_status"] == "IN_FIELD", (
        "the second order walked REQUESTED to SCHEDULED to IN_FIELD"
    )
    assert unbilled["fee_status"] == "UNASSESSED", (
        "its fee dimension has never left UNASSESSED because it was never completed"
    )
    assert unbilled["assessed_fee_cents"] == 0
    assert unbilled["fee_due_on"] is None

    owner = read_owner(scenario["owner"]["id"])
    assert owner["posted_arrears_cents"] == 0
    assert owner["projected_arrears_cents"] == 0


# ─── The suspension threshold ─────────────────────────────────────────────────

def test_owner_at_exactly_the_suspension_threshold_is_blocked(api):
    """PRD §3.9: "An owner's `standing` reads `SUSPENDED` whenever
    `posted_arrears_cents` is at or above 25,000 cents — two hundred and fifty dollars —
    and reads `GOOD` at any lower amount; the breakpoint is inclusive, so an owner
    sitting at exactly 25,000 cents of posted arrears is suspended."
    PRD §3.9: "On the recompute that flips an owner from `GOOD` to `SUSPENDED`,
    `suspended_since` is stamped with the logical clock; on the recompute that flips them
    back to `GOOD`, `suspended_since` returns to null."
    PRD §3.5: "An owner whose `standing` reads `SUSPENDED` cannot have new work
    scheduled, and the attempt is refused with `ERR_OWNER_STANDING_SUSPENDED` (HTTP 402
    Payment Required)."

    Design: Difficulty/boundary_precision_check/arrears_exactly_at_suspension_threshold_suspends
    """
    scenario = setup_arrears_boundary_pair()
    assert scenario["sweep"]["suspended_owner_count"] == 1

    owner = read_owner(scenario["owner_at_threshold"]["id"])
    assert owner["posted_arrears_cents"] == 25000
    assert owner["standing"] == "SUSPENDED"
    assert_instant_equals(
        owner["suspended_since"], "2026-08-31T00:00:00Z", "suspended_since"
    )

    spare = scenario["spare_inspector_at_threshold"]
    response = api.schedule_order(
        scenario["next_order_at_threshold"]["id"],
        schedule_order_payload(
            spare["id"], spare["version"],
            scheduled_start_at="2026-09-05T09:00:00Z",
            scheduled_end_at="2026-09-05T11:00:00Z",
        ),
        BOARD_ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_OWNER_STANDING_SUSPENDED.value, 402)
    assert (
        read_order(scenario["next_order_at_threshold"]["id"])["schedule_status"]
        == "REQUESTED"
    )


def test_owner_one_cent_below_the_threshold_still_schedules(api):
    """PRD §3.9: "An owner's `standing` reads `SUSPENDED` whenever
    `posted_arrears_cents` is at or above 25,000 cents — two hundred and fifty dollars —
    and reads `GOOD` at any lower amount; the breakpoint is inclusive, so an owner
    sitting at exactly 25,000 cents of posted arrears is suspended."
    PRD §3.1: "A newly enrolled owner begins in good fiscal standing — `standing` is
    `GOOD`, both `posted_arrears_cents` and `projected_arrears_cents` are 0, and
    `suspended_since` is null, since the owner has never been suspended."

    Design: Difficulty/boundary_precision_check/arrears_exactly_at_suspension_threshold_suspends
    """
    scenario = setup_arrears_boundary_pair()

    owner = read_owner(scenario["owner_under_threshold"]["id"])
    assert owner["posted_arrears_cents"] == 24999
    assert owner["standing"] == "GOOD"
    assert owner["suspended_since"] is None
    assert_arrears_consistent(owner)

    spare = scenario["spare_inspector_under_threshold"]
    scheduled = validate_success(
        api.schedule_order(
            scenario["next_order_under_threshold"]["id"],
            schedule_order_payload(
                spare["id"], spare["version"],
                scheduled_start_at="2026-09-05T09:00:00Z",
                scheduled_end_at="2026-09-05T11:00:00Z",
            ),
            BOARD_ADMIN,
        ),
        200,
    )

    assert scheduled["schedule_status"] == "SCHEDULED"
    assert scheduled["inspector_id"] == spare["id"]


# ─── Unwinding an assessment ──────────────────────────────────────────────────

def test_void_assessment_returns_projected_arrears_to_its_prior_value(api):
    """PRD §3.9: "Unwinding an assessment is the compensating action for the assessment
    stamp itself: it moves the fee dimension from `ASSESSED` or `DELINQUENT` back to
    `UNASSESSED`, sets `assessed_fee_cents` to 0 and `fee_due_on` to null, and — because
    the owner aggregates are recomputed from their source rows rather than nudged (§2.9)
    — returns the owner's arrears and `standing` to exactly the values they held before
    the assessment."
    PRD §2.9: "Third, derived aggregates are recomputed from their source rows rather
    than adjusted incrementally, so that a compensating action returns an aggregate to
    exactly the value it held before the action it compensates."

    Design: Difficulty/compensating_invariant/void_assessment_restores_owner_fee_ledger
    """
    scenario = setup_void_assessment_scenario()
    assert scenario["baseline_projected"] == 2500
    assert scenario["order"]["assessed_fee_cents"] == 7450

    peak = read_owner_statement(scenario["owner"]["id"])
    assert peak["projected_arrears_cents"] == 9950

    validate_success(api.void_assessment(scenario["order"]["id"], FEE_ADMIN), 200)

    restored = read_owner_statement(scenario["owner"]["id"])
    assert restored["projected_arrears_cents"] == 2500
    assert restored["projected_arrears_cents"] == scenario["baseline_projected"]
    assert restored["posted_arrears_cents"] == 0
    assert restored["standing"] == "GOOD"


def test_void_assessment_zeroes_the_fee_and_clears_the_due_date(api):
    """PRD §3.9: "Unwinding an assessment is the compensating action for the assessment
    stamp itself: it moves the fee dimension from `ASSESSED` or `DELINQUENT` back to
    `UNASSESSED`, sets `assessed_fee_cents` to 0 and `fee_due_on` to null, and — because
    the owner aggregates are recomputed from their source rows rather than nudged (§2.9)
    — returns the owner's arrears and `standing` to exactly the values they held before
    the assessment."
    PRD §3.5: "An inspection order carries two state dimensions on the same row, and they
    evolve independently of one another."

    Design: Difficulty/compensating_invariant/void_assessment_restores_owner_fee_ledger
    """
    scenario = setup_void_assessment_scenario()

    voided = validate_success(
        api.void_assessment(scenario["order"]["id"], FEE_ADMIN), 200
    )

    assert voided["assessed_fee_cents"] == 0
    assert voided["fee_status"] == "UNASSESSED"
    assert voided["fee_due_on"] is None
    assert voided["schedule_status"] == "COMPLETED", (
        "unwinding the fee never rewinds the scheduling dimension"
    )
    assert read_owner(scenario["owner"]["id"])["standing"] == "GOOD"


# ─── The remittance waterfall ─────────────────────────────────────────────────

def test_waterfall_stops_at_the_first_uncoverable_order(api):
    """PRD §3.9: "The board first selects, from `covered_order_ids`, only those orders
    whose `fee_status` is still `ASSESSED` or `DELINQUENT` — orders already settled or
    waived by an earlier pass are skipped entirely and contribute nothing — and re-sorts
    that selection by `fee_due_on` ascending and then `created_at` ascending, ignoring
    the order in which the client listed them."
    PRD §3.9: "The first order that cannot be fully covered stops the walk outright — the
    board never settles a cheaper order sitting behind an expensive one out of turn, and
    it never writes a partial settlement of a single order."
    PRD §3.9: "A remittance whose `shortfall_cents` lands at zero moves
    `SUBMITTED → RECONCILED`; one with any shortfall moves `SUBMITTED → SHORT_PAID`."
    PRD §3.9: "Its owner may top it up by supplying `additional_cents`, which must be
    greater than zero and is added to the remittance's `amount_cents`, returning it
    `SHORT_PAID → SUBMITTED` for another reconciliation pass — the cycle
    `SUBMITTED → SHORT_PAID → SUBMITTED → RECONCILED` is the normal path for an owner who
    underestimated their bill."
    PRD §3.9: "Because `applied_cents` accumulates across passes, the second pass picks
    up exactly where the first one stopped."

    Design: Corner/calculations/corner_remittance_waterfall_stops_at_first_uncoverable_order
    """
    scenario = setup_three_open_fees_for_waterfall()
    first, second, third = scenario["orders"]
    assert first["assessed_fee_cents"] == 7450
    assert second["assessed_fee_cents"] == 10601
    assert third["assessed_fee_cents"] == 2500

    remittance = tender_remittance(
        scenario["owner"]["id"], 15000, [first["id"], second["id"], third["id"]]
    )
    assert_fee_remittance(remittance)
    assert remittance["status"] == "SUBMITTED"

    short_paid = validate_success(
        api.reconcile_remittance(remittance["id"], FEE_ADMIN), 200
    )
    assert short_paid["status"] == "SHORT_PAID"
    assert short_paid["applied_cents"] == 7450
    assert short_paid["shortfall_cents"] == 5551
    assert read_order(first["id"])["fee_status"] == "REMITTED"
    assert read_order(second["id"])["fee_status"] == "ASSESSED"
    assert read_order(third["id"])["fee_status"] == "ASSESSED", (
        "the cheaper third order is never settled out of turn"
    )

    topped_up = validate_success(
        api.top_up_remittance(
            remittance["id"],
            top_up_remittance_payload(5551),
            make_livestock_owner_headers(scenario["owner"]["id"]),
        ),
        200,
    )
    assert topped_up["status"] == "SUBMITTED"
    assert topped_up["amount_cents"] == 20551

    reconciled = validate_success(
        api.reconcile_remittance(remittance["id"], FEE_ADMIN), 200
    )
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["applied_cents"] == 20551
    assert reconciled["shortfall_cents"] == 0
    assert read_order(second["id"])["remittance_id"] == remittance["id"]
    assert read_order(third["id"])["remittance_id"] == remittance["id"]
    assert read_owner(scenario["owner"]["id"])["projected_arrears_cents"] == 0


def test_overpayment_is_refused_while_the_exact_amount_reconciles(api):
    """PRD §3.9: "Before applying anything, the board tests for overpayment: if the
    remittance's `amount_cents` exceeds its `applied_cents` plus that covered total, the
    pass is refused with `ERR_REMITTANCE_AMOUNT_INVALID` (HTTP 422); equality is
    accepted, and only a strictly greater tender is an overpayment."
    PRD §3.9: "A new remittance enters at status `SUBMITTED` with `applied_cents` and
    `shortfall_cents` both 0, and remittances may be listed and narrowed by `owner_id` or
    by `status`."

    Design: Corner/calculations/corner_remittance_overpayment_rejected_at_reconcile
    """
    scenario = setup_owner_with_assessed_fee(
        travel_surcharge_cents=2500, owner_name="Overpay Ranch", territory_code="T-OVER"
    )
    order = scenario["order"]
    assert order["assessed_fee_cents"] == 2500

    over = tender_remittance(scenario["owner"]["id"], 2501, [order["id"]])
    exact = tender_remittance(scenario["owner"]["id"], 2500, [order["id"]])

    refused = api.reconcile_remittance(over["id"], FEE_ADMIN)
    validate_error(refused, ApiErrorId.ERR_REMITTANCE_AMOUNT_INVALID.value, 422)

    untouched = read_remittance(over["id"])
    assert untouched["status"] == "SUBMITTED"
    assert untouched["applied_cents"] == 0

    reconciled = validate_success(
        api.reconcile_remittance(exact["id"], FEE_ADMIN), 200
    )
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["applied_cents"] == 2500

    settled = read_order(order["id"])
    assert settled["fee_status"] == "REMITTED"
    assert settled["remittance_id"] == exact["id"]


def test_top_up_of_a_submitted_remittance_is_refused(api):
    """PRD §3.9: "Reconciling a remittance that is not `SUBMITTED`, or topping up one
    that is not `SHORT_PAID`, is refused with `ERR_REMITTANCE_INVALID_STATE`."
    PRD §3.9: "A new remittance enters at status `SUBMITTED` with `applied_cents` and
    `shortfall_cents` both 0, and remittances may be listed and narrowed by `owner_id` or
    by `status`."

    Design: Corner/errors/corner_topup_on_submitted_remittance_rejected
    """
    scenario = setup_owner_with_assessed_fee(
        travel_surcharge_cents=2500, owner_name="Topup Ranch", territory_code="T-TOPUP"
    )
    order = scenario["order"]
    remittance = tender_remittance(scenario["owner"]["id"], 2500, [order["id"]])
    assert remittance["status"] == "SUBMITTED"

    response = api.top_up_remittance(
        remittance["id"],
        top_up_remittance_payload(100),
        make_livestock_owner_headers(scenario["owner"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_REMITTANCE_INVALID_STATE.value, 409)

    unchanged = read_remittance(remittance["id"])
    assert unchanged["amount_cents"] == 2500
    assert unchanged["applied_cents"] == 0
    assert read_order(order["id"])["fee_status"] == "ASSESSED"


def test_waive_on_an_unassessed_order_is_refused(api):
    """PRD §3.9: "Either operation attempted against an order whose `hold_flag` is true
    is refused with `ERR_ORDER_HOLD_ACTIVE`; either attempted against a fee dimension
    that is `UNASSESSED`, `REMITTED` or `WAIVED` is refused with
    `ERR_FEE_INVALID_STATE`."
    PRD §3.5: "Neither dimension constrains the other's declared transitions except where
    a workflow explicitly says so, and a state check evaluates only the dimension the
    requested operation acts on."

    Design: Corner/errors/corner_waive_fee_on_unassessed_order_rejected
    """
    scenario = setup_order_in_field(
        territory_code="T-FEEST", owner_name="Fee State Ranch"
    )
    assert scenario["order"]["schedule_status"] == "IN_FIELD"
    assert scenario["order"]["fee_status"] == "UNASSESSED"

    response = api.waive_fee(scenario["order"]["id"], FEE_ADMIN)

    error = validate_error(response, ApiErrorId.ERR_FEE_INVALID_STATE.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_ORDER_INVALID_STATE.value

    order = read_order(scenario["order"]["id"])
    assert order["fee_status"] == "UNASSESSED"
    assert order["schedule_status"] == "IN_FIELD"


def test_statement_agrees_with_the_owner_row(api):
    """PRD §3.1: "The board also offers a computed statement read on any owner, which
    returns `owner_id`, the current `standing`, both arrears figures side by side, an
    `open_order_count` of the owner's inspection orders whose fee is still outstanding,
    and a `delinquent_order_count` of those that have already aged past their due date."
    PRD §3.9: "A fee assessed this morning contributes its full amount to the projected
    figure and nothing at all to the posted one, so for an owner with a single freshly
    assessed order the two figures differ by exactly that order's `assessed_fee_cents`."

    Design: Corner/endpoints/corner_owner_statement_agrees_with_owner_row
    """
    scenario = setup_owner_with_assessed_fee(
        travel_surcharge_cents=2500, owner_name="Statement Ranch", territory_code="T-STMT"
    )
    owner_headers = make_livestock_owner_headers(scenario["owner"]["id"])

    statement = validate_success(
        api.get_owner_statement(scenario["owner"]["id"], owner_headers), 200
    )
    owner = validate_success(
        api.get_owner(scenario["owner"]["id"], owner_headers), 200
    )

    assert statement["owner_id"] == scenario["owner"]["id"]
    assert statement["posted_arrears_cents"] == 0
    assert statement["projected_arrears_cents"] == 2500
    assert statement["standing"] == "GOOD"
    assert statement["open_order_count"] == 1
    assert statement["delinquent_order_count"] == 0

    assert owner["posted_arrears_cents"] == statement["posted_arrears_cents"]
    assert owner["projected_arrears_cents"] == statement["projected_arrears_cents"]
    assert owner["standing"] == statement["standing"]


# ─── Role separation on the fee desk ──────────────────────────────────────────

def test_board_admin_cannot_waive_a_fee(api):
    """PRD §2.1: "Each endpoint in §4 names the roles admitted to it; a caller whose role
    is not on that list is refused with `ERR_UNAUTHORIZED` (HTTP 403 Forbidden)."
    PRD §2.1: "A `FeeAdministrator` is the board's fee officer, who waives and voids
    assessments, reconciles remittances, disburses estray proceeds and runs the board's
    delinquency sweep."

    Design: Corner/rbac/corner_board_admin_cannot_waive_fee
    """
    scenario = setup_owner_with_assessed_fee(
        travel_surcharge_cents=2500, owner_name="Waive RBAC Ranch", territory_code="T-WV"
    )

    response = api.waive_fee(scenario["order"]["id"], BOARD_ADMIN)

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    order = read_order(scenario["order"]["id"])
    assert order["fee_status"] == "ASSESSED"
    assert order["assessed_fee_cents"] == 2500


def test_field_inspector_cannot_run_the_delinquency_sweep(api):
    """PRD §2.1: "Each endpoint in §4 names the roles admitted to it; a caller whose role
    is not on that list is refused with `ERR_UNAUTHORIZED` (HTTP 403 Forbidden)."
    PRD §3.9: "Time then does its work through the board's delinquency sweep, which a
    `FeeAdministrator` runs after moving the logical clock."

    Design: Corner/rbac/corner_field_inspector_cannot_run_delinquency_sweep
    """
    territory = open_district("T-RBAC")
    inspector = commission_inspector(territory["id"])

    response = api.delinquency_sweep(make_field_inspector_headers(inspector["id"]))

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
