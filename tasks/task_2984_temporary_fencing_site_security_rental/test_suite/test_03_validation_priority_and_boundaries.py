"""Validation-ladder precedence and boundary precision.

Covers the ordering guarantees of PRD §2.7 where a single request violates two
rungs at once, and the exact boundaries of the cancellation notice window of
PRD §3.9 and the flat footage tiers of PRD §3.2.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_ACCOUNT_CREDIT_HOLD,
    ERR_CREW_NOT_CERTIFIED,
    ERR_CREW_WINDOW_CONFLICT,
    ERR_WORK_ORDER_STATE,
)
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_integer,
    assert_invoice_rollup,
    assert_labor_hours,
    assert_line_types,
)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
# ---------------------------------------------------------------------------


def _credit_hold_world(api):
    """A mobilized contract whose account is one cent over its credit limit.

    The mobilization invoice totals 85487 cents against a credit limit of 85486,
    so ``credit_hold_flag`` is true while a completed install and a planned
    relocation both sit on the contract.
    """
    world = FX.seed_world(
        api,
        crews=(C.CREW_A, C.CREW_B),
        account={"credit_limit_cents": 85486},
        jobsite={"phase_count": 4},
    )
    contract, _quote = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=500
    )
    install = FX.plan_work_order(api, contract["id"], C.WO_DELIVERY_INSTALL, 500)
    relocation = FX.plan_work_order(api, contract["id"], C.WO_RELOCATION, 500)
    FX.set_clock(api, C.CLOCK_AUG_20)
    FX.dispatch(
        api, install["id"], world["crews"][C.CREW_A]["id"], "2026-08-20T08:00:00Z"
    )
    FX.complete(api, install["id"], 500)
    account = FX.read_account(api, world["account"]["id"])
    return world, contract, install, relocation, account


def test_dispatching_a_completed_visit_reports_state_not_credit_hold(api):
    """PRD §3.5: "A dispatch attempted against a visit that is not in `PLANNED`
    is `ERR_WORK_ORDER_STATE`." and "Because this gate sits at the top of the
    ladder, a visit that is simultaneously in the wrong state, on an unpermitted
    site, staffed by an uncertified crew, colliding with another booking, over
    the day's cap or short of fleet reports that other failure instead."

    Design: Difficulty/priority_pair_validation_conflict/work_order_state_error_precedes_credit_hold_on_dispatch
    """
    world, _contract, install, _relocation, account = _credit_hold_world(api)

    assert_cents(account["open_balance_cents"], 85487, "open_balance_cents")
    assert account["credit_hold_flag"] is True

    response = api.dispatch_work_order(
        install["id"],
        F.dispatch_payload(
            world["crews"][C.CREW_B]["id"], "2026-08-22T08:00:00Z"
        ),
        U.DISPATCH_COORDINATOR,
    )
    validate_error(response, ERR_WORK_ORDER_STATE, 409)

    unchanged = FX.read_work_order(api, install["id"])
    assert unchanged["status"] == C.WO_COMPLETED
    assert unchanged["crew_id"] == world["crews"][C.CREW_A]["id"]


def test_credit_hold_refuses_a_planned_visit_when_no_earlier_rung_is_violated(api):
    """PRD §3.5: "Dispatch is refused with `ERR_ACCOUNT_CREDIT_HOLD`, carrying
    HTTP 402, while the contract's owning account has `credit_hold_flag` true —
    that is, while its `open_balance_cents` is strictly greater than its
    `credit_limit_cents`."

    Design: Difficulty/priority_pair_validation_conflict/work_order_state_error_precedes_credit_hold_on_dispatch
    """
    world, _contract, _install, relocation, account = _credit_hold_world(api)

    assert account["credit_hold_flag"] is True

    response = api.dispatch_work_order(
        relocation["id"],
        F.dispatch_payload(
            world["crews"][C.CREW_B]["id"], "2026-08-22T08:00:00Z"
        ),
        U.DISPATCH_COORDINATOR,
    )
    validate_error(response, ERR_ACCOUNT_CREDIT_HOLD, 402)

    still_planned = FX.read_work_order(api, relocation["id"])
    assert still_planned["status"] == C.WO_PLANNED
    assert still_planned["crew_id"] is None

    body = api.list_work_orders(
        U.DISPATCH_COORDINATOR,
        params={
            "crew_id": world["crews"][C.CREW_B]["id"],
            "status": C.WO_SCHEDULED,
            "limit": C.MAX_LIMIT,
        },
    ).json()
    assert body["data"] == []


def _certification_world(api):
    """One uncertified crew whose diary already holds a two-hour install.

    Site X and Site Z are quoted with no screen; Site Y is quoted with
    ``SOLID_130``.  Site X's install occupies 08:00 to 10:00 and blocks the crew
    until 11:30, so a 10:30 candidate collides on the calendar whichever site it
    belongs to.
    """
    world = FX.seed_world(
        api,
        clock=C.CLOCK_AUG_20,
        crews=("CRW-U",),
        crew_overrides={
            "daily_capacity_hours": 24.0,
            "certified_for_solid_screen": False,
        },
        jobsite={"site_label": "Site X", "address_line": "1 Foundry Road"},
    )
    crew = world["crews"]["CRW-U"]
    site_y = FX.add_jobsite(
        world, api, site_label="Site Y", address_line="2 Foundry Road"
    )
    site_z = FX.add_jobsite(
        world, api, site_label="Site Z", address_line="3 Foundry Road"
    )

    contract_x, quote_x = FX.seed_contract(
        api, world["jobsite"]["id"], world["account"]["id"], linear_feet=200
    )
    contract_y, quote_y = FX.seed_contract(
        api,
        site_y["id"],
        world["account"]["id"],
        linear_feet=200,
        wind_screen=C.SCREEN_SOLID_130,
    )
    contract_z, _quote_z = FX.seed_contract(
        api, site_z["id"], world["account"]["id"], linear_feet=200
    )

    install_x = FX.plan_work_order(api, contract_x["id"], C.WO_DELIVERY_INSTALL, 200)
    install_y = FX.plan_work_order(api, contract_y["id"], C.WO_DELIVERY_INSTALL, 200)
    install_z = FX.plan_work_order(api, contract_z["id"], C.WO_DELIVERY_INSTALL, 200)

    scheduled_x = FX.dispatch(
        api, install_x["id"], crew["id"], "2026-08-20T08:00:00Z"
    )
    return {
        "crew": crew,
        "quote_x": quote_x,
        "quote_y": quote_y,
        "install_x": scheduled_x,
        "install_y": install_y,
        "install_z": install_z,
    }


def test_screen_certification_precedes_the_crew_calendar_gate(api):
    """PRD §3.5: "Certification is deliberately checked before the crew's
    calendar, so an uncertified crew is refused even when its diary is
    completely empty."

    Design: Difficulty/priority_pair_validation_conflict/crew_certification_precedes_crew_window_conflict
    """
    state = _certification_world(api)

    assert_labor_hours(state["install_x"]["estimated_labor_hours"], 2.00)
    assert_instant(
        state["install_x"]["scheduled_end_utc"],
        "2026-08-20T10:00:00Z",
        "scheduled_end_utc",
    )
    assert_cents(
        state["quote_x"]["monthly_recurring_cents"], 12400, "monthly_recurring_cents"
    )
    assert_cents(
        state["quote_y"]["monthly_recurring_cents"], 21940, "monthly_recurring_cents"
    )
    assert_cents(state["quote_y"]["install_labor_cents"], 35000, "install_labor_cents")
    assert_cents(state["quote_y"]["one_time_cents"], 66000, "one_time_cents")

    response = api.dispatch_work_order(
        state["install_y"]["id"],
        F.dispatch_payload(state["crew"]["id"], "2026-08-20T10:30:00Z"),
        U.DISPATCH_COORDINATOR,
    )
    validate_error(response, ERR_CREW_NOT_CERTIFIED, 409)

    unmoved = FX.read_work_order(api, state["install_y"]["id"])
    assert unmoved["status"] == C.WO_PLANNED
    assert unmoved["crew_id"] is None


def test_crew_window_conflict_reported_when_certification_is_not_in_question(api):
    """PRD §3.5: "The candidate collides when its own such interval intersects
    that of any other `SCHEDULED` visit of the same crew, using the intersection
    rule of §2.6 ... A collision is `ERR_CREW_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/crew_certification_precedes_crew_window_conflict
    """
    state = _certification_world(api)

    response = api.dispatch_work_order(
        state["install_z"]["id"],
        F.dispatch_payload(state["crew"]["id"], "2026-08-20T10:30:00Z"),
        U.DISPATCH_COORDINATOR,
    )
    validate_error(response, ERR_CREW_WINDOW_CONFLICT, 409)

    unmoved = FX.read_work_order(api, state["install_z"]["id"])
    assert unmoved["status"] == C.WO_PLANNED
    assert unmoved["crew_id"] is None
    assert FX.read_work_order(api, state["install_x"]["id"])["status"] == C.WO_SCHEDULED


# ---------------------------------------------------------------------------
# boundary_precision_check
# ---------------------------------------------------------------------------


def _event_contract_with_scheduled_install(api):
    """An EVENT contract of 250 ft with ten barricades, install due 08-24 09:00.

    Pricing: monthly_recurring_cents 60000 and install_labor_cents 48750.
    """
    world = FX.seed_world(
        api,
        addons=(C.BARRICADE_CODE,),
        event_account=True,
        jobsite={"site_label": "Festival Lot A", "address_line": "11 Quay Street"},
    )
    state = FX.seed_scheduled_install(
        api,
        world,
        event=True,
        linear_feet=250,
        addon_lines=[F.addon_line(C.BARRICADE_CODE, 10)],
        dispatch_clock=C.CLOCK_AUG_20,
        scheduled_start="2026-08-24T09:00:00Z",
    )
    state["world"] = world
    return state


def test_cancellation_at_exactly_seventy_two_hours_notice_is_free(api):
    """PRD §3.9: "the boundary itself is free, so notice of exactly 72 hours on
    an event contract costs nothing while notice of 71 hours does not." and
    "When the fee is exactly zero **no invoice is created at all** and the money
    dimension does not move."

    Design: Difficulty/boundary_precision_check/cancellation_notice_72_hour_boundary
    """
    state = _event_contract_with_scheduled_install(api)
    contract = FX.read_contract(api, state["contract"]["id"])
    assert_cents(contract["monthly_recurring_cents"], 60000, "monthly_recurring_cents")
    assert_cents(contract["install_labor_cents"], 48750, "install_labor_cents")

    FX.set_clock(api, C.CLOCK_AUG_21_09)
    cancelled = validate_success(
        api.cancel_contract(
            contract["id"], F.cancel_payload("EVENT_POSTPONED"), U.ACCOUNT_MANAGER
        )
    )

    assert_cents(cancelled["cancellation_fee_cents"], 0, "cancellation_fee_cents")
    assert cancelled["lifecycle_status"] == C.LIFECYCLE_CANCELLED
    assert cancelled["billing_status"] == C.BILLING_NOT_BILLED
    assert FX.invoices_for(api, contract["id"]) == []

    account = FX.read_account(api, state["world"]["account"]["id"])
    assert_cents(account["open_balance_cents"], 0, "open_balance_cents")
    assert FX.read_work_order(api, state["install"]["id"])["status"] == C.WO_CANCELLED
    panel = FX.read_product(api, state["world"]["panel"]["id"])
    assert_integer(panel["reserved_count"], 0, "reserved_count")
    assert_integer(panel["available_count"], 400, "available_count")


def test_cancellation_one_hour_inside_the_window_charges_the_event_forfeit(api):
    """PRD §3.9: "An `EVENT` contract owes half of its `monthly_recurring_cents`,
    rounded half up, plus the whole of its `install_labor_cents`" and "a
    `CANCELLATION` invoice is issued against the contract carrying a single
    `CANCELLATION_FEE` line for that amount".

    Design: Difficulty/boundary_precision_check/cancellation_notice_72_hour_boundary
    """
    state = _event_contract_with_scheduled_install(api)
    contract_id = state["contract"]["id"]

    FX.set_clock(api, C.CLOCK_AUG_21_10)
    cancelled = validate_success(
        api.cancel_contract(
            contract_id, F.cancel_payload("EVENT_POSTPONED"), U.ACCOUNT_MANAGER
        )
    )

    assert_cents(cancelled["cancellation_fee_cents"], 78750, "cancellation_fee_cents")
    assert cancelled["lifecycle_status"] == C.LIFECYCLE_CANCELLED

    invoices = FX.invoices_for(api, contract_id)
    assert len(invoices) == 1, invoices
    invoice = invoices[0]
    assert invoice["invoice_kind"] == C.KIND_CANCELLATION
    assert_line_types(invoice, [C.LINE_CANCELLATION_FEE])
    assert_cents(invoice["lines"][0]["amount_cents"], 78750, "CANCELLATION_FEE")
    assert invoice["lines"][0]["product_code"] is None
    assert_integer(invoice["lines"][0]["quantity"], 1, "quantity")
    assert_invoice_rollup(invoice, subtotal=78750, tax=7009, late_fee=0, total=85759)

    account = FX.read_account(api, state["world"]["account"]["id"])
    assert_cents(account["open_balance_cents"], 85759, "open_balance_cents")
    assert FX.read_work_order(api, state["install"]["id"])["status"] == C.WO_CANCELLED


def _tier_quote(api, world, label, address, linear_feet):
    site = FX.add_jobsite(world, api, site_label=label, address_line=address)
    return FX.seed_quote(api, site["id"], linear_feet=linear_feet)


def test_flat_footage_tier_makes_the_rent_drop_at_two_hundred_fifty_one_feet(api):
    """PRD §3.2: "The rate is **flat on the total footage, not marginal**: the
    entire run is priced at the rate of the band the footage falls into. A run of
    at most 250 feet is priced at 62 cents per foot; a run above 250 feet and at
    most 500 feet at 54 cents per foot".

    Design: Difficulty/boundary_precision_check/panel_tier_boundary_at_250_and_500_feet
    """
    world = FX.seed_world(api)
    at_250 = _tier_quote(api, world, "Tier Site 250", "1 Foundry Road", 250)
    at_251 = _tier_quote(api, world, "Tier Site 251", "2 Foundry Road", 251)

    assert_integer(at_250["tier_rate_cents_per_ft"], 62, "tier_rate_cents_per_ft")
    assert_cents(at_250["monthly_recurring_cents"], 15500, "monthly_recurring_cents")
    assert_cents(at_250["install_labor_cents"], 35000, "install_labor_cents")
    assert_cents(at_250["one_time_cents"], 66000, "one_time_cents")
    assert_integer(at_250["panel_unit_count"], 25, "panel_unit_count")

    assert_integer(at_251["tier_rate_cents_per_ft"], 54, "tier_rate_cents_per_ft")
    assert_cents(at_251["monthly_recurring_cents"], 13554, "monthly_recurring_cents")
    assert_cents(at_251["install_labor_cents"], 35000, "install_labor_cents")
    assert_cents(at_251["one_time_cents"], 66000, "one_time_cents")
    assert_integer(at_251["panel_unit_count"], 26, "panel_unit_count")

    assert at_251["monthly_recurring_cents"] < at_250["monthly_recurring_cents"]


def test_flat_footage_tier_makes_the_rent_drop_at_five_hundred_one_feet(api):
    """PRD §3.2: "a run above 250 feet and at most 500 feet at 54 cents per foot;
    a run above 500 feet and at most 1000 feet at 47 cents per foot" — one extra
    foot across a band edge re-rates the entire run.

    Design: Difficulty/boundary_precision_check/panel_tier_boundary_at_250_and_500_feet
    """
    world = FX.seed_world(api)
    at_500 = _tier_quote(api, world, "Tier Site 500", "3 Foundry Road", 500)
    at_501 = _tier_quote(api, world, "Tier Site 501", "4 Foundry Road", 501)

    assert_integer(at_500["tier_rate_cents_per_ft"], 54, "tier_rate_cents_per_ft")
    assert_cents(at_500["monthly_recurring_cents"], 27000, "monthly_recurring_cents")
    assert_cents(at_500["install_labor_cents"], 47500, "install_labor_cents")
    assert_cents(at_500["one_time_cents"], 78500, "one_time_cents")
    assert_integer(at_500["panel_unit_count"], 50, "panel_unit_count")

    assert_integer(at_501["tier_rate_cents_per_ft"], 47, "tier_rate_cents_per_ft")
    assert_cents(at_501["monthly_recurring_cents"], 23547, "monthly_recurring_cents")
    assert_cents(at_501["install_labor_cents"], 47595, "install_labor_cents")
    assert_cents(at_501["one_time_cents"], 78595, "one_time_cents")
    assert_integer(at_501["panel_unit_count"], 51, "panel_unit_count")

    assert at_501["monthly_recurring_cents"] < at_500["monthly_recurring_cents"]
