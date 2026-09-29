"""Corner cases of the billing, credit and placement guards of the upfront API.

The file covers invoice issue against an unfunded campaign, the issue replay, an
overpaying client payment, the credit-limit and credit-hold refusals, the
posture-blocked plan re-submission, and the fully guarded placement that passes
every one of those rules.
"""

from test_helpers import (
    BUYER_HEADERS,
    BUYER_USER_ID,
    CONTROLLER_HEADERS,
    PLANNER_HEADERS,
    AiringOutcome,
    AllocationPosture,
    AllocationStatus,
    ApiErrorId,
    BuyStatus,
    CategoryCode,
    Channel,
    CreditStatus,
    Daypart,
    ExclusivityMode,
    InvoiceClientStatus,
    MakeGoodProvision,
    Market,
    PlanPosture,
    PlanStatus,
    Platform,
    SettlementStatus,
    assert_allocation_posture,
    assert_buy_axes,
    assert_campaign_axes,
    assert_cents,
    assert_impressions,
    assert_instant_field,
    assert_invoice_axes,
    assert_null_instant,
    fixtures as fx,
    get_success_data,
    make_advertiser_client_headers,
    make_seller_rep_headers,
    validate_error,
    validate_success,
)

# --------------------------------------------------------------------------
# The calendar and the figures the design's payloads imply
# --------------------------------------------------------------------------
#: Flight of the baseline campaign, and the window of the avail serving it.
_FLIGHT_START = "2026-11-01T00:00:00Z"
_FLIGHT_END = "2026-12-31T23:59:59Z"

#: Air window of the single ordered unit line.
_AIR_WINDOW_START = "2026-11-02T00:00:00Z"
_AIR_WINDOW_END = "2026-11-30T23:59:59Z"

#: Billing period that captures that line's air window end.
_BILLING_PERIOD_START = "2026-11-01T00:00:00Z"
_BILLING_PERIOD_END = "2026-11-30T23:59:59Z"

#: The instant the November air window has elapsed at, and the issue instant.
_AFTER_AIR_WINDOW = "2026-12-01T00:00:00Z"

#: Thirty days of payment terms after that issue instant.
_DUE_DATE = "2026-12-31T00:00:00Z"

#: An instant well past the due date, so a payment made there is late.
_AFTER_DUE_DATE = "2027-01-05T00:00:00Z"

#: The guarantee the parties settle on, and the price they settle it at.
_GUARANTEED_IMPRESSIONS = 1_000_000
_AGREED_CPM_CENTS = 2_200

#: The gross those two figures imply once the top commission tier is applied to
#: a 2,200,000-cent net.
_GROSS_COST_CENTS = 2_354_000

#: The one aired line bills exactly that gross, and nothing is credited back.
_NET_PAYABLE_CENTS = 2_354_000

#: The campaign's authorised budget and the headroom the placement leaves.
_TOTAL_BUDGET_CENTS = 10_000_000
_UNCOMMITTED_BUDGET_CENTS = 7_646_000


def _advertiser_payload(credit_limit_cents: int) -> dict:
    """The brand client, whose credit limit the scenario chooses."""
    return {
        "name": "Cascadia Beverage",
        "category_code": CategoryCode.BEVERAGE.value,
        "credit_limit_cents": credit_limit_cents,
        "payment_terms_days": 30,
        "sequential_liability_enabled": True,
    }


_SELLER_PAYLOAD = {
    "name": "Harbor Broadcasting",
    "platform_types": [
        Platform.LINEAR.value,
        Platform.CTV.value,
        Platform.DIGITAL.value,
    ],
    "make_good_capacity_impressions": 50_000_000,
}

_CAMPAIGN_PAYLOAD = {
    "name": "Q4 Linear Base",
    "target_demo": "A25-54",
    "universe_thousands": 120_000,
    "reach_goal_pct": 60.00,
    "frequency_goal": 4.00,
    "total_budget_cents": _TOTAL_BUDGET_CENTS,
    "flight_start": _FLIGHT_START,
    "flight_end": _FLIGHT_END,
    "fiscal_quarter": "2026Q4",
}

_SECOND_CAMPAIGN_PAYLOAD = {
    "name": "Q1 Follow-On",
    "target_demo": "A18-34",
    "universe_thousands": 120_000,
    "reach_goal_pct": 50.00,
    "frequency_goal": 3.00,
    "total_budget_cents": 8_000_000,
    "flight_start": "2027-03-01T00:00:00Z",
    "flight_end": "2027-04-30T23:59:59Z",
    "fiscal_quarter": "2027Q1",
}

#: The whole plan on one linear line.
_FULL_LINEAR_ALLOCATION = {
    "channel": Channel.LINEAR_TV.value,
    "allocation_pct": 100.00,
    "planned_cpm_cents": 2_000,
    "planned_market": Market.UPFRONT.value,
    "primary_daypart": Daypart.PRIME.value,
}

#: A tenth of the plan on linear, which one baseline buy overcommits.
_THIN_LINEAR_ALLOCATION = {
    "channel": Channel.LINEAR_TV.value,
    "allocation_pct": 10.00,
    "planned_cpm_cents": 2_000,
    "planned_market": Market.UPFRONT.value,
    "primary_daypart": Daypart.PRIME.value,
}

#: The connected-television line that completes that plan to a hundred per cent.
_FAT_CTV_ALLOCATION = {
    "channel": Channel.CTV.value,
    "allocation_pct": 90.00,
    "planned_cpm_cents": 1_500,
    "planned_market": Market.UPFRONT.value,
    "primary_daypart": Daypart.DIGITAL_ANY.value,
}

_AVAIL_PAYLOAD = {
    "market": Market.UPFRONT.value,
    "fiscal_quarter": "2026Q4",
    "daypart": Daypart.PRIME.value,
    "program": "Harbor Nightly",
    "platform": Platform.LINEAR.value,
    "window_start": _FLIGHT_START,
    "window_end": _FLIGHT_END,
    "total_impressions": 10_000_000,
    "forecast_cpm_cents": 2_200,
    "exclusivity_mode": ExclusivityMode.SHARED.value,
}

_UNIT_PAYLOAD = {
    "daypart": Daypart.PRIME.value,
    "program": "Harbor Nightly",
    "platform": Platform.LINEAR.value,
    "units": 1,
    "unit_rate_cents": 2_200_000,
    "projected_impressions": _GUARANTEED_IMPRESSIONS,
    "air_window_start": _AIR_WINDOW_START,
    "air_window_end": _AIR_WINDOW_END,
    "exclusive": False,
}


# --------------------------------------------------------------------------
# Shared setup: the approved linear plan, the negotiated buy and its one line
# --------------------------------------------------------------------------
def _planned_world(
    api,
    credit_limit_cents: int = 500_000_000,
    allocations=None,
) -> dict:
    """Approves the plan, publishes the avail, negotiates a buy and orders one line.

    The buy is left at ``PENDING_PLACEMENT`` so a caller can place it, or trigger
    the placement itself.
    """
    advertiser = get_success_data(
        api.create_advertiser(_advertiser_payload(credit_limit_cents), CONTROLLER_HEADERS)
    )
    seller = get_success_data(api.create_seller(dict(_SELLER_PAYLOAD), CONTROLLER_HEADERS))
    client_headers = make_advertiser_client_headers(advertiser["id"])
    seller_headers = make_seller_rep_headers(seller["id"])

    campaign = get_success_data(
        api.create_campaign(
            dict(_CAMPAIGN_PAYLOAD, advertiser_id=advertiser["id"]), PLANNER_HEADERS
        )
    )
    specs = [dict(_FULL_LINEAR_ALLOCATION)] if allocations is None else allocations
    allocation_rows = [
        get_success_data(
            api.create_channel_allocation(
                dict(spec, campaign_id=campaign["id"]), PLANNER_HEADERS
            )
        )
        for spec in specs
    ]
    get_success_data(api.submit_plan(campaign["id"], None, PLANNER_HEADERS))
    get_success_data(api.approve_plan(campaign["id"], None, client_headers))

    avail = get_success_data(
        api.create_inventory_forecast(
            dict(_AVAIL_PAYLOAD, seller_id=seller["id"]), seller_headers
        )
    )
    get_success_data(api.publish_inventory_forecast(avail["id"], None, seller_headers))

    negotiation = get_success_data(
        api.create_negotiation(
            {
                "campaign_id": campaign["id"],
                "seller_id": seller["id"],
                "channel_allocation_id": allocation_rows[0]["id"],
                "market": Market.UPFRONT.value,
                "channel": Channel.LINEAR_TV.value,
                "requested_impressions": _GUARANTEED_IMPRESSIONS,
                "opening_cpm_cents": 2_000,
                "guarantee_pct": 100,
                "make_good_provision": MakeGoodProvision.MAKE_GOOD_UNITS.value,
                "option_pct_ceiling": 25,
            },
            BUYER_HEADERS,
        )
    )
    get_success_data(
        api.counter_negotiation(
            negotiation["id"],
            {
                "expected_negotiation_version": negotiation["version"],
                "counter_cpm_cents": _AGREED_CPM_CENTS,
                "counter_impressions": _GUARANTEED_IMPRESSIONS,
            },
            seller_headers,
        )
    )
    buy = get_success_data(api.accept_negotiation(negotiation["id"], None, BUYER_HEADERS))
    unit = get_success_data(
        api.add_buy_unit(
            buy["id"], dict(_UNIT_PAYLOAD, forecast_id=avail["id"]), BUYER_HEADERS
        )
    )
    return {
        "advertiser_id": advertiser["id"],
        "seller_id": seller["id"],
        "client_headers": client_headers,
        "seller_headers": seller_headers,
        "campaign_id": campaign["id"],
        "allocation_ids": [row["id"] for row in allocation_rows],
        "allocation_id": allocation_rows[0]["id"],
        "forecast_id": avail["id"],
        "negotiation_id": negotiation["id"],
        "buy_id": buy["id"],
        "unit_id": unit["id"],
    }


def _placed_world(api, **options) -> dict:
    """The planned world with its one covering line actually placed."""
    world = _planned_world(api, **options)
    version = get_success_data(api.get_campaign(world["campaign_id"], BUYER_HEADERS))[
        "version"
    ]
    world["buy"] = get_success_data(
        api.place_buy(
            world["buy_id"], {"expected_campaign_version": version}, BUYER_HEADERS
        )
    )
    return world


def _drafted_invoice_world(api, **options) -> dict:
    """The placed world, its line settled as aired, and one draft invoice raised."""
    world = _placed_world(api, **options)
    fx.move_clock(api, _AFTER_AIR_WINDOW)
    get_success_data(
        api.settle_airing(
            world["unit_id"],
            {
                "outcome": AiringOutcome.AIRED.value,
                "actual_impressions": _GUARANTEED_IMPRESSIONS,
            },
            world["seller_headers"],
        )
    )
    invoice = get_success_data(
        api.create_invoice(
            {
                "buy_id": world["buy_id"],
                "billing_period_start": _BILLING_PERIOD_START,
                "billing_period_end": _BILLING_PERIOD_END,
            },
            CONTROLLER_HEADERS,
        )
    )
    world["invoice_id"] = invoice["id"]
    return world


def _issued_invoice_world(api, **options) -> dict:
    """The drafted invoice, funded to the cent and issued to the client."""
    world = _drafted_invoice_world(api, **options)
    get_success_data(
        api.fund_campaign(
            world["campaign_id"],
            {"amount_cents": _NET_PAYABLE_CENTS},
            world["client_headers"],
        )
    )
    get_success_data(api.issue_invoice(world["invoice_id"], None, CONTROLLER_HEADERS))
    return world


def _second_plan(api, advertiser_id: str, submit: bool = True) -> dict:
    """A follow-on campaign carrying one full linear allocation."""
    campaign = get_success_data(
        api.create_campaign(
            dict(_SECOND_CAMPAIGN_PAYLOAD, advertiser_id=advertiser_id), PLANNER_HEADERS
        )
    )
    allocation = get_success_data(
        api.create_channel_allocation(
            dict(_FULL_LINEAR_ALLOCATION, campaign_id=campaign["id"]), PLANNER_HEADERS
        )
    )
    if submit:
        get_success_data(api.submit_plan(campaign["id"], None, PLANNER_HEADERS))
    return {"campaign_id": campaign["id"], "allocation_id": allocation["id"]}


class TestInvoiceIssueAgainstUnfundedCampaign:
    """Issue refuses to bill a campaign that holds none of the client's cash."""

    def test_issuing_an_invoice_the_campaign_has_not_funded_is_rejected(self, api):
        """An aired line is drafted into an invoice for 2,354,000 cents while the
        campaign was never funded, so the controller cannot issue the bill.

        PRD: "Funding exactly equal to that total is sufficient; anything less is
        refused with `ERR_CAMPAIGN_FUNDING_INSUFFICIENT`."

        Design: Corner/validations/issuing_an_invoice_the_campaign_has_not_funded_is_rejected
        """
        world = _drafted_invoice_world(api)

        response = api.issue_invoice(world["invoice_id"], None, CONTROLLER_HEADERS)

        validate_error(response, ApiErrorId.CAMPAIGN_FUNDING_INSUFFICIENT, 409)
        invoice = validate_success(api.get_invoice(world["invoice_id"], CONTROLLER_HEADERS))
        assert_invoice_axes(invoice, client_status=InvoiceClientStatus.DRAFT.value)
        assert invoice["version"] == 1, (
            f"a refused issue must not version the invoice, got {invoice['version']}"
        )
        assert_null_instant(invoice, "issued_at")
        assert_null_instant(invoice, "due_date")

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(buy, settlement_status=SettlementStatus.UNBILLED.value)

        campaign = validate_success(api.get_campaign(world["campaign_id"], PLANNER_HEADERS))
        assert_cents(campaign, "funded_cents", 0)


class TestInvoiceIssueReplay:
    """The second issue of the same invoice finds the receivable axis past `DRAFT`."""

    def test_issuing_the_same_invoice_twice_is_rejected(self, api):
        """A bill funded to the cent and already issued on 1 December cannot be
        issued a second time, and its stamped dates stand.

        PRD: "Issuing an invoice that is not `DRAFT` is refused with
        `ERR_INVOICE_NOT_IN_EXPECTED_STATE`."

        Design: Corner/validations/issuing_the_same_invoice_twice_is_rejected
        """
        world = _issued_invoice_world(api)

        response = api.issue_invoice(world["invoice_id"], None, CONTROLLER_HEADERS)

        validate_error(response, ApiErrorId.INVOICE_NOT_IN_EXPECTED_STATE, 409)
        invoice = validate_success(api.get_invoice(world["invoice_id"], CONTROLLER_HEADERS))
        assert_invoice_axes(invoice, client_status=InvoiceClientStatus.ISSUED.value)
        assert invoice["version"] == 2, (
            f"only the first issue may version the invoice, got {invoice['version']}"
        )
        assert_instant_field(invoice, "issued_at", _AFTER_AIR_WINDOW)
        assert_instant_field(invoice, "due_date", _DUE_DATE)

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(buy, settlement_status=SettlementStatus.INVOICED.value)

        advertiser = validate_success(
            api.get_advertiser(world["advertiser_id"], CONTROLLER_HEADERS)
        )
        assert_cents(advertiser, "outstanding_receivable_cents", _NET_PAYABLE_CENTS)


class TestClientPaymentOverpay:
    """A payment one cent above the net payable is refused outright."""

    def test_a_client_payment_above_the_net_payable_is_rejected(self, api):
        """The client tries to settle an issued 2,354,000-cent bill with 2,354,001
        cents, and nothing of the payment is recorded.

        PRD: "The invoice must be at `ISSUED` or `PARTIALLY_PAID`, or the request is
        refused with `ERR_INVOICE_NOT_IN_EXPECTED_STATE`, and a payment may never
        overpay: `client_paid_cents` plus `amount_cents` must be no greater than
        `net_payable_cents`, and exceeding it is refused with
        `ERR_PAYMENT_EXCEEDS_INVOICE`."

        Design: Corner/validations/a_client_payment_above_the_net_payable_is_rejected
        """
        world = _issued_invoice_world(api)

        response = api.record_client_payment(
            world["invoice_id"],
            {"amount_cents": _NET_PAYABLE_CENTS + 1},
            world["client_headers"],
        )

        validate_error(response, ApiErrorId.PAYMENT_EXCEEDS_INVOICE, 422)
        invoice = validate_success(api.get_invoice(world["invoice_id"], CONTROLLER_HEADERS))
        assert_cents(invoice, "client_paid_cents", 0)
        assert_invoice_axes(invoice, client_status=InvoiceClientStatus.ISSUED.value)
        assert_cents(invoice, "max_remittable_cents", 0)
        assert invoice["version"] == 2, (
            f"a refused payment must not version the invoice, got {invoice['version']}"
        )

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(buy, settlement_status=SettlementStatus.INVOICED.value)


class TestApprovalOverCreditLimit:
    """A receivable above the client's limit blocks the next approval."""

    def test_approving_a_second_plan_over_the_credit_limit_is_rejected(self, api):
        """A client with a 1,000,000-cent limit already owes 2,354,000 cents on an
        issued bill, so the brand cannot approve its follow-on plan.

        PRD: "Two financial conditions guard the hop: the advertiser must not be on
        `HOLD` (`ERR_ADVERTISER_CREDIT_HOLD`), and its
        `outstanding_receivable_cents` must be no greater than its
        `credit_limit_cents` — a receivable exactly equal to the limit is
        acceptable, a receivable one cent above it is rejected with
        `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/approving_a_second_plan_over_the_credit_limit_is_rejected
        """
        world = _issued_invoice_world(api, credit_limit_cents=1_000_000)
        follow_on = _second_plan(api, world["advertiser_id"])

        response = api.approve_plan(
            follow_on["campaign_id"], None, world["client_headers"]
        )

        validate_error(response, ApiErrorId.CREDIT_LIMIT_EXCEEDED, 409)
        advertiser = validate_success(
            api.get_advertiser(world["advertiser_id"], CONTROLLER_HEADERS)
        )
        assert_cents(advertiser, "outstanding_receivable_cents", _NET_PAYABLE_CENTS)
        assert advertiser["credit_status"] == CreditStatus.ACTIVE.value, (
            "an over-limit receivable does not by itself move the credit posture, "
            f"got {advertiser['credit_status']}"
        )

        campaign = validate_success(
            api.get_campaign(follow_on["campaign_id"], PLANNER_HEADERS)
        )
        assert_campaign_axes(
            campaign, plan_status=PlanStatus.PENDING_CLIENT_APPROVAL.value
        )

        allocation = validate_success(
            api.get_channel_allocation(follow_on["allocation_id"], PLANNER_HEADERS)
        )
        assert_allocation_posture(allocation, status=AllocationStatus.DRAFT.value)


class TestPlanSubmissionOnCreditHold:
    """A client driven to `HOLD` by two late payments cannot submit a new plan."""

    def test_submitting_a_plan_for_an_advertiser_on_credit_hold_is_rejected(self, api):
        """Two 1,000,000-cent payments made on 5 January against a bill due on
        31 December put the client on `HOLD`, freezing its follow-on submission.

        PRD: "An advertiser on `HOLD` is frozen out of exactly three operations —
        plan submission, plan approval and negotiation acceptance — each of which
        is rejected with `ERR_ADVERTISER_CREDIT_HOLD`."

        Design: Corner/validations/submitting_a_plan_for_an_advertiser_on_credit_hold_is_rejected
        """
        world = _issued_invoice_world(api)
        fx.move_clock(api, _AFTER_DUE_DATE)
        for _ in range(2):
            get_success_data(
                api.record_client_payment(
                    world["invoice_id"],
                    {"amount_cents": 1_000_000},
                    world["client_headers"],
                )
            )
        follow_on = _second_plan(api, world["advertiser_id"], submit=False)

        response = api.submit_plan(follow_on["campaign_id"], None, PLANNER_HEADERS)

        validate_error(response, ApiErrorId.ADVERTISER_CREDIT_HOLD, 403)
        advertiser = validate_success(
            api.get_advertiser(world["advertiser_id"], CONTROLLER_HEADERS)
        )
        assert advertiser["late_payment_count"] == 2, (
            f"expected two late payments, got {advertiser['late_payment_count']}"
        )
        assert advertiser["credit_status"] == CreditStatus.HOLD.value, (
            f"expected the client on HOLD, got {advertiser['credit_status']}"
        )

        invoice = validate_success(api.get_invoice(world["invoice_id"], CONTROLLER_HEADERS))
        assert_cents(invoice, "client_paid_cents", 2_000_000)
        assert_invoice_axes(
            invoice, client_status=InvoiceClientStatus.PARTIALLY_PAID.value
        )
        assert invoice["late_payment_flag"] is True, (
            f"expected the bill flagged late, got {invoice['late_payment_flag']!r}"
        )

        campaign = validate_success(
            api.get_campaign(follow_on["campaign_id"], PLANNER_HEADERS)
        )
        assert_campaign_axes(campaign, plan_status=PlanStatus.DRAFT.value)
        assert campaign["version"] == 2, (
            f"a refused submission must not version the campaign, got {campaign['version']}"
        )


class TestResubmissionWhilePostureIsReplanRequired:
    """The revision loop stays shut while an allocation is still overcommitted."""

    def test_resubmitting_a_plan_while_the_posture_is_replan_required_is_rejected(
        self, api
    ):
        """A 2,354,000-cent buy against a 1,000,000-cent linear allocation pushed the
        plan into revision, and it cannot be re-submitted before the release.

        PRD: "A campaign sitting at `REVISION_REQUIRED` may be re-submitted, moving
        `REVISION_REQUIRED → PENDING_CLIENT_APPROVAL`, but only once the
        overcommitment that forced the revision has actually been released or
        re-allocated: the campaign's `plan_posture` must read `WITHIN_PLAN`, and a
        re-submission attempted while it still reads `REPLAN_REQUIRED` is rejected
        with `ERR_PLAN_POSTURE_REPLAN_REQUIRED`."

        Design: Corner/validations/resubmitting_a_plan_while_the_posture_is_replan_required_is_rejected
        """
        world = _placed_world(
            api,
            allocations=[dict(_THIN_LINEAR_ALLOCATION), dict(_FAT_CTV_ALLOCATION)],
        )

        response = api.submit_plan(world["campaign_id"], None, PLANNER_HEADERS)

        validate_error(response, ApiErrorId.PLAN_POSTURE_REPLAN_REQUIRED, 409)
        campaign = validate_success(api.get_campaign(world["campaign_id"], PLANNER_HEADERS))
        assert_campaign_axes(
            campaign,
            plan_status=PlanStatus.REVISION_REQUIRED.value,
            plan_posture=PlanPosture.REPLAN_REQUIRED.value,
        )

        overcommitted = validate_success(
            api.get_channel_allocation(world["allocation_ids"][0], PLANNER_HEADERS)
        )
        assert_allocation_posture(
            overcommitted,
            status=AllocationStatus.DRAFT.value,
            posture=AllocationPosture.OVERCOMMITTED.value,
        )
        assert_cents(overcommitted, "committed_cents", _GROSS_COST_CENTS)

        untouched = validate_success(
            api.get_channel_allocation(world["allocation_ids"][1], PLANNER_HEADERS)
        )
        assert_allocation_posture(
            untouched,
            status=AllocationStatus.DRAFT.value,
            posture=AllocationPosture.WITHIN_PLAN.value,
        )

        buy = validate_success(api.get_buy(world["buy_id"], BUYER_HEADERS))
        assert_buy_axes(buy, buy_status=BuyStatus.PLACED.value)


def _place_the_covered_buy(api):
    """Places the fully covering buy on the whole-plan linear allocation."""
    world = _planned_world(api)
    version = get_success_data(api.get_campaign(world["campaign_id"], BUYER_HEADERS))[
        "version"
    ]
    response = api.place_buy(
        world["buy_id"], {"expected_campaign_version": version}, BUYER_HEADERS
    )
    return world, response


class TestCoveredPlacementInsideBudget:
    """The placement that clears every guard: covered, funded room, no cascade."""

    def test_placing_a_covered_buy_inside_budget_succeeds(self, api):
        """The buyer places a 2,354,000-cent buy carrying its full guarantee against
        a 10,000,000-cent plan, and the buy records who placed it.

        PRD: "A successful placement moves `buy_status` `PENDING_PLACEMENT → PLACED`,
        records the acting `X-User-ID` as `placed_by_user_id` on the buy, and
        increments the campaign's `version` by 1."

        Design: Corner/validations/placing_a_covered_buy_inside_budget_succeeds
        """
        world, response = _place_the_covered_buy(api)

        buy = validate_success(response, 200)
        assert_buy_axes(buy, buy_status=BuyStatus.PLACED.value)
        assert buy["placed_by_user_id"] == BUYER_USER_ID, (
            f"expected the acting buyer recorded, got {buy['placed_by_user_id']!r}"
        )

        campaign = validate_success(api.get_campaign(world["campaign_id"], PLANNER_HEADERS))
        assert campaign["version"] == 5, (
            f"expected the fifth version of the campaign, got {campaign['version']}"
        )

    def test_the_placed_buy_carries_its_whole_guarantee(self, api):
        """The single ordered line projects exactly the 1,000,000 impressions the buy
        guarantees, which is why the coverage guard lets the placement through.

        PRD: "Coverage exactly equal to the guarantee is sufficient; anything less is
        refused with `ERR_UNIT_COVERAGE_SHORT`."

        Design: Corner/validations/placing_a_covered_buy_inside_budget_succeeds
        """
        _world, response = _place_the_covered_buy(api)

        buy = validate_success(response, 200)
        assert_impressions(buy, "placed_impressions", _GUARANTEED_IMPRESSIONS)
        assert_impressions(buy, "guaranteed_impressions", _GUARANTEED_IMPRESSIONS)

    def test_the_covered_placement_leaves_the_plan_within_plan(self, api):
        """The 2,354,000 cents committed sit under the 10,000,000 cents allocated, so
        the cascade stops at the first link and the plan stays approved and locked.

        PRD: "This link does not fire while `committed_cents` remains at or below
        `allocated_cents`, and when it does not fire the chain stops here."

        Design: Corner/validations/placing_a_covered_buy_inside_budget_succeeds
        """
        world, response = _place_the_covered_buy(api)
        validate_success(response, 200)

        allocation = validate_success(
            api.get_channel_allocation(world["allocation_id"], PLANNER_HEADERS)
        )
        assert_cents(allocation, "committed_cents", _GROSS_COST_CENTS)
        assert_allocation_posture(
            allocation,
            status=AllocationStatus.LOCKED.value,
            posture=AllocationPosture.WITHIN_PLAN.value,
        )

        campaign = validate_success(api.get_campaign(world["campaign_id"], PLANNER_HEADERS))
        assert_campaign_axes(
            campaign,
            plan_status=PlanStatus.APPROVED.value,
            plan_posture=PlanPosture.WITHIN_PLAN.value,
        )

    def test_the_covered_placement_recomputes_the_budget_ledger(self, api):
        """Placement books 2,354,000 cents of the 10,000,000-cent budget and leaves
        7,646,000 cents of it uncommitted.

        PRD: "Independently of whether links 2 through 4 fire, placement recomputes
        the campaign's `committed_gross_cents` and `uncommitted_budget_cents`."

        Design: Corner/validations/placing_a_covered_buy_inside_budget_succeeds
        """
        world, response = _place_the_covered_buy(api)
        validate_success(response, 200)

        campaign = validate_success(api.get_campaign(world["campaign_id"], PLANNER_HEADERS))
        assert_cents(campaign, "committed_gross_cents", _GROSS_COST_CENTS)
        assert_cents(campaign, "uncommitted_budget_cents", _UNCOMMITTED_BUDGET_CENTS)
        assert_cents(campaign, "total_budget_cents", _TOTAL_BUDGET_CENTS)
