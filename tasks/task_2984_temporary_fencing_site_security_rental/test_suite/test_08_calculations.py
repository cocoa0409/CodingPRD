"""Arithmetic, floors, aggregate membership and allocation order.

Covers the labor estimate of PRD §3.5 with its quarter-hour ceiling and its
two-hour floor, the closure-corridor aggregate of PRD §3.4, the ground-condition
labor constants of PRD §3.2 and the oldest-due payment waterfall of PRD §3.8.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import ERR_PAYMENT_EXCEEDS_BALANCE
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_integer,
    assert_invoice_rollup,
    assert_labor_hours,
)


def test_the_two_hour_floor_bites_the_removal_but_not_the_install(api):
    """PRD §3.5: "That raw estimate is then quantised **upward** to the smallest
    multiple of 0.25 hours that is at or above it ... Finally,
    `estimated_labor_hours` is the greater of a two-hour minimum billable figure
    and the quantised estimate." 250 feet at 120 feet an hour ceils to 2.25; the
    same 250 feet at 200 feet an hour ceils to 1.25 and is then lifted to 2.00.

    Design: Corner/calculations/removal_labor_hours_hit_the_two_hour_minimum_floor
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Foundry Road Phase Yard",
            "address_line": "402 Foundry Road",
            "site_condition": C.CONDITION_SOIL,
            "phase_count": 4,
        },
    )
    contract, quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=250
    )

    # 250 * 95 is 23750, below the 35,000-cent mobilization minimum of step nine.
    assert_cents(quote["install_labor_cents"], 35000, "install_labor_cents")
    assert_cents(quote["monthly_recurring_cents"], 15500, "monthly_recurring_cents")
    assert_cents(quote["one_time_cents"], 66000, "one_time_cents")

    install = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 250)
    scheduled_install = FX.dispatch(
        api, install["id"], world["crew"]["id"], "2026-08-03T08:00:00Z"
    )
    FX.complete(api, install["id"], 250)
    removal = FX.plan_work_order(api, contract["id"], C.WO_REMOVAL, 250)

    scheduled_removal = validate_success(
        api.dispatch_work_order(
            removal["id"],
            F.dispatch_payload(world["crew"]["id"], "2026-08-05T08:00:00Z"),
            U.DISPATCH_COORDINATOR,
        )
    )

    assert scheduled_removal["status"] == C.WO_SCHEDULED
    assert_labor_hours(scheduled_removal["estimated_labor_hours"], 2.00)
    assert_instant(
        scheduled_removal["scheduled_end_utc"],
        "2026-08-05T10:00:00Z",
        "scheduled_end_utc",
    )
    assert scheduled_removal["reserved_unit_counts"] == []

    # The install's own figure is the quarter-hour ceiling, untouched by the floor.
    assert_labor_hours(scheduled_install["estimated_labor_hours"], 2.25)
    reread_install = FX.read_work_order(api, install["id"])
    assert_labor_hours(reread_install["estimated_labor_hours"], 2.25)
    assert_instant(
        reread_install["scheduled_end_utc"],
        "2026-08-03T10:15:00Z",
        "scheduled_end_utc",
    )

    reread_contract = FX.read_contract(api, contract["id"])
    assert_cents(reread_contract["install_labor_cents"], 35000, "install_labor_cents")
    assert_cents(
        reread_contract["monthly_recurring_cents"], 15500, "monthly_recurring_cents"
    )
    assert_cents(reread_contract["one_time_cents"], 66000, "one_time_cents")


def test_draft_and_denied_applications_never_enter_the_corridor_aggregate(api):
    """PRD §3.4: the contending set is "the other permit applications of the same
    jurisdiction whose `status` is `SUBMITTED` or `APPROVED` and whose closure
    window intersects the candidate's", and "a projected total exactly equal to the
    cap is admitted". A 600-foot `DRAFT` and a 200-foot `DENIED` application
    sharing the window therefore contribute nothing.

    Design: Corner/calculations/draft_and_denied_permits_hold_no_corridor_footage
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Dock Street North",
            "address_line": "8 Dock Street",
            "site_condition": C.CONDITION_ASPHALT,
            "phase_count": 2,
            "requires_sidewalk_closure": True,
        },
    )
    north = world["jobsite"]
    south = FX.add_jobsite(
        world,
        api,
        site_label="Dock Street South",
        address_line="11 Dock Street",
        site_condition=C.CONDITION_ASPHALT,
        phase_count=2,
        requires_sidewalk_closure=True,
    )

    approved = FX.seed_approved_permit(api, north["id"], closure_linear_feet=300)
    assert approved["status"] == C.PERMIT_APPROVED

    left_in_draft = FX.seed_permit(
        api,
        south["id"],
        closure_linear_feet=600,
        sidewalk_closure_type=C.CLOSURE_FULL,
    )
    refused = FX.seed_permit(
        api,
        south["id"],
        closure_linear_feet=200,
        sidewalk_closure_type=C.CLOSURE_LANE_SHIFT,
    )
    FX.submit_permit(api, refused["id"])
    denied = FX.decide_permit(
        api,
        refused["id"],
        C.DECISION_DENY,
        reviewer_note="lane shift conflicts with transit detour",
    )
    assert denied["status"] == C.PERMIT_DENIED

    candidate = FX.seed_permit(
        api,
        north["id"],
        closure_linear_feet=500,
        closure_start_utc="2026-08-12T00:00:00Z",
        closure_end_utc="2026-08-18T00:00:00Z",
    )

    submitted = validate_success(
        api.submit_permit(candidate["id"], U.MUNICIPAL_LIAISON, F.submit_payload())
    )

    # 300 approved plus the 500 candidate is exactly the 800-foot cap, and equality
    # is admitted; the 600 DRAFT and the 200 DENIED would have blown through it.
    assert submitted["status"] == C.PERMIT_SUBMITTED
    assert_integer(submitted["closure_linear_feet"], 500, "closure_linear_feet")
    assert FX.read_permit(api, left_in_draft["id"])["status"] == C.PERMIT_DRAFT
    assert FX.read_permit(api, refused["id"])["status"] == C.PERMIT_DENIED

    decided = FX.decide_permit(
        api,
        candidate["id"],
        C.DECISION_APPROVE,
        reviewer_note="sequenced behind the north closure",
    )
    assert decided["status"] == C.PERMIT_APPROVED

    FX.set_clock(api, "2026-08-12T00:00:00Z")
    municipality = FX.read_municipality(api, world["municipality"]["id"])
    assert_integer(
        municipality["committed_closure_linear_feet"],
        800,
        "committed_closure_linear_feet",
    )
    assert_integer(
        municipality["max_concurrent_closure_linear_feet"],
        C.HRB_MAX_CLOSURE_FT,
        "max_concurrent_closure_linear_feet",
    )


def test_the_ground_condition_moves_only_the_one_time_charge(api):
    """PRD §3.2 step nine reads the per-foot condition labor rate — "95 cents per
    foot on `SOIL`, 140 cents per foot on `ASPHALT`, 210 cents per foot on
    `CONCRETE`" — from the jobsite, and step eleven folds it into `one_time_cents`.
    None of the recurring steps see it.

    Design: Corner/calculations/site_condition_labor_constants_move_only_the_one_time_charge
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Foundry Road Soil Pad",
            "address_line": "402 Foundry Road",
            "site_condition": C.CONDITION_SOIL,
        },
    )
    concrete_site = FX.add_jobsite(
        world,
        api,
        site_label="Foundry Road Concrete Deck",
        address_line="406 Foundry Road",
        site_condition=C.CONDITION_CONCRETE,
    )

    on_soil = validate_success(
        api.create_quote(
            world["jobsite"]["id"],
            F.quote_payload(
                FX.jobsite_version(api, world["jobsite"]["id"]),
                linear_feet=500,
                term_months=3,
                wind_screen=C.SCREEN_NONE,
            ),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    on_concrete = validate_success(
        api.create_quote(
            concrete_site["id"],
            F.quote_payload(
                FX.jobsite_version(api, concrete_site["id"]),
                linear_feet=500,
                term_months=3,
                wind_screen=C.SCREEN_NONE,
            ),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )

    # The condition constant never touches steps one through eight.
    assert_cents(on_soil["monthly_recurring_cents"], 27000, "monthly_recurring_cents")
    assert_cents(
        on_concrete["monthly_recurring_cents"], 27000, "monthly_recurring_cents"
    )

    assert_cents(on_soil["install_labor_cents"], 47500, "install_labor_cents")
    assert_cents(on_concrete["install_labor_cents"], 105000, "install_labor_cents")
    assert_cents(on_soil["one_time_cents"], 78500, "one_time_cents")
    assert_cents(on_concrete["one_time_cents"], 136000, "one_time_cents")
    assert (
        on_concrete["one_time_cents"] - on_soil["one_time_cents"]
        == 500 * (C.INSTALL_RATE_CENTS_PER_FT[C.CONDITION_CONCRETE]
                  - C.INSTALL_RATE_CENTS_PER_FT[C.CONDITION_SOIL])
    )

    for quote in (on_soil, on_concrete):
        assert_cents(
            quote["permit_handling_fee_cents"], 12500, "permit_handling_fee_cents"
        )
        assert_integer(quote["panel_unit_count"], 50, "panel_unit_count")


def test_a_payment_fills_the_oldest_due_invoice_before_the_next(api):
    """PRD §3.8: "Each invoice in turn absorbs the lesser of the remaining amount
    and its own open amount ... The first bucket fills completely before the second
    receives anything; there is no proportional spreading." And at rung 26 "a
    payment larger than the account's total open amount ... is **refused in full**
    ... no invoice is mutated at all and no partial allocation is retained."

    Design: Corner/calculations/payment_fills_the_oldest_due_invoice_before_the_next
    """
    world = FX.seed_world(
        api,
        jobsite={
            "site_label": "Foundry Road Phase Yard",
            "address_line": "402 Foundry Road",
            "site_condition": C.CONDITION_SOIL,
            "phase_count": 4,
        },
    )
    account_id = world["account"]["id"]
    state = FX.seed_installed_contract(
        api,
        world,
        linear_feet=500,
        install_clock=C.CLOCK_AUG_01,
        install_start="2026-08-03T08:00:00Z",
    )
    contract_id = state["contract"]["id"]

    mobilization = state["mobilization_invoice"]
    assert mobilization is not None, "the mobilization cascade must issue an invoice"
    assert_invoice_rollup(mobilization, subtotal=78500, tax=6987, late_fee=0, total=85487)
    assert_instant(mobilization["due_at_utc"], "2026-08-31T00:00:00Z", "due_at_utc")
    assert mobilization["status"] == C.INVOICE_ISSUED

    # A run that closes two days before the mobilization invoice falls due, so the
    # money dimension is still CURRENT when the period is priced.
    FX.set_clock(api, "2026-08-29T00:00:00Z")
    assert FX.read_contract(api, contract_id)["billing_status"] == C.BILLING_CURRENT
    periodic = validate_success(
        api.create_billing_run(
            contract_id,
            F.billing_run_payload(C.CLOCK_AUG_01, "2026-08-29T00:00:00Z"),
            U.ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )
    assert_integer(periodic["billable_days"], 28, "billable_days")
    assert_invoice_rollup(periodic, subtotal=27000, tax=2403, late_fee=0, total=29403)
    assert_instant(periodic["due_at_utc"], "2026-09-28T00:00:00Z", "due_at_utc")

    filled = FX.pay_account(api, account_id, 85487)

    assert_cents(filled["open_balance_cents"], 29403, "open_balance_cents")
    paid = FX.read_invoice(api, mobilization["id"])
    assert paid["status"] == C.INVOICE_PAID
    assert_cents(paid["amount_paid_cents"], 85487, "amount_paid_cents")
    untouched = FX.read_invoice(api, periodic["id"])
    assert untouched["status"] == C.INVOICE_ISSUED
    assert_cents(untouched["amount_paid_cents"], 0, "amount_paid_cents")

    validate_error(
        api.create_payment(
            account_id, F.payment_payload(29404), U.ACCOUNT_MANAGER_2
        ),
        ERR_PAYMENT_EXCEEDS_BALANCE,
        409,
    )

    still_open = FX.read_invoice(api, periodic["id"])
    assert still_open["status"] == C.INVOICE_ISSUED
    assert_cents(still_open["amount_paid_cents"], 0, "amount_paid_cents")
    assert_integer(still_open["version"], untouched["version"], "version")
    assert_cents(
        FX.read_account(api, account_id)["open_balance_cents"], 29403, "open_balance_cents"
    )

    partial = FX.pay_account(api, account_id, 10000)

    assert_cents(partial["open_balance_cents"], 19403, "open_balance_cents")
    assert partial["credit_hold_flag"] is False
    part_paid = FX.read_invoice(api, periodic["id"])
    assert part_paid["status"] == C.INVOICE_PARTIALLY_PAID
    assert_cents(part_paid["amount_paid_cents"], 10000, "amount_paid_cents")
    assert FX.read_invoice(api, mobilization["id"])["status"] == C.INVOICE_PAID
